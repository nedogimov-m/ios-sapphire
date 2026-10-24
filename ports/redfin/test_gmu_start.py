"""Run the real native GMU start protocol against bounded device callbacks."""
import ctypes
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include <stdint.h>
#include <string.h>
#include "include/redfin_gmu_start.h"
static struct rf_gb_report report;
static struct rf_gb_config config;
static uint32_t regs[RF_GB_UNITS][0x30000/4];
static unsigned issue,fail_store,fail_audit,stores,reads,audits,exchanges,bad,lost;
static unsigned reset_releases,fw_reads,hfi_reads;
static uint64_t now;
static int guard(void *p,unsigned phase){
 if(p!=&report || phase>RF_GB_HFI_LIVE)bad++;
 if(lost)return ECANCELED;
 if(issue==4 && phase==RF_GB_HELD)return EAGAIN;
 if(phase!=RF_GB_HELD && !reset_releases)bad++;
 return 0;
}
static int read_word(void *p,unsigned u,uint32_t a,uint32_t *v){
 if(p!=&report || lost || u>=RF_GB_UNITS || a&3u || a>=(u==RF_GB_GMU?0x30000u:0x10000u) ||
    (u==RF_GB_RSC && a>=0x1000))bad++;
 reads++;
 if(u==RF_GB_GMU && a==0x14070 && reset_releases){
  fw_reads++;
  if(issue!=5 && fw_reads>=3)regs[u][a/4]=issue==6?0x300:0x100;
 }
 if(u==RF_GB_GMU && a==0x14600 && regs[RF_GB_GMU][0x14618/4]){
  hfi_reads++;if(issue!=7 && hfi_reads>=2)regs[u][a/4]=1;
 }
 *v=regs[u][a/4];
 if(u==RF_GB_GMU && a==0x24c18)*v&=0x29; /* Unimplemented mask bits may be RAZ. */
 if(u==RF_GB_GMU && a==0x1464c)*v&=7;
 if(issue==3 && u==RF_GB_GMU && a==0x14070 && stores==report.program_count)*v=0x100;
 if(issue==9 && stores==6 && u==RF_GB_RSC && a==0x2c)*v^=1;
 return 0;
}
static int write_word(void *p,unsigned u,uint32_t a,uint32_t v){
 if(p!=&report || lost || u>=RF_GB_UNITS || a&3u || a>=(u==RF_GB_GMU?0x30000u:0x10000u) ||
    (u==RF_GB_RSC && a>=0x1000))bad++;
 stores++;if(stores==fail_store)return EIO;
 if(u==RF_GB_GMU && a==0x14000){
  if(v || report.phase!=RF_GB_FW_WAIT || audits<2 || exchanges || stores!=report.program_count+(issue==11?3u:1u))bad++;
  reset_releases++;
 }
 if(u==RF_GB_GMU && a==0x14618){
  if(v!=1 || !report.firmware || report.phase!=RF_GB_HFI_WAIT)bad++;
 }
 if(u==RF_GB_GMU && a==0x24c1c && v==2)regs[u][0x24c20/4]=2;
 regs[u][a/4]=v;
 if(issue==10 && stores==8)lost=1;
 return 0;
}
static int audit(void *p,unsigned phase){
 if(p!=&report || lost || phase>RF_GB_HFI_LIVE)bad++;
 audits++;return audits==fail_audit?EFAULT:0;
}
static int exchange(void *p,uint32_t *version){
 if(p!=&report || lost || report.phase!=RF_GB_HFI_LIVE || !report.hfi || !report.firmware)bad++;
 exchanges++;if(issue==8)return EPROTO;*version=0x20010008;return 0;
}
static int delay_us(void *p,unsigned us){if(p!=&report || lost || us!=100)bad++;now+=10000000;return 0;}
static uint64_t time_ns(void *p){if(p!=&report)bad++;return now;}
static const struct rf_gb_ops ops={&report,guard,read_word,write_word,audit,exchange,delay_us,time_ns};
int run(unsigned mode,unsigned failure,unsigned audit_failure,unsigned vrm){
 memset(&report,0,sizeof(report));memset(regs,0,sizeof(regs));
 issue=mode;fail_store=failure;fail_audit=audit_failure;
 stores=reads=audits=exchanges=bad=lost=reset_releases=fw_reads=hfi_reads=0;now=0;
 config=(struct rf_gb_config){0x06020001,0x20010008,0x20000001,0x60001000,0x60006000,
  0x30018,0x30000,0x30004,vrm?0x40000u:0,0};
 regs[RF_GB_GMU][0x14000/4]=1;
 regs[RF_GB_GMU][0x143a0/4]=0x2000;
 if(mode==1)regs[RF_GB_RSC][0x404/4]=1;
 if(mode==2)regs[RF_GB_RSC][0xd14/4]=0x10000;
 if(mode==11)regs[RF_GB_RSC][0x10/4]=0x10000;
 if(mode==12)config.xo=0x30001;
 if(mode==13)config.mx=config.cx;
 if(mode==14)config.hfi_address=0x60002000;
 if(mode==15)config.chip=0x06030500;
 return rf_gb_run(&report,&config,&ops);
}
unsigned stat(unsigned i){unsigned values[]={stores,reads,audits,exchanges,bad,
 reset_releases,report.stage,report.firmware,report.hfi,report.ack,report.program_count};return i<11?values[i]:999;}
