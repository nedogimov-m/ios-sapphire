"""Exercise the native PIL BCM parser/votes and bounded PAS4 executor."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_rpmh_probe import added_file

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "redfin_rpmh.h"
#include "wifi_bw.h"
#include "redfin_scm_query.h"
#include "wifi_pas.h"
static uint8_t db[RF_CMDDB_BYTES];
static struct rf_wifi_bcm bcm;
static struct rf_sq_report report;
static struct rf_sq_regs first;
static unsigned calls,mode,unsafe;
static bool owner;
static uint64_t clock_ns;
static bool valid(void *p){return p==&report && owner;}
static uint64_t now(void *p){(void)p;return clock_ns;}
static void delay(void *p,unsigned us){(void)p;clock_ns+=(uint64_t)us*1000;}
static int invoke(void *p,struct rf_sq_regs *r) {
 if(p!=&report || !owner)return -91;
 ++calls;
 if(calls==1)first=*r;
 else if(mode==4 || mode==6) {
  if(r->x[0]!=1 || r->x[1]!=41 || r->x[2]!=42 || r->x[6]!=46){++unsafe;return -92;}
 } else if(memcmp(r,&first,sizeof(first))){++unsafe;return -93;}
 if(mode==7)owner=false;
 if(mode==8)clock_ns+=3000000000ULL;
 if((mode==3 && calls==1) || mode==5){r->x[0]=(uint64_t)-12;return 0;}
 if((mode==4 && calls==1) || mode==6){r->x[0]=1;for(unsigned i=1;i<7;++i)r->x[i]=40+i;return 0;}
 r->x[0]=mode==2 ? (uint64_t)-5 : 0;r->x[1]=mode==1 ? 7 : 0;return 0;
}
uint8_t *database(void){return db;}
int lookup(unsigned index){memset(&bcm,0,sizeof(bcm));return rf_wifi_bcm_lookup(db,index,&bcm);}
uint32_t vote(unsigned index){return rf_wifi_bcm_vote(&bcm,index);}
int floor_vote(unsigned index,uint32_t requested,uint32_t inherited,uint32_t *out){return rf_wifi_bcm_floor(index,requested,inherited,out);}
int pas(unsigned selected,unsigned width,unsigned command,uint64_t address,uint64_t bytes) {
 mode=selected;calls=unsafe=0;owner=true;clock_ns=0;memset(&report,0,sizeof(report));
 const struct rf_sq_ops ops={&report,valid,invoke,delay,now};
 return rf_wifi_pas_run(&ops,width,command,address,bytes,&report);
}
uint64_t metric(unsigned which) {
 if(which==0)return calls;if(which==1)return unsafe;if(which==2)return report.resumes;
 if(which==3)return report.busy_retries;if(which==4)return report.completed;
 return which>=8 && which<16 ? first.x[which-8] : 0;
}
'''


class NativeWifiStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'redfin_rpmh.h').write_text(added_file('redfin_rpmh.h'))
        (directory / 'test.c').write_text(HARNESS)
        result = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                                 '-I', str(HERE), '-I', str(HERE / 'include'), '-I', str(directory),
                                 str(directory / 'test.c'), '-o', str(directory / 'test.so')],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.library = C.CDLL(str(directory / 'test.so'))
        cls.library.database.restype = C.c_void_p
        cls.library.vote.restype = C.c_uint32
        cls.library.metric.restype = C.c_uint64
        cls.library.pas.argtypes = [C.c_uint, C.c_uint, C.c_uint, C.c_uint64, C.c_uint64]
        cls.library.floor_vote.argtypes = [C.c_uint, C.c_uint32, C.c_uint32, C.POINTER(C.c_uint32)]

    def setUp(self):
        self.db = bytearray(0x20000)
        struct.pack_into('<II', self.db, 0, 1, 0x0c0330db)
        struct.pack_into('<5H', self.db, 8, 5, 0, 144, 6, 0x1000)
        for i, name in enumerate((b'CE0', b'SN6', b'SN0', b'SH0', b'MC0', b'ACV')):
            at = 144 + i * 24
            self.db[at:at + 8] = name.ljust(8, b'\0')
            struct.pack_into('<IIIHH', self.db, at + 8, 1, 2, 0x50000 + i * 4, 8, i * 8)
            struct.pack_into('<IHBB', self.db, 288 + i * 8, 1000000, 8, i, 0)

    def load(self):
        C.memmove(self.library.database(), bytes(self.db), len(self.db))

    def test_native_table_aux_and_both_pil_clients_produce_the_real_wire_votes(self):
        self.load()
        for i, xy in enumerate(((394, 3936), (197, 1968), (197, 1968), (99, 1968), (394, 16344), (0, 8))):
            with self.subTest(resource=i):
                self.assertEqual(self.library.lookup(i), 0)
                self.assertEqual(self.library.vote(i), 0x60000000 | xy[0] << 14 | xy[1])

    def test_corrupt_bcm_aux_and_out_of_range_tables_fail_before_a_vote(self):
        for offset, fmt, value in ((288, 'I', 0), (292, 'H', 0), (294, 'B', 16),
                                   (295, 'B', 1), (164, 'H', 7), (166, 'H', 65535)):
            with self.subTest(offset=offset):
                self.setUp()
                struct.pack_into('<' + fmt, self.db, offset, value)
                self.load()
                self.assertNotEqual(self.library.lookup(0), 0)
        self.setUp()
        self.db[168:176] = self.db[144:152]
        self.load()
        self.assertNotEqual(self.library.lookup(0), 0)

    def test_observed_inherited_bandwidth_and_foreign_acv_bits_are_retained(self):
        out = C.c_uint32()
        self.assertEqual(self.library.floor_vote(0, 0x60010004, 0x20020003, C.byref(out)), 0)
        self.assertEqual(out.value, 0x60020004)
        self.assertEqual(self.library.floor_vote(5, 0x60000008, 0x20000010, C.byref(out)), 0)
        self.assertEqual(out.value, 0x60000018)
        for old in (0x80000000, 0x10000000, 1):
            self.assertNotEqual(self.library.floor_vote(0, 0x60000001, old, C.byref(out)), 0)

    def test_acv_is_a_bitmask_and_does_not_require_bandwidth_divisors(self):
        struct.pack_into('<IH', self.db, 288 + 5 * 8, 0, 0)
        self.load()
        self.assertEqual(self.library.lookup(5), 0)
        self.assertEqual(self.library.vote(5), 0x60000008)
        struct.pack_into('<B', self.db, 288 + 5 * 8 + 6, 16)
        self.load()
        self.assertNotEqual(self.library.lookup(5), 0)

    def test_pas4_registers_for_every_native_command_and_both_conventions(self):
        for width in (32, 64):
            for command in (1, 2, 5, 6):
                address = 0x8c000000 if command in (1, 2) else 0
                size = 0x11800000 if command == 2 else 0
                self.assertEqual(self.library.pas(0, width, command, address, size), 0)
                self.assertEqual(self.library.metric(0), 1)
                self.assertEqual(self.library.metric(8), 0x02000200 | command | (0x40000000 if width == 64 else 0))
                self.assertEqual(self.library.metric(9), 0x82 if command == 1 else 3 if command == 2 else 1)
                self.assertEqual(self.library.metric(10), 4)
                self.assertEqual(self.library.metric(11), address)
                self.assertEqual(self.library.metric(12), size)

    def test_pas_whitelist_rejects_foreign_functions_ranges_and_conventions(self):
        for width, command, address, size in ((0, 6, 0, 0), (64, 7, 0, 0), (64, 1, 0x51900000, 0),
                                             (64, 2, 0x8c000000, 4096), (64, 5, 0x8c000000, 0)):
            self.assertNotEqual(self.library.pas(0, width, command, address, size), 0)
            self.assertEqual(self.library.metric(0), 0)

    def test_owned_high_metadata_requires_smc64_and_exact_page_geometry(self):
        self.assertEqual(self.library.pas(0, 64, 1, 0x182600000, 0), 0)
        self.assertEqual(self.library.metric(11), 0x182600000)
        for width, address in ((32, 0x182600000), (64, 0x182600001), (64, 0x200000000)):
            self.assertNotEqual(self.library.pas(0, width, 1, address, 0), 0)
            self.assertEqual(self.library.metric(0), 0)

    def test_pas_resumes_preserve_native_cookie_and_busy_retries_restore_request(self):
        for mode, resumes, busy in ((3, 0, 1), (4, 1, 0)):
            self.assertEqual(self.library.pas(mode, 64, 6, 0, 0), 0)
            self.assertEqual([self.library.metric(i) for i in range(4)], [2, 0, resumes, busy])

    def test_separate_pas_failure_transport_failure_timeouts_and_lease_loss_stop(self):
        for mode in (1, 2, 5, 6, 7, 8):
            self.assertNotEqual(self.library.pas(mode, 64, 6, 0, 0), 0)
            self.assertLessEqual(self.library.metric(0), 17)
            self.assertEqual(self.library.metric(1), 0)


if __name__ == '__main__':
    unittest.main()
