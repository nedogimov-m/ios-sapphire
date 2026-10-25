"""Keep native daemon identity and unrelated launch policy while adding services."""
import copy
import plistlib
import unittest
from ports.redfin import platform_userland as platform
from ports.redfin.wifi_userland import _encode_same_size


def fixture():
    jobs={}
    for label,(program,_) in platform.NATIVE_LOGS.items():
        jobs[label]=dict(Label=label,ProgramArguments=[program],UserName='mobile',
                        MachServices={label:True},KeepAlive={'Crashed':True})
    value={'LaunchDaemons':jobs,'Keep':{'RootVolume':'native'}}
    # The native cache can share containers with unrelated records.
    value['NativeReference']=jobs['com.apple.tccd']
    return value


class PlatformServicesTests(unittest.TestCase):
    def encode(self,value):return _encode_same_size(value,16384)[0]

    def test_exact_native_jobs_and_aliases_survive_the_scoped_logging_change(self):
        value=fixture();original=self.encode(value)
        after,report=platform.patch_launchd_cache(original);decoded=plistlib.loads(after)
        self.assertEqual(len(after),len(original));self.assertTrue(report['changed'])
        self.assertEqual(decoded['NativeReference'],value['NativeReference'])
        for name,record in platform.PROGRAMS.items():
            path='/System/Library/LaunchDaemons/'+record['label']+'.plist'
            self.assertEqual(decoded['LaunchDaemons'][path],platform.job(name))
        for label,(program,log) in platform.NATIVE_LOGS.items():
            j=decoded['LaunchDaemons'][label]
            self.assertEqual(j['ProgramArguments'],[program]);self.assertEqual(j['UserName'],'mobile')
            self.assertEqual(j['MachServices'],{label:True});self.assertEqual(j['KeepAlive'],{'Crashed':True})
            self.assertEqual(j['StandardOutPath'],log);self.assertEqual(j['StandardErrorPath'],log)
        again,report=platform.patch_launchd_cache(after)
        self.assertEqual(again,after);self.assertFalse(report['changed'])

    def test_conflicting_service_identity_output_or_probe_job_is_refused(self):
        changes=[('ProgramArguments',['/wrong/tccd']),('UserName','root'),
                 ('StandardOutPath','/unrelated/log'),('EnvironmentVariables',[])]
        for field,value in changes:
            v=fixture();v['LaunchDaemons']['com.apple.tccd'][field]=value
            with self.assertRaises(ValueError):platform.patch_launchd_cache(self.encode(v))
        v=fixture();j=platform.job('network-check');j['ProgramArguments']=['/wrong/probe']
        v['LaunchDaemons']['/System/Library/LaunchDaemons/'+j['Label']+'.plist']=j
        with self.assertRaises(ValueError):platform.patch_launchd_cache(self.encode(v))
        v=fixture();del v['LaunchDaemons']['com.apple.assetsd']
        with self.assertRaises(ValueError):platform.patch_launchd_cache(self.encode(v))


if __name__=='__main__':unittest.main()
