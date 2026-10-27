/* SPDX-License-Identifier: MIT */
/* Explicit one-boot observation of actual completed GUI presentations. The
 * optional workload animates an existing fullscreen window's sublayers by
 * two points and removes only its own finite animation on completion. */
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#include <IOKit/IOKitLib.h>
#include <mach/mach_time.h>
#include <math.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include "gui-profile.h"
#include "display-statistics.h"
#include "display-benchmark.h"
#include "display-content.h"
#include "idle-system.h"
#import <objc/runtime.h>
#import <objc/message.h>
extern void redfin_controls_probe_run(uint64_t,BOOL (^)(BOOL,double),void (^)(BOOL,BOOL));

@interface RedfinDisplayProbe : NSObject
{
    struct redfin_display_window_state _hostState;
}
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) UIWindow *fallbackWindow;
@property(nonatomic,strong) UIWindow *candidateWindow;
@property(nonatomic,strong) CALayer *candidateLayer;
@property(nonatomic) double candidateAt,motionAt,motionMinimum,motionMaximum;
@property(nonatomic) unsigned motionSamples,motionMissing;
@property(nonatomic) CATransform3D originalTransform;
@property(nonatomic,strong) CADisplayLink *link;
@property(nonatomic) io_connect_t framebuffer;
@property(nonatomic) uint64_t nonce;
@property(nonatomic) struct redfin_display_statistics_v2 first;
@property(nonatomic) double origin,began,last,maximum;
@property(nonatomic) double clockRatio;
@property(nonatomic) unsigned callbacks,under12,under18,under35;
@property(nonatomic) BOOL finished;
@property(nonatomic) BOOL checksCompleted;
@property(nonatomic) BOOL controlsRequested,controlsCompleted;
@property(nonatomic) const char *finishReason;
@property(nonatomic) unsigned mode,samples,missed;
@property(nonatomic) double minimumFPS,maximumFPS;
@property(nonatomic) struct redfin_display_statistics_v2 lastNative;
@property(nonatomic,strong) CALayer *animatedLayer;
- (void)tick:(CADisplayLink *)link;
- (void)finish:(BOOL)timedOut;
- (BOOL)attachWindow:(UIWindow *)window layer:(CALayer *)layer;
- (void)resetMeasurement;
@end

