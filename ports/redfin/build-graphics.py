#!/usr/bin/env python3
"""Build the preferred Mesa25.0.7 freedreno bridge for arm64 iOS16.

Downloads and compiled/Apple artifacts remain in the ignored work directory.
This prepares a reviewable bundle and never writes the phone or its root.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

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
    a=p.parse_args();work=a.work_dir.resolve();work.mkdir(parents=True,exist_ok=True)
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
            inputs+=sorted((upstream/'tools/mesa/redwood-drm').iterdir())
            fingerprint=hashlib.sha256(b''.join(x.read_bytes() for x in inputs)).hexdigest()
            source=work/('mesa-'+VERSION)
            stamp=source/'.redfin-graphics'
            if source.exists() and (not stamp.exists() or stamp.read_text().strip()!=fingerprint):
                raise ValueError('graphics input changed; use another --work-dir to retain the old build')
            if not source.exists():
                with tarfile.open(archive) as t:t.extractall(work,filter='data')
                for patch in inputs[:len(PATCHES)]:run(['patch','--batch','--forward','-p1','-i',patch],source)
                shutil.copytree(upstream/'tools/mesa/redwood-drm',source/'src/redwood-drm')
                stamp.write_text(fingerprint+'\n')
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
                    '-Dzstd=disabled','-Dxmlconfig=disabled','-Dexpat=disabled','-Dshader-cache=disabled',
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
            launch=bundle/'Library/LaunchDaemons'
            launch.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/'ports/redfin/gpu-render-job.plist',launch/'com.redfin.gpu-render.plist')
            result.update(success=True,sdk=str(sdk),input_sha256=fingerprint,bundle=str(bundle),
                artifacts={str(x.relative_to(bundle)):hashlib.sha256(x.read_bytes()).hexdigest()
                           for x in sorted(bundle.rglob('*')) if x.is_file()})
        except (subprocess.CalledProcessError,ValueError,OSError) as e:
            result['error']=str(e);log.write('\nFAILED '+str(e)+'\n')
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(('built: ' if result['success'] else 'build failed: ')+str(log_path))
    return 0 if result['success'] else 1


if __name__=='__main__':sys.exit(main())
