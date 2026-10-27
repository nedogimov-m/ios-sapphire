/* SPDX-License-Identifier: MIT
 * One-boot observation of the native CA server. Forward every original call,
 * argument and result. Never request an update/render or change display state.
 */
#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <IOKit/IOKitLib.h>
#include <mach/mach_time.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/stat.h>
#include <math.h>
#include "native-image-uuid.h"
#include "gui-profile.h"
#include "display-benchmark.h"
#include "display-statistics.h"

enum {
#define RF_SERVER_METHOD(key,cls,selector,types,meta,hook) RF_AD_##key,
#include "server-admission-methods.def"
#undef RF_SERVER_METHOD
    RF_AD_COUNT
};
static const struct {const char *cls,*selector,*types;BOOL meta,hook;} admission_methods[]={
#define RF_SERVER_METHOD(key,cls,selector,types,meta,hook) {cls,selector,types,meta,hook},
#include "server-admission-methods.def"
#undef RF_SERVER_METHOD
};
struct admission_call {uint64_t calls,allowed,denied,ns,maximum,last_argument;};
static struct admission_call admission_calls[RF_AD_COUNT];
static IMP admission_original[RF_AD_COUNT];
static bool admission_active;
static double admission_scale;
static double admission_began;
static uint64_t admission_nonce;
static io_connect_t admission_framebuffer;
static dispatch_source_t admission_timer;

static double admission_clock(void)
{return (double)mach_absolute_time()*admission_scale;}

/* These counters are the only work in native callbacks; all I/O and getter
 * sampling occur on the observer's private serial queue, at most once/second. */
