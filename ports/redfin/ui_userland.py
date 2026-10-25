"""Build the actual-ABI full-panel/camera status-bar adapter; no device I/O."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from ports.redfin.userland_files import prepare

from ports.redfin.graphics_abi import Cache, audit_bundle

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LIBRARY='/redfin/lib/libredfin-ui.dylib'
REFRESH_LIBRARY='/redfin/lib/libredfin-refresh.dylib'
REFRESH_LOG='/private/var/mobile/Library/Logs/redfin-refresh.log'
LOG='/private/var/mobile/Library/Logs/redfin-ui.log'
UIKIT='/System/Library/PrivateFrameworks/UIKitCore.framework/UIKitCore'
METHODS={
    '_UIStatusBar': {'-layoutSubviews':'v16@0:8',
        '-setAvoidanceFrame:':'v48@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16',
        '-avoidanceFrame':'{CGRect={CGPoint=dd}{CGSize=dd}}16@0:8',
        '-itemWithIdentifier:':'@24@0:8@16'},
    '_UIStatusBarItem': {'+identifier':'@16@0:8'},
    '_UIStatusBarTimeItem': {'+timeDisplayIdentifier':'@16@0:8',
        '+shortTimeDisplayIdentifier':'@16@0:8', '+pillTimeDisplayIdentifier':'@16@0:8',
        '-viewForIdentifier:':'@24@0:8@16'},
}
REFRESH_METHODS={'UIScreen':{'-maximumFramesPerSecond':'q16@0:8',
    '-_maximumFramesPerSecond':'q16@0:8','-_refreshRate':'d16@0:8','-_isMainScreen':'B16@0:8'},
    'CADisplay':{'+mainDisplay':'@16@0:8','-refreshRate':'d16@0:8','-hardwareRefreshRate':'d16@0:8'}}


def build(out,cache_path=None):
    out=Path(out).resolve()
    if (ROOT/'research').resolve() not in out.parents:
        raise ValueError('native libraries must stay under ignored research')
    out.mkdir(parents=True,exist_ok=False)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        image=cache.image(UIKIT)
        for name,wanted in METHODS.items():
            methods=image.objc_methods(name)
            if any(key not in methods or methods[key]['types']!=types for key,types in wanted.items()):
                raise ValueError('native status-bar ABI differs: '+name)
        uuid=image.uuid
        quartz=cache.image('/System/Library/Frameworks/QuartzCore.framework/QuartzCore')
        for name,wanted in REFRESH_METHODS.items():
            actual=(image if name=='UIScreen' else quartz).objc_methods(name)
            if any(key not in actual or actual[key]['types']!=types for key,types in wanted.items()):
                raise ValueError('native display-period ABI differs: '+name)
        quartz_uuid=quartz.uuid
    define=','.join('0x'+uuid[i:i+2] for i in range(0,32,2))
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    library=out/'libredfin-ui.dylib'
    command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
        '-miphoneos-version-min=16.0','-O2','-fblocks','-fobjc-arc','-Wall','-Wextra','-Werror',
        '-Wno-deprecated-declarations','-dynamiclib','-install_name',LIBRARY,
        '-DREDFIN_UIKIT_UUID_BYTES='+define,'-I',str(HERE),str(HERE/'statusbar-cutout.m'),str(HERE/'native-diagnostics.m'),
        str(HERE/'display-probe.m'),'-framework','UIKit','-framework','Foundation',
        '-framework','CoreGraphics','-framework','QuartzCore','-framework','IOKit','-o',str(library)]
    with (out/'build.log').open('wb') as log:
        subprocess.run(command,check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--force','--sign','-','--identifier','com.redfin.ui','--timestamp=none',str(library)],
            check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--verify','--strict',str(library)],check=True,stdout=log,stderr=log)
        refresh=out/'libredfin-refresh.dylib'
        quartz_define=','.join('0x'+quartz_uuid[i:i+2] for i in range(0,32,2))
        command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
            '-miphoneos-version-min=16.0','-O2','-fobjc-arc','-Wall','-Wextra','-Werror',
            '-Wno-deprecated-declarations','-dynamiclib','-install_name',REFRESH_LIBRARY,
            '-DREDFIN_UIKIT_UUID_BYTES='+define,'-DREDFIN_QUARTZ_UUID_BYTES='+quartz_define,
            '-I',str(HERE),str(HERE/'display-refresh.m'),'-framework','Foundation',
            '-framework','QuartzCore','-framework','IOKit','-o',str(refresh)]
        subprocess.run(command,check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--force','--sign','-','--identifier','com.redfin.refresh','--timestamp=none',str(refresh)],
            check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--verify','--strict',str(refresh)],check=True,stdout=log,stderr=log)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        abi=audit_bundle(cache,[library,refresh])
    if not abi['compatible']:
        raise ValueError('cutout library imports unavailable on actual20H392')
    report=dict(success=True,uikit_uuid=uuid,quartz_uuid=quartz_uuid,methods=METHODS,
        refresh_methods=REFRESH_METHODS,abi=abi,refresh_requires_measured_panel=True,
        refresh_sha256=hashlib.sha256(refresh.read_bytes()).hexdigest(),
        sha256=hashlib.sha256(library.read_bytes()).hexdigest(),full_panel=True,physical_refresh_claimed=False)
    (out/'log-initial').write_bytes(b'REDFIN native status-bar adapter; per-boot geometry follows.\n')
    (out/'refresh-log-initial').write_bytes(b'REDFIN verified physical refresh adaptation; native periods are seconds.\n')
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def prepare_root(root,metadata,bundle):
    bundle=Path(bundle);report=json.loads((bundle/'build.json').read_text())
    if not report.get('success') or not report.get('full_panel') or not report.get('abi',{}).get('compatible'):
        raise ValueError('verified native cutout library required')
    log=bundle/'log-initial'
    prepare(root,metadata,[(bundle/'libredfin-ui.dylib',LIBRARY,0,0o644,report['sha256'],False),
        (bundle/'libredfin-refresh.dylib',REFRESH_LIBRARY,0,0o644,report['refresh_sha256'],False),
        (log,LOG,501,0o600,hashlib.sha256(log.read_bytes()).hexdigest(),True),
        (bundle/'refresh-log-initial',REFRESH_LOG,501,0o600,
         hashlib.sha256((bundle/'refresh-log-initial').read_bytes()).hexdigest(),True)])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--cache',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.out,args.cache),indent=2))
