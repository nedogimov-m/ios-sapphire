"""Build native thermal propagation/network probes and scoped service logging."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from ports.redfin.graphics_abi import Cache,audit_bundle
from ports.redfin.wifi_userland import _encode_same_size
from ports.redfin.userland_files import prepare

MOBILE_WIFI='/System/Library/PrivateFrameworks/MobileWiFi.framework/MobileWiFi'
DIAGNOSTIC_LIBRARY='/redfin/lib/libredfin-diagnostic.dylib'
NETWORK_ENTITLEMENTS={'application-identifier':'com.apple.wifid','platform-application':True,
                      'com.apple.private.system-keychain':True}
PROGRAMS={'thermald':dict(label='com.redfin.thermald',source='thermald.c',uid=0),
          'network-check':dict(label='com.redfin.network-check',source='network-check.m',uid=0)}
NATIVE_LOGS={'com.apple.tccd':('/System/Library/PrivateFrameworks/TCC.framework/Support/tccd',
    '/private/var/mobile/Library/Logs/redfin-native-tcc.log'),
    'com.apple.assetsd':('/System/Library/Frameworks/AssetsLibrary.framework/Support/assetsd',
    '/private/var/mobile/Library/Logs/redfin-native-assetsd.log')}


def job(name):
    record=PROGRAMS[name]
    result=dict(Label=record['label'],ProgramArguments=['/redfin/bin/'+name],RunAtLoad=True,
        KeepAlive=False,ProcessType='Background',StandardOutPath='/private/var/log/redfin-'+name+'.log',
        StandardErrorPath='/private/var/log/redfin-'+name+'.log')
    if name=='thermald':result['KeepAlive']={'SuccessfulExit':False}
    else:result['EnvironmentVariables']={'OS_ACTIVITY_DT_MODE':'YES'}
    return result


def patch_launchd_cache(original):
    if not isinstance(original,bytes) or not original.startswith(b'bplist00') or not 40<=len(original)<=16*1024**2:
        raise ValueError('bounded native launchd cache required')
    before=plistlib.loads(original);after=copy.deepcopy(before);jobs=after.get('LaunchDaemons')
    if not isinstance(jobs,dict) or any(not isinstance(value,dict) for value in jobs.values()):
        raise ValueError('native LaunchDaemons dictionary absent')
    allowed=set()
    for name,record in PROGRAMS.items():
        path='/System/Library/LaunchDaemons/'+record['label']+'.plist';wanted=job(name)
        found=[(key,value) for key,value in jobs.items() if value.get('Label')==record['label']]
        if found and found!=[(path,wanted)]:raise ValueError('conflicting native platform job')
        if path in jobs and not found:raise ValueError('platform job path occupied')
        jobs[path]=wanted;allowed.add(path)
    for label,(program,log) in NATIVE_LOGS.items():
        found=[key for key,value in jobs.items() if value.get('Label')==label]
        if len(found)!=1:raise ValueError('one native service required: '+label)
        key=found[0];j=copy.deepcopy(jobs[key]);jobs[key]=j
        actual=j.get('Program',j.get('ProgramArguments',[None])[0])
        if actual!=program or j.get('UserName')!='mobile':raise ValueError('native service identity differs: '+label)
        if not isinstance(j.get('EnvironmentVariables',{}),dict):raise ValueError('native environment is not a dictionary')
        environment=j.setdefault('EnvironmentVariables',{})
        if environment.get('OS_ACTIVITY_DT_MODE','YES')!='YES':raise ValueError('native logging already configured differently')
        environment['OS_ACTIVITY_DT_MODE']='YES'
        for field in ['StandardOutPath','StandardErrorPath']:
            if j.get(field,log) not in (log,'/dev/console'):raise ValueError('native output already redirected')
            j[field]=log
        allowed.add(key)
    if after==before:return original,dict(changed=False,scope=sorted(allowed))
    encoded,padding=_encode_same_size(after,len(original),compact=True)
    decoded=plistlib.loads(encoded)
    for obj in [before,decoded]:
        for key in allowed:obj['LaunchDaemons'].pop(key,None)
    if decoded!=before:raise ValueError('unrelated native launchd policy changed')
    return encoded,dict(changed=True,padding_bytes=padding,scope=sorted(allowed))


def inventory(bundle):
    bundle=Path(bundle);v=json.loads((bundle/'build.json').read_text())
    if not v.get('success') or not v.get('abi',{}).get('compatible'):raise ValueError('complete native platform bundle required')
    files=[]
    for name,record in PROGRAMS.items():
        label=record['label'];files += [(name,'/redfin/bin/'+name,0,0o755),
            (label+'.plist','/System/Library/LaunchDaemons/'+label+'.plist',0,0o644),
            (name+'-log-initial','/private/var/log/redfin-'+name+'.log',0,0o600)]
    for label,(_,path) in NATIVE_LOGS.items():files.append((label+'-log-initial',path,501,0o600))
    files.append(('libredfin-diagnostic.dylib',DIAGNOSTIC_LIBRARY,0,0o644))
    return [(bundle/name,path,uid,mode,v['sha256'][name]) for name,path,uid,mode in files]


def build(out,cache_path=None):
    out=Path(out).resolve()
    if ROOT/'research' not in out.parents:raise ValueError('private research output required')
    out.mkdir(parents=True,exist_ok=False)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        image=cache.image(MOBILE_WIFI);exports,_=image.exports()
        if any(not exports.get(k) for k in ['_WiFiSecurityCopyPassword','_WiFiSecuritySetPassword']):
            raise ValueError('native MobileWiFi credential API absent')
        uuid=image.uuid
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    with (out/'build.log').open('wb') as log:
        for name,record in PROGRAMS.items():
            command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
                '-miphoneos-version-min=16.0','-O2','-Wall','-Wextra','-Werror','-I',str(HERE),
                str(HERE/record['source']),'-o',str(out/name)]
            if name=='network-check':command+=['-fobjc-arc','-fblocks','-framework','Foundation']
            subprocess.run(command,check=True,stdout=log,stderr=log)
            entitlements=out/(name+'.entitlements.plist')
            value=NETWORK_ENTITLEMENTS if name=='network-check' else {'application-identifier':record['label'],'platform-application':True}
            entitlements.write_bytes(plistlib.dumps(value))
            subprocess.run(['codesign','--force','--sign','-','--timestamp=none','--identifier',record['label'],
                '--entitlements',str(entitlements),str(out/name)],check=True,stdout=log,stderr=log)
            subprocess.run(['codesign','--verify','--strict',str(out/name)],check=True,stdout=log,stderr=log)
            (out/(record['label']+'.plist')).write_bytes(plistlib.dumps(job(name),fmt=plistlib.FMT_BINARY,sort_keys=False))
            (out/(name+'-log-initial')).write_text('REDFIN native '+name+'; boot-bound observations follow.\n')
        command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
            '-miphoneos-version-min=16.0','-O2','-Wall','-Wextra','-Werror','-fobjc-arc','-fblocks',
            '-I',str(HERE),'-dynamiclib','-install_name',DIAGNOSTIC_LIBRARY,
            str(HERE/'native-diagnostics.m'),'-framework','Foundation','-o',str(out/'libredfin-diagnostic.dylib')]
        subprocess.run(command,check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--force','--sign','-','--timestamp=none','--identifier','com.redfin.native-diagnostic',
            str(out/'libredfin-diagnostic.dylib')],check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--verify','--strict',str(out/'libredfin-diagnostic.dylib')],check=True,stdout=log,stderr=log)
    for label in NATIVE_LOGS:(out/(label+'-log-initial')).write_text('REDFIN scoped native '+label+' output.\n')
    with (Cache(cache_path) if cache_path else Cache()) as cache:abi=audit_bundle(cache,
        [out/name for name in PROGRAMS]+[out/'libredfin-diagnostic.dylib'])
    if not abi['compatible']:raise ValueError('native platform service imports unavailable on20H392')
    report=dict(success=True,abi=abi,mobile_wifi_uuid=uuid,synthetic_password_only=True,
                source_sha256={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest()
                    for n in ['thermald.c','network-check.m','native-diagnostics.m','native-tcc-observer.inc','graphics-exec-scope.h','gui-profile.h']},
                sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='build.json'})
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n');return report


def prepare_root(root,metadata,bundle):
    root=Path(root).resolve()
    prepare(root,metadata,[(source,target,uid,mode,digest,target.endswith('.log'))
        for source,target,uid,mode,digest in inventory(bundle)])
    path=root/'System/Library/xpc/launchd.plist'
    if path.is_symlink() or root.resolve() not in path.resolve().parents:raise ValueError('native launchd cache escapes root')
    before=path.read_bytes();after,proof=patch_launchd_cache(before)
    with path.open('r+b') as f:
        if f.write(after)!=len(after):raise OSError('short platform startup write')
        f.flush();f.seek(0)
        if f.read()!=after:raise OSError('platform startup readback differs')
    return proof


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.out),indent=2))
