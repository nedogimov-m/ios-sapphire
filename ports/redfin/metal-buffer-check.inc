/* SPDX-License-Identifier: MIT */
#include <stdlib.h>
static BOOL buffer_short_tails(id<MTLDevice> device)
{
    const unsigned lengths[]={1,2,3,5,7,31,63,65};BOOL valid=YES;
    id<MTLCommandQueue> queue=[device newCommandQueue];valid=queue!=nil;
    for(unsigned trial=0;valid&&trial<sizeof(lengths)/sizeof(lengths[0]);++trial)@autoreleasepool {
        unsigned n=lengths[trial];uint8_t expected[65];for(unsigned i=0;i<n;++i)expected[i]=(uint8_t)(i*37+trial+11);
        id<MTLBuffer> source=[device newBufferWithBytes:expected length:n options:MTLResourceStorageModeShared];
        id<MTLBuffer> output=[device newBufferWithLength:n options:MTLResourceStorageModeShared];
        valid=source&&output&&source.length==n&&output.length==n&&output.contents;
        for(unsigned step=0;valid&&step<2;++step) {
            memset(output.contents,0xa5,n);
            id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];
            valid=command&&encoder;
            if(encoder) {
                if(step)[encoder copyFromBuffer:source sourceOffset:0 toBuffer:output destinationOffset:0 size:n];
                else [encoder fillBuffer:output range:NSMakeRange(0,n) value:0x6d];
                [encoder endEncoding];valid=valid&&blit_completed(command,"short-logical-dword-tail");
                for(unsigned i=0;valid&&i<n;++i)if(((const uint8_t *)output.contents)[i]!=(step?expected[i]:0x6d)) {
                    printf("REDFIN METAL BUFFER TAIL: length=%u step=%u byte=%u actual=%02x\n",n,step,i,((uint8_t *)output.contents)[i]);valid=NO;
                }
            }
        }
        [output release];[source release];
    }
    [queue release];return valid;
}
static BOOL buffer_external_pages(id<MTLDevice> device,id<MTLComputePipelineState> pipeline,uint32_t nonce)
{
    NSUInteger page=(NSUInteger)getpagesize();void *allocation=NULL;
    if(!page||page>65536||posix_memalign(&allocation,page,page*3))return NO;
    uint8_t *base=allocation,*original=base+page;memset(base,0x93,page*3);
    __block unsigned released=0;__block BOOL releaseRange=NO;
    dispatch_semaphore_t releaseEvent=dispatch_semaphore_create(0);
    BOOL valid=YES,created=NO;
    @autoreleasepool {
        id<MTLCommandQueue> queue=[device newCommandQueue];
        id<MTLBuffer> seed=[device newBufferWithLength:4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> output=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
        id<MTLBuffer> external=[device newBufferWithBytesNoCopy:original length:page options:MTLResourceStorageModeShared
            deallocator:^(void *bytes,NSUInteger length){releaseRange=bytes==original&&length==page;++released;dispatch_semaphore_signal(releaseEvent);}];
        created=external!=nil;
        valid=queue&&seed&&seed.contents&&output&&output.contents&&external&&external.contents==original&&external.length==page;
        if(valid) {
            *(uint32_t *)seed.contents=nonce;
            id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
            valid=command&&encoder;
            if(encoder) {
                [encoder setComputePipelineState:pipeline];[encoder setBuffer:external offset:0 atIndex:0];
                [encoder setBuffer:seed offset:0 atIndex:1];
                [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];[encoder endEncoding];
                valid=valid&&blit_completed(command,"GPU-writes-original-external-pages");
                for(unsigned i=0;valid&&i<64;++i)valid=((uint32_t *)original)[i]==(i^nonce)*1664525u+1013904223u;
                for(NSUInteger i=256;valid&&i<page;++i)valid=original[i]==0x93;
            }
        }
        if(valid) {
            *(uint32_t *)original=nonce^0xb1c079d3u;memset(output.contents,0xa5,page);
            id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
            valid=command&&encoder;
            if(encoder) {
                [encoder setComputePipelineState:pipeline];[encoder setBuffer:output offset:0 atIndex:0];
                [encoder setBuffer:external offset:0 atIndex:1];
                [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];[encoder endEncoding];
                valid=valid&&blit_completed(command,"GPU-reads-original-external-pages");
                for(unsigned i=0;valid&&i<64;++i)valid=((uint32_t *)output.contents)[i]==(i^(nonce^0xb1c079d3u))*1664525u+1013904223u;
                for(NSUInteger i=256;valid&&i<page;++i)valid=((uint8_t *)output.contents)[i]==0xa5;
            }
        }
        if(valid) {
            id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];
            valid=command&&encoder;
            if(encoder) {
                [encoder copyFromBuffer:seed sourceOffset:1 toBuffer:external destinationOffset:page-3 size:3];[encoder endEncoding];
                /* Drop the caller's last reference before commit: native command
                 * retention must keep its original pages and deallocator alive. */
                [external release];external=nil;valid=valid&&!released;
                valid=valid&&blit_completed(command,"external-lifetime-unaligned-copy")&&!memcmp(original+page-3,(uint8_t *)seed.contents+1,3);
            }
        }
        for(NSUInteger i=0;valid&&i<page;++i)valid=base[i]==0x93&&base[2*page+i]==0x93;
        [external release];[output release];[seed release];[queue release];
    }
    BOOL releasedNow=!created||!dispatch_semaphore_wait(releaseEvent,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC));
    valid=valid&&created&&releasedNow&&releaseRange&&released==1;
    if(releasedNow){free(allocation);dispatch_release(releaseEvent);}
    /* On a genuine completion/lifetime failure the diagnostic leaves its pages
     * and callback semaphore alive until process exit, never frees live DMA. */
    return valid;
}
static BOOL buffer_native(id<MTLDevice> device,id<MTLComputePipelineState> pipeline,uint64_t nonce)
{
    BOOL tails=buffer_short_tails(device),external=buffer_external_pages(device,pipeline,(uint32_t)nonce);
    printf("REDFIN METAL BUFFER RESULT: boot=%016llx short-logical-tails=%u original-external-pages-compute-guards-and-lifetime=%u CPU-transfer-fallback=0\n",
        (unsigned long long)nonce,tails,external);return tails&&external;
}