static void admission_record(unsigned slot,uint64_t argument,int answer,double began)
{
    struct admission_call *s=&admission_calls[slot];
    double seconds=admission_clock()-began;
    uint64_t elapsed=isfinite(seconds)&&seconds>0?(uint64_t)(seconds*1e9):0;
    __atomic_fetch_add(&s->calls,1,__ATOMIC_RELAXED);
    if(answer>=0)__atomic_fetch_add(answer?&s->allowed:&s->denied,1,__ATOMIC_RELAXED);
    __atomic_fetch_add(&s->ns,elapsed,__ATOMIC_RELAXED);
    __atomic_store_n(&s->last_argument,argument,__ATOMIC_RELAXED);
    uint64_t previous=__atomic_load_n(&s->maximum,__ATOMIC_RELAXED);
    while(elapsed>previous&&!__atomic_compare_exchange_n(&s->maximum,&previous,elapsed,false,
        __ATOMIC_RELAXED,__ATOMIC_RELAXED)){}
}
static void admission_update(id object,SEL selector)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    ((void (*)(id,SEL))admission_original[RF_AD_DISPLAY_UPDATE])(object,selector);
    if(observe)admission_record(RF_AD_DISPLAY_UPDATE,0,-1,began);
}
static void admission_render(id object,SEL selector,double time)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    ((void (*)(id,SEL,double))admission_original[RF_AD_DISPLAY_RENDER])(object,selector,time);
    if(observe)admission_record(RF_AD_DISPLAY_RENDER,0,-1,began);
}
static BOOL admission_can_update(id object,SEL selector,BOOL force)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    BOOL result=((BOOL (*)(id,SEL,BOOL))admission_original[RF_AD_DISPLAY_CAN_UPDATE])(object,selector,force);
    if(observe)admission_record(RF_AD_DISPLAY_CAN_UPDATE,force,result,began);
    return result;
}
static BOOL admission_can_flags(id object,SEL selector,unsigned flags)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    BOOL result=((BOOL (*)(id,SEL,unsigned))admission_original[RF_AD_DISPLAY_CAN_FLAGS])(object,selector,flags);
    if(observe)admission_record(RF_AD_DISPLAY_CAN_FLAGS,flags,result,began);
    return result;
}
static void admission_set_enabled(id object,SEL selector,BOOL value)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    ((void (*)(id,SEL,BOOL))admission_original[RF_AD_DISPLAY_SET_ENABLED])(object,selector,value);
    if(observe)admission_record(RF_AD_DISPLAY_SET_ENABLED,value,-1,began);
}
static void admission_set_disabled(id object,SEL selector,BOOL value)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    ((void (*)(id,SEL,BOOL))admission_original[RF_AD_DISPLAY_SET_DISABLED])(object,selector,value);
    if(observe)admission_record(RF_AD_DISPLAY_SET_DISABLED,value,-1,began);
}
static void admission_set_compositing(id object,SEL selector,BOOL value)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    ((void (*)(id,SEL,BOOL))admission_original[RF_AD_DISPLAY_SET_COMPOSITING])(object,selector,value);
    if(observe)admission_record(RF_AD_DISPLAY_SET_COMPOSITING,value,-1,began);
}
static void admission_power(id object,SEL selector,id notification)
{
    bool observe=__atomic_load_n(&admission_active,__ATOMIC_ACQUIRE);
    double began=observe?admission_clock():0;
    ((void (*)(id,SEL,id))admission_original[RF_AD_DISPLAY_POWER])(object,selector,notification);
    if(observe)admission_record(RF_AD_DISPLAY_POWER,0,-1,began);
}
static IMP admission_replacement(unsigned slot)
{
    switch(slot) {
    case RF_AD_DISPLAY_UPDATE:return (IMP)admission_update;
    case RF_AD_DISPLAY_RENDER:return (IMP)admission_render;
    case RF_AD_DISPLAY_CAN_UPDATE:return (IMP)admission_can_update;
    case RF_AD_DISPLAY_CAN_FLAGS:return (IMP)admission_can_flags;
    case RF_AD_DISPLAY_SET_ENABLED:return (IMP)admission_set_enabled;
    case RF_AD_DISPLAY_SET_DISABLED:return (IMP)admission_set_disabled;
    case RF_AD_DISPLAY_SET_COMPOSITING:return (IMP)admission_set_compositing;
    case RF_AD_DISPLAY_POWER:return (IMP)admission_power;
    default:return NULL;
    }
}
static void admission_log(const char *format,...)
{
    char line[2048];int prefix=snprintf(line,sizeof(line),"REDFIN SERVER ADMISSION: boot=%016llx seconds=%.3f ",
        (unsigned long long)admission_nonce,admission_clock()-admission_began);
    if(prefix<0||(size_t)prefix>=sizeof(line))return;
    va_list args;va_start(args,format);int count=vsnprintf(line+prefix,sizeof(line)-(size_t)prefix,format,args);va_end(args);
    if(count<0||(size_t)count>=sizeof(line)-(size_t)prefix-1)return;
    size_t bytes=(size_t)(prefix+count);line[bytes++]='\n';
    int fd=open("/private/var/mobile/Library/Logs/redfin-refresh.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if(fd>=0){(void)write(fd,line,bytes);close(fd);}
}
static BOOL admission_bool(id object,unsigned slot)
{return ((BOOL (*)(id,SEL))objc_msgSend)(object,sel_registerName(admission_methods[slot].selector));}
static uint64_t admission_u64(id object,unsigned slot)
{return ((uint64_t (*)(id,SEL))objc_msgSend)(object,sel_registerName(admission_methods[slot].selector));}
static uint32_t admission_id(id object,unsigned slot)
{return ((uint32_t (*)(id,SEL))objc_msgSend)(object,sel_registerName(admission_methods[slot].selector));}
static id admission_object(id object,unsigned slot)
{return ((id (*)(id,SEL))objc_msgSend)(object,sel_registerName(admission_methods[slot].selector));}
static uint64_t admission_count(unsigned slot,unsigned field)
{
    struct admission_call *s=&admission_calls[slot];
    const uint64_t *value=field==0?&s->calls:field==1?&s->allowed:field==2?&s->denied:
        field==3?&s->ns:field==4?&s->maximum:&s->last_argument;
    return __atomic_load_n(value,__ATOMIC_RELAXED);
}
static void admission_sample(void)
{
    if(!admission_framebuffer) {
        io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("AppleCLCD"));
        if(service){(void)IOServiceOpen(service,mach_task_self(),0,&admission_framebuffer);IOObjectRelease(service);}
    }
    struct redfin_display_statistics_v2 statistics={0};size_t bytes=sizeof(statistics);
    kern_return_t queried=admission_framebuffer?IOConnectCallMethod(admission_framebuffer,
        REDFIN_DISPLAY_STATISTICS_SELECTOR_V2,&admission_nonce,1,NULL,0,NULL,NULL,&statistics,&bytes):kIOReturnNotReady;
    BOOL valid=queried==KERN_SUCCESS&&bytes==sizeof(statistics)&&redfin_display_statistics_valid_v2(&statistics);
    admission_log("event=counts statistics=%u status=%#x counter-ticks=%llu counter-hz=%llu presents=%llu gpu=%llu update=%llu render=%llu can=%llu allow=%llu deny=%llu can-flags=%llu flags-allow=%llu flags-deny=%llu last-flags=%llu render-ns=%llu render-max-ns=%llu enabled-sets=%llu last-enabled=%llu disabled-sets=%llu last-disabled=%llu compositing-sets=%llu last-compositing=%llu power-events=%llu original-forwarded=1",
        valid,queried,(unsigned long long)(valid?statistics.ticks:0),(unsigned long long)(valid?statistics.counter_hz:0),
        (unsigned long long)(valid?statistics.presents:0),(unsigned long long)(valid?statistics.gpu_presents:0),
        (unsigned long long)admission_count(RF_AD_DISPLAY_UPDATE,0),(unsigned long long)admission_count(RF_AD_DISPLAY_RENDER,0),
        (unsigned long long)admission_count(RF_AD_DISPLAY_CAN_UPDATE,0),(unsigned long long)admission_count(RF_AD_DISPLAY_CAN_UPDATE,1),
        (unsigned long long)admission_count(RF_AD_DISPLAY_CAN_UPDATE,2),(unsigned long long)admission_count(RF_AD_DISPLAY_CAN_FLAGS,0),
        (unsigned long long)admission_count(RF_AD_DISPLAY_CAN_FLAGS,1),(unsigned long long)admission_count(RF_AD_DISPLAY_CAN_FLAGS,2),
        (unsigned long long)admission_count(RF_AD_DISPLAY_CAN_FLAGS,5),(unsigned long long)admission_count(RF_AD_DISPLAY_RENDER,3),
        (unsigned long long)admission_count(RF_AD_DISPLAY_RENDER,4),(unsigned long long)admission_count(RF_AD_DISPLAY_SET_ENABLED,0),
        (unsigned long long)admission_count(RF_AD_DISPLAY_SET_ENABLED,5),(unsigned long long)admission_count(RF_AD_DISPLAY_SET_DISABLED,0),
        (unsigned long long)admission_count(RF_AD_DISPLAY_SET_DISABLED,5),(unsigned long long)admission_count(RF_AD_DISPLAY_SET_COMPOSITING,0),
        (unsigned long long)admission_count(RF_AD_DISPLAY_SET_COMPOSITING,5),(unsigned long long)admission_count(RF_AD_DISPLAY_POWER,0));
    id server=admission_object(objc_getClass("CAWindowServer"),RF_AD_SERVER_IF_RUNNING);
    if(!server){admission_log("event=server running=0");return;}
    id found=admission_object(server,RF_AD_SERVER_DISPLAYS);
    if(![found isKindOfClass:NSArray.class]||[found count]>4){admission_log("event=server display-inventory-refused=1");return;}
    id main=admission_object(objc_getClass("CADisplay"),RF_AD_DISPLAY_MAIN);
    CGRect frame=main?((CGRect (*)(id,SEL))objc_msgSend)(main,sel_registerName(admission_methods[RF_AD_DISPLAY_FRAME].selector)):CGRectZero;
    unsigned count=0;
    for(id display in found) {
        if(count++==4)break;
        if(![display isKindOfClass:objc_getClass("CAWindowServerDisplay")])continue;
        BOOL geometry=isfinite(frame.size.width)&&isfinite(frame.size.height)&&frame.size.width>0&&frame.size.height>0;
        CGPoint a=CGPointMake(CGRectGetMidX(frame),CGRectGetMidY(frame));
        CGPoint b=CGPointMake(frame.origin.x+frame.size.width*0.25,frame.origin.y+frame.size.height*0.25);
        uint32_t hit_a=geometry?((uint32_t (*)(id,SEL,CGPoint))objc_msgSend)(display,
            sel_registerName(admission_methods[RF_AD_DISPLAY_HIT].selector),a):0;
        uint32_t hit_b=geometry?((uint32_t (*)(id,SEL,CGPoint))objc_msgSend)(display,
            sel_registerName(admission_methods[RF_AD_DISPLAY_HIT].selector),b):0;
        admission_log("event=display id=%u enabled=%u disabled=%u compositing=%u needs-update=%u flipbook=%u minimum-frame=%llu maximum-frame=%llu update-callback=%u frame-callback=%u frame-width=%.3f frame-height=%.3f center-context=%u quarter-context=%u readonly=1",
            admission_id(display,RF_AD_DISPLAY_ID),admission_bool(display,RF_AD_DISPLAY_ENABLED),
            admission_bool(display,RF_AD_DISPLAY_DISABLED),admission_bool(display,RF_AD_DISPLAY_COMPOSITING),
            admission_bool(display,RF_AD_DISPLAY_NEEDS_UPDATE),admission_bool(display,RF_AD_DISPLAY_FLIPBOOK),
            (unsigned long long)admission_u64(display,RF_AD_DISPLAY_MIN_FRAME),(unsigned long long)admission_u64(display,RF_AD_DISPLAY_MAX_FRAME),
            admission_object(display,RF_AD_DISPLAY_UPDATE_CALLBACK)!=nil,admission_object(display,RF_AD_DISPLAY_FRAME_CALLBACK)!=nil,
            frame.size.width,frame.size.height,hit_a,hit_b);
    }
}
static BOOL admission_request(const char *text,uint64_t *nonce)
{
    uint64_t value=0;
    if(!text||strlen(text)!=16)return NO;
    for(unsigned i=0;i<16;++i){unsigned c=(unsigned char)text[i];if(c>='0'&&c<='9')c-='0';else if(c>='a'&&c<='f')c=c-'a'+10;else return NO;value=(value<<4)|c;}
    int fd=open(REDFIN_DISPLAY_PROBE_REQUEST,O_RDONLY|O_NOFOLLOW);if(fd<0)return NO;
    char data[128];struct stat st={0};ssize_t bytes=-1;
    if(!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==0&&!(st.st_mode&022)&&st.st_size>0&&st.st_size<(off_t)sizeof(data))bytes=read(fd,data,sizeof(data));
    close(fd);
    unsigned mode=bytes>0?redfin_display_probe_request(data,(size_t)bytes,value):RF_DISPLAY_PROBE_NONE;
    if(mode!=RF_DISPLAY_PROBE_CHECKED&&mode!=RF_DISPLAY_PROBE_CONTROLS_CHECKED)return NO;
    *nonce=value;return YES;
}
void redfin_server_admission_install(const char *text);
void redfin_server_admission_install(const char *text)
{
    const char *process=getprogname();uint64_t nonce=0;
    if(!process||strcmp(process,"backboardd")||getuid()!=501||!admission_request(text,&nonce))return;
    static bool attempted;if(__atomic_exchange_n(&attempted,true,__ATOMIC_ACQ_REL))return;
    Method methods[RF_AD_COUNT];const uint8_t quartz[16]={REDFIN_QUARTZ_UUID_BYTES};
    for(unsigned i=0;i<RF_AD_COUNT;++i) {
        Class cls=objc_getClass(admission_methods[i].cls);SEL selector=sel_registerName(admission_methods[i].selector);
        methods[i]=admission_methods[i].meta?class_getClassMethod(cls,selector):class_getInstanceMethod(cls,selector);
        if(!methods[i]||strcmp(method_getTypeEncoding(methods[i]),admission_methods[i].types)||
           !redfin_native_image_uuid((const void *)method_getImplementation(methods[i]),quartz))return;
        admission_original[i]=method_getImplementation(methods[i]);
        if(admission_methods[i].hook&&!admission_replacement(i))return;
    }
    mach_timebase_info_data_t scale={0};if(mach_timebase_info(&scale)!=KERN_SUCCESS||!scale.numer||!scale.denom)return;
    admission_scale=(double)scale.numer/scale.denom/1e9;admission_began=admission_clock();admission_nonce=nonce;
    __atomic_store_n(&admission_active,true,__ATOMIC_RELEASE);
    for(unsigned i=0;i<RF_AD_COUNT;++i)if(admission_methods[i].hook)method_setImplementation(methods[i],admission_replacement(i));
    admission_log("event=installed methods=%u maximum-seconds=150 observer-hz=1 getter-ABI=1 forces-render=0 display-state-changed=0",RF_AD_COUNT);
    dispatch_queue_t queue=dispatch_queue_create("com.redfin.finite-server-observer",DISPATCH_QUEUE_SERIAL);
    admission_timer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,queue);
    dispatch_source_set_timer(admission_timer,dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC),NSEC_PER_SEC,NSEC_PER_MSEC*20);
    dispatch_source_set_event_handler(admission_timer,^{@autoreleasepool{
        @try {admission_sample();} @catch(NSException *exception){(void)exception;admission_log("event=sample exception=1");}
        if(admission_clock()-admission_began>=150) {
            __atomic_store_n(&admission_active,false,__ATOMIC_RELEASE);
            if(admission_framebuffer)IOServiceClose(admission_framebuffer);admission_framebuffer=0;
            admission_log("event=finished original-forwarding-preserved=1");
            dispatch_source_cancel(admission_timer);admission_timer=nil;
        }
    }});
    dispatch_resume(admission_timer);
}
