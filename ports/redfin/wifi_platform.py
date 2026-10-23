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


def add_glink_contract(tree, nodes, services=False):
    start_contract(nodes)
    modem = '/soc/qcom,glink/modem'
    ipcc = nodes['/soc/qcom,ipcc@408000']
    handle = ipcc.get('phandle', ipcc.get('linux,phandle'))
    words = lambda *values: struct.pack('>' + 'I' * len(values), *values)
    expected = {'qcom,remote-pid': words(1), 'transport': b'smem\0',
                'mboxes': handle + words(2, 0), 'mbox-names': b'modem_smem\0',
                'interrupt-parent': handle, 'interrupts': words(2, 0, 1), 'qcom,glink-label': b'mpss\0'}
    if any(nodes.get(modem, {}).get(key) != value for key, value in expected.items()) or \
            nodes.get(modem + '/qcom,modem_qrtr', {}).get('qcom,glink-channels') != b'IPCRTR\0':
        raise ValueError('native MPSS GLINK/QRTR live route changed')
    if any(child.name == 'redfin-wifi-glink' for child in tree.children):
        raise ValueError('duplicate native GLINK contract')
    tree.children.append(mkadt.node('redfin-wifi-glink', [
        ('source-contract', mkadt.u32(1, 4, 1, 478, 479, 480, 16384, 0x20000, 3, 1)),
        ('channel', b'IPCRTR\0')]))
    if services:
        output = '/soc/qcom,smp2p-mpss/qcom,smp2p-ipa-1-out'
        incoming = '/soc/qcom,smp2p-mpss/qcom,smp2p-ipa-1-in'
        mapping = '/soc/qcom,ipa@1e00000/qcom,smp2p_map_ipa_1_out'
        handle = nodes.get(output, {}).get('phandle', nodes.get(output, {}).get('linux,phandle'))
        if (nodes.get(output, {}).get('qcom,entry-name') != b'ipa\0' or
                nodes.get(output, {}).get('#qcom,smem-state-cells') != words(1) or
                nodes.get(incoming, {}).get('qcom,entry-name') != b'ipa\0' or not handle or
                nodes.get(mapping, {}).get('qcom,smem-states') != handle + words(0)):
            raise ValueError('native IPA SMP2P query/reply binding changed')
        rmtfs = nodes.get('/soc/qcom,rmtfs_sharedmem@0', {})
        if (rmtfs.get('compatible') != b'qcom,sharedmem-uio\0' or rmtfs.get('reg') != words(0, 0x280000) or
                rmtfs.get('reg-names') != b'rmtfs\0' or rmtfs.get('qcom,client-id') != words(1)):
            raise ValueError('native RMTFS dynamic memory binding changed')
        tree.children[-1].props.append(('host-services', 0,
            mkadt.u32(3, 64, 257, 0x4001, 4096, 1, 0x4002, 4, 65536, 8, 4096, 0, 1, 14, 1, 0x4003)))


def add_wlfw_contract(tree, nodes):
    """Legacy ICNSS fixed MSA, with the live board's absent hyp_enabled flag.

    Native icnss_assign_msa_perm() returns without a permission transition
    when qcom,hyp_enabled is absent. This profile preserves that behavior and
    never maps/zeroes the firmware's MSA memory on the host CPU.
    """
    words = lambda *values: struct.pack('>' + 'I' * len(values), *values)
    icnss = nodes.get('/soc/qcom,icnss@18800000', {})
    region = nodes.get('/reserved-memory/pil_wlan_fw_region@8ba00000', {})
    reference = icnss.get('qcom,wlan-msa-fixed-region')
    if (icnss.get('compatible') != b'qcom,icnss\0' or
            icnss.get('status', b'okay\0') not in (b'okay\0', b'ok\0') or
            region.get('status', b'okay\0') not in (b'okay\0', b'ok\0') or
            'qcom,hyp_enabled' in icnss or 'qcom,wlan-msa-memory' in icnss or
            region.get('compatible') != b'removed-dma-pool\0' or region.get('no-map') != b'' or
            region.get('reg') != struct.pack('>QQ', 0x8ba00000, 0x200000) or
            'reusable' in region or not reference or len(reference) != 4 or
            reference in (words(0), words(0xffffffff))):
        raise ValueError('native fixed-permission ICNSS/MSA binding changed')
    matches = []
    for path, properties in nodes.items():
        if properties.get('phandle', properties.get('linux,phandle')) == reference:
            matches.append(path)
        if ('phandle' in properties and 'linux,phandle' in properties and
                properties['phandle'] != properties['linux,phandle']):
            raise ValueError('native ICNSS phandle aliases disagree')
    if matches != ['/reserved-memory/pil_wlan_fw_region@8ba00000']:
        raise ValueError('native ICNSS MSA reference is missing or ambiguous')
    if any(child.name == 'redfin-wifi-wlfw' for child in tree.children):
        raise ValueError('duplicate native WLFW setup contract')
    tree.children.append(mkadt.node('redfin-wifi-wlfw', [
        ('reg', mkadt.u64(0x8ba00000, 0x200000)),
        ('source-contract', mkadt.u32(1, 0x45, 1, 0, 0x4b4e454c, 0, 2, 4096, 0x2d, 0x2e)),
        ('shim-verified', mkadt.u32(0))]))


