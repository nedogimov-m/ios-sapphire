/* SPDX-License-Identifier: MIT */
/* Native20H392 heartbeat configuration and app caps, bound to measured mode.
 * The native CLCD backend reads CA_HEARTBEAT_RATE in Hz before creating its
 * timer. CADisplay's actual period getters and timestamps remain native.
 * No UIKit/QuartzCore ivar offsets or hardcoded method addresses are used. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <mach/mach_time.h>
#include <sys/sysctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "gui-profile.h"
#include "graphics-exec-scope.h"
#include "display-mode.h"
extern void redfin_backlight_system_install(const char *);
extern void redfin_server_admission_install(const char *);

static double (*ui_period)(id,SEL);
static NSInteger (*ui_maximum)(id,SEL),(*ui_private_maximum)(id,SEL);
static unsigned verified_hz,observations;
static char boot_nonce[17];
static bool refresh_policy_active;
static __thread bool in_info_policy;
static CFDictionaryRef high_refresh_info;
static id (*bundle_info_value)(id,SEL,NSString *);
static void refresh_policy_log(const char *);

/* Public per-app opt-in required by iOS for rates above60. Preserve the
 * original main-bundle dictionary and add the documented key in a retained
 * process-local copy only after the physical90Hz contract is verified. */
static unsigned physical_rate(void);
static BOOL high_refresh_bundle(CFBundleRef bundle)
{
    return refresh_policy_active && bundle && !in_info_policy && bundle==CFBundleGetMainBundle() && physical_rate()==90;
}
static CFTypeRef redfin_bundle_value(CFBundleRef bundle,CFStringRef key)
{
    CFTypeRef original=CFBundleGetValueForInfoDictionaryKey(bundle,key);
    if(!key||!CFEqual(key,CFSTR("CADisableMinimumFrameDurationOnPhone"))||!high_refresh_bundle(bundle))return original;
    refresh_policy_log("CFBundleGetValueForInfoDictionaryKey");
    return kCFBooleanTrue;
}
static CFDictionaryRef redfin_bundle_dictionary(CFBundleRef bundle)
{
    CFDictionaryRef original=CFBundleGetInfoDictionary(bundle);
    if(!high_refresh_bundle(bundle))return original;
    in_info_policy=true;
    CFDictionaryRef cached=__atomic_load_n(&high_refresh_info,__ATOMIC_ACQUIRE);
    if(!cached) {
        CFMutableDictionaryRef copy=original?CFDictionaryCreateMutableCopy(NULL,0,original):
            CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
        if(copy) {
            CFDictionarySetValue(copy,CFSTR("CADisableMinimumFrameDurationOnPhone"),kCFBooleanTrue);
            CFDictionaryRef expected=NULL;
            if(__atomic_compare_exchange_n(&high_refresh_info,&expected,copy,false,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE))
                cached=copy;
            else {CFRelease(copy);cached=expected;}
        }
    }
    in_info_policy=false;
    if(cached)refresh_policy_log("CFBundleGetInfoDictionary");
    return cached?cached:original;
}
/* dyld excludes the defining interposer image when binding its own calls to
 * the original public functions. Other bundles retain their native values. */
__attribute__((used,section("__DATA,__interpose")))
static const struct {
    CFTypeRef (*replacement)(CFBundleRef,CFStringRef);
    CFTypeRef (*original)(CFBundleRef,CFStringRef);
} redfin_info_value_interpose={redfin_bundle_value,CFBundleGetValueForInfoDictionaryKey};
__attribute__((used,section("__DATA,__interpose")))
static const struct {
    CFDictionaryRef (*replacement)(CFBundleRef);
    CFDictionaryRef (*original)(CFBundleRef);
} redfin_info_dictionary_interpose={redfin_bundle_dictionary,CFBundleGetInfoDictionary};

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
static void refresh_policy_log(const char *method)
{
    static bool reported;
    if(__atomic_exchange_n(&reported,true,__ATOMIC_RELAXED))return;
    char line[384];int n=snprintf(line,sizeof(line),
        "REDFIN REFRESH POLICY: boot=%s pid=%d main-bundle-public-opt-in=1 physical-hz=90 source=%s\n",
        boot_nonce,getpid(),method);
    if(n<=0||(size_t)n>=sizeof(line))return;
    int fd=open("/private/var/mobile/Library/Logs/redfin-refresh.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if(fd>=0){(void)write(fd,line,(size_t)n);close(fd);}
}
static unsigned physical_rate(void)
{
    unsigned cached=__atomic_load_n(&verified_hz,__ATOMIC_ACQUIRE);if (cached) return cached;
    if(in_info_policy)return 0;
    in_info_policy=true;
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("IOMobileFramebuffer"));
    if (!service) {in_info_policy=false;return 0;}
    CFTypeRef rate=IORegistryEntryCreateCFProperty(service,CFSTR("RedfinVerifiedRefreshHz"),NULL,0);
    CFTypeRef verified=IORegistryEntryCreateCFProperty(service,CFSTR("RedfinPhysicalRefreshVerified"),NULL,0);
    unsigned hz=0;
    BOOL valid=rate && CFGetTypeID(rate)==CFNumberGetTypeID() &&
        CFNumberGetValue((CFNumberRef)rate,kCFNumberIntType,&hz) &&
        hz==90 && verified==kCFBooleanTrue;
    if (rate) CFRelease(rate);if (verified) CFRelease(verified);IOObjectRelease(service);
    if (valid) __atomic_store_n(&verified_hz,hz,__ATOMIC_RELEASE);
    in_info_policy=false;
    return valid ? hz : 0;
}
static id redfin_bundle_info_value(id object,SEL selector,NSString *key)
{
    id value=bundle_info_value(object,selector,key);
    if(refresh_policy_active && object==NSBundle.mainBundle &&
       [key isEqualToString:@"CADisableMinimumFrameDurationOnPhone"] && physical_rate()==90) {
        refresh_policy_log("NSBundle.objectForInfoDictionaryKey:");
        return @YES;
    }
    return value;
}
static BOOL main_screen(id object)
{
    return physical_rate() && ((BOOL (*)(id,SEL))objc_msgSend)(object,sel_registerName("_isMainScreen"));
}
/* Publish this environment only in the window server, before its native
 * heartbeat is cached. Both the actual20H392 reader and the physical/native
 * kernel dictionary are audited; there is no synthetic callback clock. */
