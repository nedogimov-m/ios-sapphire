"""Exact synthetic live-FDT binding for Redfin MPSS/AOP/SMP2P prerequisites."""
import copy
import struct
import unittest

from memory import _tree
import wifi_platform as P
from test_wifi_firmware import fdt


def words(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def fixture(changes=None):
    mss = '/soc/qcom,mss@4080000'
    rsc = '/soc/rsc@18200000'
    smp = '/soc/qcom,smp2p-mpss'
    extra = [
        (rsc, {'compatible': b'qcom,rpmh-rsc\0', 'reg': words(0x18200000, 0x10000, 0x18210000, 0x10000,
                                                          0x18220000, 0x10000),
               'qcom,drv-id': words(2), 'qcom,tcs-config': words(2, 2, 0, 3, 1, 3, 3, 1)}),
        (rsc + '/qcom,rpmhclk', {'compatible': b'qcom,lito-rpmh-clk\0', '#clock-cells': words(1), 'phandle': words(6)}),
        (rsc + '/rpmh-regulator-cxlvl', {'compatible': b'qcom,rpmh-arc-regulator\0', 'qcom,resource-name': b'cx.lvl\0'}),
        (rsc + '/rpmh-regulator-cxlvl/regulator-pm8150-s1-level', {
            'qcom,set': words(3), 'regulator-min-microvolt': words(16),
            'regulator-max-microvolt': words(65535), 'phandle': words(10)}),
        (rsc + '/rpmh-regulator-msslvl', {'compatible': b'qcom,rpmh-arc-regulator\0', 'qcom,resource-name': b'mss.lvl\0'}),
        (rsc + '/rpmh-regulator-msslvl/regulator-pm8150-s8', {
            'qcom,set': words(3), 'regulator-min-microvolt': words(16),
            'regulator-max-microvolt': words(65535), 'phandle': words(11)}),
        ('/soc/qcom,ipcc@408000', {'compatible': b'qcom,ipcc\0', 'reg': words(0x408000, 0x1000),
                                  '#mbox-cells': words(2), '#interrupt-cells': words(3),
                                  'interrupts': words(0, 229, 4), 'phandle': words(8)}),
        ('/soc/qcom,qmp-aop@c300000', {'compatible': b'qcom,qmp-mbox\0', 'reg': words(0xc300000, 0x1000),
                                     'mbox-desc-offset': words(0), '#mbox-cells': words(1),
                                     'mboxes': words(8, 0, 0), 'interrupt-parent': words(8),
                                     'interrupts': words(0, 0, 1), 'phandle': words(9)}),
        (smp, {'compatible': b'qcom,smp2p\0', 'qcom,smem': words(435, 428),
               'qcom,local-pid': words(0), 'qcom,remote-pid': words(1),
               'mboxes': words(8, 2, 2), 'interrupt-parent': words(8), 'interrupts': words(2, 2, 1)}),
        (smp + '/master-kernel', {'qcom,entry-name': b'master-kernel\0',
                                  '#qcom,smem-state-cells': words(1), 'phandle': words(12)}),
        (smp + '/slave-kernel', {'qcom,entry-name': b'slave-kernel\0',
                                 '#interrupt-cells': words(2), 'interrupt-controller': b'', 'phandle': words(13)}),
        ('/reserved-memory/reserved-memory@80860000', {'compatible': b'qcom,cmd-db\0',
                                                       'reg': struct.pack('>QQ', 0x80860000, 0x20000), 'no-map': b''}),
    ]
    attributes = {
        '/soc': {'#address-cells': words(1), '#size-cells': words(1), 'ranges': words(0, 0, 0, 0xffffffff)},
        mss: {'reg': words(0x4080000, 0x100), 'qcom,proxy-reg-names': b'vdd_cx\0vdd_mss\0',
              'qcom,vdd_cx-uV-uA': words(384, 100000), 'qcom,vdd_mss-uV-uA': words(384, 100000),
              'vdd_cx-supply': words(10), 'vdd_mss-supply': words(11),
              'clock-names': b'xo\0', 'qcom,proxy-clock-names': b'xo\0', 'clocks': words(6, 0),
              'mboxes': words(9, 0), 'qcom,smem-states': words(12, 0), 'qcom,smem-state-names': b'qcom,force-stop\0'},
    }
    for path, properties in (changes or {}).items():
        attributes.setdefault(path, {}).update(properties)
    return fdt(changes=attributes, extra=extra)


class WifiPlatformTests(unittest.TestCase):
    def test_native_contract_resolves_actual_roles_without_fixed_phandle_numbers(self):
        result = P.live_contract(fixture(), 0x180000000, 0x80000000)
        self.assertEqual(result['pas_id'], 4)
        self.assertEqual(result['probe_ranges'], P.PROBE_RANGES)
        self.assertEqual(result['proxy']['cx_consumer_level'], 384)
        self.assertEqual(result['proxy']['mss_consumer_level'], 384)
        self.assertEqual(result['proxy']['xo_arc_data'], 3)
        self.assertEqual(result['smp2p']['incoming_item'], 435)
        self.assertEqual(result['smp2p']['outgoing_item'], 428)
        self.assertFalse(result['power_proven'])
        self.assertFalse(result['hardware_started'])

    def test_all_required_observed_properties_fail_closed_on_single_bit_changes(self):
        nodes = _tree(fixture())[0]
        # Mutation of each property checked by the contract must reject. This
        # exercises topology and ABI binding, without introducing hardware I/O.
        inspected = [
            ('/soc', '#address-cells'), ('/soc', '#size-cells'), ('/soc', 'ranges'),
            ('/soc/qcom,mss@4080000', 'reg'), ('/soc/qcom,mss@4080000', 'qcom,pas-id'),
            ('/soc/qcom,mss@4080000', 'qcom,vdd_cx-uV-uA'),
            ('/soc/qcom,mss@4080000', 'qcom,vdd_mss-uV-uA'),
            ('/soc/qcom,mss@4080000', 'vdd_cx-supply'), ('/soc/qcom,mss@4080000', 'vdd_mss-supply'),
            ('/soc/qcom,mss@4080000', 'clocks'), ('/soc/qcom,mss@4080000', 'mboxes'),
            ('/soc/qcom,mss@4080000', 'qcom,smem-states'),
            ('/soc/qcom,qmp-aop@c300000', 'reg'), ('/soc/qcom,qmp-aop@c300000', 'mbox-desc-offset'),
            ('/soc/qcom,qmp-aop@c300000', 'mboxes'), ('/soc/qcom,qmp-aop@c300000', 'interrupts'),
            ('/soc/qcom,ipcc@408000', 'reg'), ('/soc/qcom,ipcc@408000', 'interrupts'),
            ('/soc/qcom,smp2p-mpss', 'qcom,smem'), ('/soc/qcom,smp2p-mpss', 'qcom,remote-pid'),
            ('/soc/qcom,smp2p-mpss', 'mboxes'), ('/soc/qcom,smp2p-mpss', 'interrupts'),
            ('/soc/rsc@18200000', 'qcom,drv-id'), ('/soc/rsc@18200000', 'qcom,tcs-config'),
            ('/soc/rsc@18200000', 'reg'),
            ('/soc/rsc@18200000/rpmh-regulator-cxlvl', 'qcom,resource-name'),
            ('/soc/rsc@18200000/rpmh-regulator-msslvl', 'qcom,resource-name'),
        ]
        for path, key in inspected:
            for bit in range(len(nodes[path][key]) * 8):
                changed = copy.deepcopy(nodes)
                value = bytearray(changed[path][key])
                value[bit // 8] ^= 1 << (bit % 8)
                changed[path][key] = bytes(value)
                with self.subTest(path=path, key=key, bit=bit), self.assertRaises(ValueError):
                    P.contract(changed)

    def test_disabled_dependencies_missing_aop_and_bad_cmd_db_never_admitted(self):
        changes = [
            {'/soc/qcom,mss@4080000': {'qcom,signal-aop': None}},
            {'/soc/qcom,qmp-aop@c300000': {'status': b'disabled\0'}},
            {'/soc/rsc@18200000/qcom,rpmhclk': {'status': b'disabled\0'}},
            {'/reserved-memory/reserved-memory@80860000': {'no-map': None}},
            {'/reserved-memory/reserved-memory@80860000': {'reg': struct.pack('>QQ', 0x80860000, 0x10000)}},
            {'/reserved-memory/reserved-memory@80860000': {'reusable': b''}},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                P.live_contract(fixture(change), 0x180000000, 0x80000000)

    def test_proxy_supplies_require_both_active_sleep_and_declared_consumer_range(self):
        supply = '/soc/rsc@18200000/rpmh-regulator-msslvl/regulator-pm8150-s8'
        for key, value in [('qcom,set', words(1)), ('regulator-min-microvolt', words(64)),
                           ('regulator-max-microvolt', words(384))]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                P.live_contract(fixture({supply: {key: value}}), 0x180000000, 0x80000000)

    def test_duplicate_or_crossed_role_phandles_and_unsafe_ram_refused(self):
        for change in ({'/soc/qcom,mss@4080000': {'vdd_cx-supply': words(11)}},
                       {'/soc/qcom,qmp-aop@c300000': {'phandle': words(8)}},
                       {'/soc/qcom,smp2p-mpss': {'qcom,smem': words(428, 435)}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                P.live_contract(fixture(change), 0x180000000, 0x80000000)
        with self.assertRaises(ValueError):
            P.live_contract(fixture(), 0x8c000000, 0x4000)

    def test_adt_probe_contract_is_exact_and_duplicate_insertion_fails(self):
        root = P.mkadt.node('/', [])
        nodes = _tree(fixture())[0]
        P.add_probe_contract(root, nodes)
        self.assertEqual([child.name for child in root.children], ['redfin-wifi-native'])
        properties = {name: value for name, _flags, value in root.children[0].props}
        self.assertEqual(properties['reg'], P.mkadt.u64(*(value for pair in P.PROBE_RANGES for value in pair)))
        self.assertEqual(properties['source-contract'], P.mkadt.u32(*P.WITNESS))
        self.assertEqual(properties['live-fdt-verified'], P.mkadt.u32(1))
        with self.assertRaises(ValueError):
            P.add_probe_contract(root, nodes)


if __name__ == '__main__':
    unittest.main()
