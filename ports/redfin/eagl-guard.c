/* SPDX-License-Identifier: MIT
 * Validate the whole 20H392 interface before replacing any method. The UUID,
 * signatures and RVAs below are generated from this root's own shared cache.
 */
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <mach/mach.h>
#include <objc/runtime.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include <pthread.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include "gui-profile.h"
#include "eagl-guard.h"
#include "eagl-abi.h"

typedef void *OSMesaContext;
extern OSMesaContext OSMesaCreateContextAttribs(const int *,OSMesaContext);
extern unsigned char OSMesaMakeCurrent(OSMesaContext,void *,unsigned,int,int);
extern void OSMesaDestroyContext(OSMesaContext);
extern const unsigned char *glGetString(unsigned);
extern void glGetIntegerv(unsigned,int *);
static uint64_t boot_nonce;
static unsigned installed_methods;
static unsigned published_frames,publication_fallbacks;
static void (*original_uniform)(void *,unsigned,size_t,size_t,const float *);
extern void redwood_gl_function_values(void *,unsigned,unsigned,size_t,size_t,const float *);
#if REDFIN_GLES_PUBLICATION
extern int redfin_gl_frame_publish(void);
#endif

static bool display_number(io_service_t service,const char *name,int expected)
{
    CFStringRef key=CFStringCreateWithCString(NULL,name,kCFStringEncodingUTF8);
    CFTypeRef value=key?IORegistryEntryCreateCFProperty(service,key,NULL,0):NULL;
    int actual=0;
    bool valid=value && CFGetTypeID(value)==CFNumberGetTypeID() &&
        CFNumberGetValue(value,kCFNumberIntType,&actual) && actual==expected;
    if(value)CFRelease(value);
    if(key)CFRelease(key);
    return valid;
}

int redfin_eagl_display_waits(unsigned display)
{
    /* Scoped-wait ABI1 includes retained FIFO kernel presents and a full
     * queue barrier before CPU fallback. Require the actual Redfin display
     * and queue versions; older/foreign drivers keep upstream's glFinish. */
    if(!REDFIN_GLES_PUBLICATION || !boot_nonce || !display ||
       !display_number(display,"RedfinPresentationStatisticsABI",2))return 0;
    io_service_t gpu=IOServiceGetMatchingService(0,IOServiceMatching("RedwoodGPU"));
    bool valid=gpu && display_number(gpu,"chip-id",0x06020001) &&
        display_number(gpu,"RedfinRuntimeABI",1) &&
        display_number(gpu,"RedfinQueuedSubmissionABI",1) &&
        display_number(gpu,"RedfinScopedWaitABI",1);
    if(gpu)IOObjectRelease(gpu);
    dprintf(2,"REDFIN EAGL PRESENT: boot=%016llx driver-waits=%u required-FIFO-ABI=1 publication-before-handoff=1\n",
        boot_nonce,valid);
    return valid;
}

int redfin_eagl_publish_frame(void)
{
    /* The current Mesa context flushes its CPU worker and materializes a
     * native kernel fence. This does not wait for that GPU fence to retire.
     * On failure the caller uses a real glFinish before any handoff. */
    int result=-1;
#if REDFIN_GLES_PUBLICATION
    result=redfin_gl_frame_publish();
#endif
    if(!result)++published_frames;else ++publication_fallbacks;
    if(published_frames<=4 || !(published_frames%120) || result)
        dprintf(2,"REDFIN EAGL PUBLISH: boot=%016llx pid=%d published=%u fallbacks=%u result=%d GPU-wait=0\n",
            boot_nonce,getpid(),published_frames,publication_fallbacks,result);
    return result==0;
}

static void observe_uniform(void *context,unsigned index,size_t components,size_t count,const float *values)
{
    const uint8_t *state=*(const uint8_t **)((const uint8_t *)context+REDFIN_CA_STATE_OFFSET);
    unsigned function=state?state[REDFIN_CA_FUNCTION_OFFSET]:90;
    if(state && values && components && count<=20/components)
        redwood_gl_function_values(context,function,index,components,count,values);
    original_uniform(context,index,components,count,values);
}

