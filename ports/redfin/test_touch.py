"""Execute the overlay's actual SEC parser and probe using a host MMIO model."""
import ctypes as C
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def added_file(patch, name):
    chunk = patch.split(f"diff --git a/{name} b/{name}\n", 1)[1]
    chunk = chunk.split("\ndiff --git ", 1)[0]
    return "\n".join(line[1:] for line in chunk.splitlines()
                     if line.startswith("+") and not line.startswith("+++")) + "\n"


class Contact(C.Structure):
    _fields_ = [(key, C.c_uint) for key in
                ("finger", "action", "x", "y", "type", "remaining")]


class TouchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host C compiler unavailable")
        cls.patch = Path(__file__).with_name("touch.patch").read_text()
        header = added_file(cls.patch, "bsd/dev/redfin_touch_protocol.h")
        source = added_file(cls.patch, "bsd/dev/redfin_touch.c")
        cls.source = source
        source = re.sub(r"^#include.*\n", "", source, flags=re.M)
        source = source.replace('*(volatile const uint32_t *)(base + offset)',
                                'model_read(base, offset)')
        source = source.replace('__asm__ volatile("dmb oshld" ::: "memory");', '(void)0;')
        stub = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
#define printf model_printf
static int model_printf(const char *format,...) {(void)format;return 0;}
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
static uint32_t mode, clocks[5];
static int bad, maps, reads, se_maps, violation, tlmm_maps;
static uint64_t regs[6];
static const uint64_t expected_regs[] = {0x100000,0x1f0000,0x880000,0x4000,0xf000000,0x1000000};
static const uint32_t gpios[] = {8,9,35}, dimensions[] = {1080,2340};
static const uint32_t spi_mode=3, cs=0, speed=10000000;
static int PE_parse_boot_argn(const char *n,void *p,int size) {
    (void)n; (void)size; *(uint32_t *)p=mode; return 1;
}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out) {
    (void)root; if(strcmp(path,"/redfin-touch")) violation++;
    *out=(void *)1; return bad==1 ? -1 : 0;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *n) {
    (void)node;
    if(!strcmp(name,"compatible")){*out="redfin,sec-touch";*n=sizeof("redfin,sec-touch");}
    else if(!strcmp(name,"reg")){*out=regs;*n=sizeof(regs);}
    else if(!strcmp(name,"spi-mode")){*out=&spi_mode;*n=4;}
    else if(!strcmp(name,"chip-select")){*out=&cs;*n=4;}
    else if(!strcmp(name,"spi-max-frequency")){*out=&speed;*n=4;}
    else if(!strcmp(name,"touch-gpios")){*out=gpios;*n=sizeof(gpios);}
    else if(!strcmp(name,"touch-size")){*out=dimensions;*n=sizeof(dimensions);}
    else {violation++;return -1;}
    if(bad==2 && !strcmp(name,"compatible")) (*n)--;
    if(bad==3 && !strcmp(name,"reg")) (*n)--;
    if(bad==4 && !strcmp(name,"spi-mode")) (*n)--;
    if(bad==5 && !strcmp(name,"chip-select")) (*n)--;
    if(bad==6 && !strcmp(name,"spi-max-frequency")) (*n)--;
    if(bad==7 && !strcmp(name,"touch-gpios")) (*n)--;
    if(bad==8 && !strcmp(name,"touch-size")) (*n)--;
    return 0;
}
vm_offset_t ml_io_map(vm_offset_t base,vm_size_t size) {
    maps++;
    if(base==0x100000 && size==0x1f0000)return 1;
    if(base==0x880000 && size==0x4000){se_maps++;return 2;}
    if(size==0x4000 && (base==0xf508000 || base==0xf920000 ||
        base==0xf928000 || base==0xf92c000)){tlmm_maps++;return base;}
    violation++;return 0;
}
static uint32_t model_read(vm_offset_t base,unsigned offset) {
    reads++;
    if(base==1){
        if(offset==0x17004)return clocks[0];
        if(offset==0x17008)return clocks[1];
        if(offset==0x1700c)return clocks[2];
        if(offset==0x23000)return clocks[3];
        if(offset==0x23008)return clocks[4];
        if(offset==0x52008 || (offset>=0x17010 && offset<=0x17020 && offset%4==0))return 0;
    } else if(base==2){
        static const unsigned allowed[]={0x68,0xe24,0xe28,0x64,0x40,0x800,0x804,0x610,
            0x258,0x224,0x230,0x250,0x24c,0x268,0x25c,0x278,0x48,0x7c,0x260,0x264,0x284,0x288};
        for(unsigned i=0;i<sizeof(allowed)/sizeof(allowed[0]);i++)
            if(offset==allowed[i])return offset==0x68 ? 0x101 : 0;
    } else if(base>=0xf000000 && base<0x10000000 && offset<0x4000){
        static const unsigned pins[]={8,9,35,42,43,44,45};
        for(unsigned i=0;i<sizeof(pins)/sizeof(pins[0]);i++){
            unsigned reg=(pins[i]<=9 ? 0x500000 : 0x900000)+pins[i]*0x1000;
            if(base+offset==0xf000000u+reg || base+offset==0xf000000u+reg+4)return 0;
        }
    }
    violation++;return 0;
}
'''
        wrappers = r'''
