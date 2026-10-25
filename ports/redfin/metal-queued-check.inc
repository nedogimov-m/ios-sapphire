/* SPDX-License-Identifier: MIT */
/* Two native commands are committed before any wait. Shared writers, distinct
 * snapshots, real completion callbacks and a reentrant submit all check bytes. */
static BOOL queued_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {page=4096,offset=64,length=512};
    id<MTLCommandQueue> queues[2]={[device newCommandQueue],[device newCommandQueue]};
    id<MTLBuffer> parent=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    id<MTLBuffer> snapshots[3]={nil};uint8_t *maps[3]={NULL};
    id<MTLBuffer> callbackBuffer=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    uint8_t *original=parent.contents,*callbackBytes=callbackBuffer.contents;
    BOOL valid=queues[0]&&queues[1]&&parent&&original&&callbackBuffer&&callbackBytes;
    if(original)memset(original,0xa5,page);if(callbackBytes)memset(callbackBytes,0xa5,page);
    for(unsigned i=0;i<3;++i) {
        snapshots[i]=[device newBufferWithLength:page options:MTLResourceStorageModeShared];maps[i]=snapshots[i].contents;
        valid=valid&&snapshots[i]&&maps[i];if(maps[i])memset(maps[i],0xa5,page);
    }
    uint8_t first=(uint8_t)(nonce|1),second=(uint8_t)((nonce>>8)^0x6b);if(first==second)second^=0x80;
    dispatch_semaphore_t callback=dispatch_semaphore_create(0);__block BOOL callbackOK=NO;
    id<MTLCommandBuffer> commands[2]={[queues[0] commandBuffer],[queues[1] commandBuffer]};
    valid=valid&&commands[0]&&commands[1];
    uint8_t *firstSnapshot=maps[0];id<MTLBuffer> keptSnapshot=snapshots[0];
    id<MTLCommandQueue> callbackQueue=queues[0];
    if(valid) {
        id<MTLBlitCommandEncoder> a=[commands[0] blitCommandEncoder];valid=a!=nil;
        [a fillBuffer:parent range:NSMakeRange(offset,length) value:first];
        [a copyFromBuffer:parent sourceOffset:0 toBuffer:snapshots[0] destinationOffset:0 size:page];[a endEncoding];
        id<MTLBlitCommandEncoder> b=[commands[1] blitCommandEncoder];valid=valid&&b;
        [b copyFromBuffer:parent sourceOffset:0 toBuffer:snapshots[1] destinationOffset:0 size:page];
        [b fillBuffer:parent range:NSMakeRange(offset,length) value:second];
        [b copyFromBuffer:parent sourceOffset:0 toBuffer:snapshots[2] destinationOffset:0 size:page];[b endEncoding];
        [commands[0] addCompletedHandler:^(id<MTLCommandBuffer> completed) {
            @autoreleasepool {
                BOOL good=completed.status==MTLCommandBufferStatusCompleted;
                (void)keptSnapshot;
                for(unsigned i=0;good&&i<page;++i)good=firstSnapshot[i]==(i>=offset&&i<offset+length?first:0xa5);
                id<MTLCommandBuffer> nested=[callbackQueue commandBuffer];id<MTLBlitCommandEncoder> fill=[nested blitCommandEncoder];
                [fill fillBuffer:callbackBuffer range:NSMakeRange(offset,length) value:0x39];[fill endEncoding];
                [nested commit];[nested waitUntilCompleted];
                callbackOK=good&&nested&&fill&&nested.status==MTLCommandBufferStatusCompleted;
                dispatch_semaphore_signal(callback);
            }
        }];
        [commands[0] commit];[commands[1] commit];
        [commands[1] waitUntilCompleted];[commands[0] waitUntilCompleted];
        valid=valid&&commands[0].status==MTLCommandBufferStatusCompleted&&commands[1].status==MTLCommandBufferStatusCompleted;
        valid=valid&&!dispatch_semaphore_wait(callback,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC))&&callbackOK;
        for(unsigned i=0;valid&&i<page;++i) {
            BOOL in=i>=offset&&i<offset+length;
            valid=maps[0][i]==(in?first:0xa5)&&maps[1][i]==(in?first:0xa5)&&maps[2][i]==(in?second:0xa5)&&
                original[i]==(in?second:0xa5)&&callbackBytes[i]==(in?0x39:0xa5);
        }
    }
    BOOL errorDrain=NO,emptyOrdering=NO;
    id<MTLRenderPipelineState> pipeline=ordering_pipeline(device,library,@"redfin_vertex",@"redfin_position_sample_fragment",nil);
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:8 height:4 mipmapped:NO];
    shape.usage=MTLTextureUsageRenderTarget;shape.storageMode=MTLStorageModeShared;
    id<MTLTexture> target=[device newTextureWithDescriptor:shape];
    if(valid&&pipeline&&target) {
        id<MTLCommandBuffer> partial=[queues[0] commandBuffer];id<MTLBlitCommandEncoder> fill=[partial blitCommandEncoder];
        [fill fillBuffer:parent range:NSMakeRange(offset,length) value:0x27];[fill endEncoding];
        id<MTLRenderCommandEncoder> bad=[partial renderCommandEncoderWithDescriptor:ordering_pass(target)];
        [bad setRenderPipelineState:pipeline];[bad drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[bad endEncoding];
        id<MTLCommandBuffer> empty=[queues[1] commandBuffer];
        [partial commit];[empty commit];[partial waitUntilScheduled];
        errorDrain=partial&&fill&&bad&&partial.status==MTLCommandBufferStatusError&&partial.error!=nil;
        [empty waitUntilCompleted];[partial waitUntilCompleted];
        emptyOrdering=empty&&empty.status==MTLCommandBufferStatusCompleted;
        for(unsigned i=0;errorDrain&&i<page;++i)errorDrain=original[i]==(i>=offset&&i<offset+length?0x27:0xa5);
    }
    printf("REDFIN METAL QUEUED RESULT: boot=%016llx two-commits-before-wait=%u shared-write-order=%u distinct-snapshots-guards=%u callback-submit-wait=%u partial-error-real-drain=%u empty-order=%u passed=%u\n",
        (unsigned long long)nonce,valid,valid,valid,callbackOK,errorDrain,emptyOrdering,valid&&errorDrain&&emptyOrdering);
    [target release];[pipeline release];for(unsigned i=0;i<3;++i)[snapshots[i] release];
    [callbackBuffer release];[parent release];[queues[0] release];[queues[1] release];dispatch_release(callback);
    return valid&&errorDrain&&emptyOrdering;
}
