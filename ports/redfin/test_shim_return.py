"""Run the real shim guard and shared leaf against recorded fixed-window MMIO."""
import ctypes as C
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).parent
PREFIX = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include "fdt.h"
static struct hardware hardware;
static uint64_t runtime_el,runtime_mpidr,runtime_sctlr,runtime_daif,frequency,counter;
static unsigned fault,reads,writes,violations,transactions,observes,polls,relaxes,spare,subtype,imem;
static uint64_t redfin_shim_er_el(void){return runtime_el;}
static uint64_t redfin_shim_er_mpidr(void){return runtime_mpidr;}
static uint64_t redfin_shim_er_sctlr(void){return runtime_sctlr;}
static uint64_t redfin_shim_er_daif(void){return runtime_daif;}
static uint32_t redfin_er_rd(uintptr_t base,unsigned offset){
 reads++;
 if(base==0x0c440000){
  if(!offset)return fault==1?0x40000000:0x50000000;
  if(offset<0x900 || offset>=0x1100 || (offset&3)){violations++;return 0;}
  return offset==0x900+7*4 && fault!=2?0x800:0;
 }
 if(base==0x0c40a000){if(offset!=0x700+7*4)violations++;return fault==3?1:0;}
 if(base==0x0e600000){
  if(offset==7*0x80+8){polls++;return fault==10?0:fault==11?9:1;}
  if(offset==7*0x80+0x18)return observes==1?subtype:spare;
  violations++;return 0;
 }
 if(base==0x0c670000 && offset==8){polls++;return fault==12?0:fault==13?9:1;}
 if(base==0x146ab65c && !offset)return fault==14?0:imem;
 violations++;return 0;
}
static void redfin_er_wr(uintptr_t base,unsigned offset,uint32_t value){
 writes++;
 if(base==0x0e600000 && offset==7*0x80){
  if(value!=(observes?0x80008f0:0x8000050))violations++;
  observes++;transactions++;return;
 }
 if(base==0x0c670000 && offset==0x10){
  if(value!=((spare&1)|4) || observes!=2)violations++;
  spare=value;return;
 }
 if(base==0x0c670000 && !offset){if(value!=0x8f0)violations++;transactions++;return;}
 if(base==0x146ab65c && !offset){if(value!=0x77665500 || observes!=3)violations++;imem=value;return;}
 violations++;
}
static void redfin_er_read_start(void){}
static void redfin_er_data_done(void){}
static void redfin_er_command_done(void){}
static void redfin_er_imem_done(void){}
static uint64_t redfin_er_counter(void){if(fault!=4)counter+=20;return counter;}
static uint64_t redfin_er_frequency(void){return frequency;}
static void redfin_er_relax(void){relaxes++;}
'''
SUFFIX = r'''
static struct redfin_shim_er_report report;
void reset(void){
 memset(&hardware,0,sizeof(hardware));memset(&report,0,sizeof(report));
 hardware.redfin=hardware.psci_smc=1;runtime_el=4;runtime_mpidr=0x80000000;
 runtime_sctlr=0x30500800;runtime_daif=0x3c0;frequency=19200000;counter=0;
 fault=reads=writes=violations=transactions=observes=polls=relaxes=imem=0;
 spare=0x10;subtype=4;redfin_shim_er_attempted=0;
}
void set(unsigned kind,uint64_t value){
 switch(kind){case 0:fault=value;break;case 1:hardware.redfin=value;break;
 case 2:hardware.psci_smc=value;break;case 3:runtime_el=value;break;
 case 4:runtime_mpidr=value;break;case 5:runtime_sctlr=value;break;
 case 6:runtime_daif=value;break;case 7:frequency=value;break;
 case 8:subtype=value;break;case 9:spare=value;break;
 case 10:counter=value;break;default:violations++;}
}
int run(unsigned mode){return redfin_shim_prearm(mode==1?NULL:&hardware,mode==2?NULL:&report);}
unsigned stat(unsigned n){
 const unsigned values[]={reads,writes,violations,transactions,observes,polls,relaxes,spare,imem,
  redfin_shim_er_attempted,report.stage,(unsigned)report.error,report.leaf.stage,
  report.leaf.pon_issued,report.leaf.imem_issued,report.target.apid};
 return n<16?values[n]:0;
}
'''


class ShimReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        leaf = (HERE / 'early-return.h').read_text()
        leaf = re.sub(r'/\* REDFIN_EARLY_RETURN_HW_BEGIN \*/.*?/\* REDFIN_EARLY_RETURN_HW_END \*/', '', leaf, flags=re.S)
        wrapper = (HERE / 'shim-return.h').read_text()
        wrapper = re.sub(r'/\* REDFIN_SHIM_RETURN_HW_BEGIN \*/.*?/\* REDFIN_SHIM_RETURN_HW_END \*/', '', wrapper, flags=re.S)
        source = root / 'shim.c'
        source.write_text(PREFIX + leaf + wrapper + SUFFIX)
        output = root / 'shim.so'
        subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
                        '-Wall', '-Wextra', '-Werror', '-I', str(HERE), str(source), '-o', str(output)],
                       check=True, capture_output=True)
        cls.lib = C.CDLL(str(output))
        cls.lib.set.argtypes = [C.c_uint, C.c_uint64]
        cls.lib.run.argtypes = [C.c_uint]
        cls.lib.stat.argtypes = [C.c_uint]

    def setUp(self):
        self.lib.reset()

    def test_fixed_physical_windows_and_canonical_arm(self):
        self.assertEqual(self.lib.run(0), 0)
        self.assertEqual([self.lib.stat(i) for i in range(1, 10)],
                         [6, 0, 4, 3, 4, 0, 4, 0x77665500, 1])
        self.assertEqual([self.lib.stat(i) for i in range(10, 16)], [4, 0, 6, 1, 1, 7])

    def test_wrong_cpu_el_caches_daif_and_hardware_never_access_mmio(self):
        cases = [(1, 0), (1, 2), (2, 0), (2, 2), (3, 8), (3, 12),
                 (4, 0x81000600), (4, 0x100000000), (4, 0x100000600),
                 (5, 1), (5, 4), (5, 5)]
        cases += [(6, 0x3c0 ^ bit) for bit in (0x200, 0x100, 0x80, 0x40)]
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                self.lib.reset();self.lib.set(kind, value)
                self.assertEqual(self.lib.run(0), 1)
                self.assertEqual([self.lib.stat(i) for i in (0, 1, 9)], [0, 0, 0])
        for mode in (1, 2):
            self.lib.reset()
            self.assertEqual(self.lib.run(mode), 1)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 9)], [0, 0, 0])

    def test_counter_frequency_and_stall_reject_before_mmio(self):
        for kind, value in ((7, 0), (7, 24000000), (7, 1000000000), (0, 4)):
            self.lib.reset();self.lib.set(kind, value)
            self.assertEqual(self.lib.run(0), 6)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 9, 10)], [0, 0, 1, 1])
            self.assertEqual(self.lib.run(0), 8)
            self.assertEqual([self.lib.stat(i) for i in (0, 1)], [0, 0])
        self.assertEqual(self.lib.stat(6), 4096)

    def test_success_and_discovery_failure_are_once_only(self):
        for fault in (0, 1, 2, 3):
            self.lib.reset();self.lib.set(0, fault)
            self.assertEqual(self.lib.run(0), (0, 2, 3, 3)[fault])
            counts = [self.lib.stat(i) for i in range(9)]
            self.assertEqual(self.lib.run(0), 8)
            self.assertEqual([self.lib.stat(i) for i in range(9)], counts)

    def test_subtype_and_transaction_failures_stop_without_reset_or_imem(self):
        for fault, expected in ((10, 5), (11, 4), (12, 5), (13, 4), (14, 4)):
            with self.subTest(fault=fault):
                self.lib.reset();self.lib.set(0, fault)
                self.assertEqual(self.lib.run(0), expected)
                self.assertEqual(self.lib.stat(2), 0)
                self.assertEqual(self.lib.stat(5), 1000 if fault == 10 else 1002 if fault == 12 else 1 if fault == 11 else 3 if fault == 13 else 4)
                self.assertEqual(self.lib.stat(14), int(fault == 14))
                counts = [self.lib.stat(i) for i in range(9)]
                self.assertEqual(self.lib.run(0), 8)
                self.assertEqual([self.lib.stat(i) for i in range(9)], counts)
        self.lib.reset();self.lib.set(8, 5)
        self.assertEqual(self.lib.run(0), 2)
        self.assertEqual([self.lib.stat(i) for i in (3, 13, 14)], [1, 0, 0])

    def test_prior_bit_zero_and_counter_wrap_are_preserved(self):
        self.lib.set(9, 0x11);self.lib.set(10, 2**64 - 5)
        self.assertEqual(self.lib.run(0), 0)
        self.assertEqual(self.lib.stat(7), 5)
        self.assertEqual(self.lib.stat(2), 0)

    def test_native_freestanding_object_has_no_external_calls_or_exclusives(self):
        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang unavailable')
        root = Path(self.temp.name)
        source = root / 'native-shim.c'
        source.write_text('#include "shim-return.h"\nint exercise(const struct hardware *h,'
                          'struct redfin_shim_er_report *r){return redfin_shim_prearm(h,r);}\n')
        common = [compiler, '--target=aarch64-none-elf', '-mcpu=cortex-a55', '-mno-outline-atomics',
                  '-ffreestanding', '-fno-builtin', '-mgeneral-regs-only', '-mstrict-align',
                  '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(HERE)]
        for output, switch in (('native-shim.s', '-S'), ('native-shim.o', '-c')):
            result = subprocess.run(common + [switch, str(source), '-o', str(root / output)],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        assembly = (root / 'native-shim.s').read_text()
        self.assertNotRegex(assembly.lower(), r'(?m)^\s*(?:smc|hvc|ldxr|ldaxr|stxr|stlxr|blr)\s')
        definitions = set(re.findall(r'(?m)^([A-Za-z_][A-Za-z_0-9]*):', assembly))
        calls = set(re.findall(r'(?m)^\s*bl\s+([A-Za-z_][A-Za-z_0-9]*)', assembly))
        self.assertTrue(calls <= definitions, calls - definitions)
        for register in ('mpidr_el1', 'currentel', 'sctlr_el1', 'daif', 'cntpct_el0', 'cntfrq_el0'):
            self.assertIn(register, assembly.lower())


if __name__ == '__main__':
    unittest.main()