unsigned request(unsigned r,unsigned n,uint8_t *o){return redfin_touch_read_request(r,n,o);}
unsigned response_size(unsigned r,unsigned n){return redfin_touch_response_size(r,n);}
unsigned read_delay(unsigned r){return redfin_touch_read_delay(r);}
int valid(unsigned r,unsigned n,const uint8_t *p,unsigned b){return redfin_touch_response_valid(r,n,p,b);}
int decode(const uint8_t *p,unsigned b,struct redfin_touch_contact *o){return redfin_touch_decode(p,b,o);}
int ranges(const uint64_t *p,unsigned n){return redfin_touch_ranges(p,n);}
int probe(unsigned m,int b,unsigned master,unsigned slave,unsigned serial,unsigned core,unsigned core2x){
    mode=m;bad=b;clocks[0]=master;clocks[1]=slave;clocks[2]=serial;
    clocks[3]=core;clocks[4]=core2x;
    maps=reads=se_maps=violation=tlmm_maps=0;redfin_touch_attempted=false;
    memcpy(regs,expected_regs,sizeof(regs));return redfin_touch_probe();
}
int stats(unsigned i){return i==0 ? maps : i==1 ? reads : i==2 ? se_maps : i==4 ? tlmm_maps : violation;}
'''
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        path = Path(cls.tmp.name)
        (path / "touch.c").write_text(stub + header + source + wrappers)
        lib = path / "touch.so"
        subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(path / "touch.c"), "-o", str(lib)], check=True)
        cls.lib = C.CDLL(str(lib))
        cls.lib.ranges.argtypes = [C.POINTER(C.c_uint64), C.c_uint]
        cls.lib.decode.argtypes = [C.POINTER(C.c_uint8), C.c_uint, C.POINTER(Contact)]
        cls.lib.probe.argtypes = [C.c_uint, C.c_int] + [C.c_uint] * 5

    def test_read_allowlist_and_request_framing(self):
        for reg, count in ((0x22, 5), (0x55, 1), (0x60, 8), (0x61, 248)):
            out = (C.c_uint8 * 8)()
            self.assertEqual(self.lib.request(reg, count, out), 8)
            self.assertEqual(bytes(out[:6]), bytes([0xaa, 0, 1, count >> 8, count & 255, reg]))
            self.assertEqual(out[6], sum(out[:6]) & 255)
            self.assertEqual(out[7], 0)
            self.assertEqual(self.lib.read_delay(reg), 500 if reg == 0x61 else 100)
        for reg in range(256):
            if reg not in (0x22, 0x55, 0x60, 0x61):
                self.assertEqual(self.lib.request(reg, 8, (C.c_uint8 * 8)()), 0)
        for reg, count in ((0x22, 4), (0x55, 2), (0x60, 16), (0x61, 0), (0x61, 249), (0x61, 256)):
            self.assertEqual(self.lib.response_size(reg, count), 0)

    def test_response_rejects_corrupt_or_short_frames(self):
        frame = bytearray([0xaa, 0, 1, 0, 5, 0x22, 0, 0x53, 0x45, 0x37, 0x91, 0, 0, 0, 0, 0])
        frame[12] = sum(frame[:12]) & 255
        def valid(value, count=16):
            return self.lib.valid(0x22, 5, (C.c_uint8 * len(value)).from_buffer_copy(value), count)
        self.assertEqual(valid(frame), 1)
        self.assertEqual(valid(frame, 15), 0)
        for pos in range(13):
            corrupt = frame.copy()
            corrupt[pos] ^= 1
            self.assertEqual(valid(corrupt), 0)

    def test_coordinate_bitfields_bounds_and_release(self):
        for x, y, finger, action, kind, left in ((0, 0, 0, 1, 0, 0),
                (1079, 2339, 9, 2, 6, 31), (541, 1171, 2, 3, 5, 1)):
            raw = bytes([(action << 6) | ((finger + 1) << 2), x >> 4, y >> 4,
                         ((x & 15) << 4) | (y & 15), 10, 8, (kind >> 2) << 6, ((kind & 3) << 6) | left])
            out = Contact()
            self.assertEqual(self.lib.decode((C.c_uint8 * 8).from_buffer_copy(raw), 8, C.byref(out)), 1)
            self.assertEqual(tuple(getattr(out, key) for key, _ in out._fields_),
                             (finger, action, x, y, kind, left))
        for raw in (bytes(8), bytes([9, 0, 16, 0, 0, 0, 0, 0])):
            self.assertEqual(self.lib.decode((C.c_uint8 * 8).from_buffer_copy(raw), 8, C.byref(Contact())), 0)
        for raw in ([0x40, 0, 0, 0, 0, 0, 0, 0], [0x6c, 0, 0, 0, 0, 0, 0, 0],
                    [0x44, 67, 0, 0x80, 0, 0, 0, 0], [0x44, 0, 146, 4, 0, 0, 0, 0],
                    [0x44, 0, 0, 0, 0, 0, 0, 32]):
            self.assertEqual(self.lib.decode((C.c_uint8 * 8)(*raw), 8, C.byref(Contact())), -1)

    def test_exact_ranges_and_property_sizes(self):
        expected = [0x100000, 0x1f0000, 0x880000, 0x4000, 0xf000000, 0x1000000]
        self.assertEqual(self.lib.ranges((C.c_uint64 * 6)(*expected), 48), 1)
        for pos in range(6):
            changed = expected.copy()
            changed[pos] += 1
            self.assertEqual(self.lib.ranges((C.c_uint64 * 6)(*changed), 48), 0)
        for bad in range(1, 9):
            self.assertNotEqual(self.lib.probe(1, bad, 0, 0, 0, 0, 0), 0)
            self.assertEqual(self.lib.stats(0), 0)

    def test_default_does_not_map_and_clock_gate_blocks_se(self):
        for mode in (0, 2, 3, 0xffffffff):
            self.assertNotEqual(self.lib.probe(mode, 0, 0, 0, 0, 0, 0), 0)
            self.assertEqual(self.lib.stats(0), 0)
        for position in range(5):
            clocks = [0] * 5
            clocks[position] = 0x80000000
            self.assertNotEqual(self.lib.probe(1, 0, *clocks), 0)
            self.assertEqual(self.lib.stats(2), 0)
            self.assertEqual(self.lib.stats(3), 0)
            self.assertEqual(self.lib.stats(4), 4)
        self.assertEqual(self.lib.probe(1, 0, 0, 0, 0, 0, 0), 0)
        self.assertEqual(self.lib.stats(2), 1)
        self.assertEqual(self.lib.stats(3), 0)
        self.assertEqual(self.lib.stats(4), 4)

    def test_no_hardware_store_or_fifo_read_in_probe(self):
        self.assertEqual(self.source.count("*(volatile const uint32_t *)"), 1)
        self.assertNotIn("*(volatile uint32_t *)", self.source)
        self.assertNotIn("0x700", self.source)
        self.assertNotIn("0x780", self.source)
        self.assertNotIn("sweet_hid_touch", self.source)
        self.assertNotIn('IOKitBSDInit.cpp', self.patch)


if __name__ == "__main__":
    unittest.main()
