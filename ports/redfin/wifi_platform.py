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
# Optional retained-power experiment: AOP/IPCC/DRV2 write mappings, followed by
# read-only GCC/GICD/CMD-DB. Version, DRV, ACTIVE pair, IRQs, inherited CBCR,
# CX/MSS/XO addresses/selectors and consumer levels, AOP packed notification.
POWER_RANGES = ((0x0c300000, 0x1000), (0x00408000, 0x1000), (0x18220000, 0x10000),
                (0x00100000, 0x1f0000), (0x17a00000, 0x4000), (0x80860000, 0x20000))
POWER_WITNESS = (1, 2, 0, 1, 37, 261, 0x71004, 0x30000, 7, 416,
                 0x30060, 6, 384, 0x300a0, 3, 0)


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


def power_contract(nodes):
    result = contract(nodes)
    words = lambda *values: struct.pack('>' + 'I' * len(values), *values)

    def need(path, key, value):
        if nodes.get(path, {}).get(key) != value:
            raise ValueError(f'native MPSS power FDT mismatch: {path} {key}')

    gic = '/soc/interrupt-controller@17a00000'
    gcc = '/soc/qcom,gcc@100000'
    rsc = '/soc/rsc@18200000'
    for path in (gic, gcc):
        if nodes.get(path, {}).get('status', b'okay\0') not in (b'okay\0', b'ok\0'):
            raise ValueError('native MPSS power prerequisite is disabled')
    need(gic, 'compatible', b'arm,gic-v3\0')
    need(gic, '#interrupt-cells', words(3))
    need(gic, 'reg', words(0x17a00000, 0x10000, 0x17a60000, 0x100000))
    need(gcc, 'compatible', b'qcom,gcc-lito\0syscon\0')
    need(gcc, 'reg', words(0x00100000, 0x1f0000))
    need(rsc, 'reg-names', b'drv-0\0drv-1\0drv-2\0')
    need(rsc, 'interrupts', words(0, 3, 4, 0, 4, 4, 0, 5, 4))
    gic_handle = nodes[gic].get('phandle', nodes[gic].get('linux,phandle', b''))
    if len(gic_handle) != 4:
        raise ValueError('native MPSS power requires the actual GIC phandle')

    def parent(path):
        while True:
            if 'interrupt-parent' in nodes.get(path, {}):
                return nodes[path]['interrupt-parent']
            if path == '/':
                return None
            path = path.rsplit('/', 1)[0] or '/'

    for path in (rsc, '/soc/qcom,ipcc@408000'):
        if parent(path) != gic_handle:
            raise ValueError('native MPSS power interrupt route does not select GIC')
    result['power_probe'] = {'ranges': POWER_RANGES, 'witness': POWER_WITNESS,
                             'retained_selectors': {'cx': 7, 'mss': 6, 'xo': 3},
                             'pas_calls': False, 'smem_writes': False}
    return result


def live_power_contract(blob, xnu_base, xnu_bytes):
    if (xnu_base, xnu_bytes) != (0x180000000, 0x80000000):
        raise ValueError('native MPSS power requires the proven CPU0/md0 RAM window')
    excluded = live_layout(blob, xnu_base, xnu_bytes)
    result = power_contract(_tree(blob)[0])
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


def add_power_contract(tree, nodes):
    power_contract(nodes)
    if any(child.name == 'redfin-wifi-power' for child in tree.children):
        raise ValueError('duplicate native Wi-Fi power contract')
    tree.children.append(mkadt.node('redfin-wifi-power', [
        ('reg', mkadt.u64(*(value for pair in POWER_RANGES for value in pair))),
        ('live-fdt-verified', mkadt.u32(1)),
        ('source-contract', mkadt.u32(*POWER_WITNESS))]))


