/* SPDX-License-Identifier: MIT */
/* Validate the installed Metal superclass ABI before changing a method or
 * constructing a driver. No instruction addresses or Apple ivar offsets. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include "metal-abi.h"

static pthread_once_t checked=PTHREAD_ONCE_INIT;
static int compatible;

static int image_matches(IMP method)
{
    Dl_info info={0};
    if (!dladdr((void *)method,&info) || !info.dli_fbase) return 0;
    const struct mach_header_64 *h=info.dli_fbase;
    if (h->magic!=MH_MAGIC_64 || h->ncmds>4096 || h->sizeofcmds>1048576) return 0;
    const unsigned char *at=(const unsigned char *)(h+1),*end=at+h->sizeofcmds;
    for (unsigned i=0;i<h->ncmds;++i) {
        if ((size_t)(end-at)<sizeof(struct load_command)) return 0;
        const struct load_command *c=(const struct load_command *)at;
        if (c->cmdsize<sizeof(*c) || c->cmdsize>(size_t)(end-at)) return 0;
        if (c->cmd==LC_UUID) return c->cmdsize==sizeof(struct uuid_command) &&
            !memcmp(((const struct uuid_command *)c)->uuid,redfin_metal_uuid,16);
        at+=c->cmdsize;
    }
    return 0;
}

static void check_abi(void)
{
    for (unsigned i=0;i<sizeof(redfin_metal_methods)/sizeof(redfin_metal_methods[0]);++i) {
        const struct redfin_metal_method *wanted=&redfin_metal_methods[i];
        Method method=class_getInstanceMethod(objc_getClass(wanted->cls),sel_registerName(wanted->name));
        if (!method || strcmp(method_getTypeEncoding(method),wanted->types) ||
            !image_matches(method_getImplementation(method))) {
            dprintf(2,"REDFIN METAL ABI: refused class=%s selector=%s\n",wanted->cls,wanted->name);
            return;
        }
    }
    static const struct {const char *cls,*name,*type;} ivars[]={
        {"_MTLCommandQueue","_commandBufferSemaphore","@"},
        {"_MTLCommandQueue","_completionQueue","@"},
        {"_MTLCommandBuffer","_needsCommandBufferSemaphoreSignal","B"},
    };
    for (unsigned i=0;i<sizeof(ivars)/sizeof(ivars[0]);++i) {
        Class cls=objc_getClass(ivars[i].cls);
        Ivar ivar=class_getInstanceVariable(cls,ivars[i].name);
        const char *type=ivar ? ivar_getTypeEncoding(ivar) : NULL;
        ptrdiff_t offset=ivar ? ivar_getOffset(ivar) : -1;
        size_t bytes=ivars[i].type[0]=='B' ? 1 : sizeof(void *);
        if (!type || type[0]!=ivars[i].type[0] || offset<0 ||
            (size_t)offset>class_getInstanceSize(cls) ||
            bytes>class_getInstanceSize(cls)-(size_t)offset) {
            dprintf(2,"REDFIN METAL ABI: refused ivar=%s.%s\n",ivars[i].cls,ivars[i].name);
            return;
        }
    }
    compatible=1;
    dprintf(2,"REDFIN METAL ABI: native Metal superclass UUID/selectors/ivars accepted\n");
}

int redfin_metal_abi_ready(void)
{ return !pthread_once(&checked,check_abi) && compatible; }

static int number(io_service_t service,CFStringRef key,int wanted)
{
    CFTypeRef value=IORegistryEntryCreateCFProperty(service,key,NULL,0);int actual=0;
    int valid=value && CFGetTypeID(value)==CFNumberGetTypeID() &&
        CFNumberGetValue(value,kCFNumberIntType,&actual) && actual==wanted;
    if (value) CFRelease(value);
    return valid;
}

int redfin_metal_hardware_ready(void)
{
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("RedwoodGPU"));
    int valid=service && number(service,CFSTR("chip-id"),0x06020001) &&
        number(service,CFSTR("RedfinRuntimeABI"),1) &&
        (number(service,CFSTR("RedfinMetalPolicy"),1) ||
         number(service,CFSTR("RedfinMetalPolicy"),2));
    if (service) IOObjectRelease(service);
    return valid;
}
