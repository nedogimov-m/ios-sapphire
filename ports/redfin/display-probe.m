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

@interface RedfinDisplayProbe : NSObject
{
    struct redfin_display_window_state _hostState;
}
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) UIWindow *fallbackWindow;
@property(nonatomic,strong) UIWindow *candidateWindow;
@property(nonatomic,strong) CADisplayLink *link;
@property(nonatomic) io_connect_t framebuffer;
@property(nonatomic) uint64_t nonce;
@property(nonatomic) struct redfin_display_statistics_v2 first;
@property(nonatomic) double origin,began,last,maximum;
@property(nonatomic) double clockRatio;
@property(nonatomic) unsigned callbacks,under12,under18,under35;
@property(nonatomic) BOOL finished;
@property(nonatomic) BOOL checksCompleted;
@property(nonatomic) const char *finishReason;
@property(nonatomic) unsigned mode,samples,missed;
@property(nonatomic) double minimumFPS,maximumFPS;
@property(nonatomic) struct redfin_display_statistics_v2 lastNative;
@property(nonatomic,strong) CALayer *animatedLayer;
- (void)tick:(CADisplayLink *)link;
- (void)finish:(BOOL)timedOut;
- (void)attachWindow:(UIWindow *)window;
- (void)resetMeasurement;
@end