def add_wlan_observer_contract(tree, nodes, power=False, pmic=False, hang=False, bdf=False):
    """Bind the native ICNSS consumers/providers before reading VRM metadata."""
    names = ('ldoa1', 'ldoa14', 'ldoc2', 'ldoc11', 'ldoc10')
    supply_keys = ('vdd-cx-mx', 'vdd-1.8-xo', 'vdd-1.3-rfa', 'vdd-3.3-ch1', 'vdd-3.3-ch0')
    children = ('regulator-pm8150-l1', 'regulator-pm8150-l14', 'regulator-pm8150a-l2',
                'regulator-pm8150a-l11', 'regulator-pm8150a-l10')
    bounds = ((352000, 952000, 352000), (1616000, 1984000, 1616000), (1144000, 1328000, 1144000),
              (3000000, 3312000, 3000000), (3000000, 3312000, 3000000))
    words = lambda *values: struct.pack('>' + 'I' * len(values), *values)
    icnss = nodes.get('/soc/qcom,icnss@18800000', {})
    if (not any(child.name == 'redfin-wifi-wlfw' for child in tree.children) or
            any(key in icnss for key in ('clocks', 'clock-names'))):
        raise ValueError('native WLAN observer requires fixed legacy setup and absent optional XO pin clock')
    for index, name in enumerate(names):
        path = '/soc/rsc@18200000/rpmh-regulator-' + name
        provider, consumer = nodes.get(path, {}), nodes.get(path + '/' + children[index], {})
        reference = consumer.get('phandle', consumer.get('linux,phandle'))
        if (provider.get('compatible') != b'qcom,rpmh-vrm-regulator\0' or
                provider.get('status', b'okay\0') not in (b'okay\0', b'ok\0') or
                consumer.get('status', b'okay\0') not in (b'okay\0', b'ok\0') or
                provider.get('qcom,resource-name') != name.encode() + b'\0' or
                provider.get('qcom,regulator-type') != b'pmic5-ldo\0' or not reference or
                icnss.get(supply_keys[index] + '-supply') != reference or
                consumer.get('qcom,set') != words(3) or consumer.get('qcom,init-mode') != words(2) or
                any(consumer.get(key) != words(value) for key, value in zip(
                    ('regulator-min-microvolt', 'regulator-max-microvolt', 'qcom,init-voltage'), bounds[index]))):
            raise ValueError('native WLAN VRM supply/provider binding changed: ' + name)
        matches = [path for path, props in nodes.items() if props.get('phandle', props.get('linux,phandle')) == reference]
        if matches != [path + '/' + children[index]]:
            raise ValueError('native WLAN supply reference is ambiguous')
        config = icnss.get('qcom,' + supply_keys[index] + '-config')
        expected = words(0, 0) if index == 0 else words(3000000, 3312000) if index >= 3 else None
        if config != expected:
            raise ValueError('native WLAN consumer voltage/load/delay config changed')
    if any(child.name == 'redfin-wifi-wlan' for child in tree.children):
        raise ValueError('duplicate native WLAN observer contract')
    if any(type(value) is not bool for value in (power, pmic, hang, bdf)) or ((pmic or hang or bdf) and not power):
        raise ValueError('native WLAN selectors must be boolean; PMIC/hang/BDF require power')
    if pmic:
        spmi_path = '/soc/qcom,spmi@c440000'
        spmi = nodes.get(spmi_path, {})
        if (spmi.get('compatible') != b'qcom,spmi-pmic-arb\0' or
                spmi.get('qcom,ee') != words(0) or
                spmi.get('#address-cells') != words(2) or spmi.get('#size-cells') != words(0)):
            raise ValueError('native WLAN PMIC observer requires the captured EE0 SPMI bus')
        # Preserve the captured legacy node labels; physical SID4 REVID is2751.
        for name, sid in (('pm8150', 0), ('pm8150', 1), ('pm8150l', 4), ('pm8150l', 5)):
            props = nodes.get(f'{spmi_path}/qcom,{name}@{sid}', {})
            if (props.get('compatible') != b'qcom,spmi-pmic\0' or props.get('reg') != words(sid, 0) or
                    props.get('status', b'okay\0') not in (b'okay\0', b'ok\0')):
                raise ValueError('native WLAN PMIC observer requires the captured PM8150/PM8150L SIDs')
    tree.children.append(mkadt.node('redfin-wifi-wlan', [
        ('source-contract', mkadt.u32(2 if power else 1, 5, 4, 4, 0, 352, 1800, 1304, 3000, 3000)),
        ('resource-names', b''.join(name.encode().ljust(8, b'\0') for name in names)),
        ('observe-only', mkadt.u32(0 if power else 1))] + ([
        ('resource-addresses', mkadt.u32(0x40800, 0x42100, 0x41d00, 0x41a00, 0x41900))] if power else []) + ([
        ('pmic-observe', mkadt.u32(1)),
        ('pmic-candidates', mkadt.u32(0x001, 0x401, 0x140, 0x14d, 0x541, 0x54a, 0x549))] if pmic else []) + ([
        ('msa-hang-observe', mkadt.u32(1))] if hang else []) + ([
        ('bdf-download', mkadt.u32(1)),
        ('bdf-contract', mkadt.u32(1, 0x444d4f4e, 0x4005, 26328, 2048, 0x4320, 0xff, 0)),
        ('bdf-name', b'image/bdwlan-u-redfin.bin\0'),
        ('bdf-sha256', bytes.fromhex('7b0add4f469df39c0b26167513da8931419e917a4d9058252c05e0f5cffe7b90'))] if bdf else [])))


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
