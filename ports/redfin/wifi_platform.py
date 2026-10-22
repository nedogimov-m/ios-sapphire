#!/usr/bin/env python3
"""Bind native MPSS prerequisites to the exact live Redfin FDT, without I/O."""
import argparse
import json
from pathlib import Path
import struct

if __package__:
    from . import mkadt
    from .memory import _tree
    from .wifi_firmware import live_layout, read_regular
else:
    import mkadt
    from memory import _tree
    from wifi_firmware import live_layout, read_regular

PROBE_RANGES = ((0x0c300000, 0x1000), (0x80900000, 0x200000), (0x80860000, 0x20000))
# ABI version, PAS, CX/MSS consumer levels, XO ARC data, inbound/outbound SMP2P
# IDs, remote PID, AOP/MPSS notification IDs, ready bit and stop-ack bit.
WITNESS = (1, 4, 384, 384, 3, 435, 428, 1, 0, 0x00020002, 1, 3)


def contract(nodes):
    def need(path, key, expected):
        if nodes.get(path, {}).get(key) != expected:
            raise ValueError(f'native MPSS live FDT mismatch: {path} {key}')

    def words(*values):
        return struct.pack('>' + 'I' * len(values), *values)

    handles = {}
    for path, props in nodes.items():
        for key in ('phandle', 'linux,phandle'):
            if key not in props:
                continue
            value = props[key]
            if (len(value) != 4 or int.from_bytes(value, 'big') in (0, 0xffffffff) or
                    (value in handles and handles[value] != path)):
                raise ValueError('native MPSS requires unique valid live phandles')
            handles[value] = path
        if 'phandle' in props and 'linux,phandle' in props:
            if props['phandle'] != props['linux,phandle']:
                raise ValueError('native MPSS phandle aliases disagree')

    def handle(path):
        props = nodes.get(path, {})
        value = props.get('phandle', props.get('linux,phandle', b''))
        if handles.get(value) != path:
            raise ValueError(f'native MPSS phandle absent: {path}')
        return value

    mss = '/soc/qcom,mss@4080000'
    qmp = '/soc/qcom,qmp-aop@c300000'
    ipcc = '/soc/qcom,ipcc@408000'
    smp2p = '/soc/qcom,smp2p-mpss'
    master, slave = smp2p + '/master-kernel', smp2p + '/slave-kernel'
    rsc = '/soc/rsc@18200000'
    clock = rsc + '/qcom,rpmhclk'
    cx = rsc + '/rpmh-regulator-cxlvl'
    mss_level = rsc + '/rpmh-regulator-msslvl'
    cx_supply = cx + '/regulator-pm8150-s1-level'
    mss_supply = mss_level + '/regulator-pm8150-s8'
    need('/soc', '#address-cells', words(1))
    need('/soc', '#size-cells', words(1))
    need('/soc', 'ranges', words(0, 0, 0, 0xffffffff))
    for path in (mss, qmp, ipcc, smp2p, rsc, clock, cx, mss_level, cx_supply, mss_supply):
        if nodes.get(path, {}).get('status', b'okay\0') not in (b'okay\0', b'ok\0'):
            raise ValueError('native MPSS prerequisite is disabled')
    need(mss, 'compatible', b'qcom,pil-tz-generic\0')
    need(mss, 'reg', words(0x04080000, 0x100))
    need(mss, 'qcom,pas-id', words(4))
    need(mss, 'qcom,firmware-name', b'modem\0')
    need(mss, 'qcom,signal-aop', b'')
    need(mss, 'qcom,proxy-reg-names', b'vdd_cx\0vdd_mss\0')
    need(mss, 'qcom,vdd_cx-uV-uA', words(384, 100000))
    need(mss, 'qcom,vdd_mss-uV-uA', words(384, 100000))
    need(mss, 'vdd_cx-supply', handle(cx_supply))
    need(mss, 'vdd_mss-supply', handle(mss_supply))
    need(mss, 'clock-names', b'xo\0')
    need(mss, 'qcom,proxy-clock-names', b'xo\0')
    need(mss, 'clocks', handle(clock) + words(0))
    need(clock, 'compatible', b'qcom,lito-rpmh-clk\0')
    need(clock, '#clock-cells', words(1))
    need(rsc, 'compatible', b'qcom,rpmh-rsc\0')
    need(rsc, 'reg', words(0x18200000, 0x10000, 0x18210000, 0x10000, 0x18220000, 0x10000))
    need(rsc, 'qcom,drv-id', words(2))
    need(rsc, 'qcom,tcs-config', words(2, 2, 0, 3, 1, 3, 3, 1))
    for resource, supply, name in ((cx, cx_supply, b'cx.lvl\0'),
                                    (mss_level, mss_supply, b'mss.lvl\0')):
        need(resource, 'compatible', b'qcom,rpmh-arc-regulator\0')
        need(resource, 'qcom,resource-name', name)
        need(supply, 'qcom,set', words(3))
        need(supply, 'regulator-min-microvolt', words(16))
        need(supply, 'regulator-max-microvolt', words(65535))
    need(qmp, 'compatible', b'qcom,qmp-mbox\0')
    need(qmp, 'reg', words(0x0c300000, 0x1000))
    need(qmp, 'mbox-desc-offset', words(0))
    need(qmp, '#mbox-cells', words(1))
    need(qmp, 'mboxes', handle(ipcc) + words(0, 0))
    need(qmp, 'interrupt-parent', handle(ipcc))
    need(qmp, 'interrupts', words(0, 0, 1))
    need(mss, 'mboxes', handle(qmp) + words(0))
    need(ipcc, 'compatible', b'qcom,ipcc\0')
    need(ipcc, 'reg', words(0x00408000, 0x1000))
    need(ipcc, '#mbox-cells', words(2))
    need(ipcc, '#interrupt-cells', words(3))
    need(ipcc, 'interrupts', words(0, 229, 4))
    need(smp2p, 'compatible', b'qcom,smp2p\0')
    need(smp2p, 'qcom,smem', words(435, 428))
    need(smp2p, 'qcom,local-pid', words(0))
    need(smp2p, 'qcom,remote-pid', words(1))
    need(smp2p, 'mboxes', handle(ipcc) + words(2, 2))
    need(smp2p, 'interrupt-parent', handle(ipcc))
    need(smp2p, 'interrupts', words(2, 2, 1))
    need(master, 'qcom,entry-name', b'master-kernel\0')
    need(master, '#qcom,smem-state-cells', words(1))
    need(slave, 'qcom,entry-name', b'slave-kernel\0')
    need(slave, 'interrupt-controller', b'')
    need(slave, '#interrupt-cells', words(2))
    need(mss, 'qcom,smem-states', handle(master) + words(0))
    need(mss, 'qcom,smem-state-names', b'qcom,force-stop\0')
    cmddb = [props for path, props in nodes.items() if path.startswith('/reserved-memory/') and
             props.get('compatible') == b'qcom,cmd-db\0']
    if len(cmddb) != 1 or cmddb[0].get('reg') != struct.pack('>QQ', 0x80860000, 0x20000) or \
            cmddb[0].get('no-map') != b'' or 'reusable' in cmddb[0]:
        raise ValueError('native MPSS requires the exact no-map CMD-DB reservation')
    return {'schema': 1, 'pas_id': 4, 'firmware': 'modem',
            'probe_ranges': PROBE_RANGES, 'witness': WITNESS,
            'proxy': {'cx_consumer_level': 384, 'mss_consumer_level': 384,
                      'cx_resource': 'cx.lvl', 'mss_resource': 'mss.lvl',
                      'xo_resource': 'xo.lvl', 'xo_arc_data': 3, 'drv': 2},
            'smp2p': {'incoming_item': 435, 'outgoing_item': 428,
                      'local_pid': 0, 'remote_pid': 1, 'force_stop_bit': 0,
                      'fatal_bit': 0, 'ready_bit': 1, 'handover_bit': 2,
                      'stop_ack_bit': 3, 'shutdown_ack_bit': 7},
            'power_proven': False, 'hardware_started': False}


def live_contract(blob, xnu_base, xnu_bytes):
    excluded = live_layout(blob, xnu_base, xnu_bytes)
    result = contract(_tree(blob)[0])
    result['excluded'] = excluded
    return result


def add_probe_contract(tree, nodes):
    contract(nodes)
    if any(child.name == 'redfin-wifi-native' for child in tree.children):
        raise ValueError('duplicate native Wi-Fi probe contract')
    tree.children.append(mkadt.node('redfin-wifi-native', [
        ('reg', mkadt.u64(*(value for pair in PROBE_RANGES for value in pair))),
        ('live-fdt-verified', mkadt.u32(1)),
        ('source-contract', mkadt.u32(*WITNESS))]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', required=True, type=Path)
    parser.add_argument('--xnu-base', required=True, type=lambda text: int(text, 0))
    parser.add_argument('--xnu-bytes', required=True, type=lambda text: int(text, 0))
    args = parser.parse_args()
    try:
        print(json.dumps(live_contract(read_regular(args.dtb, 16 * 1024 * 1024),
                                       args.xnu_base, args.xnu_bytes), indent=2))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
