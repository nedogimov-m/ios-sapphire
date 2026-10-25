#!/usr/bin/env python3
"""Check full-panel or legacy cutout geometry in an authenticated RAM log.

Reads the existing 120x260 RGB captures without device access or output writes.
This checks RAM presentation; it does not measure the physical camera or touch.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('redfin_fit_screen_decoder', HERE / 'decode-screen.py')
decoder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decoder
SPEC.loader.exec_module(decoder)

FB_LINE = b'REDFIN FB: fit 2 bilinear viewport 31,136 1017x2204 top-exclusion 136'
HID_LINE = b'REDFIN HID: fit 2 inverse viewport 31,136 1017x2204'
VIEWPORT = (31, 136, 1017, 2204)
FULL_FB_LINE = b'REDFIN FB: fit 1 bilinear viewport 0,0 1080x2340 top-exclusion 0'
FULL_HID_LINE = b'REDFIN HID: fit 1 inverse viewport 0,0 1080x2340'
SAMPLE_STEP, SAMPLE_CENTER = 9, 4


def inspect(data):
    if not isinstance(data, bytes) or len(data) > decoder.MAX_LOG_BYTES:
        raise ValueError('log exceeds bounded input size')
    lines = [line.removesuffix(b'\r') for line in data.split(b'\n')]
    full=FULL_FB_LINE in lines
    for prefix, expected in ((b'REDFIN FB: fit ', FULL_FB_LINE if full else FB_LINE),
                             (b'REDFIN HID: fit ', FULL_HID_LINE if full else HID_LINE)):
        matches = [line for line in lines if prefix in line]
        if matches != [expected]:
            raise ValueError('expected exactly one matching fit line: ' + expected.decode())
    frames = decoder.decode(data)
    vx, vy, vw, vh = (0,0,1080,2340) if full else VIEWPORT
    results = []
    rendered = False
    for frame in frames:
        black_margins = nonblack_content = 0
        left, top, right, bottom = decoder.WIDTH, decoder.HEIGHT, 0, 0
        for y in range(decoder.HEIGHT):
            py = y * SAMPLE_STEP + SAMPLE_CENTER
            for x in range(decoder.WIDTH):
                px = x * SAMPLE_STEP + SAMPLE_CENTER
                offset = (y * decoder.WIDTH + x) * decoder.CHANNELS
                rgb = frame.rgb[offset:offset + decoder.CHANNELS]
                inside = vx <= px < vx + vw and vy <= py < vy + vh
                if not inside:
                    if rgb != b'\0\0\0':
                        raise ValueError(f'frame {frame.number}: nonblack margin at thumbnail '
                                         f'{x},{y}, physical {px},{py}, RGB {rgb.hex()}')
                    black_margins += 1
                elif rgb != b'\0\0\0':
                    nonblack_content += 1
                    left, top = min(left, x), min(top, y)
                    right, bottom = max(right, x + 1), max(bottom, y + 1)
        if nonblack_content:
            rendered = True
        results.append({'frame': frame.number, 'present': frame.present,
                        'crc32': f'{frame.crc32:08x}',
                        'black_margin_samples': black_margins,
                        'nonblack_content_samples': nonblack_content,
                        'nonblack_content_bounds':
                            {'left': left, 'top': top, 'right': right, 'bottom': bottom}
                            if nonblack_content else None})
    if not rendered:
        raise ValueError('captured frames contain no rendered content inside the viewport')
    return {'evidence': 'RAM presentation', 'mode': 'full' if full else 'cutout',
            'viewport': {'x': vx, 'y': vy, 'width': vw, 'height': vh},
            'thumbnail_content_bounds': {'left': 0 if full else 3, 'top': 0 if full else 15,
                                         'right': 120 if full else 116, 'bottom': 260},
            'checks': {'display_and_hid_fit_logs': True, 'black_margins': None if full else True,
                       'full_panel_viewport': full,
                       'captured_rendered_content': True}, 'frames': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path, help='authenticated xnu-console.txt from a cutout capture boot')
    args = parser.parse_args(argv)
    try:
        with args.log.open('rb') as stream:
            result = inspect(stream.read(decoder.MAX_LOG_BYTES + 1))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print('check-display-fit: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
