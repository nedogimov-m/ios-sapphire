/* SPDX-License-Identifier: MIT */
/* Redfin has a native standalone backlight, without Apple's synchronous
 * IOMFB brightness transport. Let CoreBrightness select its native backlight
 * path. Composition and app Metal are independent of that capability. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <IOKit/IOKitLib.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include "native-image-uuid.h"
#include "backlight-manual.h"
extern void redfin_backlight_failures_prepare(const char *);

static BOOL (*native_brightness_available)(id,SEL);
static NSInteger (*native_display_type)(id,SEL);
static BOOL (*native_use_sync)(id,SEL,id);
static BOOL (*native_find_displays)(id,SEL),(*native_find_backlight)(id,SEL);
static BOOL (*native_container_start)(id,SEL),(*native_container_setup)(id,SEL);
static void (*native_module_start)(id,SEL);
static void (*native_manual_set)(id,SEL,float,id,NSUInteger);
static BOOL (*native_manual_available)(id,SEL);
static BOOL (*native_display_external)(id,SEL);
static kern_return_t (*native_set_properties)(io_registry_entry_t,CFTypeRef);
static bool manual_fallback_admitted;
static char backlight_nonce[17];
static unsigned backlight_observations;
static unsigned backlight_context_observations;

static void backlight_log(const char *format,...)
{
    if(__atomic_fetch_add(&backlight_observations,1,__ATOMIC_RELAXED)>=32)return;
    char line[768];int prefix=snprintf(line,sizeof(line),"REDFIN NATIVE BACKLIGHT: boot=%s ",backlight_nonce);
    if(prefix<0||(size_t)prefix>=sizeof(line))return;
    va_list args;va_start(args,format);int n=vsnprintf(line+prefix,sizeof(line)-(size_t)prefix,format,args);va_end(args);
    if(n<0||(size_t)n>=sizeof(line)-(size_t)prefix-1)return;
    size_t bytes=(size_t)(prefix+n);line[bytes++]='\n';
    int fd=open("/private/var/mobile/Library/Logs/redfin-refresh.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if(fd>=0){(void)write(fd,line,bytes);close(fd);}
}
static BOOL backlight_uint(NSDictionary *properties,NSString *key,uint64_t wanted)
{
    id value=properties[key];return [value isKindOfClass:NSNumber.class]&&[value unsignedLongLongValue]==wanted;
}
static BOOL backlight_transport_present(void)
{
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("AppleARMBacklight"));
    CFMutableDictionaryRef raw=NULL;
    kern_return_t result=service?IORegistryEntryCreateCFProperties(service,&raw,NULL,0):KERN_FAILURE;
    if(service)IOObjectRelease(service);
    NSDictionary *properties=CFBridgingRelease(raw);
    NSDictionary *parameters=[properties[@"IODisplayParameters"] isKindOfClass:NSDictionary.class]?
        properties[@"IODisplayParameters"]:nil;
    NSDictionary *brightness=[parameters[@"brightness"] isKindOfClass:NSDictionary.class]?parameters[@"brightness"]:nil;
    id level=brightness[@"value"],ignore=properties[@"ignore-IOMFB"];
    uint32_t separate=0;
    if([ignore isKindOfClass:NSData.class]&&[ignore length]==sizeof(separate))
        memcpy(&separate,[ignore bytes],sizeof(separate));
    return result==KERN_SUCCESS&&separate==1&&
        backlight_uint(properties,@"RedfinDisplayControlABI",1)&&backlight_uint(properties,@"RedfinCoreBrightnessABI",1)&&
        backlight_uint(brightness,@"min",4)&&backlight_uint(brightness,@"max",1023)&&
        [level isKindOfClass:NSNumber.class]&&[level unsignedLongLongValue]>=4&&[level unsignedLongLongValue]<=1023;
}
static Method backlight_method(Class cls,const char *name,const char *types,const uint8_t uuid[16])
{
    Method method=cls?class_getInstanceMethod(cls,sel_registerName(name)):NULL;
    return method&&!strcmp(method_getTypeEncoding(method),types)&&
        redfin_native_image_uuid((const void *)method_getImplementation(method),uuid)?method:NULL;
}
static BOOL redfin_brightness_available(id display,SEL selector)
{
    if(native_display_type(display,sel_registerName("displayType"))==0) {
        static bool reported;
        if(!__atomic_exchange_n(&reported,true,__ATOMIC_RELAXED))
            backlight_log("integrated-display synchronous-IOMFB=unsupported standalone-native-backlight=1");
        return NO;
    }
    return native_brightness_available(display,selector);
}
static BOOL redfin_use_sync(id object,SEL selector,id display)
{
    BOOL value=native_use_sync(object,selector,display);
    backlight_log("CoreBrightness-use-sync=%u original-continued=1",value);return value;
}
static BOOL redfin_find_displays(id object,SEL selector)
{
    BOOL value=native_find_displays(object,selector);
    backlight_log("CoreBrightness-find-displays=%u original-continued=1",value);return value;
}
static BOOL redfin_find_backlight(id object,SEL selector)
{
    BOOL value=native_find_backlight(object,selector);
    backlight_log("CoreBrightness-find-backlight=%u original-continued=1",value);return value;
}
static BOOL redfin_container_start(id object,SEL selector)
{
    BOOL value=native_container_start(object,selector);
    backlight_log("CoreBrightness-container-start=%u original-continued=1",value);return value;
}
static int backlight_container_context(id object,const char *phase)
{
    BOOL report=__atomic_fetch_add(&backlight_context_observations,1,__ATOMIC_RELAXED)<8;
    Class cls=object_getClass(object);Ivar service_ivar=class_getInstanceVariable(cls,"_displayService");
    Ivar display_ivar=class_getInstanceVariable(cls,"_display"),proxy_ivar=class_getInstanceVariable(cls,"_brtCtl");
    Ivar module_ivar=class_getInstanceVariable(cls,"_displayControlModule");
    if(!service_ivar||!display_ivar||!proxy_ivar||!module_ivar||strcmp(ivar_getTypeEncoding(service_ivar),"I")||
       strcmp(ivar_getTypeEncoding(display_ivar),"@\"CADisplay\"")||
       strcmp(ivar_getTypeEncoding(proxy_ivar),"@\"<CBBrightnessProxy>\"")||
       strcmp(ivar_getTypeEncoding(module_ivar),"@\"<CBContainerModuleProtocol>\"")) {
        if(report)backlight_log("container-context phase=%s typed-native-fields=0 unchanged=1",phase);return -1;
    }
    ptrdiff_t offset=ivar_getOffset(service_ivar);uint32_t service=0;
    if(offset<0||(size_t)offset>class_getInstanceSize(cls)||sizeof(service)>class_getInstanceSize(cls)-(size_t)offset)return -1;
    memcpy(&service,(const uint8_t *)(__bridge const void *)object+offset,sizeof(service));
    id display=object_getIvar(object,display_ivar),proxy=object_getIvar(object,proxy_ivar),module=object_getIvar(object,module_ivar);
    BOOL integrated=display&&[display isKindOfClass:objc_getClass("CADisplay")]&&
        !native_display_external(display,sel_registerName("isExternal"))&&!proxy;
    if(report)backlight_log("container-context phase=%s typed-native-fields=1 service-present=%u conforms-AppleARMBacklight=%u CADisplay=%u proxy=%u display-module=%u integrated=%u state-unchanged=1",
        phase,service!=0,service&&IOObjectConformsTo(service,"AppleARMBacklight"),display!=nil,proxy!=nil,module!=nil,integrated);
    return integrated?(module?1:0):-1;
}
static BOOL redfin_container_setup(id object,SEL selector)
{
    (void)backlight_container_context(object,"before-setup");
    BOOL value=native_container_setup(object,selector);
    int state=backlight_container_context(object,"after-setup");
    if(state>=0)__atomic_store_n(&manual_fallback_admitted,!value&&state==0,__ATOMIC_RELEASE);
    backlight_log("CoreBrightness-module-setup=%u original-continued=1",value);return value;
}
static void redfin_module_start(id object,SEL selector)
{
    native_module_start(object,selector);
    backlight_log("CoreBrightness-display-module-start=1 original-continued=1");
}
static BOOL redfin_manual_available(id object,SEL selector)
{
    BOOL available=native_manual_available(object,selector);
    return available||(__atomic_load_n(&manual_fallback_admitted,__ATOMIC_ACQUIRE)&&backlight_transport_present());
}
static void redfin_manual_set(id object,SEL selector,float value,id reason,NSUInteger options)
{
    /* Native notifications, ownership, logical state and preferences always
     * run first. Option2 is the audited request-to-driver bit; uncommitted
     * brightness transaction samples retain their original behavior. */
    native_manual_set(object,selector,value,reason,options);
    uint32_t level=0;
    if(!(options&2)||!redfin_manual_backlight_level(value,&level)||
       !__atomic_load_n(&manual_fallback_admitted,__ATOMIC_ACQUIRE))return;
    if(native_manual_available(object,sel_registerName("isBrightnessLevelControlAvailable")))return;
    if(!backlight_transport_present())return;
    io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("AppleARMBacklight"));
    NSDictionary *request=@{@"brightness":@(level)};
    kern_return_t result=service?native_set_properties(service,(__bridge CFTypeRef)request):KERN_FAILURE;
    if(service)IOObjectRelease(service);
    backlight_log("manual-native-request raw-DBV=%u result=%#x native-processing-continued=1 actual-completion-required=1",level,result);
}

