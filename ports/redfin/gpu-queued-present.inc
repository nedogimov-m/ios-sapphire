/* SPDX-License-Identifier: MIT */
/* Internal presentation is a retained job on the same FIFO as rendering.
 * Its real completion ends the wait; future render jobs cannot reacquire
 * hardware ahead of an already-admitted presentation. No frame is discarded. */
struct gd_queued_present {
    IOLock *lock;
    uint32_t references;
    bool done;
    int result;
    uint64_t cold_deadline;
    SweetSurface *panel,*sources[RF_GD_LAYERS];
    redfin_display_geometry geometry;
    uint8_t record[0x120];
    uint32_t *pages,page_count,page_capacity;
};
static void gd_queued_release(gd_queued_present *p)
{
    if(__atomic_sub_fetch(&p->references,1,__ATOMIC_ACQ_REL))return;
    if(!__atomic_load_n(&gd.uncertain,__ATOMIC_ACQUIRE)) {
        for(unsigned i=0;i<RF_GD_LAYERS;++i)if(p->sources[i]) {
            OSAddAtomic64(-1,(volatile SInt64 *)((uint8_t *)p->sources[i]->state->getBytesNoCopy()+0x18));
            p->sources[i]->release();
        }
        if(p->panel)p->panel->release();
    }
    /* Unknown DMA retains the actual surfaces/in-use references until reset.
     * These CPU-only metadata allocations have never been DMA mapped. */
    if(p->pages)IODelete(p->pages,uint32_t,p->page_capacity);
    if(p->lock)IOLockFree(p->lock);
    IODelete(p,gd_queued_present,1);
}
static IOReturn gd_queued_execute(void *argument)
{
    gd_queued_present *p=(gd_queued_present *)argument;
    p->result=gd_present_locked(p->panel,&p->geometry,p->record);
    return p->result<0?kIOReturnIOError:kIOReturnSuccess;
}
static void gd_queued_complete(void *argument,IOReturn status)
{
    gd_queued_present *p=(gd_queued_present *)argument;
    if(status!=kIOReturnSuccess)__atomic_store_n(&gd.uncertain,true,__ATOMIC_RELEASE);
    IOLockLock(p->lock);
    if(status!=kIOReturnSuccess)p->result=-1;
    p->done=true;IOLockWakeup(p->lock,&p->done,false);IOLockUnlock(p->lock);
    gd_queued_release(p);
}
static IOReturn gpuQueueSubmitKernel(gpu_queued_job *job,uint64_t *cold_deadline)
{
    if(!job||!cold_deadline||job->owner||!job->kernel_execute||!job->kernel_complete||
       (job->scope_count&&!job->scope_pages))return kIOReturnBadArgument;
    for(unsigned i=0;i<job->scope_count;++i)
        if(job->scope_pages[i]>=RF_GW_PAGES)return kIOReturnBadArgument;
    IOReturn result=gpuQueueReserve(job->charge);if(result!=kIOReturnSuccess)return result;
    IOLockLock(gGPUQueue.lock);
    if(gGPUQueue.stopping||!redfin_gpu_ready()||gGPUQueue.issued==UINT64_MAX)result=kIOReturnNotReady;
    else {
        job->sequence=++gGPUQueue.issued;job->accepted=gpuNow();
        if(!gGPUQueue.cold_output_sequence&&!__atomic_load_n(&gd.startup_ready,__ATOMIC_ACQUIRE)) {
            gGPUQueue.cold_output_sequence=job->sequence;
            gGPUQueue.cold_output_deadline=job->accepted>UINT64_MAX-RF_GQ_COLD_OUTPUT_NS?
                UINT64_MAX:job->accepted+RF_GQ_COLD_OUTPUT_NS;
            IOLog("REDFIN GPU COLD OUTPUT: sequence=%llu maximum-ms=%llu shared-deadline=1 ordinary-ms=%llu\n",
                job->sequence,RF_GQ_COLD_OUTPUT_NS/1000000,RF_GQ_WAIT_NS/1000000);
        }
        *cold_deadline=!__atomic_load_n(&gd.startup_ready,__ATOMIC_ACQUIRE)?gGPUQueue.cold_output_deadline:0;
        if(job->scope_count&&rf_ga_mark_pages(&gGPUQueue.access,job->scope_pages,job->scope_count,job->sequence,RF_GA_READ))
            redfin_gpu_poison("internal presentation dependency metadata changed");
        if(gGPUQueue.tail)gGPUQueue.tail->next=job;else gGPUQueue.head=job;gGPUQueue.tail=job;
        IOLockWakeup(gGPUQueue.lock,&gGPUQueue.head,false);
    }
    IOLockUnlock(gGPUQueue.lock);
    if(result!=kIOReturnSuccess)gpuQueueUnreserve(job->charge);
    return result;
}
static int gd_before_cpu_fallback(void)
{
    if(redfinGpuQueueBarrier(NULL,false)==kIOReturnSuccess)return 0;
    __atomic_store_n(&gd.uncertain,true,__ATOMIC_RELEASE);return -1;
}
static int gd_queued_wait(gd_queued_present *p)
{
    /* The first owned output performs full private native pixel/guard checks
     * before mapping the panel. V97 measured2.65s for that one-time work;
     * it must not inherit the ordinary two-second frame deadline. An acquire
     * pairs with complete successful initialization, not merely "attempted".
     * Both paths stay finite; spurious wakes never extend either deadline. */
    bool startup=p->cold_deadline!=0;
    uint64_t began=gpuNow(),end=startup?p->cold_deadline:gpuQueueOrdinaryDeadline(began);
    uint64_t budget=end>began?end-began:0,deadline=gpuQueueAbsolute(end);
    IOLockLock(p->lock);
    while(!p->done) {
        int waited=IOLockSleepDeadline(p->lock,&p->done,deadline,THREAD_ABORTSAFE);
        if(waited!=THREAD_AWAKENED&&!p->done)break;
    }
    bool completed=p->done;int result=completed?p->result:-1;
    if(!completed)__atomic_store_n(&gd.uncertain,true,__ATOMIC_RELEASE);
    IOLockUnlock(p->lock);
    if(startup||!completed)
        IOLog("REDFIN GPU DISPLAY WAIT: startup=%u budget-ms=%llu elapsed-us=%llu completed=%u result=%d ordinary-ms=%llu uncertain=%u\n",
            startup,budget/1000000,(gpuNow()-began)/1000,completed,result,
            RF_GQ_WAIT_NS/1000000,!completed);
    gd_queued_release(p);return result;
}
int RedfinGPUPresent(SweetSurface *panel,const redfin_display_geometry *geometry,const uint8_t *record)
{
    if(!RedfinGPUDisplayWritable())return -1;
    if(!gLock||!redfin_gpu_ready()||!gd_selected()||!record||
       !redfin_display_geometry_valid(geometry))return 0;
    gd_queued_present *p=IONewZero(gd_queued_present,1);
    gpu_queued_job *job=IONewZero(gpu_queued_job,1);
    if(!p||!job) {
        if(p)IODelete(p,gd_queued_present,1);if(job)IODelete(job,gpu_queued_job,1);
        return gd_before_cpu_fallback();
    }
    p->references=2;p->result=-1;p->geometry=*geometry;memcpy(p->record,record,sizeof(p->record));
    p->lock=IOLockAlloc();p->panel=panel;if(panel)panel->retain();
    bool valid=p->lock!=NULL;
    uint32_t mask=gd_u32(record+0x104);
    uint64_t capacity=0;
    for(unsigned i=0;i<RF_GD_LAYERS;++i) {
        uint32_t id=gd_u32(record+0x54+4*i);
        if(!(mask&(1u<<i))||!id)continue;
        SweetSurface *source=sweet_surface_copy(id);
        if(!source)continue; /* The existing CPU fallback will skip it too. */
        if(!source->state||!source->memory||source->memory->getLength()>RF_GR_BUFFER_MAX) {
            source->release();valid=false;break;
        }
        p->sources[i]=source;
        OSAddAtomic64(1,(volatile SInt64 *)((uint8_t *)source->state->getBytesNoCopy()+0x18));
        capacity+=(source->memory->getLength()+RF_GW_PAGE_BYTES-1)/RF_GW_PAGE_BYTES;
    }
    if(capacity>UINT32_MAX)valid=false;
    p->page_capacity=(uint32_t)capacity;
    if(valid&&capacity) {
        p->pages=IONew(uint32_t,p->page_capacity);if(!p->pages)valid=false;
    }
    if(valid)for(unsigned i=0;i<RF_GD_LAYERS;++i)if(p->sources[i]) {
        IOMemoryDescriptor *memory=p->sources[i]->memory;
        uint64_t size=memory->getLength();
        for(uint64_t offset=0;offset<size;offset+=RF_GW_PAGE_BYTES) {
            IOByteCount length=0;uint64_t physical=memory->getPhysicalSegment(offset,&length,kIOMemoryMapperNone);
            uint32_t page=0;
            /* The physical panel/unsupported sources keep FIFO ordering but
             * cannot be imported by a userspace GPU client. Their CPU access
             * retains the ordinary full-queue fallback. */
            if(physical&&length>=((size-offset)<RF_GW_PAGE_BYTES?size-offset:RF_GW_PAGE_BYTES)&&
               !rf_gw_index(physical,&page))p->pages[p->page_count++]=page;
        }
    }
    if(!valid) {
        gd_queued_release(p);gd_queued_release(p);IODelete(job,gpu_queued_job,1);
        return gd_before_cpu_fallback();
    }
    job->kernel_execute=gd_queued_execute;job->kernel_complete=gd_queued_complete;job->kernel_argument=p;
    job->scope_pages=p->pages;job->scope_count=p->page_count;
    job->charge=sizeof(*job)+sizeof(*p)+(uint64_t)p->page_capacity*sizeof(*p->pages);
    IOReturn admitted=gpuQueueSubmitKernel(job,&p->cold_deadline);
    if(admitted!=kIOReturnSuccess) {
        IODelete(job,gpu_queued_job,1);
        __atomic_store_n(&gd.uncertain,true,__ATOMIC_RELEASE);
        gd_queued_release(p);gd_queued_release(p);return -1;
    }
    return gd_queued_wait(p);
}