void redfin_eagl_set_tls(void *native_context)
{
    /* Apple's own EAGL sets the same reserved key using pthread_setspecific.
     * It is independently derived from every GL stub in the current cache. */
    (void)pthread_setspecific(REDFIN_EAGL_TLS_OFFSET/sizeof(void *),native_context);
}

int redfin_eagl_hardware(void)
{
    const char *renderer=(const char *)glGetString(0x1f01);
    return renderer && strstr(renderer,"620") && !strstr(renderer,"softpipe") &&
        !strstr(renderer,"llvmpipe") && !strstr(renderer,"Software");
}

static const struct mach_header_64 *native_image(const char *expected_name)
{
    for(uint32_t i=0;i<_dyld_image_count();i++) {
        const char *name=_dyld_get_image_name(i);
        if(name && !strcmp(name,expected_name))return (const void *)_dyld_get_image_header(i);
    }
    return NULL;
}

static bool image_uuid(const struct mach_header_64 *image,const uint8_t expected[16])
{
    if(!image || image->magic!=MH_MAGIC_64 || image->cputype!=CPU_TYPE_ARM64 ||
       image->ncmds>4096 || image->sizeofcmds>1024*1024)return false;
    const uint8_t *at=(const void *)(image+1),*end=at+image->sizeofcmds;
    bool uuid_ok=false;
    for(uint32_t i=0;i<image->ncmds;i++) {
        if((size_t)(end-at)<sizeof(struct load_command))return false;
        const struct load_command *command=(const void *)at;
        if(command->cmdsize<sizeof(*command) || command->cmdsize>(size_t)(end-at))return false;
        if(command->cmd==LC_UUID && command->cmdsize==sizeof(struct uuid_command))
            uuid_ok=!memcmp(((const struct uuid_command *)command)->uuid,expected,16);
        at+=command->cmdsize;
    }
    return uuid_ok && at==end;
}

