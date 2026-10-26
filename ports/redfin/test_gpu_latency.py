"""Native precise deadlines and the final FIFO/cache handoff with host receivers."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_display_geometry import function
from test_smp_gui import patched_source
from ports.redfin import test_surface_cache
from ports.redfin import test_gpu_physical

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'research/redfin-gpu/gpu-latency-base-v1'
NATIVE = ROOT / 'research/redfin-gpu/gpu-latency-native-v1'


class GPULatencyTests(unittest.TestCase):
    def test_actual_pause_uses_native_units_critical_timer_and_platform_spin_rules(self):
        pause = function((HERE/'gpu-precise-pause.inc').read_text(),
                         'void redfin_gpu_precise_pause(')
        wrapper = function((HERE/'gpu-runtime.inc').read_text(),
                           'static void gr_wait_pause(')
        receiver = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef int wait_result_t;
typedef void *event_t;
enum {NSEC_PER_USEC=1000,THREAD_UNINT=2,TIMEOUT_URGENCY_SYS_CRITICAL=1,
      THREAD_WAITING=3,THREAD_AWAKENED=4};
#define THREAD_CONTINUE_NULL ((void *)0)
static uint64_t now,divisor,seen_interval,seen_deadline,overshoot;
static unsigned conversions,reads,spins,waits,blocks,spin_queries;
static bool native_spin,interrupts;
static int preemption,wait_result;
static struct {uint64_t pause_ns,pause_max_ns,pause_calls;} gr;
static struct {void *context;} gx={(void *)1};
void redfin_gpu_precise_pause(unsigned);
static void clock_interval_to_absolutetime_interval(unsigned value,unsigned unit,uint64_t *out)
{assert(unit==NSEC_PER_USEC);++conversions;*out=(uint64_t)value*unit/divisor;}
static uint64_t mach_absolute_time(void){++reads;return now;}
static bool ml_delay_should_spin(uint64_t interval)
{++spin_queries;seen_interval=interval;return native_spin;}
static int get_preemption_level(void){return preemption;}
static bool ml_get_interrupts_enabled(void){return interrupts;}
static void machine_delay_until(uint64_t interval,uint64_t deadline)
{assert(deadline==now+interval);++spins;seen_interval=interval;seen_deadline=deadline;now=deadline;}
static wait_result_t assert_wait_deadline_with_leeway(event_t event,int mode,
                                                      int urgency,uint64_t deadline,uint64_t leeway)
{
 assert(event==(event_t)&redfin_gpu_precise_pause&&mode==THREAD_UNINT);
 assert(urgency==TIMEOUT_URGENCY_SYS_CRITICAL&&!leeway&&deadline>now);
 assert(!native_spin&&!preemption&&interrupts);
 ++waits;seen_deadline=deadline;return wait_result;
}
static void thread_block(void *continuation)
{assert(!continuation&&wait_result==THREAD_WAITING&&waits==1);++blocks;now=seen_deadline+overshoot;}
static uint64_t gm_time_ns(void *context){assert(context==gx.context);return now*divisor;}
static void reset(uint64_t scale)
{
 now=50000;divisor=scale;overshoot=3;seen_interval=seen_deadline=0;
 conversions=reads=spins=waits=blocks=spin_queries=0;
 native_spin=false;interrupts=true;preemption=0;wait_result=THREAD_WAITING;
 memset(&gr,0,sizeof(gr));
}
'''+pause+'\n'+wrapper+r'''
int main(void)
{
 for(unsigned scale=1;scale<=8;scale*=8)for(unsigned us=100;us<=1000;us*=10){
  reset(scale);gr_wait_pause(0,us);
  assert(conversions==1&&reads==1&&spin_queries==1&&!spins&&waits==1&&blocks==1);
  assert(seen_interval==(uint64_t)us*1000/scale&&seen_deadline==50000+seen_interval);
  assert(gr.pause_calls==1&&gr.pause_ns==(uint64_t)us*1000+3*scale&&gr.pause_max_ns==gr.pause_ns);
 }
 for(unsigned mode=0;mode<3;++mode){
  reset(8);native_spin=mode==0;preemption=mode==1;interrupts=mode!=2;
  gr_wait_pause(0,100);
  assert(spins==1&&!waits&&!blocks&&seen_interval==12500&&seen_deadline==62500);
  assert(gr.pause_calls==1&&gr.pause_ns==100000&&gr.pause_max_ns==100000);
 }
 reset(8);wait_result=THREAD_AWAKENED;redfin_gpu_precise_pause(1000);
 assert(waits==1&&!blocks&&!spins&&now==50000);
 reset(8);redfin_gpu_precise_pause(0);
 assert(conversions==1&&!reads&&!spin_queries&&!waits&&!spins&&!blocks);
 return 0;
}
'''
        test_gpu_physical.GPUPhysicalTests().compile_run(receiver)

    def test_final_wc_and_cached_fifo_methods_keep_order_completion_and_late_admission(self):
        if not NATIVE.is_dir():
            self.skipTest('exact native latency fixture unavailable')
        with patch.object(test_surface_cache, 'NATIVE', NATIVE):
            test_surface_cache.SurfaceCacheTests().test_actual_wc_worker_keeps_real_completion_while_cached_aliases_still_quiesce()

    def test_complete_overlay_applies_to_verified_run15_and_matches_final_sources(self):
        if not BASE.is_dir():
            self.skipTest('verified run15 native preimages unavailable')
        overlay = HERE/'native-gpu-latency.patch'
        with tempfile.TemporaryDirectory(prefix='redfin-latency-') as temporary:
            directory = Path(temporary)
            shutil.copytree(BASE, directory, dirs_exist_ok=True)
            checked = subprocess.run(['git', 'apply', '--check', str(overlay)],
                                     cwd=directory, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            subprocess.run(['git', 'apply', str(overlay)], cwd=directory,
                           check=True, capture_output=True)
            for path in NATIVE.rglob('*'):
                if not path.is_file() or path.name == 'source-proof.json':
                    continue
                target = str(path.relative_to(NATIVE))
                self.assertEqual((directory/target).read_bytes(), path.read_bytes(), target)
                # Preserve the exact run18 prefix proof, then replay the later
                # producer extension before comparing the current final tree.
                if target=='iokit/Kernel/arm/RedfinGPU.cpp':
                    later=HERE/'native-surface-producer.patch'
                    if later.exists():
                        subprocess.run(['git','apply','--include='+target,str(later)],
                                       cwd=directory,check=True,capture_output=True)
                self.assertEqual(patched_source(target),(directory/target).read_text(),target)
        for owned, target in (
            ('gpu-precise-pause.inc', 'bsd/dev/redfin_gpu_precise_pause.inc'),
            ('gpu-runtime.inc', 'bsd/dev/redfin_gpu_runtime.inc'),
            ('gpu-service.h', 'bsd/dev/redfin_gpu_service.h'),
            ('gpu-physical-runtime.inc', 'bsd/dev/redfin_gpu_physical.inc'),
            ('gpu-physical-worker.inc', 'iokit/Kernel/arm/RedfinGPUPhysicalWorker.inc'),
            ('gpu-throughput-queue.inc', 'iokit/Kernel/arm/RedfinGPUQueue.inc'),
        ):
            self.assertEqual((HERE/owned).read_text(), patched_source(target))

    def test_clock_wait_and_cache_partitions_fit_native_log_records(self):
        formats = []
        for target in ('bsd/dev/redfin_gpu_physical.inc', 'iokit/Kernel/arm/RedfinGPU.cpp'):
            path = NATIVE/target
            if not path.is_file():
                self.skipTest('exact native latency fixture unavailable')
            formats += re.findall(r'(?:printf|IOLog)\("(REDFIN GPU (?:CLOCK|WAIT PARTS|CACHE PARTS):[^"\n]+)"',
                                  path.read_text())
        self.assertEqual(len(formats), 3)
        for value in formats:
            value = value.replace('%llu', str(2**64-1)).replace('%u', str(2**32-1))
            self.assertNotIn('%', value)
            self.assertLessEqual(len(value.replace(r'\n', '\n').encode()), 255, value)


if __name__ == '__main__':
    unittest.main()
