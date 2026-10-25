/* SPDX-License-Identifier: MIT */
#include "metal-ordering.h"
static BOOL ordering_statistics(id device,uint64_t values[REDFIN_METAL_ORDERING_WORDS])
{
    void *plugin=dlopen("/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",RTLD_NOW|RTLD_LOCAL|RTLD_NOLOAD);
    int (*read)(id,uint64_t *,size_t)=plugin?
        (int (*)(id,uint64_t *,size_t))dlsym(plugin,"redfin_metal_ordering_statistics"):NULL;
    BOOL valid=read&&!read(device,values,REDFIN_METAL_ORDERING_WORDS);
    if(plugin)dlclose(plugin);return valid;
}
static id<MTLRenderPipelineState> ordering_pipeline(id<MTLDevice> device,id<MTLLibrary> library,
    NSString *vertex,NSString *fragment,MTLVertexDescriptor *layout)
{
    MTLRenderPipelineDescriptor *shape=[MTLRenderPipelineDescriptor new];
    shape.vertexFunction=[library newFunctionWithName:vertex];shape.fragmentFunction=[library newFunctionWithName:fragment];
    shape.vertexDescriptor=layout;shape.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
    NSError *error=nil;id<MTLRenderPipelineState> pipeline=[device newRenderPipelineStateWithDescriptor:shape error:&error];
    if(!pipeline)printf("REDFIN METAL ORDERING PIPELINE: %s\n",error?error.description.UTF8String:"missing");
    [shape.vertexFunction release];[shape.fragmentFunction release];[shape release];return pipeline;
}
static MTLRenderPassDescriptor *ordering_pass(id<MTLTexture> texture)
{
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture=texture;pass.colorAttachments[0].loadAction=MTLLoadActionDontCare;
    pass.colorAttachments[0].storeAction=MTLStoreActionStore;return pass;
}
/* Three changing GPU-only chains in ONE command. The parent contains both a
 * tightly packed converted view and a different padded shadow. Raw reads must
 * resolve the latest writer; the next compute must invalidate both mirrors. */
