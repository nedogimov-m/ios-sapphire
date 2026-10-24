/*
 * A620 adaptation of the preferred HackiOS RedwoodGPU / msm DRM 1.7 bridge:
 * oosexgang/hackios-xnu-kernel 8e611870, iokit/Kernel/RedwoodGPU.cpp.
 * Changed 2026-10-24 for Redfin's owned native backend and iOS20H392 surfaces.
 *
 * There is one serialized, synchronous GPU queue. Each submission must finish
 * its actual GPU cache-flush fence before the kernel returns success. This
 * also establishes when surfaces can be read by the existing CPU display path.
 * A failed queue/TLB retains every mapped descriptor until the platform reset.
 * No recovery, false completion, foreign fault clearing or Metal claim.
 *
 * This file contains Modifications of Original Code subject to the Apple
 * Public Source License Version2.0 (https://opensource.apple.com/apsl/).
 * The code is provided AS IS, WITHOUT WARRANTY OF ANY KIND; see the License.
 */
#include "SweetSurface.h"
#if defined(SWEET)
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include "RedfinGPUService.h"
#include "RedfinGPURuntime.h"

enum {
    GemClose=0x09,GetParam=0x40,SetParam=0x41,GemNew=0x42,GemInfo=0x43,
    CpuPrep=0x44,CpuFini=0x45,Submit=0x46,WaitFence=0x47,Madvise=0x48,
    QueueNew=0x4a,QueueClose=0x4b,QueueQuery=0x4c,Surface=0x7e,Show=0x7f
};
struct msm_timespec {int64_t seconds,nanoseconds;};
struct msm_param {uint32_t pipe,param;uint64_t value;uint32_t len,pad;};
struct msm_gem_new {uint64_t size;uint32_t flags,handle;};
struct msm_gem_info {uint32_t handle,info;uint64_t value;uint32_t len,pad;};
struct msm_cpu_prep {uint32_t handle,op;struct msm_timespec timeout;};
struct msm_cmd {uint32_t type,index,offset,size,pad,relocs;uint64_t relocations;};
struct msm_bo {uint32_t flags,handle;uint64_t presumed;};
struct msm_submit {
    uint32_t flags,fence,nr_bos,nr_cmds;uint64_t bos,cmds;int32_t fence_fd;uint32_t queue;
    uint64_t in_syncobjs,out_syncobjs;uint32_t nr_in,nr_out,stride,pad;
};
struct msm_wait {uint32_t fence,flags;struct msm_timespec timeout;uint32_t queue;};
struct msm_madvise {uint32_t handle,madv,retained;};
struct msm_queue {uint32_t flags,prio,id;};
struct msm_query {uint64_t data;uint32_t id,param,len,pad;};
struct drm_close {uint32_t handle,pad;};
struct redwood_surface {
    uint32_t surface,handle;uint64_t size;uint32_t offset,rowBytes,width,height,pixelFormat,planes;
};
struct redwood_show {uint64_t pixels;uint32_t width,height,rowBytes,pad;};
static_assert(sizeof(msm_submit)==72,"msm DRM 1.7 submission ABI");
static_assert(sizeof(msm_cmd)==32,"msm command ABI");
static_assert(sizeof(redwood_surface)==40,"preferred IOSurface import ABI");
static IOLock *gLock;
static uint32_t gStarts;
class GPUTransaction {
    void *previous;
public:
    GPUTransaction():previous(redfin_gpu_bind()){IOLockLock(gLock);}
    ~GPUTransaction(){IOLockUnlock(gLock);redfin_gpu_unbind(previous);}
};
static IOReturn gpuError(int error)
{
    switch(error) {
    case 0:return kIOReturnSuccess;
    case ENOMEM:case ENOSPC:return kIOReturnNoMemory;
    case EINVAL:case ERANGE:return kIOReturnBadArgument;
    case EBUSY:return kIOReturnBusy;
    case ETIMEDOUT:return kIOReturnTimeout;
    case ENXIO:case ECANCELED:return kIOReturnNotReady;
    default:return kIOReturnIOError;
    }
}
class RedwoodGPU:public IOService {
    OSDeclareDefaultStructors(RedwoodGPU);
public:
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(RedwoodGPU,IOService);
bool RedwoodGPU::start(IOService *provider)
{
    if(!redfin_gpu_ready() || !IOService::start(provider))return false;
    setName("RedwoodGPU");setProperty(kIOUserClientClassKey,"RedwoodGPUUserClient");
    setProperty("chip-id",0x06020001,32);setProperty("RedfinRuntimeABI",1,32);
    registerService();return true;
}
void RedfinGPUStart(void)
{
    if(__atomic_exchange_n(&gStarts,1,__ATOMIC_ACQ_REL) || !redfin_gpu_ready())return;
    gLock=IOLockAlloc();IOService *provider=IOService::getPlatform();
    RedwoodGPU *gpu=OSTypeAlloc(RedwoodGPU);
    if(!gLock || !provider || !gpu || !gpu->init() || !gpu->attach(provider)) {
        OSSafeReleaseNULL(gpu);IOLog("REDFIN GPU SERVICE: creation failed\n");return;
    }
    if(!gpu->start(provider)){gpu->detach(provider);IOLog("REDFIN GPU SERVICE: publication failed\n");}
    else IOLog("REDFIN GPU SERVICE: RedwoodGPU msm1.7 ready, native A620; synchronous actual fences\n");
    gpu->release();
}
void RedfinGPUStop(void)
{
    if(!gLock)return;
    GPUTransaction transaction;redfin_gpu_stop();
}
struct gpu_buffer {
    IOMemoryDescriptor *memory;
    SweetSurface *surface;
    uint8_t *kernel;
    uint64_t address,size;
    uint32_t flags,fence;
};
class RedwoodGPUUserClient:public IOUserClient {
    OSDeclareDefaultStructors(RedwoodGPUUserClient);
    gpu_buffer *buffers;
    uint32_t nextHandle,nextQueue;
    bool closed;
    gpu_buffer *buffer(uint32_t handle);
    IOReturn create(msm_gem_new *request);
    IOReturn importSurface(redwood_surface *request);
    IOReturn info(msm_gem_info *request);
    IOReturn submit(msm_submit *request);
    IOReturn drop(uint32_t handle);
    IOReturn mapDescriptor(IOMemoryDescriptor *,uint8_t *,SweetSurface *,uint64_t,uint32_t,uint32_t *);
public:
    bool initWithTask(task_t,void *,UInt32,OSDictionary *) APPLE_KEXT_OVERRIDE;
    bool start(IOService *) APPLE_KEXT_OVERRIDE;
    IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
    void free(void) APPLE_KEXT_OVERRIDE;
    IOReturn clientMemoryForType(UInt32,IOOptionBits *,IOMemoryDescriptor **) APPLE_KEXT_OVERRIDE;
    IOReturn externalMethod(uint32_t,IOExternalMethodArguments *,IOExternalMethodDispatch *,OSObject *,void *) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(RedwoodGPUUserClient,IOUserClient);
bool RedwoodGPUUserClient::initWithTask(task_t task,void *security,UInt32 type,OSDictionary *properties)
{return type==0 && IOUserClient::initWithTask(task,security,type,properties);}
bool RedwoodGPUUserClient::start(IOService *provider)
{
    if(!redfin_gpu_ready() || !IOUserClient::start(provider))return false;
    buffers=IONewZero(gpu_buffer,RF_GR_OBJECTS);return buffers!=NULL;
}
gpu_buffer *RedwoodGPUUserClient::buffer(uint32_t handle)
{return handle && handle<=RF_GR_OBJECTS && buffers && buffers[handle-1].memory?&buffers[handle-1]:NULL;}
/* On success takes descriptor/surface references; on failure the caller keeps
 * them, except a new permanent retain when DMA ownership is uncertain. */
IOReturn RedwoodGPUUserClient::mapDescriptor(IOMemoryDescriptor *memory,uint8_t *kernel,SweetSurface *surface,
    uint64_t size,uint32_t flags,uint32_t *handle)
{
    if(!redfin_gpu_ready() || !memory || !kernel || !size || size>RF_GR_BUFFER_MAX ||
        (size&PAGE_MASK) || memory->getLength()<size)return kIOReturnBadArgument;
    unsigned slot=RF_GR_OBJECTS;
    for(unsigned i=0;i<RF_GR_OBJECTS;i++) {
        unsigned at=(nextHandle+i)%RF_GR_OBJECTS;
        if(!buffers[at].memory){slot=at;break;}
    }
    if(slot==RF_GR_OBJECTS)return kIOReturnNoResources;
    uint64_t address=redfin_gpu_address(size);if(!address)return kIOReturnNoMemory;
    int error=0;
    for(uint64_t offset=0;offset<size;offset+=4096) {
        IOByteCount bytes=0;
        addr64_t physical=memory->getPhysicalSegment(offset,&bytes,kIOMemoryMapperNone);
        if(!physical || bytes<4096){error=EINVAL;break;}
        error=redfin_gpu_map(address+offset,physical,(flags&2u)!=0);if(error)break;
    }
    if(!error)error=redfin_gpu_mapped();
    if(error) {
        if(redfin_gpu_release(address,size)) {
            memory->retain();if(surface)surface->retain();
            IOLog("REDFIN GPU SERVICE: failed map retains %llu bytes until reset\n",size);
        }
        return gpuError(error);
    }
    gpu_buffer *b=&buffers[slot];*b=(gpu_buffer){memory,surface,kernel,address,size,flags,0};
    nextHandle=slot+1;*handle=slot+1;return kIOReturnSuccess;
}
IOReturn RedwoodGPUUserClient::create(msm_gem_new *r)
{
    if(!r->size || r->size>RF_GR_BUFFER_MAX || (r->flags&~0x000f0003u))return kIOReturnBadArgument;
    uint64_t size=(r->size+PAGE_MASK)&~(uint64_t)PAGE_MASK;
    IOBufferMemoryDescriptor *memory=IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
        kIODirectionInOut|kIOMemoryKernelUserShared|kIOMapWriteCombineCache,(vm_size_t)size,PAGE_SIZE);
    if(!memory)return kIOReturnNoMemory;
    IOReturn result=mapDescriptor(memory,(uint8_t *)memory->getBytesNoCopy(),NULL,size,r->flags,&r->handle);
    if(result!=kIOReturnSuccess)memory->release();return result;
}
IOReturn RedwoodGPUUserClient::importSurface(redwood_surface *r)
{
    SweetSurface *s=sweet_surface_copy(r->surface);if(!s)return kIOReturnNotFound;
    uint64_t size=((uint64_t)s->allocSize+PAGE_MASK)&~(uint64_t)PAGE_MASK;
    /* This port keeps state and pixels in separate descriptors. There is no
     * upstream PAGE_SIZE prefix to skip. Wrapped client ranges are deferred. */
    if(s->wrapped || !s->memory || s->planeCount>1 || !size || size>RF_GR_BUFFER_MAX ||
        s->memory->getLength()<size || !s->kernelAddress()) {s->release();return kIOReturnUnsupported;}
    r->size=size;r->offset=s->offset;r->rowBytes=s->bytesPerRow;r->width=s->width;
    r->height=s->height;r->pixelFormat=s->pixelFormat;r->planes=s->planeCount;
    if(r->handle==UINT32_MAX){r->handle=0;s->release();return kIOReturnSuccess;}
    for(unsigned i=0;i<RF_GR_OBJECTS;i++)if(buffers[i].memory && buffers[i].surface==s) {
        r->handle=i+1;s->release();return kIOReturnSuccess;
    }
    s->memory->retain();
    IOReturn result=mapDescriptor(s->memory,(uint8_t *)s->kernelAddress(),s,size,0,&r->handle);
    if(result!=kIOReturnSuccess){s->memory->release();s->release();}return result;
}
IOReturn RedwoodGPUUserClient::drop(uint32_t handle)
{
    gpu_buffer *b=buffer(handle);if(!b)return kIOReturnBadArgument;
    int error=redfin_gpu_release(b->address,b->size);
    if(error) {
        /* These references remain deliberately live; after a failed fence,
         * releasing backing pages would let DMA reach another owner's RAM. */
        IOLog("REDFIN GPU SERVICE: retained handle=%u bytes=%llu error=%d until reset\n",handle,b->size,error);
    } else {
        b->memory->release();if(b->surface)b->surface->release();
    }
    *b=(gpu_buffer){};return error?gpuError(error):kIOReturnSuccess;
}
IOReturn RedwoodGPUUserClient::clientClose(void)
{
    if(!closed && buffers) {
        GPUTransaction transaction;
        for(unsigned i=0;i<RF_GR_OBJECTS;i++)if(buffers[i].memory)(void)drop(i+1);
        closed=true;
    }
    if(!isInactive())terminate();return kIOReturnSuccess;
}
void RedwoodGPUUserClient::free(void)
{
    if(buffers){
        if(!closed){GPUTransaction transaction;for(unsigned i=0;i<RF_GR_OBJECTS;i++)if(buffers[i].memory)(void)drop(i+1);}
        IODelete(buffers,gpu_buffer,RF_GR_OBJECTS);buffers=NULL;
    }
    IOUserClient::free();
}
IOReturn RedwoodGPUUserClient::info(msm_gem_info *r)
{
    gpu_buffer *b=buffer(r->handle);if(!b)return kIOReturnBadArgument;
    switch(r->info) {
    case 0:r->value=(uint64_t)r->handle<<32;return kIOReturnSuccess;
    case 1:r->value=b->address;return kIOReturnSuccess;
    case 2:return kIOReturnSuccess; /* debugger-only name */
    case 5:r->value=b->flags;return kIOReturnSuccess;
    default:return kIOReturnUnsupported;
    }
}
IOReturn RedwoodGPUUserClient::clientMemoryForType(UInt32 type,IOOptionBits *options,IOMemoryDescriptor **memory)
{
    if(!options || !memory || !gLock)return kIOReturnBadArgument;
    GPUTransaction transaction;gpu_buffer *b=buffer(type);
    if(!b || !redfin_gpu_ready())return kIOReturnNotFound;
    *memory=b->memory;(*memory)->retain();
    *options=b->surface?b->surface->mapCache:kIOMapWriteCombineCache;return kIOReturnSuccess;
}
IOReturn RedwoodGPUUserClient::submit(msm_submit *r)
{
    if(!r->nr_cmds || r->nr_cmds>RF_GR_COMMANDS || !r->nr_bos || r->nr_bos>RF_GR_OBJECTS ||
        (r->flags&~0x80000010u) || (r->flags&0xffu)!=0x10u || r->nr_in || r->nr_out || r->in_syncobjs || r->out_syncobjs ||
        r->pad || r->queue>nextQueue)return kIOReturnBadArgument;
    msm_bo *bos=IONew(msm_bo,r->nr_bos);msm_cmd *commands=IONew(msm_cmd,r->nr_cmds);
    uint64_t addresses[RF_GR_COMMANDS];uint32_t words[RF_GR_COMMANDS],count=0;
    IOReturn result=kIOReturnBadArgument;
    if(!bos || !commands){result=kIOReturnNoMemory;goto done;}
    if(copyin((user_addr_t)r->bos,bos,r->nr_bos*sizeof(*bos)) ||
        copyin((user_addr_t)r->cmds,commands,r->nr_cmds*sizeof(*commands))){result=kIOReturnVMError;goto done;}
    for(unsigned i=0;i<r->nr_bos;i++) {
        gpu_buffer *b=buffer(bos[i].handle);
        if(!b || (bos[i].flags&~0xfu) || (bos[i].presumed && bos[i].presumed!=b->address))goto done;
    }
    for(unsigned i=0;i<r->nr_cmds;i++) {
        const msm_cmd *cmd=&commands[i];
        if(cmd->type!=1) {if(cmd->type==2 || cmd->type==3)continue;goto done;}
        gpu_buffer *b=cmd->index<r->nr_bos?buffer(bos[cmd->index].handle):NULL;
        if(!b || cmd->relocs || cmd->pad || !cmd->size || (cmd->offset&3u) ||
            (cmd->size&3u) || (uint64_t)cmd->offset+cmd->size>b->size)goto done;
        addresses[count]=b->address+cmd->offset;words[count++]=cmd->size/4;
    }
    if(!count)goto done;
    for(unsigned i=0;i<r->nr_bos;i++) {
        gpu_buffer *b=buffer(bos[i].handle);
        if(b->surface)redfin_gpu_sync(b->kernel,b->size,true);
    }
    redfin_gpu_sync(NULL,0,false);
    result=gpuError(redfin_gpu_submit(addresses,words,count,&r->fence));
    if(result==kIOReturnSuccess)for(unsigned i=0;i<r->nr_bos;i++) {
        gpu_buffer *b=buffer(bos[i].handle);b->fence=r->fence;
        if(b->surface)redfin_gpu_sync(b->kernel,b->size,true);
    }
done:
    if(bos)IODelete(bos,msm_bo,r->nr_bos);
    if(commands)IODelete(commands,msm_cmd,r->nr_cmds);
    return result;
}
static bool parameter(uint32_t param,uint64_t *value)
{
    switch(param) {
    case 1:case 6:case 8:case 9:case 0x0a:case 0x11:*value=0;return true;
    case 2:*value=512*1024;return true;
    case 3:*value=0x06020001;return true;
    case 4:*value=275000000;return true;
    case 5:*value=mach_absolute_time();return true;
    case 7:*value=1;return true;
    case 0x10:*value=14;return true;
    /* A620 uses native UBWC3. Do not advertise A642L UBWC4 parameters. */
    default:return false;
    }
}
IOReturn RedwoodGPUUserClient::externalMethod(uint32_t selector,IOExternalMethodArguments *args,
    IOExternalMethodDispatch *,OSObject *,void *)
{
    union Request {
        msm_param param;msm_gem_new create;msm_gem_info info;msm_cpu_prep prep;msm_submit submit;
        msm_wait wait;msm_madvise madvise;msm_queue queue;msm_query query;drm_close close;
        redwood_surface surface;redwood_show show;
    } r;
    if(!args || !buffers || closed || !args->structureInput || args->scalarInputCount ||
        args->scalarOutputCount)return kIOReturnBadArgument;
    size_t expected=0;
    switch(selector) {
    case GetParam:case SetParam:expected=sizeof(msm_param);break;
    case GemNew:expected=sizeof(msm_gem_new);break;
    case GemInfo:expected=sizeof(msm_gem_info);break;
    case CpuPrep:expected=sizeof(msm_cpu_prep);break;
    case CpuFini:expected=4;break;
    case Submit:expected=sizeof(msm_submit);break;
    case WaitFence:expected=sizeof(msm_wait);break;
    case Madvise:expected=sizeof(msm_madvise);break;
    case QueueNew:expected=sizeof(msm_queue);break;
    case QueueClose:expected=4;break;
    case QueueQuery:expected=sizeof(msm_query);break;
    case GemClose:expected=sizeof(drm_close);break;
    case Surface:expected=sizeof(redwood_surface);break;
    case Show:expected=sizeof(redwood_show);break;
    default:return kIOReturnUnsupported;
    }
    if(args->structureInputSize!=expected ||
        (args->structureOutputSize && (!args->structureOutput || args->structureOutputSize<expected)))return kIOReturnBadArgument;
    bzero(&r,sizeof(r));memcpy(&r,args->structureInput,expected);
    GPUTransaction transaction;
    if(!redfin_gpu_ready())return kIOReturnNotReady;
    IOReturn result=kIOReturnSuccess;
    switch(selector) {
    case GetParam:if(r.param.pipe!=0x10 || !parameter(r.param.param,&r.param.value))result=kIOReturnBadArgument;break;
    case SetParam:break;
    case GemNew:result=create(&r.create);break;
    case GemInfo:result=info(&r.info);break;
    case CpuPrep:
        if(!buffer(r.prep.handle))result=kIOReturnBadArgument;
        else if(!redfin_gpu_done(buffer(r.prep.handle)->fence))result=kIOReturnBusy;
        break;
    case CpuFini:if(!buffer(*(uint32_t *)&r))result=kIOReturnBadArgument;break;
    case Submit:result=submit(&r.submit);break;
    case WaitFence:
        if(!r.wait.fence || r.wait.fence>redfin_gpu_last() || !redfin_gpu_done(r.wait.fence))result=kIOReturnTimeout;
        break;
    case Madvise:if(!buffer(r.madvise.handle))result=kIOReturnBadArgument;else r.madvise.retained=1;break;
    case QueueNew:if(r.queue.flags || r.queue.prio || nextQueue==UINT32_MAX)result=kIOReturnBadArgument;else r.queue.id=++nextQueue;break;
    case QueueClose:if(!*(uint32_t *)&r || *(uint32_t *)&r>nextQueue)result=kIOReturnBadArgument;break;
    case QueueQuery:
        if(!r.query.id || r.query.id>nextQueue || r.query.param || r.query.len<8 || !r.query.data)result=kIOReturnBadArgument;
        else {uint64_t faults=0;if(copyout(&faults,(user_addr_t)r.query.data,8))result=kIOReturnVMError;}
        break;
    case GemClose:result=drop(r.close.handle);break;
    case Surface:result=importSurface(&r.surface);break;
    case Show:result=kIOReturnUnsupported;break; /* Use IOMobileFramebuffer/IOSurface for display. */
    default:result=kIOReturnUnsupported;break;
    }
    if(result==kIOReturnSuccess && args->structureOutputSize) {
        memcpy(args->structureOutput,&r,expected);args->structureOutputSize=(uint32_t)expected;
    }
    return result;
}
#endif /* SWEET */
