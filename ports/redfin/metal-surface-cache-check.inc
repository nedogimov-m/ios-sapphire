/* SPDX-License-Identifier: MIT */
/* Public IOSurface/Metal CPU->GPU->CPU round trips under the real allocation
 * cache requests. Every command finishes on its actual fence; no window or
 * application is opened. No new shader or compiler-cache identity is needed. */
static uint32_t surface_cache_pattern(unsigned x,unsigned y,unsigned round,unsigned hint)
{
    return 0xff000000u|((hint+37*x+19*y+73*round)&0xffffffu);
}
static BOOL surface_cache_case(id<MTLDevice> device,uint64_t nonce,unsigned hint)
{
    const unsigned width=16,height=8,pitch=64,visible=pitch*height,allocation=16384;
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),
        (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(pitch),
        (id)kIOSurfaceAllocSize:@(allocation),(id)kIOSurfacePixelFormat:@0x42475241,
        @"IOSurfaceCacheMode":@(hint),@"IOSurfaceIsGlobal":@YES};
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    id<MTLTexture> texture=surface?raster_texture(device,surface):nil;
    id<MTLCommandQueue> queue=[device newCommandQueue];
    BOOL valid=surface&&texture&&queue&&IOSurfaceGetAllocSize(surface)==allocation&&
        IOSurfaceGetWidth(surface)==width&&IOSurfaceGetHeight(surface)==height&&
        IOSurfaceGetBytesPerRow(surface)==pitch;
    unsigned rounds=0;
    for(unsigned round=0;valid&&round<3;++round) {
        uint32_t seed=0;
        valid=IOSurfaceLock(surface,0,&seed)==KERN_SUCCESS;
        if(valid) {
            uint8_t *bytes=IOSurfaceGetBaseAddress(surface);valid=bytes!=NULL;
            if(valid) {
                memset(bytes,0x5a,allocation);
                for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)
                    ((uint32_t *)bytes)[y*width+x]=surface_cache_pattern(x,y,round,hint);
            }
            if(IOSurfaceUnlock(surface,0,&seed)!=KERN_SUCCESS)valid=NO;
        }
        id<MTLBuffer> output=valid?[device newBufferWithLength:64+visible+64 options:MTLResourceStorageModeShared]:nil;
        valid=valid&&output&&output.contents;
        if(valid)memset(output.contents,0x33,output.length);
        id<MTLCommandBuffer> command=valid?[queue commandBuffer]:nil;
        id<MTLBlitCommandEncoder> blit=command?[command blitCommandEncoder]:nil;
        valid=valid&&blit;
        if(valid) {
            [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                sourceSize:MTLSizeMake(width,height,1) toBuffer:output destinationOffset:64
                destinationBytesPerRow:pitch destinationBytesPerImage:visible];
            [blit endEncoding];valid=raster_complete(command,"surface-cache-CPU-to-GPU");
        }
        const uint8_t *copied=valid?output.contents:NULL;
        for(unsigned y=0;valid&&y<height;++y)for(unsigned x=0;valid&&x<width;++x)
            if(((const uint32_t *)(copied+64))[y*width+x]!=surface_cache_pattern(x,y,round,hint))valid=NO;
        for(unsigned i=0;valid&&i<64;++i)
            if(copied[i]!=0x33||copied[64+visible+i]!=0x33)valid=NO;
        [output release];
        command=valid?[queue commandBuffer]:nil;
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=texture;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=MTLClearColorMake(round==0,round==1,round==2,1);
        id<MTLRenderCommandEncoder> render=command?[command renderCommandEncoderWithDescriptor:pass]:nil;
        valid=valid&&render;
        if(valid) {[render endEncoding];valid=raster_complete(command,"surface-cache-GPU-to-CPU");}
        if(valid) {
            valid=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
            if(valid) {
                const uint8_t *bytes=IOSurfaceGetBaseAddress(surface);valid=bytes!=NULL;
                uint32_t color=round==0?0xffff0000u:round==1?0xff00ff00u:0xff0000ffu;
                for(unsigned i=0;valid&&i<width*height;++i)
                    if(((const uint32_t *)bytes)[i]!=color)valid=NO;
                for(unsigned i=visible;valid&&i<allocation;++i)if(bytes[i]!=0x5a)valid=NO;
                if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
            }
        }
        if(valid)++rounds;
    }
    printf("REDFIN METAL SURFACE CACHE CASE: boot=%016llx hint=%#x rounds=%u CPU-to-GPU-and-output-guards=%u GPU-to-CPU-and-tail-guards=%u\n",
        (unsigned long long)nonce,hint,rounds,valid,valid);
    [queue release];[texture release];if(surface)CFRelease(surface);
    return valid;
}
static BOOL surface_cache_native(id<MTLDevice> device,uint64_t nonce)
{
    BOOL valid=surface_cache_case(device,nonce,kIOSurfaceMapDefaultCache)&&
        surface_cache_case(device,nonce,kIOSurfaceMapWriteCombineCache)&&
        surface_cache_case(device,nonce,kIOSurfaceMapCopybackCache)&&
        /* Actual20H392 CoreAnimation hint: kIOMapRealTimeCache. */
        surface_cache_case(device,nonce,0x700u);
    printf("REDFIN METAL SURFACE CACHE RESULT: boot=%016llx allocation-modes=4 rounds-each=3 full-CPU-GPU-pixels-and-guards=%u\n",
        (unsigned long long)nonce,valid);
    return valid;
}