static RedfinDisplayProbe *active_probe;
static BOOL probe_ended,idle_guard_active,idle_guard_changed;
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
static BOOL fullscreen_window(UIWindow *window)
{
    CGSize wanted=UIScreen.mainScreen.bounds.size,size=window.bounds.size;
    return window&&!window.hidden&&window.alpha>=0.99&&window.screen==UIScreen.mainScreen&&
        size.width>=wanted.width*0.9&&size.height>=wanted.height*0.9;
}
static UIWindow *animation_host(UIWindow *fallback)
{
    for(UIWindow *window in UIApplication.sharedApplication.windows)
        if(fullscreen_window(window)&&window.isKeyWindow)return window;
    for(UIWindow *window in UIApplication.sharedApplication.windows.reverseObjectEnumerator)
        if(fullscreen_window(window)&&window.windowLevel<=UIWindowLevelStatusBar)return window;
    return fullscreen_window(fallback)?fallback:nil;
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
/* Borrow only this process's public idle request, for this exact one-boot
 * observation. All success/refusal paths and an independent finite deadline
 * release our request. No lock/unlock/passcode policy is changed. */
static BOOL probe_idle_release(void)
{
    BOOL restored=YES;
    if(idle_guard_active&&idle_guard_changed) {
        UIApplication.sharedApplication.idleTimerDisabled=NO;
        restored=!UIApplication.sharedApplication.idleTimerDisabled;
    }
    idle_guard_active=NO;idle_guard_changed=NO;probe_ended=YES;return restored;
}
static void probe_idle_begin(uint64_t nonce)
{
    if(idle_guard_active)return;
    idle_guard_changed=!UIApplication.sharedApplication.idleTimerDisabled;
    idle_guard_active=YES;
    if(idle_guard_changed)UIApplication.sharedApplication.idleTimerDisabled=YES;
    probe_log(nonce,"finite-idle-guard borrowed=%u maximum-seconds=%u",idle_guard_changed,
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
@implementation RedfinDisplayProbe
- (void)resetMeasurement
{
    self.origin=0;self.began=0;self.last=0;self.maximum=0;
    self.callbacks=0;self.under12=0;self.under18=0;self.under35=0;
    self.samples=0;self.missed=0;self.minimumFPS=0;self.maximumFPS=0;
    self.first=(struct redfin_display_statistics_v2){0};
    self.lastNative=(struct redfin_display_statistics_v2){0};
}
- (void)attachWindow:(UIWindow *)window
{
    [self.animatedLayer removeAnimationForKey:animation_key];self.animatedLayer=nil;
    self.window=window;
    if(self.mode!=RF_DISPLAY_PROBE_ANIMATE||!window)return;
    CABasicAnimation *animation=[CABasicAnimation animationWithKeyPath:@"sublayerTransform.translation.x"];
    animation.fromValue=@0;animation.toValue=@2;animation.duration=0.25*self.clockRatio;
    animation.autoreverses=YES;animation.additive=YES;animation.repeatDuration=RF_DISPLAY_PROBE_ANIMATION_SECONDS*self.clockRatio;
    animation.removedOnCompletion=YES;
    self.animatedLayer=window.layer;[self.animatedLayer addAnimation:animation forKey:animation_key];
}
- (void)tick:(CADisplayLink *)link
{
    if (self.finished) return;
    double now=link.timestamp;
    if(self.mode==RF_DISPLAY_PROBE_ANIMATE) {
        UIWindow *candidate=animation_host(self.fallbackWindow);
        self.candidateWindow=candidate; /* Hold identity stable across callbacks. */
        bool reset=false;
        unsigned state=redfin_display_probe_window(&_hostState,(uintptr_t)(__bridge void *)candidate,
            now/self.clockRatio,&reset);
        if(reset) {
            BOOL discarded=self.began!=0;
            [self attachWindow:nil];[self resetMeasurement];
            probe_log(self.nonce,"window-transition restart=%u discarded-measurement=%u",_hostState.restarts,discarded);
        }
        if(state==RF_DISPLAY_WINDOW_REFUSED) {self.finishReason="window-churn";[self finish:YES];return;}
        if(state==RF_DISPLAY_WINDOW_PENDING)return;
        if(state==RF_DISPLAY_WINDOW_READY) {
            [self attachWindow:candidate];self.origin=now;
            probe_log(self.nonce,"window-stable seconds=%u restarts=%u fresh-warmup=1",RF_DISPLAY_PROBE_WINDOW_STABLE_SECONDS,_hostState.restarts);
        }
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
    probe_log(self.nonce,"result passive=%u animation=%s stats-valid=%u timed-out=%u panel-hz=%u seconds=%.6f completed-presents=%llu gpu-presents=%llu observed-present-fps=%.3f callbacks=%u callback-fps=%.3f under12=%u under18=%u under35=%u max-interval-ms=%.3f sample-count=%u sample-missed=%u minimum-present-fps=%.3f maximum-present-fps=%.3f hardware-counter-hz=%llu mach-to-physical-ratio=%.9f native-checks-completed=%u finish-reason=%s idle-restored=%u",
        self.mode==RF_DISPLAY_PROBE_PASSIVE,self.mode==RF_DISPLAY_PROBE_ANIMATE?"system-window-subpixel":"none",
        valid,timedOut,valid ? final.panel_hz : 0,seconds,(unsigned long long)presents,(unsigned long long)gpu,
        seconds>0 ? presents/seconds : 0,self.callbacks,elapsed>0 ? (self.callbacks-1)/elapsed : 0,
        self.under12,self.under18,self.under35,self.maximum*1000,self.samples,self.missed,self.minimumFPS,self.maximumFPS,
        (unsigned long long)(valid?final.counter_hz:0),self.clockRatio,self.checksCompleted,reason,idle_restored);
    if (self.framebuffer) IOServiceClose(self.framebuffer);
    self.framebuffer=0;self.window=nil;self.fallbackWindow=nil;self.candidateWindow=nil;
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
static void probe_begin(UIWindow *native_host,uint64_t nonce,unsigned requested,unsigned waits)
{
    if(probe_ended)return;
    BOOL checks_completed=NO;unsigned mode=requested;
    if(requested==RF_DISPLAY_PROBE_CHECKED) {
        unsigned state=probe_checks(nonce);
        if(!state&&waits) {
            if(waits==60)probe_log(nonce,"waiting-for-current-native-checks bounded-seconds=60");
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC),dispatch_get_main_queue(),^{
                probe_begin(native_host,nonce,requested,waits-1);
            });
            return;
        }
        if(state!=1){probe_log(nonce,"refused current-native-checks state=%u remaining=%u",state,waits);(void)probe_idle_release();return;}
        checks_completed=YES;mode=RF_DISPLAY_PROBE_ANIMATE;
        probe_log(nonce,"current-native-checks-complete ordinary-animation-measurement-starts=1");
    }
        UIWindow *parent=native_host;
        if (!parent || parent.screen!=UIScreen.mainScreen) {(void)probe_idle_release();probe_log(nonce,"refused no native main-screen host");return;}
        if(mode==RF_DISPLAY_PROBE_ANIMATE) {
            parent=animation_host(parent);
            if(!parent){probe_log(nonce,"refused no existing visible fullscreen animation host");(void)probe_idle_release();return;}
        }
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
        CADisplayLink *link=[CADisplayLink displayLinkWithTarget:probe selector:@selector(tick:)];
        link.preferredFrameRateRange=CAFrameRateRangeMake(start.panel_hz,start.panel_hz,start.panel_hz);
        probe.link=link;[link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
        probe_log(nonce,"start passive=%u animation=%s seconds=%u panel-hz=%u begin-presents=%llu begin-gpu=%llu",
            mode==RF_DISPLAY_PROBE_PASSIVE,mode==RF_DISPLAY_PROBE_ANIMATE?"system-window-subpixel":"none",
            RF_DISPLAY_PROBE_MEASURE_SECONDS,start.panel_hz,(unsigned long long)start.presents,(unsigned long long)start.gpu_presents);
        __weak RedfinDisplayProbe *weak=probe;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(RF_DISPLAY_PROBE_DEADLINE_SECONDS*ratio*NSEC_PER_SEC)),dispatch_get_main_queue(),^{
            RedfinDisplayProbe *held=weak;if(held&&!held.finished){held.finishReason="wall-clock-deadline";[held finish:YES];}
        });
}

void redfin_display_probe_schedule(UIWindow *host,uint64_t nonce)
{
    static BOOL scheduled;
    if (scheduled || !NSThread.isMainThread || !host || !nonce ||
        strcmp(NSProcessInfo.processInfo.processName.UTF8String,"SpringBoard")) return;
    scheduled=YES;
    unsigned mode=request_mode(nonce);if(mode==RF_DISPLAY_PROBE_NONE)return;
    probe_idle_begin(nonce);
    UIWindow *native_host=host;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,40*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        probe_begin(native_host,nonce,mode,60);
    });
}
