"""Build/provision unattended native app checks for explicit capture boots."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
from ports.redfin.graphics_abi import Cache,audit_bundle
from ports.redfin.wifi_userland import _encode_same_size
from ports.redfin.userland_files import prepare

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LABEL='com.redfin.gui-check'
PROGRAM='/redfin/bin/gui-check'
JOB_PATH='/System/Library/LaunchDaemons/'+LABEL+'.plist'
LOG_PATH='/private/var/mobile/Library/Logs/redfin-gui-check.log'
LIBRARY='/System/Library/Frameworks/CoreServices.framework/CoreServices'
METHODS={'+defaultWorkspace':'@16@0:8','-openApplicationWithBundleID:':'B24@0:8@16'}
ENTITLEMENTS={'application-identifier':LABEL,'platform-application':True,
    'com.apple.frontboard.launchapplications':True,'com.apple.springboard.launchapplications':True}


def job():
    return dict(Label=LABEL,ProgramArguments=[PROGRAM],RunAtLoad=True,KeepAlive=False,
        UserName='mobile',ProcessType='Background',StandardOutPath=LOG_PATH,StandardErrorPath=LOG_PATH)


def patch_launchd_cache(original):
    if not isinstance(original,bytes) or not original.startswith(b'bplist00') or not 40<=len(original)<=16*1024**2:
        raise ValueError('bounded native launchd cache required')
    value=plistlib.loads(original)
    jobs=value.get('LaunchDaemons') if isinstance(value,dict) else None
    if not isinstance(jobs,dict):raise ValueError('native LaunchDaemons required')
    found=[(k,v) for k,v in jobs.items() if isinstance(v,dict) and v.get('Label')==LABEL]
    if found and found!=[(JOB_PATH,job())]:raise ValueError('conflicting native GUI check job')
    if JOB_PATH in jobs and not found:raise ValueError('GUI check path occupied')
    expected=copy.deepcopy(value);expected['LaunchDaemons'][JOB_PATH]=job()
    if expected==value:return original,dict(changed=False)
    encoded,padding=_encode_same_size(expected,len(original),compact=True)
    proof=plistlib.loads(encoded);proof['LaunchDaemons'].pop(JOB_PATH)
    before=copy.deepcopy(value);before['LaunchDaemons'].pop(JOB_PATH,None)
    if proof!=before:raise ValueError('GUI job patch changed an unrelated job')
    return encoded,dict(changed=True,padding_bytes=padding)


def build(out,cache_path=None):
    out=Path(out).resolve()
    if (ROOT/'research').resolve() not in out.parents:raise ValueError('private research output required')
    out.mkdir(parents=True,exist_ok=False)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        image=cache.image(LIBRARY);methods=image.objc_methods('LSApplicationWorkspace')
        if any(k not in methods or methods[k]['types']!=v for k,v in METHODS.items()):
            raise ValueError('actual native LS ABI differs')
        uuid=image.uuid
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    executable=out/'gui-check'
    command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
        '-miphoneos-version-min=16.0','-O2','-fblocks','-Wall','-Wextra','-Werror',
        '-I',str(HERE),str(HERE/'gui-check.m'),'-framework','Foundation','-o',str(executable)]
    entitlement=out/'entitlements.plist';entitlement.write_bytes(plistlib.dumps(ENTITLEMENTS))
    with (out/'build.log').open('wb') as log:
        subprocess.run(command,check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--force','--sign','-','--timestamp=none','--identifier',LABEL,
            '--entitlements',str(entitlement),str(executable)],check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--verify','--strict',str(executable)],check=True,stdout=log,stderr=log)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        abi=audit_bundle(cache,[executable])
    if not abi['compatible']:raise ValueError('native app check imports unavailable on20H392')
    (out/'job.plist').write_bytes(plistlib.dumps(job(),fmt=plistlib.FMT_BINARY,sort_keys=False))
    (out/'log-initial').write_bytes(b'REDFIN opt-in native Phone/Photos app checks.\n')
    report=dict(success=True,uuid=uuid,methods=METHODS,abi=abi,capture_opt_in=True,
        sha256={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in ['gui-check','job.plist','log-initial']})
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n');return report


def prepare_root(root,metadata,bundle):
    bundle=Path(bundle);report=json.loads((bundle/'build.json').read_text())
    if not report.get('success') or not report.get('capture_opt_in') or not report.get('abi',{}).get('compatible'):
        raise ValueError('verified opt-in GUI checker required')
    prepare(root,metadata,[(bundle/name,target,uid,mode,report['sha256'][name],preserve)
        for name,target,uid,mode,preserve in [('gui-check',PROGRAM,0,0o755,False),
            ('job.plist',JOB_PATH,0,0o644,False),('log-initial',LOG_PATH,501,0o644,True)]])
    path=Path(root)/'System/Library/xpc/launchd.plist'
    if path.is_symlink() or Path(root).resolve() not in path.resolve().parents:
        raise ValueError('native launchd cache escapes root')
    before=path.read_bytes();after,patched=patch_launchd_cache(before)
    with path.open('r+b') as stream:
        if stream.write(after)!=len(after):raise OSError('short native GUI cache write')
        stream.flush();stream.seek(0)
        if stream.read()!=after:raise OSError('native GUI cache readback differs')
    return patched


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.out),indent=2))
