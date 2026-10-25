"""The actual failed runtime captures an owned FAR/PTE before revoking its lease."""
import ctypes as C
import errno
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
HARNESS=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include "include/redfin_gpu_runtime.h"
struct gm_context {unsigned smmu_mode;uintptr_t cb;};
static struct gm_context context;
static uint32_t banks[0x1000/4];static uint64_t leaves[RF_GR_BYTES/4096],l2[512];
static struct {struct gm_context *context;unsigned dvfs_index;void *dvfs_profile;struct {struct {unsigned khz;}gpu[16];}performance;}gx;
static struct {uint32_t state,fence,completed,fault_fsr,fault_syndrome;uint64_t fault_address;bool fault_captured;uint64_t *leaves,*l2;}gr;
static unsigned lease,valid,reads,poisons,diagnostics,diagnostic_live;static int error;
static char logged[1024];
static bool redfin_gpu_ready(void){return gr.state==1;}
static bool redfin_gui_cpu0(void){return false;}
static bool redfin_gpu_runtime_caller(void){return gr.state==1&&lease;}
static int gx_check(void *p){(void)p;return error;}
static bool gm_valid(void *p){return p==&context&&valid&&redfin_gpu_runtime_caller();}
static uint32_t gm_scalar_read(uintptr_t at){++reads;return *(uint32_t *)at;}
static void gx_diagnostic(void *p){++diagnostics;diagnostic_live=gm_valid(p);}
static void redfin_gpu_poison(const char *why){(void)why;++poisons;gr.state=2;}
static int host_printf(const char *fmt,...){va_list ap;va_start(ap,fmt);int n=vsnprintf(logged,sizeof(logged),fmt,ap);va_end(ap);return n;}
#define printf host_printf
@ACTUAL@
void reset(uint64_t address,unsigned scenario){
 memset(&gr,0,sizeof(gr));memset(&gx,0,sizeof(gx));memset(banks,0,sizeof(banks));memset(leaves,0,sizeof(leaves));memset(l2,0,sizeof(l2));
 gr.state=1;gr.leaves=leaves;gr.l2=l2;gr.completed=41;gr.fence=42;
 context=(struct gm_context){6,(uintptr_t)banks};gx.context=&context;gx.dvfs_profile=(void *)1;gx.dvfs_index=4;gx.performance.gpu[4].khz=625000;
 banks[0x58/4]=2;banks[0x60/4]=(uint32_t)address;banks[0x64/4]=(uint32_t)(address>>32);banks[0x68/4]=17;
 if(address>=RF_GR_BASE&&address-RF_GR_BASE<RF_GR_BYTES){leaves[(address-RF_GR_BASE)>>12]=0x180004e43;l2[address>>21]=0x180010003;}
 lease=valid=1;reads=poisons=diagnostics=diagnostic_live=0;logged[0]=0;error=EFAULT;
 if(scenario==1)error=EAGAIN;if(scenario==2)valid=0;if(scenario==3)lease=0;if(scenario==4)error=0;
}
int run(void){return gr_live();}
unsigned metric(unsigned i){unsigned a[]={gr.state,gr.fault_captured,reads,poisons,diagnostics,diagnostic_live,gr.completed,gr.fence};return i<8?a[i]:0;}
const char *log_line(void){return logged;}
'''


class GPUFaultCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        p=Path(cls.temp.name);raw=(HERE/'gpu-runtime.inc').read_text()
        body=raw[raw.index('static int gr_live(void)'):raw.index('/* Runtime snapshots remain complete')]
        (p/'fault.c').write_text(HARNESS.replace('@ACTUAL@',body))
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(HERE),
                        str(p/'fault.c'),'-o',str(p/'fault.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(p/'fault.so'));cls.lib.reset.argtypes=[C.c_uint64,C.c_uint]
        cls.lib.log_line.restype=C.c_char_p;cls.lib.redfin_gpu_fault_info.argtypes=[C.POINTER(C.c_uint64),C.POINTER(C.c_uint32)]

    def test_real_fault_metadata_is_captured_while_lease_is_live_then_dma_is_retained(self):
        self.lib.reset(0x10004000,0);self.assertEqual(self.lib.run(),errno.EFAULT)
        self.assertEqual([self.lib.metric(i) for i in range(8)],[2,1,4,1,1,1,41,42])
        address=C.c_uint64();fsr=C.c_uint32();self.assertTrue(self.lib.redfin_gpu_fault_info(C.byref(address),C.byref(fsr)))
        self.assertEqual((address.value,fsr.value),(0x10004000,2))
        log=self.lib.log_line();self.assertIn(b'PTE=0x180004e43',log)
        self.assertIn(b'completed=41 issued=42',log)
        self.assertEqual(self.lib.run(),errno.ENXIO);self.assertEqual(self.lib.metric(2),4)

    def test_high_far_or_guard_address_is_retained_exactly_without_indexing_outside_owned_tables(self):
        for address in [0,0x0fffffff,0x30000000,0x4010004000,0xffffffffffffffff]:
            self.lib.reset(address,0);self.assertEqual(self.lib.run(),errno.EFAULT)
            value=C.c_uint64();fsr=C.c_uint32();self.assertTrue(self.lib.redfin_gpu_fault_info(C.byref(value),C.byref(fsr)))
            self.assertEqual(value.value,address);self.assertIn(b'PTE=0 ',self.lib.log_line())

    def test_lost_parent_or_cpu_ownership_cannot_authorize_any_diagnostic_mmio(self):
        for scenario in [1,2,3]:
            self.lib.reset(0x10004000,scenario);self.assertNotEqual(self.lib.run(),0)
            self.assertEqual(self.lib.metric(2),0);self.assertEqual(self.lib.metric(4),0)

    def test_healthy_runtime_does_not_read_or_manufacture_a_fault(self):
        self.lib.reset(0x10004000,4);self.assertEqual(self.lib.run(),0)
        self.assertEqual((self.lib.metric(1),self.lib.metric(2),self.lib.metric(3)),(0,0,0))
