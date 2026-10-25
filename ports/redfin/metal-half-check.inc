/* SPDX-License-Identifier: MIT */
/* Native half storage/colour exports and mixed-width stage interfaces.
 * Every result comes from actual offscreen A620 pixels and untouched guards.
 */
static BOOL half_surface_pixels(IOSurfaceRef surface,const unsigned expected[4],
    int stream_round,const char *stage)
{
    uint32_t seed=0;
    if(!surface||IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)return NO;
    const uint8_t *bytes=IOSurfaceGetBaseAddress(surface);BOOL valid=bytes!=NULL;
    for(unsigned y=0;valid&&y<16;++y)for(unsigned x=0;valid&&x<16;++x) {
        unsigned want[4];memcpy(want,expected,sizeof(want));
        if(stream_round>=0) {
            uint32_t pattern=vertex_pattern(x,y);
            unsigned r=(pattern>>16)&255,g=(pattern>>8)&255,b=pattern&255;
            want[0]=stream_round?(r+2)/4:(r+1)/2;
            want[1]=stream_round?(g+2)/4:(g+1)/2;
            want[2]=stream_round?(b+4)/8:(b+2)/4;want[3]=stream_round?128:255;
        }
        uint32_t pixel;memcpy(&pixel,bytes+(y*16+x)*4,4);
        unsigned actual[4]={(pixel>>16)&255,(pixel>>8)&255,pixel&255,pixel>>24};
        for(unsigned channel=0;valid&&channel<4;++channel)if(abs((int)actual[channel]-(int)want[channel])>1) {
            printf("REDFIN METAL HALF PIXEL: stage=%s round=%d x=%u y=%u channel=%u actual=%u expected=%u\n",
                stage,stream_round,x,y,channel,actual[channel],want[channel]);valid=NO;
        }
    }
    for(unsigned at=1024;valid&&at<16384;++at)if(bytes[at]!=0xa5) {
        printf("REDFIN METAL HALF GUARD: stage=%s offset=%u\n",stage,at);valid=NO;
    }
    if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
    return valid;
}

static BOOL half_render_storage(id<MTLDevice> device,id<MTLLibrary> library,BOOL outcomes[4])
{
    IOSurfaceRef surfaces[2]={raster_surface(16,16,64,16384),raster_surface(16,16,64,16384)};
    id<MTLTexture> textures[2]={raster_texture(device,surfaces[0]),raster_texture(device,surfaces[1])};
    uint8_t packed_bytes[128],color_bytes[128],scale_bytes[128];
    memset(packed_bytes,0xa5,sizeof(packed_bytes));memset(color_bytes,0xa5,sizeof(color_bytes));
    memset(scale_bytes,0xa5,sizeof(scale_bytes));
    /* Actual MSL layout: half3 consumes eight bytes, scalar at8, packed_half3
     * at10 and final scalar at16; half3's spare lane is an explicit NaN.
     */
    const uint16_t packed[12]={0x3000,0x3400,0x3a00,0x7e00,0x3600,0x3400,
        0x3a00,0x3900,0x3b00,0xa5a5,0xa5a5,0xa5a5};
    const uint16_t color[4]={0x3000,0x3600,0x3900,0x3b00};
    const uint16_t scale[4]={0x3800,0x3c00,0x3400,0x3c00};
    memcpy(packed_bytes+64,packed,sizeof(packed));memcpy(color_bytes+64,color,sizeof(color));
    memcpy(scale_bytes+64,scale,sizeof(scale));
    id<MTLBuffer> buffers[3]={
        [device newBufferWithBytes:packed_bytes length:sizeof(packed_bytes) options:MTLResourceStorageModeShared],
        [device newBufferWithBytes:color_bytes length:sizeof(color_bytes) options:MTLResourceStorageModeShared],
        [device newBufferWithBytes:scale_bytes length:sizeof(scale_bytes) options:MTLResourceStorageModeShared]};
    id<MTLCommandQueue> queue=[device newCommandQueue];
    NSString *names[4]={@"redfin_half_constant",@"redfin_half_uniform",@"redfin_half_mrt",@"redfin_half_fetch"};
    const unsigned direct[4]={32,96,159,223},swapped[4]={159,96,32,223},fetched[4]={80,96,8,223};
    BOOL ready=textures[0]&&textures[1]&&buffers[0]&&buffers[1]&&buffers[2]&&queue;
    for(unsigned stage=0;stage<4;++stage) {
        @autoreleasepool {
            unsigned count=stage>=2?2:1;
            id<MTLRenderPipelineState> pipeline=ready?raster_pipeline(device,library,names[stage],count,stage==3):nil;
            id<MTLCommandBuffer> command=pipeline?[queue commandBuffer]:nil;
            MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
            for(unsigned i=0;i<count;++i) {
                pass.colorAttachments[i].texture=textures[i];pass.colorAttachments[i].loadAction=MTLLoadActionClear;
                pass.colorAttachments[i].storeAction=MTLStoreActionStore;
                pass.colorAttachments[i].clearColor=stage==3&&i?
                    MTLClearColorMake(0.625,0.375,0.125,0.875):MTLClearColorMake(0,0,0,0);
            }
            id<MTLRenderCommandEncoder> encoder=command?[command renderCommandEncoderWithDescriptor:pass]:nil;
            BOOL valid=encoder!=nil;
            if(valid) {
                [encoder setRenderPipelineState:pipeline];
                if(stage)[encoder setFragmentBuffer:buffers[stage-1] offset:64 atIndex:1];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                [encoder endEncoding];valid=raster_complete(command,names[stage].UTF8String);
            }
            if(valid)valid=half_surface_pixels(surfaces[0],stage==3?fetched:direct,-1,names[stage].UTF8String);
            if(valid&&count==2)valid=half_surface_pixels(surfaces[1],swapped,-1,"half-mrt-or-fetch-source");
            outcomes[stage]=valid;[pipeline release];
        }
    }
    /* Storage is read-only to these shaders, including every prefix/tail. */
    const uint8_t *expected[3]={packed_bytes,color_bytes,scale_bytes};
    BOOL unchanged=ready;
    for(unsigned i=0;unchanged&&i<3;++i)unchanged=[buffers[i] contents]&&
        !memcmp([buffers[i] contents],expected[i],128);
    [queue release];for(unsigned i=0;i<3;++i)[buffers[i] release];
    for(unsigned i=0;i<2;++i){[textures[i] release];if(surfaces[i])CFRelease(surfaces[i]);}
    return unchanged;
}