static BOOL ordering_gpu_chain(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {width=8,height=4,words=32,page=4096,aOffset=64,aPitch=32,bOffset=256,bPitch=48,
          readOffset=7,readPitch=43,readBytes=readOffset+readPitch*height+19,rounds=3};
    id<MTLFunction> affine=[library newFunctionWithName:@"redfin_affine"];
    NSError *error=nil;id<MTLComputePipelineState> compute=affine?[device newComputePipelineStateWithFunction:affine error:&error]:nil;
    id<MTLRenderPipelineState> raster=ordering_pipeline(device,library,@"redfin_vertex",@"redfin_position_sample_fragment",nil);
    id<MTLCommandQueue> queue=[device newCommandQueue];
    id<MTLBuffer> parent=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
    id<MTLBuffer> seed=[device newBufferWithLength:4 options:MTLResourceStorageModeShared];
    id<MTLBuffer> snapshots[rounds]={nil},outputs[rounds]={nil};
    uint8_t *original=parent.contents;BOOL valid=compute&&raster&&queue&&parent&&seed&&original&&!error;
    if(original)memset(original,0xa5,page);
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
    shape.storageMode=MTLStorageModeShared;shape.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;
    id<MTLTexture> a=[parent newTextureWithDescriptor:shape offset:aOffset bytesPerRow:aPitch];
    id<MTLTexture> b=[parent newTextureWithDescriptor:shape offset:bOffset bytesPerRow:bPitch];valid=valid&&a&&b;
    for(unsigned i=0;i<rounds;++i) {
        snapshots[i]=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
        outputs[i]=[device newBufferWithLength:readBytes options:MTLResourceStorageModeShared];
        valid=valid&&snapshots[i]&&outputs[i]&&snapshots[i].contents&&outputs[i].contents;
        if(outputs[i].contents)memset(outputs[i].contents,0xa5,readBytes);
    }
    uint64_t before[REDFIN_METAL_ORDERING_WORDS]={0},after[REDFIN_METAL_ORDERING_WORDS]={0};
    valid=valid&&ordering_statistics(device,before);id<MTLCommandBuffer> command=[queue commandBuffer];
    for(unsigned round=0;valid&&round<rounds;++round) {
        id<MTLBlitCommandEncoder> fill=[command blitCommandEncoder];valid=fill!=nil;
        [fill fillBuffer:seed range:NSMakeRange(0,4) value:(uint8_t)(nonce+round*73)];[fill endEncoding];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];valid=valid&&encoder;
        [encoder setComputePipelineState:compute];[encoder setBuffer:parent offset:aOffset atIndex:0];[encoder setBuffer:seed offset:0 atIndex:1];
        [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(words,1,1)];[encoder endEncoding];
        id<MTLRenderCommandEncoder> draw=[command renderCommandEncoderWithDescriptor:ordering_pass(b)];valid=valid&&draw;
        [draw setRenderPipelineState:raster];[draw setFragmentTexture:a atIndex:0];
        [draw drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[draw endEncoding];
        id<MTLBlitCommandEncoder> copy=[command blitCommandEncoder];valid=valid&&copy;
        [copy copyFromBuffer:parent sourceOffset:0 toBuffer:snapshots[round] destinationOffset:0 size:page];
        [copy copyFromTexture:b sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(width,height,1)
            toBuffer:outputs[round] destinationOffset:readOffset destinationBytesPerRow:readPitch destinationBytesPerImage:0];
        [copy endEncoding];
    }
    if(valid)valid=blit_completed(command,"GPU-compute-shadow-render-alias-download")&&ordering_statistics(device,after)&&
        after[1]==before[1]+1&&after[2]==before[2]&&after[3]>before[3]&&after[4]>=before[4]+rounds;
    for(unsigned round=0;valid&&round<rounds;++round) {
        uint32_t expected[words],live=(uint32_t)(uint8_t)(nonce+round*73)*0x01010101u;
        for(unsigned i=0;i<words;++i)expected[i]=(i^live)*1664525u+1013904223u;
        const uint8_t *pattern=(const uint8_t *)expected,*snapshot=snapshots[round].contents,*out=outputs[round].contents;
        valid=snapshot&&out;
        for(unsigned i=0;valid&&i<page;++i) {
            BOOL inA=i>=aOffset&&i<aOffset+sizeof(expected);
            BOOL inB=i>=bOffset&&(i-bOffset)/bPitch<height&&(i-bOffset)%bPitch<width*4;
            uint8_t wanted=inA?pattern[i-aOffset]:inB?pattern[((i-bOffset)/bPitch)*width*4+(i-bOffset)%bPitch]:0xa5;
            if(snapshot[i]!=wanted) {
                printf("REDFIN METAL ORDERING ALIAS PIXEL: round=%u byte=%u actual=%02x expected=%02x\n",round,i,snapshot[i],wanted);valid=NO;
            }
        }
        for(unsigned i=0;valid&&i<readBytes;++i) {
            BOOL in=i>=readOffset&&(i-readOffset)/readPitch<height&&(i-readOffset)%readPitch<width*4;
            uint8_t wanted=in?pattern[((i-readOffset)/readPitch)*width*4+(i-readOffset)%readPitch]:0xa5;
            if(out[i]!=wanted) {
                printf("REDFIN METAL ORDERING DOWNLOAD PIXEL: round=%u byte=%u actual=%02x expected=%02x\n",round,i,out[i],wanted);valid=NO;
            }
        }
    }
    printf("REDFIN METAL ORDERING GPU: boot=%016llx changing-chains=%u queued=%llu actual-finishes=%llu CPU-drains=%llu deferred=%llu resolves=%llu pixels-guards=%u\n",
        (unsigned long long)nonce,rounds,(unsigned long long)(after[0]-before[0]),(unsigned long long)(after[1]-before[1]),
        (unsigned long long)(after[2]-before[2]),(unsigned long long)(after[3]-before[3]),(unsigned long long)(after[4]-before[4]),valid);
    for(unsigned i=0;i<rounds;++i){[snapshots[i] release];[outputs[i] release];}
    [a release];[b release];[seed release];[parent release];[queue release];[raster release];[compute release];[affine release];return valid;
}
/* The first draw must see freshly GPU-copied valid indices. The second must
 * refuse freshly GPU-filled 65535 before any out-of-range vertex fetch. */
