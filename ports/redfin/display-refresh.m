/* SPDX-License-Identifier: MIT */
/* Native20H392 display periods and app caps, bound to measured panel mode.
 * CADisplay refreshRate/hardwareRefreshRate are SECONDS PER FRAME. UIScreen
 * maximumFramesPerSecond is Hz; its private _refreshRate is also a period.
 * No UIKit/QuartzCore ivar offsets or hardcoded method addresses are used. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <sys/sysctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include "gui-profile.h"
#include "graphics-exec-scope.h"

static double (*ca_period)(id,SEL),(*ca_hardware)(id,SEL),(*ca_heartbeat)(id,SEL),(*ui_period)(id,SEL);
static NSInteger (*ui_maximum)(id,SEL),(*ui_private_maximum)(id,SEL);
static Class display_class;
static unsigned verified_hz,observations;
static __thread bool in_refresh;
static char boot_nonce[17];

static BOOL method_abi(Class cls,const char *name,const char *types,BOOL meta)
{
    Method m=meta ? class_getClassMethod(cls,sel_registerName(name)) :
        class_getInstanceMethod(cls,sel_registerName(name));
    return m && !strcmp(method_getTypeEncoding(m),types);
}
static BOOL image_uuid(IMP implementation,const unsigned char expected[16])
{
    Dl_info info={};if (!dladdr((void *)implementation,&info) || !info.dli_fbase) return NO;
    const struct mach_header_64 *h=info.dli_fbase;
    if (h->magic!=MH_MAGIC_64 || h->ncmds>4096 || h->sizeofcmds>1048576) return NO;
    const unsigned char *at=(const unsigned char *)(h+1),*end=at+h->sizeofcmds;
    for (unsigned i=0;i<h->ncmds;++i) {
        if ((size_t)(end-at)<sizeof(struct load_command)) return NO;
        const struct load_command *c=(const struct load_command *)at;
        if (c->cmdsize<sizeof(*c) || c->cmdsize>(size_t)(end-at)) return NO;
        if (c->cmd==LC_UUID) return c->cmdsize==sizeof(struct uuid_command) &&
            !memcmp(((const struct uuid_command *)c)->uuid,expected,16);
        at+=c->cmdsize;
    }
    return NO;
}
static void refresh_log(const char *what,double period,long maximum)
{
    if (__atomic_fetch_add(&observations,1,__ATOMIC_RELAXED)>=12) return;
    char line[384];int n=snprintf(line,sizeof(line),
        "REDFIN REFRESH: boot=%s pid=%d %s physical-hz=90 period-seconds=%.9f app-max-fps=%ld verified-registry=1\n",
        boot_nonce,getpid(),what,period,maximum);
    if (n<=0 || (size_t)n>=sizeof(line)) return;
    int fd=open("/private/var/mobile/Library/Logs/redfin-refresh.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if (fd>=0) {(void)write(fd,line,(size_t)n);close(fd);}
}
static unsigned physical_rate(void)
{
    unsigned cached=__atomic_load_n(&verified_hz,__ATOMIC_ACQUIRE);if (cached) return cached;
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("IOMobileFramebuffer"));
    if (!service) return 0;
    CFTypeRef rate=IORegistryEntryCreateCFProperty(service,CFSTR("RedfinVerifiedRefreshHz"),NULL,0);
    CFTypeRef verified=IORegistryEntryCreateCFProperty(service,CFSTR("RedfinPhysicalRefreshVerified"),NULL,0);
    unsigned hz=0;
    BOOL valid=rate && CFGetTypeID(rate)==CFNumberGetTypeID() &&
        CFNumberGetValue((CFNumberRef)rate,kCFNumberIntType,&hz) &&
        hz==90 && verified==kCFBooleanTrue;
    if (rate) CFRelease(rate);if (verified) CFRelease(verified);IOObjectRelease(service);
    if (valid) __atomic_store_n(&verified_hz,hz,__ATOMIC_RELEASE);
    return valid ? hz : 0;
}
static BOOL main_display(id object)
{
    if (in_refresh || !physical_rate()) return NO;
    in_refresh=true;
    id main=((id (*)(id,SEL))objc_msgSend)(display_class,sel_registerName("mainDisplay"));
    in_refresh=false;return object==main;
}
static BOOL main_screen(id object)
{
    return physical_rate() && ((BOOL (*)(id,SEL))objc_msgSend)(object,sel_registerName("_isMainScreen"));
}
static double redfin_ca_period(id object,SEL selector)
{
    if (!main_display(object)) return ca_period(object,selector);
    double period=1.0/90.0;refresh_log("CADisplay.refreshRate",period,90);return period;
}
static double redfin_ca_hardware(id object,SEL selector)
{
    if (!main_display(object)) return ca_hardware(object,selector);
    double period=1.0/90.0;refresh_log("CADisplay.hardwareRefreshRate",period,90);return period;
}
static double redfin_ca_heartbeat(id object,SEL selector)
{
    if (!main_display(object)) return ca_heartbeat(object,selector);
    refresh_log("CADisplay.heartbeatRate",1.0/90.0,90);return 1.0/90.0;
}
static double redfin_ui_period(id object,SEL selector)
{return main_screen(object) ? 1.0/90.0 : ui_period(object,selector);}
static NSInteger redfin_ui_maximum(id object,SEL selector)
{
    if (!main_screen(object)) return ui_maximum(object,selector);
    refresh_log("UIScreen.maximumFramesPerSecond",1.0/90.0,90);return 90;
}
static NSInteger redfin_ui_private_maximum(id object,SEL selector)
{return main_screen(object) ? 90 : ui_private_maximum(object,selector);}

__attribute__((constructor)) static void redfin_refresh_install(void)
{
    char args[608]={};size_t bytes=sizeof(args);
    if (getuid()!=501 || sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || bytes>sizeof(args) ||
        !redfin_ui_fullscreen(args,(unsigned)bytes)) return;
    const char *nonce=strstr(args,"redfinbootid=0x");if (!nonce || strlen(nonce+15)<16) return;
    memcpy(boot_nonce,nonce+15,16);
    static const unsigned char quartz[16]={REDFIN_QUARTZ_UUID_BYTES},uikit[16]={REDFIN_UIKIT_UUID_BYTES};
    display_class=objc_getClass("CADisplay");
    if (!method_abi(display_class,"mainDisplay","@16@0:8",YES) ||
        !method_abi(display_class,"refreshRate","d16@0:8",NO) ||
        !method_abi(display_class,"hardwareRefreshRate","d16@0:8",NO) ||
        !method_abi(display_class,"heartbeatRate","d16@0:8",NO)) return;
    Method period=class_getInstanceMethod(display_class,sel_registerName("refreshRate"));
    Method hardware=class_getInstanceMethod(display_class,sel_registerName("hardwareRefreshRate"));
    Method heartbeat=class_getInstanceMethod(display_class,sel_registerName("heartbeatRate"));
    if (!image_uuid(method_getImplementation(period),quartz) || !image_uuid(method_getImplementation(hardware),quartz) ||
        !image_uuid(method_getImplementation(heartbeat),quartz)) return;
    ca_period=(double (*)(id,SEL))method_getImplementation(period);
    ca_hardware=(double (*)(id,SEL))method_getImplementation(hardware);
    ca_heartbeat=(double (*)(id,SEL))method_getImplementation(heartbeat);
    method_setImplementation(period,(IMP)redfin_ca_period);method_setImplementation(hardware,(IMP)redfin_ca_hardware);
    method_setImplementation(heartbeat,(IMP)redfin_ca_heartbeat);
    Class screen=objc_getClass("UIScreen");
    if (!screen || !method_abi(screen,"_isMainScreen","B16@0:8",NO) ||
        !method_abi(screen,"maximumFramesPerSecond","q16@0:8",NO) ||
        !method_abi(screen,"_maximumFramesPerSecond","q16@0:8",NO) ||
        !method_abi(screen,"_refreshRate","d16@0:8",NO)) return;
    Method maximum=class_getInstanceMethod(screen,sel_registerName("maximumFramesPerSecond"));
    Method private_maximum=class_getInstanceMethod(screen,sel_registerName("_maximumFramesPerSecond"));
    Method ui=class_getInstanceMethod(screen,sel_registerName("_refreshRate"));
    if (!image_uuid(method_getImplementation(maximum),uikit) || !image_uuid(method_getImplementation(private_maximum),uikit) ||
        !image_uuid(method_getImplementation(ui),uikit)) return;
    ui_maximum=(NSInteger (*)(id,SEL))method_getImplementation(maximum);
    ui_private_maximum=(NSInteger (*)(id,SEL))method_getImplementation(private_maximum);
    ui_period=(double (*)(id,SEL))method_getImplementation(ui);
    method_setImplementation(maximum,(IMP)redfin_ui_maximum);
    method_setImplementation(private_maximum,(IMP)redfin_ui_private_maximum);
    method_setImplementation(ui,(IMP)redfin_ui_period);
}