static BOOL half_render_streams(id<MTLDevice> device,id<MTLLibrary> library)
{
    IOSurfaceRef source=raster_surface(16,16,64,16384),destination=raster_surface(16,16,64,16384);
    id<MTLTexture> input=raster_texture(device,source),output=raster_texture(device,destination);
    BOOL valid=input&&output;uint32_t seed=0;
    if(valid) {
        valid=IOSurfaceLock(source,0,&seed)==KERN_SUCCESS;
        if(valid) {
            uint32_t *pixels=IOSurfaceGetBaseAddress(source);valid=pixels!=NULL;
            for(unsigned y=0;valid&&y<16;++y)for(unsigned x=0;x<16;++x)pixels[y*16+x]=vertex_pattern(x,y);
            if(IOSurfaceUnlock(source,0,&seed)!=KERN_SUCCESS)valid=NO;
        }
    }
    uint8_t bytes[256];memset(bytes,0xa5,sizeof(bytes));
    const float positions[8]={-1,1,-1,-1,1,1,1,-1};
    const uint16_t uv[8]={0,0,0,0x3c00,0x3c00,0,0x3c00,0x3c00};
    const uint16_t tint[4]={0x3800,0x3c00,0x3400,0x3c00},flat[4]={0x3c00,0x3800,0x3c00,0x3c00};
    for(unsigned i=0;i<4;++i) {
        uint8_t *v=bytes+64+i*32;uint16_t mask=0x3c00;
        memcpy(v,positions+i*2,8);memcpy(v+8,uv+i*2,4);memcpy(v+12,tint,8);
        memcpy(v+20,flat,8);memcpy(v+28,&mask,2);
    }
    id<MTLBuffer> vertex=[device newBufferWithBytes:bytes length:sizeof(bytes) options:MTLResourceStorageModeShared];
    MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];
    const MTLVertexFormat formats[5]={MTLVertexFormatFloat2,MTLVertexFormatHalf2,MTLVertexFormatHalf4,
        MTLVertexFormatHalf4,MTLVertexFormatHalf};const unsigned offsets[5]={0,8,12,20,28};
    for(unsigned i=0;i<5;++i) {
        layout.attributes[i].format=formats[i];layout.attributes[i].offset=offsets[i];layout.attributes[i].bufferIndex=1;
    }
    layout.layouts[1].stride=32;layout.layouts[1].stepFunction=MTLVertexStepFunctionPerVertex;layout.layouts[1].stepRate=1;
    MTLRenderPipelineDescriptor *shape=[MTLRenderPipelineDescriptor new];shape.vertexDescriptor=layout;
    shape.vertexFunction=[library newFunctionWithName:@"redfin_half_vertex"];
    shape.fragmentFunction=[library newFunctionWithName:@"redfin_half_stream_fragment"];
    shape.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    NSError *error=nil;id<MTLRenderPipelineState> pipeline=valid?[device newRenderPipelineStateWithDescriptor:shape error:&error]:nil;
    if(!pipeline)printf("REDFIN METAL HALF PIPELINE: error=%s\n",error?error.description.UTF8String:"missing source/target");
    [shape.vertexFunction release];[shape.fragmentFunction release];[shape release];
    MTLSamplerDescriptor *sampling=[MTLSamplerDescriptor new];sampling.minFilter=sampling.magFilter=MTLSamplerMinMagFilterNearest;
    sampling.sAddressMode=sampling.tAddressMode=MTLSamplerAddressModeClampToEdge;
    id<MTLSamplerState> sampler=[device newSamplerStateWithDescriptor:sampling];[sampling release];
    id<MTLCommandQueue> queue=[device newCommandQueue];valid=valid&&vertex&&pipeline&&sampler&&queue;
    for(unsigned round=0;valid&&round<2;++round) {
        @autoreleasepool {
            uint8_t *mapped=[vertex contents];valid=mapped!=NULL;
            if(!valid)break;
            for(unsigned i=0;i<4;++i){uint16_t mask=round?0x3800:0x3c00;memcpy(mapped+64+i*32+28,&mask,2);memcpy(bytes+64+i*32+28,&mask,2);}
            id<MTLCommandBuffer> command=[queue commandBuffer];
            MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture=output;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
            pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
            id<MTLRenderCommandEncoder> encoder=command?[command renderCommandEncoderWithDescriptor:pass]:nil;valid=encoder!=nil;
            if(valid) {
                [encoder setRenderPipelineState:pipeline];[encoder setVertexBuffer:vertex offset:64 atIndex:1];
                [encoder setFragmentTexture:input atIndex:0];[encoder setFragmentSamplerState:sampler atIndex:0];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];[encoder endEncoding];
                valid=raster_complete(command,"half-attributes-varyings-texture");
            }
            const unsigned unused[4]={0};
            if(valid)valid=half_surface_pixels(destination,unused,(int)round,"half-attributes-varyings-texture");
            if(valid)valid=!memcmp(mapped,bytes,sizeof(bytes));
        }
    }
    /* The sampled original IOSurface and all its trailing bytes remain exact. */
    if(valid) {
        valid=IOSurfaceLock(source,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
        if(valid) {
            const uint32_t *pixels=IOSurfaceGetBaseAddress(source);valid=pixels!=NULL;
            for(unsigned y=0;valid&&y<16;++y)for(unsigned x=0;valid&&x<16;++x)valid=pixels[y*16+x]==vertex_pattern(x,y);
            for(unsigned i=1024;valid&&i<16384;++i)valid=((const uint8_t *)pixels)[i]==0xa5;
            if(IOSurfaceUnlock(source,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
        }
    }
    [queue release];[sampler release];[pipeline release];[vertex release];[input release];[output release];
    if(source)CFRelease(source);if(destination)CFRelease(destination);return valid;
}

static BOOL half_raster_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    BOOL outcomes[4]={NO,NO,NO,NO};BOOL readonly=half_render_storage(device,library,outcomes);
    BOOL storage=readonly&&outcomes[0]&&outcomes[1]&&outcomes[2]&&outcomes[3];
    BOOL varying=half_render_streams(device,library);
    printf("REDFIN METAL HALF RESULT: boot=%016llx constant-half-colour=%u packed-half3-ubo=%u half-mrt=%u half-fetch=%u storage-readonly=%u half-attributes-smooth-flat-noperspective-sampler-two-rounds-pixels-guards=%u visible-overlay=0\n",
        (unsigned long long)nonce,outcomes[0],outcomes[1],outcomes[2],outcomes[3],readonly,varying);
    return storage&&varying;
}
