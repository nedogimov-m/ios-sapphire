#!/usr/bin/env python3
"""Validate and fingerprint primary GPT metadata in a disk-prefix capture."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


def fingerprint(blob, block_size=4096):
    """Hash the exact validated header and entry array; exclude boot padding."""
    if (type(block_size) is not int or block_size < 512 or block_size > 65536
            or block_size & (block_size - 1)):
        raise ValueError("invalid logical block size")
    if not isinstance(blob, bytes) or len(blob) < 2 * block_size:
        raise ValueError("truncated disk prefix")
    if blob[510:512] != b"\x55\xaa" or not any(
            blob[446 + 16 * i + 4] == 0xee for i in range(4)):
        raise ValueError("missing protective MBR")
    offset = block_size
    if blob[offset:offset + 8] != b"EFI PART":
        raise ValueError("missing primary GPT signature")
    revision, size, header_crc, reserved = struct.unpack_from("<4I", blob, offset + 8)
    if revision != 0x10000 or not 92 <= size <= block_size or reserved:
        raise ValueError("invalid GPT revision/header size/reserved field")
    header = blob[offset:offset + size]
    check = header[:16] + bytes(4) + header[20:]
    if zlib.crc32(check) != header_crc:
        raise ValueError("GPT header CRC mismatch")
    current, alternate, first, last = struct.unpack_from("<4Q", header, 24)
    entries_lba, count, entry_size, entries_crc = struct.unpack_from("<Q3I", header, 72)
    if current != 1 or first <= current or first > last or alternate <= last:
        raise ValueError("invalid GPT LBA geometry")
    if not 1 <= count <= 16384 or not 128 <= entry_size <= 4096 or entry_size % 8:
        raise ValueError("invalid or excessive GPT entry count/size")
    length = count * entry_size
    if length > 16 * 1024 * 1024:
        raise ValueError("GPT entry array exceeds 16 MiB limit")
    array_blocks = (length + block_size - 1) // block_size
    if entries_lba < 2 or entries_lba + array_blocks > first:
        raise ValueError("GPT entry array overlaps header/usable LBAs")
    start = entries_lba * block_size
    if start > len(blob) or length > len(blob) - start:
        raise ValueError("truncated GPT entry array")
    entries = blob[start:start + length]
    if zlib.crc32(entries) != entries_crc:
        raise ValueError("GPT entry array CRC mismatch")
    partitions = []
    for index in range(count):
        entry = entries[index * entry_size:(index + 1) * entry_size]
        if not any(entry[:16]):
            continue
        begin, end = struct.unpack_from("<QQ", entry, 32)
        if begin < first or end > last or begin > end:
            raise ValueError("partition extends outside usable GPT LBAs")
        partitions.append((begin, end))
    partitions.sort()
    if any(a[1] >= b[0] for a, b in zip(partitions, partitions[1:])):
        raise ValueError("overlapping GPT partitions")
    return {"metadata_sha256": hashlib.sha256(header + entries).hexdigest(),
            "entry_count": count, "entry_size": entry_size, "block_size": block_size,
            "header_crc32": f"{header_crc:08x}", "entries_crc32": f"{entries_crc:08x}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path, nargs="?")
    parser.add_argument("--block-size", type=int, default=4096)
    args = parser.parse_args()
    try:
        before = fingerprint(args.before.read_bytes(), args.block_size)
        if args.after is None:
            print(json.dumps(before, indent=2))
            return 0
        after = fingerprint(args.after.read_bytes(), args.block_size)
        unchanged = before == after
        print(json.dumps({"unchanged": unchanged, "before": before, "after": after}, indent=2))
        return 0 if unchanged else 1
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
