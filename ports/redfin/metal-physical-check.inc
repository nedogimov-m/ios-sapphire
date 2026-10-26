/* SPDX-License-Identifier: MIT
 * Real offscreen public Metal work. Two commands commit before either wait;
 * full values/guards decide success, while native post-doorbell records alone
 * decide whether two physical submissions actually remained pending.
 */
static BOOL physical_pending_native(id<MTLDevice> device,id<MTLLibrary> library,uint64_t nonce)
{
    enum {words=1<<18,first=16,total=words+32,rounds=4};
    id<MTLFunction> function=[library newFunctionWithName:@"redfin_physical_pending"];NSError *error=nil;
    id<MTLComputePipelineState> pipeline=function?[device newComputePipelineStateWithFunction:function error:&error]:nil;
    id<MTLCommandQueue> queue=[device newCommandQueue];
    id<MTLBuffer> output[2]={nil},parameters[2]={nil};uint32_t *maps[2]={NULL},*uniforms[2]={NULL};
    BOOL valid=pipeline&&!error&&queue;unsigned passed=0;
    for(unsigned i=0;i<2;++i) {
        output[i]=[device newBufferWithLength:(uint64_t)total*4 options:MTLResourceStorageModeShared];
        parameters[i]=[device newBufferWithLength:8 options:MTLResourceStorageModeShared];
        maps[i]=output[i].contents;uniforms[i]=parameters[i].contents;
        valid=valid&&output[i]&&parameters[i]&&maps[i]&&uniforms[i];
    }
    for(unsigned round=0;valid&&round<rounds;++round) {
        unsigned count=round?words:64,iterations=round?256:16;
        uint32_t seeds[2]={(uint32_t)nonce^(round*0x1f123bb5u),(uint32_t)(nonce>>32)^(round*0x9e3779b9u)^0x6a09e667u};
        id<MTLCommandBuffer> commands[2]={nil};
        for(unsigned i=0;valid&&i<2;++i) {
            memset(maps[i],0xa5,(uint64_t)total*4);uniforms[i][0]=seeds[i];uniforms[i][1]=iterations;
            commands[i]=[queue commandBuffer];id<MTLComputeCommandEncoder> encoder=[commands[i] computeCommandEncoder];
            valid=commands[i]&&encoder;
            [encoder setComputePipelineState:pipeline];[encoder setBuffer:output[i] offset:first*4 atIndex:0];
            [encoder setBuffer:parameters[i] offset:0 atIndex:1];
            [encoder dispatchThreadgroups:MTLSizeMake(count/64,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];[encoder endEncoding];
        }
        if(valid) {
            [commands[0] commit];[commands[1] commit];
            [commands[1] waitUntilCompleted];[commands[0] waitUntilCompleted];
            valid=commands[0].status==MTLCommandBufferStatusCompleted&&!commands[0].error&&
                commands[1].status==MTLCommandBufferStatusCompleted&&!commands[1].error;
            if(!valid)printf("REDFIN METAL PHYSICAL ERROR: round=%u status=%lu/%lu code=%ld/%ld\n",round,
                (unsigned long)commands[0].status,(unsigned long)commands[1].status,
                (long)commands[0].error.code,(long)commands[1].error.code);
        }
        /* Affine composition gives an independent O(1) expectation per word,
         * avoiding billions of CPU iterations during the actual GPU probe. */
        uint32_t scale=1,bias=0;
        for(unsigned i=0;i<iterations;++i){scale*=1664525u;bias=bias*1664525u+1013904223u;}
        for(unsigned i=0;valid&&i<2;++i) {
            for(unsigned word=0;valid&&word<total;++word) {
                uint32_t wanted=word>=first&&word<first+count?scale*((word-first)^seeds[i])+bias:0xa5a5a5a5u;
                if(maps[i][word]!=wanted){printf("REDFIN METAL PHYSICAL PIXEL: round=%u command=%u word=%u got=%08x expected=%08x\n",round,i,word,maps[i][word],wanted);valid=NO;}
            }
            valid=valid&&uniforms[i][0]==seeds[i]&&uniforms[i][1]==iterations;
        }
        printf("REDFIN METAL PHYSICAL CASE: boot=%016llx round=%u threads=%u iterations=%u two-commits-before-wait=1 actual-values-source-output-guards=%u\n",
            (unsigned long long)nonce,round,count,iterations,valid);
        if(valid)++passed;
    }
    printf("REDFIN METAL PHYSICAL RESULT: boot=%016llx bounded-long-compute-pairs=%u warmup-pairs=1 passed=%u actual-two-pending-requires-native-post-counter=1\n",
        (unsigned long long)nonce,rounds-1,valid&&passed==rounds);
    for(unsigned i=0;i<2;++i){[parameters[i] release];[output[i] release];}
    [queue release];[pipeline release];[function release];return valid&&passed==rounds;
}
