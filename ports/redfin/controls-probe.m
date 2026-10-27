/* SPDX-License-Identifier: MIT */
/* Explicit one-boot native system brightness -> CoreBrightness -> DSI/wake observation.
 * Restores the user's brightness and display state on every changed path.
 * Actual physical key presses remain distinct from input-path readiness. */
#import <UIKit/UIKit.h>
#include <IOKit/IOKitLib.h>
#include <mach/mach_time.h>
#include <sys/sysctl.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdarg.h>
#include <unistd.h>
#include <math.h>
#include "gui-profile.h"
#include "display-statistics.h"
#include "controls-policy.h"
#include "brightness-system.h"

static double control_seconds(void)
{
    mach_timebase_info_data_t scale={0};mach_timebase_info(&scale);
    return scale.denom?(double)mach_absolute_time()*scale.numer/scale.denom/1e9:0;
}
static void control_log(uint64_t nonce,const char *format,...)
{
    char line[1024];int prefix=snprintf(line,sizeof(line),"REDFIN CONTROLS PROBE: boot=%016llx ",(unsigned long long)nonce);
    if(prefix<0||(size_t)prefix>=sizeof(line))return;
    va_list args;va_start(args,format);int count=vsnprintf(line+prefix,sizeof(line)-(size_t)prefix,format,args);va_end(args);
    if(count<0||(size_t)count>=sizeof(line)-(size_t)prefix-1)return;
    size_t bytes=(size_t)(prefix+count);line[bytes++]='\n';
    int fd=open("/private/var/mobile/Library/Logs/redfin-ui.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if(fd>=0){(void)write(fd,line,bytes);close(fd);}
}
static BOOL control_uint(NSDictionary *properties,NSString *key,uint64_t *value)
{
    id n=properties[key];if(![n isKindOfClass:NSNumber.class])return NO;
    *value=[n unsignedLongLongValue];return YES;
}
static NSDictionary *control_properties(io_service_t service)
{
    CFMutableDictionaryRef values=NULL;
    if(IORegistryEntryCreateCFProperties(service,&values,kCFAllocatorDefault,0)!=KERN_SUCCESS)return nil;
    return CFBridgingRelease(values);
}
static BOOL control_sysctl(const char *name,unsigned *value)
{
    size_t bytes=sizeof(*value);return !sysctlbyname(name,value,&bytes,NULL,0)&&bytes==sizeof(*value);
}

@interface RedfinControlsProbe : NSObject
@property(nonatomic) io_service_t service;
@property(nonatomic) io_connect_t client;
@property(nonatomic) uint64_t nonce,cursor,offFrames;
@property(nonatomic) unsigned phase,error,lowDBV,highDBV,initialKeySamples,initialKeyErrors;
@property(nonatomic) unsigned loggedPhase;
@property(nonatomic) double savedBrightness,lowBrightness,highBrightness,began,phaseBegan,offSampleAt;
@property(nonatomic) double clockRatio;
@property(nonatomic) double loggedAt;
@property(nonatomic) BOOL finished,offProven,wakeProven,restoreNeedsCommit;
@property(nonatomic,copy) void (^completion)(BOOL,BOOL);
- (void)poll;
- (void)restore:(unsigned)error;
- (void)finish:(BOOL)restored;
@end

static RedfinControlsProbe *control_active;
@implementation RedfinControlsProbe
- (BOOL)statistics:(struct redfin_display_statistics_v2 *)snapshot
{
    size_t bytes=sizeof(*snapshot);uint64_t nonce=self.nonce;
    kern_return_t status=IOConnectCallMethod(self.client,REDFIN_DISPLAY_STATISTICS_SELECTOR_V2,&nonce,1,
        NULL,0,NULL,NULL,snapshot,&bytes);
    return status==KERN_SUCCESS&&bytes==sizeof(*snapshot)&&redfin_display_statistics_valid_v2(snapshot);
}
- (BOOL)power:(BOOL)on
{
    uint64_t value=on?1:0;
    kern_return_t status=IOConnectCallScalarMethod(self.client,12,&value,1,NULL,NULL);
    control_log(self.nonce,"power-request on=%u result=%#x",on,status);return status==KERN_SUCCESS;
}
- (void)restore:(unsigned)error
{
    if(self.phase==5||self.finished)return;
    if(!self.error)self.error=error;
    NSDictionary *properties=control_properties(self.service);
    uint64_t sequence=0,on=0;
    if(control_uint(properties,@"RedfinControlSequence",&sequence))self.cursor=sequence;
    self.restoreNeedsCommit=fabs(redfin_brightness_system_get()-self.savedBrightness)>=0.01||
        !control_uint(properties,@"RedfinDisplayOn",&on)||!on;
    self.phase=5;self.phaseBegan=control_seconds()/self.clockRatio;
    if(!redfin_brightness_system_set((float)self.savedBrightness)&&!self.error)self.error=8;
    if(![self power:YES]&&!self.error)self.error=8;
    control_log(self.nonce,"restore-start reason=%u native-brightness=%.5f",self.error,self.savedBrightness);
}
- (void)finish:(BOOL)restored
{
    if(self.finished)return;self.finished=YES;
    unsigned samples=0,errors=0,armed=0,consumer=0,usable=0;
    BOOL keys=control_sysctl("kern.redfin_controls.keys_samples",&samples)&&
        control_sysctl("kern.redfin_controls.keys_errors",&errors)&&
        control_sysctl("kern.redfin_controls.keys_armed",&armed)&&
        control_sysctl("kern.redfin_controls.keys_consumer",&consumer)&&
        control_sysctl("kern.redfin_controls.keys_usable",&usable)&&samples>self.initialKeySamples&&
        errors==self.initialKeyErrors&&armed==7&&usable==7&&consumer==1;
    BOOL brightness=self.lowDBV&&self.highDBV>self.lowDBV;
    unsigned result=self.error?self.error:!restored?9:!keys?10:
        !(brightness&&self.offProven&&self.wakeProven)?12:0;
    control_log(self.nonce,"result=%u restored=%u native-system-physical-DBV=%u low=%u high=%u display-off-stops-output=%u wake-resumes-output=%u physical-key-input-ready=%u key-samples=%u key-errors=%u physical-key-presses-tested=0",
        result,restored,brightness,self.lowDBV,self.highDBV,self.offProven,self.wakeProven,keys,samples,errors);
    if(self.client)IOServiceClose(self.client);if(self.service)IOObjectRelease(self.service);
    self.client=0;self.service=0;
    void (^completion)(BOOL,BOOL)=self.completion;self.completion=nil;control_active=nil;
    if(completion)completion(restored,result==0);
}
- (void)poll
{
    if(self.finished)return;
    double now=control_seconds()/self.clockRatio;
    NSDictionary *properties=control_properties(self.service);
    uint64_t sequence=0,level=0,on=0,uncertain=0,applied_nits=0,requested_nits=0;
    uint32_t expected=0;
    BOOL valid=properties&&control_uint(properties,@"RedfinControlSequence",&sequence)&&
        control_uint(properties,@"RedfinAppliedDBV",&level)&&control_uint(properties,@"RedfinDisplayOn",&on)&&
        control_uint(properties,@"RedfinControlUncertain",&uncertain)&&level>=4&&level<=1023;
    BOOL state=valid&&!uncertain;
    BOOL brightnessApplied=state&&control_uint(properties,@"RedfinAppliedNits",&applied_nits)&&
        control_uint(properties,@"IOMFBBrightnessLevel",&requested_nits)&&applied_nits==requested_nits&&
        rf_panel_nits_to_dbv(applied_nits,&expected)&&expected==level;
    double brightness=redfin_brightness_system_get();
    if(self.loggedPhase!=self.phase||now-self.loggedAt>=1) {
        self.loggedPhase=self.phase;self.loggedAt=now;
        control_log(self.nonce,"state phase=%u system=%.5f valid=%u applied=%u on=%llu sequence=%llu DBV=%llu requested-nits16=%llu applied-nits16=%llu uncertain=%llu",
            self.phase,brightness,valid,brightnessApplied,(unsigned long long)on,(unsigned long long)sequence,
            (unsigned long long)level,(unsigned long long)requested_nits,(unsigned long long)applied_nits,(unsigned long long)uncertain);
    }
    if(self.phase!=5&&(now-self.began>20||!properties||uncertain||!isfinite(brightness))) {
        [self restore:uncertain?7:!isfinite(brightness)?8:6];
    } else if(self.phase==1&&brightnessApplied&&on&&sequence>self.cursor&&fabs(brightness-self.lowBrightness)<0.01) {
        self.lowDBV=(unsigned)level;self.cursor=sequence;self.phase=2;self.phaseBegan=now;
        control_log(self.nonce,"low system=%.5f applied-DBV=%u sequence=%llu",brightness,self.lowDBV,(unsigned long long)sequence);
        if(!redfin_brightness_system_set((float)self.highBrightness))[self restore:8];
    } else if(self.phase==2&&brightnessApplied&&on&&sequence>self.cursor&&level>self.lowDBV&&fabs(brightness-self.highBrightness)<0.01) {
        self.highDBV=(unsigned)level;self.cursor=sequence;self.phase=3;self.phaseBegan=now;
        control_log(self.nonce,"high system=%.5f applied-DBV=%u sequence=%llu",brightness,self.highDBV,(unsigned long long)sequence);
        if(![self power:NO])[self restore:4];
    } else if(self.phase==3&&state&&!on&&sequence>self.cursor&&now-self.phaseBegan>=0.25) {
        struct redfin_display_statistics_v2 snapshot={0};
        if([self statistics:&snapshot]) {
            if(!self.offSampleAt){self.offSampleAt=now;self.offFrames=snapshot.presents;}
            else if(now-self.offSampleAt>=0.25) {
                if(snapshot.presents!=self.offFrames)[self restore:5];
                else {
                    self.offProven=YES;
                    self.cursor=sequence;self.phase=4;self.phaseBegan=now;
                    control_log(self.nonce,"display-off stable-presents=%llu",(unsigned long long)self.offFrames);
                    if(![self power:YES])[self restore:4];
                }
            }
        }
    } else if(self.phase==4&&state&&on&&sequence>self.cursor) {
        struct redfin_display_statistics_v2 snapshot={0};
        if([self statistics:&snapshot]&&snapshot.presents>self.offFrames) {
            self.wakeProven=YES;
            self.cursor=sequence;
            control_log(self.nonce,"display-on resumed-presents=%llu",(unsigned long long)snapshot.presents);
            [self restore:0];
        }
    } else if(self.phase==5) {
        if(brightnessApplied&&on&&sequence>=self.cursor+(self.restoreNeedsCommit?1:0)&&
            fabs(brightness-self.savedBrightness)<0.01) {[self finish:YES];return;}
        if(now-self.phaseBegan>4){[self finish:NO];return;}
    }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC/10),dispatch_get_main_queue(),^{[self poll];});
}
@end

