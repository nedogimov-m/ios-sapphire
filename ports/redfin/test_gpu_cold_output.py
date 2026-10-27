"""Exercise actual FIFO wait policy across one cold output and ordinary work."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class GPUColdOutputTests(unittest.TestCase):
    def test_shared_cold_dependency_deadline_and_original_caller_bounds(self):
        actual=(HERE/'gpu-scoped-waits.inc').read_text()
        body='\n'.join(function(actual,name) for name in (
            'static bool gpuQueueColdOutputPendingLocked(',
            'static uint64_t gpuQueueOrdinaryDeadline(',
            'static IOReturn gpuQueueWaitDeadlineLocked(',
            'static void gpuQueueAfterColdOutputLocked(',
            'static IOReturn gpuQueueWaitTargetLocked('))
        source=r'''
#include <cassert>
#include <cstdint>
#include "redfin_gpu_queue.h"
using IOReturn=int;
enum{kIOReturnSuccess,kIOReturnBadArgument,kIOReturnBusy,kIOReturnTimeout,kIOReturnAborted,kIOReturnIOError};
enum{THREAD_ABORTSAFE,THREAD_AWAKENED=0,THREAD_TIMED_OUT=1};
struct msm_timespec{int64_t seconds,nanoseconds;};
static struct{int lock;uint64_t issued,retired,first_failed,cold_output_sequence,cold_output_deadline;}gGPUQueue;
static uint64_t now,expected_first,expected_second,cold_complete,target_complete;
static unsigned sleeps,spurious;
static bool ready=true;
static uint64_t gpuNow(){return now;}
static uint64_t gpuQueueAbsolute(uint64_t ns){return ns;}
static bool redfin_gpu_ready(){return ready;}
static int IOLockSleepDeadline(int lock,void *event,uint64_t deadline,unsigned mode){
 assert(lock==1&&event==&gGPUQueue.retired&&mode==THREAD_ABORTSAFE);++sleeps;
 assert(deadline==(gGPUQueue.retired<2?expected_first:expected_second));
 if(spurious){--spurious;now+=100000;return THREAD_AWAKENED;}
 uint64_t next=gGPUQueue.retired<2?cold_complete:target_complete;
 if(next>deadline){now=deadline;return THREAD_TIMED_OUT;}
 now=next;gGPUQueue.retired=gGPUQueue.retired<2?2:3;return THREAD_AWAKENED;
}
'''+body+r'''
static void reset(bool cold){
 now=UINT64_C(1000000000);sleeps=spurious=0;ready=true;
 gGPUQueue={1,3,1,0,cold?2u:0u,cold?now+RF_GQ_COLD_OUTPUT_NS:0};
 cold_complete=now+UINT64_C(4930000000);target_complete=cold_complete+UINT64_C(100000000);
 expected_first=cold?gGPUQueue.cold_output_deadline:now+RF_GQ_WAIT_NS;
 expected_second=cold_complete+RF_GQ_WAIT_NS;
}
int main(){
 // Reproduce the original2s readback failure behind a4.93s FIFO predecessor.
 reset(false);assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnTimeout&&sleeps==1);
 // The identical real dependency completes under the one shared cold lease.
 reset(true);assert(!gpuQueueWaitTargetLocked(3,nullptr,false)&&sleeps==2&&gGPUQueue.retired==3);
 reset(true);spurious=6;assert(!gpuQueueWaitTargetLocked(3,nullptr,false)&&sleeps==8);
 // Both shorter and longer caller deadlines remain actual absolute bounds.
 reset(true);msm_timespec short_wait={2,0};expected_first=UINT64_C(2000000000);
 assert(gpuQueueWaitTargetLocked(3,&short_wait,false)==kIOReturnTimeout&&now==expected_first);
 reset(true);msm_timespec long_wait={20,0};assert(!gpuQueueWaitTargetLocked(3,&long_wait,false));
 reset(true);long_wait={6,0};expected_first=UINT64_C(6000000000);expected_second=expected_first;
 assert(gpuQueueWaitTargetLocked(3,&long_wait,false)==kIOReturnTimeout&&now==expected_first);
 reset(true);long_wait={7,0};expected_first=UINT64_C(7000000000);expected_second=expected_first;
 assert(!gpuQueueWaitTargetLocked(3,&long_wait,false));
 // A later client cannot turn cold readiness into an ordinary long timeout.
 reset(true);target_complete=cold_complete+RF_GQ_WAIT_NS+1;
 assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnTimeout&&sleeps==2&&now==expected_second);
 // Unrelated and already-retired cold sequences never borrow its allowance.
 reset(true);gGPUQueue.cold_output_sequence=4;expected_first=now+RF_GQ_WAIT_NS;
 assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnTimeout&&sleeps==1);
 reset(true);gGPUQueue.retired=2;target_complete=now+RF_GQ_WAIT_NS+1;expected_second=now+RF_GQ_WAIT_NS;
 assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnTimeout&&sleeps==1);
 // Frozen shared deadline, no restart for late consumers or endless wakes.
 reset(true);cold_complete=gGPUQueue.cold_output_deadline+1;
 assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnTimeout&&now==expected_first);
 reset(true);uint64_t lease=gGPUQueue.cold_output_deadline;now+=UINT64_C(4000000000);
 uint64_t end=0;assert(!gpuQueueWaitDeadlineLocked(3,nullptr,&end)&&end==lease);
 assert(gGPUQueue.cold_output_deadline==lease);
 reset(true);assert(gpuQueueWaitTargetLocked(3,nullptr,true)==kIOReturnBusy&&!sleeps);
 msm_timespec invalid={-1,0};assert(gpuQueueWaitTargetLocked(3,&invalid,false)==kIOReturnBadArgument&&!sleeps);
 invalid={0,1000000000};assert(gpuQueueWaitTargetLocked(3,&invalid,false)==kIOReturnBadArgument&&!sleeps);
 reset(true);gGPUQueue.retired=3;gGPUQueue.first_failed=2;
 assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnIOError&&!sleeps);
 reset(true);gGPUQueue.retired=3;ready=false;
 assert(gpuQueueWaitTargetLocked(3,nullptr,false)==kIOReturnIOError&&!sleeps);
 now=UINT64_MAX-1;gGPUQueue.cold_output_deadline=UINT64_MAX-1;
 assert(gpuQueueOrdinaryDeadline(now)==UINT64_MAX);
 assert(!gpuQueueWaitDeadlineLocked(3,nullptr,&end)&&end==UINT64_MAX);
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-cold-output-') as directory:
            root=Path(directory);path=root/'waits.cpp';path.write_text(source);exe=root/'waits'
            built=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE/'include'),str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
