"""Bind a complete native A620 command run to the captured FDT and inventory.

Firmware stays private. Native generic PIL allocates the relocatable zap;
the unaligned, unreferenced bootloader reservation is never a load target.
"""
import hashlib
import json
from pathlib import Path
import struct

from ports.redfin import gmu_probe, mkadt
from ports.redfin.wifi_firmware import read_regular

POLICY = (5, 0x06020001, 275000000, 64, 5, 14, 32, 3, 0, 0x401, 0xFFFFFFFF, 0,
          13, 0x100000, 0x1000, 0x1000000, 0x8000, 0x1100000, 0x1200000, 500, 0, 1, 9999999)
RANGES = (0x3D00000, 0x40000, 0x18220000, 0x10000)
DDR_KBPS = (0, 400000, 800000, 1200000, 1804800, 2188000, 2724000, 3072000,
            4068000, 5412000, 6220000, 7216000, 8371200)
FILES = {'sqe': ('/firmware/a650_sqe.fw', 31632),
         'zap-mdt': ('/firmware/a620_zap.mdt', 6860),
         'zap-segment': ('/firmware/a620_zap.b02', 1676)}


def load_assets(inventory):
    inventory = Path(inventory).resolve()
    record = json.loads(read_regular(inventory, 0x200000))
    entries = record.get('files')
    if not isinstance(entries, list):
        raise ValueError('GPU requires a captured native firmware inventory')
    wanted = dict(FILES, **{'zap-header': ('/firmware/a620_zap.b00', 148),
                           'zap-signature': ('/firmware/a620_zap.b01', 6712)})
    result = {}
    for name, (path, size) in wanted.items():
        candidates = [e for e in entries if isinstance(e, dict) and e.get('path') == path]
        if len(candidates) != 1:
            raise ValueError(f'GPU inventory has missing/duplicate {path}')
        entry = candidates[0]
        if entry.get('bytes') != size or not isinstance(entry.get('private_file'), str):
            raise ValueError(f'GPU inventory size/source mismatch: {path}')
        source = Path(entry['private_file'])
        if source.is_absolute() or '..' in source.parts:
            raise ValueError('GPU inventory source must be a bounded relative path')
        roots = (inventory.parent, inventory.parent.parent)
        matches = {candidate.resolve() for root in roots
                   if (candidate := root / source).is_file()}
        if len(matches) != 1:
            raise ValueError(f'GPU inventory source is missing/ambiguous: {path}')
        payload = read_regular(matches.pop(), size)
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) != size or digest != entry.get('sha256'):
            raise ValueError(f'GPU captured firmware SHA256 mismatch: {path}')
        result[name] = payload
        result[name + '-sha256'] = bytes.fromhex(digest)
    if result['zap-header'] + result['zap-signature'] != result['zap-mdt']:
        raise ValueError('GPU signed MDT differs from its recorded split header/hash files')
    validate_assets(result)
    return {k: result[k] for name in FILES for k in (name, name + '-sha256')}