static BOOL ordering_cpu_indices(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    const float vertices[24]={-1,-1,0,0,1,1,1,1, 3,-1,0,0,1,1,1,1, -1,3,0,0,1,1,1,1};
    const uint16_t elements[3]={0,1,2};
    id<MTLBuffer> source=[device newBufferWithBytes:elements length:sizeof(elements) options:MTLResourceStorageModeShared];
    id<MTLBuffer> index=[device newBufferWithLength:32 options:MTLResourceStorageModeShared];
    id<MTLBuffer> vertex=[device newBufferWithBytes:vertices length:sizeof(vertices) options:MTLResourceStorageModeShared];
    if(index.contents)memset(index.contents,0xff,32);
    MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];
    const MTLVertexFormat formats[4]={MTLVertexFormatFloat2,MTLVertexFormatFloat2,MTLVertexFormatFloat4,MTLVertexFormatFloat};
    const NSUInteger offsets[4]={0,8,16,28};
    for(unsigned i=0;i<4;++i){layout.attributes[i].format=formats[i];layout.attributes[i].offset=offsets[i];layout.attributes[i].bufferIndex=0;}
    layout.layouts[0].stride=32;layout.layouts[0].stepFunction=MTLVertexStepFunctionPerVertex;layout.layouts[0].stepRate=1;
    id<MTLRenderPipelineState> pipeline=ordering_pipeline(device,library,@"redfin_stream_vertex",@"redfin_stream_fragment",layout);
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:8 height:4 mipmapped:NO];
    shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;shape.storageMode=MTLStorageModeShared;
    id<MTLTexture> output=[device newTextureWithDescriptor:shape];
    MTLTextureDescriptor *pixel=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];
    pixel.usage=MTLTextureUsageShaderRead;pixel.storageMode=MTLStorageModeShared;id<MTLTexture> input=[device newTextureWithDescriptor:pixel];
    uint32_t white=UINT32_MAX;[input replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&white bytesPerRow:4];
    MTLSamplerDescriptor *sampling=[MTLSamplerDescriptor new];sampling.minFilter=sampling.magFilter=MTLSamplerMinMagFilterNearest;
    id<MTLSamplerState> sampler=[device newSamplerStateWithDescriptor:sampling];[sampling release];
    id<MTLCommandQueue> queue=[device newCommandQueue];BOOL valid=source&&index&&vertex&&pipeline&&output&&input&&sampler&&queue;
    uint64_t before[REDFIN_METAL_ORDERING_WORDS]={0},after[REDFIN_METAL_ORDERING_WORDS]={0};
    unsigned accepted=0,refused=0;
    for(unsigned phase=0;valid&&phase<2;++phase) {
        valid=ordering_statistics(device,before);id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLBlitCommandEncoder> copy=[command blitCommandEncoder];
        if(phase)[copy fillBuffer:index range:NSMakeRange(4,sizeof(elements)) value:0xff];
        else [copy copyFromBuffer:source sourceOffset:0 toBuffer:index destinationOffset:4 size:sizeof(elements)];
        [copy endEncoding];
        id<MTLRenderCommandEncoder> draw=[command renderCommandEncoderWithDescriptor:ordering_pass(output)];
        [draw setRenderPipelineState:pipeline];[draw setVertexBuffer:vertex offset:0 atIndex:0];
        [draw setFragmentTexture:input atIndex:0];[draw setFragmentSamplerState:sampler atIndex:0];
        [draw drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:3 indexType:MTLIndexTypeUInt16 indexBuffer:index indexBufferOffset:4];[draw endEncoding];
        valid=valid&&command&&copy&&draw;[command commit];[command waitUntilCompleted];
        BOOL status=phase?command.status==MTLCommandBufferStatusError&&command.error!=nil:
            command.status==MTLCommandBufferStatusCompleted&&command.error==nil;
        valid=valid&&status&&ordering_statistics(device,after)&&after[2]==before[2]+1&&after[1]==before[1]+(phase?1:2);
        if(!phase&&valid) {
            uint8_t pixels[128];memset(pixels,0,sizeof(pixels));[output getBytes:pixels bytesPerRow:32 fromRegion:MTLRegionMake2D(0,0,8,4) mipmapLevel:0];
            for(unsigned i=0;valid&&i<sizeof(pixels);++i)valid=pixels[i]==255;
        }
        if(phase)refused=valid;else accepted=valid;
    }
    printf("REDFIN METAL ORDERING INDEX: boot=%016llx GPU-copy-valid-pixels=%u GPU-fill-invalid-refused=%u actual-CPU-fences=%u\n",
        (unsigned long long)nonce,accepted,refused,valid);
    [queue release];[sampler release];[input release];[output release];[pipeline release];[vertex release];[index release];[source release];return valid;
}
/* Two different GPU-written float4 values reuse the same unaligned UBO. Each
 * CPU upload sees its own value; previously encoded native draws keep it. */
