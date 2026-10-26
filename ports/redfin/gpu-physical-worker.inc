/* SPDX-License-Identifier: MIT
 * One FIFO owner, at most two physical render publications. Native output
 * remains serialized. Client/CPU consumers wake only after the real fence,
 * cache handoff and original FIFO retirement, with hardware already unlocked.
 */
static gpu_queued_job *gpuPhysicalPopLocked(void)
{
    gpu_queued_job *job=gGPUQueue.head;
    if(job){gGPUQueue.head=job->next;if(!gGPUQueue.head)gGPUQueue.tail=NULL;job->next=NULL;}
    return job;
}
static void redfinGpuQueueWorker(void *,wait_result_t)
{
    gpu_queued_job *first=NULL,*last=NULL;unsigned count=0;bool failed_publication=false;
    for(;;) {
        IOLockLock(gGPUQueue.lock);
        bool stopped=gGPUQueue.stopping||!redfin_gpu_ready();
        gpu_queued_job *head=gGPUQueue.head,*job=NULL;
        bool kernel_next=head&&!head->owner;
        if(head&&(!count||(!stopped&&!failed_publication&&head->owner&&count<REDFIN_GPU_PUBLISH_DEPTH)))
            job=gpuPhysicalPopLocked();
        IOLockUnlock(gGPUQueue.lock);
        if(job) {
            job->dequeued=gpuNow();
            if(!job->owner||stopped) {
                /* Kernel output owns one mutable command/stage set. It can
                 * execute only after every earlier retained render retired. */
                IOReturn result=kIOReturnNotReady;
                {
                    GPUTransaction hardware;job->locked=gpuNow();
                    if(!stopped&&redfin_gpu_ready())result=job->kernel_execute(job->kernel_argument);
                    job->ran=gpuNow();
                }
                job->released=gpuNow();gpuPhysicalRetire(job,result);continue;
            }
            {
                GPUTransaction hardware;job->locked=gpuNow();
                job->publication_status=redfin_gpu_ready()?job->owner->executeQueued(job):kIOReturnNotReady;
            }
            job->published=gpuNow();
            if(last)last->next=job;else first=job;last=job;++count;
            failed_publication|=job->publication_status!=kIOReturnSuccess;
            continue;
        }
        if(first) {
            int observation=0;
            if(first->publication_status==kIOReturnSuccess&&redfin_gpu_ready()) {
                GPUTransaction hardware;observation=redfin_gpu_poll(first->physical_fence);
            }
            /* While one render is on the GPU, give newly admitted work a
             * chance to fill the second slot. This is a bounded1ms condition
             * sleep, never a client completion or a hardware-busy success. */
            if(observation==EAGAIN&&count<REDFIN_GPU_PUBLISH_DEPTH&&!kernel_next&&
               !stopped&&!failed_publication) {
                IOLockLock(gGPUQueue.lock);
                if(!gGPUQueue.head&&!gGPUQueue.stopping&&redfin_gpu_ready()) {
                    uint64_t wake=0;clock_interval_to_deadline(1,NSEC_PER_MSEC,&wake);
                    (void)IOLockSleepDeadline(gGPUQueue.lock,&gGPUQueue.head,wake,THREAD_UNINT);
                }
                IOLockUnlock(gGPUQueue.lock);continue;
            }
            job=first;first=job->next;if(!first)last=NULL;--count;
            IOReturn result=job->publication_status;job->wait_began=gpuNow();
            {
                GPUTransaction hardware;
                if(result==kIOReturnSuccess)
                    result=redfin_gpu_ready()?job->owner->finishQueued(job):kIOReturnNotReady;
                job->ran=gpuNow();
            }
            job->released=gpuNow();
            if(!count)failed_publication=false;
            if(job->sequence<=4||!(job->sequence&(job->sequence-1))||!(job->sequence%120))
                IOLog("REDFIN GPU PIPE: s=%llu pf=%u pub=%x pub-us=%llu before-wait-us=%llu wait-us=%llu FIFO=1 depth=2\n",
                    job->sequence,job->physical_fence,job->publication_status,
                    (job->published-job->locked)/1000,(job->wait_began-job->published)/1000,
                    (job->ran-job->wait_began)/1000);
            gpuPhysicalRetire(job,result);continue;
        }
        IOLockLock(gGPUQueue.lock);
        if(!gGPUQueue.head&&(gGPUQueue.stopping||!redfin_gpu_ready())) {
            IOLockUnlock(gGPUQueue.lock);break;
        }
        if(!gGPUQueue.head) {
            uint64_t wake=0;clock_interval_to_deadline(100,NSEC_PER_MSEC,&wake);
            (void)IOLockSleepDeadline(gGPUQueue.lock,&gGPUQueue.head,wake,THREAD_UNINT);
        }
        bool idle=!gGPUQueue.head&&!gGPUQueue.stopping;
        IOLockUnlock(gGPUQueue.lock);
        if(idle&&redfin_gpu_ready()){GPUTransaction hardware;(void)redfin_gpu_dvfs_idle();}
    }
    IOLockLock(gGPUQueue.lock);gGPUQueue.stopping=true;
    IOLockWakeup(gGPUQueue.lock,&gGPUQueue.budget,false);IOLockWakeup(gGPUQueue.lock,&gGPUQueue.retired,false);
    IOLockUnlock(gGPUQueue.lock);thread_terminate(current_thread());
}
