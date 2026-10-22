#!/usr/bin/env python3
"""Build a private native MPSS bundle from an existing verified host inventory.

Host regular files only. No device commands, mounts, partition reads, hardware
operations or credentials. Firmware and per-device output must stay out of git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile

from memory import _tree, memory_map, validate_window

MPSS_BASE, MPSS_BYTES = 0x8c000000, 0x11800000
SMEM_BASE, SMEM_BYTES = 0x80900000, 0x200000
DISPLAY_BASE, DISPLAY_BYTES = 0xa0000000, 0x2300000
MAX_MDT, MAX_BUNDLE = 65536, 0x10000000
MAX_REPORT = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                'input must be a bounded nonempty regular file')
        return fd, before
    except Exception:
        os.close(fd)
        raise


def unchanged(fd, before):
    after = os.fstat(fd)
    require(all(getattr(after, field) == getattr(before, field) for field in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')),
            'input changed during operation')


def read_regular(path, maximum):
    fd, before = regular(path, maximum)
    try:
        data = bytearray()
        while len(data) < before.st_size:
            chunk = os.read(fd, min(65536, before.st_size - len(data)))
            require(chunk, 'short regular-file read')
            data.extend(chunk)
        unchanged(fd, before)
        return bytes(data)
    finally:
        os.close(fd)


def live_layout(blob, xnu_base, xnu_bytes):
    """Bind exact native MPSS/SMEM/display layout and return all exclusions."""
    validate_window(blob, xnu_base, xnu_bytes)
    layout = memory_map(blob)
    nodes, header_reservations = _tree(blob)
    mss = nodes.get('/soc/qcom,mss@4080000', {})
    require(mss.get('compatible') == b'qcom,pil-tz-generic\0' and
            mss.get('qcom,firmware-name') == b'modem\0' and
            mss.get('qcom,pas-id') == struct.pack('>I', 4) and
            mss.get('status', b'okay\0') in (b'okay\0', b'ok\0') and
            'qcom,signal-aop' in mss,
            'live MPSS node is not the supported PAS4 modem/AOP contract')
    reference = mss.get('memory-region', b'')
    require(len(reference) == 4 and int.from_bytes(reference, 'big'),
            'MPSS must refer to exactly one live reservation')
    handles = {}
    for path, props in nodes.items():
        for key in ('phandle', 'linux,phandle'):
            if key not in props:
                continue
            value = props[key]
            require(len(value) == 4 and int.from_bytes(value, 'big') not in (0, 0xffffffff),
                    'invalid live phandle')
            require(value not in handles or handles[value] == path, 'duplicate live phandle')
            handles[value] = path
        if 'phandle' in props and 'linux,phandle' in props:
            require(props['phandle'] == props['linux,phandle'], 'phandle aliases disagree')
    path = handles.get(reference, '')
    region = nodes.get(path, {})
    require(path.startswith('/reserved-memory/') and path.count('/') == 2 and
            region.get('reg') == struct.pack('>QQ', MPSS_BASE, MPSS_BYTES) and
            region.get('no-map') == b'' and 'reusable' not in region,
            'MPSS reservation does not match the exact live Redfin range')
    require(any(base <= MPSS_BASE and MPSS_BASE + MPSS_BYTES <= base + size
                for base, size in layout['banks']), 'MPSS is outside live RAM')
    smem = [props for name, props in nodes.items() if name.startswith('/reserved-memory/') and
            props.get('reg') == struct.pack('>QQ', SMEM_BASE, SMEM_BYTES)]
    require(len(smem) == 1 and smem[0].get('no-map') == b'' and 'reusable' not in smem[0],
            'SMEM must retain its exact no-map reservation')
    splash = nodes.get('/reserved-memory/cont_splash_region', {})
    require(splash.get('reg') == struct.pack('>QQ', DISPLAY_BASE, DISPLAY_BYTES),
            'live display reservation differs from the proven scanout contract')
    excluded = [(xnu_base, xnu_bytes), (DISPLAY_BASE, DISPLAY_BYTES)]
    excluded.extend(header_reservations)
    for name, props in nodes.items():
        if name == path or not name.startswith('/reserved-memory/') or 'reg' not in props:
            continue
        excluded.extend(struct.iter_unpack('>QQ', props['reg']))
    # A second reservation of the modem range is ambiguous and must fail; do
    # not discard every numerically equal interval from the live FDT.
    for base, size in excluded:
        require(size > 0 and base >= 0 and base + size < 1 << 64, 'invalid exclusion')
        require(not (base < MPSS_BASE + MPSS_BYTES and MPSS_BASE < base + size),
                'MPSS overlaps kernel/display/recovery or another reservation')
    require(2 <= len(excluded) <= 64, 'too many live exclusions for native planner')
    return excluded


def native_plan(planner, metadata, excluded):
    command = [str(planner), str(metadata)]
    for base, size in excluded:
        command.extend((hex(base), hex(size)))
    result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    require(len(result.stdout) <= MAX_REPORT and len(result.stderr) <= MAX_REPORT,
            'native planner output exceeds bound')
    require(result.returncode == 0, 'native MDT planner rejected metadata')
    plan = json.loads(result.stdout)
    require(type(plan) is dict and plan.get('schema') == 1 and plan.get('pas_id') == 4 and
            plan.get('physical_base') == MPSS_BASE and 0 < plan.get('memory_bytes', 0) <= MPSS_BYTES,
            'native planner returned an unsupported plan')
    return plan


def digest_file(path, declared_bytes, expected):
    require(type(declared_bytes) is int and 0 < declared_bytes <= MAX_BUNDLE,
            'asset size outside bound')
    require(type(expected) is str and len(expected) == 64 and
            all(character in '0123456789abcdef' for character in expected),
            'asset digest must be lowercase SHA256')
    fd, before = regular(path, declared_bytes)
    try:
        require(before.st_size == declared_bytes, 'asset length differs from inventory')
        digest = hashlib.sha256()
        left = declared_bytes
        while left:
            data = os.read(fd, min(left, 65536))
            require(data, 'short asset read')
            digest.update(data)
            left -= len(data)
        unchanged(fd, before)
        require(digest.hexdigest() == expected, 'asset SHA256 differs from verified inventory')
        return before
    finally:
        os.close(fd)


def prepare(inventory_path, assets, dtb_path, planner, xnu_base, xnu_bytes):
    manifest_bytes = read_regular(inventory_path, MAX_REPORT)
    inventory = json.loads(manifest_bytes)
    require(type(inventory) is dict, 'inventory must be a JSON object')
    boot = inventory.get('initial_boot', {})
    require(boot.get('prefix') == 'modem' and boot.get('pas_id') == 4,
            'inventory is not the native modem/PAS4 selection')
    source_hash = inventory.get('image_sha256', '')
    require(type(source_hash) is str and len(source_hash) == 64 and
            all(character in '0123456789abcdef' for character in source_hash) and
            type(inventory.get('image_bytes')) is int and 0 < inventory['image_bytes'] <= 512 * 1024 * 1024,
            'inventory lacks bounded source-image identity')
    files = boot.get('required_files', [])
    require(type(files) is list and 2 <= len(files) <= 65, 'invalid asset inventory count')
    by_name = {}
    for item in files:
        require(type(item) is dict and type(item.get('name')) is str, 'invalid asset record')
        name = item['name']
        valid = name == 'modem.mdt' or (len(name) == 9 and name.startswith('modem.b') and
                name[-2:].isascii() and name[-2:].isdigit() and int(name[-2:]) < 64)
        require(valid and name not in by_name, 'unexpected or duplicate firmware asset name')
        by_name[name] = item
    require('modem.mdt' in by_name, 'MDT missing from inventory')
    metadata_record = by_name['modem.mdt']
    require(metadata_record.get('phdr_index') is None and
            type(metadata_record.get('bytes')) is int and metadata_record['bytes'] <= MAX_MDT,
            'metadata inventory has invalid PHDR index or size')
    dtb = read_regular(dtb_path, 16 * 1024 * 1024)
    excluded = live_layout(dtb, xnu_base, xnu_bytes)
    assets = Path(assets)
    digest_file(assets / 'modem.mdt', metadata_record['bytes'], metadata_record.get('sha256'))
    plan = native_plan(planner, assets / 'modem.mdt', excluded)
    require(plan['metadata_bytes'] == metadata_record['bytes'], 'planner metadata length mismatch')
    selections = [(0xffffffff, 'modem.mdt', metadata_record)]
    required = {'modem.mdt'}
    for segment in plan['segments']:
        index, size = segment['index'], segment['file_bytes']
        require(type(index) is int and 0 <= index < 64 and type(size) is int and size >= 0,
                'invalid native segment selection')
        if not size:
            continue
        name = f'modem.b{index:02d}'
        require(name in by_name and name not in required, 'required native PHDR blob absent/duplicated')
        record = by_name[name]
        require(record.get('phdr_index') == index and record.get('bytes') == size,
                'inventory does not preserve native PHDR index/size')
        required.add(name)
        selections.append((index, name, record))
    require(set(by_name) == required, 'inventory includes nonloadable or unexpected assets')
    total = 64 + len(selections) * 48
    for _, name, record in selections:
        digest_file(assets / name, record['bytes'], record.get('sha256'))
        total += (record['bytes'] + 7) & ~7
    require(total <= MAX_BUNDLE, 'complete firmware bundle exceeds native bound')
    return {'schema': 1, 'source_image_sha256': source_hash,
            'inventory_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'live_fdt_sha256': hashlib.sha256(dtb).hexdigest(),
            'bundle_bytes': total, 'excluded': excluded, 'plan': plan}, selections


def write_bundle(destination, assets, report, selections):
    """Reverify during copy and atomically publish a private, no-overwrite file."""
    destination, assets = Path(destination), Path(assets)
    header = struct.pack('<8s4I3Q16x', b'RFWIFI1\0', 1, len(selections), 48, 0,
                         report['bundle_bytes'], MPSS_BASE, MPSS_BYTES)
    cursor = 64 + len(selections) * 48
    table = bytearray()
    for index, _, record in selections:
        table.extend(struct.pack('<IIQ32s', index, record['bytes'], cursor,
                                 bytes.fromhex(record['sha256'])))
        cursor += (record['bytes'] + 7) & ~7
    require(cursor == report['bundle_bytes'], 'bundle geometry changed')
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.redfin-wifi-', dir=destination.parent)
        with os.fdopen(fd, 'wb') as output:
            output.write(header)
            output.write(table)
            for _, name, record in selections:
                source, before = regular(assets / name, record['bytes'])
                try:
                    require(before.st_size == record['bytes'], 'asset changed before bundle copy')
                    digest = hashlib.sha256()
                    left = record['bytes']
                    while left:
                        chunk = os.read(source, min(left, 65536))
                        require(chunk, 'short asset during bundle copy')
                        output.write(chunk)
                        digest.update(chunk)
                        left -= len(chunk)
                    unchanged(source, before)
                    require(digest.hexdigest() == record['sha256'], 'asset changed during bundle copy')
                finally:
                    os.close(source)
                output.write(bytes((-record['bytes']) % 8))
            require(output.tell() == report['bundle_bytes'], 'short bundle output')
            output.flush()
            os.fsync(output.fileno())
        # link() refuses existing files and symlinks. mkstemp creates mode0600.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--dtb', required=True, type=Path)
    parser.add_argument('--planner', required=True, type=Path)
    parser.add_argument('--xnu-base', required=True, type=lambda text: int(text, 0))
    parser.add_argument('--xnu-bytes', required=True, type=lambda text: int(text, 0))
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args()
    try:
        report, selections = prepare(args.inventory, args.assets, args.dtb,
                                     args.planner, args.xnu_base, args.xnu_bytes)
        if args.bundle:
            write_bundle(args.bundle, args.assets, report, selections)
            report['bundle_sha256'] = hashlib.sha256(read_regular(args.bundle, MAX_BUNDLE)).hexdigest()
        report['hardware_started'] = False
        report['signature_authenticated'] = False
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
