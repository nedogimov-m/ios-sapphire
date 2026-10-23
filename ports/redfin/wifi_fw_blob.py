#!/usr/bin/env python3
"""Append a native-verified private Wi-Fi bundle to a SWEETXNU v1 payload.

Produces a payload only. It never builds/boots an Android image or accesses a
device. A caller must separately establish ABL download and Image placement
limits before integrating this larger payload into an actual temporary boot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

if __package__:
    from . import mkadt
    from .wifi_firmware import live_layout, read_regular, require
else:
    import mkadt
    from wifi_firmware import live_layout, read_regular, require

PAGE = 16384
HEADER = 680
MAX_BUNDLE = 0x10000000
MAX_PAYLOAD = 0x20000000  # Implementation bound; not a measured ABL limit.
CONTRACT = (1, 4, PAGE, MAX_BUNDLE)


def aligned(value, alignment):
    return (value + alignment - 1) & -alignment


def payload_info(data):
    require(HEADER <= len(data) <= MAX_PAYLOAD, 'payload outside implementation bound')
    magic, version, count = struct.unpack_from('<8sII', data)
    require(magic == b'SWEETXNU' and version == 1 and 1 <= count < 64, 'unsupported payload ABI or no segment slot')
    virt, entry, adt_offset, adt_bytes, end, physical, memory = struct.unpack_from('<7Q', data, 16)
    require((physical, memory) == (0x180000000, 0x80000000) and
            not ((virt | physical | memory | end) % PAGE) and
            virt < end <= virt + memory < 1 << 64, 'payload is outside the proven RAM window')
    command = data[72:HEADER]
    require(b'\0' in command and not any(command[command.index(0) + 1:]), 'ambiguous payload command line')
    try:
        decoded = command.split(b'\0', 1)[0].decode('ascii')
        require(all(32 <= ord(character) <= 126 for character in decoded), 'nonprintable payload command line')
        words = decoded.split(' ')
    except UnicodeDecodeError as error:
        raise ValueError('non-ASCII payload command line') from error
    pairs = {}
    for word in filter(None, words):
        if '=' in word:
            key, value = word.split('=', 1)
            require(key not in pairs, 'duplicate payload argument')
            pairs[key] = value
    required = {'cpus': '1', 'rd': 'md0', 'modem': '0', 'wifi': '0', 'gpu': '0', 'sweetusb': '0',
                'redfinspmi': '1', 'redfinreturn': '1'}
    require(all(pairs.get(key) == value for key, value in required.items()), 'payload is not the native CPU0/md0/return profile')
    nonce = pairs.get('redfinbootid', '')
    require(re.fullmatch(r'0x[0-9a-f]{16}', nonce) and int(nonce, 16), 'payload requires one nonzero fresh boot ID')
    table = HEADER + 32 * count
    require(table <= len(data) and adt_offset >= table and adt_offset % 16 == 0 and 8 <= adt_bytes <= 0x200000 and
            adt_bytes % 4 == 0 and adt_offset + adt_bytes <= len(data), 'payload ADT outside source')
    segments = [struct.unpack_from('<4Q', data, HEADER + 32 * index) for index in range(count)]
    entry_found = False
    for index, (address, size, offset, length) in enumerate(segments):
        require(size > 0 and not ((address | size) % PAGE) and virt <= address and
                address + size <= virt + memory and length <= size and offset >= table and
                offset % 8 == 0 and offset + length <= len(data) and
                not (offset < adt_offset + adt_bytes and adt_offset < offset + length), 'invalid source segment')
        for old_address, old_size, old_offset, old_length in segments[:index]:
            require(not (address < old_address + old_size and old_address < address + size) and
                    not (offset < old_offset + old_length and old_offset < offset + length), 'aliased payload segments')
        entry_found |= address <= entry < address + length
    require(entry_found and entry % 4 == 0 and max(address + size for address, size, _offset, _length in segments) == end,
            'payload entry or kernel end mismatch')
    try:
        root, consumed = mkadt.adt.parse(data[adt_offset:adt_offset + adt_bytes])
    except (ValueError, UnicodeDecodeError, struct.error, RecursionError) as error:
        raise ValueError('malformed payload ADT') from error
    require(consumed == adt_bytes, 'trailing ADT bytes')
    chosen = [child for child in root.children if child.name == 'chosen']
    require(len(chosen) == 1 and chosen[0].prop('dram-base') == mkadt.u64(physical) and
            chosen[0].prop('dram-size') == mkadt.u64(memory), 'ADT and payload RAM differ')
    maps = [child for child in chosen[0].children if child.name == 'memory-map']
    require(len(maps) == 1, 'payload requires one memory-map node')
    require(not any(child.name == 'redfin-wifi-fw' for child in root.children) and
            maps[0].prop('RedfinWiFiFirmware') is None, 'payload already contains a firmware source')
    return {'virt': virt, 'entry': entry, 'end': end, 'physical': physical, 'memory': memory,
            'segments': segments, 'root': root, 'memory_map': maps[0]}


def verify_bundle(verifier, path, digest, excluded):
    command = [str(verifier), str(path), digest]
    for base, size in excluded:
        command.extend((hex(base), hex(size)))
    result = subprocess.run(command, capture_output=True, timeout=60, check=False)
    require(len(result.stdout) <= 1024 * 1024 and len(result.stderr) <= 1024 * 1024,
            'native source verifier output exceeds bound')
    require(result.returncode == 0, 'native source adapter rejected bundle')
    report = json.loads(result.stdout)
    require(type(report) is dict and report.get('schema') == 1 and report.get('bundle_sha256') == digest and
            report.get('signature_authenticated') is False and report.get('hardware_started') is False,
            'unsupported native source verifier report')
    return report


def pack(payload, firmware, digest, native_report, max_payload_bytes):
    require(type(max_payload_bytes) is int and 0 < max_payload_bytes <= MAX_PAYLOAD, 'explicit payload cap outside implementation bound')
    require(type(digest) is str and re.fullmatch(r'[0-9a-f]{64}', digest), 'expected bundle SHA256 must be lowercase hex')
    require(64 <= len(firmware) <= MAX_BUNDLE and hashlib.sha256(firmware).hexdigest() == digest,
            'bundle differs from the selected verified inventory')
    require(native_report.get('schema') == 1 and native_report.get('bundle_bytes') == len(firmware) and
            native_report.get('bundle_sha256') == digest and 2 <= native_report.get('assets', 0) <= 65 and
            0 < native_report.get('memory_bytes', 0) <= 0x11800000 and
            native_report.get('hardware_started') is False and native_report.get('signature_authenticated') is False,
            'missing native planner/source verification')
    info = payload_info(payload)
    reserved = aligned(len(firmware), PAGE)
    physical = info['physical'] + info['end'] - info['virt']
    new_end = info['end'] + reserved
    info['memory_map'].props.append(('RedfinWiFiFirmware', 0, mkadt.u64(physical, reserved)))
    info['root'].children.append(mkadt.node('redfin-wifi-fw', [
        ('reg', mkadt.u64(physical, reserved)), ('bundle-bytes', mkadt.u64(len(firmware))),
        ('bundle-sha256', bytes.fromhex(digest)), ('source-contract', mkadt.u32(*CONTRACT))]))
    tree = mkadt.adt.serialize(info['root'])
    tree_physical = physical + reserved
    arguments = aligned(tree_physical + len(tree), 16)
    top = aligned(arguments + 736, PAGE)
    require(top <= info['physical'] + info['memory'], 'firmware/ADT/arguments exceed kernel RAM')
    pieces = [(address, size, memoryview(payload)[offset:offset + length])
              for address, size, offset, length in info['segments']]
    pieces.append((info['end'], reserved, memoryview(firmware)))
    projected = aligned(HEADER + 32 * len(pieces), 16) + sum(aligned(len(data), 16) for _address, _size, data in pieces) + aligned(len(tree), 16)
    require(projected <= max_payload_bytes, 'complete payload exceeds explicit host cap')
    output = bytearray(aligned(HEADER + 32 * len(pieces), 16))
    output[:HEADER] = payload[:HEADER]
    table = []
    for address, size, data in pieces:
        offset = len(output)
        output.extend(data); output.extend(bytes(-len(output) % 16))
        table.append((address, size, offset, len(data)))
    tree_offset = len(output)
    output.extend(tree); output.extend(bytes(-len(output) % 16))
    require(len(output) == projected, 'payload accounting mismatch')
    struct.pack_into('<II', output, 8, 1, len(table))
    struct.pack_into('<QQQ', output, 32, tree_offset, len(tree), new_end)
    for index, segment in enumerate(table):
        struct.pack_into('<4Q', output, HEADER + 32 * index, *segment)
    return bytes(output), {'schema': 1, 'bundle_bytes': len(firmware), 'bundle_sha256': digest,
                           'source_physical': physical, 'source_reserved': reserved,
                           'adt_physical': tree_physical, 'boot_args_physical': arguments, 'top': top,
                           'segments': len(table), 'payload_bytes': len(output),
                           'explicit_payload_cap': max_payload_bytes, 'rootfs_dependency': False,
                           'abl_limits_proven': False, 'hardware_started': False,
                           'signature_authenticated': False}


def publish(destination, data):
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.redfin-wifi-blob-', dir=destination.parent)
        with os.fdopen(fd, 'wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        os.link(temporary, destination)  # No overwrite, including symlinks.
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--verifier', required=True, type=Path)
    parser.add_argument('--dtb', required=True, type=Path)
    parser.add_argument('--max-payload-bytes', required=True, type=lambda text: int(text, 0))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = read_regular(args.payload, MAX_PAYLOAD)
        info = payload_info(payload)
        excluded = live_layout(read_regular(args.dtb, 16 * 1024 * 1024), info['physical'], info['memory'])
        verified = verify_bundle(args.verifier, args.bundle, args.bundle_sha256, excluded)
        result, report = pack(payload, read_regular(args.bundle, MAX_BUNDLE), args.bundle_sha256,
                              verified, args.max_payload_bytes)
        publish(args.output, result)
        report['payload_sha256'] = hashlib.sha256(result).hexdigest()
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
