/* SPDX-License-Identifier: MIT */
/* Real CPU writers, tile restores, partial draws, native GMEM counters and
 * every visible/tail byte. Padding itself is owned transfer storage. */
static uint32_t padding_cpu_pixel(unsigned x,unsigned y,unsigned phase)
{
    return 0xff000000u | (((x*3+y*11+phase*17)&255u)<<16) |
        (((x*7+y*5+phase*31)&255u)<<8) | ((x*5+y*3+phase*47)&255u);
}
static BOOL padding_restore_native(id<MTLDevice> device,id<MTLLibrary> library,
    uint64_t nonce,unsigned width,unsigned height,unsigned pitch)
{
    unsigned payload=height*pitch,extent=((height+3u)&~3u)*pitch;
    unsigned allocation=(extent+16383u)&~16383u;
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),
        (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(pitch),
        (id)kIOSurfaceAllocSize:@(payload),(id)kIOSurfacePixelFormat:@0x42475241,
        @"IOSurfaceIsGlobal":@YES};
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    MTLTextureDescriptor *desc=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
        MTLPixelFormatBGRA8Unorm width:width height:height mipmapped:NO];
    desc.storageMode=MTLStorageModeShared;
    desc.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    id<MTLTexture> texture=surface?[(id)device newTextureWithDescriptor:desc iosurface:surface plane:0]:nil;
    MTLRenderPipelineDescriptor *shape=[[MTLRenderPipelineDescriptor alloc] init];
    shape.vertexFunction=[library newFunctionWithName:@"redfin_vertex"];
    shape.fragmentFunction=[library newFunctionWithName:@"redfin_fragment"];
    shape.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    NSError *error=nil;
    id<MTLRenderPipelineState> pipeline=texture?[device newRenderPipelineStateWithDescriptor:shape error:&error]:nil;
    id<MTLCommandQueue> queue=pipeline?[device newCommandQueue]:nil;
    BOOL valid=surface&&IOSurfaceGetAllocSize(surface)==allocation&&texture&&pipeline&&queue&&!error;
    unsigned completed=0;uint64_t mismatch=0,guards=0;
    for(unsigned phase=0;valid&&phase<2;++phase) {
        uint32_t seed=0;
        BOOL locked=IOSurfaceLock(surface,0,&seed)==KERN_SUCCESS;
        valid=locked;
        if(locked) {
            uint8_t *pixels=IOSurfaceGetBaseAddress(surface);
            valid=pixels&&IOSurfaceGetBytesPerRow(surface)==pitch;
            if(valid) {
                memset(pixels,0xa5,allocation);
                for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)
                    ((uint32_t *)(pixels+(uint64_t)y*pitch))[x]=padding_cpu_pixel(x,y,phase);
            }
            if(IOSurfaceUnlock(surface,0,&seed)!=KERN_SUCCESS)valid=NO;
        }
        MTLScissorRect scissor=phase? (MTLScissorRect){0,0,13,9} :
            (MTLScissorRect){width-17,height-7,17,7};
        uint64_t before[2]={0},after[2]={0};
        valid=valid&&native_gmem_statistics(device,before);
        id<MTLCommandBuffer> command=valid?[queue commandBuffer]:nil;
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=texture;
        pass.colorAttachments[0].loadAction=MTLLoadActionLoad;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        id<MTLRenderCommandEncoder> encoder=command?[command renderCommandEncoderWithDescriptor:pass]:nil;
        valid=valid&&command&&encoder;
        if(encoder) {
            [encoder setRenderPipelineState:pipeline];[encoder setScissorRect:scissor];
            [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [encoder endEncoding];[command commit];[command waitUntilCompleted];
            valid=valid&&command.status==MTLCommandBufferStatusCompleted&&!command.error;
        }
        valid=valid&&native_gmem_statistics(device,after)&&after[0]>before[0]&&after[1]==before[1];
        locked=valid&&IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
        valid=valid&&locked;
        if(locked) {
            const uint8_t *pixels=IOSurfaceGetBaseAddress(surface);
            valid=pixels!=NULL;
            if(pixels) {
                for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x) {
                    uint32_t actual=((const uint32_t *)(pixels+(uint64_t)y*pitch))[x];
                    BOOL covered=x>=scissor.x&&x<scissor.x+scissor.width&&
                        y>=scissor.y&&y<scissor.y+scissor.height;
                    const uint8_t *p=(const uint8_t *)&actual;
                    BOOL match=covered? p[0]>=190&&p[0]<=192&&p[1]>=127&&p[1]<=129&&
                        p[2]>=63&&p[2]<=65&&p[3]==255 : actual==padding_cpu_pixel(x,y,phase);
                    if(!match)++mismatch;
                }
                for(unsigned at=extent;at<allocation;++at)guards+=pixels[at]!=0xa5;
            }
            if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
        }
        valid=valid&&!mismatch&&!guards;
        if(valid)++completed;
    }
    printf("REDFIN METAL PAD RESTORE: boot=%016llx width=%u height=%u pitch=%u extent=%u allocation=%u completed=%u mismatches=%llu guard-errors=%llu actual-GMEM=%u CPU-rewrites=2\n",
        (unsigned long long)nonce,width,height,pitch,extent,allocation,completed,
        (unsigned long long)mismatch,(unsigned long long)guards,valid);
    [queue release];[pipeline release];[shape.vertexFunction release];[shape.fragmentFunction release];
    [shape release];[texture release];if(surface)CFRelease(surface);
    return valid&&completed==2;
}
