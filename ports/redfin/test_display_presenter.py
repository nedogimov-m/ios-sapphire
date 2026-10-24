"""Execute the actual presenter/row-worker code with host event locks/threads."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_smp_gui import patched_source

HERE = Path(__file__).resolve().parent
PREFIX = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "display-geometry.h"
#define SWEET_FB_SWAP_REC_SIZE 0x120
#define SWEET_FB_VSYNC_US 16667
#define THREAD_UNINT 0
#define KERN_SUCCESS 0
#ifndef __unused
#define __unused __attribute__((unused))
#endif
typedef int wait_result_t;
typedef void *thread_t;
static unsigned stopped,thread_count,start_calls,fail_start;
static pthread_t threads[8];
struct IOLock {
 pthread_mutex_t mutex;
 struct {const void *event;pthread_cond_t condition;} channels[8];
 unsigned count;
};
static IOLock *IOLockAlloc(void){IOLock *p=(IOLock *)calloc(1,sizeof(*p));assert(p);pthread_mutex_init(&p->mutex,NULL);return p;}
static void IOLockFree(IOLock *p){for(unsigned i=0;i<p->count;i++)pthread_cond_destroy(&p->channels[i].condition);
 pthread_mutex_destroy(&p->mutex);free(p);}
static void IOLockLock(IOLock *p){assert(!pthread_mutex_lock(&p->mutex));}
static void IOLockUnlock(IOLock *p){assert(!pthread_mutex_unlock(&p->mutex));}
static pthread_cond_t *channel(IOLock *p,const void *event){
 for(unsigned i=0;i<p->count;i++)if(p->channels[i].event==event)return &p->channels[i].condition;
 assert(p->count<8);unsigned i=p->count++;p->channels[i].event=event;
 pthread_cond_init(&p->channels[i].condition,NULL);return &p->channels[i].condition;
}
static void IOLockSleep(IOLock *p,const void *event,int mode){(void)mode;
 if(__atomic_load_n(&stopped,__ATOMIC_ACQUIRE)){IOLockUnlock(p);pthread_exit(NULL);}
 pthread_cond_wait(channel(p,event),&p->mutex);
 if(__atomic_load_n(&stopped,__ATOMIC_ACQUIRE)){IOLockUnlock(p);pthread_exit(NULL);}
}
static void IOLockWakeup(IOLock *p,const void *event,bool one){
 if(one)pthread_cond_signal(channel(p,event));else pthread_cond_broadcast(channel(p,event));
}
static uint64_t mach_absolute_time(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *out){*out=n;}
static void absolutetime_to_nanoseconds(uint64_t n,uint64_t *out){*out=n;}
static void *IOMallocData(size_t n){return malloc(n);}
static void *IOMallocZeroData(size_t n){return calloc(1,n);}
static void IOFreeData(void *p,size_t n){(void)n;free(p);}
static void IOLog(const char *format,...){(void)format;}
struct start_info {void (*function)(void *,int);void *argument;};
static void *entry(void *argument){start_info info=*(start_info *)argument;free(argument);info.function(info.argument,0);return NULL;}
static int kernel_thread_start(void (*function)(void *,int),void *argument,thread_t *out){
 ++start_calls;if(fail_start==99 || fail_start==start_calls)return 1;
 start_info *info=(start_info *)malloc(sizeof(*info));*info={function,argument};
 assert(thread_count<8);unsigned i=thread_count++;assert(!pthread_create(&threads[i],NULL,entry,info));*out=(void *)(uintptr_t)(i+1);return 0;
}
static void thread_set_thread_name(thread_t thread,const char *name){(void)thread;(void)name;}
static void thread_deallocate(thread_t thread){(void)thread;}
static int redfin_gui_selected(void){return 1;}
static int redfin_smp_verified(void){return 1;}
struct SweetSurface {
 int references,in_use;uint32_t color,pixels[4];
 void release(void){assert(__atomic_sub_fetch(&references,1,__ATOMIC_ACQ_REL)>=1);}
};
static void sweet_hold_set(SweetSurface **held,bool on){assert(!on);
 for(unsigned i=0;i<4;i++)if(held[i]){assert(__atomic_sub_fetch(&held[i]->in_use,1,__ATOMIC_ACQ_REL)>=0);held[i]->release();held[i]=NULL;}}
struct IOTimerEventSource {uint64_t deadline;unsigned relative;
 void setTimeoutUS(unsigned us){relative=us;}void wakeAtTime(uint64_t at){deadline=at;}};
struct redfin_presenter;
class AppleCLCD {
public:
 bool fRedfinCopyOnly=true,fPowerOff=false;int references=1;
 struct redfin_display_geometry fRedfinFit={};
 struct redfin_display_workspace *fRedfinFitWorkspace=NULL;
 struct redfin_presenter *fRedfinPresenter=NULL;
 IOLock *fLock=NULL;SweetSurface *fShowHold[4]={},*fRetireHold[4]={};
 uint8_t *output=NULL;unsigned finished=0;uint32_t last=0;
 void retain(void){references++;}void release(void){assert(--references>=1);}
 bool startRedfinPresenter(void);void freeRedfinPresenter(void);void armRedfinVsync(IOTimerEventSource *);
 bool queueRedfinPresent(const uint8_t *,SweetSurface **);
 static void redfinPresentMain(void *,int);static void redfinRowsMain(void *,int);
 bool drawRedfinLayer(uint8_t *,uint64_t,uint32_t,const struct redfin_display_surface *,const int32_t *,const int32_t *,uint64_t *);
 void present(const uint8_t *);
};
static SweetSurface surfaces[4];
'''
SUFFIX = r'''
void AppleCLCD::present(const uint8_t *record){
 unsigned id=record[0];assert(id>=1 && id<=3);SweetSurface *s=&surfaces[id];
 for(unsigned i=1;i<SWEET_FB_SWAP_REC_SIZE;i++)assert(record[i]==(uint8_t)(id+37*i));
 assert(__atomic_load_n(&s->references,__ATOMIC_ACQUIRE)>=2 && __atomic_load_n(&s->in_use,__ATOMIC_ACQUIRE)>0);
 redfin_display_surface surface={(uint8_t *)s->pixels,sizeof(s->pixels),0,2,2,8,REDFIN_DISPLAY_BGRA};
 const int32_t source[]={0,0,2,2},destination[]={0,0,1125,2436};uint64_t copied=0;
 assert(redfin_display_clear_margins(&fRedfinFit,output,4320ULL*2340,4320));
 assert(drawRedfinLayer(output,4320ULL*2340,4320,&surface,source,destination,&copied));
 assert(copied==(uint64_t)fRedfinFit.w*fRedfinFit.h*4);
 assert(__atomic_load_n(&s->references,__ATOMIC_ACQUIRE)>=2 && __atomic_load_n(&s->in_use,__ATOMIC_ACQUIRE)>0);
 last=id;__atomic_add_fetch(&finished,1,__ATOMIC_RELEASE);
}
static AppleCLCD *fb;
static void add_hold(unsigned id,SweetSurface **held){
 memset(held,0,4*sizeof(*held));held[0]=&surfaces[id];
 __atomic_add_fetch(&held[0]->references,1,__ATOMIC_ACQ_REL);__atomic_add_fetch(&held[0]->in_use,1,__ATOMIC_ACQ_REL);
}
extern "C" int setup(unsigned failure){
 thread_count=start_calls=stopped=0;fail_start=failure;fb=new AppleCLCD;
 fb->fLock=IOLockAlloc();fb->fRedfinFitWorkspace=(redfin_display_workspace *)malloc(sizeof(redfin_display_workspace));
 fb->output=(uint8_t *)malloc(4320ULL*2340);memset(fb->output,0x35,4320ULL*2340);
 assert(redfin_display_geometry_make(2,1080,2340,1125,2436,&fb->fRedfinFit));
 for(unsigned i=0;i<4;i++){surfaces[i].references=1;surfaces[i].in_use=0;surfaces[i].color=0xff000000u|i*0x123456;
  for(unsigned j=0;j<4;j++)surfaces[i].pixels[j]=surfaces[i].color;}
 assert(fb->startRedfinPresenter());return fb->references;
}
extern "C" unsigned metric(unsigned i){auto *p=fb->fRedfinPresenter;unsigned values[]={p->slices,p->async,thread_count,start_calls};return i<4?values[i]:999;}
extern "C" int hold_and_queue(unsigned id){SweetSurface *held[4];uint8_t record[SWEET_FB_SWAP_REC_SIZE];
 for(unsigned i=0;i<SWEET_FB_SWAP_REC_SIZE;i++)record[i]=(uint8_t)(id+37*i);
 add_hold(id,held);IOLockLock(fb->fLock);bool ok=fb->queueRedfinPresent(record,held);IOLockUnlock(fb->fLock);
 assert((held[0]==NULL)==ok);if(!ok)sweet_hold_set(held,false);return ok;
}
extern "C" void block_pixels(void){IOLockLock(fb->fRedfinPresenter->pixelsLock);}
extern "C" void unblock_pixels(void){IOLockUnlock(fb->fRedfinPresenter->pixelsLock);}
extern "C" int wait_taken(void){for(unsigned i=0;i<5000;i++){
 IOLockLock(fb->fRedfinPresenter->lock);bool empty=!fb->fRedfinPresenter->queued;IOLockUnlock(fb->fRedfinPresenter->lock);
 if(empty)return 1;usleep(1000);}return 0;}
extern "C" int wait_finished(unsigned wanted){for(unsigned i=0;i<5000;i++){
 if(__atomic_load_n(&fb->finished,__ATOMIC_ACQUIRE)>=wanted){
  IOLockLock(fb->fLock);bool shown=fb->fShowHold[0]==&surfaces[fb->last];IOLockUnlock(fb->fLock);
  bool released=true;for(unsigned j=1;j<=3;j++)if(j!=fb->last && __atomic_load_n(&surfaces[j].in_use,__ATOMIC_ACQUIRE))released=false;
  if(shown && released)return 1;
 }usleep(1000);}return 0;}
extern "C" int surface_metric(unsigned id,unsigned n){return __atomic_load_n(n?&surfaces[id].in_use:&surfaces[id].references,__ATOMIC_ACQUIRE);}
extern "C" int output_matches(unsigned id){
 for(unsigned y=0;y<2340;y++)for(unsigned x=0;x<1080;x++){
  auto &g=fb->fRedfinFit;uint32_t expected=x>=g.x && x<g.x+g.w && y>=g.y && y<g.y+g.h?surfaces[id].color:0xff000000u;
  if(((uint32_t *)fb->output)[y*1080+x]!=expected)return 0;}
 return 1;
}
extern "C" void power_off(int off){IOLockLock(fb->fLock);fb->fPowerOff=off;IOLockUnlock(fb->fLock);}
extern "C" void teardown(void){
 auto *p=fb->fRedfinPresenter;
 /* Pixel serialization waits for an active frame and every row to finish. */
 IOLockLock(p->pixelsLock);IOLockUnlock(p->pixelsLock);
 __atomic_store_n(&stopped,1,__ATOMIC_RELEASE);IOLockLock(p->lock);
 for(unsigned i=0;i<p->lock->count;i++)pthread_cond_broadcast(&p->lock->channels[i].condition);
 IOLockUnlock(p->lock);for(unsigned i=0;i<thread_count;i++){pthread_join(threads[i],NULL);fb->release();}
 for(unsigned i=0;i+1<p->slices;i++)free(p->workers[i].workspace);
 sweet_hold_set(fb->fShowHold,false);sweet_hold_set(fb->fRetireHold,false);sweet_hold_set(p->held,false);
 assert(fb->references==1);p->async=false;p->slices=1;fb->freeRedfinPresenter();IOLockFree(fb->fLock);
 free(fb->fRedfinFitWorkspace);free(fb->output);delete fb;fb=NULL;
 for(unsigned i=0;i<4;i++)assert(surfaces[i].references==1 && !surfaces[i].in_use);
}
extern "C" uint64_t next_tick(uint64_t previous,uint64_t now,uint64_t period,uint64_t *missed){return redfin_display_next_tick(previous,now,period,missed);}
extern "C" int slice_equivalence(unsigned slices,unsigned scenario){
 redfin_display_geometry g;assert(redfin_display_geometry_make(2,1080,2340,1125,2436,&g));
 uint8_t *input=(uint8_t *)malloc(16+73*520),*expected=(uint8_t *)malloc(4320ULL*2340),*actual=(uint8_t *)malloc(4320ULL*2340);
 auto *work=(redfin_display_workspace *)malloc(sizeof(redfin_display_workspace));
 for(unsigned i=0;i<16+73*520;i++)input[i]=(uint8_t)(i*19+(i/517)*41);
 memset(expected,0x65,4320ULL*2340);memset(actual,0x65,4320ULL*2340);
 redfin_display_surface s={input,16+73*520,16,128,73,520,REDFIN_DISPLAY_BGRA};
 int32_t src[]={3,2,121,69},dst[]={-30,-70,640,900};
 if(scenario==1){dst[0]=0;dst[1]=0;dst[2]=1125;dst[3]=2436;}
 if(scenario==2){dst[0]=100;dst[1]=200;dst[2]=10;dst[3]=1;}
 uint64_t reference=0,total=0,bytes=0;
 bool ok=redfin_display_draw(&g,work,expected,4320ULL*2340,4320,&s,src,dst,&reference);
 for(unsigned i=slices;i>0;i--){
  bool part=redfin_display_draw_slice(&g,work,actual,4320ULL*2340,4320,&s,src,dst,i-1,slices,&bytes);
  if(part!=ok){free(input);free(expected);free(actual);free(work);return 0;}total+=bytes;
 }
 int equal=reference==total && !memcmp(expected,actual,4320ULL*2340);
 free(input);free(expected);free(actual);free(work);return equal;
}
'''


class DisplayPresenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root / 'RedfinDisplayPacing.h').write_text((HERE / 'display-pacing.h').read_text())
        source, library = root / 'presenter.cpp', root / 'presenter.so'
        source.write_text(PREFIX + (HERE / 'display-presenter.inc').read_text() + SUFFIX)
        result = subprocess.run(['c++', '-std=c++17', '-O2', '-shared', '-fPIC', '-pthread',
                                 '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                                 '-I', str(root), '-I', str(HERE), str(source), '-o', str(library)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library))
        cls.lib.next_tick.argtypes = [C.c_uint64, C.c_uint64, C.c_uint64, C.POINTER(C.c_uint64)]
        cls.lib.next_tick.restype = C.c_uint64

    def test_native_overlay_contains_the_exact_executed_presenter_and_clock(self):
        for native, source in [('RedfinDisplayPresenter.inc', 'display-presenter.inc'),
                               ('RedfinDisplayPacing.h', 'display-pacing.h')]:
            self.assertEqual(patched_source('iokit/Kernel/arm/' + native), (HERE / source).read_text())

    def test_absolute_phase_does_not_accumulate_present_time_or_burst_after_a_pause(self):
        skipped = C.c_uint64(99)
        tick = self.lib.next_tick(0, 1000, 100, C.byref(skipped))
        self.assertEqual((tick, skipped.value), (1100, 0))
        for work in (10, 50, 90, 0, 1):
            previous = tick
            tick = self.lib.next_tick(previous, previous + work, 100, C.byref(skipped))
            self.assertEqual((tick, skipped.value), (previous + 100, 0))
        self.assertEqual(self.lib.next_tick(tick, tick + 350, 100, C.byref(skipped)), tick + 400)
        self.assertEqual(skipped.value, 3)
        for previous, now, period in ((0, 2**64 - 1, 100), (10, 2**64 - 1, 1), (0, 0, 0)):
            self.assertEqual(self.lib.next_tick(previous, now, period, C.byref(skipped)), 0)

    def test_real_mailbox_preserves_full_slot_and_source_holds_through_parallel_copy(self):
        self.assertEqual(self.lib.setup(0), 5)
        self.addCleanup(self.lib.teardown)
        self.assertEqual([self.lib.metric(i) for i in range(4)], [4, 1, 4, 4])
        self.lib.block_pixels()
        try:
            self.assertTrue(self.lib.hold_and_queue(1))
            self.assertTrue(self.lib.wait_taken())
            self.assertEqual([self.lib.surface_metric(1, i) for i in range(2)], [2, 1])
            self.assertTrue(self.lib.hold_and_queue(2))
            self.assertFalse(self.lib.hold_and_queue(3))
            self.assertEqual([self.lib.surface_metric(2, i) for i in range(2)], [2, 1])
            self.assertEqual([self.lib.surface_metric(3, i) for i in range(2)], [1, 0])
        finally:
            self.lib.unblock_pixels()
        self.assertTrue(self.lib.wait_finished(2))
        self.assertTrue(self.lib.output_matches(2))
        self.assertEqual([self.lib.surface_metric(1, i) for i in range(2)], [1, 0])
        self.lib.power_off(1)
        self.assertTrue(self.lib.hold_and_queue(3))
        self.assertTrue(self.lib.wait_taken())

    def test_partial_thread_start_failure_uses_a_complete_scalar_presenter(self):
        self.assertEqual(self.lib.setup(1), 2)
        self.addCleanup(self.lib.teardown)
        self.assertEqual([self.lib.metric(i) for i in range(4)], [1, 1, 1, 2])
        self.assertTrue(self.lib.hold_and_queue(1))
        self.assertTrue(self.lib.wait_finished(1))
        self.assertTrue(self.lib.output_matches(1))

    def test_no_started_thread_leaves_original_synchronous_path_and_no_stranded_holds(self):
        self.assertEqual(self.lib.setup(99), 1)
        self.addCleanup(self.lib.teardown)
        self.assertEqual([self.lib.metric(i) for i in range(4)], [1, 0, 0, 2])
        self.assertFalse(self.lib.hold_and_queue(1))
        self.assertEqual([self.lib.surface_metric(1, i) for i in range(2)], [1, 0])

    def test_clipped_gradient_and_thin_rectangle_pixels_are_independent_of_stripe_order(self):
        for count in (1, 2, 3, 4, 7, 8):
            for scenario in range(3):
                self.assertTrue(self.lib.slice_equivalence(count, scenario), (count, scenario))


if __name__ == '__main__':
    unittest.main()
