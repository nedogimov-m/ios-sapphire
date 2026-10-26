/* SPDX-License-Identifier: MIT */
#include "metal-scheduling.h"
static BOOL scheduling_counts(id device,uint64_t *counts)
{
    int (*read)(id,uint64_t *,size_t)=dlsym(RTLD_DEFAULT,"redfin_metal_scheduling_statistics");
    return read&&read(device,counts,REDFIN_METAL_SCHEDULING_WORDS)==0;
}
static BOOL scheduling_native(id<MTLDevice> device,uint64_t nonce)
{
    enum {page=4096,offset=64,length=512};
    uint64_t before[REDFIN_METAL_SCHEDULING_WORDS]={0},after[REDFIN_METAL_SCHEDULING_WORDS]={0};
    id<MTLCommandQueue> queues[2]={[device newCommandQueue],[device newCommandQueue]};
    id<MTLBuffer> parent=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    id<MTLBuffer> result=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    id<MTLBuffer> nestedResult=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    uint8_t *input=parent.contents,*output=result.contents,*nestedBytes=nestedResult.contents;
    BOOL valid=queues[0]&&queues[1]&&input&&output&&nestedBytes&&scheduling_counts(device,before);
    if(input)memset(input,0xa5,page);if(output)memset(output,0xa5,page);if(nestedBytes)memset(nestedBytes,0xa5,page);
    id<MTLCommandBuffer> first=[queues[0] commandBuffer],second=[queues[1] commandBuffer];
    dispatch_semaphore_t scheduled=dispatch_semaphore_create(0),completed=dispatch_semaphore_create(0);
    __block unsigned scheduledCalls=0,completedCalls=0;__block BOOL reentrant=NO;
    uint8_t value=(uint8_t)(nonce^0x63);
    if(valid&&first&&second) {
        id<MTLBlitCommandEncoder> fill=[first blitCommandEncoder],copy=[second blitCommandEncoder];
        valid=fill&&copy;
        [fill fillBuffer:parent range:NSMakeRange(offset,length) value:value];[fill endEncoding];
        [copy copyFromBuffer:parent sourceOffset:0 toBuffer:result destinationOffset:0 size:page];[copy endEncoding];
        id<MTLCommandQueue> callbackQueue=queues[0];
        [first addScheduledHandler:^(id<MTLCommandBuffer> command) {
            @autoreleasepool {
                [command waitUntilScheduled];
                id<MTLCommandBuffer> nested=[callbackQueue commandBuffer];
                id<MTLBlitCommandEncoder> encoder=[nested blitCommandEncoder];
                [encoder fillBuffer:nestedResult range:NSMakeRange(offset,length) value:0x39];[encoder endEncoding];
                [nested commit];[nested waitUntilCompleted];
                __atomic_store_n(&reentrant,nested&&encoder&&nested.status==MTLCommandBufferStatusCompleted,__ATOMIC_RELAXED);
                __atomic_add_fetch(&scheduledCalls,1,__ATOMIC_RELAXED);dispatch_semaphore_signal(scheduled);
            }
        }];
        [first addScheduledHandler:^(id<MTLCommandBuffer> command) {
            [command waitUntilScheduled];__atomic_add_fetch(&scheduledCalls,1,__ATOMIC_RELAXED);dispatch_semaphore_signal(scheduled);
        }];
        [first addCompletedHandler:^(id<MTLCommandBuffer> command) {
            if(command.status==MTLCommandBufferStatusCompleted)__atomic_add_fetch(&completedCalls,1,__ATOMIC_RELAXED);
            dispatch_semaphore_signal(completed);
        }];
        [first commit];[first waitUntilScheduled];[second commit];[second waitUntilScheduled];
        [first waitUntilCompleted];[second waitUntilCompleted];
        valid=valid&&first.status==MTLCommandBufferStatusCompleted&&second.status==MTLCommandBufferStatusCompleted;
        /* Late registration must be delivered once as well. */
        [first addScheduledHandler:^(id<MTLCommandBuffer> command) {
            [command waitUntilScheduled];__atomic_add_fetch(&scheduledCalls,1,__ATOMIC_RELAXED);dispatch_semaphore_signal(scheduled);
        }];
        [first addCompletedHandler:^(id<MTLCommandBuffer> command) {
            if(command.status==MTLCommandBufferStatusCompleted)__atomic_add_fetch(&completedCalls,1,__ATOMIC_RELAXED);
            dispatch_semaphore_signal(completed);
        }];
        for(unsigned i=0;i<3;++i)valid=!dispatch_semaphore_wait(scheduled,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))&&valid;
        for(unsigned i=0;i<2;++i)valid=!dispatch_semaphore_wait(completed,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))&&valid;
        valid=valid&&__atomic_load_n(&reentrant,__ATOMIC_RELAXED)&&
            __atomic_load_n(&scheduledCalls,__ATOMIC_RELAXED)==3&&__atomic_load_n(&completedCalls,__ATOMIC_RELAXED)==2;
        for(unsigned i=0;valid&&i<page;++i) {
            BOOL inside=i>=offset&&i<offset+length;
            valid=input[i]==(inside?value:0xa5)&&output[i]==(inside?value:0xa5)&&nestedBytes[i]==(inside?0x39:0xa5);
        }
    } else valid=NO;
    BOOL counts=valid&&scheduling_counts(device,after)&&after[RF_MS_PUBLICATIONS]>=before[RF_MS_PUBLICATIONS]+3&&
        after[RF_MS_SCHEDULED_CALLS]>=before[RF_MS_SCHEDULED_CALLS]+5&&
        after[RF_MS_COMPLETED_CALLS]>=before[RF_MS_COMPLETED_CALLS]+3&&
        after[RF_MS_SCHEDULED_HANDLERS]>=before[RF_MS_SCHEDULED_HANDLERS]+3&&
        after[RF_MS_COMPLETED_HANDLERS]>=before[RF_MS_COMPLETED_HANDLERS]+2;
    BOOL callbacksDone=__atomic_load_n(&scheduledCalls,__ATOMIC_RELAXED)==3&&__atomic_load_n(&completedCalls,__ATOMIC_RELAXED)==2;
    printf("REDFIN METAL SCHEDULING RESULT: boot=%016llx native-publication=%u scheduled-handler-submit-wait=%u late-handlers-once=%u cross-queue-pixels-guards=%u real-counters=%u early-returns=%llu passed=%u\n",
        (unsigned long long)nonce,counts,__atomic_load_n(&reentrant,__ATOMIC_RELAXED),callbacksDone,valid,counts,
        (unsigned long long)(counts?after[RF_MS_EARLY_RETURNS]-before[RF_MS_EARLY_RETURNS]:0),valid&&counts);
    [parent release];[result release];[nestedResult release];[queues[0] release];[queues[1] release];
    /* A missing callback must not signal a freed semaphore after a refusal. */
    if(callbacksDone){dispatch_release(scheduled);dispatch_release(completed);}
    return valid&&counts;
}
