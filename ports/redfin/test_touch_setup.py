"""Run the actual cold-setup C against MMIO, GPIO and clock handoff models."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch import added_file


class TouchSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host compiler unavailable")
        patch = Path(__file__).with_name("touch-setup.patch").read_text()
        source = added_file(patch, "bsd/dev/redfin_touch_setup.c")
        source = re.sub(r"^#include.*\n", "", source, flags=re.M)
        source = source.replace('*(volatile const uint32_t *)(base + offset)', 'model_read(base, offset)')
        source = source.replace('*(volatile uint32_t *)(base + offset) = value;', 'model_write(base, offset, value);')
        source = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', source)
        stub = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
#define printf model_printf
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
static int model_printf(const char *f,...) {(void)f;return 0;}
static unsigned fault,mode,enabled,maps,writes,se_reads,se_writes,pin_writes,dfs_writes;
static unsigned wait_us,id_calls,violations,gic_reads,reset_high_writes,serial_reads;
static uint32_t vote,cfg,dfs,cmd,se[0x1000/4],pins[7][2];
static const uint64_t ranges[]={0x100000,0x1f0000,0x880000,0x4000,0xf000000,0x1000000};
static const uint32_t gpio[]={8,9,35},dimensions[]={1080,2340},spi_mode=3,cs=0,hz=10000000;
static const unsigned pin_page[]={4,4,5,6,6,7,7},pin_offset[]={0,0x1000,0x3000,0x2000,0x3000,0,0x1000};
static int PE_parse_boot_argn(const char *n,void *out,int size){
    (void)size;*(uint32_t *)out=!strcmp(n,"redfintouch") ? mode : enabled;return 1;
}
static int SecureDTLookupEntry(void *root,const char *name,DTEntry *out){
    (void)root;(void)name;*out=(void *)1;return fault==30 ? -1 : 0;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *n){
    (void)node;
    if(!strcmp(name,"compatible")){*out="redfin,sec-touch";*n=sizeof("redfin,sec-touch");}
    else if(!strcmp(name,"reg")){*out=ranges;*n=sizeof(ranges);}
    else if(!strcmp(name,"spi-mode")){*out=&spi_mode;*n=4;}
    else if(!strcmp(name,"chip-select")){*out=&cs;*n=4;}
    else if(!strcmp(name,"spi-max-frequency")){*out=&hz;*n=4;}
    else if(!strcmp(name,"touch-gpios")){*out=gpio;*n=sizeof(gpio);}
    else if(!strcmp(name,"touch-size")){*out=dimensions;*n=sizeof(dimensions);}
    else {violations++;return -1;}
    if(fault==31 && !strcmp(name,"reg"))(*n)--;
    if(fault==32 && !strcmp(name,"compatible"))(*n)--;
    if((fault==34 && !strcmp(name,"compatible")) || (fault==35 && !strcmp(name,"reg")) ||
       (fault==36 && !strcmp(name,"spi-mode")))*out=NULL;
    return 0;
}
vm_offset_t ml_io_map(vm_offset_t p,vm_size_t size){
    maps++;
    if(p==0x100000 && size==0x1f0000)return 1;
    if(p==0x880000 && size==0x4000)return 2;
    if(p==0x17a00000 && size==0x10000)return 3;
    const uint64_t pa[]={0xf508000,0xf920000,0xf928000,0xf92c000};
    for(unsigned i=0;i<4;i++)if(p==pa[i] && size==0x4000)return fault==33 && i==3 ? 0 : 4+i;
    violations++;return 0;
}
static int pin_index(unsigned page,unsigned offset){
    for(unsigned i=0;i<7;i++)if(page==pin_page[i] && (offset==pin_offset[i] || offset==pin_offset[i]+4))return (int)i;
    return -1;
}
static uint32_t model_read(vm_offset_t base,unsigned offset){
    if(base==1){
        if(offset==0x52008)return vote;
        if(offset==0x17014)return cfg;
        if(offset==0x17024)return dfs;
        if(offset==0x17010)return cmd;
        if(offset==0x17008)return 0x80000002; /* Source-proven HWCG skip path. */
        unsigned mask=offset==0x17004 ? 0x40 : offset==0x1700c ? 0x400 :
            offset==0x23000 ? 0x100 : offset==0x23008 ? 0x200 : 0;
        if(mask){if(offset==0x1700c)serial_reads++;return (vote&mask) && !(fault==1 && mask==0x400) ? 0 : 0x80000000;}
    }else if(base==2){
        se_reads++;
        if((vote&0x7c0)!=0x7c0 || fault==1)violations++; /* No unclocked SE access. */
        if(offset<sizeof(se) && offset%4==0)return se[offset/4];
    }else if(base==3 && offset==0x14c){
        gic_reads++;return fault==14 || (fault==15 && gic_reads>=2) ||
            (fault==16 && gic_reads>=3) ? 1u<<25 : 0;
    }else{
        int pin=pin_index((unsigned)base,offset);
        if(pin>=0)return pins[pin][offset==pin_offset[pin] ? 0 : 1];
    }
    violations++;return 0;
}
static void model_write(vm_offset_t base,unsigned offset,uint32_t value){
    writes++;
    if(base==1){
        if(offset==0x52008){
            if((value&~0x7c0u)!=(vote&~0x7c0u) || (value|vote)!=value)violations++;
            vote=value;return;
        }
        dfs_writes++;
        if(offset==0x17024){if(fault!=11)dfs=value;return;}
        if(offset==0x17014){cfg=value;return;}
        if(offset==0x17010){cmd=fault==10 ? value|1 : value&~1u;return;}
    }else if(base==2){
        se_writes++;
        static const unsigned allowed[]={0xe1c,0x614,0x644,0x48,0x7c,0x28,0xe30,0x224,0x230,0x22c,
            0x250,0x24c,0x25c,0x268,0x278,0x260,0x264,0x284,0x288,0x254,0x24,0x20,0x618,0x648};
        bool found=false;
        for(unsigned i=0;i<sizeof(allowed)/sizeof(allowed[0]);i++)if(offset==allowed[i])found=true;
        if(!found || (vote&0x7c0)!=0x7c0){violations++;return;}
        se[offset/4]=value;return;
    }else{
        int p=pin_index((unsigned)base,offset);
        if(p>=0){
            pin_writes++;
            if(offset==pin_offset[p]){
                if(p==0 && (!(value&0x200) || !(pins[p][1]&2)))violations++; /* latch before OE. */
                if(p==2 && (!(value&0x200) || (pins[p][1]&2)))violations++;
                pins[p][0]=value;
                if(value&0x200){
                    pins[p][1]=(pins[p][1]&~1u)|((pins[p][1]>>1)&1);
                    if(p==0 && fault==12)pins[p][1]&=~1u;
                }
            }else{
                if(p==0){reset_high_writes++;if(!(value&2))violations++;}
                if(p==2 && (value&2))violations++;
                pins[p][1]=(pins[p][1]&1)|(value&~1u);
            }
            return;
        }
    }
    violations++;
}
static void delay(unsigned us){wait_us+=us;}
int redfin_touch_spi_probe(vm_offset_t base,unsigned speed,bool gic_masked){
    id_calls++;
    if(base!=2 || speed!=960000 || !gic_masked || wait_us<70000 || (dfs&1) ||
        (cfg&0x10371f)!=1 || se[0x48/4]!=0x141 || se[0x7c/4] ||
        se[0x224/4]!=1 || se[0x230/4]!=4 || se[0x268/4]!=4 ||
        !(pins[0][1]&1) || (pins[2][1]&1) || (pins[1][0]&0x200))violations++;
    for(unsigned p=3;p<7;p++)if(((pins[p][0]>>2)&15)!=1 || ((pins[p][0]>>6)&7)!=2 || (pins[p][0]&3))violations++;
    return fault==20 ? EIO : 0;
}
'''
        wrapper = r'''
int run(unsigned selected,unsigned setup,unsigned issue,bool rail,bool exclusive){
    mode=selected;enabled=setup;fault=issue;
    maps=writes=se_reads=se_writes=pin_writes=dfs_writes=wait_us=id_calls=violations=gic_reads=reset_high_writes=serial_reads=0;
    memset(se,0,sizeof(se));memset(pins,0,sizeof(pins));redfin_setup_attempted=false;
    vote=0xfc1000;cfg=0x100000;cmd=0x80000000;dfs=0x81;
    for(unsigned i=0;i<7;i++)pins[i][0]=1;
    pins[1][1]=1;pins[6][0]=0;pins[6][1]=1;
    se[0x68/4]=0x101;se[0xe24/4]=se[0xe28/4]=(32u<<24)|(16u<<16);
    se[0x48/4]=0x11;
    if(fault==2)se[0x40/4]=1;
    if(fault==3)se[0x40/4]=0x1000;
    if(fault==4)se[0x68/4]=0x301;
    if(fault==5)se[0x64/4]=1;
    if(fault==6)se[0x258/4]=1;
    if(fault==7)se[0xe18/4]=1;
    if(fault==8)se[0x804/4]=1;
    if(fault==9)se[0x800/4]=1;
    if(fault==13)pins[2][1]=1;
    if(fault==17)pins[3][0]=2u<<2;
    if(fault==18)pins[0][1]=1;
    if(fault==19)vote|=0x400;
    if(fault==21)se[0xe24/4]|=8;
    if(fault==22)pins[3][0]=0x200;
    return redfin_touch_setup(rail,exclusive);
}
unsigned stat(unsigned n){
    const unsigned values[]={maps,writes,se_reads,se_writes,pin_writes,dfs_writes,wait_us,id_calls,
        violations,reset_high_writes,vote,dfs,cfg,serial_reads};
    return n<sizeof(values)/sizeof(values[0]) ? values[n] : 0;
}
unsigned pin_value(unsigned old,unsigned function,unsigned drive,bool output){return redfin_setup_pin_value(old,function,drive,output);}
'''
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        (base / "setup.c").write_text(stub + source + wrapper)
        library = base / "setup.so"
        subprocess.run([cc, "-std=c11", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(base / "setup.c"), "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint] * 3 + [C.c_bool] * 2
        cls.lib.pin_value.argtypes = [C.c_uint] * 3 + [C.c_bool]
        cls.lib.pin_value.restype = C.c_uint

    def run_setup(self, issue=0, mode=2, enabled=1, rail=True, exclusive=True):
        result = self.lib.run(mode, enabled, issue, rail, exclusive)
        self.assertEqual(self.lib.stat(8), 0, "unsafe map/access/write, pre-clock SE read or latch ordering")
        self.assertLessEqual(self.lib.stat(6), 71700)
        return result

    def test_rail_exclusive_and_explicit_mode_before_mapping(self):
        for args in ({"mode": 0}, {"mode": 1}, {"mode": 3}, {"enabled": 0},
                     {"rail": False}, {"exclusive": False}):
            self.assertEqual(self.run_setup(**args), errno.ENOTSUP)
            self.assertEqual(self.lib.stat(0), 0)

    def test_contract_maps_and_cold_ownership_before_writes(self):
        for issue in (13, 14, 17, 18, 19, 22, 30, 31, 32, 33, 34, 35, 36):
            self.assertNotEqual(self.run_setup(issue), 0)
            self.assertEqual(self.lib.stat(1), 0)
            self.assertEqual(self.lib.stat(7), 0)

    def test_clock_timeout_never_reads_unclocked_se(self):
        self.assertEqual(self.run_setup(1), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(2), 0)
        self.assertEqual(self.lib.stat(4), 0)
        self.assertEqual(self.lib.stat(6), 200)

    def test_foreign_busy_dma_gsi_or_wrong_firmware_never_changed(self):
        for issue in range(2, 10):
            self.assertNotEqual(self.run_setup(issue), 0)
            self.assertEqual(self.lib.stat(3), 0)
            self.assertEqual(self.lib.stat(4), 0)
            self.assertEqual(self.lib.stat(5), 0)
            self.assertEqual(self.lib.stat(7), 0)

    def test_dfs_and_rcg_failures_have_finite_timeouts_and_no_gpio_release(self):
        self.assertEqual(self.run_setup(10), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(6), 500)
        self.assertEqual(self.lib.stat(4), 0)
        self.assertEqual(self.run_setup(11), errno.EIO)
        self.assertEqual(self.lib.stat(4), 0)
        self.assertEqual(self.lib.stat(7), 0)

    def test_reset_release_no_low_pulse_and_settles_before_single_id(self):
        self.assertEqual(self.run_setup(), 0)
        self.assertEqual(self.lib.stat(9), 1)
        self.assertEqual(self.lib.stat(6), 70000)
        self.assertEqual(self.lib.stat(7), 1)
        self.assertEqual(self.lib.stat(10) & ~0x7c0, 0xfc1000)
        self.assertEqual(self.lib.stat(10) & 0x7c0, 0x7c0)
        self.assertEqual(self.lib.stat(11), 0x80)
        self.assertEqual(self.lib.stat(12) & 0x10371f, 1)
        self.assertEqual(self.run_setup(21), 0)  # unrelated HW feature bits are preserved/ignored.
        self.assertEqual(self.run_setup(20), errno.EIO)
        self.assertEqual(self.lib.stat(7), 1)

    def test_failed_reset_or_late_gic_enable_prevents_id(self):
        for issue in (12, 15, 16):
            self.assertNotEqual(self.run_setup(issue), 0)
            self.assertEqual(self.lib.stat(7), 0)
        self.assertEqual(self.run_setup(12), errno.EIO)
        self.assertEqual(self.lib.stat(6), 1000)

    def test_pinmux_values_preserve_unrelated_bits_and_enable_present_egpio(self):
        for old in (0, 1, 0x8000, 0x8801, 0x1800, 0xfffffc00):
            value = self.lib.pin_value(old, 1, 2, False)
            self.assertEqual(value & 0x3ff, 0x84)
            self.assertEqual(value & 0x8000, old & 0x8000)
            if old & 0x800:
                self.assertTrue(value & 0x1000)


if __name__ == "__main__":
    unittest.main()
