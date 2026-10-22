"""Execute the early marker emitter that binds pre-IOKit failures to an image."""
import ctypes
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest


class EarlyBootIDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        patch = Path(__file__).with_name('early-bootid.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        actual = added.split('/* REDFIN_EARLY_BOOT_ID_BEGIN */', 1)[1].split(
            '/* REDFIN_EARLY_BOOT_ID_END */', 1)[0]
        source = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
static uint64_t nonce;
static int present;
static char output[64];
static unsigned used;
static bool PE_parse_boot_argn(const char *name,void *out,unsigned bytes) {
 assert(!strcmp(name,"redfinbootid") && bytes==sizeof(uint64_t));
 memcpy(out,&nonce,bytes);return present;
}
static void redfin_log_putc(char c) { assert(used<sizeof(output)-1);output[used++]=c; }
'''
        source += actual + r'''
const char *emit(uint64_t value,int exists) {
 nonce=value;present=exists;used=0;memset(output,0,sizeof(output));
 redfin_log_boot_id();return output;
}
'''
        (root / 'marker.c').write_text(source)
        library = root / 'marker.dylib'
        subprocess.run([shutil.which('cc') or 'cc', '-shared', '-fPIC', '-Wall', '-Wextra',
                        '-Werror', str(root / 'marker.c'), '-o', str(library)], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.emit.argtypes = [ctypes.c_uint64, ctypes.c_int]
        cls.lib.emit.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_u64_bits_are_preserved_in_one_canonical_line(self):
        rng = random.Random(17)
        for nonce in [1, (1 << 64) - 1, 1 << 63, *[1 << bit for bit in range(64)],
                      *[rng.getrandbits(64) or 1 for _ in range(100)]]:
            self.assertEqual(self.lib.emit(nonce, 1), f'REDFIN BOOT ID: {nonce:016x}\n'.encode())

    def test_absent_or_zero_nonce_emits_nothing(self):
        self.assertEqual(self.lib.emit(0, 1), b'')
        self.assertEqual(self.lib.emit(0x123456789abcdef0, 0), b'')


if __name__ == '__main__':
    unittest.main()
