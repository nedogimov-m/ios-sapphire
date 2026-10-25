/* SPDX-License-Identifier: MIT
 * A small backboardd-only loader. Stock Apple libraries stay in place; the
 * Mesa bridge is opened only for the exact opt-in GUI3 and a real A620 owner.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include "gui-profile.h"
#include "graphics-memory-report.h"

static bool property(io_service_t service,const char *name,int expected)
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

__attribute__((constructor)) static void redfin_graphics_load(void)
{
    const char *name=getprogname();
    if(!name || strcmp(name,"backboardd"))return;
    char args[608]={0};size_t size=sizeof(args);uint64_t nonce=0;
    if(sysctlbyname("kern.bootargs",args,&size,NULL,0) || size>sizeof(args))return;
    if(!redfin_gpu_gui_profile(args,(unsigned)size,&nonce)) {
        dprintf(2,"REDFIN EAGL LOADER: profile refused bytes=%zu current-profile-rates=10/30/60/90 full-panel=1\n",size);
        return;
    }
    /* Separate actual-ABI library: QuartzCore periods need the measured panel
     * mode in the event server as well as app/UIScreen processes. */
    (void)dlopen("/redfin/lib/libredfin-refresh.dylib",RTLD_NOW|RTLD_LOCAL);
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("RedwoodGPU"));
    bool valid=service && property(service,"chip-id",0x06020001) &&
        property(service,"RedfinRuntimeABI",1);
    if(service)IOObjectRelease(service);
    if(!valid){dprintf(2,"REDFIN EAGL LOADER: boot=%016llx native A620 absent\n",nonce);return;}
    dprintf(2,"REDFIN EAGL LOADER: boot=%016llx pid=%d GUI3 native A620\n",nonce,getpid());
    redfin_graphics_memory_report("loader-before",0);
    /* These must precede dlopen: Mesa reads its driver choice on first use. */
    setenv("OSMESA_SOFTWARE","0",1);
    /* Native A620 has512KiB GMEM. Let freedreno select its ordinary tiled
     * path instead of forcing every system composition through DRAM. */
    setenv("FD_MESA_DEBUG","",1);
    setenv("MESA_DEBUG","context",1);
    void *apple=dlopen("/System/Library/Frameworks/OpenGLES.framework/OpenGLES",RTLD_NOW|RTLD_LOCAL);
    if(!apple){dprintf(2,"REDFIN EAGL LOADER: OpenGLES load failed: %s\n",dlerror());return;}
    void *bridge=dlopen("/redfin/lib/libredfin-eagl.dylib",RTLD_NOW|RTLD_LOCAL);
    if(!bridge){dprintf(2,"REDFIN EAGL LOADER: bridge load failed: %s\n",dlerror());return;}
    int (*installed)(void)=(int (*)(void))dlsym(bridge,"redfin_eagl_installed");
    dprintf(2,"REDFIN EAGL LOADER: boot=%016llx installed=%d\n",nonce,installed?installed():0);
    redfin_graphics_memory_report("loader-after",0);
    /* Both handles stay loaded: ObjC method implementations refer into them. */
}
