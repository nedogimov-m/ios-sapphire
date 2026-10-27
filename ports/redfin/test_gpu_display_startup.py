"""Cold output validation has its own finite wait without releasing live work."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class GPUDisplayStartupTests(unittest.TestCase):
    def test_actual_initialization_publication_wait_races_and_late_completion_ownership(self):
        display=(HERE/'gpu-display.inc').read_text();queued=(HERE/'gpu-queued-present.inc').read_text()
        initialize=function(display,'static bool gd_initialize(')
        complete=function(queued,'static void gd_queued_complete(')
        wait=function(queued,'static int gd_queued_wait(')
        source=r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstring>
#include "redfin_gpu_runtime.h"
#include "redfin_gpu_display.h"
#include "redfin_gpu_queue.h"
#include "display-geometry.h"
#define PAGE_SIZE 16384u
struct Memory{uint64_t size;uint64_t getLength(){return size;}};
struct SweetSurface{
 Memory *memory;bool wrapped;uint64_t offset,allocSize;
 uint32_t width,height,bytesPerRow,pixelFormat;
 void *kernelAddress(){return this;}
};
struct gd_buffer{Memory *memory;};
static struct {gd_buffer stage,commands,panel;bool attempted,tested,startup_ready,uncertain;}gd;
static unsigned fault;
static bool gd_allocate(gd_buffer *,uint64_t,bool){return fault!=1;}
static bool gd_check(){return fault!=2;}
static bool gd_map(gd_buffer *,Memory *,uint8_t *,SweetSurface *,uint64_t,bool,bool){return fault!=3;}
static void IOLog(const char *,...){}
'''+initialize+r'''
struct IOLock{bool held;};
struct gd_queued_present{IOLock *lock;unsigned references;bool done;int result;uint64_t cold_deadline;};
typedef unsigned IOReturn;
enum{kIOReturnSuccess=0,THREAD_ABORTSAFE=0,THREAD_AWAKENED=0,THREAD_TIMED_OUT=1,THREAD_INTERRUPTED=2};
static uint64_t now,completion,expected_deadline;static unsigned spurious,sleeps,interrupted,releases;
static void IOLockLock(IOLock *lock){assert(!lock->held);lock->held=true;}
static void IOLockUnlock(IOLock *lock){assert(lock->held);lock->held=false;}
static void IOLockWakeup(IOLock *lock,void *,bool){assert(lock->held);}
static uint64_t gpuNow(){return now;}
static uint64_t gpuQueueAbsolute(uint64_t value){return value;}
static uint64_t gpuQueueOrdinaryDeadline(uint64_t value){return value+RF_GQ_WAIT_NS;}
static void gd_queued_release(gd_queued_present *p){assert(p->references);--p->references;++releases;}
'''+complete+r'''
static int IOLockSleepDeadline(IOLock *lock,void *event,uint64_t deadline,unsigned mode){
 assert(lock->held&&mode==THREAD_ABORTSAFE&&deadline==expected_deadline);++sleeps;
 if(spurious){--spurious;++now;return THREAD_AWAKENED;}
 if(interrupted){now+=100;return THREAD_INTERRUPTED;}
 if(completion<=deadline){
  now=completion;
  auto *p=(gd_queued_present *)((uint8_t *)event-__builtin_offsetof(gd_queued_present,done));
  IOLockUnlock(lock);p->result=1;__atomic_store_n(&gd.startup_ready,true,__ATOMIC_RELEASE);
  gd_queued_complete(p,kIOReturnSuccess);IOLockLock(lock);return THREAD_AWAKENED;
 }
 if(deadline>now)now=deadline;return THREAD_TIMED_OUT;
}
'''+wait+r'''
int main(){
 Memory memory={RF_GD_PANEL_MAPPED};
 SweetSurface panel={&memory,false,0,RF_GD_PANEL_MAPPED,RF_GD_PANEL_W,RF_GD_PANEL_H,RF_GD_PANEL_PITCH,REDFIN_DISPLAY_BGRA};
 for(fault=0;fault<4;++fault){
  gd={};assert(gd_initialize(&panel)==(fault==0));
  assert(gd.attempted&&gd.startup_ready==(fault==0));
 }
 gd={};assert(!gd_initialize(nullptr)&&!gd.startup_ready);
 for(unsigned test=0;test<9;++test){
  gd={};now=1000;sleeps=releases=interrupted=0;spurious=test==2?4:0;
  gd.startup_ready=test==1||test==3||test==6;
  expected_deadline=now+(gd.startup_ready?RF_GQ_WAIT_NS:UINT64_C(10000000000));
  completion=now+(test==1?100000000:2654000000);
  if(test==4)completion=expected_deadline+1;
  if(test==5)interrupted=1;
  IOLock lock={};gd_queued_present p={&lock,2,false,-1,gd.startup_ready?0:expected_deadline};
  if(test==7){now+=UINT64_C(4000000000);completion=now+UINT64_C(2654000000);}
  if(test==8){now=expected_deadline+1;completion=now+1;}
  if(test==6){p.done=true;p.result=1;--p.references;}
  bool success=test==0||test==1||test==2||test==6||test==7;
  assert(gd_queued_wait(&p)==(success?1:-1));
  assert(gd.uncertain==!success&&!lock.held);
  assert(sleeps==(test==6?0u:test==2?5u:1u));
  if(success){assert(!p.references&&p.done);}
  else{
   assert(p.references==1&&!p.done&&releases==1); // caller cannot free in-flight work
   p.result=1;gd_queued_complete(&p,kIOReturnSuccess);
   assert(!p.references&&p.done&&gd.uncertain); // late success never clears a genuine timeout
  }
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-display-startup-') as directory:
            path=Path(directory)/'startup.cpp';path.write_text(source);exe=path.with_suffix('')
            result=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-Wno-unused-function','-Wno-unused-parameter','-Wno-missing-field-initializers',
                '-I'+str(HERE),'-I'+str(HERE/'include'),
                str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
