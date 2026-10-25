/* SPDX-License-Identifier: MIT */
static BOOL buffer_texture_case(id<MTLDevice> device,NSUInteger pitch,NSUInteger offset,BOOL external,uint32_t nonce)
{
    enum {width=8,height=4,pixels=width*height*4,readPitch=40,readOffset=7,readBytes=readOffset+readPitch*height+23};
    NSUInteger page=(NSUInteger)getpagesize();void *allocation=NULL;
    if(!page||page>65536||(external&&posix_memalign(&allocation,page,page)))return NO;
    __block unsigned releases=0;__block BOOL releasedRange=NO;
    dispatch_semaphore_t released=dispatch_semaphore_create(0);BOOL valid=YES,created=NO;
    id<MTLTexture> view=nil,peer=nil;NSUInteger peerOffset=page/2;
    @autoreleasepool {
        id<MTLBuffer> parent=external?[device newBufferWithBytesNoCopy:allocation length:page options:MTLResourceStorageModeShared
            deallocator:^(void *bytes,NSUInteger length){releasedRange=bytes==allocation&&length==page;++releases;dispatch_semaphore_signal(released);}]:
            [device newBufferWithLength:page options:MTLResourceStorageModeShared];
        created=parent!=nil;uint8_t *original=parent.contents;
        uint8_t pattern[2][pixels];for(unsigned phase=0;phase<2;++phase)for(unsigned i=0;i<pixels;++i)
            pattern[phase][i]=(uint8_t)(nonce+i*37+phase*79);
        id<MTLBuffer> input[2]={[device newBufferWithBytes:pattern[0] length:pixels options:MTLResourceStorageModeShared],
            [device newBufferWithBytes:pattern[1] length:pixels options:MTLResourceStorageModeShared]};
        id<MTLBuffer> snapshot=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
        id<MTLBuffer> output=[device newBufferWithLength:readBytes options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> queue=[device newCommandQueue];
        valid=parent&&original&&input[0]&&input[1]&&snapshot&&snapshot.contents&&output&&output.contents&&queue;
        if(valid) {
            memset(original,0x93,page);memset(snapshot.contents,0xa5,page);memset(output.contents,0xa5,readBytes);
            MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                width:width height:height mipmapped:NO];shape.storageMode=MTLStorageModeShared;
            shape.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;
            view=[parent newTextureWithDescriptor:shape offset:offset bytesPerRow:pitch];
            peer=[parent newTextureWithDescriptor:shape offset:peerOffset bytesPerRow:pitch];
            valid=view&&view.buffer==parent&&view.bufferOffset==offset&&view.bufferBytesPerRow==pitch&&
                peer&&[(id)peer doesAliasResource:view]&&[(id)view doesAliasResource:parent]&&[(id)parent doesAliasResource:view];
        }
        if(valid) {
            @autoreleasepool {
                id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLBlitCommandEncoder> encoder=[command blitCommandEncoder];
                valid=command&&encoder;
                if(encoder) {
                    [encoder copyFromBuffer:input[0] sourceOffset:0 sourceBytesPerRow:width*4 sourceBytesPerImage:0
                        sourceSize:MTLSizeMake(width,height,1) toTexture:view destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
                    [encoder copyFromTexture:view sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                        sourceSize:MTLSizeMake(width,height,1) toTexture:peer destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
                    /* A raw buffer read must see a prior view's actual GPU writes. */
                    [encoder copyFromBuffer:parent sourceOffset:0 toBuffer:snapshot destinationOffset:0 size:page];
                    for(unsigned y=0;y<height;++y)
                        [encoder copyFromBuffer:input[1] sourceOffset:y*width*4 toBuffer:parent destinationOffset:offset+y*pitch size:width*4];
                    /* The same view must refresh after those raw-buffer writes,
                     * including an unaligned native shadow within this command. */
                    [encoder copyFromTexture:view sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                        sourceSize:MTLSizeMake(width,height,1) toBuffer:output destinationOffset:readOffset
                        destinationBytesPerRow:readPitch destinationBytesPerImage:0];
                    [encoder endEncoding];[parent release];parent=nil;
                    valid=valid&&blit_completed(command,"buffer-texture-shared-alias-transitions");
                }
            }
            for(NSUInteger i=0;valid&&i<page;++i) {
                BOOL in=i>=offset&&(i-offset)/pitch<height&&(i-offset)%pitch<width*4;
                BOOL inPeer=i>=peerOffset&&(i-peerOffset)/pitch<height&&(i-peerOffset)%pitch<width*4;
                unsigned at=in?(unsigned)(((i-offset)/pitch)*width*4+(i-offset)%pitch):0;
                unsigned peerAt=inPeer?(unsigned)(((i-peerOffset)/pitch)*width*4+(i-peerOffset)%pitch):0;
                uint8_t first=in?pattern[0][at]:inPeer?pattern[0][peerAt]:0x93;
                uint8_t second=in?pattern[1][at]:inPeer?pattern[0][peerAt]:0x93;
                if(((uint8_t *)snapshot.contents)[i]!=first||original[i]!=second) {
                    printf("REDFIN METAL BUFFER TEXTURE PIXEL: pitch=%lu offset=%lu external=%u byte=%lu snapshot=%02x/%02x original=%02x/%02x\n",
                        (unsigned long)pitch,(unsigned long)offset,external,(unsigned long)i,((uint8_t *)snapshot.contents)[i],first,original[i],second);valid=NO;
                }
            }
            for(unsigned i=0;valid&&i<readBytes;++i) {
                BOOL in=i>=readOffset&&(i-readOffset)/readPitch<height&&(i-readOffset)%readPitch<width*4;
                uint8_t wanted=in?pattern[1][((i-readOffset)/readPitch)*width*4+(i-readOffset)%readPitch]:0xa5;
                if(((uint8_t *)output.contents)[i]!=wanted) {
                    printf("REDFIN METAL BUFFER TEXTURE READ: pitch=%lu offset=%lu external=%u byte=%u actual=%02x expected=%02x\n",
                        (unsigned long)pitch,(unsigned long)offset,external,i,((uint8_t *)output.contents)[i],wanted);valid=NO;
                }
            }
        }
        [parent release];[queue release];[snapshot release];[output release];[input[0] release];[input[1] release];
    }
    if(external&&view) {
        /* With every command/caller reference gone, the view still owns its
         * parent. Its caller deallocator must not run until the view leaves. */
        valid=valid&&dispatch_semaphore_wait(released,dispatch_time(DISPATCH_TIME_NOW,50*NSEC_PER_MSEC))!=0;
    }
    [peer release];[view release];
    BOOL done=!external||!created||!dispatch_semaphore_wait(released,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC));
    if(external&&created)valid=valid&&done&&releasedRange&&releases==1;
    if(done){if(allocation)free(allocation);dispatch_release(released);}
    return valid;
}
static BOOL buffer_texture_native(id<MTLDevice> device,uint64_t nonce)
{
    BOOL aligned=buffer_texture_case(device,64,256,NO,(uint32_t)nonce);
    BOOL converted=buffer_texture_case(device,48,68,YES,(uint32_t)(nonce>>32));
    printf("REDFIN METAL BUFFER TEXTURE RESULT: boot=%016llx aligned-parent-pixels-guards=%u converted-external-offset-pixels-guards-lifetime=%u CPU-transfer-fallback=0\n",
        (unsigned long long)nonce,aligned,converted);return aligned&&converted;
}
