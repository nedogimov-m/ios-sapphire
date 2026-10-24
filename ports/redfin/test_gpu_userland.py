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


if __name__=='__main__':unittest.main()