static RedfinDisplayProbe *active_probe;
static BOOL probe_ended,idle_guard_active;
static NSString *const animation_key=@"com.redfin.presentation.measure";
static kern_return_t last_sample_status;
static size_t last_sample_bytes;
static struct redfin_display_statistics_v2 last_sample_value;
static unsigned request_mode(uint64_t nonce)
{
    int fd=open(REDFIN_DISPLAY_PROBE_REQUEST,O_RDONLY|O_NOFOLLOW);
    if(fd<0)return RF_DISPLAY_PROBE_NONE;
    struct stat st={0};char request[128]={0};ssize_t bytes=-1;
    if(!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==0&&
       !(st.st_mode&022)&&st.st_size>0&&st.st_size<(off_t)sizeof(request))
        bytes=read(fd,request,sizeof(request));
    close(fd);
    return bytes>0?redfin_display_probe_request(request,(size_t)bytes,nonce):RF_DISPLAY_PROBE_NONE;
}
static UIWindow *animation_host(UIWindow *fallback)
{
    return redfin_display_content_window(fallback);
}
static void probe_log(uint64_t nonce,const char *format,...)
{
    char line[1024];int prefix=snprintf(line,sizeof(line),"REDFIN DISPLAY PROBE: boot=%016llx pid=%d ",
        (unsigned long long)nonce,getpid());
    if (prefix<0 || (size_t)prefix>=sizeof(line)) return;
    va_list args;va_start(args,format);
    int n=vsnprintf(line+prefix,sizeof(line)-(size_t)prefix,format,args);va_end(args);
    if (n<0) return;
    size_t bytes=strnlen(line,sizeof(line)-2);line[bytes++]='\n';
    int fd=open("/private/var/mobile/Library/Logs/redfin-ui.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if (fd>=0) {(void)write(fd,line,bytes);close(fd);}
}
static BOOL content_animation(CALayer *layer,NSString *key,double ratio,double seconds)
{
    if(!layer||[layer animationForKey:key]||!isfinite(ratio)||ratio<=0)return NO;
    CABasicAnimation *animation=[CABasicAnimation animationWithKeyPath:@"transform.translation.x"];
    animation.fromValue=@0;animation.toValue=@2;animation.duration=0.25*ratio;
    animation.beginTime=[layer convertTime:CACurrentMediaTime() fromLayer:nil];
    animation.autoreverses=YES;animation.additive=YES;animation.repeatDuration=seconds*ratio;
    animation.removedOnCompletion=YES;[layer addAnimation:animation forKey:key];
    return [layer animationForKey:key]!=nil;
}
/* SpringBoard's public app idle request can lack an application scene. Borrow
 * one owned native system assertion instead, with the same finite deadline.
 * Other clients and the system's lock/unlock/passcode policy are preserved. */
static BOOL probe_idle_release(void)
{
    BOOL restored=redfin_idle_system_end();
    if(restored)idle_guard_active=NO;
    probe_ended=YES;return restored;
}
static BOOL probe_idle_begin(uint64_t nonce)
{
    if(idle_guard_active)return YES;
    if(!redfin_idle_system_begin(nonce))return NO;
    idle_guard_active=YES;
    probe_log(nonce,"finite-idle-guard borrowed=1 native-SpringBoard=1 maximum-seconds=%u",
        RF_DISPLAY_PROBE_IDLE_LIMIT_SECONDS);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)RF_DISPLAY_PROBE_IDLE_LIMIT_SECONDS*NSEC_PER_SEC),
        dispatch_get_main_queue(),^{
            if(!idle_guard_active)return;
            if(active_probe) {
                active_probe.finishReason="idle-deadline";[active_probe finish:YES];
            } else {
                BOOL restored=probe_idle_release();
                probe_log(nonce,"refused bounded-idle-deadline idle-restored=%u",restored);
            }
        });
    return YES;
}
static BOOL sample_attempts(io_connect_t client,uint64_t nonce,struct redfin_display_statistics_v2 *out,unsigned attempts)
{
    if (!client) return NO;
    for (unsigned attempt=0;attempt<attempts;++attempt) {
        size_t bytes=sizeof(*out);memset(out,0,bytes);
        kern_return_t status=IOConnectCallMethod(client,REDFIN_DISPLAY_STATISTICS_SELECTOR_V2,&nonce,1,
            NULL,0,NULL,NULL,out,&bytes);
        last_sample_status=status;last_sample_bytes=bytes;last_sample_value=*out;
        if (status==KERN_SUCCESS) return bytes==sizeof(*out) && redfin_display_statistics_valid_v2(out);
        if (status!=kIOReturnBusy) return NO;
        if(attempt+1<attempts)usleep(1000);
    }
    return NO;
}
static BOOL sample(io_connect_t client,uint64_t nonce,struct redfin_display_statistics_v2 *out)
{return sample_attempts(client,nonce,out,8);}
static void probe_native_periods(uint64_t nonce,CADisplayLink *link)
{
    Class cls=objc_getClass("CADisplay");
    const char *selectors[]={"refreshRate","hardwareRefreshRate","heartbeatRate","minimumFrameDuration"};
    const char *types[]={"d16@0:8","d16@0:8","d16@0:8","q16@0:8"};
    Method main=class_getClassMethod(cls,sel_registerName("mainDisplay"));
    Method maximum=class_getInstanceMethod(link.class,sel_registerName("maximumRefreshRate"));
    if(!main||strcmp(method_getTypeEncoding(main),"@16@0:8")||!maximum||strcmp(method_getTypeEncoding(maximum),"d16@0:8"))return;
    for(unsigned i=0;i<4;++i) {
        Method method=class_getInstanceMethod(cls,sel_registerName(selectors[i]));
        if(!method||strcmp(method_getTypeEncoding(method),types[i]))return;
    }
    id display=((id (*)(id,SEL))objc_msgSend)(cls,sel_registerName("mainDisplay"));
    if(!display)return;
    double periods[3];
    for(unsigned i=0;i<3;++i)periods[i]=((double (*)(id,SEL))objc_msgSend)(display,sel_registerName(selectors[i]));
    NSInteger minimum=((NSInteger (*)(id,SEL))objc_msgSend)(display,sel_registerName(selectors[3]));
    double maximum_period=((double (*)(id,SEL))objc_msgSend)(link,sel_registerName("maximumRefreshRate"));
    probe_log(nonce,"native-periods refresh-seconds=%.9f hardware-seconds=%.9f heartbeat-seconds=%.9f minimum-frame-duration=%ld link-maximum-period-seconds=%.9f native-getters-preserved=1",
        periods[0],periods[1],periods[2],(long)minimum,maximum_period);
}
@implementation RedfinDisplayProbe
- (void)resetMeasurement
{
    self.origin=0;self.began=0;self.last=0;self.maximum=0;
    self.callbacks=0;self.under12=0;self.under18=0;self.under35=0;
    self.samples=0;self.missed=0;self.minimumFPS=0;self.maximumFPS=0;
    self.first=(struct redfin_display_statistics_v2){0};
    self.lastNative=(struct redfin_display_statistics_v2){0};
    self.motionAt=0;self.motionSamples=0;self.motionMissing=0;
    self.motionMinimum=0;self.motionMaximum=0;
}
- (BOOL)attachWindow:(UIWindow *)window layer:(CALayer *)layer
{
    [self.animatedLayer removeAnimationForKey:animation_key];self.animatedLayer=nil;
    self.window=window;
    if(self.mode!=RF_DISPLAY_PROBE_ANIMATE||!window)return YES;
    uint32_t context=redfin_display_content_context(window,layer);
    if(!context||!content_animation(layer,animation_key,self.clockRatio,RF_DISPLAY_PROBE_ANIMATION_SECONDS))return NO;
    self.animatedLayer=layer;self.originalTransform=layer.transform;
    probe_log(self.nonce,"content-attached window=%s layer=%s context=%u root-container=0 model-unchanged=1 native-local-time=1",
        class_getName(window.class),class_getName(layer.class),context);
    return YES;
}
- (void)tick:(CADisplayLink *)link
{
    if (self.finished) return;
    double now=link.timestamp;
    if(self.mode==RF_DISPLAY_PROBE_ANIMATE) {
        if(!self.candidateAt||now-self.candidateAt>=0.25*self.clockRatio||
           (self.candidateLayer&&!redfin_display_content_context(self.candidateWindow,self.candidateLayer))) {
            self.candidateWindow=animation_host(self.fallbackWindow);
            self.candidateLayer=redfin_display_content_layer(self.candidateWindow);
            self.candidateAt=now;
        }
        UIWindow *candidate=self.candidateWindow;
        CALayer *target=self.candidateLayer;
        /* A replaced content tree discards the interval even when its UIWindow
         * survives. Keep both identities alive across the same finite gate. */
        uintptr_t identity=(uintptr_t)(__bridge void *)target;
        if(self.animatedLayer==target&&self.window!=candidate)identity=0;
        bool reset=false;
        unsigned state=redfin_display_probe_window(&_hostState,identity,
            now/self.clockRatio,&reset);
        if(reset) {
            BOOL discarded=self.began!=0;
            (void)[self attachWindow:nil layer:nil];[self resetMeasurement];
            probe_log(self.nonce,"window-transition restart=%u discarded-measurement=%u",_hostState.restarts,discarded);
        }
        if(state==RF_DISPLAY_WINDOW_REFUSED) {self.finishReason="window-churn";[self finish:YES];return;}
        if(state==RF_DISPLAY_WINDOW_PENDING)return;
        if(state==RF_DISPLAY_WINDOW_READY) {
            if(![self attachWindow:candidate layer:target]) {self.finishReason="content-animation-admission";[self finish:YES];return;}
            self.origin=now;
            probe_log(self.nonce,"window-stable seconds=%u restarts=%u fresh-warmup=1",RF_DISPLAY_PROBE_WINDOW_STABLE_SECONDS,_hostState.restarts);
        }
    }
    if(self.began&&self.mode==RF_DISPLAY_PROBE_ANIMATE&&
       (!self.motionAt||now-self.motionAt>=0.25*self.clockRatio)) {
        self.motionAt=now;
        CALayer *presentation=self.animatedLayer.presentationLayer;
        double x=presentation?presentation.transform.m41:NAN;
        if(presentation&&isfinite(x)&&[self.animatedLayer animationForKey:animation_key]) {
            if(!self.motionSamples)self.motionMinimum=self.motionMaximum=x;
            self.motionMinimum=fmin(self.motionMinimum,x);self.motionMaximum=fmax(self.motionMaximum,x);
            ++self.motionSamples;
        } else ++self.motionMissing;
    }
    if (!self.origin) self.origin=now;
    if (!self.began && now-self.origin>=RF_DISPLAY_PROBE_WARMUP_SECONDS*self.clockRatio) {
        struct redfin_display_statistics_v2 start={0};
        if (!sample(self.framebuffer,self.nonce,&start)) {self.finishReason="initial-counters";[self finish:YES];return;}
        self.first=start;self.lastNative=start;self.began=now;self.last=now;
        probe_log(self.nonce,"measure-start warmup-seconds=%u ticks=%llu completed-presents=%llu gpu-presents=%llu",
            RF_DISPLAY_PROBE_WARMUP_SECONDS,(unsigned long long)start.ticks,(unsigned long long)start.presents,(unsigned long long)start.gpu_presents);
    } else if (self.began) {
        double interval=(now-self.last)/self.clockRatio;self.last=now;
        if (interval>self.maximum) self.maximum=interval;
        if (interval>0 && interval<=0.0125) self.under12++;
        if (interval>0 && interval<=0.018) self.under18++;
        if (interval>0 && interval<=0.035) self.under35++;
    }
    if(self.began&&(now-self.began)/self.clockRatio>=self.samples+self.missed+1) {
        struct redfin_display_statistics_v2 snapshot={0};
        if(sample_attempts(self.framebuffer,self.nonce,&snapshot,1)&&snapshot.ticks>self.lastNative.ticks&&
           snapshot.presents>=self.lastNative.presents&&snapshot.gpu_presents>=self.lastNative.gpu_presents&&
           snapshot.counter_hz==self.first.counter_hz) {
            double seconds=(double)(snapshot.ticks-self.lastNative.ticks)/snapshot.counter_hz;
            double fps=seconds>0?(snapshot.presents-self.lastNative.presents)/seconds:0;
            if(!self.samples||fps<self.minimumFPS)self.minimumFPS=fps;
            if(fps>self.maximumFPS)self.maximumFPS=fps;
            ++self.samples;self.lastNative=snapshot;
        } else ++self.missed;
    }
    if (self.began) self.callbacks++;
    if (self.began && (now-self.began)/self.clockRatio>=RF_DISPLAY_PROBE_MEASURE_SECONDS) [self finish:NO];
}
- (void)finish:(BOOL)timedOut
{
    if (self.finished) return;
    self.finished=YES;[self.link invalidate];self.link=nil;
    BOOL attached=redfin_display_content_context(self.window,self.animatedLayer)!=0;
    BOOL preserved=self.animatedLayer&&CATransform3DEqualToTransform(self.originalTransform,self.animatedLayer.transform);
    BOOL moving=self.motionSamples>=3&&self.motionMaximum-self.motionMinimum>=0.1;
    [self.animatedLayer removeAnimationForKey:animation_key];self.animatedLayer=nil;
    struct redfin_display_statistics_v2 final={0};
    BOOL valid=self.began && sample(self.framebuffer,self.nonce,&final) && final.ticks>self.first.ticks &&
        final.presents>=self.first.presents && final.gpu_presents>=self.first.gpu_presents &&
        final.panel_hz==self.first.panel_hz&&final.counter_hz==self.first.counter_hz;
    double seconds=valid?(double)(final.ticks-self.first.ticks)/final.counter_hz:0;
    uint64_t presents=valid ? final.presents-self.first.presents : 0;
    uint64_t gpu=valid ? final.gpu_presents-self.first.gpu_presents : 0;
    double elapsed=(self.last-self.began)/self.clockRatio;
    BOOL idle_restored=probe_idle_release();
    const char *reason=timedOut?(self.finishReason?self.finishReason:"unspecified-abort"):
        valid?"complete":"final-counters";
    probe_log(self.nonce,"result passive=%u animation=%s stats-valid=%u timed-out=%u panel-hz=%u seconds=%.6f completed-presents=%llu gpu-presents=%llu observed-present-fps=%.3f callbacks=%u callback-fps=%.3f under12=%u under18=%u under35=%u max-interval-ms=%.3f sample-count=%u sample-missed=%u minimum-present-fps=%.3f maximum-present-fps=%.3f hardware-counter-hz=%llu mach-to-physical-ratio=%.9f native-checks-completed=%u finish-reason=%s idle-restored=%u controls-requested=%u controls-completed=%u context-attached=%u model-preserved=%u workload-motion-proved=%u motion-samples=%u motion-missing=%u motion-range=%.3f",
        self.mode==RF_DISPLAY_PROBE_PASSIVE,self.mode==RF_DISPLAY_PROBE_ANIMATE?"system-content-subpixel":"none",
        valid,timedOut,valid ? final.panel_hz : 0,seconds,(unsigned long long)presents,(unsigned long long)gpu,
        seconds>0 ? presents/seconds : 0,self.callbacks,elapsed>0 ? (self.callbacks-1)/elapsed : 0,
        self.under12,self.under18,self.under35,self.maximum*1000,self.samples,self.missed,self.minimumFPS,self.maximumFPS,
        (unsigned long long)(valid?final.counter_hz:0),self.clockRatio,self.checksCompleted,reason,idle_restored,
        self.controlsRequested,self.controlsCompleted,attached,preserved,moving,
        self.motionSamples,self.motionMissing,self.motionMaximum-self.motionMinimum);
    if (self.framebuffer) IOServiceClose(self.framebuffer);
    self.framebuffer=0;self.window=nil;self.fallbackWindow=nil;self.candidateWindow=nil;self.candidateLayer=nil;
    active_probe=nil;
}
@end

