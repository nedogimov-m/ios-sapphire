"""Bounded file-update planning for an unmounted Redfin HFSX root.

Newly allocated blocks have unknown live contents even when a sparse staging
image reads zero. Always write their complete staged contents, including zero
blocks, and verify complete files through the catalog's actual extent list.
This module performs no device I/O and never changes a filesystem header.
"""
from pathlib import Path

BLOCK_BYTES = 4096
ROOT_BLOCKS = 4194304


def extent_ranges(record):
    if (record.get('block_bytes') != BLOCK_BYTES or type(record.get('bytes')) is not int
            or not 0 < record['bytes'] <= 128 * 1024**2):
        raise ValueError('bounded native regular file required')
    ranges = record.get('extents')
    if not isinstance(ranges, list) or not ranges or len(ranges) > 4096:
        raise ValueError('bounded complete extent list required')
    occupied = set()
    capacity = 0
    for extent in ranges:
        if (not isinstance(extent, (list, tuple)) or len(extent) != 2
                or any(type(x) is not int for x in extent)):
            raise ValueError('invalid native file extent')
        start, count = extent
        if not 0 < start < start + count <= ROOT_BLOCKS or count > 32768:
            raise ValueError('file extent escapes the first 16GiB root')
        blocks = set(range(start, start + count))
        if occupied.intersection(blocks):
            raise ValueError('overlapping native file extents')
        occupied.update(blocks)
        capacity += count * BLOCK_BYTES
    if not record['bytes'] <= capacity < record['bytes'] + BLOCK_BYTES:
        raise ValueError('file allocation does not match complete data extent')
    return ranges


def read_file(read_blocks, record):
    chunks = []
    for start, count in extent_ranges(record):
        for at in range(start, start + count, 2048):
            n = min(2048, start + count - at)
            data = read_blocks(at, n)
            if not isinstance(data, bytes) or len(data) != n * BLOCK_BYTES:
                raise ValueError('short complete-file readback')
            chunks.append(data)
    return b''.join(chunks)[:record['bytes']]


def verify_file(read_blocks, record, expected):
    if not isinstance(expected, bytes) or len(expected) != record.get('bytes'):
        raise ValueError('complete expected file bytes required')
    if read_file(read_blocks, record) != expected:
        raise ValueError('complete installed file differs from staged bytes')


def plan_blocks(original, staged, candidates, newly_allocated=()):
    """Include ALL new blocks; comparing an unpopulated sparse preimage is insufficient."""
    new = set(newly_allocated)
    blocks = set(candidates) | new
    if (not blocks or len(blocks) > 131072
            or any(type(x) is not int or not 0 <= x < ROOT_BLOCKS for x in blocks)):
        raise ValueError('bounded root update candidates required')
    changed = []
    with Path(original).open('rb') as before, Path(staged).open('rb') as after:
        for block in sorted(blocks):
            before.seek(block * BLOCK_BYTES)
            after.seek(block * BLOCK_BYTES)
            a, b = before.read(BLOCK_BYTES), after.read(BLOCK_BYTES)
            if len(a) != BLOCK_BYTES or len(b) != BLOCK_BYTES:
                raise ValueError('short staged root block')
            if block in new or a != b:
                changed.append(block)
    return changed


def zero_hole_damage(actual, expected):
    """Recognize the observed installation failure; never excuse changed code bytes."""
    if not isinstance(actual, bytes) or not isinstance(expected, bytes) or len(actual) != len(expected):
        raise ValueError('equal complete file lengths required')
    changed = sum(a != b for a, b in zip(actual, expected))
    if not changed or any(a != b and b != 0 for a, b in zip(actual, expected)):
        raise ValueError('file damage differs from omitted zero blocks')
    return changed
