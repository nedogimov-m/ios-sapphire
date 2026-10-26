/* SPDX-License-Identifier: MIT */
/* Host event/descriptor fixture for the actual retained kernel queue and
 * presentation include. Hardware execution is deliberately controlled here;
 * actual A620 pixels remain a separate combined device contract. */
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <vector>
#include "include/redfin_gpu_scope.h"
#include "include/redfin_gpu_runtime.h"
#include "include/redfin_gpu_queue.h"
#include "display-geometry.h"

using IOReturn=int;using IOByteCount=uint64_t;using SInt64=long long;using wait_result_t=int;
enum {kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnBusy=2,kIOReturnTimeout=3,
 kIOReturnNotReady=4,kIOReturnIOError=5,kIOReturnAborted=6,kIOReturnNoMemory=7};
enum {THREAD_ABORTSAFE=0,THREAD_UNINT=1,THREAD_AWAKENED=0,THREAD_TIMED_OUT=1};
#define NSEC_PER_MSEC 1000000ull
#define RF_GD_LAYERS 4
#define kIOMemoryMapperNone 0
#define IONew(T,n) ((T *)malloc(sizeof(T)*(n)))
#define IONewZero(T,n) ((T *)calloc((n),sizeof(T)))
#define IODelete(p,T,n) free(p)
struct IOLock {std::mutex mutex;std::condition_variable condition;};
static std::atomic<unsigned> wait_events{0};
static IOLock *IOLockAlloc(){return new IOLock;}
static void IOLockFree(IOLock *lock){delete lock;}
static void IOLockLock(IOLock *lock){lock->mutex.lock();}
static void IOLockUnlock(IOLock *lock){lock->mutex.unlock();}
static void IOLockWakeup(IOLock *lock,const void *,bool){lock->condition.notify_all();}
static uint64_t gpuNow(){
 return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
  std::chrono::steady_clock::now().time_since_epoch()).count();
}
static int IOLockSleepDeadline(IOLock *lock,const void *,uint64_t end,int){
 ++wait_events;
 std::unique_lock<std::mutex> held(lock->mutex,std::adopt_lock);
 auto result=lock->condition.wait_until(held,std::chrono::steady_clock::time_point(std::chrono::nanoseconds(end)));
 held.release();return result==std::cv_status::timeout?THREAD_TIMED_OUT:THREAD_AWAKENED;
}
static void nanoseconds_to_absolutetime(uint64_t ns,uint64_t *out){*out=ns;}
static void clock_interval_to_deadline(unsigned value,uint64_t scale,uint64_t *out){*out=gpuNow()+value*scale;}
static void *current_thread(){return nullptr;}
static void thread_terminate(void *){}
static std::atomic<bool> runtime_ready{true};
static bool redfin_gpu_ready(){return runtime_ready.load();}
static int redfin_gpu_dvfs_idle(){return 0;}
static void redfin_gpu_poison(const char *){runtime_ready=false;}
static IOReturn gpuError(int error){
 switch(error){case 0:return 0;case EINVAL:case ERANGE:return 1;case EBUSY:return 2;
  case ETIMEDOUT:return 3;case ECANCELED:case ENXIO:return 4;default:return 5;}
}
static IOLock *gLock;
static thread_local bool hardware_held=false;
struct GPUTransaction {
 GPUTransaction(){IOLockLock(gLock);assert(!hardware_held);hardware_held=true;}
 ~GPUTransaction(){assert(hardware_held);hardware_held=false;IOLockUnlock(gLock);}
};
struct IOMemoryDescriptor {
 uint64_t physical[4]={};unsigned count=0;
 uint64_t getLength(){return count*4096ull;}
 uint64_t getPhysicalSegment(uint64_t offset,IOByteCount *length,int){
  if(offset>=getLength()){*length=0;return 0;}*length=4096;return physical[offset/4096];
 }
};
struct FakeState {alignas(16) uint64_t bytes[8]={};void *getBytesNoCopy(){return bytes;}};
struct SweetSurface {
 unsigned id=0;int references=1;IOMemoryDescriptor *memory=nullptr;FakeState *state=nullptr;
 void retain(){__atomic_add_fetch(&references,1,__ATOMIC_ACQ_REL);}
 void release(){assert(!hardware_held);assert(__atomic_sub_fetch(&references,1,__ATOMIC_ACQ_REL)>=1);}
 uint64_t in_use(){return __atomic_load_n(&state->bytes[3],__ATOMIC_ACQUIRE);}
};
static SweetSurface *surface_table[4];
static SweetSurface *sweet_surface_copy(unsigned id){
 if(id>=4||!surface_table[id])return nullptr;surface_table[id]->retain();return surface_table[id];
}
static SInt64 OSAddAtomic64(SInt64 value,volatile SInt64 *at){return __atomic_fetch_add(at,value,__ATOMIC_ACQ_REL);}
struct gpu_buffer {uint32_t *pages=nullptr,page_count=0,pending=0;uint64_t size=0,generation=1;};
struct gpu_queued_job;
struct msm_timespec {int64_t seconds,nanoseconds;};
struct msm_cpu_prep {uint32_t handle,op;msm_timespec timeout;};
class RedwoodGPUUserClient {
public:
 IOLock *clientLock=nullptr;gpu_buffer buffers[3];rf_gq_client queue={};bool closed=false;int references=1;
 gpu_buffer *buffer(unsigned id){return id&&id<=3&&buffers[id-1].pages?&buffers[id-1]:nullptr;}
 void retain(){__atomic_add_fetch(&references,1,__ATOMIC_ACQ_REL);}
 void release(){assert(!hardware_held);assert(__atomic_sub_fetch(&references,1,__ATOMIC_ACQ_REL)>=1);}
 IOReturn executeQueued(gpu_queued_job *);
 void retireQueued(gpu_queued_job *,IOReturn);
 IOReturn prepareRange(rf_gw_cpu_range *,bool whole=false);
 IOReturn prepareQueued(msm_cpu_prep *);
};
/* ACTUAL_QUEUE_DECLARATIONS_AND_WAIT */
/* ACTUAL_QUEUE_WORKER */
/* ACTUAL_CLIENT_RETIREMENT_AND_PREPARATION */

