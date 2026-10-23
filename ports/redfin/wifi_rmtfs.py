"""Pack private EFS snapshots and reserve an isolated low RMTFS RAM buffer."""
import hashlib
import json
from pathlib import Path
import struct

from memory import memory_map, validate_window, _tree
from wifi_firmware import read_regular, require

PAGE = 16384
SHARED_BYTES = 0x280000
POOL_BYTES = SHARED_BYTES + 2 * PAGE
FILES = (('/boot/modem_fs1', 'modemst1'), ('/boot/modem_fs2', 'modemst2'),
         ('/boot/modem_fsg', 'fsg'), ('/boot/modem_fsc', 'fsc'))


def reserve_low(dtb, xnu_base, xnu_bytes):
    """Top-down allocation from live free DRAM, never a board-guessed pool.

    Linux's dynamic pool rules have no allocated address at this boot stage.
    The shim independently checks the chosen range against its actual input
    Image, DTB, RAM banks and every fixed reservation before claiming it.
    """
    nodes, _ = _tree(dtb)
    native = nodes.get('/soc/qcom,rmtfs_sharedmem@0', {})
    require(native.get('compatible') == b'qcom,sharedmem-uio\0' and
            native.get('reg') == struct.pack('>II', 0, SHARED_BYTES) and
            native.get('reg-names') == b'rmtfs\0' and native.get('qcom,client-id') == struct.pack('>I', 1) and
            'qcom,vm-nav-path' not in native and 'qcom,guard-memory' not in native,
            'native RMTFS dynamic allocation or VMID binding changed')
    layout = memory_map(dtb)
    excluded = [*layout['reserved'], (xnu_base, xnu_bytes)]
    # Keep the complete bounded ABL Image download window out of the allocator.
    excluded.append((0x80080000, 0x8000000))
    for first, size in reversed(layout['banks']):
        end = min(first + size, 1 << 32)
        while end - first >= POOL_BYTES:
            base = (end - POOL_BYTES) & -PAGE
            conflicts = [(a, n) for a, n in excluded if base < a + n and a < base + POOL_BYTES]
            if conflicts:
                end = min(a for a, _ in conflicts)
                continue
            validate_window(dtb, base, POOL_BYTES)
            return {'pool': (base, POOL_BYTES), 'shared': (base + PAGE, SHARED_BYTES)}
    raise ValueError('no independently reservable low RMTFS DRAM range')


def pack(manifest, dtb, xnu_base, xnu_bytes):
    manifest = Path(manifest).resolve()
    report = json.loads(read_regular(manifest, 1024 * 1024))
    require(type(report) is dict and report.get('schema') == 1 and report.get('device') == 'redfin' and
            report.get('status') == 'verified-read-only-rmtfs-snapshot' and
            report.get('source') == 'verified-offline-recovery' and report.get('disk_writes') is False and
            report.get('left_in_bootloader') is True and type(report.get('files')) is list and len(report['files']) == 4,
            'RMTFS requires a complete verified private read-only snapshot')
    selected = {}
    for item in report['files']:
        require(type(item) is dict and item.get('path') in dict(FILES) and item['path'] not in selected and
                item.get('partition') == dict(FILES)[item['path']] and item.get('independent_reads_match') is True and
                type(item.get('gpt')) is dict and item['gpt'].get('block_size') == 4096,
                'RMTFS snapshot lacks exact partition/GPT/read proof')
        path = Path(item['private_file'])
        require(not path.is_absolute() and len(path.parts) == 1 and path.name not in ('.', '..'),
                'RMTFS snapshot file escapes its private inventory')
        data = read_regular(manifest.parent / path, 4 * 1024 * 1024)
        digest = hashlib.sha256(data).hexdigest()
        require(data and not len(data) % 4096 and len(data) == item.get('bytes') and digest == item.get('sha256'),
                'RMTFS snapshot bytes differ from the two verified reads')
        selected[item['path']] = (data, bytes.fromhex(digest))
    require(set(selected) == set(dict(FILES)), 'RMTFS snapshot paths differ from native allowlist')
    out = bytearray(64 + 4 * 128)
    for index, (name, _) in enumerate(FILES):
        data, digest = selected[name]
        offset, record = len(out), 64 + 128 * index
        out.extend(data)
        out[record:record + 64] = name.encode().ljust(64, b'\0')
        struct.pack_into('<QQ', out, record + 64, offset, len(data))
        out[record + 80:record + 112] = digest
    require(len(out) <= 12 * 1024 * 1024, 'RMTFS snapshot exceeds native image bound')
    struct.pack_into('<8sIIQQ', out, 0, b'RFRMS01\0', 1, 4, len(out), 128)
    allocation = reserve_low(dtb, xnu_base, xnu_bytes)
    return bytes(out), {'schema': 1, 'bytes': len(out), 'sha256': hashlib.sha256(out).hexdigest(),
                       'pool': allocation['pool'], 'shared': allocation['shared'],
                       'persistent_writes': False, 'shadow_bytes': sum(len(data) for data, _ in selected.values())}
