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