static std::mutex gate_lock,order_lock;
static std::condition_variable gate_changed;
static bool first_allowed=false,future_allowed=false;
static std::atomic<unsigned> active_user{0};
static std::vector<unsigned> order;
IOReturn RedwoodGPUUserClient::executeQueued(gpu_queued_job *job){
 assert(hardware_held);
 {std::lock_guard<std::mutex> held(order_lock);order.push_back(job->count);}
 active_user=job->count;
 std::unique_lock<std::mutex> gate(gate_lock);
 gate_changed.wait(gate,[&]{return job->count==1?first_allowed:future_allowed;});
 return kIOReturnSuccess;
}
static struct {bool uncertain=false;} gd;
static bool RedfinGPUDisplayWritable(){return !__atomic_load_n(&gd.uncertain,__ATOMIC_ACQUIRE);}
static bool gd_selected(){return true;}
static uint32_t gd_u32(const uint8_t *at){uint32_t value;memcpy(&value,at,4);return value;}
static std::atomic<unsigned> shown{0};static int fake_present_result=1;
static int gd_present_locked(SweetSurface *,const redfin_display_geometry *,const uint8_t *record){
 if(!RedfinGPUDisplayWritable())return -1;
 assert(hardware_held);SweetSurface *source=surface_table[gd_u32(record+0x54)];
 assert(source&&source->references>=2&&source->in_use()>=1);
 {std::lock_guard<std::mutex> held(order_lock);order.push_back(99);}
 if(fake_present_result>0)shown=source->id;
 if(fake_present_result<0)runtime_ready=false;
 return fake_present_result;
}
#include "gpu-queued-present.inc"

