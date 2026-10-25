/* SPDX-License-Identifier: MIT */
static BOOL constants_dispatch(id<MTLDevice> device,id<MTLFunction> function,uint32_t seed,
    const float vector[4],const uint8_t opcodes[3],BOOL defined)
{
    NSError *error=nil;id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:function error:&error];
    id<MTLArgumentEncoder> arguments=[function newArgumentEncoderWithBufferIndex:0];
    id<MTLBuffer> table=arguments?[device newBufferWithLength:arguments.encodedLength options:MTLResourceStorageModeShared]:nil;
    id<MTLBuffer> output=[device newBufferWithLength:256 options:MTLResourceStorageModeShared];
    id<MTLCommandQueue> queue=[device newCommandQueue];BOOL valid=pipeline&&arguments&&table&&output&&queue;
    if(valid) {
        memset(output.contents,0xa5,256);[arguments setArgumentBuffer:table offset:0];[arguments setBuffer:output offset:0 atIndex:0];
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        valid=command&&encoder;if(encoder) {
            [encoder setComputePipelineState:pipeline];[encoder setBuffer:table offset:0 atIndex:0];
            [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(32,1,1)];[encoder endEncoding];
            valid=valid&&blit_completed(command,"specialized-argument-buffer-compute");
        }
        uint32_t packed=opcodes[0]|((uint32_t)opcodes[1]<<8)|((uint32_t)opcodes[2]<<16);
        for(unsigned i=0;valid&&i<16;++i) {
            uint32_t bits;memcpy(&bits,vector+(i&3),4);
            uint32_t expected=seed^bits^packed^(defined?0x4321u:0x1234u)^(i*1664525u);
            if(((uint32_t *)output.contents)[i]!=expected) {
                printf("REDFIN METAL CONSTANT PIXEL: i=%u actual=%08x expected=%08x defined=%u\n",i,((uint32_t *)output.contents)[i],expected,defined);valid=NO;
            }
        }
        for(unsigned i=64;valid&&i<256;++i)valid=((uint8_t *)output.contents)[i]==0xa5;
    }
    if(!valid&&error)printf("REDFIN METAL CONSTANT COMPUTE: %s\n",error.description.UTF8String);
    [queue release];[output release];[table release];[arguments release];[pipeline release];return valid;
}
static BOOL constants_raster(id<MTLDevice> device,id<MTLLibrary> library)
{
    float small[4]={0.5f,0.5f,0,1},color[4]={0.75f,0.25f,0.5f,1};
    MTLFunctionConstantValues *values=[[MTLFunctionConstantValues alloc]init];NSError *error=nil;
    [values setConstantValue:small type:MTLDataTypeFloat4 atIndex:41];
    id<MTLFunction> vertex=[library newFunctionWithName:@"redfin_constants_vertex" constantValues:values error:&error];
    [values setConstantValue:color type:MTLDataTypeFloat4 atIndex:41];
    id<MTLFunction> fragment=[library newFunctionWithName:@"redfin_constants_fragment" constantValues:values error:&error];
    [values reset];MTLRenderPipelineDescriptor *shape=[[MTLRenderPipelineDescriptor alloc]init];shape.vertexFunction=vertex;shape.fragmentFunction=fragment;
    shape.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    id<MTLRenderPipelineState> pipeline=vertex&&fragment?[device newRenderPipelineStateWithDescriptor:shape error:&error]:nil;
    IOSurfaceRef surface=raster_surface(32,16,128,16384);id<MTLTexture> output=raster_texture(device,surface);
    id<MTLCommandQueue> queue=[device newCommandQueue];BOOL valid=pipeline&&surface&&output&&queue;
    if(valid) {
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=output;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        valid=command&&encoder;if(encoder) {
            [encoder setRenderPipelineState:pipeline];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];[encoder endEncoding];
            valid=valid&&raster_complete(command,"independent-vertex-fragment-function-constants");
        }
        uint32_t seed=0;if(valid) {
            valid=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
            if(valid) {
                const uint8_t *pixels=IOSurfaceGetBaseAddress(surface);valid=pixels!=NULL;
                for(unsigned y=0;valid&&y<16;++y)for(unsigned x=0;valid&&x<32;++x) {
                    BOOL inside=x>=8&&x<24&&y>=4&&y<12;const uint8_t *p=pixels+y*128+x*4;
                    const unsigned want[4]={inside?128:0,inside?64:0,inside?191:0,inside?255:0};
                    for(unsigned c=0;c<4;++c)if(abs((int)p[c]-(int)want[c])>1)valid=NO;
                }
                for(unsigned at=2048;valid&&at<16384;++at)valid=pixels[at]==0xa5;
                if(IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
            }
        }
    }
    if(!valid&&error)printf("REDFIN METAL CONSTANT RASTER: %s\n",error.description.UTF8String);
    [queue release];[output release];if(surface)CFRelease(surface);[pipeline release];[shape release];[fragment release];[vertex release];[values release];return valid;
}
static void constants_values(MTLFunctionConstantValues *values,uint32_t seed,const float vector[4],const uint8_t opcodes[3],BOOL defined)
{
    [values reset];[values setConstantValues:&seed type:MTLDataTypeUInt withRange:NSMakeRange(37,1)];
    [values setConstantValue:vector type:MTLDataTypeFloat4 withName:@"redfin_fc_vector"];
    [values setConstantValue:opcodes type:MTLDataTypeUChar3 atIndex:58];
    if(defined){uint32_t zero=0;[values setConstantValue:&zero type:MTLDataTypeUInt atIndex:59];}
}
static BOOL function_constants_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    float a[4]={0.25f,0.5f,0.75f,1},b[4]={1,0.75f,0.5f,0.25f};
    uint8_t opsA[3]={3,17,71},opsB[3]={101,29,7};uint32_t seedA=(uint32_t)nonce,seedB=seedA^0x921fab3du;
    MTLFunctionConstantValues *values=[[MTLFunctionConstantValues alloc]init];NSError *error=nil;
    id missing=[library newFunctionWithName:@"redfin_constants" constantValues:values error:&error];
    BOOL refused=!missing&&error!=nil;[missing release];
    constants_values(values,seedA,a,opsA,NO);
    id<MTLFunction> first=[library newFunctionWithName:@"redfin_constants" constantValues:values error:&error];
    constants_values(values,seedB,b,opsB,YES);
    id<MTLFunction> second=[library newFunctionWithName:@"redfin_constants" constantValues:values error:&error];
    __block id asynchronous=nil;dispatch_semaphore_t completed=dispatch_semaphore_create(0);
    [library newFunctionWithName:@"redfin_constants" constantValues:values completionHandler:^(id function,NSError *failure){
        if(!failure)asynchronous=[function retain];dispatch_semaphore_signal(completed);
    }];
    constants_values(values,seedA,a,opsA,NO);
    MTLFunctionDescriptor *descriptor=[MTLFunctionDescriptor functionDescriptor];descriptor.name=@"redfin_constants";descriptor.constantValues=values;
    id<MTLFunction> described=[library newFunctionWithDescriptor:descriptor error:&error];[values reset];
    BOOL arrived=!dispatch_semaphore_wait(completed,dispatch_time(DISPATCH_TIME_NOW,10*NSEC_PER_SEC));
    BOOL separate=first&&second&&first!=second;
    if(separate) {
        SEL hash=sel_getUid("functionConstantSpecializationHash");
        const void *x=((const void *(*)(id,SEL))objc_msgSend)(first,hash),*y=((const void *(*)(id,SEL))objc_msgSend)(second,hash);
        separate=x&&y&&memcmp(x,y,32)!=0;
    }
    BOOL compute=separate&&arrived&&asynchronous&&described;
    if(compute)compute=constants_dispatch(device,first,seedA,a,opsA,NO)&&
        constants_dispatch(device,second,seedB,b,opsB,YES)&&constants_dispatch(device,first,seedA,a,opsA,NO)&&
        constants_dispatch(device,asynchronous,seedB,b,opsB,YES)&&constants_dispatch(device,described,seedA,a,opsA,NO);
    BOOL raster=constants_raster(device,library);
    printf("REDFIN METAL CONSTANT RESULT: boot=%016llx required-refusal=%u distinct-native-hashes=%u immutable-vectors-optional-zero-argbuf-async-descriptor-compute=%u separate-vertex-fragment-pixels-guards=%u\n",
        (unsigned long long)nonce,refused,separate,compute,raster);
    if(arrived){[asynchronous release];dispatch_release(completed);}
    [described release];[second release];[first release];[values release];return refused&&separate&&compute&&raster;
}