static size_t probe_log_tail(const char *path,char *out,size_t capacity)
{
    int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0)return 0;
    struct stat st={0};ssize_t bytes=-1;
    if(!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==501&&st.st_size>0) {
        off_t at=st.st_size>(off_t)capacity?st.st_size-(off_t)capacity:0;
        bytes=pread(fd,out,capacity,at);
        if(bytes>0&&at) {
            char *first=memchr(out,'\n',(size_t)bytes);
            if(first){size_t skip=(size_t)(first-out)+1;memmove(out,out+skip,(size_t)bytes-skip);bytes-=(ssize_t)skip;}
            else bytes=0;
        }
    }
    close(fd);return bytes>0?(size_t)bytes:0;
}
static unsigned probe_checks(uint64_t nonce)
{
    const size_t limit=65536;
    char *metal=malloc(limit),*gpu=malloc(limit);
    if(!metal||!gpu){free(metal);free(gpu);return 0;}
    size_t m=probe_log_tail("/private/var/mobile/Library/Logs/redfin-metal-check.log",metal,limit);
    size_t g=probe_log_tail("/private/var/mobile/Library/Logs/redfin-gpu-render.log",gpu,limit);
    unsigned result=redfin_display_probe_checks(metal,m,gpu,g,nonce);
    free(metal);free(gpu);return result;
}
static void probe_measure(UIWindow *native_host,uint64_t nonce,unsigned mode,BOOL checks_completed,
    BOOL controls_requested,BOOL controls_completed)
{
    if(probe_ended)return;
        UIWindow *parent=native_host;
        if (!parent || parent.screen!=UIScreen.mainScreen) {(void)probe_idle_release();probe_log(nonce,"refused no native main-screen host");return;}
        if(mode==RF_DISPLAY_PROBE_ANIMATE) {
            parent=animation_host(parent);
            if(!parent){probe_log(nonce,"refused no existing visible fullscreen animation host");(void)probe_idle_release();return;}
        }
        probe_log(nonce,"host class=%s key=%u level=%.3f sublayers=%lu contents=%u root-controller=%s scene=%u width=%.3f height=%.3f",
            class_getName(parent.class),parent.isKeyWindow,(double)parent.windowLevel,(unsigned long)parent.layer.sublayers.count,
            parent.layer.contents!=nil,parent.rootViewController?class_getName(parent.rootViewController.class):"none",
            parent.windowScene!=nil,parent.bounds.size.width,parent.bounds.size.height);
        io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("AppleCLCD"));
        io_connect_t client=0;
        kern_return_t opened=service ? IOServiceOpen(service,mach_task_self(),0,&client) : KERN_FAILURE;
        if (service) IOObjectRelease(service);
        struct redfin_display_statistics_v2 start={0};
        if (opened!=KERN_SUCCESS || !sample(client,nonce,&start)) {
            probe_log(nonce,"refused native completed-presentation statistics unavailable open-error=%#x query-error=%#x returned-bytes=%zu version=%u panel-hz=%u hardware-counter-hz=%llu",
                opened,last_sample_status,last_sample_bytes,last_sample_value.version,last_sample_value.panel_hz,
                (unsigned long long)last_sample_value.counter_hz);
            if (client) IOServiceClose(client);
            (void)probe_idle_release();return;
        }
        RedfinDisplayProbe *probe=[RedfinDisplayProbe new];
        probe.framebuffer=client;probe.nonce=nonce;probe.first=start;
        mach_timebase_info_data_t scale={0};mach_timebase_info(&scale);
        double ratio=scale.denom?(double)start.counter_hz*scale.numer/scale.denom/1e9:0;
        if(!isfinite(ratio)||ratio<0.25||ratio>4) {
            probe_log(nonce,"refused invalid physical/mach counter ratio");IOServiceClose(client);(void)probe_idle_release();return;
        }
        probe.clockRatio=ratio;
        probe.window=parent;probe.fallbackWindow=native_host;probe.mode=mode;probe.checksCompleted=checks_completed;active_probe=probe;
        probe.controlsRequested=controls_requested;probe.controlsCompleted=controls_completed;
        CADisplayLink *link=[CADisplayLink displayLinkWithTarget:probe selector:@selector(tick:)];
        link.preferredFrameRateRange=CAFrameRateRangeMake(start.panel_hz,start.panel_hz,start.panel_hz);
        probe_native_periods(nonce,link);
        probe.link=link;[link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
        probe_log(nonce,"start passive=%u animation=%s seconds=%u panel-hz=%u begin-presents=%llu begin-gpu=%llu",
            mode==RF_DISPLAY_PROBE_PASSIVE,mode==RF_DISPLAY_PROBE_ANIMATE?"system-content-subpixel":"none",
            RF_DISPLAY_PROBE_MEASURE_SECONDS,start.panel_hz,(unsigned long long)start.presents,(unsigned long long)start.gpu_presents);
        __weak RedfinDisplayProbe *weak=probe;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(RF_DISPLAY_PROBE_DEADLINE_SECONDS*ratio*NSEC_PER_SEC)),dispatch_get_main_queue(),^{
            RedfinDisplayProbe *held=weak;if(held&&!held.finished){held.finishReason="wall-clock-deadline";[held finish:YES];}
        });
}

