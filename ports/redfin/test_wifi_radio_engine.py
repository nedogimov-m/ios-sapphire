"""Execute actual public-patch CE code with native ring ownership and DMA metadata."""
import ctypes as C
import errno
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_smp_gui import compile_shared

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def ce_source(directory):
    name = 'iokit/Kernel/arm/TopazModem.cpp'
    tree = directory / 'source'
    tree.mkdir()
    for patch in [*sorted((ROOT / 'xnu/patches').glob('*.patch')), HERE / 'wifi-radio.patch']:
        if ('+++ b/' + name + '\n').encode() not in patch.read_bytes():
            continue
        subprocess.run(['git', 'apply', '--include=' + name, str(patch)], cwd=tree,
                       check=True, capture_output=True)
    source = (tree / name).read_text()
    return source.split('#define CE_COUNT', 1)[1].split('/* ---------------- HTC', 1)[0]


class NativeRadioEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        source = ce_source(root)
        stub = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "wifi_radio.h"
#define MIN(a,b) ((a)<(b)?(a):(b))
#define LOG(...) ((void)0)
#define g_ms 0
#define CE_PA 0
static struct redfin_wifi_radio_ops rf_radio_bus;
static int rf_radio_error;
static uint32_t registers[0x10000/4];
static uint8_t arena[2*1024*1024] __attribute__((aligned(4096)));
static unsigned used,maps,violations,ce5_writes,received,shadow_ce;
static void mb(void){}
static void *ml_io_map(uint64_t pa,uint64_t size){(void)pa;(void)size;maps++;return NULL;}
static uint32_t r32(volatile uint8_t *base,unsigned at){(void)base;return registers[at/4];}
static void w32(volatile uint8_t *base,unsigned at,uint32_t v){(void)base;registers[at/4]=v;}
static void *pool_alloc(uint64_t bytes,uint64_t *physical){
 unsigned take=(unsigned)((bytes+4095u)&~4095ull);
 if(take>sizeof(arena)-used)return NULL;
 void *out=arena+used;*physical=0xfed74000u+used;used+=take;memset(out,0,take);return out;
}
static int check(void *ctx){return ctx==arena?0:EPERM;}
static int read_register(void *ctx,uint32_t at,uint32_t *out){
 if(check(ctx)||at%4||at>=sizeof(registers)){violations++;return EPERM;}*out=registers[at/4];return 0;
}
static int write_register(void *ctx,uint32_t at,uint32_t value){
 if(check(ctx)||at%4||at>=sizeof(registers)){violations++;return EPERM;}
 if(at/0x1000==5 || at/0x1000==6)ce5_writes++;
 registers[at/4]=value;return 0;
}
static int shadow(void *ctx,unsigned c,uint32_t value){
 (void)value;if(check(ctx)||(c!=0&&c!=3&&c!=4)){violations++;return EPERM;}shadow_ce|=1u<<c;return 0;
}
'''
        wrapper = r'''
static void htc_rx(uint32_t c,const uint8_t *p,uint32_t n){
 if(c!=2||p!=ce[2].rx_buf||n!=64)violations++;received++;
}
int run(unsigned fault){
 memset(registers,0,sizeof(registers));memset(ce,0,sizeof(ce));
 used=maps=violations=ce5_writes=received=shadow_ce=0;ce_up=false;rf_radio_error=0;
 rf_radio_bus=(struct redfin_wifi_radio_ops){arena,check,NULL,read_register,write_register,shadow};
 registers[0x500c/4]=0x8ba6cf00;registers[0x5010/4]=0x30;registers[0x5014/4]=1024;
 if(!ce_start())return -1;
 if(ce_host_rx(5)||ce[5].src_n||ce[5].dst_n||ce[5].rx_buf||ce5_writes||maps||violations)return -2;
 if(registers[0x500c/4]!=0x8ba6cf00||registers[0x5010/4]!=0x30||registers[0x5014/4]!=1024)return -3;
 if(fault==0)return 0;
 ce[2].dst[0].nbytes=fault==3?2049:64;
 ce[2].dst[0].addr|=1ull<<36; /* WCN3990 completion metadata is not address. */
 if(fault==2)ce[2].dst[0].addr^=4;
 bool any=ce_poll();
 if(fault==2||fault==3)return !any&&rf_radio_error==EOVERFLOW&&!received?0:-4;
 if(!any||rf_radio_error||received!=1||violations)return -5;
 const uint32_t frame=0x11223344;
 if(!ce_send(3,&frame,sizeof(frame),2)||!ce_send(4,&frame,sizeof(frame),1))return -6;
 return shadow_ce==((1u<<3)|(1u<<4))&&!violations?0:-7;
}
unsigned metric(unsigned n){const unsigned v[]={used,maps,ce5_writes,received,violations,shadow_ce};return n<6?v[n]:0;}
'''
        cls.lib = compile_shared(root, stub + '#define CE_COUNT' + source + wrapper, 'ce_engine')
        cls.lib.metric.restype = C.c_uint

    def test_native_start_preserves_firmware_ce5_and_never_posts_or_polls_it(self):
        self.assertEqual(self.lib.run(0), 0)
        self.assertEqual(self.lib.metric(1), 0)
        self.assertEqual(self.lib.metric(2), 0)

    def test_actual_poll_accepts_metadata_and_actual_tx_uses_both_native_data_pipes(self):
        self.assertEqual(self.lib.run(1), 0)
        self.assertEqual(self.lib.metric(3), 1)
        self.assertEqual(self.lib.metric(5), (1 << 3) | (1 << 4))

    def test_actual_poll_refuses_foreign_address_and_oversized_data_before_dispatch(self):
        for fault in (2, 3):
            self.assertEqual(self.lib.run(fault), 0)
            self.assertEqual(self.lib.metric(3), 0)


if __name__ == '__main__':
    unittest.main()