void redfin_controls_probe_run(uint64_t nonce,void (^completion)(BOOL,BOOL))
{
    if(control_active||!NSThread.isMainThread||!nonce){if(completion)completion(NO,NO);return;}
    RedfinControlsProbe *probe=[RedfinControlsProbe new];probe.nonce=nonce;probe.completion=completion;
    probe.service=IOServiceGetMatchingService(0,IOServiceMatching("AppleCLCD"));
    NSDictionary *properties=probe.service?control_properties(probe.service):nil;
    uint64_t abi=0,on=0,sequence=0;
    BOOL supported=redfin_brightness_system_ready()&&properties&&control_uint(properties,@"RedfinDisplayControlABI",&abi)&&abi==1&&
        control_uint(properties,@"RedfinDisplayOn",&on)&&on==1&&control_uint(properties,@"RedfinControlSequence",&sequence);
    io_connect_t client=0;
    if(!supported||IOServiceOpen(probe.service,mach_task_self(),0,&client)!=KERN_SUCCESS) {
        control_log(nonce,"refused native-controls-unavailable result=11 restored=1 unchanged=1");
        if(probe.service)IOObjectRelease(probe.service);if(completion)completion(YES,NO);return;
    }
    probe.client=client;
    struct redfin_display_statistics_v2 initial={0};mach_timebase_info_data_t scale={0};mach_timebase_info(&scale);
    BOOL statistics=[probe statistics:&initial];
    probe.clockRatio=statistics&&scale.denom?(double)initial.counter_hz*scale.numer/scale.denom/1e9:0;
    probe.savedBrightness=redfin_brightness_system_get();
    if(!isfinite(probe.savedBrightness)||probe.savedBrightness<0||probe.savedBrightness>1||
        !isfinite(probe.clockRatio)||probe.clockRatio<0.25||probe.clockRatio>4) {
        control_log(nonce,"refused native-brightness-or-statistics result=11 restored=1 unchanged=1");
        IOServiceClose(client);IOObjectRelease(probe.service);if(completion)completion(YES,NO);return;
    }
    probe.lowBrightness=fabs(probe.savedBrightness-0.15)<0.03?0.25:0.15;
    probe.highBrightness=fabs(probe.savedBrightness-0.75)<0.03?0.85:0.75;
    unsigned samples=0,errors=0;
    (void)control_sysctl("kern.redfin_controls.keys_samples",&samples);
    (void)control_sysctl("kern.redfin_controls.keys_errors",&errors);
    probe.initialKeySamples=samples;probe.initialKeyErrors=errors;
    probe.cursor=sequence;probe.began=probe.phaseBegan=control_seconds()/probe.clockRatio;probe.phase=1;
    control_active=probe;
    control_log(nonce,"start native-ABI=1 system-BKS=1 scene-independent=1 saved=%.5f low=%.5f high=%.5f bounded-seconds=24",
        probe.savedBrightness,probe.lowBrightness,probe.highBrightness);
    if(!redfin_brightness_system_set((float)probe.lowBrightness))[probe restore:8];
    [probe poll];
}
