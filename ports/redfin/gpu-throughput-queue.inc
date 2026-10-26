/* SPDX-License-Identifier: MIT
 * CPU admission is asynchronous; a single native owner executes retained jobs
 * using the already verified hardware submit/fence path. No early success is
 * reported by WaitFence/CpuPrep or display consumers. Lock order:
 * client -> queue (short admission), client -> hardware (map/release only).
 * The worker never acquires a client/queue lock while holding hardware.
 */
struct gpu_queued_bo {gpu_buffer *buffer;uint32_t handle,flags,access;};
struct gpu_queued_job {
    gpu_queued_job *next;
    RedwoodGPUUserClient *owner;
    IOReturn (*kernel_execute)(void *);
    void (*kernel_complete)(void *,IOReturn);
    void *kernel_argument;
    const uint32_t *scope_pages;uint32_t scope_count;
    gpu_queued_bo *bos;
    rf_gw_submit_range *ranges;uint32_t nr_ranges;bool typed;
    uint64_t addresses[RF_GR_COMMANDS],sequence,charge,accepted;
    uint32_t words[RF_GR_COMMANDS],count,nr_bos,fence,physical_fence;
    uint64_t dequeued,locked,ran,released,published,wait_began;
    IOReturn publication_status;
    char process[20];int pid;
};
static struct {
    IOLock *lock;
    gpu_queued_job *head,*tail;
    rf_gq_budget budget;
    rf_ga_history access;
    uint64_t cpu_calls,cpu_waits,cpu_read_calls,cpu_wait_ns;
    uint64_t surface_calls,surface_waits,surface_query_ns,surface_wait_ns;
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
static void gpuPhysicalRetire(gpu_queued_job *job,IOReturn result)
{
        /* Hardware is unlocked before any client waiter or object release. */
        if(job->owner)job->owner->retireQueued(job,result);
        uint64_t client_retired=gpuNow();
        IOLockLock(gGPUQueue.lock);
        if(job->sequence!=gGPUQueue.retired+1)redfin_gpu_poison("global queued retirement order changed");
        gGPUQueue.retired=job->sequence;++gGPUQueue.executed;
        if(result!=kIOReturnSuccess&&!gGPUQueue.first_failed)gGPUQueue.first_failed=job->sequence;
        IOLockWakeup(gGPUQueue.lock,&gGPUQueue.retired,false);
        if(!(job->sequence%256))IOLog("REDFIN GPU ACCESS: jobs=%llu CPU-calls=%llu CPU-waits=%llu CPU-read=%llu CPU-wait-us=%llu fine-pages=%u partial-marks=%llu fine-queries=%llu coarse-fallbacks=%llu line-bytes=%u surface-calls=%llu surface-waits=%llu surface-query-us=%llu surface-wait-us=%llu\n",
            job->sequence,gGPUQueue.cpu_calls,gGPUQueue.cpu_waits,gGPUQueue.cpu_read_calls,
            gGPUQueue.cpu_wait_ns/1000,gGPUQueue.access.allocated,gGPUQueue.access.partial_marks,
            gGPUQueue.access.fine_queries,gGPUQueue.access.fallbacks,RF_GA_LINE_BYTES,
            gGPUQueue.surface_calls,gGPUQueue.surface_waits,gGPUQueue.surface_query_ns/1000,gGPUQueue.surface_wait_ns/1000);
        IOLockUnlock(gGPUQueue.lock);
        if(job->sequence<=4||!(job->sequence&(job->sequence-1))||!(job->sequence%120)) {
            uint64_t queue_retired=gpuNow();
            /* The actual kernel logger retains at most255 bytes. Even all
             * uint64 maxima fit these separate records; sequence joins them.
             * us: admission, lock, execution, release, client retire, queue
             * retire, total. These are host scopes, not isolated GPU cycles. */
            IOLog("REDFIN GPU OWNER: s=%llu k=%c r=%x us=%llu,%llu,%llu,%llu,%llu,%llu,%llu host=1\n",
                job->sequence,job->owner?'R':'P',result,
                (job->dequeued-job->accepted)/1000,(job->locked-job->dequeued)/1000,
                (job->ran-job->locked)/1000,(job->released-job->ran)/1000,(client_retired-job->released)/1000,
                (queue_retired-client_retired)/1000,(queue_retired-job->accepted)/1000);
            IOLog("REDFIN GPU OWNER ID: s=%llu name=%s pid=%d cf=%u pf=%u\n",
                job->sequence,job->owner?job->process:"kernel",job->owner?job->pid:0,
                job->fence,job->physical_fence);
        }
        if(job->kernel_complete)job->kernel_complete(job->kernel_argument,result);
        RedwoodGPUUserClient *owner=job->owner;uint64_t charge=job->charge;
        if(job->ranges)IODelete(job->ranges,rf_gw_submit_range,job->nr_ranges);
        if(job->bos)IODelete(job->bos,gpu_queued_bo,job->nr_bos);IODelete(job,gpu_queued_job,1);
        gpuQueueUnreserve(charge);if(owner)owner->release();
}

#include "RedfinGPUPhysicalWorker.inc"
static bool redfinGpuQueueStart(void)
{
    gGPUQueue.lock=IOLockAlloc();if(!gGPUQueue.lock)return false;
    rf_ga_history *history=&gGPUQueue.access;
    history->use=IONewZero(uint64_t,RF_GW_PAGES);
    history->write=IONewZero(uint64_t,RF_GW_PAGES);
    history->fine_index=IONewZero(uint32_t,RF_GW_PAGES);
    history->fine=IONewZero(rf_ga_fine,RF_GA_FINE_PAGES);history->capacity=RF_GA_FINE_PAGES;
    if(!rf_ga_valid(history))return false;
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
IOReturn RedwoodGPUUserClient::submit(msm_submit *r,const rf_gw_submit_extension *scope,bool typed)
{
    if(!r->nr_cmds||r->nr_cmds>RF_GR_COMMANDS||!r->nr_bos||r->nr_bos>RF_GR_OBJECTS||
       (r->flags&~0x80000010u)||(r->flags&0xffu)!=0x10u||r->nr_in||r->nr_out||r->in_syncobjs||r->out_syncobjs||r->pad)
        return kIOReturnBadArgument;
    if((typed&&!scope)||(scope&&(!scope->ranges||!scope->count||scope->count>RF_GW_MAX_RANGES||scope->reserved)))return kIOReturnBadArgument;
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
        job->bos[i]={b,bos[i].handle,bos[i].flags,nr_ranges?0:rf_ga_access(bos[i].flags,0,false)};
    }
    for(unsigned i=0;i<nr_ranges;++i) {
        const rf_gw_submit_range *range=&ranges[i];
        gpu_buffer *b=range->bo<r->nr_bos?job->bos[range->bo].buffer:NULL;
        if(!b||(!typed&&range->reserved)||(typed&&((range->reserved&~RF_GA_RW)||
           (range->reserved&~(job->bos[range->bo].flags&RF_GA_RW))))||
           !range->bytes||range->offset>b->size||range->bytes>b->size-range->offset) {
            result=kIOReturnBadArgument;goto unlock;
        }
        covered[range->bo]=true;
        job->bos[range->bo].access|=rf_ga_access(job->bos[range->bo].flags,range->reserved,typed);
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
        job->nr_ranges=nr_ranges;job->typed=typed;
        job->sequence=++gGPUQueue.issued;proc_selfname(job->process,sizeof(job->process));job->pid=proc_selfpid();
        for(unsigned i=0;i<r->nr_bos;++i){
            gpu_buffer *b=job->bos[i].buffer;++b->pending;b->fence=job->fence;
            if(!nr_ranges&&rf_ga_mark_pages(&gGPUQueue.access,b->pages,b->page_count,job->sequence,job->bos[i].access))
                redfin_gpu_poison("physical GPU dependency metadata changed");
        }
        for(unsigned i=0;i<nr_ranges;++i) {
            const rf_gw_submit_range *range=&ranges[i];gpu_buffer *b=job->bos[range->bo].buffer;
            unsigned access=rf_ga_access(job->bos[range->bo].flags,range->reserved,typed);
            if(rf_ga_mark_span(&gGPUQueue.access,b->pages,b->page_count,range->offset,range->bytes,b->size,job->sequence,access))
                redfin_gpu_poison("scoped GPU dependency metadata changed");
        }
        if(gGPUQueue.tail)gGPUQueue.tail->next=job;else gGPUQueue.head=job;gGPUQueue.tail=job;
        r->fence=job->fence;job->ranges=ranges;ranges=NULL;job=NULL;IOLockWakeup(gGPUQueue.lock,&gGPUQueue.head,false);
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
/* Scope cache maintenance to the same validated physical cache-line spans
 * as CPU retirement. The original retained backing and SMMU map stay whole. */
static bool gpuQueuedSurfaceCache(gpu_queued_job *job,unsigned index,bool invalidate)
{
    gpu_buffer *b=job->bos[index].buffer;
    if(!job->nr_ranges) {
        if(invalidate){redfin_gpu_invalidate(b->kernel,b->size);gTiming.invalidated+=b->size;}
        else {redfin_gpu_sync(b->kernel,b->size,true);gTiming.cleaned+=b->size;}
        return true;
    }
    for(unsigned n=0;n<job->nr_ranges;++n) {
        const rf_gw_submit_range *range=&job->ranges[n];if(range->bo!=index)continue;
        unsigned access=rf_ga_access(job->bos[index].flags,range->reserved,job->typed);
        if(invalidate&&!(access&RF_GA_WRITE))continue;
        uint64_t first=range->offset&~UINT64_C(63);
        uint64_t end=(range->offset+range->bytes+63)&~UINT64_C(63);
        if(end>b->size||first>=end){redfin_gpu_poison("retained cache scope changed");return false;}
        void *address=(uint8_t *)b->kernel+first;uint64_t bytes=end-first;
        if(invalidate){redfin_gpu_invalidate(address,bytes);gTiming.invalidated+=bytes;}
        else {redfin_gpu_sync(address,bytes,true);gTiming.cleaned+=bytes;}
    }
    return true;
}
IOReturn RedwoodGPUUserClient::executeQueued(gpu_queued_job *job)
{
    uint64_t began=gpuNow(),again=4ULL*NSEC_PER_MSEC;
    for(unsigned i=0;i<job->nr_bos;++i) {
        gpu_buffer *b=job->bos[i].buffer;if(!b->surface)continue;
        /* All CPU aliases of these exact owned pages are already WC.
         * Keep the actual submitter/worker barriers and real GPU fences. */
        if(redfin_surface_write_combined(b->surface,b->memory,b->size)) {
            ++gTiming.wc_clean;gTiming.wc_clean_bytes+=b->size;continue;
        }
        uint32_t seed=__atomic_load_n((uint32_t *)((uint8_t *)b->surface->state->getBytesNoCopy()+12),__ATOMIC_ACQUIRE);
        if(rf_gr_surface_push(&b->cache,seed,began,again,__atomic_load_n(&b->clientMapped,__ATOMIC_ACQUIRE))) {
            int drained=redfin_gpu_quiesce();if(drained)return gpuError(drained);
            if(!gpuQueuedSurfaceCache(job,i,false))return kIOReturnIOError;
        } else ++gTiming.skipped;
    }
    redfin_gpu_sync(NULL,0,false);gTiming.cleaning+=gpuNow()-began;began=gpuNow();
    IOReturn result=gpuError(redfin_gpu_publish(job->addresses,job->words,job->count,&job->physical_fence));
    if(result!=kIOReturnSuccess)gpuQueueFault(job);
    gTiming.submitting+=gpuNow()-began;++gTiming.submissions;
    return result;
}
IOReturn RedwoodGPUUserClient::finishQueued(gpu_queued_job *job)
{
    uint64_t began=gpuNow();
    IOReturn result=gpuError(redfin_gpu_wait(job->physical_fence));
    if(result!=kIOReturnSuccess)gpuQueueFault(job);
    gTiming.submitting+=gpuNow()-began;began=gpuNow();
    /* A later writer may still be active. Cached imported CPU ownership
     * changes only at actual idle. Proven all-WC aliases need only their
     * real per-job cache-flush fence and the CPU observation barrier. */
    if(result==kIOReturnSuccess)for(unsigned i=0;i<job->nr_bos;++i)
        if(job->bos[i].buffer->surface&&(job->bos[i].access&RF_GA_WRITE)&&
           !redfin_surface_write_combined(job->bos[i].buffer->surface,
                job->bos[i].buffer->memory,job->bos[i].buffer->size)) {
            result=gpuError(redfin_gpu_quiesce());break;
        }
    if(result==kIOReturnSuccess)for(unsigned i=0;i<job->nr_bos;++i) {
        gpu_buffer *b=job->bos[i].buffer;
        if(!b->surface||!(job->bos[i].access&RF_GA_WRITE))continue;
        if(redfin_surface_write_combined(b->surface,b->memory,b->size)) {
            ++gTiming.wc_invalidate;gTiming.wc_invalidate_bytes+=b->size;
        } else if(!gpuQueuedSurfaceCache(job,i,true))result=kIOReturnIOError;
    }
    if(result==kIOReturnSuccess)redfin_surface_cache_barrier();
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
    if(!b||closed||queue.closing||queue.failed||!redfin_gpu_ready()){IOLockUnlock(clientLock);return kIOReturnBadArgument;}
    uint64_t generation=b->generation;
    msm_timespec timeout={r->seconds,r->nanoseconds};
    IOLockLock(gGPUQueue.lock);
    uint64_t target=0;
    IOReturn result=gpuError(rf_ga_target(&gGPUQueue.access,b->pages,b->page_count,
        r->offset,whole?b->size:r->bytes,b->size,r->op,&target));
    ++gGPUQueue.cpu_calls;if((r->op&RF_GA_RW)==RF_GA_READ)++gGPUQueue.cpu_read_calls;
    if(gGPUQueue.retired<target)++gGPUQueue.cpu_waits;
    uint64_t began=gpuNow();
    IOLockUnlock(clientLock);
    if(result==kIOReturnSuccess)result=gpuQueueWaitTargetLocked(target,&timeout,(r->op&4u)!=0);
    gGPUQueue.cpu_wait_ns+=gpuNow()-began;IOLockUnlock(gGPUQueue.lock);
    IOLockLock(clientLock);b=buffer(r->handle);
    if(!b||b->generation!=generation||queue.failed||!redfin_gpu_ready())result=kIOReturnBadArgument;
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
    uint64_t began=gpuNow();
    uint64_t target=gpuQueueMemoryTargetLocked((IOMemoryDescriptor *)descriptor);
    uint64_t resolved=gpuNow();++gGPUQueue.surface_calls;
    gGPUQueue.surface_query_ns+=resolved-began;if(gGPUQueue.retired<target)++gGPUQueue.surface_waits;
    IOReturn result=gpuQueueWaitTargetLocked(target,NULL,false);
    gGPUQueue.surface_wait_ns+=gpuNow()-resolved;
    IOLockUnlock(gGPUQueue.lock);return (int)result;
}

extern "C" int redfin_gpu_queue_cpu_barrier(void)
{
    /* No GPU service is published in non-GUI/bootstrap profiles. */
    return gGPUQueue.lock?(int)redfinGpuQueueBarrier(NULL,false):(int)kIOReturnSuccess;
}
