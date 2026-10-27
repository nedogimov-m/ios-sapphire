"""Actual AIR sync/queued wait contract: native attestation, bounded original result."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class MetalNativeWaitTests(unittest.TestCase):
    def test_actual_native_attestation_sync_wait_budget_error_and_no_retry(self):
        baseline=ROOT/'research/redfin-metal-ubo-extent-v1/mesa-25.0.7/src/compiler/air/air_metal.c'
        if not baseline.is_file():self.skipTest('private reviewed Mesa source absent')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'src/compiler/air/air_metal.c'
            target.parent.mkdir(parents=True);target.write_bytes(baseline.read_bytes())
            applied=subprocess.run(['git','apply',str(HERE/'metal-native-waits.patch')],cwd=root,capture_output=True,text=True)
            self.assertEqual(applied.returncode,0,applied.stderr)
            sync=function(target.read_text(),'static int\nfinish_or_say_why(')
            for header in ('IOKit/IOKitLib.h','CoreFoundation/CoreFoundation.h','util/os_time.h'):
                path=root/header;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
            source=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#define GALLIUM_FREEDRENO 1
#define RWA_FENCE_TIMEOUT_NS UINT64_C(2000000000)
typedef unsigned io_service_t;
typedef const void *CFTypeRef;
#define CFSTR(s) (s)
#define kCFNumberSInt32Type 3
static unsigned matches,releases,property_releases;
static unsigned service_present=1,value_present=1,value_type=1,number_valid=1;
static int32_t version=1;
static const char *screen_name="FD620";
static const void *IOServiceMatching(const char *name){assert(!strcmp(name,"RedwoodGPU"));++matches;return name;}
static io_service_t IOServiceGetMatchingService(unsigned port,const void *m){assert(!port&&m);return service_present;}
static CFTypeRef IORegistryEntryCreateCFProperty(io_service_t s,const char *key,void *a,unsigned f){
 assert(s==1&&!a&&!f&&!strcmp(key,"RedfinColdOutputWaitABI"));return value_present?&version:NULL;
}
static unsigned CFGetTypeID(CFTypeRef value){assert(value);return value_type;}
static unsigned CFNumberGetTypeID(void){return 1;}
static bool CFNumberGetValue(CFTypeRef value,unsigned type,void *out){
 assert(value&&type==kCFNumberSInt32Type);*(int32_t *)out=version;return number_valid;
}
static void CFRelease(CFTypeRef v){assert(v);++property_releases;}
static void IOObjectRelease(io_service_t s){assert(s);++releases;}
struct pipe_fence_handle{unsigned dummy;};
struct pipe_screen{
 const char *(*get_name)(struct pipe_screen *);
 bool (*fence_finish)(struct pipe_screen *,void *,struct pipe_fence_handle *,uint64_t);
 void (*fence_reference)(struct pipe_screen *,struct pipe_fence_handle **,struct pipe_fence_handle *);
};
struct pipe_context{void (*flush)(struct pipe_context *,struct pipe_fence_handle **,unsigned);};
struct rwa_device{struct pipe_screen *screen;struct pipe_context *pipe;bool software,native_cold_wait,queued_failed;};
static uint64_t now=UINT64_C(1000000000),cost,last_budget;
static unsigned waits,refs,retired,flushes;
static int native_error,publication;
static bool make_fence=true;
static struct pipe_fence_handle fence;
static int64_t os_time_get_nano(void){return (int64_t)now;}
static const char *get_name(struct pipe_screen *s){assert(s);return screen_name;}
static bool finish(struct pipe_screen *s,void *ctx,struct pipe_fence_handle *f,uint64_t budget){
 assert(s&&!ctx&&f==&fence);++waits;last_budget=budget;
 now+=cost<budget?cost:budget;errno=native_error;
 return !native_error&&cost<=budget;
}
static void reference(struct pipe_screen *s,struct pipe_fence_handle **f,struct pipe_fence_handle *to){assert(s);++refs;*f=to;}
static void flush(struct pipe_context *p,struct pipe_fence_handle **f,unsigned flags){assert(p&&!flags);++flushes;*f=make_fence?&fence:NULL;}
static int rwa_redfin_fence_publish(struct rwa_device *d,struct pipe_fence_handle *f){assert(d&&f);return publication;}
static void rwa_redfin_ordering_completed(struct rwa_device *d){assert(d);++retired;}
static void say(char *out,size_t bytes,const char *format,...){va_list args;va_start(args,format);vsnprintf(out,bytes,format,args);va_end(args);}
#include "metal-native-waits.inc"
'''+sync+r'''
int main(void){
 struct pipe_screen screen={get_name,finish,reference};struct pipe_context pipe={flush};
 struct rwa_device d={.screen=&screen,.pipe=&pipe};
 rwa_redfin_native_wait_init(&d);assert(d.native_cold_wait&&matches==1&&releases==1&&property_releases==1);
 assert(rwa_redfin_internal_wait_budget(&d)==UINT64_C(12000000000));
 d.software=true;rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait&&matches==1);
 d.native_cold_wait=true;assert(rwa_redfin_internal_wait_budget(&d)==RWA_FENCE_TIMEOUT_NS);
 d.software=false;screen_name="FD635";rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait&&matches==1);
 screen_name="FD620";service_present=0;rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait&&releases==1);
 service_present=1;value_present=0;rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait&&releases==2&&property_releases==1);
 value_present=1;value_type=2;rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait);
 value_type=1;number_valid=0;rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait);
 number_valid=1;version=2;rwa_redfin_native_wait_init(&d);assert(!d.native_cold_wait);
 version=1;rwa_redfin_native_wait_init(&d);assert(d.native_cold_wait);
 struct redfin_metal_wait_result result={0};
 cost=UINT64_C(4951143000);errno=EDOM;
 assert(rwa_redfin_fence_wait(&d,&fence,"queued",&result));
 assert(result.attempted&&result.budget_ns==UINT64_C(12000000000)&&result.elapsed_ns==cost&&!result.error&&errno==EDOM&&waits==1);
 d.native_cold_wait=false;cost=UINT64_C(4951143000);native_error=ETIMEDOUT;
 assert(!rwa_redfin_fence_wait(&d,&fence,"queued",&result));
 assert(result.budget_ns==RWA_FENCE_TIMEOUT_NS&&result.elapsed_ns==RWA_FENCE_TIMEOUT_NS&&result.error==ETIMEDOUT&&errno==ETIMEDOUT&&waits==2);
 // A generic false result without errno must stay unknown, never invented.
 native_error=0;assert(!rwa_redfin_fence_wait(&d,&fence,"queued",&result)&&!result.error&&waits==3);
 char why[512]={0};d.native_cold_wait=true;cost=UINT64_C(4951143000);
 assert(!finish_or_say_why(&d,true,"test",why,sizeof(why))&&retired==1&&refs==1&&waits==4);
 assert(last_budget==UINT64_C(12000000000)&&!d.queued_failed);
 native_error=EIO;cost=UINT64_C(123456789);
 assert(finish_or_say_why(&d,true,"test",why,sizeof(why))<0&&d.queued_failed&&retired==1&&refs==2&&waits==5);
 assert(strstr(why,"elapsed-ns=123456789")&&strstr(why,"native context is retired"));
 // Publication failure never invents an actual wait, GPU success or retirement.
 publication=-1;d.queued_failed=false;unsigned before=waits;
 assert(finish_or_say_why(&d,true,"test",why,sizeof(why))<0&&waits==before&&d.queued_failed&&retired==1);
 assert(strstr(why,"publication=-1 waited=0"));
 publication=1;assert(!finish_or_say_why(&d,false,"empty",why,sizeof(why))&&waits==before&&retired==1);
 make_fence=false;assert(!finish_or_say_why(&d,false,"empty",why,sizeof(why))&&waits==before);
 assert(finish_or_say_why(&d,true,"missing",why,sizeof(why))<0&&waits==before);
 // Observe many results, still at most eight slow successes and one failure.
 cost=UINT64_C(60000000);native_error=0;
 for(unsigned i=0;i<30;++i)assert(rwa_redfin_fence_wait(&d,&fence,"queued",&result));
 native_error=EIO;
 for(unsigned i=0;i<30;++i)assert(!rwa_redfin_fence_wait(&d,&fence,"queued",&result));
 return 0;
}
'''
            path=root/'wait.c';path.write_text(source);exe=root/'wait'
            built=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(root),'-I'+str(HERE),str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)
            records=[s for s in ran.stderr.splitlines() if s.startswith('REDFIN METAL WAIT:')]
            self.assertEqual(len(records),9)
            self.assertEqual(sum('done=0' in line for line in records),1)
            self.assertTrue(any('elapsed-ns=4951143000' in line and 'cold-abi=1' in line for line in records))


if __name__=='__main__':unittest.main()
