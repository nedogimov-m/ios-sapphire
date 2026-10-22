"""Reject changed physical buses and pin assignments before emitting ADT."""
import struct
import unittest

from peripherals import add_observers, mkadt


def cells(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def fixture():
    return {
        '/soc/qcom,gcc@100000': {'reg': cells(0x100000, 0x1f0000), 'compatible': b'qcom,gcc-lito\0syscon\0'},
        '/soc/qcom,gpucc@3d90000': {'reg': cells(0x3d90000, 0x9000)},
        '/soc/qcom,kgsl-3d0@3d00000': {'qcom,chipid': cells(0x06020001)},
        '/soc/ssusb@a600000/dwc3@a600000': {'reg': cells(0xa600000, 0xcd00), 'compatible': b'snps,dwc3\0'},
        '/soc/spi@880000': {'reg': cells(0x880000, 0x4000), 'compatible': b'qcom,spi-geni\0'},
        '/soc/pinctrl@f000000': {'reg': cells(0xf000000, 0x1000000), 'compatible': b'qcom,lito-pinctrl\0', 'phandle': cells(25)},
        '/soc/spi@880000/touchscreen@0': {
            'compatible': b'sec,sec_ts\0', 'reg': cells(0), 'spi-cpol': b'', 'spi-cpha': b'',
            'spi-max-frequency': cells(10000000), 'sec,max_coords': cells(1080, 2340),
            'interrupts': cells(9, 8), 'interrupt-parent': cells(25),
            'sec,reset_gpio': cells(25, 8, 0), 'sec,irq_gpio': cells(25, 9, 0),
            'sec,switch_gpio': cells(25, 35, 0),
        },
        '/reserved-memory/smem_region@80900000': {
            'reg': struct.pack('>QQ', 0x80900000, 0x200000), 'no-map': b'', 'phandle': cells(107),
        },
        '/soc/qcom,smem': {'compatible': b'qcom,smem\0', 'memory-region': cells(107)},
        '/soc/apps-smmu@15000000': {
            'reg': cells(0x15000000, 0x100000, 0x15182000, 0x20),
            'compatible': b'qcom,qsmmu-v500\0', 'qcom,skip-init': b'', 'phandle': cells(24),
        },
        '/soc/ssusb@a600000': {'iommus': cells(24, 0xe0, 0),
                             'qcom,iommu-dma-addr-pool': cells(0x90000000, 0x60000000)},
        '/reserved-memory/reserved-memory@80860000': {
            'reg': struct.pack('>QQ', 0x80860000, 0x20000),
            'compatible': b'qcom,cmd-db\0', 'no-map': b'',
        },
        '/soc/rsc@18200000': {
            'reg': cells(0x18200000, 0x10000, 0x18210000, 0x10000, 0x18220000, 0x10000),
            'reg-names': b'drv-0\0drv-1\0drv-2\0', 'qcom,drv-id': cells(2),
            'qcom,tcs-config': cells(2, 2, 0, 3, 1, 3, 3, 1),
        },
    }


class PeripheralContracts(unittest.TestCase):
    def root(self):
        return mkadt.build(0x180000000, 0x80000000, seed=bytes(64))

    def test_disabled_does_not_need_hardware_or_change_tree(self):
        root = self.root()
        before = mkadt.adt.serialize(root)
        add_observers(root, {})
        self.assertEqual(mkadt.adt.serialize(root), before)

    def test_bypass_context_contract_requires_native_nonstatic_ns_usb(self):
        nodes = fixture()
        host, apps = '/soc/ssusb@a600000', '/soc/apps-smmu@15000000'
        nodes[host]['qcom,iommu-dma'] = b'atomic\0'
        root = self.root()
        add_observers(root, nodes, usb_bypass=True)
        route = next(child for child in root.children if child.name == 'redfin-usb-route')
        self.assertEqual(route.prop('ns-context-allocator'), mkadt.u32(1))
        root = self.root()
        add_observers(root, nodes, usb_route=True)
        route = next(child for child in root.children if child.name == 'redfin-usb-route')
        self.assertIsNone(route.prop('ns-context-allocator'))
        for path, key, value in ((host, 'qcom,iommu-dma', b'dynamic\0'),
                                 (host, 'qcom,iommu-vmid', cells(1)),
                                 (apps, 'qcom,enable-static-cb', b''),
                                 (apps, 'calxeda,smmu-secure-config-access', b''),
                                 (apps, 'qcom,secure-cfg-access', b'')):
            with self.subTest(key=key):
                changed = {path: props.copy() for path, props in nodes.items()}
                changed[path][key] = value
                root = self.root()
                before = mkadt.adt.serialize(root)
                with self.assertRaises(ValueError):
                    add_observers(root, changed, usb_bypass=True)
                self.assertEqual(mkadt.adt.serialize(root), before)

    def test_verified_buses_produce_only_requested_contracts(self):
        root = self.root()
        add_observers(root, fixture(), touch=True, usb=True, gpu=True)
        data = mkadt.adt.serialize(root)
        parsed, end = mkadt.adt.parse(data)
        children = {node.name: node for node in parsed.children}
        self.assertEqual(end, len(data))
        self.assertEqual(children['redfin-gpu'].prop('chip-id'), mkadt.u32(0x06020001))
        self.assertEqual(children['redfin-touch'].prop('touch-gpios'), mkadt.u32(8, 9, 35))
        self.assertEqual(len(children['redfin-touch'].prop('reg')), 48)

    def test_altered_touch_wiring_rejected(self):
        path = '/soc/spi@880000/touchscreen@0'
        for key, value in (('sec,reset_gpio', cells(25, 9, 0)),
                           ('interrupt-parent', cells(26)), ('spi-cpha', cells(1)),
                           ('spi-max-frequency', cells(50000000)), ('sec,max_coords', cells(1080, 2400))):
            with self.subTest(key=key):
                nodes = fixture()
                nodes[path][key] = value
                root = self.root()
                before = mkadt.adt.serialize(root)
                with self.assertRaises(ValueError):
                    add_observers(root, nodes, touch=True)
                self.assertEqual(mkadt.adt.serialize(root), before)

    def test_other_bus_addresses_and_chips_rejected_atomically(self):
        for path, key, value in (
            ('/soc/qcom,gcc@100000', 'reg', cells(0x1400000, 0x1f0000)),
            ('/soc/ssusb@a600000/dwc3@a600000', 'reg', cells(0x4e00000, 0xcd00)),
            ('/soc/qcom,kgsl-3d0@3d00000', 'qcom,chipid', cells(0x06010001)),
        ):
            nodes = fixture()
            nodes[path][key] = value
            root = self.root()
            before = mkadt.adt.serialize(root)
            with self.assertRaises(ValueError):
                add_observers(root, nodes, touch=True, usb=True, gpu=True)
            self.assertEqual(mkadt.adt.serialize(root), before)

    def test_reapplying_refused(self):
        root = self.root()
        add_observers(root, fixture(), touch=True)
        with self.assertRaises(ValueError):
            add_observers(root, fixture(), touch=True)

    def test_wifi_requires_exact_no_map_reservation_and_phandle(self):
        root = self.root()
        add_observers(root, fixture(), wifi=True)
        node = next(node for node in root.children if node.name == 'redfin-wifi')
        self.assertEqual(node.prop('reg'), mkadt.u64(0x80900000, 0x200000))
        for path, key, value in (
            ('/reserved-memory/smem_region@80900000', 'reg', struct.pack('>QQ', 0x46000000, 0x200000)),
            ('/reserved-memory/smem_region@80900000', 'no-map', None),
            ('/soc/qcom,smem', 'memory-region', cells(108)),
        ):
            nodes = fixture()
            nodes[path][key] = value
            root = self.root()
            before = mkadt.adt.serialize(root)
            with self.assertRaises(ValueError):
                add_observers(root, nodes, touch=True, wifi=True)
            self.assertEqual(mkadt.adt.serialize(root), before)

    def test_usb_route_and_rpmh_require_exact_handoff_layout(self):
        root = self.root()
        add_observers(root, fixture(), usb_route=True, rpmh=True)
        nodes = {node.name: node for node in root.children}
        self.assertEqual(nodes['redfin-usb-route'].prop('stream-id'), mkadt.u32(0xe0))
        self.assertEqual(nodes['redfin-rpmh'].prop('reg'),
                         mkadt.u64(0x80860000, 0x20000, 0x18220000, 0x10000))
        for path, key, value in (
            ('/soc/ssusb@a600000', 'iommus', cells(24, 0x1a0, 0)),
            ('/soc/apps-smmu@15000000', 'qcom,secure-cfg-access', b''),
            ('/soc/rsc@18200000', 'qcom,drv-id', cells(0)),
            ('/soc/rsc@18200000', 'qcom,tcs-config', cells(2, 3, 0, 2, 1, 3, 3, 1)),
            ('/reserved-memory/reserved-memory@80860000', 'no-map', None),
        ):
            raw = fixture()
            raw[path][key] = value
            root = self.root()
            before = mkadt.adt.serialize(root)
            with self.assertRaises(ValueError):
                add_observers(root, raw, usb_route=True, rpmh=True)
            self.assertEqual(mkadt.adt.serialize(root), before)


if __name__ == '__main__':
    unittest.main()
