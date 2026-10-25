/* SPDX-License-Identifier: MIT */
/* Two real vertex streams, four attributes, nonzero binding/index offsets,
 * base instance, indexed strips, varying UV/tint and native nearest/linear sampling. */
static uint32_t vertex_pattern(unsigned x,unsigned y)
{return 0xff000000u|((8+x*8)<<16)|((8+y*8)<<8)|(16+(x^y)*4);}
static BOOL render_vertex_streams(id<MTLDevice> device,id<MTLLibrary> library)
{
    IOSurfaceRef source=raster_surface(16,16,64,16384),destination=raster_surface(16,16,64,16384);
    id<MTLTexture> input=raster_texture(device,source),output=raster_texture(device,destination);
    BOOL valid=source&&destination&&input&&output;uint32_t seed=0;
    if(valid) {
        valid=IOSurfaceLock(source,0,&seed)==KERN_SUCCESS;
        if(valid) {
            uint32_t *pixels=IOSurfaceGetBaseAddress(source);valid=pixels!=NULL;
            for(unsigned y=0;valid&&y<16;++y)for(unsigned x=0;x<16;++x)pixels[y*16+x]=vertex_pattern(x,y);
            if(IOSurfaceUnlock(source,0,&seed)!=KERN_SUCCESS)valid=NO;
        }
    }
    uint8_t vertices[128],instances[128],indices[32];memset(vertices,0xa5,sizeof(vertices));
    memset(instances,0xa5,sizeof(instances));memset(indices,0xa5,sizeof(indices));
    const float data[16]={-1,1,0,0, -1,-1,0,1, 1,1,1,0, 1,-1,1,1};
    const float colors[8]={0,0,0,0,1,1,1,1};const uint16_t elements[4]={0,1,2,3};
    memcpy(vertices+64,data,sizeof(data));memcpy(instances+64,colors,sizeof(colors));memcpy(indices+16,elements,sizeof(elements));
    id<MTLBuffer> vertex=[device newBufferWithBytes:vertices length:sizeof(vertices) options:MTLResourceStorageModeShared];
    id<MTLBuffer> instance=[device newBufferWithBytes:instances length:sizeof(instances) options:MTLResourceStorageModeShared];
    id<MTLBuffer> index=[device newBufferWithBytes:indices length:sizeof(indices) options:MTLResourceStorageModeShared];
    MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];
    layout.attributes[0].format=MTLVertexFormatFloat2;layout.attributes[0].offset=0;layout.attributes[0].bufferIndex=1;
    layout.attributes[1].format=MTLVertexFormatFloat2;layout.attributes[1].offset=8;layout.attributes[1].bufferIndex=1;
    layout.attributes[2].format=MTLVertexFormatFloat4;layout.attributes[2].offset=0;layout.attributes[2].bufferIndex=0;
    layout.attributes[3].format=MTLVertexFormatFloat;layout.attributes[3].offset=12;layout.attributes[3].bufferIndex=0;
    layout.layouts[0].stride=16;layout.layouts[0].stepFunction=MTLVertexStepFunctionPerInstance;layout.layouts[0].stepRate=1;
    layout.layouts[1].stride=16;layout.layouts[1].stepFunction=MTLVertexStepFunctionPerVertex;layout.layouts[1].stepRate=1;
    MTLRenderPipelineDescriptor *shape=[MTLRenderPipelineDescriptor new];shape.vertexDescriptor=layout;
    shape.vertexFunction=[library newFunctionWithName:@"redfin_stream_vertex"];
    shape.fragmentFunction=[library newFunctionWithName:@"redfin_stream_fragment"];
    shape.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    NSError *error=nil;id<MTLRenderPipelineState> pipeline=[device newRenderPipelineStateWithDescriptor:shape error:&error];
    if(!pipeline)printf("REDFIN METAL VERTEX: pipeline error=%s\n",error?error.description.UTF8String:"none");
    [shape.vertexFunction release];[shape.fragmentFunction release];[shape release];
    id<MTLCommandQueue> queue=[device newCommandQueue];
    valid=valid&&vertex&&instance&&index&&pipeline&&queue;
    for(unsigned round=0;valid&&round<2;++round) {
        void *memory=[instance contents];valid=memory!=NULL;
        if(!valid)break;
        float *tint=(float *)((uint8_t *)memory+80);
        tint[0]=round?0.5:1;tint[1]=1;tint[2]=round?0.25:1;tint[3]=1;
        MTLSamplerDescriptor *sampling=[MTLSamplerDescriptor new];
        sampling.minFilter=sampling.magFilter=round?MTLSamplerMinMagFilterLinear:MTLSamplerMinMagFilterNearest;
        sampling.sAddressMode=sampling.tAddressMode=MTLSamplerAddressModeClampToEdge;
        id<MTLSamplerState> sampler=[device newSamplerStateWithDescriptor:sampling];[sampling release];
        id<MTLCommandBuffer> command=[queue commandBuffer];
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=output;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
        id<MTLRenderCommandEncoder> encoder=sampler?[command renderCommandEncoderWithDescriptor:pass]:nil;valid=encoder!=nil;
        if(valid) {
            [encoder setRenderPipelineState:pipeline];[encoder setVertexBuffer:instance offset:64 atIndex:0];
            [encoder setVertexBuffer:vertex offset:64 atIndex:1];[encoder setFragmentTexture:input atIndex:0];
            [encoder setFragmentSamplerState:sampler atIndex:0];
            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangleStrip indexCount:4 indexType:MTLIndexTypeUInt16
                indexBuffer:index indexBufferOffset:16 instanceCount:1 baseVertex:0 baseInstance:1];
            [encoder endEncoding];valid=raster_complete(command,"vertex-stream-varying-sample");
        }
        if(valid) {
            valid=IOSurfaceLock(destination,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
            if(valid) {
                const uint32_t *pixels=IOSurfaceGetBaseAddress(destination);valid=pixels!=NULL;
                for(unsigned y=0;valid&&y<16;++y)for(unsigned x=0;valid&&x<16;++x) {
                    uint32_t expected=vertex_pattern(x,y),actual=pixels[y*16+x];
                    unsigned r=(expected>>16)&255,g=(expected>>8)&255,b=expected&255;
                    if(round){r=(r+1)/2;b=(b+2)/4;}
                    if(abs((int)((actual>>16)&255)-(int)r)>1||abs((int)((actual>>8)&255)-(int)g)>1||
                       abs((int)(actual&255)-(int)b)>1||(actual>>24)!=255) {
                        printf("REDFIN METAL VERTEX PIXEL: round=%u x=%u y=%u actual=%08x expected-rgb=%u/%u/%u\n",round,x,y,actual,r,g,b);valid=NO;
                    }
                }
                for(unsigned at=1024;valid&&at<16384;++at)valid=((const uint8_t *)pixels)[at]==0xa5;
                if(IOSurfaceUnlock(destination,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
            }
        }
        printf("REDFIN METAL VERTEX RESULT: round=%u streams=2 attributes=4 indexed-strip=1 base-instance=1 linear-sampler=%u actual-pixels-and-guards=%u\n",round,round,valid);
        [sampler release];
    }
    [queue release];[pipeline release];[vertex release];[instance release];[index release];[input release];[output release];
    if(source)CFRelease(source);if(destination)CFRelease(destination);return valid;
}
