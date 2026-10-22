#!/usr/bin/env python3
"""Decode bounded REDFIN SCREEN v1 RAMLOG captures into PNG files under logs/.

The kernel records captures only when booted with redfinscreen=1.
"""
import argparse
import base64
from dataclasses import dataclass
import json
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
WIDTH, HEIGHT, CHANNELS = 120, 260, 3
RAW_BYTES, B64_BYTES, CHUNKS, CHUNK_CHARS = 93600, 124800, 650, 192
MAX_LOG_BYTES, MAX_RECORD_BYTES, MAX_FRAMES = 8 * 1024 * 1024, 255, 3
PREFIX = b'[REDFIN SCREEN'
BEGIN = re.compile(rb'\[REDFIN SCREEN v1 BEGIN frame=([1-3]) present=([1-9][0-9]{0,19}) '
                   rb'width=120 height=260 format=RGB8 raw=93600 b64=124800 chunks=650\]')
DATA = re.compile(rb'\[REDFIN SCREEN v1 DATA frame=([1-3]) seq=(0|[1-9][0-9]{0,2})\] ([A-Za-z0-9+/]{192})')
END = re.compile(rb'\[REDFIN SCREEN v1 END frame=([1-3]) chunks=650 raw=93600 crc32=([0-9a-f]{8})\]')


@dataclass(frozen=True)
class Frame:
    number: int
    present: int
    rgb: bytes
    crc32: int


def decode(data):
    """Validate all records before returning frames; unrelated log lines may interleave."""
    if not isinstance(data, bytes) or len(data) > MAX_LOG_BYTES:
        raise ValueError('log exceeds bounded input size')
    frames, active = [], None
    for line_number, line in enumerate(data.split(b'\n'), 1):
        line = line.removesuffix(b'\r')
        if PREFIX not in line:
            continue
        if len(line) > MAX_RECORD_BYTES or not line.startswith(PREFIX):
            raise ValueError(f'malformed or oversized screen record at line {line_number}')
        begin, chunk, end = BEGIN.fullmatch(line), DATA.fullmatch(line), END.fullmatch(line)
        if begin:
            number, present = map(int, begin.groups())
            if (active is not None or len(frames) >= MAX_FRAMES or present > (1 << 64) - 1 or
                    frames and (number <= frames[-1].number or present <= frames[-1].present)):
                raise ValueError('nested, duplicated or out-of-order screen frame')
            active = {'number': number, 'present': present, 'chunks': 0, 'rgb': bytearray()}
        elif chunk:
            number, sequence, encoded = chunk.groups()
            if (active is None or int(number) != active['number'] or
                    int(sequence) != active['chunks'] or active['chunks'] >= CHUNKS):
                raise ValueError('missing, duplicated or out-of-order screen chunk')
            decoded = base64.b64decode(encoded, validate=True)
            if len(decoded) != 144 or base64.b64encode(decoded) != encoded:
                raise ValueError('noncanonical screen base64')
            active['rgb'].extend(decoded)
            active['chunks'] += 1
        elif end:
            number, checksum = int(end[1]), int(end[2], 16)
            if (active is None or number != active['number'] or
                    active['chunks'] != CHUNKS or len(active['rgb']) != RAW_BYTES):
                raise ValueError('truncated screen frame')
            rgb = bytes(active['rgb'])
            if zlib.crc32(rgb) & 0xffffffff != checksum:
                raise ValueError('screen CRC32 mismatch')
            frames.append(Frame(number, active['present'], rgb, checksum))
            active = None
        else:
            raise ValueError(f'malformed screen record at line {line_number}')
    if active is not None:
        raise ValueError('truncated screen frame at end of log')
    if not frames:
        raise ValueError('no complete screen captures found')
    return frames


def png(frame):
    if len(frame.rgb) != RAW_BYTES:
        raise ValueError('incorrect RGB buffer size')

    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload +
                struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))

    rows = b''.join(b'\0' + frame.rgb[y * WIDTH * CHANNELS:(y + 1) * WIDTH * CHANNELS]
                    for y in range(HEIGHT))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--out', type=Path, help='new output directory under repository logs/')
    args = parser.parse_args(argv)
    try:
        output = (args.out or args.log.parent / 'screens').resolve()
        if not output.is_relative_to((ROOT / 'logs').resolve()):
            raise ValueError('--out must remain under repository logs/')
        with args.log.open('rb') as stream:
            frames = decode(stream.read(MAX_LOG_BYTES + 1))
        # Parse and encode every frame before creating any output artifacts.
        images = [(frame, png(frame)) for frame in frames]
        if output.exists():
            raise ValueError('output directory already exists; choose a fresh --out')
        output.mkdir(parents=True)
        results = []
        for frame, image in images:
            path = output / f'redfin-screen-{frame.number:02d}-present-{frame.present}.png'
            path.write_bytes(image)
            results.append({'frame': frame.number, 'present': frame.present, 'path': str(path),
                            'width': WIDTH, 'height': HEIGHT, 'crc32': f'{frame.crc32:08x}'})
        print(json.dumps({'frames': results}, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print('decode-screen: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