static void wait_for(bool (*predicate)()){
 uint64_t end=gpuNow()+1000000000ull;
 while(!predicate()){assert(gpuNow()<end);std::this_thread::yield();}
}
static bool display_admitted(){
 IOLockLock(gGPUQueue.lock);bool done=gGPUQueue.issued>=2;IOLockUnlock(gGPUQueue.lock);return done;
}
static bool third_retired(){
 IOLockLock(gGPUQueue.lock);bool done=gGPUQueue.retired>=3;IOLockUnlock(gGPUQueue.lock);return done;
}
static bool future_started(){return active_user.load()==2;}
static void enqueue_user(RedwoodGPUUserClient *client,unsigned id,unsigned page){
 auto *job=IONewZero(gpu_queued_job,1);assert(job);
 job->owner=client;client->retain();job->count=id;job->charge=sizeof(*job);
 assert(!gpuQueueReserve(job->charge));IOLockLock(client->clientLock);
 assert(!rf_gq_accept(&client->queue,&job->fence));
 IOLockLock(gGPUQueue.lock);job->sequence=++gGPUQueue.issued;
 assert(!rf_gw_mark(gGPUQueue.page_use,&page,1,job->sequence));
 if(gGPUQueue.tail)gGPUQueue.tail->next=job;else gGPUQueue.head=job;gGPUQueue.tail=job;
 IOLockWakeup(gGPUQueue.lock,&gGPUQueue.head,false);IOLockUnlock(gGPUQueue.lock);
 IOLockUnlock(client->clientLock);
}
static void setup(){
 gGPUQueue={};gGPUQueue.lock=IOLockAlloc();gGPUQueue.page_use=IONewZero(uint64_t,RF_GW_PAGES);
 assert(gGPUQueue.page_use);gLock=IOLockAlloc();runtime_ready=true;gd.uncertain=false;shown=0;
 order.clear();active_user=0;first_allowed=future_allowed=false;fake_present_result=1;
}
static void stop(std::thread &worker){
 runtime_ready=false;IOLockLock(gGPUQueue.lock);gGPUQueue.stopping=true;
 IOLockWakeup(gGPUQueue.lock,&gGPUQueue.head,false);IOLockUnlock(gGPUQueue.lock);
 worker.join();
}
static void teardown(){
 assert(!gGPUQueue.head&&!gGPUQueue.budget.jobs&&!gGPUQueue.budget.bytes);
 IODelete(gGPUQueue.page_use,uint64_t,RF_GW_PAGES);IOLockFree(gGPUQueue.lock);IOLockFree(gLock);
}
static rf_gw_cpu_range request(unsigned handle,unsigned op,uint64_t offset,uint64_t bytes){
 uint64_t end=gpuNow()+1000000000ull;
 return {handle,op,offset,bytes,(int64_t)(end/1000000000),(int64_t)(end%1000000000)};
}
extern "C" int queue_contract(){
 setup();RedwoodGPUUserClient client;client.clientLock=IOLockAlloc();
 uint32_t a[]={0},parent[]={0,1},alias[]={0};
 client.buffers[0]={a,1,0,4096,1};client.buffers[1]={parent,2,0,8192,2};
 client.buffers[2]={alias,1,0,4096,3};
 IOMemoryDescriptor memory={{RF_GW_RAM_BASE},1},panel_memory={{0xa0000000},1};
 FakeState state,panel_state;SweetSurface source={1,1,&memory,&state},panel={0,1,&panel_memory,&panel_state};
 surface_table[1]=&source;
 redfin_display_geometry geometry={};assert(redfin_display_geometry_make(1,1080,2340,1125,2436,&geometry));
 uint8_t record[0x120]={};unsigned one=1;memcpy(record+0x104,&one,4);memcpy(record+0x54,&one,4);
 enqueue_user(&client,1,2);
 std::thread worker([]{redfinGpuQueueWorker(nullptr,0);});
 int result=-99;
 std::thread display([&]{result=RedfinGPUPresent(&panel,&geometry,record);});
 wait_for(display_admitted);assert(source.references==2&&source.in_use()==1);
 enqueue_user(&client,2,1);
 {std::lock_guard<std::mutex> held(gate_lock);first_allowed=true;}gate_changed.notify_all();
 wait_for(future_started);display.join();
 assert(result==1&&shown==1&&source.references==1&&!source.in_use()&&panel.references==1);
 {std::lock_guard<std::mutex> held(order_lock);assert((order==std::vector<unsigned>{1,99,2}));}
 auto read=request(1,1,0,4096);assert(!client.prepareRange(&read));
 read=request(3,1,0,4096);assert(!client.prepareRange(&read)); /* physical alias */
 assert(!redfin_gpu_queue_memory_barrier(&memory)); /* future page1 is unrelated */
 auto full=request(2,5,0,8192);assert(client.prepareRange(&full)==kIOReturnBusy);
 msm_cpu_prep legacy={2,5,{full.seconds,full.nanoseconds}};
 assert(client.prepareQueued(&legacy)==kIOReturnBusy);
 auto bad=request(2,1,8192,1);assert(client.prepareRange(&bad)==kIOReturnBadArgument);
 {std::lock_guard<std::mutex> held(gate_lock);future_allowed=true;}gate_changed.notify_all();
 wait_for(third_retired);full.op=1;assert(!client.prepareRange(&full));
 assert(!redfin_gpu_queue_memory_barrier(&panel_memory)); /* preserved foreign fallback */
 stop(worker);assert(client.references==1&&!client.queue.pending&&client.queue.completed==2);
 /* A close/reuse during an actual wait must not certify the new handle. */
 gGPUQueue.issued=4;gGPUQueue.retired=3;gGPUQueue.page_use[0]=4;
 read=request(1,1,0,4096);unsigned slept=wait_events.load();result=-99;
 std::thread stale([&]{result=client.prepareRange(&read);});
 while(wait_events.load()==slept)std::this_thread::yield();
 IOLockLock(client.clientLock);++client.buffers[0].generation;IOLockUnlock(client.clientLock);
 IOLockLock(gGPUQueue.lock);gGPUQueue.retired=4;IOLockWakeup(gGPUQueue.lock,&gGPUQueue.retired,false);IOLockUnlock(gGPUQueue.lock);
 stale.join();assert(result==kIOReturnBadArgument);
 gGPUQueue.issued=6;gGPUQueue.retired=4;gGPUQueue.first_failed=5;gGPUQueue.page_use[0]=6;
 read=request(1,5,0,4096);assert(client.prepareRange(&read)==kIOReturnBusy);
 gGPUQueue.retired=6;read.op=1;assert(client.prepareRange(&read)==kIOReturnIOError);
 IOLockFree(client.clientLock);teardown();
 /* Unknown completion releases CPU metadata but preserves source/in-use holds. */
 setup();fake_present_result=-1;source.references=panel.references=1;state.bytes[3]=0;
 std::thread failing([]{redfinGpuQueueWorker(nullptr,0);});
 assert(RedfinGPUPresent(&panel,&geometry,record)==-1&&!RedfinGPUDisplayWritable());
 failing.join();assert(source.references==2&&source.in_use()==1&&panel.references==2&&!shown.load());
 teardown();
 /* Caller timeout cannot free payload/sources while its FIFO job still
  * belongs to a blocked worker. The late callback retires its own reference. */
 setup();source.references=panel.references=1;state.bytes[3]=0;
 client.queue={};client.references=1;client.clientLock=IOLockAlloc();
 enqueue_user(&client,1,2);
 std::thread late([]{redfinGpuQueueWorker(nullptr,0);});
 result=RedfinGPUPresent(&panel,&geometry,record);
 assert(result==-1&&!RedfinGPUDisplayWritable()&&source.references==2&&source.in_use()==1);
 {std::lock_guard<std::mutex> held(gate_lock);first_allowed=true;}gate_changed.notify_all();
 for(;;){
  IOLockLock(gGPUQueue.lock);bool retired=gGPUQueue.retired==2;IOLockUnlock(gGPUQueue.lock);
  if(retired)break;std::this_thread::yield();
 }
 stop(late);assert(source.references==2&&source.in_use()==1&&panel.references==2&&!shown.load());
 assert(client.references==1&&!client.queue.pending);IOLockFree(client.clientLock);teardown();return 0;
}
