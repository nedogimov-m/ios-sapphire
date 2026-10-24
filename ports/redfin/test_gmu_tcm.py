"""Compile the real reset-held Lito clock/TCM leaf and enforce its MMIO scope."""
import ctypes
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class Report(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'stage', 'error', 'reads', 'writes', 'polls',
        'pll_mode', 'pll_l', 'pll_user', 'pll_alpha',
        'pll_vote_before', 'feed_before', 'misc', 'cx', 'cx_hw', 'gx',
        'rcg_before', 'source_before', 'gmu_clock_before',
        'reset_before', 'result_before', 'hfi_before',
        'reset_after', 'source_after', 'gmu_clock_after',
        'counter_before', 'counter_after', 'counter_delta')]
    _fields_ += [('saved', ctypes.c_uint32 * 2), ('pattern_read', ctypes.c_uint32 * 2),
                 ('restored', ctypes.c_uint32 * 2), ('counter_elapsed_ns', ctypes.c_uint64)]
    _fields_ += [(name, ctypes.c_bool) for name in (
        'reset_held', 'source_200m', 'counter_live', 'dtcm_dirty', 'dtcm_restored')]


HARNESS = r'''
#include <stdlib.h>
#include <string.h>
#include "redfin_gmu_tcm.h"
struct host {
 uint32_t gcc[0x80000/4], gpucc[0x9000/4], gmu[0x30000/4];
 unsigned scenario, variant, checks, accesses, reads, writes, us, dtcm_writes, ns_reads;
 unsigned fail_valid, fail_read, fail_write, bad, after_loss;
 uint32_t counter;
 bool lost, ahb_requested;
};
static struct host *h;
static unsigned metrics[8];
static uint32_t final_values[13];
static uint32_t *slot(unsigned unit,uint32_t at) {
 if(unit==RF_GT_GCC && at<sizeof(h->gcc)) return &h->gcc[at/4];
 if(unit==RF_GT_GPUCC && at<sizeof(h->gpucc)) return &h->gpucc[at/4];
 if(unit==RF_GT_GMU && at<sizeof(h->gmu)) return &h->gmu[at/4];
 h->bad++;return NULL;
}
static bool valid(void *ctx) {
 if(ctx!=h)abort();
 h->checks++;
 if(h->fail_valid && h->checks>=h->fail_valid)h->lost=true;
 if(h->dtcm_writes==1 && h->scenario==21) h->gpucc[0x1098/4]|=0x80000000;
 if(h->dtcm_writes==1 && h->scenario==22) h->gmu[0x14000/4]=0;
 if(h->dtcm_writes==1 && h->scenario==23) h->gcc[4/4]=32;
 if(h->dtcm_writes==1 && h->scenario==24) h->gpucc[0x106c/4]=1;
 if(h->dtcm_writes==1 && h->scenario==28) h->gpucc[0x1540/4]=0;
 return !h->lost;
}
static void access(unsigned unit,uint32_t at,bool writing) {
 h->accesses++;
 if(h->lost)h->after_loss++;
 if(!rf_gt_allowed(unit,at,writing))h->bad++;
 if(unit==RF_GT_GMU) {
  if(!h->ahb_requested || !(h->gpucc[0x109c/4]&1) ||
     (h->gpucc[0x1098/4]&0x80000001)!=1)h->bad++;
  if(at==0x7000 || at==0x7004 || at==0x14220) {
   if((h->gpucc[0x1098/4]&0x80000001)!=1 || h->gmu[0x14000/4]!=1)h->bad++;
  }
 }
}
static int read_reg(void *ctx,unsigned unit,uint32_t at,uint32_t *out) {
 (void)ctx;access(unit,at,false);h->reads++;
 if(h->fail_read==h->reads)return EIO;
 uint32_t *p=slot(unit,at);if(!p)return EINVAL;
 uint64_t ns=(uint64_t)h->us*1000+(h->scenario==29?(uint64_t)h->accesses*20000:0);
 uint32_t ticks=(uint32_t)(ns*192/10000);
 if(h->scenario==17)ticks=0;
 if(h->scenario==18)ticks*=2;
 *out=unit==RF_GT_GMU && at==0x14220?h->counter+ticks:*p;
 if(h->scenario==19 && unit==RF_GT_GMU && at==0x7000 && h->dtcm_writes==2)*out^=1;
 if(h->scenario==20 && unit==RF_GT_GMU && at==0x7000 && h->dtcm_writes==4)*out^=1;
 return 0;
}
static int write_reg(void *ctx,unsigned unit,uint32_t at,uint32_t value) {
 (void)ctx;access(unit,at,true);h->writes++;
 uint32_t *p=slot(unit,at);if(!p)return EINVAL;
 uint32_t old=*p,mask=0;
 if(unit==RF_GT_GCC) {
  if(at==0x52010)mask=1;
  else if(at==0x52000)mask=0x10000;
  else if(at==0x71028)mask=3;
  else mask=1;
 }else if(unit==RF_GT_GPUCC) {
  if(at==0x1120)mask=3;
  else if(at==0x1124)mask=0x10371f;
  else if(at==0x1098)mask=0xff1;
  else mask=1;
 }
 if(unit!=RF_GT_GMU && ((old^value)&~mask))h->bad++;
 if(unit==RF_GT_GMU && at==0x14000 && value!=1)h->bad++;
 bool branch=(unit==RF_GT_GCC && (at==0x71154 || at==0x7100c || at==0x71018)) ||
   (unit==RF_GT_GPUCC && (at==0x1078 || at==0x109c || at==0x5000 || at==0x1098));
 if(branch) {
  if(unit==RF_GT_GPUCC && at==0x1078)h->ahb_requested=true;
  *p=value;
  if(value&1)*p&=~0x80000000u;else *p|=0x80000000u;
  if(h->scenario==10 && unit==RF_GT_GPUCC && at==0x109c)*p|=0x80000000;
  if(h->scenario==11 && unit==RF_GT_GCC && at==0x71154)*p|=0x80000000;
  if(h->scenario==12 && unit==RF_GT_GPUCC && at==0x1098)*p|=0x80000000;
  if(h->scenario==26 && unit==RF_GT_GPUCC && at==0x1078)*p=old; /* AHB native delay. */
  if(unit==RF_GT_GPUCC && at==0x1098 && (value&1)) {
   h->gpucc[0x1120/4]&=~0x80000000u;
  }
 }else if(unit==RF_GT_GPUCC && at==0x1120) {
  *p=value;
  if(value&2)*p&=~0x80000000u;
  else if(!(h->gpucc[0x1098/4]&1))*p|=0x80000000u;
  if(h->scenario!=14)*p&=~1u;
  if(h->scenario==13)*p|=0x80000000u;
 }else if(unit==RF_GT_GPUCC && at==0x1124 && h->scenario==15) {
  *p=old;
 }else if(unit==RF_GT_GMU && at==0x14000 && h->scenario==16) {
  *p=old;
 }else {
  *p=value;
 }
 if(h->scenario==33 && unit==RF_GT_GCC && at==0x71028)*p=old;
 if(unit==RF_GT_GMU && (at==0x7000 || at==0x7004))h->dtcm_writes++;
 return h->fail_write==h->writes?EIO:0; /* Error can follow a committed write. */
}
static void delay_us(void *ctx,unsigned us) {
 (void)ctx;
 h->us+=us;
}
static uint64_t time_ns(void *ctx) {
 (void)ctx;h->ns_reads++;
 if(h->scenario==30)return 0;
 if(h->scenario==31)return h->ns_reads==1?100000000:99000000;
 if(h->scenario==32)return h->ns_reads==1?1:100000002;
 return (uint64_t)h->us*1000+(h->scenario==29?(uint64_t)h->accesses*20000:0);
}
int host_run(uint32_t chip,unsigned scenario,unsigned variant,
 unsigned fail_valid,unsigned fail_read,unsigned fail_write,struct rf_gt_report *report) {
 h=calloc(1,sizeof(*h));if(!h)abort();
 h->scenario=scenario;h->variant=variant;
 h->fail_valid=fail_valid;h->fail_read=fail_read;h->fail_write=fail_write;
 h->gcc[0x71004/4]=1;h->gcc[0]=0xc0100001;h->gcc[4/4]=31;
 h->gcc[0xc/4]=0x20000107;h->gcc[0x40/4]=0x4000;h->gcc[0x71028/4]=0xabc00003;
 h->gcc[0x52010/4]=0x40000000;h->gcc[0x52000/4]=0x8000;
 h->gcc[0x71154/4]=h->gcc[0x7100c/4]=h->gcc[0x71018/4]=0x80000200;
 h->gpucc[0x106c/4]=0x222000;h->gpucc[0x1540/4]=0x80000000;h->gpucc[0x100c/4]=0x17;
 h->gpucc[0x1064/4]=0x80000020;h->gpucc[0x1098/4]=0x8000a000;
 h->gpucc[0x109c/4]=0x80000040;h->gpucc[0x1078/4]=0x80000002;
 h->gpucc[0x5000/4]=0x80000020;
 h->gpucc[0x1120/4]=0x80000100;h->gpucc[0x1124/4]=0x42100000;
 h->gmu[0x7000/4]=0x12345678;h->gmu[0x7004/4]=0xfedcba98;
 h->counter=variant==2?0xfffff000:0x12340000;
 if(variant==1)h->gpucc[0x1120/4]=0x102;
 switch(scenario) {
 case 1:h->gcc[4/4]=32;break;
 case 2:h->gcc[0]&=~(1u<<variant);break;
 case 3:h->gcc[0xc/4]^=1u<<variant;break;
 case 4:h->gcc[0x40/4]^=1u<<variant;break;
 case 5:h->gcc[0x71028/4]=0xabc00000|variant;h->gcc[0xc/4]=0x20000103;break;
 case 33:h->gcc[0x71028/4]=0xabc00000;break;
 case 6:h->gpucc[0x1098/4]=1;break;
 case 7:h->gpucc[0x100c/4]=0x80000000;break;
 case 8:h->gpucc[0x1120/4]|=1u<<variant;break;
 case 9:h->gcc[0x71004/4]=0x80000001;break;
 case 16:h->gmu[0x14000/4]=0;break;
 case 25:h->gmu[0x14000/4]=variant==2?2:0;
  h->gmu[0x14070/4]=variant==0?0x100:0;
  h->gmu[0x14600/4]=variant==1?1:0;break;
 case 27:h->gpucc[0x1540/4]=0;break;
 default:break;
 }
 struct rf_gt_ops ops={h,valid,read_reg,write_reg,delay_us,time_ns};
 int result=rf_gt_run(&ops,chip,report);
 metrics[0]=h->checks;metrics[1]=h->reads;metrics[2]=h->writes;metrics[3]=h->us;
 metrics[4]=h->dtcm_writes;metrics[5]=h->bad;metrics[6]=h->after_loss;metrics[7]=h->accesses;
 final_values[0]=h->gmu[0x14000/4];final_values[1]=h->gmu[0x7000/4];
 final_values[2]=h->gmu[0x7004/4];final_values[3]=h->gcc[0x52010/4];
 final_values[4]=h->gcc[0x52000/4];final_values[5]=h->gpucc[0x1120/4];
 final_values[6]=h->gpucc[0x1124/4];final_values[7]=h->gpucc[0x1098/4];
 final_values[8]=h->gcc[0];final_values[9]=h->gcc[4/4];
 final_values[10]=h->gcc[0xc/4];final_values[11]=h->gcc[0x40/4];final_values[12]=h->gcc[0x71028/4];
 free(h);h=NULL;return result;
}
unsigned host_metric(unsigned i){return i<8?metrics[i]:999;}
uint32_t host_final(unsigned i){return i<13?final_values[i]:0;}
size_t host_report_size(void){return sizeof(struct rf_gt_report);}
int host_allowed(unsigned unit,uint32_t at,int writing){return rf_gt_allowed(unit,at,writing!=0);}
'''


class RedfinGMUTCMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        source = root/'gmu_tcm.c'
        source.write_text(HARNESS)
        subprocess.run([shutil.which('clang') or 'cc', '-std=c11', '-Wall', '-Wextra',
                        '-Werror', '-shared', '-fPIC', '-I',
                        str(Path(__file__).parent/'include'), str(source),
                        '-o', str(root/'gmu_tcm.dylib')], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(root/'gmu_tcm.dylib'))
        cls.lib.host_run.argtypes = [ctypes.c_uint32, ctypes.c_uint, ctypes.c_uint,
                                     ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                     ctypes.POINTER(Report)]
        cls.lib.host_report_size.restype = ctypes.c_size_t
        cls.lib.host_final.restype = ctypes.c_uint32

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_leaf(self, scenario=0, variant=0, fail_valid=0, fail_read=0, fail_write=0,
                 chip=0x06020001):
        report = Report()
        result = self.lib.host_run(chip, scenario, variant, fail_valid, fail_read,
                                    fail_write, ctypes.byref(report))
        metrics = tuple(self.lib.host_metric(i) for i in range(8))
        final = tuple(self.lib.host_final(i) for i in range(13))
        self.assertEqual(result, report.error)
        self.assertEqual(metrics[5:7], (0, 0))
        self.assertEqual((report.reads, report.writes), metrics[1:3])
        return result, report, metrics, final

    def test_complete_leaf_restores_tcm_preserves_other_votes_and_keeps_reset(self):
        self.assertEqual(ctypes.sizeof(Report), self.lib.host_report_size())
        result, r, metrics, final = self.run_leaf()
        self.assertEqual(result, 0)
        self.assertEqual(r.stage, 10)
        self.assertTrue(r.reset_held and r.source_200m and r.counter_live and r.dtcm_restored)
        self.assertFalse(r.dtcm_dirty)
        self.assertEqual(r.counter_delta, 19200)
        self.assertEqual(r.counter_elapsed_ns, 1000000)
        self.assertEqual(tuple(r.saved), (0x12345678, 0xFEDCBA98))
        self.assertEqual(tuple(r.restored), tuple(r.saved))
        self.assertEqual(final[:5], (1, 0x12345678, 0xFEDCBA98, 0x40000001, 0x18000))
        self.assertEqual(final[5] & 3, 0)
        self.assertEqual(final[6], (0x42100000 & ~0x10371F) | 0x602)
        self.assertEqual(final[7], 0xAFF1)
        self.assertEqual(final[8:12], (0xC0100001, 31, 0x20000107, 0x4000))
        self.assertEqual(final[12], 0xABC00003)
        self.assertEqual(metrics[4], 4)
        self.assertLessEqual(metrics[3], 2000)

    def test_initial_force_enable_bit_and_counter_wrap_are_preserved(self):
        for variant in (1, 2):
            result, r, _, final = self.run_leaf(variant=variant)
            self.assertEqual(result, 0)
            self.assertEqual(final[5] & 2, 2 if variant == 1 else 0)
            self.assertEqual(r.counter_delta, 19200)
            if variant == 2:
                self.assertLess(r.counter_after, r.counter_before)

    def test_native_cold_misc_setup_preserves_other_bits_and_pll_outputs(self):
        for inherited in range(4):
            result, r, _, final = self.run_leaf(5, inherited)
            self.assertEqual(result, 0)
            self.assertEqual(r.misc, 0xABC00000 | inherited)
            self.assertEqual(final[12], 0xABC00003)
            self.assertEqual(final[8:12], (0xC0100001, 31, 0x20000103, 0x4000))

    def test_failed_misc_readback_never_enables_a_feed_or_touches_gmu(self):
        result, r, metrics, final = self.run_leaf(33)
        self.assertEqual(result, errno.EIO)
        self.assertEqual(r.stage, 2)
        self.assertEqual(metrics[4], 0)
        self.assertEqual(final[3:5], (0x40000000, 0x8000))

    def test_counter_counts_sample_guard_time_with_full_source_audits_outside_interval(self):
        result, r, _, _ = self.run_leaf(29)
        self.assertEqual(result, 0)
        self.assertGreater(r.counter_elapsed_ns, 1000000)
        self.assertGreater(r.counter_delta, 19200)
        self.assertLess(r.counter_delta, 23040)
        expected = r.counter_elapsed_ns * 192 // 10000
        self.assertLessEqual(abs(r.counter_delta-expected), 1)

    def test_stopped_backward_or_excessive_cpu_window_rejects_tcm(self):
        for scenario in (30, 31, 32):
            result, r, metrics, _ = self.run_leaf(scenario)
            self.assertEqual(result, errno.ETIMEDOUT)
            self.assertEqual(r.stage, 6)
            self.assertEqual(metrics[4], 0)

    def test_wrong_chip_is_rejected_before_any_callback(self):
        for chip in (0, 0x06010001, 0x06020000, 0x06030500, 0x06050001):
            result, _, metrics, _ = self.run_leaf(chip=chip)
            self.assertEqual(result, errno.EINVAL)
            self.assertEqual(metrics, (0,)*8)

    def test_source_identity_mismatch_is_read_only(self):
        cases = [(1, 0), (9, 0)]
        cases += [(2, bit) for bit in (20, 30, 31)]
        cases += [(3, bit) for bit in (0, 1, 8, 9, 10, 11)]
        cases += [(4, bit) for bit in range(32)]
        cases += [(8, bit) for bit in (0, 4, 5, 6, 7)]
        for scenario, variant in cases:
            result, _, metrics, _ = self.run_leaf(scenario, variant)
            self.assertEqual(result, errno.EAGAIN)
            self.assertEqual(metrics[2], 0)

    def test_inherited_gmu_or_gx_owner_is_rejected_without_writes(self):
        for scenario in (6, 7):
            result, _, metrics, _ = self.run_leaf(scenario)
            self.assertEqual(result, errno.EBUSY)
            self.assertEqual(metrics[2], 0)

    def test_cx_uses_live_hardware_status_instead_of_control_bit31(self):
        result, r, _, _ = self.run_leaf()
        self.assertEqual(result, 0)
        self.assertEqual(r.cx, 0x222000)
        self.assertEqual(r.cx_hw, 0x80000000)
        result, _, metrics, _ = self.run_leaf(27)
        self.assertEqual(result, errno.EBUSY)
        self.assertEqual(metrics[2], 0)

    def test_inherited_firmware_or_ambiguous_reset_is_not_modified(self):
        for variant in range(3):
            result, r, metrics, final = self.run_leaf(25, variant)
            self.assertEqual(result, errno.EBUSY)
            self.assertEqual(r.stage, 3)
            self.assertEqual(metrics[4], 0)
            self.assertFalse(r.reset_held)
            self.assertEqual(final[0], 2 if variant == 2 else 0)
            self.assertEqual(final[7] & 0x80000001, 1)

    def test_stuck_branches_are_bounded_and_never_touch_tcm(self):
        for scenario in (10, 11, 12):
            result, r, metrics, _ = self.run_leaf(scenario)
            self.assertEqual(result, errno.ETIMEDOUT)
            self.assertEqual(metrics[4], 0)
            self.assertLessEqual(r.polls, 210)
            self.assertLessEqual(metrics[3], 1000)

    def test_rcg_force_update_and_reset_failures_are_terminal(self):
        for scenario, expected, stage in ((13, errno.ETIMEDOUT, 4),
                                          (14, errno.ETIMEDOUT, 4),
                                          (15, errno.EIO, 4), (16, errno.EIO, 3)):
            result, r, metrics, _ = self.run_leaf(scenario)
            self.assertEqual(result, expected)
            self.assertEqual(r.stage, stage)
            self.assertEqual(metrics[4], 0)
            self.assertLessEqual(r.polls, 510)
            self.assertLessEqual(metrics[3], 1000)

    def test_counter_liveness_is_fresh_and_precedes_any_data_write(self):
        for scenario in (17, 18):
            result, r, metrics, _ = self.run_leaf(scenario)
            self.assertEqual(result, errno.ETIMEDOUT)
            self.assertEqual(r.stage, 6)
            self.assertTrue(r.reset_held)
            self.assertFalse(r.counter_live)
            self.assertEqual(metrics[4], 0)

    def test_pattern_mismatch_is_reported_after_verified_restoration(self):
        result, r, metrics, final = self.run_leaf(19)
        self.assertEqual(result, errno.EIO)
        self.assertEqual(r.stage, 9)
        self.assertTrue(r.dtcm_restored)
        self.assertFalse(r.dtcm_dirty)
        self.assertEqual(final[1:3], (0x12345678, 0xFEDCBA98))
        self.assertEqual(metrics[4], 4)

    def test_failed_restoration_remains_explicitly_dirty(self):
        result, r, metrics, _ = self.run_leaf(20)
        self.assertEqual(result, errno.EIO)
        self.assertTrue(r.dtcm_dirty)
        self.assertFalse(r.dtcm_restored)
        self.assertEqual(metrics[4], 4)

    def test_changed_clock_reset_source_or_domain_stops_before_second_pattern(self):
        for scenario in (21, 22, 23, 24, 28):
            result, r, metrics, _ = self.run_leaf(scenario)
            self.assertEqual(result, errno.EAGAIN)
            self.assertTrue(r.dtcm_dirty)
            self.assertFalse(r.dtcm_restored)
            self.assertEqual(metrics[4], 1)

    def test_ahb_native_delay_does_not_require_its_unreliable_halt_bit(self):
        result, r, _, _ = self.run_leaf(26)
        self.assertEqual(result, 0)
        self.assertTrue(r.counter_live and r.dtcm_restored)

    def test_every_lost_lease_edge_stops_all_further_mmio(self):
        _, _, baseline, _ = self.run_leaf()
        for failed in range(1, baseline[0]+1):
            result, r, metrics, _ = self.run_leaf(fail_valid=failed)
            self.assertEqual(result, errno.ECANCELED)
            self.assertEqual(metrics[0], failed)
            self.assertNotEqual(r.stage, 10)

    def test_every_read_failure_is_terminal(self):
        _, _, baseline, _ = self.run_leaf()
        for failed in range(1, baseline[1]+1):
            result, _, metrics, _ = self.run_leaf(fail_read=failed)
            self.assertEqual(result, errno.EIO)
            self.assertEqual(metrics[1], failed)

    def test_every_committed_write_error_stops_before_any_next_access(self):
        _, _, baseline, _ = self.run_leaf()
        for failed in range(1, baseline[2]+1):
            result, _, metrics, _ = self.run_leaf(fail_write=failed)
            self.assertEqual(result, errno.EIO)
            self.assertEqual(metrics[2], failed)

    def test_allowlist_excludes_firmware_start_gx_smmu_and_debug_mux_writes(self):
        for unit, at in ((0, 0), (0, 4), (0, 0x40), (0, 0xc), (0, 0x62000),
                          (0, 0x4300C), (1, 0x100C), (1, 0x106C), (1, 0x1540), (1, 0x1568),
                          (2, 0), (2, 0x3000), (2, 0x14070), (2, 0x14618),
                          (2, 0x7008), (3, 0)):
            self.assertEqual(self.lib.host_allowed(unit, at, 1), 0)
        for at in (0x14000, 0x7000, 0x7004):
            self.assertEqual(self.lib.host_allowed(2, at, 1), 1)


if __name__ == '__main__':
    unittest.main()
