"""Validate capture bytes, strict framing and standalone PNG output without a phone."""
import ast
import base64
import ctypes
import importlib.util
from pathlib import Path
import shutil
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('redfin_decode_screen', HERE / 'decode-screen.py')
decoder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decoder
SPEC.loader.exec_module(decoder)


def capture(rgb, number=1, present=7):
    encoded = base64.b64encode(rgb)
    lines = [f'[REDFIN SCREEN v1 BEGIN frame={number} present={present} width=120 height=260 '
             'format=RGB8 raw=93600 b64=124800 chunks=650]'.encode()]
    lines += [f'[REDFIN SCREEN v1 DATA frame={number} seq={i}] '.encode() + encoded[i * 192:(i + 1) * 192]
              for i in range(650)]
    lines += [f'[REDFIN SCREEN v1 END frame={number} chunks=650 raw=93600 '
              f'crc32={zlib.crc32(rgb) & 0xffffffff:08x}]'.encode()]
    return lines


class ScreenCaptureTests(unittest.TestCase):
    RGB = bytes(range(256)) * (decoder.RAW_BYTES // 256) + bytes(range(decoder.RAW_BYTES % 256))

    def test_actual_kernel_record_formats_fit_iolog_and_ring_budget(self):
        patch = (HERE / 'screen-capture.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        parameters = {'BEGIN': (3, (1 << 64) - 1), 'DATA': (3, 649, 'A' * 192),
                      'END': (3, 0xffffffff)}
        formats = re.findall(r'IOLog\("(\[REDFIN SCREEN v1 [^"]*)"', added)
        self.assertEqual(len(formats), 3)
        for text in formats:
            kind = next(kind for kind in parameters if f'v1 {kind} ' in text)
            template = ast.literal_eval('"' + text + '"').replace('%llu', '%d').replace('%u', '%d')
            line = (template % parameters[kind]).encode('ascii')
            self.assertTrue(line.endswith(b'\n'))
            # IOLog's console_printbuf retains at most 255 bytes per call.
            self.assertLessEqual(len(line), 255, (kind, len(line)))
            self.assertLessEqual(len(line.rstrip(b'\n')), decoder.MAX_RECORD_BYTES)
        largest = capture(self.RGB, 3, (1 << 64) - 1)
        self.assertEqual(sum(len(line.split(b'] ', 1)[1]) for line in largest[1:-1]), 124800)
        self.assertLess(124800, 125000)
        self.assertLess(3 * sum(len(line) + 1 for line in largest), 512 * 1024)

    def test_interleaved_logs_three_frames_and_png_pixels(self):
        records = []
        for number in (1, 2, 3):
            for line in capture(self.RGB, number, number * 7):
                self.assertLessEqual(len(line) + 1, 255)
                records += [b'kernel noise\0', line]
        frames = decoder.decode(b'\r\n'.join(records))
        self.assertEqual([frame.number for frame in frames], [1, 2, 3])
        self.assertEqual(frames[2].rgb, self.RGB)
        image = decoder.png(frames[0])
        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
        offset, kinds, compressed = 8, [], b''
        while offset < len(image):
            size = struct.unpack_from('>I', image, offset)[0]
            kind, value = image[offset + 4:offset + 8], image[offset + 8:offset + 8 + size]
            self.assertEqual(zlib.crc32(kind + value) & 0xffffffff,
                             struct.unpack_from('>I', image, offset + 8 + size)[0])
            kinds.append(kind)
            if kind == b'IHDR':
                self.assertEqual(struct.unpack('>IIBBBBB', value), (120, 260, 8, 2, 0, 0, 0))
            if kind == b'IDAT':
                compressed += value
            offset += size + 12
        self.assertEqual(kinds, [b'IHDR', b'IDAT', b'IEND'])
        rows = zlib.decompress(compressed)
        self.assertEqual(len(rows), 260 * 361)
        self.assertEqual(b''.join(rows[y * 361 + 1:(y + 1) * 361] for y in range(260)), self.RGB)
        self.assertTrue(all(rows[y * 361] == 0 for y in range(260)))

    def test_truncated_duplicate_missing_reordered_or_wrong_frame_records_fail(self):
        good = capture(self.RGB)
        cases = [good[:-1], good[1:], good[:10] + good[11:], good[:10] + good[9:],
                 good[:4] + [good[5], good[4]] + good[6:], good + [good[1]],
                 [good[0], good[0]] + good[1:], good + good,
                 [good[0]] + [line.replace(b'frame=1', b'frame=2') for line in good[1:]]]
        for lines in cases:
            with self.subTest(case=cases.index(lines)), self.assertRaises(ValueError):
                decoder.decode(b'\n'.join(lines))

    def test_malformed_metadata_alphabet_crc_and_oversized_records_fail(self):
        good = capture(self.RGB)
        cases = []
        for before, after in ((b'width=120', b'width=121'), (b'raw=93600', b'raw=93601'),
                              (b'b64=124800', b'b64=99999999'), (b'chunks=650', b'chunks=651'),
                              (b'frame=1', b'frame=4'), (b'present=7', b'present=18446744073709551616')):
            cases.append([good[0].replace(before, after)] + good[1:])
        cases += [good[:1] + [good[1][:-1] + b'='] + good[2:],
                  good[:1] + [good[1].replace(b'seq=0', b'seq=00')] + good[2:],
                  good[:1] + [good[1][:-1] + b'!'] + good[2:],
                  good[:1] + [good[1] + b'A' * 721] + good[2:],
                  good[:1] + [b'prefix ' + good[1]] + good[2:],
                  good[:-1] + [good[-1].replace(b'crc32=', b'crc32=0')],
                  good[:-1] + [good[-1][:-9] + b'00000000]']]
        for lines in cases:
            with self.subTest(case=cases.index(lines)), self.assertRaises(ValueError):
                decoder.decode(b'\n'.join(lines))
        with self.assertRaises(ValueError):
            decoder.decode(b'X' * (decoder.MAX_LOG_BYTES + 1))

    def test_invalid_log_produces_no_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log, output = root / 'log.txt', root / 'logs/screens'
            log.write_bytes(b'\n'.join(capture(self.RGB)[:-1]))
            with mock.patch.object(decoder, 'ROOT', root):
                self.assertEqual(decoder.main([str(log), '--out', str(output)]), 1)
            self.assertFalse(output.exists())

    def test_actual_kernel_sampler_encoder_and_crc_match_rgb_contract(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('host compiler unavailable')
        patch = (HERE / 'screen-capture.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        helpers = added.split('/* REDFIN_SCREEN_TEST_BEGIN:', 1)[1].split('/* REDFIN_SCREEN_TEST_END */', 1)[0]
        helpers = helpers.split('*/', 1)[1]
        wrappers = '''
void sample(const uint8_t *src,uint8_t *dst){redfin_screen_sample(src,dst);}
void encode(const uint8_t *src,char *dst){redfin_screen_base64(src,dst);}
uint32_t checksum(const uint8_t *src,uint32_t n){return redfin_screen_crc32(src,n);}
'''
        with tempfile.TemporaryDirectory() as temporary:
            source, library = Path(temporary) / 'capture.c', Path(temporary) / 'capture.so'
            source.write_text('#include <stdint.h>\n' + helpers + wrappers)
            subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(source), '-o', str(library)], check=True)
            lib = ctypes.CDLL(str(library))
            lib.sample.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.encode.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.checksum.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            lib.checksum.restype = ctypes.c_uint32
            bgra = bytearray(b'\x11\x22\x33\x44' * (1080 * 2340))
            for x, y, color in ((4, 4, b'\x00\x00\xff\xff'), (1075, 2335, b'\x00\xff\x00\xff')):
                offset = y * 4320 + x * 4
                bgra[offset:offset + 4] = color
            actual = ctypes.create_string_buffer(decoder.RAW_BYTES)
            lib.sample(bytes(bgra), actual)
            self.assertEqual(actual.raw[:3], b'\xff\0\0')
            self.assertEqual(actual.raw[-3:], b'\0\xff\0')
            self.assertEqual(actual.raw[3:-3], b'\x33\x22\x11' * (120 * 260 - 2))
            self.assertEqual(lib.checksum(actual, decoder.RAW_BYTES), zlib.crc32(actual.raw) & 0xffffffff)
            pieces = []
            for index in range(650):
                out = ctypes.create_string_buffer(193)
                lib.encode(ctypes.byref(actual, index * 144), out)
                pieces.append(out.value)
            self.assertEqual(b''.join(pieces), base64.b64encode(actual.raw))
            decoded = decoder.decode(b'\n'.join(capture(actual.raw)))[0]
            self.assertEqual(decoded.rgb, actual.raw)


if __name__ == '__main__':
    unittest.main()