int again(void){return rf_gb_run(&report,&config,&ops);}
uint32_t reg(unsigned unit,unsigned at){return regs[unit][at/4];}
int ack(const uint32_t *w,unsigned n,uint32_t request,uint32_t wanted,uint32_t *version){
 return rf_gb_version_ack(w,n,request,wanted,version);}
'''


class GMUStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        source, library = root / 'start.c', root / 'start.so'
        source.write_text(HARNESS)
        result = subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
            '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-I', str(HERE),
            str(source), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.reg.restype = ctypes.c_uint32
        cls.lib.ack.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]

    def test_complete_native_cold_start_and_single_fresh_version_exchange(self):
        for vrm in (0, 1):
            self.assertEqual(self.lib.run(0, 0, 0, vrm), 0)
            self.assertEqual([self.lib.stat(i) for i in (2, 3, 4, 5, 6, 7, 8, 9)],
                             [4, 1, 0, 1, 6, 1, 1, 1])
            self.assertEqual(self.lib.stat(0), self.lib.stat(10) + 2)
            self.assertEqual(self.lib.again(), errno.EBUSY)

    def test_native_a620_programs_local_pdc_and_keeps_gx_and_gpu_cp_outside_protocol(self):
        self.assertEqual(self.lib.run(0, 0, 0, 1), 0)
        self.assertEqual([self.lib.reg(1, 0x600 + 4*i) for i in range(5)],
            [0xeaaae5a0, 0xe1a1ebab, 0xa2e0a581, 0xecac82e2, 0x0020edad])
        self.assertEqual(self.lib.reg(1, 0x48), 0x80000000)
        self.assertEqual([self.lib.reg(3, 4*i) for i in range(5)],
            [0xfebea1e1, 0xa5a4a3a2, 0x8382a6e0, 0xbce3e284, 0x002081fc])
        self.assertEqual(self.lib.reg(2, 0x4500), 0x80000001)
        self.assertEqual(self.lib.reg(2, 4*0x1576), 0x30004)
        self.assertEqual(self.lib.reg(2, 4*0x15da + 16), 0x30000)
        self.assertEqual(self.lib.reg(2, 4*0x15db + 16), 2)
        self.assertEqual(self.lib.reg(2, 4*0x1576 + 48), 0x40004)
        self.assertEqual(self.lib.reg(2, 4*0x15db + 48), 1)
        self.assertEqual(self.lib.reg(0, 0x14608), 0x06020100)
        self.assertEqual(self.lib.reg(0, 0x143a0), 0x2f11)

    def test_busy_rsc_inflight_tcs_unavailable_guard_and_bad_configs_never_write(self):
        for mode in (1, 2, 4, 12, 13, 14, 15):
            self.assertNotEqual(self.lib.run(mode, 0, 0, 1), 0)
            self.assertEqual(self.lib.stat(0), 0)
            self.assertEqual(self.lib.stat(5), 0)
            self.assertEqual(self.lib.stat(4), 0)

    def test_every_failed_store_is_terminal_with_no_rollback_or_second_reset_release(self):
        self.assertEqual(self.lib.run(0, 0, 0, 1), 0)
        count = self.lib.stat(0)
        for failure in range(1, count + 1):
            with self.subTest(failure=failure):
                self.assertEqual(self.lib.run(0, failure, 0, 1), errno.EIO)
                self.assertEqual(self.lib.stat(0), failure)
                self.assertLessEqual(self.lib.stat(5), 1)
                self.assertEqual(self.lib.stat(3), 0)
                self.assertEqual(self.lib.stat(4), 0)

    def test_each_complete_ownership_audit_can_revoke_the_run(self):
        for failure in range(1, 5):
            self.assertEqual(self.lib.run(0, 0, failure, 1), errno.EFAULT)
            self.assertEqual(self.lib.stat(2), failure)
            self.assertLessEqual(self.lib.stat(5), 1)
            self.assertEqual(self.lib.stat(4), 0)

    def test_stale_completion_bad_readback_timeout_and_fault_stop(self):
        for mode, expected in ((3, errno.EAGAIN), (5, errno.ETIMEDOUT),
                               (6, errno.EIO), (7, errno.ETIMEDOUT),
                               (8, errno.EPROTO), (9, errno.EIO), (10, errno.ECANCELED)):
            self.assertEqual(self.lib.run(mode, 0, 0, 1), expected, mode)
            self.assertEqual(self.lib.stat(4), 0, mode)
            self.assertLessEqual(self.lib.stat(5), 1)
        self.assertEqual(self.lib.run(3, 0, 0, 1), errno.EAGAIN)
        self.assertEqual(self.lib.stat(5), 0)
        self.assertEqual(self.lib.run(10, 0, 0, 1), errno.ECANCELED)
        self.assertEqual(self.lib.stat(0), 8)

    def test_inherited_asleep_rsc_wakes_before_programming_and_has_one_cm3_release(self):
        self.assertEqual(self.lib.run(11, 0, 0, 1), 0)
        self.assertEqual(self.lib.stat(5), 1)
        self.assertEqual(self.lib.reg(0, 0x24c1c), 0)
        self.assertEqual(self.lib.stat(4), 0)

    def test_v2_ack_checks_full_echo_status_and_native_version_compatibility(self):
        request = 0x00100201
        good = [0x00010401, request, 0, 0x20010008]

        def check(words, wanted=0x20000000):
            array = (ctypes.c_uint32 * len(words))(*words)
            output = ctypes.c_uint32(0xa5a5a5a5)
            error = self.lib.ack(array, len(words), request, wanted, ctypes.byref(output))
            return error, output.value

        self.assertEqual(check(good), (0, 0x20010008))
        self.assertEqual(check([*good[:3], 0x20000001]), (0, 0x20000001))
        self.assertNotEqual(check([*good[:3], 0x10000001])[0], 0)
        self.assertNotEqual(check([*good[:3], 0x20000001], 0x20010000)[0], 0)
        for index, altered in ((0, 0x401), (0, 0x10501), (1, request ^ 0x100000), (2, 1)):
            words = good.copy()
            words[index] = altered
            self.assertNotEqual(check(words)[0], 0)
            self.assertEqual(check(words)[1], 0xa5a5a5a5)


if __name__ == '__main__':
    unittest.main()