static void configure_native_heartbeat(void)
{
    const char *process=getprogname();if(!process||strcmp(process,"backboardd"))return;
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("AppleCLCD"));
    CFTypeRef abi=service?IORegistryEntryCreateCFProperty(service,CFSTR("RedfinNativeCadenceABI"),NULL,0):NULL;
    CFTypeRef clock=service?IORegistryEntryCreateCFProperty(service,CFSTR("RedfinCadenceClockHz"),NULL,0):NULL;
    CFTypeRef refresh=service?IORegistryEntryCreateCFProperty(service,CFSTR("IOMFBDisplayRefresh"),NULL,0):NULL;
    int version=0,minimum=0,step=0;int64_t reported_clock=0;
    mach_timebase_info_data_t scale={0};
    BOOL valid=physical_rate()==90&&abi&&CFGetTypeID(abi)==CFNumberGetTypeID()&&
        CFNumberGetValue((CFNumberRef)abi,kCFNumberIntType,&version)&&version==1&&
        clock&&CFGetTypeID(clock)==CFNumberGetTypeID()&&
        CFNumberGetValue((CFNumberRef)clock,kCFNumberSInt64Type,&reported_clock)&&reported_clock>0&&
        refresh&&CFGetTypeID(refresh)==CFDictionaryGetTypeID()&&
        mach_timebase_info(&scale)==KERN_SUCCESS&&scale.numer&&scale.denom;
    struct redfin_display_refresh_parameters wanted={0};
    if(valid) {
        uint64_t native_clock=(UINT64_C(1000000000)*scale.denom+scale.numer/2)/scale.numer;
        CFTypeRef a=CFDictionaryGetValue((CFDictionaryRef)refresh,CFSTR("displayMinRefreshInterval"));
        CFTypeRef b=CFDictionaryGetValue((CFDictionaryRef)refresh,CFSTR("displayRefreshStepMachTime"));
        valid=native_clock==(uint64_t)reported_clock&&
            redfin_display_refresh_parameters(90,native_clock,&wanted)&&
            a&&b&&CFGetTypeID(a)==CFNumberGetTypeID()&&CFGetTypeID(b)==CFNumberGetTypeID()&&
            CFNumberGetValue((CFNumberRef)a,kCFNumberIntType,&minimum)&&
            CFNumberGetValue((CFNumberRef)b,kCFNumberIntType,&step)&&
            minimum==(int)wanted.minimum_interval_32_32&&step==(int)wanted.step_mach_ticks;
    }
    BOOL installed=valid&&setenv("CA_HEARTBEAT_RATE","90",1)==0;
    if(abi)CFRelease(abi);if(clock)CFRelease(clock);if(refresh)CFRelease(refresh);if(service)IOObjectRelease(service);
    char line[384];int n=snprintf(line,sizeof(line),
        "REDFIN NATIVE CADENCE SETUP: boot=%s pid=%d requested-hz=90 verified-kernel-contract=%u environment-installed=%u native-period-getters=1\n",
        boot_nonce,getpid(),valid,installed);
    int fd=open("/private/var/mobile/Library/Logs/redfin-refresh.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if(fd>=0){if(n>0&&(size_t)n<sizeof(line))(void)write(fd,line,(size_t)n);close(fd);}
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
    redfin_server_admission_install(boot_nonce);
    redfin_backlight_system_install(boot_nonce);
    refresh_policy_active=true;
    static const unsigned char quartz[16]={REDFIN_QUARTZ_UUID_BYTES},uikit[16]={REDFIN_UIKIT_UUID_BYTES};
    static const unsigned char foundation[16]={REDFIN_FOUNDATION_UUID_BYTES};
    Class bundle=objc_getClass("NSBundle");
    if(method_abi(bundle,"objectForInfoDictionaryKey:","@24@0:8@16",NO)) {
        Method method=class_getInstanceMethod(bundle,sel_registerName("objectForInfoDictionaryKey:"));
        if(image_uuid(method_getImplementation(method),foundation)) {
            bundle_info_value=(id (*)(id,SEL,NSString *))method_getImplementation(method);
            method_setImplementation(method,(IMP)redfin_bundle_info_value);
        }
    }
    Class display_class=objc_getClass("CADisplay");
    if (!method_abi(display_class,"mainDisplay","@16@0:8",YES) ||
        !method_abi(display_class,"refreshRate","d16@0:8",NO) ||
        !method_abi(display_class,"hardwareRefreshRate","d16@0:8",NO) ||
        !method_abi(display_class,"heartbeatRate","d16@0:8",NO)) return;
    Method period=class_getInstanceMethod(display_class,sel_registerName("refreshRate"));
    Method hardware=class_getInstanceMethod(display_class,sel_registerName("hardwareRefreshRate"));
    Method heartbeat=class_getInstanceMethod(display_class,sel_registerName("heartbeatRate"));
    if (!image_uuid(method_getImplementation(period),quartz) || !image_uuid(method_getImplementation(hardware),quartz) ||
        !image_uuid(method_getImplementation(heartbeat),quartz)) return;
    configure_native_heartbeat();
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
