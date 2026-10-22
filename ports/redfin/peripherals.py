"""Translate only verified Redfin FDT contracts into opt-in observer ADT nodes."""
import struct
from ports.redfin import mkadt


def add_observers(root, nodes, *, touch=False, usb=False, gpu=False, wifi=False,
                  usb_route=False, rpmh=False):
    if not (touch or usb or gpu or wifi or usb_route or rpmh):
        return

    def require(path, key, wanted):
        if nodes.get(path, {}).get(key) != wanted:
            raise ValueError(f'peripheral FDT mismatch: {path} {key}')

    gcc = '/soc/qcom,gcc@100000'
    require(gcc, 'reg', struct.pack('>II', 0x100000, 0x1f0000))
    if b'qcom,gcc-lito' not in nodes[gcc].get('compatible', b'').split(b'\0'):
        raise ValueError('peripheral GCC must be Lito')
    names = {child.name for child in root.children}
    if names.intersection({'redfin-touch', 'redfin-gpu', 'redfin-wifi',
                           'redfin-usb-route', 'redfin-rpmh'}):
        raise ValueError('peripheral observer nodes already present')
    pending = []
    if usb or usb_route:
        require('/soc/ssusb@a600000/dwc3@a600000', 'reg', struct.pack('>II', 0xa600000, 0xcd00))
        require('/soc/ssusb@a600000/dwc3@a600000', 'compatible', b'snps,dwc3\0')
    if usb_route:
        apps, host = '/soc/apps-smmu@15000000', '/soc/ssusb@a600000'
        require(apps, 'compatible', b'qcom,qsmmu-v500\0')
        require(apps, 'reg', struct.pack('>IIII', 0x15000000, 0x100000, 0x15182000, 0x20))
        require(apps, 'qcom,skip-init', b'')
        if 'qcom,secure-cfg-access' in nodes[apps]:
            raise ValueError('peripheral SMMU secure configuration alias unsupported')
        phandle = nodes[apps].get('phandle', b'')
        if len(phandle) != 4 or not int.from_bytes(phandle, 'big'):
            raise ValueError('peripheral SMMU phandle missing')
        require(host, 'iommus', phandle + struct.pack('>II', 0xe0, 0))
        require(host, 'qcom,iommu-dma-addr-pool', struct.pack('>II', 0x90000000, 0x60000000))
        pending.append(mkadt.node('redfin-usb-route', [
            ('reg', mkadt.u64(0x15000000, 0x100000)), ('stream-id', mkadt.u32(0xe0)),
        ]))
    if rpmh:
        db = '/reserved-memory/reserved-memory@80860000'
        rsc = '/soc/rsc@18200000'
        require(db, 'reg', struct.pack('>QQ', 0x80860000, 0x20000))
        require(db, 'compatible', b'qcom,cmd-db\0')
        require(db, 'no-map', b'')
        require(rsc, 'reg', struct.pack('>IIIIII', 0x18200000, 0x10000,
                                       0x18210000, 0x10000, 0x18220000, 0x10000))
        require(rsc, 'reg-names', b'drv-0\0drv-1\0drv-2\0')
        require(rsc, 'qcom,drv-id', struct.pack('>I', 2))
        require(rsc, 'qcom,tcs-config', struct.pack('>8I', 2, 2, 0, 3, 1, 3, 3, 1))
        pending.append(mkadt.node('redfin-rpmh', [
            ('reg', mkadt.u64(0x80860000, 0x20000, 0x18220000, 0x10000)),
        ]))
    if touch:
        se, screen, tlmm = '/soc/spi@880000', '/soc/spi@880000/touchscreen@0', '/soc/pinctrl@f000000'
        for path, key, wanted in (
            (se, 'reg', struct.pack('>II', 0x880000, 0x4000)),
            (se, 'compatible', b'qcom,spi-geni\0'),
            (tlmm, 'reg', struct.pack('>II', 0xf000000, 0x1000000)),
            (tlmm, 'compatible', b'qcom,lito-pinctrl\0'),
            (screen, 'compatible', b'sec,sec_ts\0'),
            (screen, 'reg', struct.pack('>I', 0)),
            (screen, 'spi-cpol', b''), (screen, 'spi-cpha', b''),
            (screen, 'spi-max-frequency', struct.pack('>I', 10000000)),
            (screen, 'sec,max_coords', struct.pack('>II', 1080, 2340)),
            (screen, 'interrupts', struct.pack('>II', 9, 8)),
        ):
            require(path, key, wanted)
        phandle = nodes[tlmm].get('phandle', b'')
        if len(phandle) != 4 or not int.from_bytes(phandle, 'big'):
            raise ValueError('peripheral TLMM phandle missing')
        require(screen, 'interrupt-parent', phandle)
        for key, pin in (('sec,reset_gpio', 8), ('sec,irq_gpio', 9), ('sec,switch_gpio', 35)):
            require(screen, key, phandle + struct.pack('>II', pin, 0))
        pending.append(mkadt.node('redfin-touch', [
            ('compatible', mkadt.cstr('redfin,sec-touch')),
            ('reg', mkadt.u64(0x100000, 0x1f0000, 0x880000, 0x4000, 0xf000000, 0x1000000)),
            ('spi-mode', mkadt.u32(3)), ('chip-select', mkadt.u32(0)),
            ('spi-max-frequency', mkadt.u32(10000000)),
            ('touch-gpios', mkadt.u32(8, 9, 35)), ('touch-size', mkadt.u32(1080, 2340)),
        ]))
    if gpu:
        require('/soc/qcom,gpucc@3d90000', 'reg', struct.pack('>II', 0x3d90000, 0x9000))
        require('/soc/qcom,kgsl-3d0@3d00000', 'qcom,chipid', struct.pack('>I', 0x06020001))
        pending.append(mkadt.node('redfin-gpu', [
            ('reg', mkadt.u64(0x100000, 0x1f0000, 0x3d90000, 0x9000)),
            ('chip-id', mkadt.u32(0x06020001)),
        ]))
    if wifi:
        smem = '/reserved-memory/smem_region@80900000'
        require(smem, 'reg', struct.pack('>QQ', 0x80900000, 0x200000))
        require(smem, 'no-map', b'')
        require('/soc/qcom,smem', 'compatible', b'qcom,smem\0')
        phandle = nodes[smem].get('phandle', b'')
        if len(phandle) != 4 or not int.from_bytes(phandle, 'big'):
            raise ValueError('peripheral SMEM reservation phandle missing')
        require('/soc/qcom,smem', 'memory-region', phandle)
        pending.append(mkadt.node('redfin-wifi', [
            ('reg', mkadt.u64(0x80900000, 0x200000)),
            ('reserved-memory-verified', mkadt.u32(1)),
        ]))
    root.children.extend(pending)
