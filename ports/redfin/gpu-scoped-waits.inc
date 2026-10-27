/* SPDX-License-Identifier: MIT */
/* Caller holds the queue lock. All dependencies remain actual global FIFO
 * sequences. Only the first cold output has a separate shared deadline;
 * repeated consumers and spurious wakes cannot restart that budget. */
static bool gpuQueueColdOutputPendingLocked(uint64_t target)
{
    return gGPUQueue.cold_output_sequence&&target>=gGPUQueue.cold_output_sequence&&
        gGPUQueue.retired<gGPUQueue.cold_output_sequence;
}
static uint64_t gpuQueueOrdinaryDeadline(uint64_t now)
{return now>UINT64_MAX-RF_GQ_WAIT_NS?UINT64_MAX:now+RF_GQ_WAIT_NS;}
static IOReturn gpuQueueWaitDeadlineLocked(uint64_t target,const msm_timespec *timeout,uint64_t *end)
{
    uint64_t now=gpuNow(),limit=gpuQueueOrdinaryDeadline(now);
    if(timeout&&rf_gq_deadline(timeout->seconds,timeout->nanoseconds,now,end))return kIOReturnBadArgument;
    if(gpuQueueColdOutputPendingLocked(target)) {
        limit=gGPUQueue.cold_output_deadline;
    }
    if(timeout) {
        /* rf_gq_deadline already validated both fields. Preserve the caller's
         * actual absolute bound, including short/nonblocking requests. */
        uint64_t requested=(uint64_t)timeout->seconds>(UINT64_MAX-(uint64_t)timeout->nanoseconds)/UINT64_C(1000000000)?
            UINT64_MAX:(uint64_t)timeout->seconds*UINT64_C(1000000000)+(uint64_t)timeout->nanoseconds;
        *end=requested<limit?requested:limit;
    } else *end=limit;
    return kIOReturnSuccess;
}
static void gpuQueueAfterColdOutputLocked(uint64_t target,const msm_timespec *timeout,bool *cold,uint64_t *end)
{
    if(*cold&&!gpuQueueColdOutputPendingLocked(target)) {
        /* Exactly one transition to the target's ordinary work. The cold
         * phase is bounded by its frozen shared deadline, followed by at
         * most2s for the real target, still within any caller deadline. */
        *cold=false;(void)gpuQueueWaitDeadlineLocked(target,timeout,end);
    }
}
/* Never assume a signalled GPU-written ufence means FIFO/cache retirement. */
static IOReturn gpuQueueWaitTargetLocked(uint64_t target,const msm_timespec *timeout,bool nonblocking)
{
    uint64_t end=0;
    IOReturn deadline=gpuQueueWaitDeadlineLocked(target,timeout,&end);
    if(deadline!=kIOReturnSuccess)return deadline;
    bool cold=gpuQueueColdOutputPendingLocked(target);
    IOReturn result=kIOReturnSuccess;
    while(gGPUQueue.retired<target) {
        if(nonblocking){result=kIOReturnBusy;break;}
        gpuQueueAfterColdOutputLocked(target,timeout,&cold,&end);
        if(gpuNow()>=end){result=kIOReturnTimeout;break;}
        int waited=IOLockSleepDeadline(gGPUQueue.lock,&gGPUQueue.retired,gpuQueueAbsolute(end),THREAD_ABORTSAFE);
        if(waited==THREAD_TIMED_OUT){result=kIOReturnTimeout;break;}
        if(waited!=THREAD_AWAKENED){result=kIOReturnAborted;break;}
    }
    if(result==kIOReturnSuccess&&(gGPUQueue.first_failed||!redfin_gpu_ready()))result=kIOReturnIOError;
    return result;
}
/* A prepared descriptor remains pinned by its retained IOSurface. Its physical
 * segments are immutable; no allocation, mapping or GPU access occurs here.
 * Foreign/physical-panel descriptors retain the previous full barrier. */
static uint64_t gpuQueueMemoryTargetLocked(IOMemoryDescriptor *memory)
{
    if(!memory||!rf_ga_valid(&gGPUQueue.access))return gGPUQueue.issued;
    uint64_t size=memory->getLength(),target=0;
    if(!size||size>RF_GR_BUFFER_MAX)return gGPUQueue.issued;
    for(uint64_t offset=0;offset<size;offset+=RF_GW_PAGE_BYTES) {
        IOByteCount contiguous=0;
        uint64_t physical=memory->getPhysicalSegment(offset,&contiguous,kIOMemoryMapperNone);
        uint32_t page=0;
        if(!physical||contiguous<((size-offset)<RF_GW_PAGE_BYTES?size-offset:RF_GW_PAGE_BYTES)||
           rf_gw_index(physical,&page))return gGPUQueue.issued;
        if(gGPUQueue.access.use[page]>target)target=gGPUQueue.access.use[page];
    }
    return target;
}
