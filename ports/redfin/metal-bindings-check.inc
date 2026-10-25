/* SPDX-License-Identifier: MIT */
#include "metal-bindings.h"
static BOOL binding_statistics(id device,uint64_t counts[REDFIN_METAL_BINDING_WORDS])
{
    void *plugin=dlopen("/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",RTLD_NOW|RTLD_LOCAL|RTLD_NOLOAD);
    int (*read)(id,uint64_t *,size_t)=plugin?
        (int (*)(id,uint64_t *,size_t))dlsym(plugin,"redfin_metal_binding_statistics"):NULL;
    BOOL valid=read&&!read(device,counts,REDFIN_METAL_BINDING_WORDS);
    if(plugin)dlclose(plugin);return valid;
}
static BOOL bindings_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {width=8,height=4,pitch=64,offset=64,page=4096,draws=8};
    id<MTLRenderPipelineState> pipeline=ordering_pipeline(device,library,@"redfin_vertex",@"redfin_position_sample_fragment",nil);
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
    shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    id<MTLBuffer> parent=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    id<MTLTexture> target=[parent newTextureWithDescriptor:shape offset:offset bytesPerRow:pitch];
    id<MTLTexture> source=[device newTextureWithDescriptor:shape];id<MTLCommandQueue> queue=[device newCommandQueue];
    BOOL valid=pipeline&&parent&&parent.contents&&target&&source&&queue;unsigned passed=0;
    uint64_t before[REDFIN_METAL_BINDING_WORDS]={0},after[REDFIN_METAL_BINDING_WORDS]={0};
    for(unsigned phase=0;valid&&phase<3;++phase) {
        uint8_t pattern[width*height*4];for(unsigned i=0;i<sizeof(pattern);++i)pattern[i]=(uint8_t)(nonce+phase*79+i*37);
        [source replaceRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0 withBytes:pattern bytesPerRow:width*4];
        memset(parent.contents,0xa5,page);valid=binding_statistics(device,before)&&!before[10]&&!before[11];
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLRenderCommandEncoder> draw=[command renderCommandEncoderWithDescriptor:ordering_pass(target)];
        [draw setRenderPipelineState:pipeline];[draw setFragmentTexture:source atIndex:0];
        unsigned count=phase==2?1:draws;
        for(unsigned i=0;i<count;++i)[draw drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [draw endEncoding];valid=valid&&command&&draw;
        if(phase==2) {
            /* Refuse a later draw after the first has already retained native
             * views/CSOs. Error cleanup must still drain and release them. */
            id<MTLRenderCommandEncoder> missing=[command renderCommandEncoderWithDescriptor:ordering_pass(target)];
            [missing setRenderPipelineState:pipeline];
            [missing drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[missing endEncoding];valid=valid&&missing;
        }
        if(valid) {
            [command commit];[command waitUntilCompleted];
            valid=phase==2?command.status==MTLCommandBufferStatusError&&command.error!=nil:
                command.status==MTLCommandBufferStatusCompleted&&command.error==nil;
            valid=valid&&binding_statistics(device,after)&&!after[10]&&!after[11];
        }
        if(valid&&phase<2)valid=after[1]-before[1]==4&&after[2]-before[2]>=2*(draws-1)&&
            after[7]-before[7]>=6*(draws-1)&&after[8]-before[8]==2&&after[9]-before[9]==draws-1;
        const uint8_t *pixels=parent.contents;valid=valid&&pixels;
        for(unsigned i=0;valid&&i<page;++i) {
            BOOL in=i>=offset&&(i-offset)/pitch<height&&(i-offset)%pitch<width*4;
            uint8_t wanted=in?pattern[((i-offset)/pitch)*width*4+(i-offset)%pitch]:0xa5;
            if(pixels[i]!=wanted){printf("REDFIN METAL BINDING PIXEL: phase=%u byte=%u actual=%02x expected=%02x\n",phase,i,pixels[i],wanted);valid=NO;}
        }
        printf("REDFIN METAL BINDING REUSE: boot=%016llx phase=%u draws=%u descriptor-calls=%llu skips=%llu graphics-calls=%llu skips=%llu vertex-calls=%llu skips=%llu live-slots=%llu live-vertex-refs=%llu pixels-guards-cleanup=%u\n",
            (unsigned long long)nonce,phase,count,(unsigned long long)(after[1]-before[1]),(unsigned long long)(after[2]-before[2]),
            (unsigned long long)(after[6]-before[6]),(unsigned long long)(after[7]-before[7]),(unsigned long long)(after[8]-before[8]),
            (unsigned long long)(after[9]-before[9]),(unsigned long long)after[10],(unsigned long long)after[11],valid);
        if(valid)++passed;
    }
    printf("REDFIN METAL BINDING RESULT: boot=%016llx changing-CPU-inputs=%u identical-native-bindings-skipped=%u error-after-encoded-draw-cleanup=%u pixels-guards=%u\n",
        (unsigned long long)nonce,passed>=2,passed>=2,passed==3,valid&&passed==3);
    [queue release];[source release];[target release];[parent release];[pipeline release];return valid&&passed==3;
}
