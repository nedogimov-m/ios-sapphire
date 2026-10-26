/* SPDX-License-Identifier: MIT */
/* Caller holds the queue lock. A target is a physical-page dependency,
 * never an assumption that a signalled GPU-written ufence means retirement. */
static IOReturn gpuQueueWaitTargetLocked(uint64_t target,const msm_timespec *timeout,bool nonblocking)
{
    uint64_t end=0,now=gpuNow();
    if(timeout) {if(rf_gq_deadline(timeout->seconds,timeout->nanoseconds,now,&end))return kIOReturnBadArgument;}
    else end=now>UINT64_MAX-RF_GQ_WAIT_NS?UINT64_MAX:now+RF_GQ_WAIT_NS;
    IOReturn result=kIOReturnSuccess;
    while(gGPUQueue.retired<target) {
        if(nonblocking){result=kIOReturnBusy;break;}
        if(gpuNow()>=end){result=kIOReturnTimeout;break;}
        int waited=IOLockSleepDeadline(gGPUQueue.lock,&gGPUQueue.retired,gpuQueueAbsolute(end),THREAD_ABORTSAFE);
        if(waited==THREAD_TIMED_OUT){result=kIOReturnTimeout;break;}
        if(waited!=THREAD_AWAKENED){result=kIOReturnAborted;break;}
    }
    if(result==kIOReturnSuccess&&gGPUQueue.first_failed&&gGPUQueue.first_failed<=target)result=kIOReturnIOError;
    return result;
}
/* A prepared descriptor remains pinned by its retained IOSurface. Its physical
 * segments are immutable; no allocation, mapping or GPU access occurs here.
 * Foreign/physical-panel descriptors retain the previous full barrier. */
static uint64_t gpuQueueMemoryTargetLocked(IOMemoryDescriptor *memory)
{
    if(!memory||!gGPUQueue.page_use)return gGPUQueue.issued;
    uint64_t size=memory->getLength(),target=0;
    if(!size||size>RF_GR_BUFFER_MAX)return gGPUQueue.issued;
    for(uint64_t offset=0;offset<size;offset+=RF_GW_PAGE_BYTES) {
        IOByteCount contiguous=0;
        uint64_t physical=memory->getPhysicalSegment(offset,&contiguous,kIOMemoryMapperNone);
        uint32_t page=0;
        if(!physical||contiguous<((size-offset)<RF_GW_PAGE_BYTES?size-offset:RF_GW_PAGE_BYTES)||
           rf_gw_index(physical,&page))return gGPUQueue.issued;
        if(gGPUQueue.page_use[page]>target)target=gGPUQueue.page_use[page];
    }
    return target;
}
