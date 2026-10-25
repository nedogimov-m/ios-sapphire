"""Native compiler-context serialization and isolated/system Metal admission."""
import copy
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest

from ports.redfin import gpu_command,metal_userland,mkadt
from ports.redfin.wifi_userland import _encode_same_size


class MetalPlatformTests(unittest.TestCase):
    def test_completion_profile_uses_native_timebase_and_separates_queue_gate_encoding_and_finish(self):
        source=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <stdarg.h>
#include <mach/mach_time.h>
static char logged[1024];static unsigned logs;
static int profile_timebase(mach_timebase_info_t info){info->numer=125;info->denom=6;return 0;}
static int profile_sysctl(const char *name,void *out,size_t *bytes,void *newp,size_t newlen){
 (void)name;(void)newp;(void)newlen;const char args[]="redfinbootid=0x0123456789abcdef";
 assert(*bytes>=sizeof(args));memcpy(out,args,sizeof(args));*bytes=sizeof(args);return 0;
}
static void rw_print(const char *format,...){
 ++logs;va_list args;va_start(args,format);vsnprintf(logged,sizeof(logged),format,args);va_end(args);
}
#define mach_timebase_info profile_timebase
#define sysctlbyname profile_sysctl
'''+metal_userland.FENCE_OBSERVATIONS+r'''
int main(void){
 redfin_metal_completed(0,0,0,480,960,1440,1920);assert(!logs);
 redfin_metal_completed(3,0,0,480,960,1440,1920);assert(logs==1);
 assert(strstr(logged,"boot=0123456789abcdef")&&strstr(logged,"actual-finish=1"));
 assert(strstr(logged,"queue-us=10 gate-us=10 encode-us=10 final-fence-us=10 total-us=40"));
 uint64_t before[4]={0},after[4]={3,9000,2,3000};
 redfin_metal_io_completed(before,after);assert(logs==2);
 assert(strstr(logged,"submit-calls=3 submit-io-us=9 allocation-calls=2 allocation-io-us=3"));
 redfin_metal_io_completed(after,before);assert(logs==2);
 assert(!redfin_phase_us(2,1));redfin_fence_timebase.denom=0;assert(!redfin_phase_us(0,480));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'profile.c').write_text(source)
            compiled=subprocess.run(['cc','-std=c11','-O2','-pthread','-Wall','-Wextra','-Werror',
                                    str(p/'profile.c'),'-o',str(p/'profile')],capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            subprocess.run([str(p/'profile')],check=True,timeout=10,capture_output=True)

    def test_real_dispatch_worker_returns_before_gpu_wait_and_preserves_queue_order(self):
        # Use the actual native GCD executor. Two admitted commands retain
        # order, a third applies backpressure, and concurrent waiters cover
        # admission as well as execution. No fake fence can free a slot.
        source=r'''
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#include <dispatch/dispatch.h>
'''+metal_userland.EXECUTION+r'''
int main(void) {
 dispatch_group_t first=dispatch_group_create(),second=dispatch_group_create(),third=dispatch_group_create();
 dispatch_semaphore_t started=dispatch_semaphore_create(0),release=dispatch_semaphore_create(0);
 dispatch_semaphore_t submitted=dispatch_semaphore_create(0);
 __block unsigned output=0;
 dispatch_group_enter(first);
 redfin_metal_schedule(first,^{
  dispatch_semaphore_signal(started);
  assert(!dispatch_semaphore_wait(release,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
  output=41;
 });
 assert(!dispatch_semaphore_wait(started,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 assert(dispatch_group_wait(first,DISPATCH_TIME_NOW)!=0 && !output);
 dispatch_group_enter(second);
 redfin_metal_schedule(second,^{assert(output==41);++output;});
 assert(dispatch_group_wait(second,DISPATCH_TIME_NOW)!=0);
 dispatch_group_enter(third);
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE,0),^{
  redfin_metal_schedule(third,^{assert(output==42);++output;});
  dispatch_semaphore_signal(submitted);
 });
 assert(dispatch_semaphore_wait(submitted,dispatch_time(DISPATCH_TIME_NOW,50*NSEC_PER_MSEC))!=0);
 assert(dispatch_group_wait(third,DISPATCH_TIME_NOW)!=0 && !output);
 dispatch_semaphore_signal(release);
 assert(!dispatch_semaphore_wait(submitted,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 assert(!dispatch_group_wait(third,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 assert(!dispatch_group_wait(second,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 assert(!dispatch_group_wait(first,DISPATCH_TIME_NOW) && output==43);
 for(unsigned i=0;i<200;++i) {
  dispatch_group_enter(first);redfin_metal_schedule(first,^{});
  assert(!dispatch_group_wait(first,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 }
 dispatch_release(first);dispatch_release(second);dispatch_release(third);
 dispatch_release(started);dispatch_release(release);dispatch_release(submitted);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'execution.m').write_text(source)
            compiled=subprocess.run(['cc','-std=gnu11','-fblocks','-O2','-pthread','-Wall','-Wextra','-Werror',
                str(p/'execution.m'),'-framework','Foundation','-o',str(p/'execution')],capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            subprocess.run([str(p/'execution')],timeout=15,check=True,capture_output=True)

    def test_command_scope_fences_dependencies_and_failures_before_reuse(self):
        # Exercise the actual adapter with writes that become visible only at a
        # successful fence. Raster commands share a final fence; a following
        # compute/CPU-validation boundary must first make their writes visible.
        source=r'''
#include <assert.h>
#include "metal-command-scope.h"
struct fake_gpu { unsigned pending,visible,waits; int error; };
static int finish(void *context,char *why,size_t bytes) {
 struct fake_gpu *g=context;(void)why;(void)bytes;++g->waits;
 if(g->error)return g->error;
 g->visible+=g->pending;g->pending=0;return 0;
}
int main(void) {
 struct redfin_metal_command_scope s={0};struct fake_gpu g={0};
 assert(!redfin_metal_scope_begin(&s));
 assert(redfin_metal_scope_begin(&s)); /* nested scopes cannot steal a queue */
 for(unsigned n=0;n<96;++n) {
  assert(!redfin_metal_scope_prepare(&s,true,finish,&g,0,0));
  ++g.pending;
  assert(!redfin_metal_scope_complete(&s,true,finish,&g,0,0));
 }
 assert(!g.waits && !g.visible);
 assert(!redfin_metal_scope_end(&s,finish,&g,0,0));
 assert(g.waits==1 && g.visible==96 && !g.pending);
 assert(!redfin_metal_scope_begin(&s));
 ++g.pending;assert(!redfin_metal_scope_complete(&s,true,finish,&g,0,0));
 assert(!redfin_metal_scope_prepare(&s,false,finish,&g,0,0));
 assert(g.visible==97 && g.waits==2);
 ++g.pending;assert(!redfin_metal_scope_complete(&s,false,finish,&g,0,0));
 assert(g.visible==98 && g.waits==3);
 assert(!redfin_metal_scope_end(&s,finish,&g,0,0));
 /* Non-Metal callers retain immediate completion. */
 ++g.pending;assert(!redfin_metal_scope_complete(&s,true,finish,&g,0,0));
 assert(g.visible==99 && g.waits==4);
 /* A partially encoded command still drains on scope exit. Failed GPU
  * completion retires the context instead of allowing another submit. */
 assert(!redfin_metal_scope_begin(&s));
 ++g.pending;assert(!redfin_metal_scope_complete(&s,true,finish,&g,0,0));
 g.error=-7;
 assert(redfin_metal_scope_end(&s,finish,&g,0,0)==-7);
 assert(g.visible==99 && g.pending==1 && g.waits==5 && !s.active);
 assert(redfin_metal_scope_begin(&s));
 assert(redfin_metal_scope_prepare(&s,true,finish,&g,0,0));
 assert(redfin_metal_scope_complete(&s,true,finish,&g,0,0));
 assert(g.waits==5);return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'scope.c').write_text(source)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(Path(__file__).parent),str(p/'scope.c'),'-o',str(p/'scope')],
                capture_output=True,check=True)
            subprocess.run([str(p/'scope')],timeout=10,check=True,capture_output=True)

    def test_policy_requires_the_complete_runtime_and_has_distinct_probe_system_modes(self):
        for mode,wanted in [('probe',1),('system',2)]:
            tree=mkadt.node('device-tree',[],[mkadt.node('redfin-gpu-command',
                [('runtime-policy',mkadt.u32(*gpu_command.RUNTIME_POLICY))])])
            gpu_command.add_metal_contract(tree,mode)
            self.assertEqual(tree.children[0].prop('metal-policy'),mkadt.u32(*gpu_command.METAL_POLICY,wanted))
            with self.assertRaises(ValueError):gpu_command.add_metal_contract(tree,mode)
        for mode in ['probe','system','unknown']:
            with self.assertRaises(ValueError):gpu_command.add_metal_contract(mkadt.node('device-tree'),mode)

    def test_native_job_patch_preserves_other_policy_and_rejects_conflicting_identity(self):
        value={'LaunchDaemons':{'stock':{'Label':'stock','MachServices':{'service':True}}},'Keep':b'preserved'}
        original=_encode_same_size(value,8192)[0]
        encoded,report=metal_userland.patch_launchd_cache(original)
        self.assertTrue(report['changed']);self.assertEqual(len(encoded),len(original))
        decoded=plistlib.loads(encoded)
        self.assertEqual(decoded['LaunchDaemons'].pop(metal_userland.JOB_PATH),metal_userland.job())
        self.assertEqual(decoded,value)
        self.assertEqual(metal_userland.patch_launchd_cache(encoded)[0],encoded)
        for key,job in [('wrong',dict(metal_userland.job(),ProgramArguments=['/different'])),
                        (metal_userland.JOB_PATH,{'Label':'different'})]:
            bad=copy.deepcopy(value);bad['LaunchDaemons'][key]=job
            with self.assertRaises(ValueError):metal_userland.patch_launchd_cache(_encode_same_size(bad,8192)[0])

    def test_shared_gallium_gate_serializes_queues_and_releases_void_nested_and_error_calls(self):
        # Compile the gate actually inserted into the driver. Each native queue
        # races an intentionally unthreaded context; even a void destroy, a
        # nested dispatch and an early refusal must leave its mutex balanced.
        source=r'''
#include <pthread.h>
#include <stdlib.h>
#include <sched.h>
#include <assert.h>
static unsigned active,violations;
static unsigned work(unsigned);
static void destroy(void);
static struct {unsigned (*work)(unsigned);void (*destroy)(void);} mesa={work,destroy};
'''+metal_userland.LOCKING+r'''
static unsigned work(unsigned n){
 if(__atomic_add_fetch(&active,1,__ATOMIC_RELAXED)!=1)__atomic_add_fetch(&violations,1,__ATOMIC_RELAXED);
 sched_yield();__atomic_sub_fetch(&active,1,__ATOMIC_RELAXED);return n+1;
}
static void destroy(void){assert(!active);}
static unsigned refuse(void){REDFIN_MESA_SCOPE;return RF_MESA(work,3);}
static void *queue(void *ignored){
 (void)ignored;
 for(unsigned i=0;i<2000;i++){assert(RF_MESA(work,i)==i+1);RF_MESA(destroy);assert(refuse()==4);}
 return NULL;
}
int main(void){
 pthread_t threads[4];
 for(unsigned i=0;i<4;i++)assert(!pthread_create(&threads[i],NULL,queue,NULL));
 for(unsigned i=0;i<4;i++)assert(!pthread_join(threads[i],NULL));
 assert(!active && !violations);return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'gate.c').write_text(source)
            subprocess.run(['cc','-std=gnu11','-O2','-pthread','-Wall','-Wextra','-Werror',
                str(p/'gate.c'),'-o',str(p/'gate')],capture_output=True,check=True)
            subprocess.run([str(p/'gate')],timeout=20,check=True,capture_output=True)


if __name__=='__main__':unittest.main()
