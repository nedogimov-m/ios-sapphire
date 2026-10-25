"""GPU startup cache edits preserve every unrelated system job and allocation."""
import copy
import plistlib
import unittest
from ports.redfin import gpu_userland,wifi_userland


class GPUUserlandTests(unittest.TestCase):
    def original(self):
        jobs={f'/System/job-{i}.plist':{'Label':f'com.apple.job{i}','KeepAlive':True,
            'ProgramArguments':['/usr/bin/program'],'EnvironmentVariables':{'same':'value'}} for i in range(100)}
        obj={'LaunchDaemons':jobs,'Unrelated':{'data':b'a'*1024}}
        encoded=plistlib.dumps(obj,fmt=plistlib.FMT_BINARY,sort_keys=False)
        return wifi_userland._encode_same_size(obj,len(encoded)+8192)[0]

    def test_only_new_gpu_job_changes_and_allocation_length_is_fixed(self):
        original=self.original();changed,report=gpu_userland.patch_launchd_cache(original)
        self.assertEqual(len(changed),len(original));self.assertTrue(report['changed'])
        before=plistlib.loads(original);after=plistlib.loads(changed)
        job=after['LaunchDaemons'].pop(gpu_userland.JOB_PATH)
        self.assertEqual(before,after)
        self.assertEqual(job['ProgramArguments'],['/redfin/bin/gpu-render'])
        self.assertFalse(job['KeepAlive']);self.assertTrue(job['RunAtLoad'])
        self.assertEqual(gpu_userland.patch_launchd_cache(changed)[0],changed)
        self.assertFalse(gpu_userland.patch_launchd_cache(changed)[1]['changed'])

    def test_conflicting_job_or_label_and_invalid_cache_are_refused(self):
        raw=self.original();original=plistlib.loads(raw)
        variants=[]
        for job in ({'Label':gpu_userland.LABEL,'Program':'/other'}, {'Label':'com.other.job'}):
            obj=copy.deepcopy(original);obj['LaunchDaemons'][gpu_userland.JOB_PATH]=job;variants.append(plistlib.dumps(obj,fmt=plistlib.FMT_BINARY))
        variants.extend((b'bad',plistlib.dumps({'LaunchDaemons':[]},fmt=plistlib.FMT_BINARY)))
        for value in variants:
            with self.assertRaises(ValueError):gpu_userland.patch_launchd_cache(value)

    def backboard(self):
        return {'Label':'com.apple.backboardd','ProgramArguments':['/usr/libexec/backboardd'],
            'RunAtLoad':True,'KeepAlive':True,'UserName':'mobile','POSIXSpawnType':'Interactive',
            'MachServices':{'com.apple.CARenderServer':{'ResetAtClose':True},'PurpleSystemEventPort':True},
            'EnvironmentVariables':{'EXISTING_OPTION':'retained'},'HighPriorityIO':True}

    def test_legacy_job_migration_and_system_bridge_preserve_all_other_jobs(self):
        raw=self.original();before=plistlib.loads(raw)
        job=plistlib.loads(gpu_userland.Path(gpu_userland.__file__).with_name('gpu-render-job.plist').read_bytes())
        before['LaunchDaemons'][gpu_userland.OLD_JOB_PATH]=job
        before['LaunchDaemons'][gpu_userland.BACKBOARD_PATH]=self.backboard()
        original=wifi_userland._encode_same_size(before,len(raw))[0]
        patched,report=gpu_userland.patch_launchd_cache(original,system_eagl=True)
        after=plistlib.loads(patched)
        self.assertEqual(len(patched),len(original))
        self.assertEqual(report['migrated_from'],gpu_userland.OLD_JOB_PATH)
        self.assertNotIn(gpu_userland.OLD_JOB_PATH,after['LaunchDaemons'])
        self.assertEqual(after['LaunchDaemons'].pop(gpu_userland.JOB_PATH),job)
        backboard=after['LaunchDaemons'].pop(gpu_userland.BACKBOARD_PATH)
        self.assertEqual(backboard['EnvironmentVariables'],{'EXISTING_OPTION':'retained'})
        for key in ('StandardOutPath','StandardErrorPath'):self.assertEqual(backboard.pop(key),gpu_userland.EAGL_LOG)
        self.assertEqual(backboard.pop('JetsamProperties'),{'ActiveHardMemoryLimit':512,'InactiveHardMemoryLimit':512})
        self.assertEqual(backboard,self.backboard())
        before['LaunchDaemons'].pop(gpu_userland.OLD_JOB_PATH)
        before['LaunchDaemons'].pop(gpu_userland.BACKBOARD_PATH)
        self.assertEqual(after,before)
        self.assertEqual(gpu_userland.patch_launchd_cache(patched,system_eagl=True)[0],patched)

    def test_backboard_identity_or_existing_foreign_insertion_is_refused(self):
        original=self.backboard()
        for field,value in (('ProgramArguments',['/another/program']),('UserName','root'),
            ('MachServices',{}),('KeepAlive',False),
            ('EnvironmentVariables',{'DYLD_INSERT_LIBRARIES':'/unrelated/library.dylib'})):
            job=copy.deepcopy(original);job[field]=value
            with self.assertRaises(ValueError):gpu_userland.backboardd_job(job)
        with self.assertRaises(ValueError):gpu_userland.patch_launchd_cache(self.original(),system_eagl=True)

    def test_known_old_insertion_and_diagnostic_policy_are_migrated_together(self):
        before=plistlib.loads(self.original());b=self.backboard()
        b['EnvironmentVariables']['DYLD_INSERT_LIBRARIES']=gpu_userland.LOADER
        b['StandardOutPath']=b['StandardErrorPath']='/dev/console'
        before['LaunchDaemons'][gpu_userland.BACKBOARD_PATH]=b
        before['LaunchDaemons'][gpu_userland.JOB_PATH]=copy.deepcopy(gpu_userland.LEGACY_JOB)
        raw=wifi_userland._encode_same_size(before,len(self.original()))[0]
        changed,report=gpu_userland.patch_launchd_cache(raw,system_eagl=True)
        jobs=plistlib.loads(changed)['LaunchDaemons']
        self.assertNotIn('DYLD_INSERT_LIBRARIES',jobs[gpu_userland.BACKBOARD_PATH]['EnvironmentVariables'])
        self.assertEqual(jobs[gpu_userland.JOB_PATH]['JetsamProperties'],
            {'ActiveHardMemoryLimit':512,'InactiveHardMemoryLimit':512})
        self.assertEqual(jobs[gpu_userland.JOB_PATH]['StandardOutPath'],gpu_userland.GPU_LOG)

    def test_runtime_policy_retires_probe_and_capture_without_disabling_window_server(self):
        before=plistlib.loads(self.original())
        before['LaunchDaemons'][gpu_userland.BACKBOARD_PATH]=self.backboard()
        original=wifi_userland._encode_same_size(before,len(self.original()))[0]
        captured,_=gpu_userland.patch_launchd_cache(original,system_eagl=True,draw_capture=True)
        ordinary,report=gpu_userland.patch_launchd_cache(captured,system_eagl=True,
            draw_capture=False,startup_checks=False)
        after=plistlib.loads(ordinary);probe=after['LaunchDaemons'].pop(gpu_userland.JOB_PATH)
        self.assertTrue(probe['Disabled']);self.assertFalse(probe['RunAtLoad']);self.assertFalse(probe['KeepAlive'])
        event=after['LaunchDaemons'][gpu_userland.BACKBOARD_PATH]
        self.assertTrue(event['RunAtLoad']);self.assertTrue(event['KeepAlive']);self.assertNotIn('Disabled',event)
        self.assertEqual(event['MachServices'],self.backboard()['MachServices'])
        self.assertNotIn('REDFIN_METAL_DRAW_CAPTURE',event['EnvironmentVariables'])
        self.assertEqual(len(ordinary),len(original));self.assertFalse(report['startup_checks'])
        self.assertEqual(gpu_userland.patch_launchd_cache(ordinary,system_eagl=True,startup_checks=False)[0],ordinary)
        # Re-enabling the exact reviewed diagnostic profile is reversible.
        restored,_=gpu_userland.patch_launchd_cache(ordinary,system_eagl=True,draw_capture=True)
        self.assertEqual(plistlib.loads(restored),plistlib.loads(captured))
        after['LaunchDaemons'].pop(gpu_userland.BACKBOARD_PATH)
        before['LaunchDaemons'].pop(gpu_userland.BACKBOARD_PATH)
        self.assertEqual(after,before)

    def test_startup_probe_policy_is_explicit_and_foreign_disabled_jobs_are_refused(self):
        for invalid in ('off',0,None):
            with self.assertRaises(ValueError):gpu_userland.job(invalid)
        value=plistlib.loads(self.original());bad=gpu_userland.job(False)
        bad['ProgramArguments']=['/another/program'];value['LaunchDaemons'][gpu_userland.JOB_PATH]=bad
        with self.assertRaises(ValueError):
            gpu_userland.patch_launchd_cache(wifi_userland._encode_same_size(value,len(self.original()))[0],startup_checks=False)


if __name__=='__main__':unittest.main()
