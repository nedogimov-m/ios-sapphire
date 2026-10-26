"""Actual Metal admission preserves app devices while the render server uses GLES."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from ports.redfin.compositor_evidence import analyze
from ports.redfin import metal_userland

HERE=Path(__file__).resolve().parent


class CompositorPolicyTests(unittest.TestCase):
    def test_actual_preinit_metal_decline_disposes_without_entering_private_superclass_dealloc(self):
        upstream=HERE.parents[1]/'research/hackios-upstream/userland/userland/src/redwoodmetal.m'
        if not upstream.is_file():self.skipTest('pinned preferred Metal source unavailable')
        adapted=metal_userland.adapt_driver(upstream.read_text())
        first=adapted.index('- (instancetype)initWithAcceleratorPort:(io_service_t)port\n{')
        last=adapted.index('\t_acceleratorService = port;',first)
        prefix=adapted[first:last]+'\t(void)port;return self;\n}\n'
        source=r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <assert.h>
typedef unsigned io_service_t;
static BOOL abi,hardware;
static unsigned initialized,deallocated,disposed,hardware_queries;
static int redfin_metal_abi_ready(void){return abi;}
static int redfin_metal_hardware_ready(void){++hardware_queries;return hardware;}
static void ensure_spi(Class cls){assert(cls);}
static void redfin_install_function_constants(void){}
static id record_dispose(id object){++disposed;return object_dispose(object);}
#define object_dispose record_dispose
@interface NativeMetalBase:NSObject {BOOL ready;}
@end
@implementation NativeMetalBase
- (instancetype)init {self=[super init];if(self){ready=YES;++initialized;}return self;}
- (void)dealloc {assert(ready);++deallocated;[super dealloc];}
@end
@interface RedwoodMetalDevice:NativeMetalBase
- (instancetype)initWithAcceleratorPort:(io_service_t)port;
@end
@implementation RedwoodMetalDevice
'''+prefix+r'''
@end
int main(void){@autoreleasepool {
 for(unsigned a=0;a<2;++a)for(unsigned h=0;h<2;++h){
  abi=a;hardware=h;initialized=deallocated=disposed=hardware_queries=0;
  id object=[[RedwoodMetalDevice alloc] initWithAcceleratorPort:0];
  BOOL accepted=abi&&hardware;
  assert((object!=nil)==accepted);
  assert(initialized==accepted&&disposed==!accepted&&hardware_queries==abi);
  if(object)[object release];
  assert(deallocated==accepted);
 }
}return 0;}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-metal-decline-') as directory:
            folder=Path(directory);path=folder/'decline.m';path.write_text(source)
            built=subprocess.run(['cc','-O2','-fno-objc-arc','-Wall','-Wextra','-Werror',
                str(path),'-framework','Foundation','-o',str(folder/'decline')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            run=subprocess.run([str(folder/'decline')],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_backend_evidence_requires_actual_hardware_frames_and_rejects_mixed_or_stale_activity(self):
        boot='0123456789abcdef'
        policy=f'REDFIN COMPOSITOR: boot={boot} process=backboardd requested=gles'
        hardware=f'REDFIN EAGL ABI: boot={boot} UUID=actual GLES=3.2 renderer=FD620'
        frame=f'REDFIN EAGL FRAME: boot={boot} pid=61 frame=120 draws=380 triangles=450 shared=2 copied=0 errors=0'
        self.assertFalse(analyze([policy,hardware],boot)['actual_GLES_composition'])
        self.assertTrue(analyze([policy,hardware,frame],boot)['actual_GLES_composition'])
        for bad in (frame.replace('errors=0','errors=1'),frame.replace(boot,'fedcba9876543210')):
            self.assertFalse(analyze([policy,hardware,bad],boot)['actual_GLES_composition'])
        self.assertFalse(analyze([policy,hardware.replace('FD620','llvmpipe'),frame],boot)['actual_GLES_composition'])
        metal=f'redwoodmetal[backboardd 61]: REDFIN METAL FENCE: boot={boot} sequence=1 actual-finish=1'
        self.assertFalse(analyze([policy,hardware,frame,metal],boot)['actual_GLES_composition'])
        app=metal.replace('backboardd','metal-check')
        result=analyze([policy,hardware,frame,app],boot)
        self.assertTrue(result['actual_GLES_composition'])
        self.assertFalse(result['app_Metal_proved_by_this_log'])

    def test_real_metal_hardware_entry_declines_only_the_requested_compositor(self):
        body=function((HERE/'metal-guard.m').read_text(),'int redfin_metal_hardware_ready(')
        source=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "compositor-policy.h"
typedef unsigned io_service_t;
#define CFSTR(x) (x)
static const char *program,*setting;static unsigned queries,releases;static bool present;
static const char *program_name(void){return program;}
static const char *environment(const char *key){assert(!strcmp(key,REDFIN_COMPOSITOR_ENV));return setting;}
static const char *IOServiceMatching(const char *name){assert(!strcmp(name,"RedwoodGPU"));return name;}
static io_service_t IOServiceGetMatchingService(unsigned port,const char *name)
{assert(!port&&name);++queries;return present?17:0;}
static void IOObjectRelease(io_service_t service){assert(service==17);++releases;}
static int number(io_service_t service,const char *key,int wanted)
{
 assert(service==17);
 if(!strcmp(key,"chip-id"))return wanted==0x06020001;
 if(!strcmp(key,"RedfinRuntimeABI")||!strcmp(key,"RedfinQueuedSubmissionABI"))return wanted==1;
 assert(!strcmp(key,"RedfinMetalPolicy"));return wanted==2;
}
static int policy_sysctl(const char *name,void *out,size_t *bytes,void *newp,size_t newlen)
{(void)name;(void)out;(void)bytes;(void)newp;(void)newlen;return -1;}
static bool redfin_gpu_gui_profile(const char *args,unsigned bytes,uint64_t *nonce)
{(void)args;(void)bytes;(void)nonce;return false;}
#define getprogname program_name
#define getenv environment
#define sysctlbyname policy_sysctl
'''+body+r'''
int main(void)
{
 const char *names[]={"backboardd","metal-check","Photos","Phone","SpringBoard","backboardd-helper",NULL};
 const char *choices[]={NULL,"metal","gles","","software"};
 for(unsigned n=0;n<sizeof(names)/sizeof(names[0]);++n)
  for(unsigned s=0;s<sizeof(choices)/sizeof(choices[0]);++s)
   for(unsigned hardware=0;hardware<2;++hardware){
    program=names[n];setting=choices[s];present=hardware;queries=releases=0;
    bool declined=n==0&&s>=2;
    assert(redfin_metal_hardware_ready()==(hardware&&!declined));
    assert(queries==(declined?0:1)&&releases==(hardware&&!declined));
   }
 assert(redfin_compositor_setting_valid(NULL)&&redfin_compositor_setting_valid("gles")&&redfin_compositor_setting_valid("metal"));
 assert(!redfin_compositor_setting_valid("")&&!redfin_compositor_setting_valid("software"));
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-compositor-') as directory:
            folder=Path(directory);path=folder/'guard.c';path.write_text(source)
            build=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(path),'-o',str(folder/'guard')],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(folder/'guard')],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
