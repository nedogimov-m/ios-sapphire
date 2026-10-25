/* SPDX-License-Identifier: MIT */
/* Bounded unattended native UIKit animation. Separately records callbacks
 * and the framebuffer's actually completed presentations over the same run. */
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
#include <unistd.h>
#include "gui-profile.h"
#include "display-statistics.h"

@interface RedfinDisplayProbe : NSObject
@property(nonatomic,strong) UIWindow *window;
@property(nonatomic,strong) CADisplayLink *link;
@property(nonatomic,strong) NSArray<CALayer *> *squares;
@property(nonatomic) io_connect_t framebuffer;
@property(nonatomic) uint64_t nonce;
@property(nonatomic) struct redfin_display_statistics first;
@property(nonatomic) double began,last,maximum;
@property(nonatomic) unsigned callbacks,under12,under18,under35;
@property(nonatomic) BOOL finished;
- (void)tick:(CADisplayLink *)link;
- (void)finish:(BOOL)timedOut;
@end

static RedfinDisplayProbe *active_probe;
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
static BOOL sample(io_connect_t client,uint64_t nonce,struct redfin_display_statistics *out)
{
    if (!client) return NO;
    for (unsigned attempt=0;attempt<8;++attempt) {
        size_t bytes=sizeof(*out);memset(out,0,bytes);
        kern_return_t status=IOConnectCallMethod(client,REDFIN_DISPLAY_STATISTICS_SELECTOR,&nonce,1,
            NULL,0,NULL,NULL,out,&bytes);
        if (status==KERN_SUCCESS) return bytes==sizeof(*out) && redfin_display_statistics_valid(out);
        if (status!=kIOReturnBusy) return NO;
        usleep(1000);
    }
    return NO;
}
@implementation RedfinDisplayProbe
- (void)tick:(CADisplayLink *)link
{
    if (self.finished) return;
    double now=link.timestamp;
    if (!self.began) {self.began=now;self.last=now;}
    else {
        double interval=now-self.last;self.last=now;
        if (interval>self.maximum) self.maximum=interval;
        if (interval>0 && interval<=0.0125) self.under12++;
        if (interval>0 && interval<=0.018) self.under18++;
        if (interval>0 && interval<=0.035) self.under35++;
    }
    self.callbacks++;
    [CATransaction begin];[CATransaction setDisableActions:YES];
    double t=now-self.began;
    for (unsigned i=0;i<self.squares.count;++i) {
        CALayer *square=self.squares[i];
        square.position=CGPointMake(187.5+120*sin(t*2.0+i),140+i*74+24*cos(t*3.0+i));
        square.transform=CATransform3DMakeRotation(t+i*0.25,0,0,1);
    }
    [CATransaction commit];
    if (t>=10) [self finish:NO];
}
- (void)finish:(BOOL)timedOut
{
    if (self.finished) return;
    self.finished=YES;[self.link invalidate];self.link=nil;
    struct redfin_display_statistics final={0};
    BOOL valid=sample(self.framebuffer,self.nonce,&final) && final.ticks>self.first.ticks &&
        final.presents>=self.first.presents && final.gpu_presents>=self.first.gpu_presents &&
        final.panel_hz==self.first.panel_hz;
    mach_timebase_info_data_t scale={0};mach_timebase_info(&scale);
    double seconds=valid && scale.denom ? (double)(final.ticks-self.first.ticks)*scale.numer/scale.denom/1e9 : 0;
    uint64_t presents=valid ? final.presents-self.first.presents : 0;
    uint64_t gpu=valid ? final.gpu_presents-self.first.gpu_presents : 0;
    double elapsed=self.last-self.began;
    probe_log(self.nonce,"result stats-valid=%u timed-out=%u panel-hz=%u seconds=%.6f completed-presents=%llu gpu-presents=%llu present-fps=%.3f callbacks=%u callback-fps=%.3f under12=%u under18=%u under35=%u max-interval-ms=%.3f",
        valid,timedOut,valid ? final.panel_hz : 0,seconds,(unsigned long long)presents,(unsigned long long)gpu,
        seconds>0 ? presents/seconds : 0,self.callbacks,elapsed>0 ? (self.callbacks-1)/elapsed : 0,
        self.under12,self.under18,self.under35,self.maximum*1000);
    if (self.framebuffer) IOServiceClose(self.framebuffer);
    self.framebuffer=0;self.window.hidden=YES;self.window=nil;self.squares=nil;
    active_probe=nil;
}
@end

void redfin_display_probe_schedule(UIWindow *host,uint64_t nonce)
{
    static BOOL scheduled;
    if (scheduled || !NSThread.isMainThread || !host || !nonce ||
        strcmp(NSProcessInfo.processInfo.processName.UTF8String,"SpringBoard")) return;
    scheduled=YES;
    UIWindow *native_host=host;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        UIWindow *parent=native_host;
        if (!parent || parent.screen!=UIScreen.mainScreen) return;
        io_service_t service=IOServiceGetMatchingService(0,IOServiceMatching("AppleCLCD"));
        io_connect_t client=0;
        kern_return_t opened=service ? IOServiceOpen(service,mach_task_self(),0,&client) : KERN_FAILURE;
        if (service) IOObjectRelease(service);
        struct redfin_display_statistics start={0};
        if (opened!=KERN_SUCCESS || !sample(client,nonce,&start)) {
            probe_log(nonce,"refused native completed-presentation statistics unavailable error=%#x",opened);
            if (client) IOServiceClose(client);
            return;
        }
        RedfinDisplayProbe *probe=[RedfinDisplayProbe new];
        probe.framebuffer=client;probe.nonce=nonce;probe.first=start;
        UIWindow *window=parent.windowScene ? [[UIWindow alloc] initWithWindowScene:parent.windowScene] :
            [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
        window.frame=UIScreen.mainScreen.bounds;window.backgroundColor=UIColor.clearColor;
        window.opaque=NO;window.userInteractionEnabled=NO;window.windowLevel=UIWindowLevelNormal+1;
        UIViewController *controller=[UIViewController new];controller.view.backgroundColor=UIColor.clearColor;
        window.rootViewController=controller;
        NSMutableArray *squares=[NSMutableArray array];
        for (unsigned i=0;i<6;++i) {
            CALayer *square=[CALayer layer];square.bounds=CGRectMake(0,0,36,36);square.cornerRadius=8;
            square.backgroundColor=[UIColor colorWithHue:i/6.0 saturation:0.8 brightness:0.9 alpha:0.85].CGColor;
            [controller.view.layer addSublayer:square];[squares addObject:square];
        }
        probe.squares=squares;probe.window=window;active_probe=probe;
        window.hidden=NO;
        CADisplayLink *link=[CADisplayLink displayLinkWithTarget:probe selector:@selector(tick:)];
        link.preferredFrameRateRange=CAFrameRateRangeMake(start.panel_hz,start.panel_hz,start.panel_hz);
        probe.link=link;[link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
        probe_log(nonce,"start native-UIKit=1 seconds=10 layers=6 panel-hz=%u begin-presents=%llu begin-gpu=%llu",
            start.panel_hz,(unsigned long long)start.presents,(unsigned long long)start.gpu_presents);
        __weak RedfinDisplayProbe *weak=probe;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,25*NSEC_PER_SEC),dispatch_get_main_queue(),^{[weak finish:YES];});
    });
}
