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
    define=','.join('0x'+uuid[i:i+2] for i in range(0,32,2))
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    library=out/'libredfin-ui.dylib'
    command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
        '-miphoneos-version-min=16.0','-O2','-fblocks','-fobjc-arc','-Wall','-Wextra','-Werror',
        '-Wno-deprecated-declarations','-dynamiclib','-install_name',LIBRARY,
        '-DREDFIN_UIKIT_UUID_BYTES='+define,'-I',str(HERE),str(HERE/'statusbar-cutout.m'),
        '-framework','UIKit','-framework','Foundation','-framework','CoreGraphics','-o',str(library)]
    with (out/'build.log').open('wb') as log:
        subprocess.run(command,check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--force','--sign','-','--identifier','com.redfin.ui','--timestamp=none',str(library)],
            check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--verify','--strict',str(library)],check=True,stdout=log,stderr=log)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        abi=audit_bundle(cache,[library])
    if not abi['compatible']:
        raise ValueError('cutout library imports unavailable on actual20H392')
    report=dict(success=True,uikit_uuid=uuid,methods=METHODS,abi=abi,
        sha256=hashlib.sha256(library.read_bytes()).hexdigest(),full_panel=True,physical_refresh_claimed=False)
    (out/'log-initial').write_bytes(b'REDFIN native status-bar adapter; per-boot geometry follows.\n')
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def prepare_root(root,metadata,bundle):
    bundle=Path(bundle);report=json.loads((bundle/'build.json').read_text())
    if not report.get('success') or not report.get('full_panel') or not report.get('abi',{}).get('compatible'):
        raise ValueError('verified native cutout library required')
    log=bundle/'log-initial'
    prepare(root,metadata,[(bundle/'libredfin-ui.dylib',LIBRARY,0,0o644,report['sha256'],False),
        (log,LOG,501,0o600,hashlib.sha256(log.read_bytes()).hexdigest(),True)])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--cache',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.out,args.cache),indent=2))
