/* SPDX-License-Identifier: MIT */
/* Native Metal registration, actual GPU compute and shared IOSurface draw.
 * Probe policy keeps registration local to this process. System policy uses
 * ordinary Metal discovery. Neither a software renderer nor a nil device passes. */
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include "surface-padding.h"
#include "retained-memory.h"
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include "iosurface-abi.h"
#include "gui-profile.h"
#include "graphics-memory-report.h"

@interface NSObject (RedfinMetalSurface)
- (id)newTextureWithDescriptor:(MTLTextureDescriptor *)descriptor iosurface:(IOSurfaceRef)surface plane:(NSUInteger)plane;
- (BOOL)doesAliasResource:(id)resource;
@end

#include "metal-raster-check.inc"
#include "metal-surface-cache-check.inc"
#include "metal-vertex-check.inc"
#include "metal-half-check.inc"
#include "metal-blit-check.inc"
#include "metal-buffer-check.inc"
#include "metal-buffer-texture-check.inc"
#include "metal-alpha-check.inc"
#include "metal-function-constants-check.inc"
#include "metal-cache-check.inc"
#include "metal-ordering-check.inc"
#include "metal-bindings-check.inc"
#include "metal-queued-check.inc"
#include "metal-scheduling-check.inc"
#include "metal-ubo-extents-check.inc"
#include "metal-physical-check.inc"

int redfin_metal_resource_check(const char *path,uint64_t nonce);

extern int memorystatus_control(uint32_t,int32_t,uint32_t,void *,size_t);
struct metal_limits {int32_t active;uint32_t active_attributes;int32_t inactive;uint32_t inactive_attributes;};
static int memory_limit(void)
{
    /* Same actual8796 own-PID set/get used by the native Photos helper.
     * A job's plist limit did not reach this process in the observed boot. */
    struct metal_limits wanted={512,1,512,1},actual={0};
    if (memorystatus_control(7,getpid(),0,&wanted,sizeof(wanted)) ||
        memorystatus_control(8,getpid(),0,&actual,sizeof(actual))) return errno ? errno : EIO;
    return actual.active==512 && actual.inactive==512 ? 0 : EINVAL;
}

static int registry_number(io_service_t service,CFStringRef key)
{
    CFTypeRef value=IORegistryEntryCreateCFProperty(service,key,NULL,0);int number=0;
    if (value && CFGetTypeID(value)==CFNumberGetTypeID())
        (void)CFNumberGetValue(value,kCFNumberIntType,&number);
    if (value) CFRelease(value);
    return number;
}

static BOOL compute(id<MTLDevice> device,id<MTLComputePipelineState> pipeline,uint32_t seed)
{
    id<MTLCommandQueue> queue=[device newCommandQueue];
    id<MTLBuffer> output=[device newBufferWithLength:128*sizeof(uint32_t) options:MTLResourceStorageModeShared];
    id<MTLBuffer> input=[device newBufferWithLength:sizeof(uint32_t) options:MTLResourceStorageModeShared];
    BOOL valid=queue && output && input;
    for (unsigned round=0;valid && round<96;++round) {
        @autoreleasepool {
            uint32_t nonce=seed+round*0x9e3779b9u;
            uint32_t *words=[output contents],*in=[input contents];
            if (!words || !in) {valid=NO;break;}
            for (unsigned i=0;i<128;++i) words[i]=0xcafed00du;
            *in=nonce;
            id<MTLCommandBuffer> command=[queue commandBuffer];
            id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
            if (!command || !encoder) {valid=NO;break;}
            [encoder setComputePipelineState:pipeline];
            [encoder setBuffer:output offset:0 atIndex:0];
            [encoder setBuffer:input offset:0 atIndex:1];
            [encoder dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];
            [encoder endEncoding];[command commit];[command waitUntilCompleted];
            valid=[command status]==MTLCommandBufferStatusCompleted && ![command error];
            if (!valid) printf("REDFIN METAL COMPUTE: round=%u status=%lu error=%s\n",round,
                (unsigned long)command.status,command.error ? command.error.description.UTF8String : "none");
            for (unsigned i=0;valid && i<128;++i) {
                uint32_t expected=i<64 ? (i^nonce)*1664525u+1013904223u : 0xcafed00du;
                if (words[i]!=expected) {
                    printf("REDFIN METAL COMPUTE: round=%u index=%u actual=%08x expected=%08x\n",round,i,words[i],expected);
                    valid=NO;
                }
            }
        }
    }
    [input release];[output release];[queue release];return valid;
}

