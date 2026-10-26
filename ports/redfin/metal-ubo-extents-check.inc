/* SPDX-License-Identifier: MIT */
#include "metal-frontend-profile.h"
static BOOL ubo_frontend_statistics(id device,uint64_t counts[REDFIN_METAL_FRONTEND_WORDS])
{
    void *plugin=dlopen("/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",RTLD_NOW|RTLD_LOCAL|RTLD_NOLOAD);
    int (*read)(id,uint64_t *,size_t)=plugin?
        (int (*)(id,uint64_t *,size_t))dlsym(plugin,"redfin_metal_frontend_statistics"):NULL;
    BOOL valid=read&&!read(device,counts,REDFIN_METAL_FRONTEND_WORDS);
    if(plugin)dlclose(plugin);return valid;
}
static uint32_t ubo_source_word(uint64_t nonce,unsigned phase,unsigned index)
{return (uint32_t)nonce^(phase*0x1f123bb5u+index*1664525u+1013904223u);}

static BOOL ubo_compute_extents(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {tail=256*1024,sourceBytes=tail+64,outputWords=128,outputFirst=16};
    unsigned passed=0;BOOL valid=YES;
    for(unsigned phase=0;valid&&phase<10;++phase) {
        unsigned bounded=phase<6?0:(phase==6||phase==8?1:2),threads=bounded?64:16;
        BOOL dynamic=phase==1||phase==3||phase==5||bounded,
            indirect=(phase>=2&&phase<=4)||phase==7||phase==8,
            gpu=phase==4||phase==5||phase>=8;
        NSString *name=bounded==1?(indirect?@"redfin_ubo_argument_masked":@"redfin_ubo_masked"):
            bounded==2?(indirect?@"redfin_ubo_argument_clamped":@"redfin_ubo_clamped"):
            indirect?(dynamic?@"redfin_ubo_argument_dynamic":@"redfin_ubo_argument_fixed"):
                (dynamic?@"redfin_ubo_dynamic":@"redfin_ubo_fixed");
        id<MTLFunction> function=[library newFunctionWithName:name];NSError *error=nil;
        id<MTLComputePipelineState> pipeline=function?[device newComputePipelineStateWithFunction:function error:&error]:nil;
        id<MTLBuffer> source=[device newBufferWithLength:sourceBytes options:MTLResourceStorageModeShared];
        id<MTLBuffer> output=[device newBufferWithLength:outputWords*4 options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> writer=[device newCommandQueue],reader=[device newCommandQueue];
        uint32_t *input=source.contents,*result=output.contents;
        valid=pipeline&&source&&output&&writer&&reader&&input&&result&&!error;
        if(input)for(unsigned i=0;i<sourceBytes/4;++i)input[i]=ubo_source_word(nonce,phase,i);
        if(result)for(unsigned i=0;i<outputWords;++i)result[i]=0xa5a5a5a5u;
        id<MTLArgumentEncoder> arguments=indirect?[function newArgumentEncoderWithBufferIndex:0]:nil;
        id<MTLBuffer> table=arguments?[device newBufferWithLength:arguments.encodedLength options:MTLResourceStorageModeShared]:nil;
        if(indirect) {
            valid=valid&&arguments&&table;
            [arguments setArgumentBuffer:table offset:0];
            [arguments setBuffer:source offset:4 atIndex:0];
            [arguments setBuffer:output offset:outputFirst*4 atIndex:1];
        }
        if(valid&&gpu) {
            id<MTLCommandBuffer> producer=[writer commandBuffer];id<MTLBlitCommandEncoder> fill=[producer blitCommandEncoder];
            valid=producer&&fill;
            [fill fillBuffer:source range:NSMakeRange(4,tail) value:0x5a];[fill endEncoding];
            if(valid)[producer commit];
        }
        id<MTLCommandBuffer> command=[reader commandBuffer];id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        uint64_t boundsBefore[REDFIN_METAL_FRONTEND_WORDS]={0},boundsAfter[REDFIN_METAL_FRONTEND_WORDS]={0};
        valid=valid&&ubo_frontend_statistics(device,boundsBefore);
        [encoder setComputePipelineState:pipeline];
        if(indirect)[encoder setBuffer:table offset:0 atIndex:0];
        else {[encoder setBuffer:output offset:outputFirst*4 atIndex:0];[encoder setBuffer:source offset:4 atIndex:1];}
        [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(threads,1,1)];[encoder endEncoding];
        valid=valid&&command&&encoder;
        if(valid)valid=blit_completed(command,"constant-fixed-dynamic-argument-GPU-written");
        for(unsigned i=0;valid&&i<outputWords;++i) {
            uint32_t wanted=0xa5a5a5a5u;
            if(i>=outputFirst&&i<outputFirst+threads) {
                unsigned thread=i-outputFirst,selected=bounded==1?(thread&31u)+34u:
                    bounded==2?(thread<15u?thread:15u)+34u:dynamic?thread+34:14;
                uint32_t a=gpu?0x5a5a5a5au:ubo_source_word(nonce,phase,selected);
                uint32_t b=gpu?0x5a5a5a5au:ubo_source_word(nonce,phase,1);
                wanted=a+b*17u+thread;
            }
            if(result[i]!=wanted){printf("REDFIN METAL UBO OUTPUT: phase=%u word=%u got=%08x expected=%08x\n",phase,i,result[i],wanted);valid=NO;}
        }
        for(unsigned i=0;valid&&i<sourceBytes/4;++i) {
            uint32_t wanted=gpu&&i>=1&&i<=tail/4?0x5a5a5a5au:ubo_source_word(nonce,phase,i);
            if(input[i]!=wanted){printf("REDFIN METAL UBO SOURCE: phase=%u word=%u input/guard changed\n",phase,i);valid=NO;}
        }
        uint64_t copied=0,proofs=0;
        valid=valid&&ubo_frontend_statistics(device,boundsAfter);
        if(bounded) {
            valid=valid&&
                boundsAfter[RF_MFP_CONSTANT_BYTES]>=boundsBefore[RF_MFP_CONSTANT_BYTES]&&
                boundsAfter[RF_MFP_CONSTANT_PROVEN]>boundsBefore[RF_MFP_CONSTANT_PROVEN]&&
                boundsAfter[RF_MFP_CONSTANT_FALLBACK]==boundsBefore[RF_MFP_CONSTANT_FALLBACK];
            if(valid) {
                copied=boundsAfter[RF_MFP_CONSTANT_BYTES]-boundsBefore[RF_MFP_CONSTANT_BYTES];
                proofs=boundsAfter[RF_MFP_CONSTANT_PROVEN]-boundsBefore[RF_MFP_CONSTANT_PROVEN];
                valid=copied>0&&copied<=1024&&
                    boundsAfter[RF_MFP_CONSTANT_GPU]==boundsBefore[RF_MFP_CONSTANT_GPU];
            }
        }
        if(phase==1||phase==3||phase==5)
            valid=valid&&boundsAfter[RF_MFP_CONSTANT_GPU]==boundsBefore[RF_MFP_CONSTANT_GPU]+1&&
                boundsAfter[RF_MFP_CONSTANT_GPU_BYTES]==boundsBefore[RF_MFP_CONSTANT_GPU_BYTES]+sourceBytes-4;
        printf("REDFIN METAL UBO CASE: boot=%016llx phase=%u dynamic=%u bounded=%u argument-buffer=%u GPU-written=%u threads=%u copied-bytes=%llu proven-snapshots=%llu actual-values-and-guards=%u\n",
            (unsigned long long)nonce,phase,dynamic,bounded,indirect,gpu,threads,
            (unsigned long long)copied,(unsigned long long)proofs,valid);
        if(valid)++passed;
        [table release];[arguments release];[writer release];[reader release];[output release];[source release];[pipeline release];[function release];
    }
    return valid&&passed==10;
}

/* Four distinct snapshots in one deferred command, across GPU overwrites of
 * the same source. Exercise byte offsets/tails and argument-buffer restoration;
 * prior slices and queued resource references must survive arena rollover. */
static BOOL ubo_gpu_snapshots(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {rounds=4,sourceBytes=320*1024+63,outputWords=128,threads=64,first=16};
    const unsigned offsets[rounds]={1,3,4,63};
    const uint8_t fills[rounds]={0,0x5a,0xc3,0x7e};
    id<MTLFunction> function=[library newFunctionWithName:@"redfin_ubo_argument_dynamic"];
    NSError *error=nil;
    id<MTLComputePipelineState> pipeline=function?[device newComputePipelineStateWithFunction:function error:&error]:nil;
    id<MTLBuffer> source=[device newBufferWithLength:sourceBytes options:MTLResourceStorageModeShared];
    id<MTLCommandQueue> queue=[device newCommandQueue];
    uint8_t *input=source.contents;
    BOOL valid=function&&pipeline&&!error&&source&&input&&queue;
    uint8_t *initial=malloc(sourceBytes);
    valid=valid&&initial;
    if(initial)for(unsigned i=0;i<sourceBytes;++i)initial[i]=(uint8_t)((i*37u)^(nonce>>(8*(i&7))));
    if(input&&initial)memcpy(input,initial,sourceBytes);
    id<MTLBuffer> outputs[rounds]={nil},tables[rounds]={nil};
    id<MTLArgumentEncoder> arguments[rounds]={nil};
    uint64_t before[REDFIN_METAL_FRONTEND_WORDS]={0},after[REDFIN_METAL_FRONTEND_WORDS]={0};
    valid=valid&&ubo_frontend_statistics(device,before);
    id<MTLCommandBuffer> command=[queue commandBuffer];
    for(unsigned round=0;valid&&round<rounds;++round) {
        outputs[round]=[device newBufferWithLength:outputWords*4 options:MTLResourceStorageModeShared];
        arguments[round]=[function newArgumentEncoderWithBufferIndex:0];
        tables[round]=[device newBufferWithLength:arguments[round].encodedLength options:MTLResourceStorageModeShared];
        uint32_t *result=outputs[round].contents;
        valid=outputs[round]&&result&&arguments[round]&&tables[round];
        if(!valid)break;
        for(unsigned i=0;i<outputWords;++i)result[i]=0xa5a5a5a5u;
        if(round) {
            id<MTLBlitCommandEncoder> fill=[command blitCommandEncoder];
            valid=fill!=nil;
            [fill fillBuffer:source range:NSMakeRange(64,sourceBytes-128) value:fills[round]];[fill endEncoding];
        }
        [arguments[round] setArgumentBuffer:tables[round] offset:0];
        [arguments[round] setBuffer:source offset:offsets[round] atIndex:0];
        [arguments[round] setBuffer:outputs[round] offset:first*4 atIndex:1];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        valid=valid&&encoder!=nil;
        [encoder setComputePipelineState:pipeline];[encoder setBuffer:tables[round] offset:0 atIndex:0];
        [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(threads,1,1)];[encoder endEncoding];
    }
    if(valid)valid=command&&blit_completed(command,"large-constant-snapshots-byte-tails-argument-GPU-overwrites");
    uint64_t expectedBytes=0;
    for(unsigned round=0;round<rounds;++round) {
        expectedBytes+=sourceBytes-offsets[round];
        const uint32_t *result=outputs[round].contents;
        for(unsigned i=0;valid&&i<outputWords;++i) {
            uint32_t wanted=0xa5a5a5a5u;
            if(i>=first&&i<first+threads) {
                unsigned thread=i-first;uint32_t a=0,b=0;
                for(unsigned byte=0;byte<4;++byte) {
                    unsigned ai=offsets[round]+4*(thread+33)+byte,bi=offsets[round]+byte;
                    uint8_t av=round&&ai>=64&&ai<sourceBytes-64?fills[round]:initial[ai];
                    uint8_t bv=round&&bi>=64&&bi<sourceBytes-64?fills[round]:initial[bi];
                    a|=(uint32_t)av<<(8*byte);b|=(uint32_t)bv<<(8*byte);
                }
                wanted=a+b*17u+thread;
            }
            if(!result||result[i]!=wanted){printf("REDFIN METAL GPU SNAPSHOT PIXEL: round=%u word=%u\n",round,i);valid=NO;}
        }
    }
    for(unsigned i=0;valid&&i<sourceBytes;++i) {
        uint8_t wanted=i>=64&&i<sourceBytes-64?fills[rounds-1]:initial[i];
        if(input[i]!=wanted){printf("REDFIN METAL GPU SNAPSHOT SOURCE: byte=%u\n",i);valid=NO;}
    }
    valid=valid&&ubo_frontend_statistics(device,after)&&
        after[RF_MFP_CONSTANT_GPU]==before[RF_MFP_CONSTANT_GPU]+rounds&&
        after[RF_MFP_CONSTANT_GPU_BYTES]==before[RF_MFP_CONSTANT_GPU_BYTES]+expectedBytes&&
        after[RF_MFP_CONSTANT_GPU_CHUNKS]>before[RF_MFP_CONSTANT_GPU_CHUNKS];
    printf("REDFIN METAL GPU SNAPSHOT RESULT: boot=%016llx snapshots=%u bytes=%llu byte-tails-arguments-overwrites-rollover-guards=%u\n",
        (unsigned long long)nonce,rounds,(unsigned long long)expectedBytes,valid);
    for(unsigned i=0;i<rounds;++i){[tables[i] release];[arguments[i] release];[outputs[i] release];}
    free(initial);[queue release];[source release];[pipeline release];[function release];return valid;
}

static BOOL ubo_render_extents(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {width=8,height=8,bytes=256*1024};
    id<MTLRenderPipelineState> pipeline=ordering_pipeline(device,library,@"redfin_ubo_vertex",@"redfin_ubo_fragment",nil);
    id<MTLBuffer> vertex=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    id<MTLBuffer> fragment=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
    shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;shape.storageMode=MTLStorageModeShared;
    id<MTLTexture> target=[device newTextureWithDescriptor:shape];id<MTLCommandQueue> queue=[device newCommandQueue];
    BOOL valid=pipeline&&vertex&&fragment&&target&&queue&&vertex.contents&&fragment.contents;
    if(valid) {
        memset(vertex.contents,0xa5,bytes);memset(fragment.contents,0xa5,bytes);
        float *v=(float *)((uint8_t *)vertex.contents+4),*f=(float *)((uint8_t *)fragment.contents+4);
        v[0]=v[13]=1;f[0]=0.125f;f[5]=0.375f;f[9]=0.625f;f[13]=0.875f;
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> draw=[command renderCommandEncoderWithDescriptor:ordering_pass(target)];
        [draw setRenderPipelineState:pipeline];[draw setVertexBuffer:vertex offset:4 atIndex:1];[draw setFragmentBuffer:fragment offset:4 atIndex:1];
        [draw drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[draw endEncoding];
        valid=command&&draw&&blit_completed(command,"constant-independent-vertex-fragment");
        uint8_t pixels[width*height*4]={0};[target getBytes:pixels bytesPerRow:width*4 fromRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0];
        const unsigned expected[4]={32,96,159,223};
        for(unsigned i=0;valid&&i<sizeof(pixels);++i) {
            int difference=(int)pixels[i]-(int)expected[i%4];
            if(difference<-1||difference>1)valid=NO;
        }
    }
    printf("REDFIN METAL UBO RASTER: boot=%016llx independent-unaligned-vertex-fragment=%u pixels=%u\n",(unsigned long long)nonce,valid,valid?width*height:0);
    [queue release];[target release];[fragment release];[vertex release];[pipeline release];return valid;
}

static BOOL ubo_render_gpu_snapshots(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {width=8,height=8,bytes=256*1024+64};
    id<MTLRenderPipelineState> pipeline=ordering_pipeline(device,library,@"redfin_ubo_dynamic_vertex",@"redfin_ubo_dynamic_fragment",nil);
    id<MTLBuffer> vertex=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    id<MTLBuffer> fragment=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
    shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;shape.storageMode=MTLStorageModeShared;
    id<MTLTexture> target=[device newTextureWithDescriptor:shape];id<MTLCommandQueue> queue=[device newCommandQueue];
    uint8_t *v=vertex.contents,*f=fragment.contents;
    BOOL valid=pipeline&&vertex&&fragment&&target&&queue&&v&&f;
    uint8_t *expectedVertex=malloc(bytes),*expectedFragment=malloc(bytes);
    valid=valid&&expectedVertex&&expectedFragment;
    if(valid) {
        memset(v,0xa5,bytes);memset(f,0xa5,bytes);
        for(unsigned i=0;i<64;++i) {
            float a=1,b=i==0?0.375f:i==5?0.625f:i==9?0.875f:0.125f;
            memcpy(v+3+4*i,&a,4);memcpy(f+1+4*i,&b,4);
        }
        memcpy(expectedVertex,v,bytes);memcpy(expectedFragment,f,bytes);
        uint64_t before[REDFIN_METAL_FRONTEND_WORDS]={0},after[REDFIN_METAL_FRONTEND_WORDS]={0};
        valid=ubo_frontend_statistics(device,before);
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> draw=[command renderCommandEncoderWithDescriptor:ordering_pass(target)];
        [draw setRenderPipelineState:pipeline];[draw setVertexBuffer:vertex offset:3 atIndex:1];[draw setFragmentBuffer:fragment offset:1 atIndex:1];
        for(unsigned i=0;i<2;++i)[draw drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [draw endEncoding];
        valid=valid&&command&&draw&&blit_completed(command,"large-constant-independent-vertex-fragment-repeated-draws")&&
            ubo_frontend_statistics(device,after)&&after[RF_MFP_CONSTANT_GPU]==before[RF_MFP_CONSTANT_GPU]+4&&
            after[RF_MFP_CONSTANT_GPU_BYTES]==before[RF_MFP_CONSTANT_GPU_BYTES]+2*((uint64_t)bytes*2-4);
        uint8_t pixels[width*height*4]={0};[target getBytes:pixels bytesPerRow:width*4 fromRegion:MTLRegionMake2D(0,0,width,height) mipmapLevel:0];
        const unsigned expected[4]={32,96,159,223};
        for(unsigned i=0;valid&&i<sizeof(pixels);++i) {
            int difference=(int)pixels[i]-(int)expected[i%4];if(difference<-1||difference>1)valid=NO;
        }
        valid=valid&&!memcmp(v,expectedVertex,bytes)&&!memcmp(f,expectedFragment,bytes);
    }
    printf("REDFIN METAL GPU SNAPSHOT RASTER: boot=%016llx independent-vertex-fragment-two-draws-values-guards=%u pixels=%u\n",
        (unsigned long long)nonce,valid,valid?width*height:0);
    free(expectedFragment);free(expectedVertex);
    [queue release];[target release];[fragment release];[vertex release];[pipeline release];return valid;
}

static BOOL ubo_extents_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    uint64_t before[REDFIN_METAL_FRONTEND_WORDS]={0},after[REDFIN_METAL_FRONTEND_WORDS]={0};
    BOOL valid=ubo_frontend_statistics(device,before)&&ubo_compute_extents(device,library,nonce)&&
        ubo_render_extents(device,library,nonce)&&ubo_gpu_snapshots(device,library,nonce)&&
        ubo_render_gpu_snapshots(device,library,nonce)&&ubo_frontend_statistics(device,after);
    uint64_t proven=after[RF_MFP_CONSTANT_PROVEN]>=before[RF_MFP_CONSTANT_PROVEN]?after[RF_MFP_CONSTANT_PROVEN]-before[RF_MFP_CONSTANT_PROVEN]:0;
    uint64_t avoided=after[RF_MFP_CONSTANT_AVOIDED_BYTES]>=before[RF_MFP_CONSTANT_AVOIDED_BYTES]?after[RF_MFP_CONSTANT_AVOIDED_BYTES]-before[RF_MFP_CONSTANT_AVOIDED_BYTES]:0;
    uint64_t full=after[RF_MFP_CONSTANT_FALLBACK]>=before[RF_MFP_CONSTANT_FALLBACK]?after[RF_MFP_CONSTANT_FALLBACK]-before[RF_MFP_CONSTANT_FALLBACK]:0;
    valid=valid&&proven>=7&&avoided>=2*(256*1024-256)&&full>=3;
    printf("REDFIN METAL UBO RESULT: boot=%016llx fixed-dynamic-arguments-GPU-writers-raster-guards=%u masked-clamped-boundaries=1 proven-snapshots=%llu avoided-bytes=%llu conservative-full=%llu\n",
        (unsigned long long)nonce,valid,(unsigned long long)proven,(unsigned long long)avoided,(unsigned long long)full);
    return valid;
}
