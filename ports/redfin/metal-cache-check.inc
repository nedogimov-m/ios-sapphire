/* SPDX-License-Identifier: MIT
 * Exercise actual A620 pixels while independent pipelines outlive both LRUs.
 * These checks run only in the explicitly enabled offscreen checker.
 */
#include "metal-translation-cache.h"
static BOOL cache_statistics(id device,uint64_t counts[REDFIN_AIR_CACHE_STAT_WORDS])
{
    void *plugin=dlopen("/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",RTLD_NOW|RTLD_LOCAL|RTLD_NOLOAD);
    int (*read)(id,uint64_t *,size_t)=plugin?
        (int (*)(id,uint64_t *,size_t))dlsym(plugin,"redfin_metal_translation_cache_statistics"):NULL;
    BOOL valid=read&&!read(device,counts,REDFIN_AIR_CACHE_STAT_WORDS);
    if(plugin)dlclose(plugin);return valid;
}
static id<MTLRenderPipelineState> cache_pipeline(id<MTLDevice> device,id<MTLLibrary> library,
    const unsigned rgba[4])
{
    float color[4];for(unsigned i=0;i<4;++i)color[i]=rgba[i]/255.0f;
    MTLFunctionConstantValues *values=[MTLFunctionConstantValues new];
    [values setConstantValue:color type:MTLDataTypeFloat4 atIndex:41];
    NSError *error=nil;id<MTLFunction> fragment=[library newFunctionWithName:@"redfin_constants_fragment" constantValues:values error:&error];
    id<MTLFunction> vertex=[library newFunctionWithName:@"redfin_vertex"];
    MTLRenderPipelineDescriptor *shape=[MTLRenderPipelineDescriptor new];
    shape.vertexFunction=vertex;shape.fragmentFunction=fragment;
    shape.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    id<MTLRenderPipelineState> pipeline=fragment&&vertex?[device newRenderPipelineStateWithDescriptor:shape error:&error]:nil;
    if(!pipeline)printf("REDFIN METAL CACHE PIPELINE: %s\n",error?error.description.UTF8String:"missing function");
    [shape release];[vertex release];[fragment release];[values release];return pipeline;
}
static BOOL cache_draw(id<MTLCommandQueue> queue,id<MTLTexture> texture,IOSurfaceRef surface,
    id<MTLRenderPipelineState> pipeline,const unsigned rgba[4],unsigned round)
{
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture=texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
    pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
    id<MTLCommandBuffer> command=[queue commandBuffer];
    id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
    BOOL valid=command&&encoder&&pipeline;
    if(encoder) {
        if(pipeline){[encoder setRenderPipelineState:pipeline];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];}
        [encoder endEncoding];
    }
    valid=valid&&raster_complete(command,"cache-hit-eviction-surviving-pipeline");
    uint32_t seed=0;if(valid) {
        valid=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
        if(valid) {
            const uint8_t *pixels=IOSurfaceGetBaseAddress(surface);valid=pixels!=NULL;
            const unsigned bgra[4]={rgba[2],rgba[1],rgba[0],rgba[3]};
            for(unsigned i=0;valid&&i<1024;++i)if(abs((int)pixels[i]-(int)bgra[i&3])>1) {
                printf("REDFIN METAL CACHE PIXEL: round=%u byte=%u actual=%u expected=%u\n",round,i,pixels[i],bgra[i&3]);valid=NO;
            }
            for(unsigned i=1024;valid&&i<16384;++i)if(pixels[i]!=0xa5) {
                printf("REDFIN METAL CACHE GUARD: round=%u byte=%u\n",round,i);valid=NO;
            }
            if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
        }
    }
    return valid;
}
static BOOL preparation_cache_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    uint64_t before[REDFIN_AIR_CACHE_STAT_WORDS]={0},warm[REDFIN_AIR_CACHE_STAT_WORDS]={0},after[REDFIN_AIR_CACHE_STAT_WORDS]={0};
    BOOL observed=cache_statistics(device,before);
    const unsigned original[4]={17,53,197,255};
    id<MTLRenderPipelineState> first=cache_pipeline(device,library,original),second=cache_pipeline(device,library,original);
    IOSurfaceRef surface=raster_surface(16,16,64,16384);id<MTLTexture> texture=raster_texture(device,surface);
    id<MTLCommandQueue> queue=[device newCommandQueue];
    BOOL valid=observed&&first&&second&&first!=second&&surface&&texture&&queue&&
        cache_statistics(device,warm)&&warm[0]>=before[0]+2&&warm[6]>=before[6]+2;
    if(valid)valid=cache_draw(queue,texture,surface,first,original,0)&&cache_draw(queue,texture,surface,second,original,1);
    unsigned rounds=0;
    for(unsigned i=0;valid&&i<70;++i) {
        @autoreleasepool {
            const unsigned color[4]={31+i,109+(i%67),233-i,255};
            id<MTLRenderPipelineState> variant=cache_pipeline(device,library,color);
            valid=variant&&cache_draw(queue,texture,surface,variant,color,i+2);
            [variant release];if(valid)++rounds;
        }
    }
    BOOL bounds=cache_statistics(device,after)&&after[2]<=REDFIN_AIR_CACHE_ENTRIES&&
        after[3]<=REDFIN_AIR_CACHE_BYTES&&after[8]<=REDFIN_AIR_CACHE_ENTRIES&&after[9]<=REDFIN_AIR_CACHE_BYTES;
    BOOL evicted=bounds&&after[4]>warm[4]&&after[10]>warm[10];
    BOOL survived=valid&&evicted&&cache_draw(queue,texture,surface,first,original,72)&&
        cache_draw(queue,texture,surface,second,original,73);
    printf("REDFIN METAL CACHE RESULT: boot=%016llx duplicate-template-and-stage-hits=%u template-hits=%llu stage-hits=%llu variants=%u bounded=%u template-evictions=%llu stage-evictions=%llu surviving-pipelines-pixels-guards=%u\n",
        (unsigned long long)nonce,observed&&warm[0]>=before[0]+2&&warm[6]>=before[6]+2,
        (unsigned long long)(warm[0]-before[0]),(unsigned long long)(warm[6]-before[6]),rounds,bounds,
        (unsigned long long)(after[4]-before[4]),(unsigned long long)(after[10]-before[10]),survived);
    [queue release];[texture release];if(surface)CFRelease(surface);[second release];[first release];
    return survived&&rounds==70;
}
