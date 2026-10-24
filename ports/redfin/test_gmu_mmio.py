"""Check actual Darwin ARM64 instructions, including zero and atomic ATS stores.

Apple's assembler accepts ';' as a comment: a multi-instruction asm string
can compile successfully while silently omitting the stores after its barrier.
Host register mocks cannot detect that failure.
"""
from collections import Counter
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def macho_text(data):
    if struct.unpack_from('<I', data)[0] != 0xFEEDFACF:
        raise ValueError('expected ARM64 Mach-O object')
    at = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<II', data, at)
        if command == 0x19:
            for section in range(struct.unpack_from('<I', data, at + 64)[0]):
                entry = at + 72 + section * 80
                if data[entry:entry + 16].rstrip(b'\0') == b'__text':
                    length = struct.unpack_from('<Q', data, entry + 40)[0]
                    offset = struct.unpack_from('<I', data, entry + 48)[0]
                    return data[offset:offset + length]
        at += size
    raise ValueError('missing Mach-O instruction section')


class GMUMMIOInstructionsTests(unittest.TestCase):
    def test_darwin_emits_complete_barrier_store_barrier_for_zero_and_live_values(self):
        compiler = shutil.which('clang')
        if compiler is None:
            self.skipTest('Clang ARM64 Darwin assembler required')
        source = (HERE / 'gmu-memory.inc').read_text()
        bodies = []
        for name in ('gm_memory_store', 'gm_memory_store64'):
            match = re.search(r'^static void ' + name + r'\([^\n]+\)\n\{.*?^\}',
                              source, re.M | re.S)
            self.assertIsNotNone(match, name)
            bodies.append(match[0])
        harness = ('typedef unsigned long vm_offset_t;\n'
                   'typedef unsigned int uint32_t;\n'
                   'typedef unsigned long long uint64_t;\n' + '\n'.join(bodies) + '\n'
                   'void word_zero(vm_offset_t a){gm_memory_store(a,0);}\n'
                   'void word_value(vm_offset_t a,uint32_t v){gm_memory_store(a,v);}\n'
                   'void atomic_zero(vm_offset_t a){gm_memory_store64(a,0);}\n'
                   'void atomic_value(vm_offset_t a,uint64_t v){gm_memory_store64(a,v);}\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, obj = root / 'stores.c', root / 'stores.o'
            path.write_text(harness)
            result = subprocess.run([compiler, '-target', 'arm64-apple-ios16.0.0',
                '-isysroot', '/', '-nostdinc', '-O2', '-Wall', '-Wextra', '-Werror',
                '-c', str(path), '-o', str(obj)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = macho_text(obj.read_bytes())
        self.assertEqual(len(text) % 4, 0)
        words = struct.unpack('<' + 'I' * (len(text) // 4), text)
        # DMB OSHST / DSB OSH, from the actual AArch64 encodings.
        begin, end = 0xD50332BF, 0xD503339F
        self.assertEqual(words.count(begin), 4)
        self.assertEqual(words.count(end), 4)
        widths = Counter()
        for index, word in enumerate(words):
            if word != begin:
                continue
            finish = words.index(end, index + 1)
            stores = [w for w in words[index + 1:finish]
                      if (w & 0xFFFFFC00) in (0xB9000000, 0xF9000000)]
            self.assertEqual(len(stores), 1, 'missing plain STR between barriers')
            self.assertEqual(stores[0] & 31, 9, 'HYP store must use a real GPR')
            widths[stores[0] & 0xFFFFFC00] += 1
        self.assertEqual(widths, {0xB9000000: 2, 0xF9000000: 2})


if __name__ == '__main__':
    unittest.main()
