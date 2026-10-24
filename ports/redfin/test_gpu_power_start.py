"""Run the actual CX adapter and its synchronous GMU publication boundary."""
import ctypes as C
import errno
from pathlib import Path
import re
import tempfile
import unittest

from test_smp_gui import compile_shared, patched_source

HERE = Path(__file__).resolve().parent
BASE = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfingpu=2 redfingpupower=1 redfinrpmh=1 '
        'redfinspmi=1 redfinreturn=1 redfinbootid=0x1234567890abcdef')

HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
#define printf(...) ((void)0)
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
typedef uintptr_t DTEntry;
/* The transaction leaf is independently tested with real register callbacks.
 * Here its result is controlled so every caller/child boundary is reachable. */
#define rf_gp_run separately_tested_transaction
#include "redfin_gpu_power.h"
#undef rf_gp_run
#include "redfin_gmu_probe.h"
#include "gui-profile.h"
int redfin_gui_cpu0(void){return 0;}
bool redfin_gmu_boot_args_mode(const char *a,unsigned n,unsigned *mode){return redfin_gmu_args_mode(a,n,mode);}
static char arguments[608];
static unsigned fault, maps, contracts, leaves, children, bad;
static uint32_t gcc[0x1f0000/4], other[0x20000/4];
static const char *PE_boot_args(void) { return arguments; }
static uint64_t sysreg(const char *name) {
 return !strcmp(name,"CurrentEL") ? (fault==9 ? 8 : 4) : (fault==10 ? 0x100 : 0);
}
#define __builtin_arm_rsr64(name) sysreg(name)
int redfin_spmi_return_ready(void) { return fault!=8; }
static void delay(unsigned us) { (void)us; }
vm_offset_t ml_io_map(vm_offset_t address,vm_size_t bytes) {
 maps++;
 if(address==0x100000 && bytes==0x1f0000)return (uintptr_t)gcc;
 if((address==0x3d90000 && bytes==0x9000) || (address==0x18220000 && bytes==0x10000) ||
    (address==0x17a00000 && bytes==0x4000))return (uintptr_t)other;
 bad++;return 0;
}
vm_offset_t ml_io_map_wcomb(vm_offset_t address,vm_size_t bytes) {
 maps++;if(address!=0x80860000 || bytes!=0x20000){bad++;return 0;}return (uintptr_t)other;
}
static int SecureDTLookupEntry(void *parent,const char *path,DTEntry *entry) {
 if(parent)bad++;
 if(fault==7)return -1;
 if(!strcmp(path,"/chosen")){*entry=1;return 0;}
 if(!strcmp(path,"/redfin-gpu-power")){*entry=2;return 0;}
 return -1;
}
static int SecureDTGetProperty(DTEntry entry,const char *key,const void **value,unsigned *bytes) {
 static const uint64_t base=0x180000000ULL,size=0x80000000ULL;
 static const uint64_t reg[]={0x3d9106c,4,0x3d91540,4,0x18220000,0x10000,0x80860000,0x20000};
 static const uint32_t parent[]={0x30000,64,65535,7,416},chip=0x06020001;
 if(entry==1 && !strcmp(key,"dram-base")){*value=&base;*bytes=8;return 0;}
 if(entry==1 && !strcmp(key,"dram-size")){*value=&size;*bytes=8;return 0;}
 if(entry==2 && !strcmp(key,"reg")){*value=reg;*bytes=sizeof(reg);return 0;}
 if(entry==2 && !strcmp(key,"cx-parent")){*value=parent;*bytes=sizeof(parent);return 0;}
 if(entry==2 && !strcmp(key,"chip-id")){*value=&chip;*bytes=4;return 0;}
 return -1;
}
int redfin_gmu_probe_contract(const char *args,unsigned bytes) {
 contracts++;
 if(maps || leaves || children || !redfin_gmu_args_valid(args,bytes) ||
    memcmp(args,arguments,bytes))bad++;
 return fault==1 ? ENXIO : 0;
}
static int rf_gp_run(const struct rf_gp_ops *ops,struct rf_gp_report *report) {
 leaves++;
 if(!ops->valid(ops->context) || maps!=5)bad++;
 report->stage=RF_GP_OK;report->parent_held=fault!=3;report->cx_on=fault!=4;
 if(fault==5)arguments[0]='?';
 return fault==2 ? RF_GP_DOMAIN : RF_GP_OK;
}
int redfin_gmu_probe(const char *args,unsigned bytes,void *parent,redfin_gmu_parent_valid_fn valid) {
 children++;
 if(contracts!=1 || leaves!=1 || !parent || !valid || !valid(parent) || valid(NULL) ||
    !redfin_gmu_args_valid(args,bytes) || memcmp(args,arguments,bytes))bad++;
 return fault==6 ? EBUSY : 0;
}
ACTUAL_SOURCE
int run(const char *args,unsigned issue) {
 memset(&gp,0,sizeof(gp));memset(&gp_report,0,sizeof(gp_report));
 memset(gcc,0,sizeof(gcc));memset(other,0,sizeof(other));
 gp_attempted=false;gp_gmu_mode=false;
 fault=issue;maps=contracts=leaves=children=bad=0;
 if(strlen(args)>=sizeof(arguments))return -1;
 memset(arguments,0,sizeof(arguments));memcpy(arguments,args,strlen(args));
 gcc[0x71004/4]=1;
 int result=redfin_gpu_power_probe();
 if(redfin_gpu_power_probe()!=EBUSY)bad++;
 return bad ? -100-(int)bad : result;
}
unsigned count(unsigned n) { unsigned values[]={maps,contracts,leaves,children};return n<4?values[n]:0; }
'''


class GPUPowerStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        for name, source in (('redfin_gpu_power.h', (HERE / 'gpu-power.h').read_text()),
                             ('gui-profile.h', (HERE / 'gui-profile.h').read_text()),
                             ('redfin_gmu_probe.h', (HERE / 'gmu-probe.h').read_text()),
                             ('redfin_rpmh.h', patched_source('bsd/dev/redfin_rpmh.h'))):
            (directory / name).write_text(source)
        actual = (HERE / 'gpu-power.c').read_text()
        actual = re.sub(r'^#include[^\n]*\n', '', actual, flags=re.M)
        actual = re.sub(r'__asm__ volatile\("(?:dmb|dsb)[^"]*" ::: "memory"\);',
                        '__asm__ volatile("" ::: "memory");', actual)
        cls.lib = compile_shared(directory, HARNESS.replace('ACTUAL_SOURCE', actual), 'power-start')
        cls.lib.run.argtypes = [C.c_char_p, C.c_uint]
        cls.lib.count.argtypes = [C.c_uint]

    def run_case(self, args, issue, result, counts):
        self.assertEqual(self.lib.run(args.encode(), issue), result)
        self.assertEqual([self.lib.count(i) for i in range(4)], counts)

    def test_legacy_cx_has_no_child_and_child_requires_a_complete_held_parent(self):
        self.run_case(BASE, 0, 0, [5, 0, 1, 0])
        self.run_case(BASE + ' redfingmu=1', 0, 0, [5, 1, 1, 1])

    def test_child_contract_refusal_precedes_first_parent_mapping_or_transaction(self):
        self.run_case(BASE + ' redfingmu=1', 1, errno.ENXIO, [0, 1, 0, 0])
        for extra in ('redfingmu=0', 'redfingmu=2', 'redfingmu=1 redfingmu=1',
                      'redfingmu=1 redfinwifi=2'):
            self.run_case(BASE + ' ' + extra, 0, errno.ENOTSUP, [0, 0, 0, 0])

    def test_failed_transaction_missing_proofs_and_late_args_never_enter_child(self):
        for issue, result in ((2, errno.EIO), (3, errno.EPERM),
                              (4, errno.EPERM), (5, errno.EPERM)):
            self.run_case(BASE + ' redfingmu=1', issue, result, [5, 1, 1, 0])

    def test_child_error_is_propagated_and_cpu_return_adt_failures_never_map(self):
        self.run_case(BASE + ' redfingmu=1', 6, errno.EBUSY, [5, 1, 1, 1])
        for issue in (7, 8, 9, 10):
            self.run_case(BASE + ' redfingmu=1', issue, errno.ENXIO, [0, 1, 0, 0])


if __name__ == '__main__':
    unittest.main()
