"""Reserve fresh guarded DMA32 RAM for the native WLAN packet transport."""
import struct

import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location('redfin_wifi_dma_mkadt', Path(__file__).with_name('mkadt.py'))
mkadt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mkadt)
from memory import memory_map, validate_window
from wifi_firmware import require

PAGE = 16384
BUFFER_BYTES = 16 * 1024 * 1024
POOL_BYTES = BUFFER_BYTES + 2 * PAGE
CONTRACT = (1, 0xc0, 1, BUFFER_BYTES, PAGE, 12, 32, 2048, 1, 0)


def reserve_low(dtb, xnu_base, xnu_bytes, rmtfs_pool):
    require(type(rmtfs_pool) in (tuple, list) and len(rmtfs_pool) == 2 and
            all(type(v) is int for v in rmtfs_pool) and rmtfs_pool[0] >= 0x80000000 and
            not rmtfs_pool[0] % PAGE and rmtfs_pool[1] == 0x288000 and
            sum(rmtfs_pool) <= 1 << 32, 'WLAN DMA requires the separate guarded RMTFS allocation')
    require(type(xnu_base) is type(xnu_bytes) is int and xnu_base == 0x180000000 and xnu_bytes == 0x80000000,
            'bounded WLAN DMA requires the isolated high-RAM profile')
    validate_window(dtb, *rmtfs_pool)
    layout = memory_map(dtb)
    excluded = [*layout['reserved'], (xnu_base, xnu_bytes), tuple(rmtfs_pool), (0x80080000, 0x8000000)]
    for first, size in reversed(layout['banks']):
        end = min(first + size, 1 << 32)
        while end - first >= POOL_BYTES:
            base = (end - POOL_BYTES) & -PAGE
            conflicts = [(a, n) for a, n in excluded if base < a + n and a < base + POOL_BYTES]
            if conflicts:
                end = min(a for a, _ in conflicts)
                continue
            validate_window(dtb, base, POOL_BYTES)
            return {'schema': 1, 'pool': (base, POOL_BYTES), 'buffer': (base + PAGE, BUFFER_BYTES),
                    'rmtfs_pool': tuple(rmtfs_pool), 'xnu': (xnu_base, xnu_bytes)}
    raise ValueError('no independently reservable low WLAN DMA range')


def add_contract(root, memory_map_node, proof, rmtfs_pool):
    require(type(proof) is dict and proof.get('schema') == 1 and
            tuple(proof.get('rmtfs_pool', ())) == tuple(rmtfs_pool) and
            tuple(proof.get('xnu', ())) == (0x180000000, 0x80000000), 'invalid WLAN DMA allocation proof')
    pool, buffer = proof.get('pool', ()), proof.get('buffer', ())
    require(len(pool) == len(buffer) == 2 and all(type(v) is int for v in (*pool, *buffer)) and
            pool[0] >= 0x80000000 and not pool[0] % PAGE and pool[1] == POOL_BYTES and sum(pool) <= 1 << 32 and
            tuple(buffer) == (pool[0] + PAGE, BUFFER_BYTES) and
            not (pool[0] < sum(rmtfs_pool) and rmtfs_pool[0] < sum(pool)), 'WLAN DMA overlaps retained RMTFS or has wrong guards')
    prior = [n for n in root.children if n.name == 'redfin-wifi-snoc']
    require(len(prior) == 1 and prior[0].prop('mission-enable') == mkadt.u32(1) and
            prior[0].prop('packets-enable') == mkadt.u32(1), 'WLAN DMA requires the explicit mission/packet profile')
    require(not any(n.name == 'redfin-wifi-dma' for n in root.children) and
            memory_map_node.prop('RedfinWiFiDMA') is None, 'duplicate WLAN DMA handoff')
    memory_map_node.props.append(('RedfinWiFiDMA', 0, mkadt.u64(*pool)))
    root.children.append(mkadt.node('redfin-wifi-dma', [
        ('reg', mkadt.u64(*pool)), ('buffer-reg', mkadt.u64(*buffer)),
        ('source-contract', mkadt.u32(*CONTRACT)), ('shim-owned', mkadt.u32(0))]))