static void probe_begin(UIWindow *native_host,uint64_t nonce,unsigned requested,unsigned waits)
{
    if(probe_ended)return;
    BOOL checked=requested==RF_DISPLAY_PROBE_CHECKED||requested==RF_DISPLAY_PROBE_CONTROLS_CHECKED;
    if(checked) {
        unsigned state=probe_checks(nonce);
        if(!state&&waits) {
            if(waits==60)probe_log(nonce,"waiting-for-current-native-checks bounded-seconds=60");
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC),dispatch_get_main_queue(),^{
                probe_begin(native_host,nonce,requested,waits-1);
            });
            return;
        }
        if(state!=1){probe_log(nonce,"refused current-native-checks state=%u remaining=%u",state,waits);(void)probe_idle_release();return;}
        probe_log(nonce,"current-native-checks-complete ordinary-animation-measurement-starts=%u controls-required=%u",
            requested!=RF_DISPLAY_PROBE_CONTROLS_CHECKED,requested==RF_DISPLAY_PROBE_CONTROLS_CHECKED);
    }
    redfin_display_content_trace(nonce,probe_log);
    if(requested==RF_DISPLAY_PROBE_CONTROLS_CHECKED) {
        UIWindow *host=animation_host(native_host);
        NSString *key=[NSString stringWithFormat:@"com.redfin.controls.observe.%016llx",(unsigned long long)nonce];
        CALayer *layer=redfin_display_content_layer(host);
        if(!host||[layer animationForKey:key]) {
            BOOL released=probe_idle_release();
            probe_log(nonce,"refused no owned controls animation host idle-restored=%u",released);return;
        }
        redfin_controls_probe_run(nonce,^BOOL(BOOL start,double ratio){
            if(start) {
                if(!redfin_display_content_context(host,layer)||!content_animation(layer,key,ratio,28))return NO;
            } else [layer removeAnimationForKey:key];
            probe_log(nonce,"controls-workload active=%u class=%s layer=%s finite-seconds=28 model-unchanged=1 root-container=0",start,class_getName(host.class),class_getName(layer.class));
            return YES;
        },^(BOOL restored,BOOL passed){
            if(!restored) {
                BOOL idle=probe_idle_release();
                probe_log(nonce,"refused display-controls-restoration-failed idle-restored=%u",idle);return;
            }
            probe_measure(native_host,nonce,RF_DISPLAY_PROBE_ANIMATE,YES,YES,passed);
        });
        return;
    }
    probe_measure(native_host,nonce,checked?RF_DISPLAY_PROBE_ANIMATE:requested,checked,NO,NO);
}

static void probe_schedule_with_idle(UIWindow *host,uint64_t nonce,unsigned mode,unsigned waits)
{
    if(probe_ended)return;
    if(!probe_idle_begin(nonce)) {
        if(waits) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{
                probe_schedule_with_idle(host,nonce,mode,waits-1);
            });
        } else {
            BOOL released=probe_idle_release();
            probe_log(nonce,"refused native-system-idle-assertion-unavailable idle-restored=%u",released);
        }
        return;
    }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,40*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        probe_begin(host,nonce,mode,60);
    });
}

void redfin_display_probe_schedule(UIWindow *host,uint64_t nonce)
{
    static BOOL scheduled;
    if (scheduled || !NSThread.isMainThread || !host || !nonce ||
        strcmp(NSProcessInfo.processInfo.processName.UTF8String,"SpringBoard")) return;
    scheduled=YES;
    unsigned mode=request_mode(nonce);if(mode==RF_DISPLAY_PROBE_NONE)return;
    probe_schedule_with_idle(host,nonce,mode,50);
}