static BOOL render_dependency(id<MTLDevice> device,id<MTLLibrary> library)
{
    IOSurfaceRef surfaces[2]={NULL,NULL};
    id<MTLTexture> textures[2]={nil,nil};
    id<MTLRenderPipelineState> pipelines[2]={nil,nil};
    id<MTLCommandQueue> queue=nil;
    BOOL valid=YES;
    for(unsigned i=0;i<2&&valid;++i) {
        NSDictionary *properties=@{(id)kIOSurfaceWidth:@64,(id)kIOSurfaceHeight:@64,
            (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@256,
            (id)kIOSurfaceAllocSize:@32768,(id)kIOSurfacePixelFormat:@0x42475241,@"IOSurfaceIsGlobal":@YES};
        surfaces[i]=IOSurfaceCreate((CFDictionaryRef)properties);
        valid=surfaces[i]&&IOSurfaceGetAllocSize(surfaces[i])==32768;
        uint32_t seed=0;
        if(valid) {
            valid=IOSurfaceLock(surfaces[i],0,&seed)==KERN_SUCCESS;
            if(valid) {
                void *pixels=IOSurfaceGetBaseAddress(surfaces[i]);valid=pixels!=NULL;
                if(pixels)memset(pixels,0xa5,32768);
                if(IOSurfaceUnlock(surfaces[i],0,&seed)!=KERN_SUCCESS)valid=NO;
            }
        }
        MTLTextureDescriptor *desc=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:64 height:64 mipmapped:NO];
        desc.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;desc.storageMode=MTLStorageModeShared;
        textures[i]=valid?[(id)device newTextureWithDescriptor:desc iosurface:surfaces[i] plane:0]:nil;
        MTLRenderPipelineDescriptor *shape=[[MTLRenderPipelineDescriptor alloc] init];
        shape.vertexFunction=[library newFunctionWithName:@"redfin_vertex"];
        shape.fragmentFunction=[library newFunctionWithName:i?@"redfin_dependency_fragment":@"redfin_fragment"];
        shape.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
        NSError *error=nil;
        pipelines[i]=textures[i]?[device newRenderPipelineStateWithDescriptor:shape error:&error]:nil;
        if(error)printf("REDFIN METAL DEPENDENCY: native pipeline error=%s\n",error.description.UTF8String);
        [shape.vertexFunction release];[shape.fragmentFunction release];[shape release];
        valid=valid&&textures[i]&&pipelines[i];
    }
    if(valid) {
        queue=[device newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];valid=queue&&command;
        for(unsigned i=0;i<2&&valid;++i) {
            MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture=textures[i];
            pass.colorAttachments[0].loadAction=MTLLoadActionClear;
            pass.colorAttachments[0].storeAction=MTLStoreActionStore;
            pass.colorAttachments[0].clearColor=MTLClearColorMake(1,0,0,1);
            id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];valid=encoder!=nil;
            if(valid) {
                [encoder setRenderPipelineState:pipelines[i]];
                if(i)[encoder setFragmentTexture:textures[0] atIndex:0];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];
            }
        }
        if(valid){[command commit];[command waitUntilCompleted];valid=command.status==MTLCommandBufferStatusCompleted&&!command.error;}
    }
    for(unsigned i=0;i<2&&valid;++i) {
        uint32_t seed=0;
        valid=IOSurfaceLock(surfaces[i],kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
        if(valid) {
            uint8_t *pixels=IOSurfaceGetBaseAddress(surfaces[i]);valid=pixels&&IOSurfaceGetBytesPerRow(surfaces[i])==256;
            for(unsigned at=0;valid&&at<16384;at+=4)valid=pixels[at]>=190&&pixels[at]<=192&&
                pixels[at+1]>=127&&pixels[at+1]<=129&&pixels[at+2]>=63&&pixels[at+2]<=65&&pixels[at+3]==255;
            for(unsigned at=16384;valid&&at<32768;++at)valid=pixels[at]==0xa5;
            if(IOSurfaceUnlock(surfaces[i],kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS)valid=NO;
        }
    }
    [queue release];
    for(unsigned i=0;i<2;++i){[pipelines[i] release];[textures[i] release];if(surfaces[i])CFRelease(surfaces[i]);}
    return valid;
}

static BOOL native_gmem_statistics(id device,uint64_t counts[2])
{
    void *plugin=dlopen("/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",RTLD_NOW|RTLD_LOCAL|RTLD_NOLOAD);
    int (*statistics)(id,uint64_t *,size_t)=plugin?
        (int (*)(id,uint64_t *,size_t))dlsym(plugin,"redfin_metal_raster_statistics"):NULL;
    BOOL valid=statistics&&!statistics(device,counts,2)&&counts[0]>0;
    if(plugin)dlclose(plugin);return valid;
}

#include "surface-padding-check.inc"

static BOOL render(id<MTLDevice> device,id<MTLLibrary> library,BOOL mask,BOOL batch,unsigned storage)
{
    BOOL short_storage=storage==1,padded_storage=storage==2||storage==4,wrapped_storage=storage==3,special=storage!=0;
    MTLPixelFormat format=mask ? MTLPixelFormatRG8Unorm : MTLPixelFormatBGRA8Unorm;
    unsigned width=storage==4?281:special?1065:64,height=storage==4?609:special?282:64;
    unsigned bpe=mask ? 2 : 4,stride_bytes=storage==4?1152:special?4288:64*bpe;
    unsigned requested=storage==4?704512:special?1212416:(batch ? 32768 : 16384),payload=height*stride_bytes;
    /* A full owned image may use its attested padded rows. A shorter view
     * of that same allocation retains its declared guard and uses sysmem. */
    unsigned surface_height=short_storage?height+1:height;
    unsigned footprint=((surface_height+3u)&~3u)*stride_bytes;
    unsigned allocation=special&&!wrapped_storage?MAX(requested,(footprint+16383u)&~16383u):requested;
    unsigned guard=padded_storage?footprint:payload;
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(surface_height),
        (id)kIOSurfaceBytesPerElement:@(bpe),(id)kIOSurfaceBytesPerRow:@(stride_bytes),
        (id)kIOSurfaceAllocSize:@(requested),(id)kIOSurfacePixelFormat:@(mask ? 0x32433038 : 0x42475241),@"IOSurfaceIsGlobal":@YES};
    void *wrapped=NULL;
    NSMutableDictionary *wrapped_properties=nil;
    if(wrapped_storage) {
        if(posix_memalign(&wrapped,16384,allocation))return NO;
        wrapped_properties=[properties mutableCopy];
        wrapped_properties[@"IOSurfaceAddress"]=@((uint64_t)(uintptr_t)wrapped);
        properties=wrapped_properties;
    }
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    [wrapped_properties release];
    if (!surface || !IOSurfaceGetID(surface)) {if(surface)CFRelease(surface);free(wrapped);return NO;}
    uint32_t initial_seed=0;
    if (IOSurfaceGetAllocSize(surface)!=allocation || IOSurfaceLock(surface,0,&initial_seed)!=KERN_SUCCESS) {
        CFRelease(surface);free(wrapped);return NO;
    }
    void *initial=IOSurfaceGetBaseAddress(surface);
    if (!initial) {IOSurfaceUnlock(surface,0,&initial_seed);CFRelease(surface);free(wrapped);return NO;}
    memset(initial,0xa5,allocation);
    if (IOSurfaceUnlock(surface,0,&initial_seed)!=KERN_SUCCESS) {CFRelease(surface);free(wrapped);return NO;}
    MTLTextureDescriptor *desc=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:width height:height mipmapped:NO];
    desc.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    desc.storageMode=MTLStorageModeShared;
    id<MTLBuffer> viewBuffer=nil;
    id<MTLTexture> texture=nil;
    if(short_storage) {
        /* The drawable IOSurface entry point correctly requires exact
         * dimensions. Exercise a smaller legal buffer-texture view over
         * this owned parent's actual memory instead of bypassing that ABI. */
        viewBuffer=[device newBufferWithBytesNoCopy:initial length:allocation
            options:MTLResourceStorageModeShared deallocator:nil];
        texture=viewBuffer?[viewBuffer newTextureWithDescriptor:desc offset:0 bytesPerRow:stride_bytes]:nil;
    } else texture=[(id)device newTextureWithDescriptor:desc iosurface:surface plane:0];
    MTLRenderPipelineDescriptor *shape=[[MTLRenderPipelineDescriptor alloc] init];
    shape.vertexFunction=[library newFunctionWithName:@"redfin_vertex"];
    shape.fragmentFunction=[library newFunctionWithName:batch ? @"redfin_batch_fragment" : @"redfin_fragment"];
    shape.colorAttachments[0].pixelFormat=format;
    if (batch) {
        MTLRenderPipelineColorAttachmentDescriptor *color=shape.colorAttachments[0];
        color.blendingEnabled=YES;
        color.sourceRGBBlendFactor=MTLBlendFactorSourceAlpha;
        color.destinationRGBBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
        color.sourceAlphaBlendFactor=MTLBlendFactorOne;
        color.destinationAlphaBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
    }
    NSError *error=nil;
    id<MTLRenderPipelineState> pipeline=texture ? [device newRenderPipelineStateWithDescriptor:shape error:&error] : nil;
    id<MTLCommandQueue> queue=pipeline ? [device newCommandQueue] : nil;
    id<MTLCommandBuffer> command=[queue commandBuffer];
    BOOL valid=texture && pipeline && command && !error;
    if (!valid) printf("REDFIN METAL RENDER: texture=%u pipeline=%u command=%u error=%s\n",
        texture!=nil,pipeline!=nil,command!=nil,error ? error.description.UTF8String : "none");
    if (valid) {
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=texture;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=batch ? MTLClearColorMake(0,0,0,0) : MTLClearColorMake(1,0,0,1);
        id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        valid=encoder!=nil;
        if (valid) {
            [encoder setRenderPipelineState:pipeline];
            if (batch) {
                const float colors[3][4]={{1,0,0,0.5},{0,1,0,0.5},{0,0,1,0.5}};
                for (unsigned layer=0;layer<3;++layer) {
                    @autoreleasepool {
                        /* The buffer created by set*Bytes must outlive this pool,
                         * until the later command-buffer commit/final fence. */
                        [encoder setFragmentBytes:colors[layer] length:sizeof(colors[layer]) atIndex:0];
                        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                    }
                }
            } else [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [encoder endEncoding];[command commit];[command waitUntilCompleted];
            valid=[command status]==MTLCommandBufferStatusCompleted && ![command error];
        }
    }
    if (valid) {
        uint32_t seed=0;
        valid=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed)==KERN_SUCCESS;
        if (valid) {
            const uint8_t *pixels=IOSurfaceGetBaseAddress(surface);
            size_t stride=IOSurfaceGetBytesPerRow(surface);
            valid=pixels && stride==stride_bytes && IOSurfaceGetWidth(surface)==width && IOSurfaceGetHeight(surface)==surface_height;
            for (unsigned y=0;valid && y<height;++y) for (unsigned x=0;valid && x<width;++x) {
                const uint8_t *p=pixels+y*stride+x*bpe;
                valid=batch ? (p[0]>=127 && p[0]<=129 && p[1]>=63 && p[1]<=65 &&
                     p[2]>=31 && p[2]<=33 && p[3]>=223 && p[3]<=225) :
                    mask ? (p[0]>=63 && p[0]<=65 && p[1]>=127 && p[1]<=129) :
                    (p[0]>=190 && p[0]<=192 && p[1]>=127 && p[1]<=129 &&
                     p[2]>=63 && p[2]<=65 && p[3]==255);
            }
            for (unsigned at=guard;valid && at<allocation;++at) valid=pixels[at]==0xa5;
            if (IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed)!=KERN_SUCCESS) valid=NO;
        }
    }
    [queue release];[pipeline release];
    [shape.vertexFunction release];[shape.fragmentFunction release];
    [shape release];[texture release];[viewBuffer release];CFRelease(surface);free(wrapped);
    return valid;
}

