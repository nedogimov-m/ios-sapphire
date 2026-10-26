/* SPDX-License-Identifier: MIT
 * CPU admission is asynchronous; a single native owner executes retained jobs
 * using the already verified hardware submit/fence path. No early success is
 * reported by WaitFence/CpuPrep or display consumers. Lock order:
 * client -> queue (short admission), client -> hardware (map/release only).
 * The worker never acquires a client/queue lock while holding hardware.
 */
struct gpu_queued_bo {gpu_buffer *buffer;uint32_t handle,flags;};
struct gpu_queued_job {
    gpu_queued_job *next;
    RedwoodGPUUserClient *owner;
    IOReturn (*kernel_execute)(void *);
    void (*kernel_complete)(void *,IOReturn);
    void *kernel_argument;
    const uint32_t *scope_pages;uint32_t scope_count;
    gpu_queued_bo *bos;
    uint64_t addresses[RF_GR_COMMANDS],sequence,charge,accepted;
    uint32_t words[RF_GR_COMMANDS],count,nr_bos,fence,physical_fence;
    char process[20];int pid;
};
static struct {
    IOLock *lock;
    gpu_queued_job *head,*tail;
    rf_gq_budget budget;
    uint64_t *page_use;
    uint64_t issued,retired,first_failed,executed;
    bool stopping;
} gGPUQueue;
static uint64_t gpuQueueAbsolute(uint64_t ns)
{uint64_t ticks=0;nanoseconds_to_absolutetime(ns,&ticks);return ticks;}
#include "RedfinGPUScopedWaits.inc"
static IOReturn gpuQueueReserve(uint64_t bytes)
{
    if(!gGPUQueue.lock)return kIOReturnNotReady;
    uint64_t end=gpuQueueAbsolute(gpuNow()+RF_GQ_WAIT_NS);
    IOLockLock(gGPUQueue.lock);
    IOReturn result=kIOReturnSuccess;
    for(;;) {
        if(gGPUQueue.stopping||!redfin_gpu_ready()){result=kIOReturnNotReady;break;}
        int error=rf_gq_reserve(&gGPUQueue.budget,bytes);
        if(!error)break;
        if(error!=EAGAIN){result=gpuError(error);break;}
        int waited=IOLockSleepDeadline(gGPUQueue.lock,&gGPUQueue.budget,end,THREAD_ABORTSAFE);
        if(waited==THREAD_TIMED_OUT){result=kIOReturnTimeout;break;}
        if(waited!=THREAD_AWAKENED){result=kIOReturnAborted;break;}
    }
    IOLockUnlock(gGPUQueue.lock);return result;
}
static void gpuQueueUnreserve(uint64_t bytes)
{
    IOLockLock(gGPUQueue.lock);
    if(rf_gq_unreserve(&gGPUQueue.budget,bytes))redfin_gpu_poison("queued admission accounting changed");
    IOLockWakeup(gGPUQueue.lock,&gGPUQueue.budget,false);IOLockUnlock(gGPUQueue.lock);
}
static IOReturn redfinGpuQueueBarrier(const msm_timespec *timeout,bool nonblocking)
{
    if(!gGPUQueue.lock)return kIOReturnNotReady;
    IOLockLock(gGPUQueue.lock);
    IOReturn result=gpuQueueWaitTargetLocked(gGPUQueue.issued,timeout,nonblocking);
    IOLockUnlock(gGPUQueue.lock);return result;
}
static void redfinGpuQueueWorker(void *,wait_result_t)
{
    for(;;) {
        IOLockLock(gGPUQueue.lock);
        if(!gGPUQueue.head) {
            if(gGPUQueue.stopping||!redfin_gpu_ready()){IOLockUnlock(gGPUQueue.lock);break;}
            uint64_t wake=0;clock_interval_to_deadline(100,NSEC_PER_MSEC,&wake);
            (void)IOLockSleepDeadline(gGPUQueue.lock,&gGPUQueue.head,wake,THREAD_UNINT);
        }
        gpu_queued_job *job=gGPUQueue.head;bool cancelled=gGPUQueue.stopping;
        if(job){gGPUQueue.head=job->next;if(!gGPUQueue.head)gGPUQueue.tail=NULL;}
        IOLockUnlock(gGPUQueue.lock);
        if(!job) {if(redfin_gpu_ready()){GPUTransaction hardware;(void)redfin_gpu_dvfs_idle();}continue;}
        IOReturn result=kIOReturnNotReady;
        {GPUTransaction hardware;if(!cancelled&&redfin_gpu_ready())
            result=job->kernel_execute?job->kernel_execute(job->kernel_argument):job->owner->executeQueued(job);}
        /* Hardware is unlocked before any client waiter or object release. */
        if(job->owner)job->owner->retireQueued(job,result);
        IOLockLock(gGPUQueue.lock);
        if(job->sequence!=gGPUQueue.retired+1)redfin_gpu_poison("global queued retirement order changed");
        gGPUQueue.retired=job->sequence;++gGPUQueue.executed;
        if(result!=kIOReturnSuccess&&!gGPUQueue.first_failed)gGPUQueue.first_failed=job->sequence;
        IOLockWakeup(gGPUQueue.lock,&gGPUQueue.retired,false);IOLockUnlock(gGPUQueue.lock);
        if(job->kernel_complete)job->kernel_complete(job->kernel_argument,result);
        RedwoodGPUUserClient *owner=job->owner;uint64_t charge=job->charge;
        if(job->bos)IODelete(job->bos,gpu_queued_bo,job->nr_bos);IODelete(job,gpu_queued_job,1);
        gpuQueueUnreserve(charge);if(owner)owner->release();
    }
    IOLockLock(gGPUQueue.lock);gGPUQueue.stopping=true;
    IOLockWakeup(gGPUQueue.lock,&gGPUQueue.budget,false);IOLockWakeup(gGPUQueue.lock,&gGPUQueue.retired,false);
    IOLockUnlock(gGPUQueue.lock);thread_terminate(current_thread());
}
static bool redfinGpuQueueStart(void)
{
    gGPUQueue.lock=IOLockAlloc();if(!gGPUQueue.lock)return false;
    gGPUQueue.page_use=IONewZero(uint64_t,RF_GW_PAGES);if(!gGPUQueue.page_use)return false;
    thread_t worker=THREAD_NULL;
    kern_return_t result=kernel_thread_start(redfinGpuQueueWorker,NULL,&worker);
    if(result!=KERN_SUCCESS){gGPUQueue.stopping=true;return false;}
    thread_set_thread_name(worker,"redfin retained GPU queue");thread_deallocate(worker);return true;
}
static void redfinGpuQueueStop(void)
{
    if(!gGPUQueue.lock)return;
    IOLockLock(gGPUQueue.lock);gGPUQueue.stopping=true;
    IOLockWakeup(gGPUQueue.lock,&gGPUQueue.head,false);IOLockWakeup(gGPUQueue.lock,&gGPUQueue.budget,false);
    IOLockUnlock(gGPUQueue.lock);
}
IOReturn RedwoodGPUUserClient::submit(msm_submit *r,const rf_gw_submit_extension *scope)
{
    if(!r->nr_cmds||r->nr_cmds>RF_GR_COMMANDS||!r->nr_bos||r->nr_bos>RF_GR_OBJECTS||
       (r->flags&~0x80000010u)||(r->flags&0xffu)!=0x10u||r->nr_in||r->nr_out||r->in_syncobjs||r->out_syncobjs||r->pad)
        return kIOReturnBadArgument;
    if(scope&&(!scope->ranges||!scope->count||scope->count>RF_GW_MAX_RANGES||scope->reserved))return kIOReturnBadArgument;
    uint32_t nr_ranges=scope?scope->count:0;
    uint64_t charge=sizeof(gpu_queued_job)+(uint64_t)r->nr_bos*sizeof(gpu_queued_bo)+
        (uint64_t)r->nr_cmds*sizeof(msm_cmd)+(uint64_t)nr_ranges*sizeof(rf_gw_submit_range);
    IOReturn result=gpuQueueReserve(charge);if(result!=kIOReturnSuccess)return result;
    rf_gw_submit_range *ranges=nr_ranges?IONew(rf_gw_submit_range,nr_ranges):NULL;
    bool covered[RF_GW_MAX_BOS]={};
    gpu_queued_job *job=IONewZero(gpu_queued_job,1);
    msm_bo *bos=IONew(msm_bo,r->nr_bos);msm_cmd *commands=IONew(msm_cmd,r->nr_cmds);
    if(job)job->bos=IONewZero(gpu_queued_bo,r->nr_bos);
    if(!job||!job->bos||!bos||!commands||(nr_ranges&&!ranges)){result=kIOReturnNoMemory;goto done;}
    if(copyin((user_addr_t)r->bos,bos,r->nr_bos*sizeof(*bos))||copyin((user_addr_t)r->cmds,commands,r->nr_cmds*sizeof(*commands))) {
        result=kIOReturnVMError;goto done;
    }
    if(nr_ranges&&copyin((user_addr_t)scope->ranges,ranges,nr_ranges*sizeof(*ranges))) {
        result=kIOReturnVMError;goto done;
    }
    IOLockLock(clientLock);
    if(closed||queue.closing||queue.failed||!redfin_gpu_ready()||r->queue>nextQueue){result=kIOReturnNotReady;goto unlock;}
    for(unsigned i=0;i<r->nr_bos;++i) {
        gpu_buffer *b=buffer(bos[i].handle);
        if(!b||!b->pages||b->page_count!=b->size/RF_GW_PAGE_BYTES||
           !rf_gr_submit_bo(bos[i].flags,bos[i].presumed,b?b->address:0)||b->pending==UINT32_MAX){result=kIOReturnBadArgument;goto unlock;}
        job->bos[i]={b,bos[i].handle,bos[i].flags};
    }
    for(unsigned i=0;i<nr_ranges;++i) {
        const rf_gw_submit_range *range=&ranges[i];
        gpu_buffer *b=range->bo<r->nr_bos?job->bos[range->bo].buffer:NULL;
        if(!b||range->reserved||!range->bytes||range->offset>b->size||range->bytes>b->size-range->offset) {
            result=kIOReturnBadArgument;goto unlock;
        }
        covered[range->bo]=true;
    }
    if(nr_ranges)for(unsigned i=0;i<r->nr_bos;++i)
        if(!covered[i]){result=kIOReturnBadArgument;goto unlock;}
    for(unsigned i=0;i<r->nr_cmds;++i) {
        const msm_cmd *cmd=&commands[i];if(cmd->type!=1){if(cmd->type==2||cmd->type==3)continue;result=kIOReturnBadArgument;goto unlock;}
        gpu_buffer *b=cmd->index<r->nr_bos?job->bos[cmd->index].buffer:NULL;
        if(!b||cmd->relocs||cmd->pad||!cmd->size||(cmd->offset&3u)||(cmd->size&3u)||
            (uint64_t)cmd->offset+cmd->size>b->size){result=kIOReturnBadArgument;goto unlock;}
        if(nr_ranges) {
            bool found=false;
            for(unsigned n=0;n<nr_ranges;++n) {
                const rf_gw_submit_range *range=&ranges[n];
                if(range->bo==cmd->index&&range->offset<=cmd->offset&&
                   (uint64_t)cmd->offset+cmd->size-range->offset<=range->bytes){found=true;break;}
            }
            if(!found){result=kIOReturnBadArgument;goto unlock;}
        }
        job->addresses[job->count]=b->address+cmd->offset;job->words[job->count++]=cmd->size/4;
    }
    if(!job->count){result=kIOReturnBadArgument;goto unlock;}
    /* Publish this caller CPU's WC writes before a different CPU executes
     * the retained IBs. The worker repeats the native cache maintenance. */
    redfin_gpu_sync(NULL,0,false);
    IOLockLock(gGPUQueue.lock);
    if(gGPUQueue.stopping||!redfin_gpu_ready()||gGPUQueue.issued==UINT64_MAX)result=kIOReturnNotReady;
    else result=gpuError(rf_gq_accept(&queue,&job->fence));
    if(result==kIOReturnSuccess) {
        job->owner=this;retain();job->nr_bos=r->nr_bos;job->charge=charge;job->accepted=gpuNow();
        job->sequence=++gGPUQueue.issued;proc_selfname(job->process,sizeof(job->process));job->pid=proc_selfpid();
        for(unsigned i=0;i<r->nr_bos;++i){
            gpu_buffer *b=job->bos[i].buffer;++b->pending;b->fence=job->fence;
            if(!nr_ranges&&rf_gw_mark(gGPUQueue.page_use,b->pages,b->page_count,job->sequence))
                redfin_gpu_poison("physical GPU dependency metadata changed");
        }
        for(unsigned i=0;i<nr_ranges;++i) {
            const rf_gw_submit_range *range=&ranges[i];gpu_buffer *b=job->bos[range->bo].buffer;
            if(rf_gw_mark_span(gGPUQueue.page_use,b->pages,b->page_count,range->offset,range->bytes,b->size,job->sequence))
                redfin_gpu_poison("scoped GPU dependency metadata changed");
        }
        if(gGPUQueue.tail)gGPUQueue.tail->next=job;else gGPUQueue.head=job;gGPUQueue.tail=job;
        r->fence=job->fence;job=NULL;IOLockWakeup(gGPUQueue.lock,&gGPUQueue.head,false);
    }
    IOLockUnlock(gGPUQueue.lock);
unlock:
    IOLockUnlock(clientLock);
done:
    if(bos)IODelete(bos,msm_bo,r->nr_bos);if(commands)IODelete(commands,msm_cmd,r->nr_cmds);
    if(ranges)IODelete(ranges,rf_gw_submit_range,nr_ranges);
    if(job){if(job->bos)IODelete(job->bos,gpu_queued_bo,r->nr_bos);IODelete(job,gpu_queued_job,1);}
    if(result!=kIOReturnSuccess)gpuQueueUnreserve(charge);return result;
}
static void gpuQueueFault(const gpu_queued_job *job)
{
    uint64_t address=0;uint32_t fsr=0;if(!redfin_gpu_fault_info(&address,&fsr))return;
    gpu_buffer *previous=NULL;uint64_t end=0;
    for(unsigned i=0;i<job->nr_bos;++i) {
        gpu_buffer *b=job->bos[i].buffer;
        if(address>=b->address&&address-b->address<b->size) {
            IOLog("REDFIN GPU FAULT BO: submitted-index=%u handle=%u VA=%#llx bytes=%llu offset=%#llx surface=%u client-mapped=%u flags=%#x FSR=%#x\n",
                i,job->bos[i].handle,b->address,b->size,address-b->address,b->surface!=NULL,
                __atomic_load_n(&b->clientMapped,__ATOMIC_ACQUIRE),b->flags,fsr);return;
        }
        uint64_t limit=b->address+b->size;if(limit<=address&&limit>end){previous=b;end=limit;}
    }
    IOLog("REDFIN GPU FAULT BO: address=%#llx outside-submitted-BOs=1 count=%u FSR=%#x\n",address,job->nr_bos,fsr);
    if(previous)IOLog("REDFIN GPU FAULT PRECEDING: VA=%#llx bytes=%llu end=%#llx gap=%llu surface=%u client-mapped=%u\n",
        previous->address,previous->size,end,address-end,previous->surface!=NULL,
        __atomic_load_n(&previous->clientMapped,__ATOMIC_ACQUIRE));
}
IOReturn RedwoodGPUUserClient::executeQueued(gpu_queued_job *job)
{
    uint64_t began=gpuNow(),again=4ULL*NSEC_PER_MSEC;
    for(unsigned i=0;i<job->nr_bos;++i) {
        gpu_buffer *b=job->bos[i].buffer;if(!b->surface)continue;
        uint32_t seed=__atomic_load_n((uint32_t *)((uint8_t *)b->surface->state->getBytesNoCopy()+12),__ATOMIC_ACQUIRE);
        if(rf_gr_surface_push(&b->cache,seed,began,again,__atomic_load_n(&b->clientMapped,__ATOMIC_ACQUIRE))) {
            redfin_gpu_sync(b->kernel,b->size,true);gTiming.cleaned+=b->size;
        } else ++gTiming.skipped;
    }
    redfin_gpu_sync(NULL,0,false);gTiming.cleaning+=gpuNow()-began;began=gpuNow();
    IOReturn result=gpuError(redfin_gpu_submit(job->addresses,job->words,job->count,&job->physical_fence));
    if(result!=kIOReturnSuccess)gpuQueueFault(job);
    gTiming.submitting+=gpuNow()-began;began=gpuNow();++gTiming.submissions;
    if(result==kIOReturnSuccess)for(unsigned i=0;i<job->nr_bos;++i) {
        gpu_buffer *b=job->bos[i].buffer;
        if(b->surface&&(job->bos[i].flags&2u)){redfin_gpu_invalidate(b->kernel,b->size);gTiming.invalidated+=b->size;}
    }
    gTiming.invalidating+=gpuNow()-began;gpuTiming();
    if(job->fence<=8||!(job->fence%256)||result!=kIOReturnSuccess)
        IOLog("REDFIN GPU QUEUED FINISH: name=%s pid=%d client-fence=%u physical-fence=%u IBs=%u actual-finish=%u result=%#x age-us=%llu\n",
            job->process,job->pid,job->fence,job->physical_fence,job->count,result==kIOReturnSuccess,result,(gpuNow()-job->accepted)/1000);
    return result;
}
void RedwoodGPUUserClient::retireQueued(gpu_queued_job *job,IOReturn result)
{
    IOLockLock(clientLock);
    for(unsigned i=0;i<job->nr_bos;++i) {
        gpu_buffer *b=job->bos[i].buffer;
        if(!b->pending)redfin_gpu_poison("queued BO ownership counter changed");else --b->pending;
        IOLockWakeup(clientLock,&b->pending,false);
    }
    int error=result==kIOReturnSuccess?0:result==kIOReturnTimeout?ETIMEDOUT:result==kIOReturnNotReady?ECANCELED:EIO;
    if(rf_gq_retire(&queue,job->fence,error)) {
        queue.failed=1;queue.first_error=EIO;if(queue.pending)--queue.pending;
        redfin_gpu_poison("client queued retirement order changed");
    }
    IOLockWakeup(clientLock,&queue.pending,false);IOLockWakeup(clientLock,&queue.completed,false);
    IOLockUnlock(clientLock);
}
IOReturn RedwoodGPUUserClient::waitQueued(msm_wait *r)
{
    uint64_t end=0;if(r->flags||rf_gq_deadline(r->timeout.seconds,r->timeout.nanoseconds,gpuNow(),&end))return kIOReturnBadArgument;
    IOLockLock(clientLock);IOReturn result=kIOReturnSuccess;
    if(r->queue>nextQueue){result=kIOReturnBadArgument;goto done;}
    for(;;) {
        int status=rf_gq_status(&queue,r->fence);
        if(status!=EAGAIN){result=gpuError(status);break;}
        if(gpuNow()>=end){result=kIOReturnTimeout;break;}
        int waited=IOLockSleepDeadline(clientLock,&queue.completed,gpuQueueAbsolute(end),THREAD_ABORTSAFE);
        if(waited==THREAD_TIMED_OUT){result=kIOReturnTimeout;break;}
        if(waited!=THREAD_AWAKENED){result=kIOReturnAborted;break;}
    }
done:IOLockUnlock(clientLock);return result;
}
IOReturn RedwoodGPUUserClient::prepareRange(rf_gw_cpu_range *r,bool whole)
{
    if(r->op&~7u)return kIOReturnBadArgument;
    IOLockLock(clientLock);gpu_buffer *b=buffer(r->handle);
    if(!b||closed||queue.closing){IOLockUnlock(clientLock);return kIOReturnBadArgument;}
    uint64_t generation=b->generation;
    msm_timespec timeout={r->seconds,r->nanoseconds};
    IOLockLock(gGPUQueue.lock);
    uint64_t target=0;
    IOReturn result=gpuError(rf_gw_target(gGPUQueue.page_use,b->pages,b->page_count,
        r->offset,whole?b->size:r->bytes,b->size,&target));
    IOLockUnlock(clientLock);
    if(result==kIOReturnSuccess)result=gpuQueueWaitTargetLocked(target,&timeout,(r->op&4u)!=0);
    IOLockUnlock(gGPUQueue.lock);
    IOLockLock(clientLock);b=buffer(r->handle);
    if(!b||b->generation!=generation)result=kIOReturnBadArgument;
    IOLockUnlock(clientLock);return result;
}
IOReturn RedwoodGPUUserClient::prepareQueued(msm_cpu_prep *r)
{
    rf_gw_cpu_range range={r->handle,r->op,0,0,r->timeout.seconds,r->timeout.nanoseconds};
    return prepareRange(&range,true);
}
extern "C" int redfin_gpu_queue_memory_barrier(void *descriptor)
{
    if(!gGPUQueue.lock)return (int)kIOReturnSuccess;
    IOLockLock(gGPUQueue.lock);
    uint64_t target=gpuQueueMemoryTargetLocked((IOMemoryDescriptor *)descriptor);
    IOReturn result=gpuQueueWaitTargetLocked(target,NULL,false);
    IOLockUnlock(gGPUQueue.lock);return (int)result;
}

extern "C" int redfin_gpu_queue_cpu_barrier(void)
{
    /* No GPU service is published in non-GUI/bootstrap profiles. */
    return gGPUQueue.lock?(int)redfinGpuQueueBarrier(NULL,false):(int)kIOReturnSuccess;
}
