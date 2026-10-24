"""Native WCN3990 receive address/metadata and exact posted-buffer guard."""
import ctypes as C
from pathlib import Path
import tempfile
import unittest

from test_smp_gui import compile_shared


class RadioCECompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.lib = compile_shared(Path(cls.tmp.name), '''#include "wifi_radio.h"
            unsigned check(uint64_t reported,uint64_t posted,unsigned n,unsigned capacity){
                return redfin_wifi_ce_receive_check(reported,posted,n,capacity);
            }
            ''', 'ce_completion')
        cls.lib.check.argtypes = [C.c_uint64, C.c_uint64, C.c_uint, C.c_uint]
        cls.lib.check.restype = C.c_uint

    def test_native_upper_metadata_does_not_change_the_owned_dma_address(self):
        posted = 0xfed76000
        for extra in (0, 0xfffffff800000000, *(1 << bit for bit in range(35, 64))):
            self.assertEqual(self.lib.check(posted | extra, posted, 64, 2048), 0, hex(extra))

    def test_every_foreign_hardware_address_bit_is_rejected_even_with_valid_metadata(self):
        posted = 0xfed76000
        for bit in range(35):
            self.assertEqual(self.lib.check((posted ^ (1 << bit)) | (1 << 63), posted, 64, 2048), 2, bit)
        for invalid in (0, 1 << 35, (1 << 35) | posted):
            self.assertEqual(self.lib.check(invalid, invalid, 64, 2048), 2)

    def test_zero_and_oversized_payloads_never_pass_the_posted_buffer_capacity(self):
        posted = 0xfed76000
        for count in (0, 2049, 65535):
            self.assertEqual(self.lib.check(posted, posted, count, 2048), 1)
        for count in (1, 64, 2048):
            self.assertEqual(self.lib.check(posted, posted, count, 2048), 0)


if __name__ == '__main__':
    unittest.main()
