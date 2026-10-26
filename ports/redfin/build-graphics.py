#!/usr/bin/env python3
"""Build the preferred Mesa25.0.7 freedreno bridge for arm64 iOS16.

Downloads and compiled/Apple artifacts remain in the ignored work directory.
This prepares a reviewable bundle and never writes the phone or its root.
"""
import argparse
import hashlib
import json
import os
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ports.redfin.eagl_userland import prepare as prepare_eagl
from ports.redfin.graphics_abi import Cache,DEFAULT_CACHE,audit_bundle
from ports.redfin.graphics_build_cache import compiler_cache,startup_policy

ROOT=Path(__file__).resolve().parents[2]
VERSION='25.0.7'
SHA256='592272df3cf01e85e7db300c449df5061092574d099da275d19e97ef0510f8a6'
PIN='906425b75e02b4f99eb5d7bb1ef7c9583472d772'
PATCHES=('freedreno-darwin.patch','osmesa-es-profile.patch','ir3-round-default.patch',
         'ir3-ssbo-subdword.patch','ir3-shift-split.patch')
FRAMEWORK_NAMES={
    '/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation':
        '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation',
    '/System/Library/Frameworks/IOSurface.framework/Versions/A/IOSurface':
        '/System/Library/Frameworks/IOSurface.framework/IOSurface',
}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,default=ROOT/'research/hackios-upstream/userland')
    p.add_argument('--work-dir',type=Path,default=ROOT/'research/redfin-graphics')
    p.add_argument('--cache',type=Path,default=DEFAULT_CACHE,help='actual installed arm64 dyld cache and paired .symbols')
    p.add_argument('--metal',action='store_true',help='also build the paired native Metal/AIR driver in this private work tree')
    p.add_argument('--startup-checks',choices=('on','off'),default='on',
                   help='automatic offscreen graphics correctness probes; ordinary GUI performance uses off')
    p.add_argument('--policy-only',action='store_true',
                   help='reuse exact verified native artifacts and change only startup-check policy; no build or setup')
    p.add_argument('--reuse-compiler-cache',type=Path,
                   help='retain a verified prior shader-cache identity only when compiler and shader/serialization inputs match')
    a=p.parse_args();work=a.work_dir.resolve()
    if a.policy_only:
        result=startup_policy(work,a.startup_checks=='on')
        print(json.dumps(dict(success=True,startup_checks_enabled=result['startup_checks_enabled'],
                              native_recompiled=False,input_sha256=result['input_sha256'])))
        return 0
    work.mkdir(parents=True,exist_ok=True)
    upstream=a.upstream.resolve()
    actual=subprocess.check_output(['git','-C',upstream,'rev-parse','HEAD'],text=True).strip()
    if actual!=PIN:raise ValueError('preferred graphics source must match reviewed pin '+PIN)
    log_path=work/('build-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
    result={'success':False,'upstream':PIN,'mesa':VERSION,'log':str(log_path)}
    env=dict(os.environ)
    env['PATH']='/opt/homebrew/opt/bison/bin:/opt/homebrew/opt/flex/bin:/opt/homebrew/bin:'+env.get('PATH','')
    with log_path.open('w') as log:
        def run(command,cwd=work,capture=False):
            command=list(map(str,command));log.write('\n'+repr(command)+'\n');log.flush()
            r=subprocess.run(command,cwd=cwd,env=env,check=True,text=capture,
                             stdout=subprocess.PIPE if capture else log,stderr=log)
            return r.stdout.strip() if capture else None
        try:
            sdk=Path(run(['xcrun','--sdk','iphoneos','--show-sdk-path'],capture=True))
            clang=run(['xcrun','--find','clang'],capture=True)
            clangxx=run(['xcrun','--find','clang++'],capture=True)
            ar=run(['xcrun','--find','ar'],capture=True)
            ranlib=run(['xcrun','--find','ranlib'],capture=True)
            if not (sdk/'System/Library/Frameworks/IOKit.framework/Headers/IOKitLib.h').is_file():
                raise ValueError('selected iOS SDK lacks IOKit userspace headers')
            venv=work/'venv'
            if not (venv/'bin/meson').is_file():
                run([sys.executable,'-m','venv',venv])
                run([venv/'bin/python3','-m','pip','install','meson==1.9.1','Mako==1.3.10','packaging==25.0','PyYAML==6.0.3'])
            env['PATH']=str(venv/'bin')+':'+env['PATH']
            archive=work/('mesa-'+VERSION+'.tar.xz')
            if not archive.exists():
                run(['curl','--fail','--location','--retry','3','--output',archive,
                     'https://archive.mesa3d.org/mesa-'+VERSION+'.tar.xz'])
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise ValueError('Mesa archive SHA256 mismatch')
            inputs=[upstream/'tools/mesa'/name for name in PATCHES]
            patch_count=len(inputs)
            if a.metal:
                inputs += [upstream/'tools/mesa'/name for name in
                           ('air-frontend.patch','air-ir3.patch','air-metal.patch')]
                patch_count=len(inputs)
            inputs+=sorted((upstream/'tools/mesa/redwood-drm').iterdir())
            inputs += [ROOT/'ports/redfin/graphics-linear-bounds.patch',
                       ROOT/'ports/redfin/gmem-bounds.h',ROOT/'ports/redfin/drm-profile.h']
            inputs += [ROOT/'ports/redfin'/name for name in
                       ('mesa-disk-cache.patch','mesa-disk-cache.h','mesa-disk-cache.inc','graphics-io-profile.patch')]
            if a.metal:
                inputs+=sorted((upstream/'tools/mesa/air').iterdir())
                inputs += [ROOT/'ports/redfin/metal-command-scope.patch',ROOT/'ports/redfin/metal-command-scope.h',ROOT/'ports/redfin/metal-gmem.patch',ROOT/'ports/redfin/metal-submission-profile.patch',ROOT/'ports/redfin/metal-attachment-cache.patch',ROOT/'ports/redfin/metal-raster.patch',ROOT/'ports/redfin/metal-raster.h',ROOT/'ports/redfin/metal-raster.inc',ROOT/'ports/redfin/metal-linear-import.patch',ROOT/'ports/redfin/metal-linear-import.h',ROOT/'ports/redfin/metal-linear-copy.patch',ROOT/'ports/redfin/metal-linear-copy.inc',ROOT/'ports/redfin/metal-composition-trace.patch',ROOT/'ports/redfin/metal-composition-trace.inc',ROOT/'ports/redfin/metal-blit.patch',ROOT/'ports/redfin/metal-blit.h',ROOT/'ports/redfin/metal-blit.inc',ROOT/'ports/redfin/metal-buffer-import.patch',ROOT/'ports/redfin/metal-buffer-import.h',ROOT/'ports/redfin/metal-buffer-import.inc']
                inputs += [ROOT/'ports/redfin/metal-buffer-texture.patch',ROOT/'ports/redfin/metal-buffer-texture.inc']
                inputs += [ROOT/'ports/redfin/metal-buffer-native-view.patch',ROOT/'ports/redfin/metal-composition-final.patch']
                inputs += [ROOT/'ports/redfin/metal-function-constants.patch',ROOT/'ports/redfin/metal-function-constants.h',ROOT/'ports/redfin/metal-function-constants.inc']
                inputs += [ROOT/'ports/redfin/metal-resource-pointers.patch']
                inputs += [ROOT/'ports/redfin/metal-active-resources.patch',ROOT/'ports/redfin/metal-active-resources.inc']
                inputs += [ROOT/'ports/redfin/metal-defined-state.patch']
                inputs += [ROOT/'ports/redfin/metal-memory-lifetime.patch']
                inputs += [ROOT/'ports/redfin/metal-raster-io.patch']
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-preparation.patch','metal-translation-cache.h',
                            'metal-translation-cache.inc','metal-stage-cache.inc')]
                inputs += [ROOT/'ports/redfin/metal-persistent-cache.inc',ROOT/'ports/redfin/metal-persistent-cache.patch']
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-ordering.patch','metal-ordering.h','metal-ordering.inc')]
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-bindings.patch','metal-bindings.h','metal-bindings.inc')]
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-queued-submission.patch','metal-queued.h','metal-queued.inc')]
                inputs += [ROOT/'ports/redfin/metal-scoped-submission.patch',
                           ROOT/'ports/redfin/include/redfin_gpu_scope.h',
                           ROOT/'ports/redfin/mesa-scoped-submit.inc']
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('mesa-submit-merge.patch','mesa-submit-merge.h','mesa-submit-merge.inc')]
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('mesa-resource-access.patch','mesa-access-submit.inc','include/redfin_gpu_access.h')]
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-frontend-profile.patch','metal-frontend-profile.h','metal-frontend-profile.inc')]
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-ubo-extents.patch','metal-ubo-extents.h','metal-ubo-extents.inc')]
                inputs += [ROOT/'ports/redfin'/name for name in
                           ('metal-constant-snapshot.patch','metal-constant-snapshot.h','metal-constant-snapshot.inc')]
            if a.metal:
                inputs += [ROOT/'ports/redfin/mesa-surface-padding.patch',ROOT/'ports/redfin/surface-padding.h']
                inputs += [ROOT/'ports/redfin/mesa-retained-memory.patch',ROOT/'ports/redfin/retained-memory.h']
            compiler_identity=json.dumps(dict(mesa=VERSION,archive=SHA256,
                target='arm64-apple-ios16.0',buildtype='release',ndebug=True,
                shader_cache='enabled/32M/redfin-v1',
                clang=run([clang,'--version'],capture=True),
                sdk=run(['xcrun','--sdk','iphoneos','--show-sdk-version'],capture=True),
                flags={k:env.get(k,'') for k in ('CFLAGS','CPPFLAGS','CXXFLAGS','LDFLAGS')}),
                sort_keys=True,separators=(',',':')).encode()
            fingerprint=hashlib.sha256(compiler_identity+b''.join(x.read_bytes() for x in inputs)).hexdigest()
            cache_proof=compiler_cache(ROOT,inputs,json.loads(compiler_identity),fingerprint,a.reuse_compiler_cache)
            source=work/('mesa-'+VERSION)
            stamp=source/'.redfin-graphics'
            if source.exists() and (not stamp.exists() or stamp.read_text().strip()!=fingerprint):
                raise ValueError('graphics input changed; use another --work-dir to retain the old build')
            if not source.exists():
                with tarfile.open(archive) as t:t.extractall(work,filter='data')
                for patch in inputs[:patch_count]:run(['patch','--batch','--forward','-p1','-i',patch],source)
                shutil.copytree(upstream/'tools/mesa/redwood-drm',source/'src/redwood-drm')
                shutil.copy2(ROOT/'ports/redfin/gmem-bounds.h',source/'src/gallium/drivers/freedreno/redfin_gmem_bounds.h')
                shutil.copy2(ROOT/'ports/redfin/drm-profile.h',source/'src/redwood-drm/redfin_drm_profile.h')
                run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/graphics-linear-bounds.patch'],source)
                for suffix in ('h','inc'):
                    shutil.copy2(ROOT/'ports/redfin'/('mesa-disk-cache.'+suffix),
                                 source/'src/util'/('redfin_mesa_disk_cache.'+suffix))
                (source/'src/util/redfin_mesa_cache_build.h').write_text(
                    '#define REDFIN_MESA_CACHE_BUILD_ID '+json.dumps(cache_proof['cache_id'])+'\n')
                run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/mesa-disk-cache.patch'],source)
                run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/graphics-io-profile.patch'],source)
                if a.metal:
                    shutil.copytree(upstream/'tools/mesa/air',source/'src/compiler/air')
                    shutil.copy2(ROOT/'ports/redfin/metal-command-scope.h',source/'src/compiler/air/redfin_metal_command_scope.h')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-command-scope.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-gmem.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-submission-profile.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-attachment-cache.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-raster.h',source/'src/compiler/air/redfin_metal_raster.h')
                    shutil.copy2(ROOT/'ports/redfin/metal-raster.inc',source/'src/compiler/air/redfin_metal_raster.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-raster.patch'],source)
                    for directory in ('src/compiler/air','src/gallium/drivers/freedreno'):
                        shutil.copy2(ROOT/'ports/redfin/metal-linear-import.h',source/directory/'redfin_metal_linear_import.h')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-linear-import.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-linear-copy.inc',source/'src/compiler/air/redfin_metal_linear_copy.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-linear-copy.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-composition-trace.inc',source/'src/compiler/air/redfin_metal_composition_trace.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-composition-trace.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-blit.h',source/'src/compiler/air/redfin_metal_blit.h')
                    shutil.copy2(ROOT/'ports/redfin/metal-blit.inc',source/'src/compiler/air/redfin_metal_blit.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-blit.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-buffer-import.h',source/'src/compiler/air/redfin_metal_buffer_import.h')
                    shutil.copy2(ROOT/'ports/redfin/metal-buffer-import.inc',source/'src/compiler/air/redfin_metal_buffer_import.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-buffer-import.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-buffer-texture.inc',source/'src/compiler/air/redfin_metal_buffer_texture.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-buffer-texture.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-buffer-native-view.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-composition-final.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-function-constants.h',source/'src/compiler/air/redfin_metal_function_constants.h')
                    shutil.copy2(ROOT/'ports/redfin/metal-function-constants.inc',source/'src/compiler/air/redfin_metal_function_constants.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-function-constants.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-resource-pointers.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-active-resources.inc',source/'src/compiler/air/redfin_metal_active_resources.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-active-resources.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-defined-state.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-memory-lifetime.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-raster-io.patch'],source)
                    for name in ('translation-cache.h','translation-cache.inc','stage-cache.inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-'+name),
                                     source/'src/compiler/air'/('redfin_metal_'+name.replace('-','_')))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-preparation.patch'],source)
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-persistent-cache.patch'],source)
                    shutil.copy2(ROOT/'ports/redfin/metal-persistent-cache.inc',
                                 source/'src/compiler/air/redfin_metal_persistent_cache.inc')
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-ordering.'+suffix),
                                     source/'src/compiler/air'/('redfin_metal_ordering.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-ordering.patch'],source)
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-bindings.'+suffix),
                                     source/'src/compiler/air'/('redfin_metal_bindings.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-bindings.patch'],source)
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-queued.'+suffix),
                                     source/'src/compiler/air'/('redfin_metal_queued.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-queued-submission.patch'],source)
                    for directory in ('src/freedreno/drm','src/redwood-drm'):
                        shutil.copy2(ROOT/'ports/redfin/include/redfin_gpu_scope.h',
                                     source/directory/'redfin_gpu_scope.h')
                    shutil.copy2(ROOT/'ports/redfin/mesa-scoped-submit.inc',
                                 source/'src/freedreno/drm/msm/redfin_mesa_scoped_submit.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-scoped-submission.patch'],source)
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('mesa-submit-merge.'+suffix),
                                     source/'src/freedreno/drm'/('redfin_mesa_submit_merge.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/mesa-submit-merge.patch'],source)
                    for directory in ('src/freedreno/drm','src/redwood-drm'):
                        shutil.copy2(ROOT/'ports/redfin/include/redfin_gpu_access.h',
                                     source/directory/'redfin_gpu_access.h')
                    shutil.copy2(ROOT/'ports/redfin/mesa-access-submit.inc',
                                 source/'src/freedreno/drm/msm/redfin_mesa_access_submit.inc')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/mesa-resource-access.patch'],source)
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-frontend-profile.'+suffix),
                                     source/'src/compiler/air'/('redfin_metal_frontend_profile.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-frontend-profile.patch'],source)
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-ubo-extents.'+suffix),
                                     source/'src/compiler/air'/('redfin_metal_ubo_extents.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-ubo-extents.patch'],source)
                if a.metal:
                    for directory in ('src/freedreno/drm','src/gallium/drivers/freedreno','src/redwood-drm'):
                        shutil.copy2(ROOT/'ports/redfin/surface-padding.h',source/directory/'redfin_surface_padding.h')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/mesa-surface-padding.patch'],source)
                    for directory in ('src/freedreno/drm','src/compiler/air'):
                        shutil.copy2(ROOT/'ports/redfin/retained-memory.h',source/directory/'redfin_retained_memory.h')
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/mesa-retained-memory.patch'],source)
                    for suffix in ('h','inc'):
                        shutil.copy2(ROOT/'ports/redfin'/('metal-constant-snapshot.'+suffix),
                                     source/'src/compiler/air'/('redfin_metal_constant_snapshot.'+suffix))
                    run(['patch','--batch','--forward','-p1','-i',ROOT/'ports/redfin/metal-constant-snapshot.patch'],source)
                stamp.write_text(fingerprint+'\n')
            if (source/'src/util/redfin_mesa_cache_build.h').read_text()!=\
                    '#define REDFIN_MESA_CACHE_BUILD_ID '+json.dumps(cache_proof['cache_id'])+'\n':
                raise ValueError('native shader-cache identity changed; reuse its prior compiler proof or use a fresh work directory')
            cross=work/'ios.ini'
            c=[clang,'-target','arm64-apple-ios16.0','-isysroot',str(sdk)]
            cxx=[clangxx,'-target','arm64-apple-ios16.0','-isysroot',str(sdk)]
            cross.write_text('[binaries]\nc = '+repr(c)+'\ncpp = '+repr(cxx)+'\nobjc = '+repr(c)+
                '\nar = '+repr(ar)+'\nranlib = '+repr(ranlib)+"\npkg-config = 'false'\n"+
                "[host_machine]\nsystem = 'darwin'\nsubsystem = 'ios'\ncpu_family = 'aarch64'\ncpu = 'arm64'\nendian = 'little'\n"+
                '[properties]\nneeds_exe_wrapper = true\n')
            build=work/'build-freedreno'
            if build.is_dir() or not build.exists():
                refresh=['--reconfigure','--clearcache'] if (build/'build.ninja').exists() else []
                run(['meson','setup',*refresh,build,source,'--cross-file',cross,'--wrap-mode=nofallback',
                    '--prefix=/redfin','--libdir=lib','--buildtype=release','-Db_ndebug=true','-Dplatforms=',
                    '-Dgallium-drivers=softpipe,freedreno','-Dfreedreno-kmds=msm','-Dvulkan-drivers=',
                    '-Dglx=disabled','-Degl=disabled','-Dgbm=disabled','-Dosmesa=true','-Dllvm=disabled',
                    '-Dshared-glapi=enabled','-Dgles1=disabled','-Dgles2=enabled','-Dopengl=true',
                    '-Dzstd=disabled','-Dxmlconfig=disabled','-Dexpat=disabled','-Dshader-cache=enabled',
                    '-Dshader-cache-max-size=32M',
                    '-Dvalgrind=disabled','-Dlibunwind=disabled','-Dglvnd=disabled','-Dvideo-codecs=',
                    '-Dtools=','-Dgallium-vdpau=disabled','-Dgallium-va=disabled','-Dgallium-xa=disabled',
                    '-Dlmsensors=disabled','-Dbuild-tests=false'])
            run(['ninja','-C',build])
            bundle=work/'bundle';(bundle/'lib').mkdir(parents=True,exist_ok=True)
            osmesa=build/'src/gallium/targets/osmesa/libOSMesa.8.dylib'
            glapis=list((build/'src/mapi').rglob('libglapi.0.dylib'))
            for source_file in [osmesa,*glapis]:
                target=bundle/'lib'/source_file.name;shutil.copy2(source_file,target)
                run(['install_name_tool','-id','/redfin/lib/'+target.name,target])
                dependencies=run(['otool','-L',target],capture=True)
                for line in dependencies.splitlines()[1:]:
                    dependency=line.strip().split(' ',1)[0]
                    if 'libglapi.' in dependency:
                        if not glapis:raise ValueError('OSMesa requires missing shared glapi')
                        run(['install_name_tool','-change',dependency,'/redfin/lib/libglapi.0.dylib',target])
                    elif dependency in FRAMEWORK_NAMES:
                        run(['install_name_tool','-change',dependency,FRAMEWORK_NAMES[dependency],target])
                run(['codesign','--force','--sign','-',target])
            (bundle/'bin').mkdir(exist_ok=True)
            executable=bundle/'bin/gpu-render'
            run([*c,'-O2','-Wno-deprecated-declarations',ROOT/'ports/redfin/gpu-render.c',
                '-L'+str(bundle/'lib'),'-lOSMesa.8','-framework','CoreFoundation','-framework','IOKit',
                '-framework','IOSurface','-Wl,-rpath,/redfin/lib','-o',executable])
            dependencies=run(['otool','-L',executable],capture=True)
            for line in dependencies.splitlines()[1:]:
                dependency=line.strip().split(' ',1)[0]
                if dependency in FRAMEWORK_NAMES:
                    run(['install_name_tool','-change',dependency,FRAMEWORK_NAMES[dependency],executable])
            run(['codesign','--force','--sign','-',executable])
            # Prepare the entire system bridge, using this root's own ObjC,
            # TLS/macro dispatch and QuartzCore vtable metadata.
            eagl=work/'eagl'
            abi=prepare_eagl(upstream,source,bundle/'lib/libOSMesa.8.dylib',eagl,a.cache)
            result['eagl_abi']={'system':abi['abi']['system'],'uuid':abi['abi']['uuid'],
                'quartz_uuid':abi['ca']['uuid'],'wrappers':abi['wrappers'],
                'macro_bias':abi['abi']['macro_bias'],'tls_offset':abi['abi']['tls_offset']}
            bridge=bundle/'lib/libredfin-eagl.dylib'
            loader=bundle/'lib/libredfin-graphics.dylib'
            run([*c,'-dynamiclib','-O2','-fno-omit-frame-pointer','-Wno-deprecated-declarations',
                '-I'+str(eagl),'-I'+str(ROOT/'ports/redfin'),
                eagl/'eagl.c',eagl/'gl_osmesa.c',ROOT/'ports/redfin/eagl-guard.c',
                '-L'+str(bundle/'lib'),'-lOSMesa.8','-framework','CoreFoundation','-framework','IOKit',
                '-framework','IOSurface','-lobjc','-Wl,-rpath,/redfin/lib',
                '-Wl,-install_name,/redfin/lib/libredfin-eagl.dylib','-o',bridge])
            run([*c,'-dynamiclib','-O2','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
                '-I'+str(ROOT/'ports/redfin'),ROOT/'ports/redfin/graphics-loader.c',
                '-framework','CoreFoundation','-framework','IOKit',
                '-Wl,-install_name,/redfin/lib/libredfin-graphics.dylib','-o',loader])
            for target in (bridge,loader):
                dependencies=run(['otool','-L',target],capture=True)
                for line in dependencies.splitlines()[1:]:
                    dependency=line.strip().split(' ',1)[0]
                    if dependency in FRAMEWORK_NAMES:
                        run(['install_name_tool','-change',dependency,FRAMEWORK_NAMES[dependency],target])
                run(['codesign','--force','--sign','-',target])
            metal_artifacts=[]
            if a.metal:
                from ports.redfin.metal_userland import prepare as prepare_metal
                # ABI identity binds both libraries to all compiler/driver inputs.
                metal_sources=[upstream/'userland/src'/name for name in
                               ('redwoodmetal.m','redwooddrawable.m','redwood_drawable.h')]
                metal_sources += [ROOT/'ports/redfin'/name for name in
                                  ('metal_userland.py','metal_raster_userland.py','metal_resource_userland.py','metal_blit_userland.py','metal_buffer_userland.py','metal_completion_userland.py','metal_buffer_texture_userland.py','metal-buffer-view-object.inc','metal-resource-completion.inc','metal-buffer-object.inc','iosurface-abi.h','metal-blit-encoder.inc','metal-raster.h','metal-guard.m','metal-check.m','metal-raster-check.inc','metal-vertex-check.inc','metal-blit-check.inc','metal-buffer-check.inc','metal-buffer-texture-check.inc','metal-alpha-check.inc','metal-check.metal')]
                metal_sources += [ROOT/'ports/redfin'/name for name in ('metal_function_constants_userland.py','metal-function-constants-object.inc','metal-function-constants.h','metal-function-constants-check.inc')]
                metal_sources += [ROOT/'ports/redfin'/name for name in ('metal-resource-check.c','metal-resource-check.ll')]
                metal_sources += [ROOT/'ports/redfin/graphics-memory-report.h']
                metal_sources += [ROOT/'ports/redfin/metal-half-check.inc']
                metal_sources += [ROOT/'ports/redfin'/name for name in
                                  ('metal-translation-cache.h','metal-cache-check.inc')]
                metal_sources += [ROOT/'ports/redfin'/name for name in
                                  ('metal-ordering.h','metal-ordering-check.inc')]
                metal_sources += [ROOT/'ports/redfin'/name for name in
                                  ('metal-bindings.h','metal-bindings-check.inc')]
                metal_sources += [ROOT/'ports/redfin'/name for name in
                                  ('metal_queued_userland.py','metal-queued.h','metal-queued-check.inc','metal-queued-resource-check.inc','metal-frontend-profile.h')]
                metal_sources += [ROOT/'ports/redfin/metal-ubo-extents-check.inc']
                metal_sources += [ROOT/'ports/redfin/metal-physical-check.inc']
                metal_sources += [ROOT/'ports/redfin/metal-surface-cache-check.inc']
                metal_sources += [ROOT/'ports/redfin/surface-padding.h',ROOT/'ports/redfin/surface-padding-check.inc']
                metal_sources += [ROOT/'ports/redfin/retained-memory.h']
                metal_sources += [ROOT/'ports/redfin'/name for name in
                                  ('metal-scheduling.h','metal-scheduling-check.inc')]
                pairing=hashlib.sha256(fingerprint.encode()+b''.join(p.read_bytes() for p in metal_sources)).hexdigest()
                metal=work/'metal'
                result['metal_abi']=prepare_metal(upstream,metal,a.cache,pairing)
                # Compile the same contract marker into the AIR library itself.
                marker=source/'src/compiler/air/redfin_pairing.c'
                marker.write_text('const char *rwa_redfin_contract(void);\nconst char *rwa_redfin_contract(void){return "'+pairing+'";}\n')
                meson_file=source/'src/gallium/drivers/freedreno/meson.build'
                before="files('../../../compiler/air/air_metal.c'),"
                after="files('../../../compiler/air/air_metal.c', '../../../compiler/air/redfin_pairing.c'),"
                content=meson_file.read_text()
                if before in content:
                    if content.count(before)!=1:raise ValueError('unreviewed AIR target')
                    meson_file.write_text(content.replace(before,after))
                elif content.count(after)!=1:raise ValueError('AIR pairing target absent')
                run(['ninja','-C',build,'src/gallium/drivers/freedreno/libredwoodair.dylib'])
                air=bundle/'lib/libredfinair.dylib'
                shutil.copy2(build/'src/gallium/drivers/freedreno/libredwoodair.dylib',air)
                run(['install_name_tool','-id','/redfin/lib/libredfinair.dylib',air])
                plugin=bundle/'System/Library/Extensions/RedfinMetal.bundle'
                plugin.mkdir(parents=True,exist_ok=True)
                binary=plugin/'RedfinMetal'
                run([*c,'-bundle','-O2','-fno-omit-frame-pointer','-Wno-deprecated-declarations',
                    '-Werror=incompatible-pointer-types','-Werror=incompatible-function-pointer-types',
                    '-I'+str(metal),'-I'+str(ROOT/'ports/redfin'),metal/'redwoodmetal.m',metal/'redwooddrawable.m',
                    ROOT/'ports/redfin/metal-guard.m','-framework','Foundation',
                    '-framework','CoreFoundation','-framework','IOKit','-framework','Metal','-framework','IOSurface','-lobjc','-o',binary])
                (plugin/'Info.plist').write_bytes(plistlib.dumps(dict(
                    CFBundleIdentifier='com.redfin.metal',CFBundleName='RedfinMetal',
                    CFBundleExecutable='RedfinMetal',CFBundlePackageType='BNDL',
                    CFBundleInfoDictionaryVersion='6.0',CFBundleVersion='1',
                    CFBundleSupportedPlatforms=['iPhoneOS'],NSPrincipalClass='RedwoodMetalDevice')))
                for target in (air,binary):
                    dependencies=run(['otool','-L',target],capture=True)
                    for line in dependencies.splitlines()[1:]:
                        dependency=line.strip().split(' ',1)[0]
                        if dependency in FRAMEWORK_NAMES:
                            run(['install_name_tool','-change',dependency,FRAMEWORK_NAMES[dependency],target])
                        elif 'libglapi.' in dependency:
                            run(['install_name_tool','-change',dependency,'/redfin/lib/libglapi.0.dylib',target])
                    run(['codesign','--force','--sign','-',target])
                    run(['codesign','--verify','--strict',target])
                checker=bundle/'bin/metal-check'
                run([*c,'-O2','-fblocks','-fno-omit-frame-pointer','-Wno-deprecated-declarations',
                    '-I'+str(ROOT/'ports/redfin'),ROOT/'ports/redfin/metal-check.m',
                    '-I'+str(source/'src/compiler/air'),ROOT/'ports/redfin/metal-resource-check.c',
                    '-L'+str(bundle/'lib'),'-lredfinair',
                    '-framework','Foundation','-framework','Metal','-framework','CoreFoundation',
                    '-framework','IOKit','-framework','IOSurface','-lobjc','-o',checker])
                dependencies=run(['otool','-L',checker],capture=True)
                for line in dependencies.splitlines()[1:]:
                    dependency=line.strip().split(' ',1)[0]
                    if dependency in FRAMEWORK_NAMES:
                        run(['install_name_tool','-change',dependency,FRAMEWORK_NAMES[dependency],checker])
                checker_entitlements=metal/'metal-check.entitlements.plist'
                checker_entitlements.write_bytes(plistlib.dumps({'application-identifier':'com.redfin.metal-check',
                    'platform-application':True,'com.apple.private.memorystatus':True}))
                run(['codesign','--force','--sign','-','--timestamp=none','--identifier','com.redfin.metal-check',
                    '--entitlements',checker_entitlements,checker])
                run(['codesign','--verify','--strict',checker])
                # Keep the old device allocation intact: its eight inline HFS
                # extents cannot grow through this host library's overflow ABI.
                shader=bundle/'lib/redfin-check-v2.metallib'
                run(['xcrun','--sdk','iphoneos','metal','-target','air64-apple-ios16.0',
                    '-std=ios-metal2.4','-c',ROOT/'ports/redfin/metal-check.metal','-o',metal/'check.air'])
                run(['xcrun','--sdk','iphoneos','metallib',metal/'check.air','-o',shader])
                if shader.read_bytes()[:4]!=b'MTLB':raise ValueError('native Metal shader library absent')
                resource_shader=bundle/'lib/redfin-resource-check.bc'
                run(['xcrun','--sdk','iphoneos','metal','-x','ir','-c','-emit-llvm','-O0',
                     '-Xclang','-disable-llvm-passes',ROOT/'ports/redfin/metal-resource-check.ll','-o',resource_shader])
                from ports.redfin.metal_userland import job as metal_job,JOB_PATH as METAL_JOB,LOG_PATH as METAL_LOG
                check_job=bundle/METAL_JOB.lstrip('/');check_job.parent.mkdir(parents=True,exist_ok=True)
                check_job.write_bytes(plistlib.dumps(metal_job(enabled=a.startup_checks=='on'),fmt=plistlib.FMT_BINARY,sort_keys=False))
                check_log=bundle/'metal-log-initial';check_log.write_text('REDFIN native Metal/AIR; hardware observations follow.\n')
                metal_artifacts=[air,binary,checker]
                result['metal_pairing_sha256']=pairing
            launch=bundle/'System/Library/LaunchDaemons'
            launch.mkdir(parents=True,exist_ok=True)
            if a.startup_checks=='on':
                shutil.copy2(ROOT/'ports/redfin/gpu-render-job.plist',launch/'com.redfin.gpu-render.plist')
            else:
                from ports.redfin.gpu_userland import job as gpu_job
                (launch/'com.redfin.gpu-render.plist').write_bytes(plistlib.dumps(gpu_job(enabled=False),fmt=plistlib.FMT_BINARY,sort_keys=False))
            old_job=bundle/'Library/LaunchDaemons/com.redfin.gpu-render.plist'
            if old_job.is_file():old_job.unlink()  # old build output only, never a root/device path
            shutil.copy2(upstream/'LICENSE',bundle/'UPSTREAM-LICENSE')
            with Cache(a.cache) as cache:
                proof=audit_bundle(cache,[executable,*sorted((bundle/'lib').glob('*.dylib')),*[p for p in metal_artifacts if p.parent!=bundle/'lib']])
            (work/'abi-check.json').write_text(json.dumps(proof,indent=2)+'\n')
            if not proof['compatible']:raise ValueError('actual iOS graphics imports missing; see abi-check.json')
            if a.metal:
                selected=[(air,'/redfin/lib/'+air.name,0,0o644),
                    (binary,'/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal',0,0o755),
                    (plugin/'Info.plist','/System/Library/Extensions/RedfinMetal.bundle/Info.plist',0,0o644),
                    (plugin/'_CodeSignature/CodeResources','/System/Library/Extensions/RedfinMetal.bundle/_CodeSignature/CodeResources',0,0o644),
                    (checker,'/redfin/bin/metal-check',0,0o755),(shader,'/redfin/lib/'+shader.name,0,0o644),
                    (resource_shader,'/redfin/lib/'+resource_shader.name,0,0o644),
                    (check_job,METAL_JOB,0,0o644),(check_log,METAL_LOG,501,0o600)]
                metal_manifest=dict(success=True,actual_abi_compatible=True,pairing_sha256=pairing,
                    max_buffer_bytes=128<<20,startup_checks_enabled=a.startup_checks=='on',files={target:dict(source=str(source.relative_to(bundle)),
                        uid=uid,mode=mode,sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                        for source,target,uid,mode in selected})
                (bundle/'metal-build.json').write_text(json.dumps(metal_manifest,indent=2)+'\n')
            result['actual_abi_compatible']=True
            result.update(success=True,sdk=str(sdk),input_sha256=fingerprint,bundle=str(bundle),
                startup_checks_enabled=a.startup_checks=='on',
                compiler_cache=cache_proof,
                gui_profile_sha256=hashlib.sha256((ROOT/'ports/redfin/gui-profile.h').read_bytes()).hexdigest(),
                gui_sources_sha256={name:hashlib.sha256((ROOT/'ports/redfin'/name).read_bytes()).hexdigest()
                    for name in ('graphics-loader.c','graphics-memory-report.h','eagl-guard.c','eagl_userland.py')},
                artifacts={str(x.relative_to(bundle)):hashlib.sha256(x.read_bytes()).hexdigest()
                           for x in sorted(bundle.rglob('*')) if x.is_file()})
            (work/'compiler-inputs.json').write_text(json.dumps(cache_proof,indent=2)+'\n')
        except (subprocess.CalledProcessError,ValueError,OSError) as e:
            result['error']=str(e);log.write('\nFAILED '+str(e)+'\n')
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(('built: ' if result['success'] else 'build failed: ')+str(log_path))
    return 0 if result['success'] else 1


if __name__=='__main__':sys.exit(main())