int redfin_eagl_validate(void)
{
    char args[608]={0};size_t size=sizeof(args);
    const char *program=getprogname();
    if(!program || strcmp(program,"backboardd") ||
       sysctlbyname("kern.bootargs",args,&size,NULL,0) || size>sizeof(args))return 0;
    if(!redfin_gpu_gui_profile(args,(unsigned)size,&boot_nonce)) {
        dprintf(2,"REDFIN EAGL ABI: profile refused bytes=%zu current-profile-rates=10/30/60/90 full-panel=1\n",size);
        return 0;
    }
    const struct mach_header_64 *image=native_image(REDFIN_EAGL_IMAGE);
    const struct mach_header_64 *quartz=native_image(REDFIN_CA_IMAGE);
    if(!image_uuid(image,redfin_eagl_uuid) || !image_uuid(quartz,redfin_ca_uuid))goto refuse;
    uintptr_t *uniform_slot=(uintptr_t *)((uintptr_t)quartz+REDFIN_CA_UNIFORM_SLOT_RVA);
    uintptr_t *supported_slot=(uintptr_t *)((uintptr_t)quartz+REDFIN_CA_SUPPORTED_SLOT_RVA);
    if(*uniform_slot!=(uintptr_t)quartz+REDFIN_CA_UNIFORM_RVA ||
       *supported_slot!=(uintptr_t)quartz+REDFIN_CA_SUPPORTED_RVA)goto refuse;
    Class cls=objc_getClass("EAGLContext");
    if(!cls)goto refuse;
    for(unsigned i=0;i<sizeof(redfin_eagl_methods)/sizeof(redfin_eagl_methods[0]);i++) {
        const struct redfin_eagl_method *expected=&redfin_eagl_methods[i];
        SEL sel=sel_registerName(expected->name);
        Method method=expected->meta?class_getClassMethod(cls,sel):class_getInstanceMethod(cls,sel);
        const char *types=method?method_getTypeEncoding(method):NULL;
        IMP implementation=method?method_getImplementation(method):NULL;
        if(!types || strcmp(types,expected->types) ||
           (uintptr_t)implementation!=(uintptr_t)image+expected->rva) {
            dprintf(2,"REDFIN EAGL ABI: boot=%016llx method=%s mismatch\n",boot_nonce,expected->name);
            goto refuse;
        }
    }
    /* Refuse the software fallback before changing EAGLContext. No draw here. */
    const int attrs[]={0x22,0x1908,0x30,24,0x31,8,0x33,0x38,0x36,3,0x37,0,0};
    OSMesaContext probe=OSMesaCreateContextAttribs(attrs,NULL);
    unsigned char pixels[16*16*4]={0};
    bool hardware=probe && OSMesaMakeCurrent(probe,pixels,0x1401,16,16) && redfin_eagl_hardware();
    if(hardware) {
        int major=0,minor=0;glGetIntegerv(0x821b,&major);glGetIntegerv(0x821c,&minor);
        hardware=major>=3;
        dprintf(2,"REDFIN EAGL ABI: boot=%016llx UUID=%s macro=%u TLS=%u GLES=%d.%d renderer=%s\n",
            boot_nonce,REDFIN_EAGL_UUID,REDFIN_EAGL_MACRO_BIAS,REDFIN_EAGL_TLS_OFFSET,
            major,minor,glGetString(0x1f01));
    }
    OSMesaMakeCurrent(NULL,NULL,0,0,0);
    if(probe)OSMesaDestroyContext(probe);
    if(!hardware)goto refuse;
    /* A private copy of one data page, as in preferred inject.c. No code or
     * shared-cache file is patched, and the original function is still called. */
    vm_address_t page=(vm_address_t)uniform_slot & ~(vm_address_t)(vm_page_size-1);
    if(vm_protect(mach_task_self(),page,vm_page_size,FALSE,
                  VM_PROT_READ|VM_PROT_WRITE|VM_PROT_COPY)!=KERN_SUCCESS)goto refuse;
    original_uniform=(void *)*uniform_slot;
    __atomic_store_n(uniform_slot,(uintptr_t)observe_uniform,__ATOMIC_RELEASE);
    if(vm_protect(mach_task_self(),page,vm_page_size,FALSE,VM_PROT_READ)!=KERN_SUCCESS)
        dprintf(2,"REDFIN EAGL ABI: private CA data page remains writable\n");
    dprintf(2,"REDFIN EAGL CA: boot=%016llx actual QuartzCore function uniforms connected\n",boot_nonce);
    return 1;
refuse:
    dprintf(2,"REDFIN EAGL ABI: boot=%016llx refused before method replacement\n",boot_nonce);
    return 0;
}

void redfin_eagl_mark_installed(unsigned methods)
{
    installed_methods=methods;
    dprintf(2,"REDFIN EAGL INSTALLED: boot=%016llx pid=%d methods=%u wrappers=%u native-prefix=%u\n",
        boot_nonce,getpid(),methods,REDFIN_EAGL_WRAPPERS,REDFIN_EAGL_MACRO_BIAS);
}
int redfin_eagl_installed(void){return installed_methods==REDFIN_EAGL_METHODS;}

void redfin_eagl_frame(unsigned frame,unsigned draws,unsigned triangles,
                       unsigned shared,unsigned copied,unsigned errors)
{
    if(frame<=4 || !(frame%60))
        dprintf(2,"REDFIN EAGL FRAME: boot=%016llx pid=%d frame=%u draws=%u triangles=%u shared=%u copied=%u errors=%u\n",
            boot_nonce,getpid(),frame,draws,triangles,shared,copied,errors);
}
