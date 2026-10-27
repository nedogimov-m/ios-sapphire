"""Run the actual system controls observer on the native Objective-C runtime.

Replace only screen/IOKit/time primitives; prove outcome labels, restoration
and finite failure behavior without touching a real display or credentials.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent

PRELUDE=r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdarg.h>
#include "gui-profile.h"
#include "display-statistics.h"
typedef unsigned io_service_t,io_connect_t;typedef int kern_return_t;
typedef struct {unsigned numer,denom;} mach_timebase_info_data_t;
#define KERN_SUCCESS 0
static uint64_t ns=1000000000,sequence=1,nits=250ULL<<16,applied_nits=250ULL<<16,presents=10;
static unsigned dbv=512,issue;static BOOL panel_on=YES,composition_active,ever_off;
static NSMutableString *transcript;static void (^scheduled)(void);
static uint64_t fake_mach_absolute_time(void){return ns;}
static int fake_mach_timebase_info(mach_timebase_info_data_t *scale){scale->numer=scale->denom=1;return 0;}
#define mach_absolute_time fake_mach_absolute_time
#define mach_timebase_info fake_mach_timebase_info
static uint64_t fake_dispatch_time(uint64_t origin,int64_t offset){(void)origin;return (uint64_t)offset;}
static void fake_dispatch_after(uint64_t when,dispatch_queue_t queue,void (^block)(void)){
 (void)queue;ns+=when;assert(!scheduled);scheduled=[block copy];}
#define dispatch_time fake_dispatch_time
#define dispatch_after fake_dispatch_after
static int fake_open(const char *path,int flags,...){(void)path;(void)flags;return 77;}
static ssize_t fake_write(int fd,const void *bytes,size_t length){assert(fd==77);
 [transcript appendString:[[NSString alloc] initWithBytes:bytes length:length encoding:NSUTF8StringEncoding]];return (ssize_t)length;}
static int fake_close(int fd){assert(fd==77);return 0;}
#define open fake_open
#define write fake_write
#define close fake_close
@interface UIScreen : NSObject
@property(nonatomic) double brightness;
+ (UIScreen *)mainScreen;
@end
@implementation UIScreen
+ (UIScreen *)mainScreen {static UIScreen *screen;if(!screen){screen=[UIScreen new];screen->_brightness=0.5;}return screen;}
- (void)setBrightness:(double)value { _brightness=value;
 if(issue==7&&value<0.3)return;
 if(issue==11&&value==0.5){++sequence;return;}
 uint64_t next=(uint64_t)llround(value*500*65536);
 if(next!=nits){nits=next;++sequence;}
 if(panel_on){applied_nits=nits;dbv=(unsigned)((nits*1023+(500ULL<<15))/(500ULL<<16));if(dbv<4)dbv=4;}
}
@end
bool redfin_brightness_system_ready(void){return issue!=5;}
float redfin_brightness_system_get(void){return issue==10&&ns>1000000000?NAN:(float)UIScreen.mainScreen.brightness;}
bool redfin_brightness_system_set(float value){
 if((issue==8&&value<0.3)||(issue==9&&value>0.7))return false;
 UIScreen.mainScreen.brightness=value;return true;}
static int sysctlbyname(const char *name,void *out,size_t *bytes,void *input,size_t input_bytes){
 (void)input;(void)input_bytes;if(*bytes!=sizeof(unsigned))return 1;
 unsigned value=strstr(name,"samples")?(unsigned)(ns/10000000):strstr(name,"errors")?0:strstr(name,"consumer")?1:7;
 if(issue==1&&strstr(name,"usable"))value=5;*(unsigned *)out=value;return 0;}
#define IOServiceMatching fake_IOServiceMatching
#define IOServiceGetMatchingService fake_IOServiceGetMatchingService
#define IOServiceOpen fake_IOServiceOpen
#define IOObjectRelease fake_IOObjectRelease
#define IOServiceClose fake_IOServiceClose
#define IORegistryEntryCreateCFProperties fake_IORegistryEntryCreateCFProperties
#define IOConnectCallMethod fake_IOConnectCallMethod
#define IOConnectCallScalarMethod fake_IOConnectCallScalarMethod
#undef mach_task_self
#define mach_task_self() 1u
static void *IOServiceMatching(const char *name){(void)name;return NULL;}
static io_service_t IOServiceGetMatchingService(unsigned master,void *match){(void)master;(void)match;return 1;}
static int IOServiceOpen(io_service_t service,unsigned task,unsigned type,io_connect_t *client){(void)service;(void)task;(void)type;*client=1;return 0;}
static int IOObjectRelease(io_service_t service){(void)service;return 0;}
static int IOServiceClose(io_connect_t client){(void)client;return 0;}
static int IORegistryEntryCreateCFProperties(io_service_t service,CFMutableDictionaryRef *values,CFAllocatorRef allocator,unsigned options){
 (void)service;(void)allocator;(void)options;
 if(composition_active&&issue!=13&&!(issue==14&&ever_off)&&(panel_on||issue==3))++presents;
 NSDictionary *p=@{@"RedfinDisplayControlABI":@(issue==5?0:1),@"RedfinDisplayOn":@(panel_on),
 @"RedfinControlSequence":@(sequence),@"RedfinAppliedDBV":@(dbv),@"RedfinControlUncertain":@(issue==12&&ns>1000000000),
 @"RedfinAppliedNits":@(applied_nits),@"IOMFBBrightnessLevel":@(nits)};
 *values=(CFMutableDictionaryRef)CFBridgingRetain(p);return 0;}
static int IOConnectCallMethod(io_connect_t client,unsigned selector,const uint64_t *in,unsigned in_count,
 const void *input,size_t input_bytes,uint64_t *out,unsigned *out_count,void *result,size_t *bytes){
 (void)client;(void)selector;(void)in;(void)in_count;(void)input;(void)input_bytes;(void)out;(void)out_count;
 struct redfin_display_statistics_v2 s={2,sizeof(s),ns,presents,presents,90,0,1000000000};
 assert(*bytes==sizeof(s));memcpy(result,&s,sizeof(s));return issue==6?1:0;}
static int IOConnectCallScalarMethod(io_connect_t client,unsigned selector,const uint64_t *value,unsigned count,uint64_t *out,unsigned *out_count){
 (void)client;(void)out;(void)out_count;assert(selector==12&&count==1);
 if((issue==2&&!*value)||(issue==4&&*value))return 1;
 if(panel_on!=(*value!=0)){panel_on=*value!=0;++sequence;}
 if(!panel_on)ever_off=YES;
 if(panel_on){applied_nits=nits;dbv=(unsigned)((nits*1023+(500ULL<<15))/(500ULL<<16));if(dbv<4)dbv=4;}
 return 0;}
'''

SUFFIX=r'''
int main(int argc,char **argv){@autoreleasepool{
 assert(argc==2);issue=(unsigned)atoi(argv[1]);transcript=[NSMutableString new];
 __block BOOL called=NO,restored=NO,passed=NO,workload=NO;__block unsigned starts=0,stops=0;
 redfin_controls_probe_run(0x12345678abcdef01,^BOOL(BOOL start,double ratio){assert(ratio==1);
  if(start&&issue==15)return NO;
  if(start){assert(!workload&&!starts);workload=YES;composition_active=YES;++starts;}
  else{assert(workload&&starts==1&&!stops);workload=NO;composition_active=NO;++stops;}
  return YES;
 },^(BOOL r,BOOL p){assert(!called&&!workload);called=YES;restored=r;passed=p;});
 for(unsigned i=0;scheduled&&i<400;++i){void (^block)(void)=scheduled;scheduled=nil;block();}
 assert(called);assert(!scheduled);assert(!control_active);
 if(issue==0){assert(restored&&passed);assert([transcript containsString:@"result=0 restored=1"]);
  assert([transcript containsString:@"display-off-stops-output=1 wake-resumes-output=1 physical-key-input-ready=1"]);}
 else {assert(!passed);
  if(issue==1){assert(restored);assert([transcript containsString:@"result=10 restored=1"]);}
  if(issue==2){assert(restored);assert([transcript containsString:@"display-off-stops-output=0 wake-resumes-output=0"]);}
  if(issue==3){assert(restored);assert([transcript containsString:@"result=5 restored=1"]);}
  if(issue==4){assert(!restored);assert([transcript containsString:@"wake-resumes-output=0"]);}
  if(issue==5||issue==6){assert(restored);assert([transcript containsString:@"unchanged=1"]);}
  if(issue==7){assert(restored);assert([transcript containsString:@"display-off-stops-output=0 wake-resumes-output=0"]);
   assert([transcript containsString:@"restore-proven original-physical-state=1 new-native-commit=0"]);}
  if(issue==8||issue==9){assert(restored);assert([transcript containsString:@"result=8 restored=1"]);}
  if(issue==10){assert(!restored);assert([transcript containsString:@"result=8 restored=0"]);}
  if(issue==11){assert(!restored);assert([transcript containsString:@"result=9 restored=0"]);}
  if(issue==12){assert(!restored);assert([transcript containsString:@"result=7 restored=0"]);}
  if(issue==13){assert(restored&&!ever_off);assert([transcript containsString:@"result=6 restored=1"]);}
  if(issue==14){assert(restored&&ever_off);assert([transcript containsString:@"display-off-stops-output=1 wake-resumes-output=0"]);}
  if(issue==15){assert(restored&&!ever_off);assert([transcript containsString:@"refused no-visible-content-workload result=13 restored=1 unchanged=1"]);}
 }
 if(issue==5||issue==6||issue==15)assert(!starts&&!stops);else assert(starts==1&&stops==1);
 if(restored){assert(panel_on);assert(fabs(UIScreen.mainScreen.brightness-0.5)<0.001);}
 assert(ns<30000000000ULL);
}return 0;}
'''


@unittest.skipUnless(sys.platform=='darwin','native Objective-C runtime required')
class ControlsProbeTests(unittest.TestCase):
    def test_real_observer_restores_and_never_promotes_a_failed_path_to_success(self):
        actual=(HERE/'controls-probe.m').read_text()
        for line in ('#import <UIKit/UIKit.h>','#include <IOKit/IOKitLib.h>',
                     '#include <mach/mach_time.h>','#include <sys/sysctl.h>'):
            actual=actual.replace(line,'')
        with tempfile.TemporaryDirectory(prefix='redfin-controls-ui-') as directory:
            root=Path(directory);source=root/'probe.m';source.write_text(PRELUDE+actual+SUFFIX)
            compiled=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),'-framework','Foundation',str(source),'-o',str(root/'probe')],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            for issue in range(16):
                result=subprocess.run([str(root/'probe'),str(issue)],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,(issue,result.stderr))


if __name__=='__main__':unittest.main()
