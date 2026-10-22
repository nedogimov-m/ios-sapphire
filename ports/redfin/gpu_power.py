"""Translate the exact live Redfin CX parent chain into a power-test contract."""
import struct
from ports.redfin import mkadt


def add_contract(tree, nodes):
    def need(path, key, value):
        if nodes.get(path, {}).get(key) != value:
            raise ValueError(f'GPU CX power FDT mismatch: {path} {key}')

    cx = '/soc/qcom,gdsc@3d9106c'
    status = '/soc/syscon@3d91540'
    arc = '/soc/rsc@18200000/rpmh-regulator-cxlvl'
    parent = arc + '/regulator-pm8150-s1-level'
    phandle = nodes.get(parent, {}).get('phandle', b'')
    hardware = nodes.get(status, {}).get('phandle', b'')
    if any(len(value) != 4 or not int.from_bytes(value, 'big') for value in (phandle, hardware)):
        raise ValueError('GPU CX parent/status phandles missing')
    need(cx, 'compatible', b'qcom,gdsc\0')
    need(cx, 'reg', struct.pack('>II', 0x3d9106c, 4))
    need(cx, 'parent-supply', phandle)
    need(cx, 'vdd_parent-supply', phandle)
    need(cx, 'hw-ctrl-addr', hardware)
    need(cx, 'qcom,gds-timeout', struct.pack('>I', 500))
    need(cx, 'qcom,clk-dis-wait-val', struct.pack('>I', 8))
    need(status, 'compatible', b'syscon\0')
    need(status, 'reg', struct.pack('>II', 0x3d91540, 4))
    need(arc, 'compatible', b'qcom,rpmh-arc-regulator\0')
    need(arc, 'qcom,resource-name', b'cx.lvl\0')
    need(parent, 'qcom,set', struct.pack('>I', 3))
    need(parent, 'regulator-min-microvolt', struct.pack('>I', 16))
    need(parent, 'regulator-max-microvolt', struct.pack('>I', 65535))
    if any(child.name == 'redfin-gpu-power' for child in tree.children):
        raise ValueError('duplicate GPU power contract')
    tree.children.append(mkadt.node('redfin-gpu-power', [
        ('reg', mkadt.u64(0x3d9106c, 4, 0x3d91540, 4, 0x18220000, 0x10000, 0x80860000, 0x20000)),
        ('cx-parent', mkadt.u32(0x30000, 64, 65535, 7, 416)),
        ('chip-id', mkadt.u32(0x06020001))]))
