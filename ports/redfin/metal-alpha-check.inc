/* SPDX-License-Identifier: MIT */
/* Actual CoreAnimation A8 dimensions/offset/pitch. The shader checks alpha
 * semantics as well as fresh shared CPU writes through the same native view. */
static BOOL buffer_alpha_case(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce,
    unsigned width,unsigned pitch,unsigned bytes)
{
    enum {height=358,offset=64,outWidth=32,outHeight=16,outPitch=128};
    void *allocation=NULL;NSUInteger page=(NSUInteger)getpagesize();
    if(!page||posix_memalign(&allocation,page,bytes))return NO;
    uint8_t *original=allocation;memset(original,0xa5,bytes);
    __block BOOL releaseRange=NO;__block unsigned releaseCount=0;
    dispatch_semaphore_t released=dispatch_semaphore_create(0);BOOL valid=YES,created=NO;
    @autoreleasepool {
        id<MTLBuffer> parent=[device newBufferWithBytesNoCopy:original length:bytes options:MTLResourceStorageModeShared
            deallocator:^(void *address,NSUInteger length){releaseRange=address==original&&length==bytes;++releaseCount;dispatch_semaphore_signal(released);}];
        created=parent!=nil;
        MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatA8Unorm
            width:width height:height mipmapped:NO];shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageShaderRead;
        id<MTLTexture> view=[parent newTextureWithDescriptor:shape offset:offset bytesPerRow:pitch];
        IOSurfaceRef surface=raster_surface(outWidth,outHeight,outPitch,16384);
        id<MTLTexture> output=raster_texture(device,surface);
        id<MTLRenderPipelineState> pipeline=raster_pipeline(device,library,@"redfin_alpha_sample_fragment",1,NO);
        id<MTLCommandQueue> queue=[device newCommandQueue];
        valid=parent&&view&&view.pixelFormat==MTLPixelFormatA8Unorm&&view.buffer==parent&&surface&&output&&pipeline&&queue;
        for(unsigned phase=0;valid&&phase<4;++phase)@autoreleasepool {
            for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)
                original[offset+y*pitch+x]=(uint8_t)((x*13+y*19+(uint32_t)nonce+phase*83)&255);
            MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture=output;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
            pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
            id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
            valid=command&&encoder;
            if(encoder) {
                [encoder setRenderPipelineState:pipeline];[encoder setFragmentTexture:view atIndex:0];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];
                valid=valid&&raster_complete(command,"actual-A8-buffer-view-alpha");
            }
            uint32_t seed=0;
            if(valid) {
                valid=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
                if(valid) {
                    const uint8_t *pixels=IOSurfaceGetBaseAddress(surface);valid=pixels!=NULL;
                    for(unsigned y=0;valid&&y<outHeight;++y)for(unsigned x=0;valid&&x<outWidth;++x) {
                        unsigned at=y*outPitch+x*4;uint8_t expected=original[offset+y*pitch+x];
                        if(pixels[at]||pixels[at+1]||abs((int)pixels[at+2]-(int)expected)>1||pixels[at+3]!=255) {
                            printf("REDFIN METAL A8 PIXEL: phase=%u x=%u y=%u BGRA=%02x/%02x/%02x/%02x expected-alpha=%02x\n",
                                phase,x,y,pixels[at],pixels[at+1],pixels[at+2],pixels[at+3],expected);valid=NO;
                        }
                    }
                    for(unsigned at=outPitch*outHeight;valid&&at<16384;++at)valid=pixels[at]==0xa5;
                    if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
                }
            }
        }
        for(unsigned y=0;valid&&y<height;++y)for(unsigned x=width;valid&&x<pitch;++x)
            valid=original[offset+y*pitch+x]==0xa5;
        for(unsigned i=0;valid&&i<offset;++i)valid=original[i]==0xa5;
        for(unsigned i=offset+height*pitch;valid&&i<bytes;++i)valid=original[i]==0xa5;
        [queue release];[pipeline release];[output release];[view release];[parent release];if(surface)CFRelease(surface);
    }
    BOOL done=!created||!dispatch_semaphore_wait(released,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC));
    valid=valid&&created&&done&&releaseRange&&releaseCount==1;
    if(done){free(allocation);dispatch_release(released);}
    printf("REDFIN METAL A8 RESULT: boot=%016llx width=%u height=358 offset=64 pitch=%u parent-bytes=%u alpha-sampling-four-CPU-seeds-and-row-guards=%u release-arrived=%u\n",
        (unsigned long long)nonce,width,pitch,bytes,valid,done);return valid;
}
static BOOL buffer_alpha_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    BOOL original=buffer_alpha_case(device,library,nonce,640,640,229376);
    BOOL actual=buffer_alpha_case(device,library,nonce^0x729f630bu,549,576,212992);
    return original&&actual;
}
