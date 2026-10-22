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

    def test_final_snapshot_can_repeat_present_but_not_capture_id_or_regress(self):
        first = capture(self.RGB, 1, 7)
        final = capture(self.RGB, 2, 7)
        frames = decoder.decode(b'\n'.join(first + final))
        self.assertEqual([(frame.number, frame.present) for frame in frames], [(1, 7), (2, 7)])
        for records in (first + capture(self.RGB, 2, 6), first + first, first + final + final):
            with self.assertRaises(ValueError):
                decoder.decode(b'\n'.join(records))

    def test_actual_final_callback_ownership_gates_and_capture_policy(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('host C++ compiler unavailable')
        patch = (HERE / 'final-frame.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        actual = added.split('/* REDFIN_FINAL_TEST_BEGIN:', 1)[1].split('/* REDFIN_FINAL_TEST_END */', 1)[0]
        actual = actual.split('*/', 1)[1]
        harness = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
struct IOLock { bool held; };
static unsigned sleeps,release_after,attempts,calls,barriers,diagnostics,busy;
static uint32_t ids[4]; static uint64_t presents[4];
static IOLock *waiting;
static bool IOLockTryLock(IOLock *lock) { attempts++; if(lock->held)return false;lock->held=true;return true; }
static void IOLockUnlock(IOLock *lock) { assert(lock->held);lock->held=false; }
static void IOSleep(unsigned ms) { assert(ms==1);sleeps++;if(release_after && sleeps==release_after)waiting->held=false; }
static void IOLog(const char *format,...) { if(strstr(format,"lock busy"))busy++;else diagnostics++; }
static void barrier(unsigned value) { assert(value==15);barriers++; }
#define __builtin_arm_dsb(x) barrier(x)
class AppleCLCD {
public:
 bool fRedfinCopyOnly=true;
 IOLock *fRedfinCaptureLock;
 uint32_t fRedfinCaptures=0;
 uint64_t fRedfinPositivePresents=0,fRedfinFrames=0;
 bool fRedfinFinalDone=false,fPowerOff=false;
 unsigned references=1;
 explicit AppleCLCD(IOLock *lock):fRedfinCaptureLock(lock){}
 void retain(){references++;}
 void release(){assert(references>1);references--;}
 void captureRedfin(uint32_t frame,uint64_t present){
  assert(fRedfinCaptureLock->held && calls<3);ids[calls]=frame;presents[calls++]=present;
 }
};
ACTUAL
static void positive(AppleCLCD *fb,uint64_t present) {
 fb->fRedfinFrames=present;fb->fRedfinCaptureLock->held=true;
 uint32_t frame=redfin_capture_early(fb);if(frame)fb->captureRedfin(frame,present);
 fb->fRedfinCaptureLock->held=false;
}
int main(int argc,char **argv) {
 assert(argc==2);unsigned test=(unsigned)strtoul(argv[1],NULL,10);
 IOLock lock={false},second={false};AppleCLCD fb(&lock),other(&second);waiting=&lock;
 if(test==0){redfin_fb_capture_final();assert(!calls && !attempts);return 0;}
 if(test==1){fb.fRedfinCaptureLock=NULL;fb.fRedfinCaptures=3;assert(!redfin_capture_publish(&fb));
  redfin_fb_capture_final();assert(fb.references==1 && !calls && !attempts);return 0;}
 if(test==2){fb.fRedfinCopyOnly=false;assert(!redfin_capture_publish(&fb));
  fb.fRedfinCopyOnly=true;fb.fRedfinCaptures=3;assert(!redfin_capture_publish(&fb));assert(fb.references==1);return 0;}
 assert(redfin_capture_publish(&fb) && fb.references==2);
 if(test==3){assert(!redfin_capture_publish(&other) && other.references==1);
  assert(!redfin_capture_publish(&fb) && fb.references==2);assert(redfin_capture_fb==&fb);return 0;}
 if(test==4){for(unsigned i=1;i<=7;i++)positive(&fb,i);
  assert(calls==2 && ids[0]==1 && ids[1]==2 && presents[0]==1 && presents[1]==5);
  assert(fb.fRedfinPositivePresents==7 && fb.fRedfinCaptures==2);return 0;}
 if(test==5){positive(&fb,7);redfin_fb_capture_final();
  assert(calls==2 && ids[1]==2 && presents[1]==7 && fb.fRedfinFrames==7 && fb.fRedfinFinalDone);
  redfin_fb_capture_final();positive(&fb,8);assert(calls==2 && !lock.held && barriers==1);return 0;}
 if(test==6){for(unsigned i=1;i<=5;i++)positive(&fb,i);redfin_fb_capture_final();
  assert(calls==3 && ids[2]==3 && presents[2]==5 && fb.fRedfinFrames==5 && !lock.held);return 0;}
 if(test==7){fb.fRedfinFrames=12;redfin_fb_capture_final();
  assert(!calls && fb.fRedfinFinalDone && fb.fRedfinFrames==12 && !barriers && !lock.held);
  positive(&fb,13);assert(!calls);return 0;}
 if(test==8){lock.held=true;redfin_fb_capture_final();
  assert(attempts==250 && sleeps==249 && busy==1 && !calls && !fb.fRedfinFinalDone);return 0;}
 if(test==9){positive(&fb,4);lock.held=true;release_after=5;redfin_fb_capture_final();
  assert(attempts==6 && sleeps==5 && calls==2 && presents[1]==4 && !lock.held && diagnostics==1);return 0;}
 return 2;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            source, executable = Path(temporary) / 'final.cpp', Path(temporary) / 'final'
            source.write_text(harness.replace('ACTUAL', actual))
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=undefined', str(source), '-o', str(executable)], check=True)
            for scenario in range(10):
                with self.subTest(scenario=scenario):
                    result = subprocess.run([str(executable), str(scenario)], capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

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
