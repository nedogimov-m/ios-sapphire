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

static BOOL (*native_brightness_available)(id,SEL);
static NSInteger (*native_display_type)(id,SEL);
static BOOL (*native_use_sync)(id,SEL,id);
static BOOL (*native_find_displays)(id,SEL),(*native_find_backlight)(id,SEL);
static BOOL (*native_container_start)(id,SEL),(*native_container_setup)(id,SEL);
static void (*native_module_start)(id,SEL);
static char backlight_nonce[17];
static unsigned backlight_observations;

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
static BOOL redfin_container_setup(id object,SEL selector)
{
    BOOL value=native_container_setup(object,selector);
    backlight_log("CoreBrightness-module-setup=%u original-continued=1",value);return value;
}
static void redfin_module_start(id object,SEL selector)
{
    native_module_start(object,selector);
    backlight_log("CoreBrightness-display-module-start=1 original-continued=1");
}

void redfin_backlight_system_install(const char *nonce)
{
    static bool attempted;
    const char *process=getprogname();
    if(attempted||!nonce||strlen(nonce)!=16||!process||strcmp(process,"backboardd"))return;
    attempted=true;memcpy(backlight_nonce,nonce,16);
    if(!backlight_transport_present()){backlight_log("refused native-backlight-contract=0 unchanged=1");return;}
    void *cb=dlopen("/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness",RTLD_NOW|RTLD_LOCAL);
    if(!cb){backlight_log("refused native-CoreBrightness=0 unchanged=1");return;}
    const uint8_t quartz[16]={REDFIN_QUARTZ_UUID_BYTES},core[16]={REDFIN_CB_UUID_BYTES};
    Class display=objc_getClass("CAWindowServerDisplay"),control=objc_getClass("BLControl");
    Class container=objc_getClass("CBDisplayContaineriOS"),module=objc_getClass("CBDisplayModuleiOS");
    Method available=backlight_method(display,"brightnessAvailable","B16@0:8",quartz);
    Method type=backlight_method(display,"displayType","q16@0:8",quartz);
    Method sync=backlight_method(control,"useSyncBrightnessTransactionForDisplay:","B24@0:8@16",core);
    Method find=backlight_method(control,"findDisplays","B16@0:8",core);
    Method legacy=backlight_method(control,"findBacklight","B16@0:8",core);
    Method start=backlight_method(container,"start","B16@0:8",core);
    Method setup=backlight_method(container,"setupInternalModules","B16@0:8",core);
    Method module_start=backlight_method(module,"start","v16@0:8",core);
    if(!available||!type||!sync||!find||!legacy||!start||!setup||!module_start) {
        backlight_log("refused native-method-ABI=0 unchanged=1");return;
    }
    native_brightness_available=(BOOL (*)(id,SEL))method_getImplementation(available);
    native_display_type=(NSInteger (*)(id,SEL))method_getImplementation(type);
    native_use_sync=(BOOL (*)(id,SEL,id))method_getImplementation(sync);
    native_find_displays=(BOOL (*)(id,SEL))method_getImplementation(find);
    native_find_backlight=(BOOL (*)(id,SEL))method_getImplementation(legacy);
    native_container_start=(BOOL (*)(id,SEL))method_getImplementation(start);
    native_container_setup=(BOOL (*)(id,SEL))method_getImplementation(setup);
    native_module_start=(void (*)(id,SEL))method_getImplementation(module_start);
    method_setImplementation(available,(IMP)redfin_brightness_available);
    method_setImplementation(sync,(IMP)redfin_use_sync);
    method_setImplementation(find,(IMP)redfin_find_displays);
    method_setImplementation(legacy,(IMP)redfin_find_backlight);
    method_setImplementation(start,(IMP)redfin_container_start);
    method_setImplementation(setup,(IMP)redfin_container_setup);
    method_setImplementation(module_start,(IMP)redfin_module_start);
    backlight_log("installed integrated-native-backlight=1 synchronous-IOMFB-brightness=0 other-displays-preserved=1 native-control-methods-continued=1");
    /* Keep the exact native image and captured methods loaded until reset. */
}