def start_contract(nodes):
    """Bind the native PIL clients and their one exact live interconnect path."""
    result = power_contract(nodes)
    words = lambda *values: struct.pack('>' + 'I' * len(values), *values)

    def need(path, key, value):
        if nodes.get(path, {}).get(key) != value:
            raise ValueError(f'native MPSS startup FDT mismatch: {path} {key}')

    modem = '/soc/qcom,mss@4080000'
    for name in ('qcom,no-auth', 'qcom,subsys-vmid', 'qcom,mas-crypto'):
        if name in nodes[modem]:
            raise ValueError('native MPSS startup requires its cold native PAS4/crypto binding')
    need(modem, 'qcom,msm-bus,name', b'pil-modem\0')
    need(modem, 'qcom,msm-bus,num-cases', words(2))
    need(modem, 'qcom,msm-bus,num-paths', words(1))
    need(modem, 'qcom,msm-bus,vectors-KBps', words(129, 512, 0, 0, 129, 512, 0, 8171520))
    bus = '/soc/ad-hoc-bus/'
    handles = {props.get('phandle', props.get('linux,phandle')): path
               for path, props in nodes.items() if props.get('phandle', props.get('linux,phandle'))}

    def links(path, key):
        raw = nodes[path].get(key, b'')
        if len(raw) % 4:
            raise ValueError('unaligned MPSS bus phandles')
        try:
            return [handles[raw[i:i + 4]] for i in range(0, len(raw), 4)]
        except KeyError as error:
            raise ValueError('unresolved MPSS bus phandle') from error

    route = [('mas-qxm-crypto', 8, 1, ['CE0']), ('slv-qns-a2noc-snoc', 16, 1, []),
             ('mas-qnm-aggre2-noc', 16, 1, ['SN6']), ('slv-qns-gemnoc-sf', 16, 1, ['SN0']),
             ('mas-qnm-snoc-sf', 16, 1, []), ('slv-qns-llcc', 16, 2, ['SH0']),
             ('mas-llcc-mc', 4, 2, []), ('slv-ebi', 4, 2, ['MC0', 'ACV'])]
    apps = bus + 'rsc-apps'
    need(apps, 'cell-id', words(8000))
    need(apps, 'label', b'apps_rsc\0')
    need(apps, 'qcom,req_state', words(2))
    need(apps, 'qcom,rsc-dev', b'')
    for i, (name, width, ports, names) in enumerate(route):
        path = bus + name
        need(path, 'qcom,buswidth', words(width))
        need(path, 'qcom,agg-ports', words(ports))
        expected_next = bus + route[i + 1][0] if i + 1 < len(route) else None
        selected = [target for target in links(path, 'qcom,connections')
                    if target == expected_next]
        if expected_next and selected != [expected_next]:
            raise ValueError('native MPSS bus route changed')
        actual = []
        for bcm in links(path, 'qcom,bcms'):
            raw = nodes[bcm].get('qcom,bcm-name', b'')
            if not raw.endswith(b'\0') or links(bcm, 'qcom,rscs') != [apps]:
                raise ValueError('native MPSS BCM/RSC binding changed')
            actual.append(raw[:-1].decode('ascii'))
        if actual != names:
            raise ValueError('native MPSS BCM membership changed')
    need(bus + 'mas-qxm-crypto', 'cell-id', words(125))
    need(bus + 'mas-llcc-mc', 'cell-id', words(129))
    need(bus + 'slv-ebi', 'cell-id', words(512))
    result['start'] = {'schema': 1, 'pas': 4, 'bcms': ['CE0', 'SN6', 'SN0', 'SH0', 'MC0', 'ACV']}
    return result


def add_start_contract(tree, nodes):
    start_contract(nodes)
    if any(child.name == 'redfin-wifi-start' for child in tree.children):
        raise ValueError('duplicate native Wi-Fi startup contract')
    tree.children.append(mkadt.node('redfin-wifi-start', [
        ('source-contract', mkadt.u32(1, 4, 2, 435, 428, 3, 1, 125, 129, 512, 6)),
        ('bandwidth', mkadt.u64(393600000, 3936000000, 0, 8171520000)),
        ('bcm-names', b'CE0\0SN6\0SN0\0SH0\0MC0\0ACV\0'),
        ('reg', mkadt.u64(0x80900000, 0x200000, 0x1f40000, 0x20000,
                          0x408000, 0x1000, 0x8c000000, 0x11800000))]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', required=True, type=Path)
    parser.add_argument('--xnu-base', required=True, type=lambda text: int(text, 0))
    parser.add_argument('--xnu-bytes', required=True, type=lambda text: int(text, 0))
    parser.add_argument('--power', action='store_true', help='validate the optional retained-power contract')
    args = parser.parse_args()
    try:
        validate = live_power_contract if args.power else live_contract
        print(json.dumps(validate(read_regular(args.dtb, 16 * 1024 * 1024),
                                   args.xnu_base, args.xnu_bytes), indent=2))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