static BOOL retained_memory_native(id device,uint64_t nonce)
{
    void *plugin=dlopen("/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",RTLD_NOW|RTLD_LOCAL|RTLD_NOLOAD);
    int (*read)(id,uint64_t *,size_t)=plugin?
        (int (*)(id,uint64_t *,size_t))dlsym(plugin,"redfin_metal_retained_statistics"):NULL;
    uint64_t counts[RF_GM_WORDS]={0};
    BOOL valid=read&&!read(device,counts,RF_GM_WORDS)&&counts[RF_GM_CAPABILITY]==RF_GM_ABI&&
        counts[RF_GM_QUERIES]==1&&counts[RF_GM_FAST]>0&&counts[RF_GM_FALLBACK]==0;
    if(plugin)dlclose(plugin);
    printf("REDFIN METAL RETAINED MEMORY: boot=%016llx ABI=%llu queries=%llu fast=%llu fallback=%llu passed=%u real-fences-and-CPU-ownership=1\n",
        (unsigned long long)nonce,(unsigned long long)counts[RF_GM_CAPABILITY],
        (unsigned long long)counts[RF_GM_QUERIES],(unsigned long long)counts[RF_GM_FAST],
        (unsigned long long)counts[RF_GM_FALLBACK],valid);
    return valid;
}

