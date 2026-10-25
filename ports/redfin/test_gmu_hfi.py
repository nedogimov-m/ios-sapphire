"""Exercise actual kernel HFI queue code with full-sized GPU startup messages."""
import ctypes
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PREFIX = r'''
#include <stdint.h>
#include <string.h>
#include "include/redfin_gmu_start.h"
typedef uintptr_t vm_offset_t;
static uint32_t memory[0x5000/4],registers[0x30000/4];
static struct {struct rf_gb_config config;vm_offset_t hfi,base[RF_GB_UNITS];
 uint64_t messages,sent,received;} gm_start;
static unsigned bad,problem,commands,padding_checks,payload_checks;
static uint64_t now;
static int gm_start_guard(void *p,unsigned phase){
 if(p!=&gm_start || phase!=RF_GB_HFI_LIVE)bad++;return problem==8?ECANCELED:0;
}
static bool gm_payloads_valid(void *p){
 payload_checks++;return p==&gm_start && problem!=9 && !(problem==10 && payload_checks==2);
}
static uint32_t gm_scalar_read(vm_offset_t at){return *(uint32_t *)at;}
static void respond(void){
 uint32_t read=memory[64/4],write=memory[68/4];
 uint32_t request=memory[0xe0/4+read],count=(request>>8)&255u,padded=(count+3u)&~3u;
 if(write!=(read+padded)%1024 || (request>>20)!=(gm_start.sent-1)%4095u+1)bad++;
 for(unsigned i=count;i<padded;i++){
  padding_checks++;if(memory[0xe0/4+(read+i)%1024]!=0xfafafafa)bad++;
 }
 commands++;
 memory[64/4]=write;
 if(problem==1)return;
 uint32_t q=24+48,start=memory[(q+44)/4];unsigned words=(request&255u)==1?4:3;
 uint32_t reply[4]={126u|(words<<8)|(1u<<16),request,problem==3?UINT32_MAX:0,0x20010008};
 if(problem==2)reply[1]^=1u<<20;
 if(problem==11 && gm_start.sent==4096)reply[1]^=1u<<20;
 if(problem==4)reply[0]^=1u<<8;
 if(problem==5)memory[64/4]=(write+4)%1024;
 if(problem==6)reply[0]=100u|(4u<<8);
 for(unsigned i=0;i<4;i++)memory[(0xe0+4096)/4+(start+i)%1024]=reply[i];
 memory[(q+44)/4]=(start+4)%1024;
}
static void gm_memory_store(vm_offset_t at,uint32_t v){
 *(uint32_t *)at=v;
 if(at==(vm_offset_t)registers+0x14650 && v==1)respond();
}
static uint64_t gm_time_ns(void *p){if(p!=&gm_start)bad++;return now;}
static int gm_start_delay(void *p,unsigned us){if(p!=&gm_start||us!=100)bad++;now+=us*1000;return 0;}
static int host_printf(const char *s,...){(void)s;return 0;}
#define printf host_printf
'''
SUFFIX = r'''
int run(unsigned mode,unsigned repeat){
 memset(&gm_start,0,sizeof(gm_start));memset(memory,0,sizeof(memory));memset(registers,0,sizeof(registers));
 bad=commands=padding_checks=payload_checks=0;problem=mode;now=0;
 gm_start.config.hfi_address=0x60001000;gm_start.hfi=(vm_offset_t)memory;
 gm_start.base[0]=(vm_offset_t)registers;
 int rc=redfin_gmu_hfi_init(memory,sizeof(memory),0x60001000,0x20000001);if(rc)return rc;
 uint32_t version=0;
 rc=gm_start_exchange(&gm_start,&version);if(rc)return rc;
 if(version!=0x20010008)bad++;
 for(unsigned n=0;n<repeat;n++){
  uint32_t message[160]={0},reply[255];unsigned count=0;
  message[1]=0x12345678+n;
  rc=gm_start_command(&gm_start,3,message,160,reply,&count);if(rc)return rc;
  if(count!=3||reply[1]!=message[0]||reply[2])bad++;
 }
 return 0;
}
unsigned stat(unsigned i){unsigned a[]={bad,commands,padding_checks,gm_start.sent,gm_start.received,
 memory[64/4],memory[68/4]};return i<7?a[i]:999;}
'''


class GMUHFIQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        source, library = root / 'hfi.c', root / 'hfi.so'
        raw = (HERE / 'gmu-start.inc').read_text()
        first = raw.index('static uint32_t gm_start_hfi_word(')
        last = raw.index('\nstatic int gm_start_resources(', first)
        source.write_text(PREFIX + raw[first:last] + SUFFIX)
        result = subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
            '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-I', str(HERE),
            str(source), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))

    def test_full_native_gpu_tables_repeated_messages_wrap_without_losing_binding(self):
        self.assertEqual(self.lib.run(0, 24), 0)
        self.assertEqual([self.lib.stat(i) for i in range(7)], [0, 25, 2, 25, 25, 772, 772])

    def test_runtime_exceeds_both_old_lifetime_caps_and_wraps_native_sequences_twice(self):
        repeat=9000
        self.assertEqual(self.lib.run(0, repeat), 0)
        self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual([self.lib.stat(i) for i in (1,3,4)], [repeat+1]*3)
        self.assertEqual([self.lib.stat(i) for i in (5,6)], [(4+repeat*160)%1024]*2)

    def test_wrong_echo_is_still_refused_after_native_sequence_rollover(self):
        self.assertEqual(self.lib.run(11, 9000), errno.EPROTO)
        self.assertEqual([self.lib.stat(i) for i in (0,1,3,4)], [0,4096,4096,4095])

    def test_timeout_wrong_echo_firmware_error_malformed_ack_and_wrong_consumer_stop(self):
        for problem, error in ((1, errno.ETIMEDOUT), (2, errno.EPROTO), (3, errno.EIO),
                               (4, errno.EPROTO), (5, errno.EPROTO), (6, errno.EIO),
                               (8, errno.ECANCELED), (9, errno.EAGAIN), (10, errno.EAGAIN)):
            self.assertEqual(self.lib.run(problem, 24), error, problem)
            self.assertLessEqual(self.lib.stat(1), 1)
            self.assertEqual(self.lib.stat(0), 0)


class GMULifecycleTests(unittest.TestCase):
    def test_actual_kernel_guard_accepts_early_hfi_but_keeps_reset_fault_and_ready_rules(self):
        source = (HERE / 'gmu-start.inc').read_text()
        body = re.search(r'^static int gm_start_guard\([^\n]+\)\n\{.*?^\}', source, re.M | re.S)[0]
        harness = r'''
#include <stdint.h>
#include <stdbool.h>
#include "include/redfin_gmu_start.h"
typedef uintptr_t vm_offset_t;
enum {RF_GT_GMU=2};
#define RF_GC_FAULT_BITS 0xc00001feu
struct gm_context {vm_offset_t base[3],cb;};
static uint32_t regs[0x30000/4],bank[0x2000/4];
static struct gm_context context;
static struct {unsigned phase;struct rf_gb_config config;} gm_start;
static bool live;
static bool gm_start_base_valid(void *p){return p==&context && live;}
static uint32_t gm_scalar_read(vm_offset_t at){return *(uint32_t *)at;}
''' + body + r'''
int run(unsigned phase,unsigned reset,unsigned init,unsigned hfi,unsigned issue){
 memset(regs,0,sizeof(regs));memset(bank,0,sizeof(bank));live=true;
 context=(struct gm_context){{0,0,(vm_offset_t)regs},(vm_offset_t)bank};
 gm_start.config.core_version=0x20010008;
 regs[0x14000/4]=reset;regs[0x14070/4]=init;regs[0x14600/4]=hfi;
 regs[0x24c18/4]=0x29;regs[0x1464c/4]=7;
 if(issue==1)regs[0x24c14/4]=1;if(issue==2)bank[0x1058/4]=2;
 if(issue==3)live=false;if(issue==4)regs[0x1464c/4]=0;
 return gm_start_guard(&context,phase);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, library = root / 'guard.c', root / 'guard.so'
            path.write_text(harness)
            subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
                '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-I', str(HERE),
                str(path), '-o', str(library)], check=True, capture_output=True)
            lib = ctypes.CDLL(str(library))
            self.assertEqual(lib.run(0, 1, 0, 0, 0), 0)
            self.assertEqual(lib.run(0, 1, 0, 1, 0), errno.EAGAIN)
            self.assertEqual(lib.run(0, 1, 0x100, 0, 0), errno.EAGAIN)
            for phase in range(1, 5):
                self.assertEqual(lib.run(phase, 0, 0x100, 1, 0), 0)
                self.assertEqual(lib.run(phase, 1, 0x100, 1, 0), errno.EAGAIN)
                self.assertEqual(lib.run(phase, 0, 0x300, 1, 0), errno.EIO)
                self.assertEqual(lib.run(phase, 0, 0x100, 1, 1), errno.EIO)
                self.assertEqual(lib.run(phase, 0, 0x100, 1, 2), errno.EFAULT)
                self.assertEqual(lib.run(phase, 0, 0x100, 1, 3), errno.ECANCELED)
                self.assertEqual(lib.run(phase, 0, 0x100, 1, 4), errno.EAGAIN)
            self.assertEqual(lib.run(4, 0, 0x100, 0, 0), errno.EIO)


if __name__ == '__main__':
    unittest.main()
