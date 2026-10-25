/* SPDX-License-Identifier: MIT */
/* Native offscreen probes: real attachment pixels, row pitches and guards.
 * No window, CALayer or physical display surface is created here. */
static IOSurfaceRef raster_surface(unsigned width,unsigned height,unsigned pitch,unsigned bytes)
{
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),
        (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(pitch),
        (id)kIOSurfaceAllocSize:@(bytes),(id)kIOSurfacePixelFormat:@0x42475241,@"IOSurfaceIsGlobal":@YES};
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    if(!surface)return NULL;
    uint32_t seed=0;
    if(IOSurfaceGetWidth(surface)!=width||IOSurfaceGetHeight(surface)!=height||
       IOSurfaceGetBytesPerRow(surface)!=pitch||IOSurfaceGetAllocSize(surface)!=bytes||
       IOSurfaceLock(surface,0,&seed)!=KERN_SUCCESS){CFRelease(surface);return NULL;}
    void *pixels=IOSurfaceGetBaseAddress(surface);if(pixels)memset(pixels,0xa5,bytes);
    BOOL valid=IOSurfaceUnlock(surface,0,&seed)==KERN_SUCCESS&&pixels;
    if(!valid){CFRelease(surface);return NULL;}return surface;
}
static id<MTLTexture> raster_texture(id device,IOSurfaceRef surface)
{
    if(!surface)return nil;
    MTLTextureDescriptor *desc=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
        width:IOSurfaceGetWidth(surface) height:IOSurfaceGetHeight(surface) mipmapped:NO];
    desc.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;desc.storageMode=MTLStorageModeShared;
    id texture=[device newTextureWithDescriptor:desc iosurface:surface plane:0];
    void *actual=texture?((void *(*)(id,SEL))objc_msgSend)(texture,sel_registerName("iosurface")):NULL;
    NSUInteger plane=texture?((NSUInteger (*)(id,SEL))objc_msgSend)(texture,sel_registerName("iosurfacePlane")):0;
    if(texture&&(actual!=surface||plane)) {
        printf("REDFIN METAL SURFACE: native object/plane getter mismatch\n");[texture release];return nil;
    }
    return texture;
}
static id<MTLRenderPipelineState> raster_pipeline(id<MTLDevice> device,id<MTLLibrary> library,
    NSString *fragment,unsigned count,BOOL fetch)
{
    MTLRenderPipelineDescriptor *shape=[MTLRenderPipelineDescriptor new];
    shape.vertexFunction=[library newFunctionWithName:@"redfin_vertex"];
    shape.fragmentFunction=[library newFunctionWithName:fragment];
    for(unsigned i=0;i<count;++i)shape.colorAttachments[i].pixelFormat=MTLPixelFormatBGRA8Unorm;
    if(fetch)shape.colorAttachments[1].writeMask=MTLColorWriteMaskNone;
    NSError *error=nil;
    id<MTLRenderPipelineState> pipeline=shape.vertexFunction&&shape.fragmentFunction?
        [device newRenderPipelineStateWithDescriptor:shape error:&error]:nil;
    if(!pipeline)printf("REDFIN METAL RASTER PIPELINE: name=%s error=%s\n",fragment.UTF8String,
        error?error.description.UTF8String:"missing function");
    [shape.vertexFunction release];[shape.fragmentFunction release];[shape release];return pipeline;
}
static BOOL raster_complete(id<MTLCommandBuffer> command,const char *stage)
{
    if(!command)return NO;
    [command commit];[command waitUntilCompleted];
    BOOL valid=command.status==MTLCommandBufferStatusCompleted&&!command.error;
    if(!valid)printf("REDFIN METAL RASTER COMMAND: stage=%s status=%lu error=%s\n",stage,
        (unsigned long)command.status,command.error?command.error.description.UTF8String:"none");
    return valid;
}
static BOOL raster_attachment_pixels(IOSurfaceRef surface,unsigned attachment,unsigned phase)
{
    uint32_t seed=0;
    if(IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)return NO;
    const uint32_t *pixels=IOSurfaceGetBaseAddress(surface);BOOL valid=pixels!=NULL;
    for(unsigned y=0;valid&&y<64;++y)for(unsigned x=0;valid&&x<64;++x) {
        BOOL inside=(x>=16&&x<32&&y>=20&&y<28)||(x>=40&&x<44&&y>=36&&y<40);
        uint32_t expected=phase==0?(attachment?0xff00ff00u:0xffff0000u):
            phase==2||attachment?(inside?0xffffff00u:0xff0000ffu):
            inside?0xffffffffu:0xffff0000u;
        if(pixels[y*64+x]!=expected) {
            printf("REDFIN METAL RASTER PIXEL: phase=%u attachment=%u x=%u y=%u actual=%08x expected=%08x\n",
                phase,attachment,x,y,pixels[y*64+x],expected);valid=NO;
        }
    }
    for(unsigned at=16384;valid&&at<32768;++at)if(((const uint8_t *)pixels)[at]!=0xa5) {
        printf("REDFIN METAL RASTER GUARD: phase=%u attachment=%u offset=%u\n",phase,attachment,at);valid=NO;
    }
    if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
    return valid;
}
static BOOL render_raster_passes(id<MTLDevice> device,id<MTLLibrary> library)
{
    IOSurfaceRef surfaces[2]={raster_surface(64,64,256,32768),raster_surface(64,64,256,32768)};
    id<MTLTexture> textures[2]={raster_texture(device,surfaces[0]),raster_texture(device,surfaces[1])};
    id<MTLRenderPipelineState> pipeline=raster_pipeline(device,library,@"redfin_mrt_fragment",2,NO);
    id<MTLRenderPipelineState> fetch=nil;
    id<MTLCommandQueue> queue=[device newCommandQueue];
    BOOL valid=textures[0]&&textures[1]&&pipeline&&queue;
    for(unsigned phase=0;valid&&phase<3;++phase) {
        id<MTLCommandBuffer> command=[queue commandBuffer];
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        for(unsigned i=0;i<2;++i) {
            pass.colorAttachments[i].texture=textures[i];pass.colorAttachments[i].storeAction=MTLStoreActionStore;
            pass.colorAttachments[i].loadAction=phase==0||(phase==1&&i)?MTLLoadActionClear:MTLLoadActionLoad;
            pass.colorAttachments[i].clearColor=i?(phase?MTLClearColorMake(0,0,1,1):MTLClearColorMake(0,1,0,1)):
                MTLClearColorMake(1,0,0,1);
        }
        id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];valid=encoder!=nil;
        if(valid) {
            if(phase==1) {
                [encoder setRenderPipelineState:pipeline];
                [encoder setViewport:(MTLViewport){8,12,40,32,0,1}];
                [encoder setScissorRect:(MTLScissorRect){16,20,16,8}];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                [encoder setViewport:(MTLViewport){36,28,16,16,0,1}];
                [encoder setScissorRect:(MTLScissorRect){40,36,4,4}];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            } else if(phase==2) {
                fetch=raster_pipeline(device,library,@"redfin_fetch_other_fragment",2,YES);
                valid=fetch!=nil;
                if(valid) {
                    [encoder setRenderPipelineState:fetch];
                    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                }
            }
            /* Phase zero deliberately has no pipeline and no draws. */
            [encoder endEncoding];if(valid)valid=raster_complete(command,phase==0?"clear-only":phase==1?"mrt-scissor-viewport":"fetch-attachment1");
        }
        for(unsigned i=0;valid&&i<2;++i)valid=raster_attachment_pixels(surfaces[i],i,phase);
        printf("REDFIN METAL RASTER PHASE: phase=%u actual-pixels-and-guards=%u\n",phase,valid);
    }
    [queue release];[pipeline release];[fetch release];
    for(unsigned i=0;i<2;++i){[textures[i] release];if(surfaces[i])CFRelease(surfaces[i]);}return valid;
}
static uint32_t raster_pattern(unsigned x,unsigned y,uint32_t nonce)
{
    return 0xff000000u|(((x*13+y*5+nonce)&255u)<<16)|
        (((x*3+y*19+(nonce>>8))&255u)<<8)|((x*17+y*7+(nonce>>16))&255u);
}
static BOOL render_byte_pitch(id<MTLDevice> device,id<MTLLibrary> library,uint32_t nonce,
    unsigned width,unsigned height,unsigned source_pitch,unsigned destination_pitch,unsigned source_bytes,unsigned destination_bytes)
{
    IOSurfaceRef source=raster_surface(width,height,source_pitch,source_bytes);
    IOSurfaceRef destination=raster_surface(width,height,destination_pitch,destination_bytes);
    id<MTLTexture> input=raster_texture(device,source),output=raster_texture(device,destination);
    BOOL alias_test=(destination_pitch%64)!=0;
    unsigned alias_pitch=(width*4+63)&~63u;
    IOSurfaceRef alias_readback=alias_test?raster_surface(width,height,alias_pitch,destination_bytes):NULL;
    id<MTLTexture> alias=alias_test?raster_texture(device,destination):nil;
    id<MTLTexture> alias_output=alias_test?raster_texture(device,alias_readback):nil;
    id<MTLRenderPipelineState> pipeline=raster_pipeline(device,library,@"redfin_position_sample_fragment",1,NO);
    id<MTLCommandQueue> queue=[device newCommandQueue];BOOL valid=source&&destination&&input&&output&&pipeline&&queue&&
        (!alias_test||(alias&&alias_output));
    for(unsigned round=0;valid&&round<2;++round) {
        uint32_t seed=0;uint32_t value=nonce+round*0x9e3779b9u;
        valid=IOSurfaceLock(source,0,&seed)==KERN_SUCCESS;
        if(valid) {
            uint8_t *pixels=IOSurfaceGetBaseAddress(source);valid=pixels!=NULL;
            for(unsigned y=0;valid&&y<height;++y)for(unsigned x=0;x<width;++x)
                ((uint32_t *)(pixels+y*source_pitch))[x]=raster_pattern(x,y,value);
            if(IOSurfaceUnlock(source,0,&seed)!=KERN_SUCCESS)valid=NO;
        }
        if(valid) {
            id<MTLCommandBuffer> command=[queue commandBuffer];
            MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture=output;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
            pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
            id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];valid=encoder!=nil;
            if(valid) {
                [encoder setRenderPipelineState:pipeline];[encoder setFragmentTexture:input atIndex:0];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                [encoder endEncoding];
                if(alias_test) {
                    MTLRenderPassDescriptor *next=[MTLRenderPassDescriptor renderPassDescriptor];
                    next.colorAttachments[0].texture=alias_output;next.colorAttachments[0].loadAction=MTLLoadActionClear;
                    next.colorAttachments[0].storeAction=MTLStoreActionStore;
                    id<MTLRenderCommandEncoder> reader=[command renderCommandEncoderWithDescriptor:next];valid=reader!=nil;
                    if(valid) {
                        [reader setRenderPipelineState:pipeline];[reader setFragmentTexture:alias atIndex:0];
                        [reader drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[reader endEncoding];
                    }
                }
                if(valid)valid=raster_complete(command,"byte-pitch-sample-and-alias");
            }
        }
        IOSurfaceRef surfaces[3]={source,destination,alias_readback};
        const unsigned pitches[3]={source_pitch,destination_pitch,alias_pitch},allocations[3]={source_bytes,destination_bytes,destination_bytes};
        for(unsigned i=0;valid&&i<(alias_test?3u:2u);++i) {
            valid=IOSurfaceLock(surfaces[i],kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
            if(valid) {
                const uint8_t *pixels=IOSurfaceGetBaseAddress(surfaces[i]);valid=pixels!=NULL;
                for(unsigned y=0;valid&&y<height;++y)for(unsigned x=0;valid&&x<width;++x) {
                    uint32_t actual=((const uint32_t *)(pixels+y*pitches[i]))[x],expected=raster_pattern(x,y,value);
                    if(actual!=expected) {
                        printf("REDFIN METAL PITCH PIXEL: pitch=%u round=%u surface=%u x=%u y=%u actual=%08x expected=%08x\n",
                            source_pitch,round,i,x,y,actual,expected);valid=NO;
                    }
                }
                /* Source padding must also stay unchanged. Destination row padding
                 * is an implementation detail, but its allocation tail is guarded. */
                if(!i)for(unsigned y=0;valid&&y<height;++y)for(unsigned at=width*4;valid&&at<pitches[i];++at)
                    if(pixels[y*pitches[i]+at]!=0xa5) {
                        printf("REDFIN METAL PITCH PADDING: source-pitch=%u surface=%u round=%u offset=%u actual=%02x\n",
                            source_pitch,i,round,y*pitches[i]+at,pixels[y*pitches[i]+at]);valid=NO;
                    }
                for(unsigned at=pitches[i]*height;valid&&at<allocations[i];++at)if(pixels[at]!=0xa5) {
                    printf("REDFIN METAL PITCH GUARD: source-pitch=%u destination-pitch=%u surface=%u round=%u offset=%u actual=%02x\n",
                        source_pitch,destination_pitch,i,round,at,pixels[at]);valid=NO;
                }
                if(IOSurfaceUnlock(surfaces[i],kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
            }
        }
        printf("REDFIN METAL BYTE PITCH: width=%u height=%u source-pitch=%u destination-pitch=%u round=%u same-import=1 alias-after-write=%u actual-pixels-source-and-guards=%u\n",
            width,height,source_pitch,destination_pitch,round,alias_test,valid);
    }
    [queue release];[pipeline release];[input release];[output release];
    [alias release];[alias_output release];if(alias_readback)CFRelease(alias_readback);
    if(source)CFRelease(source);if(destination)CFRelease(destination);return valid;
}
