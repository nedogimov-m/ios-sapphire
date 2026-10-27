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
    'UIScreen': {'-brightness':'d16@0:8','-setBrightness:':'v24@0:8d16'},
    'UIView': {'-setFrame:':'v48@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16',
        '-setBounds:':'v48@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16',
        '-setCenter:':'v32@0:8{CGPoint=dd}16','-layoutSubviews':'v16@0:8'},
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
    'CADisplay':{'+mainDisplay':'@16@0:8','-refreshRate':'d16@0:8','-hardwareRefreshRate':'d16@0:8','-heartbeatRate':'d16@0:8'}}
REFRESH_METHODS['CADisplay']['-minimumFrameDuration']='q16@0:8'
REFRESH_METHODS['CADisplayLink']={'-maximumRefreshRate':'d16@0:8'}
CONTENT_METHODS={
    'UIWindow':{'-_hasContext':'B16@0:8','-_contextId':'I16@0:8','-_isVisible':'B16@0:8',
        '+allWindowsIncludingInternalWindows:onlyVisibleWindows:forScreen:':'@32@0:8B16B20@24'},
    'CALayer':{'-context':'@16@0:8'},'CAContext':{'-contextId':'I16@0:8'},
}


def build(out,cache_path=None):
    out=Path(out).resolve()
    if (ROOT/'research').resolve() not in out.parents:
        raise ValueError('native libraries must stay under ignored research')
    out.mkdir(parents=True,exist_ok=False)
    with (Cache(cache_path) if cache_path else Cache()) as cache:
        image=cache.image(UIKIT)
        for name,wanted in METHODS.items():
            methods=image.objc_methods(name,selectors=wanted)
            if any(key not in methods or methods[key]['types']!=types for key,types in wanted.items()):
                raise ValueError('native status-bar ABI differs: '+name)
        uuid=image.uuid
        quartz=cache.image('/System/Library/Frameworks/QuartzCore.framework/QuartzCore')
        for name,wanted in REFRESH_METHODS.items():
            actual=(image if name=='UIScreen' else quartz).objc_methods(name)
            if any(key not in actual or actual[key]['types']!=types for key,types in wanted.items()):
                raise ValueError('native display-period ABI differs: '+name)
        quartz_uuid=quartz.uuid
        for name,wanted in CONTENT_METHODS.items():
            actual=(image if name=='UIWindow' else quartz).objc_methods(name,selectors=wanted)
            if any(key not in actual or actual[key]['types']!=types for key,types in wanted.items()):
                raise ValueError('native visible content/context ABI differs: '+name)
        from ports.redfin.cadence_abi import derive as derive_cadence
        cadence=derive_cadence(cache)
        from ports.redfin.brightness_abi import derive_system as derive_system_brightness
        system_brightness=derive_system_brightness(cache)
        from ports.redfin.system_display_abi import derive as derive_system_display
        system_display=derive_system_display(cache)
        foundation=cache.image('/System/Library/Frameworks/Foundation.framework/Foundation')
        bundle_methods=foundation.objc_methods('NSBundle')
        if bundle_methods.get('-objectForInfoDictionaryKey:',{}).get('types')!='@24@0:8@16':
            raise ValueError('native main-bundle public info getter ABI differs')
        foundation_uuid=foundation.uuid
    define=','.join('0x'+uuid[i:i+2] for i in range(0,32,2))
    quartz_define=','.join('0x'+quartz_uuid[i:i+2] for i in range(0,32,2))
    bks_define=','.join('0x'+system_brightness['uuid'][i:i+2] for i in range(0,32,2))
    def native_define(name):
        value=system_display['reviewed'][name]['uuid']
        return ','.join('0x'+value[i:i+2] for i in range(0,32,2))
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    library=out/'libredfin-ui.dylib'
    command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
        '-miphoneos-version-min=16.0','-O2','-fblocks','-fobjc-arc','-Wall','-Wextra','-Werror',
        '-Wno-deprecated-declarations','-dynamiclib','-install_name',LIBRARY,
        '-DREDFIN_UIKIT_UUID_BYTES='+define,'-DREDFIN_BKS_UUID_BYTES='+bks_define,
        '-DREDFIN_QUARTZ_UUID_BYTES='+quartz_define,
        '-DREDFIN_SB_UUID_BYTES='+native_define('SBIdleTimerGlobalCoordinator__sharedInstanceIfExists'),
        '-DREDFIN_BB_UUID_BYTES='+native_define('BSSimpleAssertion__invalidate'),
        '-I',str(HERE),str(HERE/'statusbar-cutout.m'),str(HERE/'native-diagnostics.m'),str(HERE/'native-tcc-probe.m'),
        str(HERE/'display-probe.m'),str(HERE/'display-content.m'),str(HERE/'controls-probe.m'),str(HERE/'brightness-system.m'),str(HERE/'idle-system.m'),
        '-framework','UIKit','-framework','Foundation',
        '-framework','CoreGraphics','-framework','QuartzCore','-framework','IOKit','-o',str(library)]
    with (out/'build.log').open('wb') as log:
        subprocess.run(command,check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--force','--sign','-','--identifier','com.redfin.ui','--timestamp=none',str(library)],
            check=True,stdout=log,stderr=log)
        subprocess.run(['codesign','--verify','--strict',str(library)],check=True,stdout=log,stderr=log)
        refresh=out/'libredfin-refresh.dylib'
        quartz_define=','.join('0x'+quartz_uuid[i:i+2] for i in range(0,32,2))
        foundation_define=','.join('0x'+foundation_uuid[i:i+2] for i in range(0,32,2))
        command=['xcrun','--sdk','iphoneos','clang','-arch','arm64','-isysroot',sdk,
            '-miphoneos-version-min=16.0','-O2','-fobjc-arc','-Wall','-Wextra','-Werror',
            '-Wno-deprecated-declarations','-dynamiclib','-install_name',REFRESH_LIBRARY,
            '-DREDFIN_UIKIT_UUID_BYTES='+define,'-DREDFIN_QUARTZ_UUID_BYTES='+quartz_define,
            '-DREDFIN_FOUNDATION_UUID_BYTES='+foundation_define,
            '-DREDFIN_CB_UUID_BYTES='+native_define('BLControl__findBacklight'),
            '-DREDFIN_BKD_UUID_BYTES='+','.join('0x'+system_display['backboard']['uuid'][i:i+2] for i in range(0,32,2)),
            '-DREDFIN_IOKIT_UUID_BYTES='+','.join('0x'+system_display['iokit_properties']['uuid'][i:i+2] for i in range(0,32,2)),
            '-I',str(HERE),str(HERE/'display-refresh.m'),str(HERE/'backlight-system.m'),str(HERE/'backlight-failures.m'),
            '-framework','Foundation',
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
    report.update(probe_opt_in_only=True,probe_uses_native_completed_counts=True,probe_statistics_version=2,
        controls_probe_opt_in_only=True,controls_probe_restores_brightness_and_display=True,
        controls_probe_physical_presses_tested=False,
        controls_probe_system_brightness_abi=system_brightness,
        controls_probe_uses_UIScreen_setter=False,probe_requires_nonempty_window=True,
        probe_content_methods=CONTENT_METHODS,probe_requires_visible_attached_content=True,
        probe_samples_native_presentation_motion=True,probe_content_model_preserved=True,
        native_system_display_abi=system_display,probe_owns_native_SpringBoard_idle_assertion=True,
        native_backlight_route='separate AppleARMBacklight; synchronous IOMFB unsupported',
        controls_probe_restoration_accepts_original_physical_state=True,controls_probe_composes_during_power_checks=True,
        native_backlight_error_formats_opt_in_only=True,native_backlight_encoded_log_arguments_preserved=True,
        native_manual_backlight_fallback=True,native_manual_backlight_preserves_BKS_state_and_preferences=True,
        probe_checks_exit_version=1,
        native_cadence_abi=cadence,native_display_period_getters_preserved=True,
        high_refresh_main_bundle_opt_in=True,foundation_uuid=foundation_uuid,
        probe_request_path='/redfin/display-probe-request',
        source_sha256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in
            ('statusbar-cutout.m','native-diagnostics.m','native-tcc-probe.m','display-probe.m','controls-probe.m','controls-policy.h',
             'brightness-system.h','brightness-system.m','brightness_abi.py',
             'native-image-uuid.h','idle-system.h','idle-system.m','backlight-system.m','system_display_abi.py',
             'backlight-failures.m',
             'backlight-manual.h',
             'display-refresh.m','display-content.h','display-content.m','display-benchmark.h','display-statistics.h','display-mode.h','cadence_abi.py','gui-profile.h',
             'statusbar-geometry.h','graphics-exec-scope.h')})
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
