#!/usr/bin/env python3
"""Validate a <=4 MiB liblp prefix and emit read-only vendor_b capture extents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct

SECTOR = 512
MAX_PREFIX = 4*1024*1024
MAX_VENDOR = 2*1024*1024*1024
SUPER_BYTES = 9755951104


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def span(data, offset, size):
    require(0 <= offset <= len(data) and 0 <= size <= len(data)-offset,
            f'captured prefix missing range [{offset}, {offset+size})')
    return data[offset:offset+size]


def checked_digest(data, checksum_offset):
    copy = bytearray(data)
    saved = bytes(copy[checksum_offset:checksum_offset+32])
    copy[checksum_offset:checksum_offset+32] = bytes(32)
    require(hashlib.sha256(copy).digest() == saved, 'SHA256 checksum mismatch')


def geometry(data, offset):
    raw = span(data, offset, 52)
    magic, size = struct.unpack_from('<II', raw)
    require(magic == 0x616c4467 and size == 52, 'unsupported liblp geometry')
    checked_digest(raw, 8)
    maximum, slots, block = struct.unpack_from('<III', raw, 40)
    require(512 <= maximum <= MAX_PREFIX and not maximum % SECTOR, 'invalid metadata maximum size')
    require(2 <= slots <= 4, 'unsupported metadata slot count')
    require(block in (512, 1024, 2048, 4096, 8192, 16384), 'unsupported logical block size')
    return {'metadata_max_size': maximum, 'metadata_slot_count': slots, 'logical_block_size': block}


def name(raw):
    first, separator, tail = raw.partition(b'\0')
    require(not separator or not any(tail), 'nonzero name padding')
    require(re.fullmatch(rb'[A-Za-z0-9_-]{1,36}', first) is not None, 'invalid liblp name')
    return first.decode('ascii')


def metadata(data, offset, maximum):
    first = span(data, offset, 128)
    magic, major, minor, header_size = struct.unpack_from('<IHHI', first)
    require(magic == 0x414c5030 and major == 10 and minor <= 2, 'unsupported liblp metadata version')
    require(header_size == (256 if minor >= 2 else 128), 'invalid metadata header size')
    header = span(data, offset, header_size)
    checked_digest(header, 12)
    tables_size = struct.unpack_from('<I', header, 44)[0]
    require(tables_size <= maximum-header_size, 'tables exceed metadata slot')
    tables = span(data, offset+header_size, tables_size)
    require(hashlib.sha256(tables).digest() == header[48:80], 'tables SHA256 mismatch')
    flags = struct.unpack_from('<I', header, 128)[0] if minor >= 2 else 0
    if minor >= 2:
        require(not any(header[132:]), 'nonzero reserved metadata header fields')
    descriptors, intervals = [], []
    for at, expected_size in ((80, 52), (92, 24), (104, 48), (116, 64)):
        start, count, size = struct.unpack_from('<III', header, at)
        require(size == expected_size and count <= 4096, 'unsupported table entry size/count')
        require(start <= tables_size and count*size <= tables_size-start, 'table outside checksummed bytes')
        descriptors.append([span(tables, start+n*size, size) for n in range(count)])
        if count:
            intervals.append((start, start+count*size))
    cursor = 0
    for start, end in sorted(intervals):
        require(start == cursor, 'metadata table gap or overlap')
        cursor = end
    require(cursor == tables_size, 'unassigned metadata table bytes')
    partitions, extents, groups, devices = descriptors
    parsed_partitions = []
    for raw in partitions:
        attributes, first, count, group = struct.unpack_from('<4I', raw, 36)
        mask = 3 if minor == 0 else 15
        require(not attributes & ~mask, 'unsupported partition attributes')
        require(first <= len(extents) and count <= len(extents)-first and group < len(groups),
                'invalid partition extent/group reference')
        parsed_partitions.append({'name': name(raw[:36]), 'attributes': attributes,
                                  'first_extent': first, 'num_extents': count, 'group_index': group})
    parsed_extents = [dict(zip(('num_sectors', 'target_type', 'target_data', 'target_source'),
                              struct.unpack('<QIQI', raw))) for raw in extents]
    parsed_groups = []
    for raw in groups:
        group_flags, maximum_size = struct.unpack_from('<IQ', raw, 36)
        require(not group_flags & ~1, 'unsupported group flags')
        parsed_groups.append({'name': name(raw[:36]), 'flags': group_flags, 'maximum_size': maximum_size})
    parsed_devices = []
    for raw in devices:
        first, alignment, alignment_offset, size, raw_name, device_flags = struct.unpack('<QIIQ36sI', raw)
        parsed_devices.append({'name': name(raw_name), 'first_logical_sector': first, 'alignment': alignment,
                               'alignment_offset': alignment_offset, 'bytes': size, 'flags': device_flags})
    for records in (parsed_partitions, parsed_groups, parsed_devices):
        require(len({r['name'] for r in records}) == len(records), 'duplicate liblp name')
    return {'offset': offset, 'major': major, 'minor': minor, 'header_size': header_size,
            'tables_size': tables_size, 'flags': flags, 'partitions': parsed_partitions,
            'extents': parsed_extents, 'groups': parsed_groups, 'block_devices': parsed_devices,
            'sha256': hashlib.sha256(header+tables).hexdigest()}


def slot_proof(text):
    lines = [line.strip() for line in text.splitlines() if 'current-slot' in line]
    require(len(lines) == 1 and re.fullmatch(r'(?:\(bootloader\)\s*)?current-slot\s*:\s*b', lines[0]),
            'exactly one fresh external current-slot:b proof is required')
    return lines[0]


def plan(data, proof, super_bytes=SUPER_BYTES):
    require(12288 <= len(data) <= MAX_PREFIX, 'prefix must be 12 KiB..4 MiB')
    require(super_bytes == SUPER_BYTES, 'unexpected validated Redfin super size')
    witness = slot_proof(proof)
    primary_geo, backup_geo = geometry(data, 4096), geometry(data, 8192)
    require(primary_geo == backup_geo and data[4096:4148] == data[8192:8244], 'redundant geometries disagree')
    maximum, slots = primary_geo['metadata_max_size'], primary_geo['metadata_slot_count']
    offset, backup = 12288+maximum, 12288+maximum*slots+maximum
    primary, secondary = metadata(data, offset, maximum), metadata(data, backup, maximum)
    require(span(data, offset, maximum) == span(data, backup, maximum), 'slot1 metadata copies disagree')
    devices = primary['block_devices']
    require(len(devices) == 1 and devices[0]['name'] == 'super' and not devices[0]['flags'],
            'only the validated unsuffixed single super device is supported')
    device = devices[0]
    require(device['bytes'] == super_bytes and not super_bytes % SECTOR, 'metadata/GPT device size mismatch')
    metadata_end = 12288+2*maximum*slots
    require(device['first_logical_sector']*SECTOR >= metadata_end and
            device['first_logical_sector'] < super_bytes//SECTOR, 'first logical sector overlaps metadata')
    require(device['alignment'] and not device['alignment'] % SECTOR and
            not device['alignment_offset'] % SECTOR and device['alignment_offset'] < device['alignment'],
            'invalid block-device alignment')
    partitions = primary['partitions']
    resolved = [(p['name']+('_b' if p['attributes'] & 2 else ''), p) for p in partitions]
    require(len({n for n, _ in resolved}) == len(resolved), 'resolved slot partition names collide')
    selected = [(n, p) for n, p in resolved if n == 'vendor_b']
    require(len(selected) == 1, 'exactly one vendor_b partition required')
    _, vendor = selected[0]
    require(not vendor['attributes'] & 8 and vendor['num_extents'],
            'vendor_b is not a populated enabled partition')
    for extent in primary['extents']:
        length = extent['num_sectors']*SECTOR
        if extent['target_type'] == 0:
            physical = extent['target_data']*SECTOR
            require(extent['target_source'] == 0 and length > 0 and
                    physical >= device['first_logical_sector']*SECTOR and physical <= super_bytes and
                    length <= super_bytes-physical, 'extent outside validated super data')
        elif extent['target_type'] == 1:
            require(length > 0 and not extent['target_data'] and not extent['target_source'], 'invalid zero extent')
        else:
            raise Invalid('unsupported extent target type')
    selected_extents = primary['extents'][vendor['first_extent']:vendor['first_extent']+vendor['num_extents']]
    reads, logical = [], 0
    for index, extent in enumerate(selected_extents):
        length = extent['num_sectors']*SECTOR
        require(length > 0 and length <= MAX_VENDOR-logical, 'vendor_b exceeds 2 GiB or has empty extent')
        target = extent['target_type']
        if target == 0:
            require(extent['target_source'] == 0, 'vendor extent targets an unvalidated device')
            physical = extent['target_data']*SECTOR
            require(physical >= device['first_logical_sector']*SECTOR and physical <= super_bytes and
                    length <= super_bytes-physical, 'vendor extent outside validated super data')
            require(not any(physical < r['source_offset_bytes']+r['bytes'] and
                            r['source_offset_bytes'] < physical+length for r in reads if r['kind'] == 'linear'),
                    'overlapping vendor physical extents')
            block = 4096 if not (physical | length) % 4096 else 512
            reads.append({'extent': index, 'kind': 'linear', 'device': '/dev/block/sda18',
                          'source_offset_bytes': physical, 'output_offset_bytes': logical, 'bytes': length,
                          'dd_block_size': block, 'dd_skip': physical//block, 'dd_count': length//block})
        elif target == 1:
            require(not extent['target_data'] and not extent['target_source'], 'invalid zero extent')
            reads.append({'extent': index, 'kind': 'zero', 'output_offset_bytes': logical, 'bytes': length})
        else:
            raise Invalid('unsupported vendor extent target type')
        logical += length
    group = primary['groups'][vendor['group_index']]
    require(not group['maximum_size'] or logical <= group['maximum_size'], 'vendor exceeds owning group limit')
    require(not logical % primary_geo['logical_block_size'], 'vendor size not logical-block aligned')
    cows = []
    for resolved_name, item in resolved:
        if resolved_name.endswith('-cow'):
            extents = primary['extents'][item['first_extent']:item['first_extent']+item['num_extents']]
            cows.append({'name': resolved_name, 'attributes': item['attributes'],
                         'bytes': sum(e['num_sectors']*SECTOR for e in extents), 'extents': extents})
    return {'schema': 1, 'view': 'raw-vendor_b-base', 'current_effective_image_proven': False,
            'virtual_ab': bool(primary['flags'] & 1), 'snapshot_status_unproven': True, 'cow_partitions': cows,
            'prefix_bytes': len(data), 'prefix_sha256': hashlib.sha256(data).hexdigest(),
            'current_slot': 'b', 'current_slot_witness': witness, 'slot_proof_sha256': hashlib.sha256(proof.encode()).hexdigest(),
            'geometry': primary_geo, 'all_metadata_end': metadata_end,
            'metadata': {'slot': 1, 'primary_offset': offset, 'backup_offset': backup,
                         'copies_identical': True, 'header_and_tables_sha256': primary['sha256'],
                         'version': f"{primary['major']}.{primary['minor']}", 'flags': primary['flags']},
            'super': device, 'vendor': {**vendor, 'resolved_name': 'vendor_b', 'bytes': logical, 'group': group},
            'capture_extents': reads, 'partitions': resolved,
            'notes': ['Read-only host plan; no device commands issued by this program.',
                      'GPT/by-name sda18 identity must remain the separately verified capture identity.',
                      'This reconstructs raw vendor_b base extents, not an active Virtual A/B snapshot overlay.',
                      'Root must retain current-slot:b proof and revalidate the same source before targeted reads.']}


def read_regular(path, maximum):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum, 'input must be a bounded regular file')
        data = os.read(fd, info.st_size+1)
        require(len(data) == info.st_size, 'input changed or read was incomplete')
        return data
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('--slot-proof', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = plan(read_regular(args.prefix, MAX_PREFIX), read_regular(args.slot_proof, 4096).decode('ascii'))
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print('vendor_b bytes='+str(result['vendor']['bytes']), 'extents='+str(len(result['capture_extents'])))
    for extent in result['capture_extents']:
        print(json.dumps(extent, sort_keys=True))


if __name__ == '__main__':
    main()
