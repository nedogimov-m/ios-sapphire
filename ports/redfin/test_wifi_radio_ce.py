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
            #include "wifi_snoc.h"
            #include "wifi_ce.h"
            unsigned check(uint64_t reported,uint64_t posted,unsigned n,unsigned capacity){
                return redfin_wifi_ce_receive_check(reported,posted,n,capacity);
            }
            unsigned owned_mask(unsigned at,unsigned source,unsigned dest){
                return rf_ce_host_config_mask(at,source,dest);
            }
            unsigned usable_mac(const uint8_t *p){return redfin_wifi_mac_usable(p);}
            ''', 'ce_completion')
        cls.lib.check.argtypes = [C.c_uint64, C.c_uint64, C.c_uint, C.c_uint]
        cls.lib.check.restype = C.c_uint
        cls.lib.owned_mask.argtypes = [C.c_uint] * 3
        cls.lib.owned_mask.restype = cls.lib.usable_mac.restype = C.c_uint
        cls.lib.usable_mac.argtypes = [C.c_char_p]

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

    def test_rx_only_ce_keeps_firmware_source_ring_and_source_control_live(self):
        self.assertEqual(self.lib.owned_mask(0x18, 0, 0), 0)
        for at in (0, 4, 8):
            self.assertEqual(self.lib.owned_mask(at, 0, 64), 0)
        self.assertEqual(self.lib.owned_mask(0x0c, 0, 64), 0xffffffff)
        self.assertEqual(self.lib.owned_mask(0x10, 0, 64), 0x1f)
        self.assertEqual(self.lib.owned_mask(0x14, 0, 64), 0xffffffff)
        self.assertEqual(self.lib.owned_mask(0x18, 0, 64), (1 << 19) | (1 << 18))

    def test_tx_only_ce_protects_host_source_geometry_without_claiming_firmware_destination(self):
        self.assertEqual(self.lib.owned_mask(0, 2048, 0), 0xffffffff)
        self.assertEqual(self.lib.owned_mask(4, 2048, 0), 0x1f)
        self.assertEqual(self.lib.owned_mask(8, 2048, 0), 0xffffffff)
        for at in (0x0c, 0x10, 0x14):
            self.assertEqual(self.lib.owned_mask(at, 2048, 0), 0)
        self.assertEqual(self.lib.owned_mask(0x18, 2048, 0), (1 << 19) | (1 << 17) | 0xffff)
        for at in (0x2c, 0x30, 0x3c, 0x40, 0x44, 0x48):
            self.assertEqual(self.lib.owned_mask(at, 2048, 512), 0)

    def test_zero_multicast_and_broadcast_firmware_macs_need_a_local_unicast_address(self):
        for value in (None, bytes(6), bytes.fromhex('010000000001'), b'\xff' * 6):
            self.assertEqual(self.lib.usable_mac(value), 0)
        for value in ('002611223344', '020000000000', 'feffffffffff'):
            self.assertEqual(self.lib.usable_mac(bytes.fromhex(value)), 1)


if __name__ == '__main__':
    unittest.main()