int main(void)
{
    @autoreleasepool {
        setvbuf(stdout,NULL,_IOLBF,0);
        char args[608]={0};size_t bytes=sizeof(args);uint64_t nonce=0;
        if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || bytes>sizeof(args) ||
            !redfin_gpu_gui_profile(args,(unsigned)bytes,&nonce)) return 0;
        io_service_t gpu=0;
        for (unsigned i=0;i<120 && !gpu;++i) {
            gpu=IOServiceGetMatchingService(0,IOServiceMatching("RedwoodGPU"));
            if (!gpu) sleep(1);
        }
        int mode=gpu ? registry_number(gpu,CFSTR("RedfinMetalPolicy")) : 0;
        int paddingABI=gpu?registry_number(gpu,CFSTR("RedfinSurfacePaddingABI")):0;
        int physicalABI=gpu?registry_number(gpu,CFSTR("RedfinPhysicalSubmissionABI")):0;
        int surfaceCacheABI=gpu?registry_number(gpu,CFSTR("RedfinSurfaceCacheABI")):0;
        if (gpu) IOObjectRelease(gpu);
        if (mode!=1 && mode!=2) return 0;
        printf("REDFIN METAL CHECK BOOT: %016llx mode=%d pid=%d\n",(unsigned long long)nonce,mode,getpid());
        int admitted=memory_limit();
        printf("REDFIN METAL CHECK MEMORY: native-own-pid=1 active=512 inactive=512 error=%d\n",admitted);
        if (admitted) return 2;
        redfin_graphics_memory_report("checker-before",0);
        @try {
            /* This initializes Metal's real device array before private registration. */
            id<MTLDevice> device=MTLCreateSystemDefaultDevice();
            if (mode==1 && device==nil) {
                NSBundle *bundle=[NSBundle bundleWithPath:@"/System/Library/Extensions/RedfinMetal.bundle"];
                NSError *error=nil;
                if (![bundle loadAndReturnError:&error]) {printf("REDFIN METAL CHECK: bundle failed code=%ld\n",(long)error.code);return 1;}
                Class cls=[bundle classNamed:@"RedwoodMetalDevice"];
                io_service_t accelerator=IOServiceGetMatchingService(0,IOServiceMatching("IOAcceleratorES"));
                id candidate=cls && accelerator ? ((id (*)(id,SEL,io_service_t))objc_msgSend)([cls alloc],sel_registerName("initWithAcceleratorPort:"),accelerator) : nil;
                if (accelerator) IOObjectRelease(accelerator);
                void (*add)(id)=(void (*)(id))dlsym(RTLD_DEFAULT,"MTLAddDevice");
                if (!candidate || !add) {[candidate release];printf("REDFIN METAL CHECK: native registration unavailable\n");return 1;}
                add(candidate);[candidate release];device=MTLCreateSystemDefaultDevice();
            }
            if (!device || strcmp(class_getName(object_getClass(device)),"RedwoodMetalDevice") ||
                [device maxBufferLength]!=(128ULL<<20)) {
                printf("REDFIN METAL CHECK: native A620 device/bounds absent\n");return 1;
            }
            NSError *error=nil;
            id<MTLLibrary> library=[device newLibraryWithFile:@"/redfin/lib/redfin-check-v2.metallib" error:&error];
            id<MTLFunction> function=[library newFunctionWithName:@"redfin_affine"];
            id<MTLComputePipelineState> pipeline=function ? [device newComputePipelineStateWithFunction:function error:&error] : nil;
            if (!library || !pipeline || error) {
                printf("REDFIN METAL CHECK: native library/pipeline failed code=%ld error=%s\n",
                    (long)error.code,error ? error.description.UTF8String : "none");return 1;
            }
            __block BOOL first=NO,second=NO;
            dispatch_group_t group=dispatch_group_create();
            dispatch_queue_t concurrent=dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0);
            dispatch_group_async(group,concurrent,^{@autoreleasepool{first=compute(device,pipeline,(uint32_t)nonce);}});
            dispatch_group_async(group,concurrent,^{@autoreleasepool{second=compute(device,pipeline,(uint32_t)(nonce>>32)^0xa5a5a5a5u);}});
            if (dispatch_group_wait(group,dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_SEC))) {
                printf("REDFIN METAL CHECK: concurrent command queues timed out\n");return 1;
            }
            BOOL pixels=first && second && render(device,library,NO,NO,NO);
            BOOL masks=pixels && render(device,library,YES,NO,NO);
            BOOL batches=masks && render(device,library,NO,YES,NO);
            BOOL dependencies=batches&&render_dependency(device,library);
            uint64_t before_short[2]={0},after_short[2]={0};
            BOOL short_bounds=dependencies&&native_gmem_statistics(device,before_short)&&
                render(device,library,NO,NO,YES)&&native_gmem_statistics(device,after_short)&&
                after_short[0]==before_short[0]&&after_short[1]>before_short[1];
            uint64_t before_wrapped[2]={0},after_wrapped[2]={0};
            BOOL wrapped_bounds=short_bounds&&native_gmem_statistics(device,before_wrapped)&&
                render(device,library,NO,NO,3)&&native_gmem_statistics(device,after_wrapped)&&
                after_wrapped[0]==before_wrapped[0]&&after_wrapped[1]>before_wrapped[1];
            uint64_t before_padded[2]={0},after_padded[2]={0};
            BOOL padded_bounds=wrapped_bounds&&paddingABI==RF_GP_ABI&&native_gmem_statistics(device,before_padded)&&
                render(device,library,NO,NO,2)&&render(device,library,NO,NO,4)&&native_gmem_statistics(device,after_padded)&&
                after_padded[0]>before_padded[0]&&after_padded[1]==before_padded[1];
            BOOL padded_restore=padded_bounds&&padding_restore_native(device,library,nonce,1065,282,4288)&&
                padding_restore_native(device,library,nonce,281,609,1152);
            printf("REDFIN METAL PADDED OUTPUT: boot=%016llx full-image-pixels-guards-GMEM=%u shorter-view-pixels-guards-sysmem=%u wrapped-pixels-guards-sysmem=%u gmem-before=%llu gmem-after=%llu sysmem-before=%llu sysmem-after=%llu owned-ABI=1\n",
                (unsigned long long)nonce,padded_bounds,short_bounds,wrapped_bounds,
                (unsigned long long)before_padded[0],(unsigned long long)after_padded[0],
                (unsigned long long)before_padded[1],(unsigned long long)after_padded[1]);
            BOOL raster=padded_bounds&&render_raster_passes(device,library);
            BOOL vertices=short_bounds&&render_vertex_streams(device,library);
            BOOL halfRaster=short_bounds&&half_raster_native(device,library,nonce);
            BOOL pitch480=short_bounds&&render_byte_pitch(device,library,(uint32_t)nonce,120,32,480,512,16384,32768,paddingABI);
            BOOL pitch4512=short_bounds&&render_byte_pitch(device,library,(uint32_t)(nonce>>32),1125,9,4512,4544,65536,65536,paddingABI);
            BOOL resolve480=short_bounds&&render_byte_pitch(device,library,(uint32_t)nonce^0xabcdecadu,120,32,480,480,16384,16384,paddingABI);
            BOOL resolve4512=short_bounds&&render_byte_pitch(device,library,(uint32_t)(nonce>>32)^0x815ca461u,1125,9,4512,4512,65536,65536,paddingABI);
            BOOL blits=short_bounds&&blit_native(device,nonce);
            BOOL buffers=short_bounds&&buffer_native(device,pipeline,nonce);
            BOOL bufferTextures=short_bounds&&buffer_texture_native(device,nonce);
            BOOL alpha=short_bounds&&buffer_alpha_native(device,library,nonce);
            BOOL constants=short_bounds&&function_constants_native(device,library,nonce);
            BOOL preparation=short_bounds&&preparation_cache_native(device,library,nonce);
            BOOL ordering=short_bounds&&ordering_native(device,library,nonce);
            BOOL bindingReuse=short_bounds&&bindings_native(device,library,nonce);
            BOOL queued=short_bounds&&queued_native(device,library,nonce);
            BOOL scheduling=short_bounds&&scheduling_native(device,nonce);
            BOOL uboExtents=short_bounds&&ubo_extents_native(device,library,nonce);
            BOOL resourceReferences=short_bounds&&redfin_metal_resource_check("/redfin/lib/redfin-resource-check.bc",nonce);
            BOOL retainedMemory=retained_memory_native(device,nonce);
            BOOL surfaceCache=short_bounds&&surfaceCacheABI==1&&surface_cache_native(device,nonce);
            uint64_t routes[2]={0};BOOL gmem=dependencies&&native_gmem_statistics(device,routes);
            /* Run the bounded busy probe last. An actual GPU failure retires
             * the context; no later checker may create/use new native pipes. */
            BOOL physicalPending=short_bounds&&physicalABI==1&&physical_pending_native(device,library,nonce);
            printf("REDFIN METAL CHECK RESULT: boot=%016llx mode=%d compute-queues=%u rounds-per-queue=96 actual-output=%u guards=%u iosurface-pixels=%u rg8-pixels-and-guards=%u batch-pixels-and-guards=%u dependency-pixels-and-guards=%u short-surface-pixels-guards-and-sysmem=%u actual-gmem=%u gmem-batches=%llu sysmem-batches=%llu\n",
                (unsigned long long)nonce,mode,(unsigned)(first+second),(unsigned)(first && second),(unsigned)(first && second),(unsigned)pixels,(unsigned)masks,(unsigned)batches,(unsigned)dependencies,(unsigned)short_bounds,(unsigned)gmem,
                (unsigned long long)routes[0],(unsigned long long)routes[1]);
            printf("REDFIN METAL COMPOSITION RESULT: boot=%016llx clear-only-mrt-scissor-viewport-fetch-pixels-guards=%u vertex-stream-varying-sample-pixels-guards=%u pitch480-two-seeds-pixels-guards=%u pitch4512-two-seeds-pixels-guards=%u resolve480-pixels-guards=%u resolve4512-pixels-guards=%u visible-overlay=0\n",
                (unsigned long long)nonce,raster,vertices,pitch480,pitch4512,resolve480,resolve4512);
            [pipeline release];[function release];[library release];dispatch_release(group);[device release];
            int status=gmem&&short_bounds&&wrapped_bounds&&padded_bounds&&padded_restore&&raster&&vertices&&halfRaster&&pitch480&&pitch4512&&resolve480&&resolve4512&&blits&&buffers&&bufferTextures&&alpha&&constants&&preparation&&ordering&&bindingReuse&&queued&&scheduling&&uboExtents&&physicalPending&&resourceReferences&&retainedMemory&&surfaceCache ? 0 : 1;
            redfin_graphics_memory_report("checker-after",0);
            /* task_info's status above describes memory accounting only. */
            printf("REDFIN METAL CHECK EXIT: boot=%016llx result=%u full-contract=1\n",
                (unsigned long long)nonce,(unsigned)status);
            return status;
        } @catch (NSException *exception) {
            printf("REDFIN METAL CHECK: exception=%s reason=%s\n",exception.name.UTF8String,exception.reason.UTF8String);
            printf("REDFIN METAL CHECK EXIT: boot=%016llx result=1 full-contract=0 exception=1\n",(unsigned long long)nonce);
            return 1;
        }
    }
}