static BOOL ordering_cpu_constants(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {page=4096,offset=64,pitch=64,width=8,height=4,rounds=2};
    float colors[rounds][4]={{0.125f,0.375f,0.625f,1},{0.75f,0.5f,0.25f,1}};
    if(nonce&1){colors[0][0]=0.25f;colors[1][2]=0.875f;}
    id<MTLBuffer> values[rounds]={nil},parents[rounds]={nil};id<MTLTexture> targets[rounds]={nil};
    id<MTLBuffer> uniform=[device newBufferWithLength:64 options:MTLResourceStorageModeShared];
    if(uniform.contents)memset(uniform.contents,0xa5,64);
    MTLTextureDescriptor *shape=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:NO];
    shape.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;shape.storageMode=MTLStorageModeShared;
    id<MTLRenderPipelineState> pipeline=ordering_pipeline(device,library,@"redfin_vertex",@"redfin_batch_fragment",nil);
    id<MTLCommandQueue> queue=[device newCommandQueue];BOOL valid=uniform&&pipeline&&queue;
    for(unsigned i=0;i<rounds;++i) {
        values[i]=[device newBufferWithBytes:colors[i] length:sizeof(colors[i]) options:MTLResourceStorageModeShared];
        parents[i]=[device newBufferWithLength:page options:MTLResourceStorageModeShared];
        if(parents[i].contents)memset(parents[i].contents,0xa5,page);
        targets[i]=[parents[i] newTextureWithDescriptor:shape offset:offset bytesPerRow:pitch];
        valid=valid&&values[i]&&parents[i]&&parents[i].contents&&targets[i];
    }
    uint64_t before[REDFIN_METAL_ORDERING_WORDS]={0},after[REDFIN_METAL_ORDERING_WORDS]={0};
    valid=valid&&ordering_statistics(device,before);id<MTLCommandBuffer> command=[queue commandBuffer];
    for(unsigned i=0;valid&&i<rounds;++i) {
        id<MTLBlitCommandEncoder> copy=[command blitCommandEncoder];
        [copy copyFromBuffer:values[i] sourceOffset:0 toBuffer:uniform destinationOffset:4 size:sizeof(colors[i])];[copy endEncoding];
        id<MTLRenderCommandEncoder> draw=[command renderCommandEncoderWithDescriptor:ordering_pass(targets[i])];
        [draw setRenderPipelineState:pipeline];[draw setFragmentBuffer:uniform offset:4 atIndex:0];
        [draw drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[draw endEncoding];valid=command&&copy&&draw;
    }
    if(valid)valid=blit_completed(command,"GPU-written-unaligned-immutable-UBO")&&ordering_statistics(device,after)&&
        after[2]==before[2]+rounds&&after[1]==before[1]+rounds+1;
    for(unsigned round=0;valid&&round<rounds;++round) {
        const uint8_t *data=parents[round].contents;valid=data!=NULL;
        for(unsigned i=0;valid&&i<page;++i) {
            BOOL in=i>=offset&&(i-offset)/pitch<height&&(i-offset)%pitch<width*4;
            int wanted=in?(int)lroundf(colors[round][(i-offset)%4]*255):0xa5;
            if(abs((int)data[i]-wanted)>(in?1:0)) {
                printf("REDFIN METAL ORDERING UBO PIXEL: round=%u byte=%u actual=%u expected=%d\n",round,i,data[i],wanted);valid=NO;
            }
        }
    }
    printf("REDFIN METAL ORDERING UBO: boot=%016llx GPU-written-values=%u CPU-drains=%llu actual-finishes=%llu pixels-guards=%u\n",
        (unsigned long long)nonce,rounds,(unsigned long long)(after[2]-before[2]),(unsigned long long)(after[1]-before[1]),valid);
    for(unsigned i=0;i<rounds;++i){[targets[i] release];[parents[i] release];[values[i] release];}
    [queue release];[pipeline release];[uniform release];return valid;
}
static BOOL ordering_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    BOOL gpu=ordering_gpu_chain(device,library,nonce);
    BOOL indices=gpu&&ordering_cpu_indices(device,library,nonce);
    BOOL constants=indices&&ordering_cpu_constants(device,library,nonce);
    printf("REDFIN METAL ORDERING RESULT: boot=%016llx GPU-ordered-pixels-guards=%u CPU-index-validation=%u CPU-unaligned-constants=%u\n",
        (unsigned long long)nonce,gpu,indices,constants);return gpu&&indices&&constants;
}