void redfin_backlight_system_install(const char *nonce)
{
    static bool attempted;
    const char *process=getprogname();
    if(attempted||!nonce||strlen(nonce)!=16||!process||strcmp(process,"backboardd"))return;
    attempted=true;memcpy(backlight_nonce,nonce,16);
    if(!backlight_transport_present()){backlight_log("refused native-backlight-contract=0 unchanged=1");return;}
    redfin_backlight_failures_prepare(nonce);
    void *cb=dlopen("/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness",RTLD_NOW|RTLD_LOCAL);
    if(!cb){backlight_log("refused native-CoreBrightness=0 unchanged=1");return;}
    const uint8_t quartz[16]={REDFIN_QUARTZ_UUID_BYTES},core[16]={REDFIN_CB_UUID_BYTES},backboard[16]={REDFIN_BKD_UUID_BYTES};
    const uint8_t iokit[16]={REDFIN_IOKIT_UUID_BYTES};
    void *set_properties=dlsym(RTLD_DEFAULT,"IORegistryEntrySetCFProperties");
    if(!redfin_native_image_uuid(set_properties,iokit)) {
        backlight_log("refused native-IOKit-set-properties-ABI=0 unchanged=1");return;
    }
    Class display=objc_getClass("CAWindowServerDisplay"),control=objc_getClass("BLControl");
    Class container=objc_getClass("CBDisplayContaineriOS"),module=objc_getClass("CBDisplayModuleiOS");
    Class brightness=objc_getClass("BKDisplayBrightnessController");
    Method available=backlight_method(display,"brightnessAvailable","B16@0:8",quartz);
    Method type=backlight_method(display,"displayType","q16@0:8",quartz);
    Method external=backlight_method(objc_getClass("CADisplay"),"isExternal","B16@0:8",quartz);
    Method sync=backlight_method(control,"useSyncBrightnessTransactionForDisplay:","B24@0:8@16",core);
    Method find=backlight_method(control,"findDisplays","B16@0:8",core);
    Method legacy=backlight_method(control,"findBacklight","B16@0:8",core);
    Method start=backlight_method(container,"start","B16@0:8",core);
    Method setup=backlight_method(container,"setupInternalModules","B16@0:8",core);
    Method module_start=backlight_method(module,"start","v16@0:8",core);
    Method manual=backlight_method(brightness,"setBrightnessLevel:reason:options:","v36@0:8f16@20Q28",backboard);
    Method manual_available=backlight_method(brightness,"isBrightnessLevelControlAvailable","B16@0:8",backboard);
    if(!available||!type||!external||!sync||!find||!legacy||!start||!setup||!module_start||!manual||!manual_available) {
        backlight_log("refused native-method-ABI=0 unchanged=1");return;
    }
    native_brightness_available=(BOOL (*)(id,SEL))method_getImplementation(available);
    native_display_type=(NSInteger (*)(id,SEL))method_getImplementation(type);
    native_display_external=(BOOL (*)(id,SEL))method_getImplementation(external);
    native_use_sync=(BOOL (*)(id,SEL,id))method_getImplementation(sync);
    native_find_displays=(BOOL (*)(id,SEL))method_getImplementation(find);
    native_find_backlight=(BOOL (*)(id,SEL))method_getImplementation(legacy);
    native_container_start=(BOOL (*)(id,SEL))method_getImplementation(start);
    native_container_setup=(BOOL (*)(id,SEL))method_getImplementation(setup);
    native_module_start=(void (*)(id,SEL))method_getImplementation(module_start);
    native_manual_set=(void (*)(id,SEL,float,id,NSUInteger))method_getImplementation(manual);
    native_manual_available=(BOOL (*)(id,SEL))method_getImplementation(manual_available);
    native_set_properties=(kern_return_t (*)(io_registry_entry_t,CFTypeRef))set_properties;
    method_setImplementation(available,(IMP)redfin_brightness_available);
    method_setImplementation(sync,(IMP)redfin_use_sync);
    method_setImplementation(find,(IMP)redfin_find_displays);
    method_setImplementation(legacy,(IMP)redfin_find_backlight);
    method_setImplementation(start,(IMP)redfin_container_start);
    method_setImplementation(setup,(IMP)redfin_container_setup);
    method_setImplementation(module_start,(IMP)redfin_module_start);
    method_setImplementation(manual,(IMP)redfin_manual_set);
    method_setImplementation(manual_available,(IMP)redfin_manual_available);
    backlight_log("installed integrated-native-backlight=1 synchronous-IOMFB-brightness=0 native-manual-driver=1 other-displays-preserved=1 native-control-methods-continued=1");
    /* Keep the exact native image and captured methods loaded until reset. */
}
