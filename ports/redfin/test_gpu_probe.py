"""Compile the actual observer; reject unverified contracts before MMIO."""
import ctypes
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def source():
    patch = Path(__file__).with_name('gpu-probe.patch').read_text()
    section = patch.split('+++ b/bsd/dev/redfin_gpu.c\n', 1)[1].split('diff --git', 1)[0]
    code = '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+') and not line.startswith('+++'))
    code = '\n'.join(line for line in code.splitlines() if not line.startswith('#include'))
    return code.replace('__asm__ volatile("dsb sy" ::: "memory");',
                        '__asm__ volatile("" ::: "memory");')


HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
#include <stdlib.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
typedef void *DTEntry;
static int mode, variant, maps, wrong_map, writes;
static uint32_t gcc[0x1f0000/4], gpucc[0x9000/4];
static uint64_t reg[4];
static uint32_t chip;
static int log_sink(const char *s,...) { (void)s;return 0; }
#define printf log_sink
static int PE_parse_boot_argn(const char *s,void *v,int n) {
 if (strcmp(s,"redfingpu") || n!=4 || mode<0) return 0;
 memcpy(v,&mode,4);return 1;
}
static int SecureDTLookupEntry(void *r,const char *s,DTEntry *e) {
 (void)r;if (strcmp(s,"/redfin-gpu") || variant==1) return -1;
 *e=(void*)1;return 0;
}
static int SecureDTGetProperty(DTEntry e,const char *s,const void **v,unsigned *n) {
 if(e!=(void*)1)abort();
 if(!strcmp(s,"reg")){*v=reg;*n=variant==3?24:sizeof(reg);return 0;}
 if(!strcmp(s,"chip-id")){*v=&chip;*n=4;return 0;}
 return -1;
}
vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t len) {
 maps++;
 if(pa==0x100000 && len==sizeof(gcc))return variant==5?0:(uintptr_t)gcc;
 if(pa==0x3d90000 && len==sizeof(gpucc))return variant==6?0:(uintptr_t)gpucc;
 wrong_map++;return 0;
}
ACTUAL_SOURCE
int host_run(int m,int v,uint32_t cfg) {
 mode=m;variant=v;maps=wrong_map=writes=0;
 memset(gcc,0,sizeof(gcc));memset(gpucc,0,sizeof(gpucc));
 gcc[0x71004/4]=cfg;
 reg[0]=0x100000;reg[1]=0x1f0000;reg[2]=0x3d90000;reg[3]=0x9000;
 chip=v==4?0x06010001:0x06020001;if(v==2)reg[2]=0x5990000;
 int result=redfin_gpu_probe();
 for(unsigned i=0;i<sizeof(gcc)/4;i++)if(gcc[i]!=(i==0x71004/4?cfg:0))writes++;
 for(unsigned i=0;i<sizeof(gpucc)/4;i++)if(gpucc[i])writes++;
 return result;
}
int host_maps(void){return maps;}
int host_bad(void){return wrong_map+writes;}
'''


class RedfinGPUProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root/'probe.c').write_text(HARNESS.replace('ACTUAL_SOURCE', source()))
        subprocess.run([shutil.which('clang') or 'cc', '-std=c11', '-Wall', '-Wextra',
                        '-Werror', '-shared', '-fPIC', str(root/'probe.c'),
                        '-o', str(root/'probe.dylib')], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(root/'probe.dylib'))
        cls.lib.host_run.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint32]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, mode, variant, clock, result, maps):
        self.assertEqual(self.lib.host_run(mode, variant, clock), result)
        self.assertEqual(self.lib.host_maps(), maps)
        self.assertEqual(self.lib.host_bad(), 0)

    def test_disabled_and_unknown_modes_do_not_map(self):
        for mode in (-1, 0, 2, 3, 0x7fffffff):
            self.run_case(mode, 0, 1, errno.ENOTSUP, 0)

    def test_invalid_contract_does_not_map(self):
        for variant in (1, 2, 3, 4):
            self.run_case(1, variant, 1, 22, 0)

    def test_upstream_gate_prevents_gpucc_access(self):
        for clock in (0, 0x80000000, 0x80000001, 0xffffffff):
            self.run_case(1, 0, clock, errno.EAGAIN, 1)

    def test_success_only_maps_clock_controllers_and_never_writes(self):
        for clock in (1, 3, 0x10001):
            self.run_case(1, 0, clock, 0, 2)

    def test_mapping_failures_stop(self):
        self.run_case(1, 5, 1, 12, 1)
        self.run_case(1, 6, 1, 12, 2)


if __name__ == '__main__':
    unittest.main()
