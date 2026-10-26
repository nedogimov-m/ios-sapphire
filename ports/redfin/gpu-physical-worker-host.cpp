/* SPDX-License-Identifier: MIT
 * Run the actual FIFO worker and publication/finish methods with delayed
 * admission/fence/lock receivers. This is not a simulation of GPU pixels.
 */
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "include/redfin_gpu_runtime.h"
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"physical worker: %s at %u\n",#x,__LINE__);abort();}}while(0)
using IOReturn=int;using wait_result_t=int;
enum {kIOReturnSuccess=0,kIOReturnNotReady=ENXIO,kIOReturnIOError=EIO,REDFIN_GPU_PUBLISH_DEPTH=2};
static constexpr uint64_t NSEC_PER_MSEC=1000000;
enum {THREAD_UNINT=0};
struct mutex {bool locked=false;};
static mutex queue_lock;
static bool hardware,ready=true;
static uint64_t ticks;
static unsigned issued,done,overlap,published_count,expected_jobs,retired_count,fail_publication;
static unsigned pending_max,quiesces,clean_calls,invalidations;
static bool inject_late,cancel_on_sleep;
struct gpu_queued_job;
static gpu_queued_job *late_job;
static std::vector<unsigned> publications,retirements,kernel_calls,results;
static bool redfin_gpu_ready(){return ready;}
static uint64_t gpuNow(){return ++ticks;}
static void IOLockLock(mutex *m){REQUIRE(!hardware&&!m->locked);m->locked=true;}
static void IOLockUnlock(mutex *m){REQUIRE(m->locked);m->locked=false;}
static void IOLockWakeup(mutex *m,void *,bool){REQUIRE(m->locked);}
struct GPUTransaction {
    GPUTransaction(){REQUIRE(!hardware&&!queue_lock.locked);hardware=true;}
    ~GPUTransaction(){REQUIRE(hardware);hardware=false;}
};
static void IOLog(const char *,...){ }
static void clock_interval_to_deadline(unsigned value,uint64_t unit,uint64_t *out){*out=ticks+value*unit;}
struct ThreadEnded { };
[[noreturn]] static void thread_terminate(void *){throw ThreadEnded{};}
static void *current_thread(){return nullptr;}
struct fake_state {uint32_t words[4]={};void *getBytesNoCopy(){return words;}};
struct fake_surface {fake_state *state;};
struct gpu_buffer {fake_surface *surface=nullptr;bool clientMapped=false;rf_gr_surface_cache cache={};unsigned pending=0;};
struct gpu_queued_bo {gpu_buffer *buffer;uint32_t access;};
#define RF_GA_WRITE 2u
class RedwoodGPUUserClient {
public:
    IOReturn executeQueued(gpu_queued_job *);
    IOReturn finishQueued(gpu_queued_job *);
};
struct gpu_queued_job {
    gpu_queued_job *next=nullptr;RedwoodGPUUserClient *owner=nullptr;
    IOReturn (*kernel_execute)(void *)=nullptr;void *kernel_argument=nullptr;
    uint64_t dequeued=0,locked=0,ran=0,released=0,published=0,wait_began=0,accepted=0,sequence=0;
    uint64_t addresses[1]={};uint32_t words[1]={};unsigned count=1,nr_bos=0,fence=0,physical_fence=0;
    IOReturn publication_status=0;gpu_queued_bo bos[1]={};char process[20]={};int pid=1;
};
static struct {mutex *lock=&queue_lock;gpu_queued_job *head=nullptr,*tail=nullptr;bool stopping=false;unsigned budget=0,retired=0;} gGPUQueue;
static struct {uint64_t cleaning=0,submitting=0,invalidating=0;unsigned skipped=0,submissions=0;} gTiming;
static void enqueue(gpu_queued_job *job)
{if(gGPUQueue.tail)gGPUQueue.tail->next=job;else gGPUQueue.head=job;gGPUQueue.tail=job;}
static void advance_time(uint64_t until)
{
    ticks=std::max(ticks,until);
    done=std::min(issued,(unsigned)(ticks/(5*NSEC_PER_MSEC)));
}
static int IOLockSleepDeadline(mutex *m,void *,uint64_t until,int)
{
    REQUIRE(m->locked&&!hardware);advance_time(until);
    if(inject_late){inject_late=false;REQUIRE(late_job);enqueue(late_job);late_job=nullptr;}
    if(cancel_on_sleep){cancel_on_sleep=false;gGPUQueue.stopping=true;}
    return 0;
}
static int redfin_gpu_quiesce()
{REQUIRE(hardware);++quiesces;advance_time((uint64_t)issued*5*NSEC_PER_MSEC);REQUIRE(done==issued);return 0;}
static int redfin_gpu_publish(const uint64_t *,const uint32_t *,unsigned,uint32_t *out)
{
    REQUIRE(hardware);++published_count;
    if(published_count==fail_publication)return EINVAL;
    REQUIRE(issued-done<2);if(issued>done)++overlap;
    *out=++issued;publications.push_back(issued);pending_max=std::max(pending_max,issued-done);return 0;
}
static int redfin_gpu_poll(uint32_t fence)
{REQUIRE(hardware&&fence&&fence<=issued);return done>=fence?0:EAGAIN;}
static int redfin_gpu_wait(uint32_t fence)
{REQUIRE(hardware&&fence&&fence<=issued);advance_time((uint64_t)fence*5*NSEC_PER_MSEC);REQUIRE(done>=fence);return 0;}
static int redfin_gpu_dvfs_idle(){REQUIRE(hardware&&issued==done);return 0;}
static IOReturn gpuError(int r){return r;}
static void gpuQueueFault(const gpu_queued_job *){REQUIRE(hardware);}
static void gpuTiming(){REQUIRE(hardware);}
static void redfin_gpu_sync(void *,uint64_t,bool){REQUIRE(hardware);}
static bool gpuQueuedSurfaceCache(gpu_queued_job *,unsigned,bool invalidate)
{REQUIRE(hardware&&issued==done);if(invalidate)++invalidations;else++clean_calls;return true;}
#include "actual-physical-methods.inc"
static void gpuPhysicalRetire(gpu_queued_job *job,IOReturn result)
{
    REQUIRE(!hardware&&!queue_lock.locked&&job->sequence==gGPUQueue.retired+1);
    if(job->owner&&result==0)REQUIRE(job->physical_fence&&done>=job->physical_fence);
    if(!job->owner&&result==0)REQUIRE(done==issued);
    for(unsigned i=0;i<job->nr_bos;++i){REQUIRE(job->bos[i].buffer->pending);--job->bos[i].buffer->pending;}
    retirements.push_back((unsigned)job->sequence);results.push_back((unsigned)result);
    ++gGPUQueue.retired;++retired_count;
    if(retired_count==expected_jobs)gGPUQueue.stopping=true;
}
#include "gpu-physical-worker.inc"
static IOReturn kernel_execute(void *argument)
{REQUIRE(hardware&&done==issued);kernel_calls.push_back((unsigned)(uintptr_t)argument);return 0;}
static void run()
{try{redfinGpuQueueWorker(nullptr,0);REQUIRE(false);}catch(ThreadEnded &){}REQUIRE(!hardware&&!queue_lock.locked&&retired_count==expected_jobs);}
static void reset(unsigned count)
{
    ticks=issued=done=overlap=published_count=retired_count=fail_publication=pending_max=quiesces=clean_calls=invalidations=0;
    hardware=false;ready=true;expected_jobs=count;inject_late=cancel_on_sleep=false;late_job=nullptr;
    gGPUQueue={&queue_lock,nullptr,nullptr,false,0,0};gTiming={};
    publications.clear();retirements.clear();kernel_calls.clear();results.clear();
}
static gpu_queued_job make_job(unsigned sequence,RedwoodGPUUserClient *owner)
{gpu_queued_job j;j.sequence=j.fence=sequence;j.owner=owner;return j;}
int main()
{
    RedwoodGPUUserClient client;
    /* A later admission must publish while the original GPU job is still
     * pending, without a fake completion or a lock held across retirement. */
    reset(2);gpu_queued_job a=make_job(1,&client),b=make_job(2,&client);enqueue(&a);late_job=&b;inject_late=true;run();
    REQUIRE(overlap==1&&pending_max==2&&publications.size()==2&&retirements==std::vector<unsigned>({1,2})&&done==2);
    /* A native output callback is a strict retained FIFO/idle boundary. */
    reset(4);a=make_job(1,&client);b=make_job(2,&client);gpu_queued_job output=make_job(3,nullptr),c=make_job(4,&client);
    output.kernel_execute=kernel_execute;output.kernel_argument=(void *)3;
    enqueue(&a);enqueue(&b);enqueue(&output);enqueue(&c);run();
    REQUIRE(retirements==std::vector<unsigned>({1,2,3,4})&&kernel_calls==std::vector<unsigned>({3})&&publications.size()==3);
    /* The actual source methods quiesce before CPU cache ownership transfer,
     * and after a real written-surface fence before invalidating its bytes. */
    reset(2);fake_state state;fake_surface surface{&state};gpu_buffer buffer;
    buffer.surface=&surface;buffer.clientMapped=true;buffer.pending=2;
    a=make_job(1,&client);b=make_job(2,&client);a.nr_bos=b.nr_bos=1;a.bos[0]=b.bos[0]={&buffer,RF_GA_WRITE};enqueue(&a);enqueue(&b);run();
    REQUIRE(clean_calls==2&&invalidations==2&&quiesces>=4&&!buffer.pending);
    /* A publication error cannot retire before its actual predecessor. */
    reset(2);a=make_job(1,&client);b=make_job(2,&client);fail_publication=2;enqueue(&a);enqueue(&b);run();
    REQUIRE(retirements==std::vector<unsigned>({1,2})&&results[0]==0&&results[1]==EINVAL&&done==1);
    /* Stopping with one real job pending drains it, then cancels the later
     * admission without ever publishing its command bytes. */
    reset(2);a=make_job(1,&client);b=make_job(2,&client);enqueue(&a);late_job=&b;inject_late=cancel_on_sleep=true;run();
    REQUIRE(publications.size()==1&&done==1&&results[0]==0&&results[1]==kIOReturnNotReady);
    puts("actual physical worker: late overlap/FIFO/output/cache/error/stop/retirement PASS");return 0;
}
