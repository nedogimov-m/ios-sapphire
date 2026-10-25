/* SPDX-License-Identifier: MIT */
/* Offscreen transfers through the public Metal encoder. CPU writes initialize
 * fixtures; every tested transfer/fill/mip operation is native GPU work. */
static BOOL blit_completed(id<MTLCommandBuffer> command,const char *probe)
{
    if(!command)return NO;
    [command commit];[command waitUntilCompleted];
    BOOL valid=command.status==MTLCommandBufferStatusCompleted&&!command.error;
    if(!valid)printf("REDFIN METAL BLIT CHECK: probe=%s status=%lu error=%s\n",probe,
        (unsigned long)command.status,command.error?command.error.description.UTF8String:"none");
    return valid;
}
static BOOL blit_bytes(id<MTLDevice> device,uint32_t seed)
{
    enum {length=2048};
    id<MTLCommandQueue> queue=[device newCommandQueue];
    id<MTLBuffer> source=[device newBufferWithLength:length options:MTLResourceStorageModeShared];
    id<MTLBuffer> destination=[device newBufferWithLength:length options:MTLResourceStorageModeShared];
    uint8_t original[length],expected[length];
    for(unsigned i=0;i<length;++i)original[i]=(uint8_t)((i*37u)^(i>>3)^seed);
    memset(expected,0xa5,length);
    BOOL valid=queue&&source&&destination&&source.contents&&destination.contents;
    if(valid) {
        memcpy(source.contents,original,length);memcpy(destination.contents,expected,length);
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];valid=command&&encoder;
        if(valid) {
            [encoder fillBuffer:destination range:NSMakeRange(7,389) value:0x6d];
            [encoder copyFromBuffer:source sourceOffset:3 toBuffer:destination destinationOffset:402 size:517];
            [encoder copyFromBuffer:source sourceOffset:64 toBuffer:destination destinationOffset:1024 size:256];
            [encoder copyFromBuffer:destination sourceOffset:1032 toBuffer:destination destinationOffset:1440 size:96];
            [encoder endEncoding];
            valid=!memcmp(destination.contents,expected,length); /* recording must not execute */
            memset(expected+7,0x6d,389);memcpy(expected+402,original+3,517);
            memcpy(expected+1024,original+64,256);memcpy(expected+1440,expected+1032,96);
            valid=valid&&blit_completed(command,"byte-fill-copy")&&
                !memcmp(source.contents,original,length)&&!memcmp(destination.contents,expected,length);
        }
    }
    /* An invalid range must deliver an actual Error and release the queue slot;
     * the next valid command must still execute. */
    if(valid) {
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];valid=command&&encoder;
        __block BOOL called=NO;
        if(valid) {
            [command addCompletedHandler:^(id<MTLCommandBuffer> done){called=done.status==MTLCommandBufferStatusError&&done.error!=nil;}];
            [encoder fillBuffer:destination range:NSMakeRange(length-1,2) value:0];[encoder endEncoding];
            [command commit];[command waitUntilCompleted];
            valid=called&&command.status==MTLCommandBufferStatusError&&command.error&&
                !memcmp(destination.contents,expected,length);
        }
        command=[queue commandBuffer];encoder=[command blitCommandEncoder];valid=valid&&command&&encoder;
        if(encoder) {
            [encoder fillBuffer:destination range:NSMakeRange(length-3,1) value:0x94];[encoder endEncoding];
            expected[length-3]=0x94;
            valid=valid&&blit_completed(command,"after-invalid-range")&&!memcmp(destination.contents,expected,length);
        }
    }
    [destination release];[source release];[queue release];return valid;
}
static BOOL blit_texture_roundtrip(id<MTLDevice> device,uint32_t seed)
{
    enum {width=120,height=32,pitch=480,allocation=16384,inputPitch=160,inputOffset=13,
          copyWidth=37,copyHeight=11,outputPitch=497,outputOffset=19,outputBytes=outputOffset+outputPitch*height+31};
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),
        (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(pitch),
        (id)kIOSurfaceAllocSize:@(allocation),(id)kIOSurfacePixelFormat:@0x42475241,@"IOSurfaceIsGlobal":@YES};
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    id<MTLTexture> textures[3]={nil,nil,nil};
    id<MTLCommandQueue> queue=[device newCommandQueue];
    id<MTLBuffer> input=[device newBufferWithLength:inputOffset+inputPitch*copyHeight+29 options:MTLResourceStorageModeShared];
    id<MTLBuffer> output=[device newBufferWithLength:outputBytes options:MTLResourceStorageModeShared];
    BOOL valid=surface&&IOSurfaceGetAllocSize(surface)==allocation&&IOSurfaceGetBytesPerRow(surface)==pitch&&
        queue&&input&&output&&input.contents&&output.contents;
    uint8_t *initial=malloc(128*64*4),*expected=malloc(allocation),*actual=malloc(128*64*4);
    uint8_t inputOriginal[inputOffset+inputPitch*copyHeight+29];
    valid=valid&&initial&&expected&&actual;
    uint32_t lockSeed=0;
    if(valid) {
        valid=IOSurfaceLock(surface,0,&lockSeed)==KERN_SUCCESS;
        if(valid) {
            void *pixels=IOSurfaceGetBaseAddress(surface);valid=pixels!=NULL;
            if(pixels)memset(pixels,0x7b,allocation);
            if(IOSurfaceUnlock(surface,0,&lockSeed)!=KERN_SUCCESS)valid=NO;
        }
        memset(inputOriginal,0xc3,sizeof(inputOriginal));
        for(unsigned y=0;y<copyHeight;++y)for(unsigned x=0;x<copyWidth*4;++x)
            inputOriginal[inputOffset+y*inputPitch+x]=(uint8_t)((x*17u+y*31u+seed)^(y<<2));
        memcpy(input.contents,inputOriginal,sizeof(inputOriginal));memset(output.contents,0xa5,outputBytes);
        memset(expected,0x7b,allocation);
        for(unsigned y=0;y<copyHeight;++y)memcpy(expected+(10+y)*pitch+53*4,inputOriginal+inputOffset+y*inputPitch,copyWidth*4);
        for(unsigned i=0;i<3&&valid;++i) {
            MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                width:i==2?width:128 height:i==2?height:64 mipmapped:NO];
            shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;
            textures[i]=i==2?[(id)device newTextureWithDescriptor:shape iosurface:surface plane:0]:[device newTextureWithDescriptor:shape];
            valid=textures[i]!=nil;
            if(i<2&&valid) {
                memset(initial,i?0x7b:0x3c,128*64*4);
                [textures[i] replaceRegion:MTLRegionMake2D(0,0,128,64) mipmapLevel:0 withBytes:initial bytesPerRow:512];
            }
        }
    }
    if(valid) {
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];valid=command&&encoder;
        if(valid) {
            [encoder copyFromBuffer:input sourceOffset:inputOffset sourceBytesPerRow:inputPitch sourceBytesPerImage:0
                sourceSize:MTLSizeMake(copyWidth,copyHeight,1) toTexture:textures[0] destinationSlice:0 destinationLevel:0
                destinationOrigin:MTLOriginMake(5,7,0)];
            [encoder copyFromTexture:textures[0] sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(5,7,0)
                sourceSize:MTLSizeMake(copyWidth,copyHeight,1) toTexture:textures[1] destinationSlice:0 destinationLevel:0
                destinationOrigin:MTLOriginMake(31,9,0)];
            [encoder copyFromTexture:textures[1] sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(31,9,0)
                sourceSize:MTLSizeMake(copyWidth,copyHeight,1) toTexture:textures[2] destinationSlice:0 destinationLevel:0
                destinationOrigin:MTLOriginMake(53,10,0)];
            [encoder copyFromTexture:textures[2] sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                sourceSize:MTLSizeMake(width,height,1) toBuffer:output destinationOffset:outputOffset
                destinationBytesPerRow:outputPitch destinationBytesPerImage:0];
            [encoder endEncoding];
            valid=blit_completed(command,"buffer-texture-texture-surface-buffer")&&
                !memcmp(input.contents,inputOriginal,sizeof(inputOriginal));
            uint8_t *pixels=output.contents;
            for(unsigned at=0;valid&&at<outputBytes;++at) {
                BOOL in=at>=outputOffset&&(at-outputOffset)/outputPitch<height&&(at-outputOffset)%outputPitch<pitch;
                uint8_t wanted=in?expected[((at-outputOffset)/outputPitch)*pitch+(at-outputOffset)%outputPitch]:0xa5;
                if(pixels[at]!=wanted) {
                    printf("REDFIN METAL BLIT CHECK: output byte=%u actual=%02x expected=%02x\n",at,pixels[at],wanted);valid=NO;
                }
            }
        }
    }
    if(valid) {
        valid=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&lockSeed)==KERN_SUCCESS;
        if(valid) {
            const void *pixels=IOSurfaceGetBaseAddress(surface);valid=pixels&&!memcmp(pixels,expected,allocation);
            if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&lockSeed)!=KERN_SUCCESS)valid=NO;
        }
    }
    for(unsigned i=0;valid&&i<2;++i) {
        memset(initial,i?0x7b:0x3c,128*64*4);
        for(unsigned y=0;y<copyHeight;++y)memcpy(initial+((i?9:7)+y)*512+(i?31:5)*4,inputOriginal+inputOffset+y*inputPitch,copyWidth*4);
        memset(actual,0xa5,128*64*4);
        [textures[i] getBytes:actual bytesPerRow:512 fromRegion:MTLRegionMake2D(0,0,128,64) mipmapLevel:0];
        valid=!memcmp(initial,actual,128*64*4);
    }
    free(actual);free(expected);free(initial);
    for(unsigned i=0;i<3;++i)[textures[i] release];
    [output release];[input release];[queue release];if(surface)CFRelease(surface);return valid;
}
static BOOL blit_mips(id<MTLDevice> device)
{
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
        width:64 height:32 mipmapped:YES];shape.storageMode=MTLStorageModeShared;
    shape.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;
    id<MTLTexture> texture=[device newTextureWithDescriptor:shape];
    id<MTLCommandQueue> queue=[device newCommandQueue];
    enum {offset=7,row=133,bytes=offset+row*16+31};
    id<MTLBuffer> output=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    uint8_t original[64*32*4],unchanged[sizeof(original)];
    for(unsigned y=0;y<32;++y)for(unsigned x=0;x<64;++x) {
        unsigned at=(y*64+x)*4;original[at]=(x&1)*128;original[at+1]=(y&1)*128;
        original[at+2]=((x+y)&1)*128;original[at+3]=255;
    }
    BOOL valid=texture&&texture.mipmapLevelCount==7&&queue&&output&&output.contents;
    if(valid) {
        memset(output.contents,0xa5,bytes);
        [texture replaceRegion:MTLRegionMake2D(0,0,64,32) mipmapLevel:0 withBytes:original bytesPerRow:256];
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];valid=command&&encoder;
        if(valid) {
            [encoder generateMipmapsForTexture:texture];
            [encoder copyFromTexture:texture sourceSlice:0 sourceLevel:1 sourceOrigin:MTLOriginMake(0,0,0)
                sourceSize:MTLSizeMake(32,16,1) toBuffer:output destinationOffset:offset
                destinationBytesPerRow:row destinationBytesPerImage:0];
            [encoder copyFromTexture:texture sourceSlice:0 sourceLevel:6 sourceOrigin:MTLOriginMake(0,0,0)
                sourceSize:MTLSizeMake(1,1,1) toBuffer:output destinationOffset:bytes-4
                destinationBytesPerRow:4 destinationBytesPerImage:0];
            [encoder endEncoding];valid=blit_completed(command,"mipmaps-nonzero-level");
            const uint8_t *pixels=output.contents;
            for(unsigned at=0;valid&&at<bytes;++at) {
                BOOL in=at>=offset&&(at-offset)/row<16&&(at-offset)%row<128;
                BOOL last=at>=bytes-4;unsigned channel=last?at-(bytes-4):(at-offset)%row%4;
                uint8_t wanted=(in||last)?(channel==3?255:64):0xa5;
                if(pixels[at]!=wanted) {
                    printf("REDFIN METAL BLIT CHECK: mip byte=%u actual=%02x expected=%02x\n",at,pixels[at],wanted);valid=NO;
                }
            }
            memset(unchanged,0xa5,sizeof(unchanged));
            [texture getBytes:unchanged bytesPerRow:256 fromRegion:MTLRegionMake2D(0,0,64,32) mipmapLevel:0];
            valid=valid&&!memcmp(unchanged,original,sizeof(original));
        }
    }
    [output release];[queue release];[texture release];return valid;
}
static BOOL blit_native(id<MTLDevice> device,uint64_t nonce)
{
    BOOL bytes=blit_bytes(device,(uint32_t)nonce);
    BOOL round0=blit_texture_roundtrip(device,(uint32_t)nonce);
    BOOL round1=blit_texture_roundtrip(device,(uint32_t)(nonce>>32)^0x8615c43du);
    BOOL mips=blit_mips(device);
    printf("REDFIN METAL BLIT RESULT: boot=%016llx byte-fill-copy-source-and-guards=%u queued-roundtrip0-pixels-guards=%u queued-roundtrip1-pixels-guards=%u mipmap-pixels-and-base-unchanged=%u CPU-transfer-fallback=0 visible-overlay=0\n",
        (unsigned long long)nonce,bytes,round0,round1,mips);
    return bytes&&round0&&round1&&mips;
}
