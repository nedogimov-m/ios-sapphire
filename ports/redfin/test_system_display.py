"""Execute native backlight routing and owned idle assertions on ObjC runtime."""
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent

COMMON=r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <dlfcn.h>
static unsigned issue;
static bool redfin_native_image_uuid(const void *function,const uint8_t expected[16]) {
 return function&&expected&&issue!=2&&!(issue==6&&expected[0]==2);
}
static Class redfin_test_getClass(const char *name) {
 NSString *qualified=[@"RedfinTest" stringByAppendingString:[NSString stringWithUTF8String:name]];
 return objc_getClass(qualified.UTF8String);
}
#define objc_getClass redfin_test_getClass
#define BSSimpleAssertion RedfinTestBSSimpleAssertion
#define SBIdleTimerGlobalCoordinator RedfinTestSBIdleTimerGlobalCoordinator
#define CAWindowServerDisplay RedfinTestCAWindowServerDisplay
#define BLControl RedfinTestBLControl
#define CBDisplayContaineriOS RedfinTestCBDisplayContaineriOS
#define CBDisplayModuleiOS RedfinTestCBDisplayModuleiOS
'''
BACKLIGHT=r'''
#include <fcntl.h>
#include <unistd.h>
#include <stdarg.h>
static unsigned calls;
static const char *fake_getprogname(void){return issue==5?"ordinary-app":"backboardd";}
#define getprogname fake_getprogname
static int fake_open(const char *path,int flags,...){(void)path;(void)flags;return -1;}
#define open fake_open
#define REDFIN_QUARTZ_UUID_BYTES 1
#define REDFIN_CB_UUID_BYTES 2
typedef unsigned io_service_t;typedef int kern_return_t;
#define KERN_SUCCESS 0
#define KERN_FAILURE 5
#define IOServiceMatching redfin_test_IOServiceMatching
#define IOServiceGetMatchingService redfin_test_IOServiceGetMatchingService
#define IOObjectRelease redfin_test_IOObjectRelease
#define IORegistryEntryCreateCFProperties redfin_test_IORegistryEntryCreateCFProperties
static void *IOServiceMatching(const char *name){assert(!strcmp(name,"AppleARMBacklight"));return NULL;}
static io_service_t IOServiceGetMatchingService(unsigned master,void *match){(void)master;(void)match;return 1;}
static int IOObjectRelease(io_service_t service){assert(service==1);return 0;}
static int IORegistryEntryCreateCFProperties(io_service_t service,CFMutableDictionaryRef *values,CFAllocatorRef allocator,unsigned options){
 (void)allocator;(void)options;assert(service==1);uint32_t separate=1;
 NSDictionary *p=@{@"ignore-IOMFB":issue==4?(id)@YES:(id)[NSData dataWithBytes:&separate length:4],
  @"RedfinDisplayControlABI":@(issue==1?0:1),@"RedfinCoreBrightnessABI":@1,
  @"IODisplayParameters":@{@"brightness":@{@"min":@4,@"max":@(issue==3?1022:1023),@"value":@409}}};
 *values=(CFMutableDictionaryRef)CFBridgingRetain(p);return 0;
}
static void *fake_dlopen(const char *path,int mode){(void)path;(void)mode;return (void *)1;}
#define dlopen fake_dlopen
@interface CAWindowServerDisplay:NSObject
@property(nonatomic) NSInteger displayType;
- (BOOL)brightnessAvailable;
@end
@implementation CAWindowServerDisplay
- (BOOL)brightnessAvailable{return YES;}
@end
@interface BLControl:NSObject
- (BOOL)useSyncBrightnessTransactionForDisplay:(id)display;
- (BOOL)findDisplays;
- (BOOL)findBacklight;
@end
@implementation BLControl
- (BOOL)useSyncBrightnessTransactionForDisplay:(id)display{return [display brightnessAvailable];}
- (BOOL)findDisplays{return issue!=7;}
- (BOOL)findBacklight{return issue!=7;}
@end
@interface CBDisplayContaineriOS:NSObject
- (BOOL)start;
- (BOOL)setupInternalModules;
@end
@implementation CBDisplayContaineriOS
- (BOOL)start{return issue!=7;}
- (BOOL)setupInternalModules{return issue!=7;}
@end
@interface CBDisplayModuleiOS:NSObject
#ifdef REDFIN_TEST_BAD_TYPE
- (BOOL)start;
#else
- (void)start;
#endif
@end
@implementation CBDisplayModuleiOS
#ifdef REDFIN_TEST_BAD_TYPE
- (BOOL)start{++calls;return YES;}
#else
- (void)start{++calls;}
#endif
@end
'''
BACKLIGHT_END=r'''
int main(int argc,char **argv){@autoreleasepool{
 assert(argc==2);issue=(unsigned)atoi(argv[1]);
 CAWindowServerDisplay *integrated=[CAWindowServerDisplay new],*external=[CAWindowServerDisplay new];
 external.displayType=1;
 redfin_backlight_system_install("12345678abcdef01");
 BLControl *control=[BLControl new];CBDisplayContaineriOS *container=[CBDisplayContaineriOS new];
 BOOL installed=issue==0||issue==7;
#ifdef REDFIN_TEST_BAD_TYPE
 installed=NO;
#endif
 assert([integrated brightnessAvailable]==!installed);
 assert([external brightnessAvailable]);
 assert([control useSyncBrightnessTransactionForDisplay:integrated]==!installed);
 assert([control useSyncBrightnessTransactionForDisplay:external]);
 assert([control findDisplays]==(issue!=7));assert([control findBacklight]==(issue!=7));
 assert([container start]==(issue!=7));assert([container setupInternalModules]==(issue!=7));
 [[CBDisplayModuleiOS new] start];assert(calls==1);
 redfin_backlight_system_install("12345678abcdef01");
 assert([integrated brightnessAvailable]==!installed&&[external brightnessAvailable]);
}return 0;}
'''
IDLE=r'''
#include <stdlib.h>
static const char *fake_getprogname(void){return issue==8?"ordinary-app":"SpringBoard";}
#define getprogname fake_getprogname
#define REDFIN_SB_UUID_BYTES 3
#define REDFIN_BB_UUID_BYTES 4
static unsigned created,invalidations;
static BOOL other_client;
static NSString *last_reason;
@interface BSSimpleAssertion:NSObject
@property(nonatomic,getter=isValid) BOOL valid;
- (void)invalidate;
@end
@implementation BSSimpleAssertion
- (void)invalidate{++invalidations;if(issue!=7)self.valid=NO;}
@end
static BSSimpleAssertion *last_assertion;
@interface SBIdleTimerGlobalCoordinator:NSObject
+ (id)sharedInstanceIfExists;
- (id)acquireIdleTimerDisableAssertionForReason:(NSString *)reason;
- (BOOL)isIdleTimerDisabled;
@end
@implementation SBIdleTimerGlobalCoordinator
+ (id)sharedInstanceIfExists{static id c;if(issue==1)return nil;if(!c)c=[self new];return c;}
- (id)acquireIdleTimerDisableAssertionForReason:(NSString *)reason{
 ++created;last_reason=reason;last_assertion=[BSSimpleAssertion new];last_assertion.valid=YES;return last_assertion;
}
- (BOOL)isIdleTimerDisabled{return issue!=3&&(other_client||last_assertion.isValid);}
@end
'''
IDLE_END=r'''
int main(int argc,char **argv){@autoreleasepool{
 assert(argc==2);issue=(unsigned)atoi(argv[1]);other_client=issue==4;
 BOOL ready;
 if(issue==6){__block BOOL acquired=YES;dispatch_semaphore_t done=dispatch_semaphore_create(0);
  dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
   acquired=redfin_idle_system_begin(1);dispatch_semaphore_signal(done);
  });dispatch_semaphore_wait(done,DISPATCH_TIME_FOREVER);ready=acquired;
 }else ready=redfin_idle_system_begin(0x12345678abcdef01);
 if(issue==1||issue==2||issue==6||issue==8){assert(!ready&&!created&&!invalidations&&!idle_assertion);}
 else if(issue==3){assert(!ready&&created==1&&invalidations==1&&!last_assertion.isValid&&!idle_assertion);}
 else{
  assert(ready&&created==1&&last_assertion.isValid&&idle_assertion==last_assertion);
  assert([last_reason isEqualToString:@"com.redfin.finite-display-probe.12345678abcdef01"]);
  if(issue==5)assert(!redfin_idle_system_begin(2)&&created==1&&last_assertion.isValid);
  if(issue==7){assert(!redfin_idle_system_end()&&idle_assertion==last_assertion&&last_assertion.isValid);issue=0;}
  assert(redfin_idle_system_end()&&!idle_assertion&&!last_assertion.isValid);
  unsigned count=invalidations;assert(redfin_idle_system_end()&&count==invalidations);
  assert(other_client==(argc&&atoi(argv[1])==4));
  assert([[SBIdleTimerGlobalCoordinator sharedInstanceIfExists] isIdleTimerDisabled]==other_client);
 }
}return 0;}
'''


@unittest.skipUnless(sys.platform=='darwin' and platform.machine()=='arm64','native arm64 Objective-C runtime required')
class SystemDisplayTests(unittest.TestCase):
    def run_actual(self,source,prelude,suffix,cases,defines=()):
        actual=(HERE/source).read_text()
        for include in ('#include "native-image-uuid.h"','#include <IOKit/IOKitLib.h>'):
            actual=actual.replace(include,'')
        with tempfile.TemporaryDirectory(prefix='redfin-system-display-') as directory:
            root=Path(directory);path=root/'native.m';path.write_text(COMMON+prelude+actual+suffix)
            compiled=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),*defines,'-framework','Foundation',str(path),'-o',str(root/'native')],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            for issue in cases:
                run=subprocess.run([str(root/'native'),str(issue)],capture_output=True,text=True,timeout=5)
                self.assertEqual(run.returncode,0,(issue,run.stderr))

    def test_only_bound_integrated_backlight_selects_legacy_without_changing_native_results(self):
        self.run_actual('backlight-system.m',BACKLIGHT,BACKLIGHT_END,range(8))
        self.run_actual('backlight-system.m',BACKLIGHT,BACKLIGHT_END,[0],['-DREDFIN_TEST_BAD_TYPE'])

    def test_idle_assertion_owns_only_its_token_and_releases_on_refusal_or_completion(self):
        self.run_actual('idle-system.m',IDLE,IDLE_END,range(9))


if __name__=='__main__':unittest.main()