def validate_assets(assets):
    if not isinstance(assets, dict):
        raise ValueError('GPU command profile requires private bound SQE and signed zap')
    for name, (_, size) in FILES.items():
        data, digest = assets.get(name), assets.get(name + '-sha256')
        if (not isinstance(data, bytes) or len(data) != size or
                not isinstance(digest, bytes) or len(digest) != 32 or
                hashlib.sha256(data).digest() != digest):
            raise ValueError(f'GPU command profile has an invalid {name} identity')
    mdt = assets['zap-mdt']
    if (mdt[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<I', mdt, 28)[0] != 52 or
            struct.unpack_from('<3H', mdt, 40) != (52, 32, 3)):
        raise ValueError('GPU zap requires the native ELF32 split image')
    loads = [struct.unpack_from('<8I', mdt, 52 + i * 32) for i in range(3)]
    if ([(i, p) for i, p in enumerate(loads) if p[0] == 1 and p[5] and
            p[6] & 0x7000000 != 0x2000000] !=
            [(2, (1, 0x3000, 0x5000, 0x5000, 1676, 1676, 0x8000007, 0x100000))]):
        raise ValueError('GPU zap relocation/span/segment differs from native A620')


def add_contract(tree, nodes, assets):
    validate_assets(assets)
    cells = lambda *v: struct.pack('>' + 'I' * len(v), *v)

    def need(path, key, value):
        if nodes.get(path, {}).get(key) != value:
            raise ValueError(f'GPU command FDT mismatch: {path} {key}')

    def resolve(raw):
        hits = [p for p, v in nodes.items() if raw and v.get('phandle') == raw]
        if len(hits) != 1:
            raise ValueError('GPU command FDT has an unresolved/ambiguous phandle')
        return hits[0]

    if any(n.name == 'redfin-gpu-command' for n in tree.children):
        raise ValueError('duplicate GPU command contract')
    gmus = [n for n in tree.children if n.name == 'redfin-gmu']
    if len(gmus) != 1 or gmus[0].prop('start-policy') != mkadt.u32(*gmu_probe.START_POLICY):
        raise ValueError('GPU commands require the complete GMU startup contract first')
    gpu, gmu = '/soc/qcom,kgsl-3d0@3d00000', '/soc/qcom,gmu@3d6a000'
    need(gpu, 'qcom,chipid', cells(0x06020001))
    need(gpu, 'interrupts', cells(0, 300, 4))
    for key, value in (('qcom,highest-bank-bit', 14), ('qcom,min-access-length', 32),
                       ('qcom,ubwc-mode', 3), ('qcom,msm-bus,num-cases', 13),
                       ('qcom,msm-bus,num-paths', 1)):
        need(gpu, key, cells(value))
    need(gpu, 'qcom,msm-bus,vectors-KBps', b''.join(cells(26, 512, 0, n) for n in DDR_KBPS))
    need(gmu, 'qcom,msm-bus,vectors-KBps', cells(26, 10036, 0, 0, 26, 10036, 0, 100))
    cfg = gpu + '/qcom,cpu-to-gpu-cfg-path'
    need(cfg, 'qcom,msm-bus,name', b'gpu_cfg\0')
    need(cfg, 'qcom,msm-bus,num-cases', cells(3))
    need(cfg, 'qcom,msm-bus,num-paths', cells(1))
    need(cfg, 'qcom,msm-bus,vectors-KBps', cells(1, 598, 0, 0, 1, 598, 0, 100,
                                               1, 598, 0, 9999999))
    opp = resolve(nodes[gpu].get('operating-points-v2'))
    need(opp + '/opp-275000000', 'opp-hz', struct.pack('>Q', 275000000))
    need(opp + '/opp-275000000', 'opp-microvolt', cells(64))
    bins = [p for p, v in nodes.items() if p.startswith(gpu + '/qcom,gpu-pwrlevel-bins/')
            and 'qcom,speed-bin' in v]
    if not bins:
        raise ValueError('GPU command profile has no native speed bins')
    for parent in bins:
        low = [p for p, v in nodes.items() if p.startswith(parent + '/') and
               v.get('qcom,gpu-freq') == cells(275000000)]
        if len(low) != 1:
            raise ValueError('GPU low OPP is not common to all native speed bins')
        for key in ('qcom,bus-freq', 'qcom,bus-min'):
            need(low[0], key, cells(5))
    smmu = '/soc/kgsl-smmu@3da0000'
    for child, sid, mask in (('gfx3d_user', 0, 0x401), ('gfx3d_secure', 2, 0x400)):
        path = '/soc/qcom,kgsl-iommu@3da0000/' + child
        need(path, 'iommus', nodes[smmu]['phandle'] + cells(sid, mask))
        need(path, 'qcom,iommu-dma', b'disabled\0')
    hyp = '/soc/qcom,kgsl-hyp'
    need(hyp, 'compatible', b'qcom,pil-tz-generic\0')
    need(hyp, 'qcom,pas-id', cells(13))
    need(hyp, 'qcom,firmware-name', b'a620_zap\0')
    if any(k in nodes[hyp] for k in ('memory-region', 'qcom,pil-no-auth', 'qcom,no-auth',
                                    'qcom,subsys-vmid', 'qcom,mas-crypto')):
        raise ValueError('GPU zap requires the native dynamic authenticated PIL binding')
    bus = '/soc/ad-hoc-bus/'
    route = [('mas-qxm-crypto', 8, 1, ['CE0']), ('slv-qns-a2noc-snoc', 16, 1, []),
             ('mas-qnm-aggre2-noc', 16, 1, ['SN6']), ('slv-qns-gemnoc-sf', 16, 1, ['SN0']),
             ('mas-qnm-snoc-sf', 16, 1, []), ('slv-qns-llcc', 16, 2, ['SH0']),
             ('mas-llcc-mc', 4, 2, []), ('slv-ebi', 4, 2, ['MC0', 'ACV'])]
    need(bus + 'rsc-apps', 'cell-id', cells(8000))
    apps = nodes[bus + 'rsc-apps']['phandle']
    for index, (name, width, ports, bcms) in enumerate(route):
        path = bus + name
        need(path, 'qcom,buswidth', cells(width))
        need(path, 'qcom,agg-ports', cells(ports))
        raw = nodes[path].get('qcom,bcms', b'')
        if len(raw) % 4:
            raise ValueError('GPU crypto route has malformed BCM membership')
        members = [resolve(raw[i:i + 4]) for i in range(0, len(raw), 4)]
        if {nodes[p].get('qcom,bcm-name') for p in members} != {n.encode() + b'\0' for n in bcms}:
            raise ValueError('GPU native crypto BCM membership changed')
        for p in members:
            need(p, 'qcom,rscs', apps)
        if index + 1 < len(route):
            links = nodes[path].get('qcom,connections', b'')
            if nodes[bus + route[index + 1][0]]['phandle'] not in [links[i:i + 4] for i in range(0, len(links), 4)]:
                raise ValueError('GPU native crypto route changed')
    for name, width, ports in (('mas-qnm-gpu', 32, 2), ('slv-qns-cnoc', 8, 1)):
        need(bus + name, 'qcom,buswidth', cells(width))
        need(bus + name, 'qcom,agg-ports', cells(ports))
    cfg_route = [('mas-acm-apps0', 16, ['SH4']), ('slv-qns-gem-noc-snoc', 8, []),
                 ('mas-qnm-gemnoc', 8, ['SN10']), ('slv-qns-cnoc', 8, []),
                 ('mas-qnm-snoc', 8, ['CN0']), ('slv-qhs-gpuss-cfg', 8, ['CN0'])]
    need(bus + 'mas-acm-apps0', 'cell-id', cells(1))
    need(bus + 'slv-qhs-gpuss-cfg', 'cell-id', cells(598))
    for index, (name, width, bcms) in enumerate(cfg_route):
        path = bus + name
        need(path, 'qcom,buswidth', cells(width))
        need(path, 'qcom,agg-ports', cells(1))
        raw = nodes[path].get('qcom,bcms', b'')
        members = [resolve(raw[i:i + 4]) for i in range(0, len(raw), 4)]
        if {nodes[p].get('qcom,bcm-name') for p in members} != {n.encode() + b'\0' for n in bcms}:
            raise ValueError('GPU native CPU configuration route BCMs changed')
        for p in members:
            need(p, 'qcom,rscs', apps)
        if index + 1 < len(cfg_route):
            links = nodes[path].get('qcom,connections', b'')
            if nodes[bus + cfg_route[index + 1][0]]['phandle'] not in [links[i:i + 4] for i in range(0, len(links), 4)]:
                raise ValueError('GPU native CPU configuration route changed')
    need(bus + 'bcm-cn0', 'qcom,bcm-name', b'CN0\0')
    need(bus + 'bcm-cn0', 'qcom,rscs', apps)
    tree.children.append(mkadt.node('redfin-gpu-command', [
        ('reg', mkadt.u64(*RANGES)), ('policy', mkadt.u32(*POLICY)),
        *[(key, value) for key, value in assets.items()]]))
