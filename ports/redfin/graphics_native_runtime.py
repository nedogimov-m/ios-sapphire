"""Narrow, provenance-checked AIR wait relink; no compiler rebuild or device I/O."""
import copy
import json
from pathlib import Path
import shlex
import shutil

from ports.redfin.graphics_build_cache import components,digest,require,verify_build
from ports.redfin.graphics_build_inputs import metal_pairing,metal_plugin_command

RUNTIME_INPUTS=frozenset('ports/redfin/'+name for name in (
    'metal-native-waits.patch','metal-native-waits.inc','metal-queued.inc'))
AIR_TARGET='src/gallium/drivers/freedreno/libredwoodair.dylib'
AIR_DIR='src/compiler/air'
FRAMEWORK_NAMES={
    '/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation':
        '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation',
    '/System/Library/Frameworks/IOSurface.framework/Versions/A/IOSurface':
        '/System/Library/Frameworks/IOSurface.framework/IOSurface',
}


def runtime_delta(prior,current):
    """Only the complete, reviewed wait block can reuse these native archives."""
    before={r['path']:r['sha256'] for r in prior}
    after={r['path']:r['sha256'] for r in current}
    require(len(before)==len(prior) and len(after)==len(current),'duplicate native runtime input')
    require(set(before)<=set(after),'native runtime reuse cannot remove inputs')
    changed={p for p in after if before.get(p)!=after[p]}
    require(changed==RUNTIME_INPUTS,'native runtime reuse requires exactly the reviewed wait block')
    require([r for r in prior if r['path'] not in RUNTIME_INPUTS]==
            [r for r in current if r['path'] not in RUNTIME_INPUTS],
            'native runtime reuse cannot reorder unrelated inputs')
    return sorted(changed)


def runtime_commands(commands,build,old_source,source,objects,air):
    """Redirect all outputs and source includes; never invoke mutating Ninja."""
    build,old_source,source,objects,air=map(Path,(build,old_source,source,objects,air))
    build=build.resolve();old_source=old_source.resolve()
    selected=[]
    replacements={}
    for name in ('air_metal.c','redfin_pairing.c'):
        found=[c for c in commands if '-c' in c and Path(c[c.index('-c')+1]).name==name]
        require(len(found)==1,'one exact native compile command required: '+name)
        original=found[0];command=list(original)
        out=original[original.index('-o')+1];new=objects/(name+'.o')
        replacements[out]=str(new)
        for flag,value in (('-o',new),('-MF',str(new)+'.d'),('-MQ',new),('-c',source/AIR_DIR/name)):
            require(command.count(flag)==1,'unreviewed native compile output: '+flag)
            command[command.index(flag)+1]=str(value)
        for i,arg in enumerate(command):
            if arg.startswith('-I'):
                path=(build/arg[2:]).resolve()
                if path==old_source or old_source in path.parents:
                    command[i]='-I'+str(source/path.relative_to(old_source))
        selected.append(command)
    links=[c for c in commands if '-o' in c and c[c.index('-o')+1]==AIR_TARGET and '-c' not in c]
    require(len(links)==1,'one exact native AIR link command required')
    command=[replacements.get(arg,arg) for arg in links[0]]
    command[command.index('-o')+1]=str(air)
    reused=[(build/arg).resolve() for arg in links[0]
            if arg.endswith(('.a','.o')) and arg not in replacements]
    require(reused and all(p.is_file() for p in reused),'native AIR link inputs are incomplete')
    selected.append(command)
    return selected,reused


def build_runtime(root,upstream,work,previous,cache,inputs,fingerprint,cache_proof,clang,sdk,checks,run):
    from ports.redfin import metal_userland
    from ports.redfin.graphics_abi import Cache,audit_bundle
    root,upstream,work,previous=map(lambda p:Path(p).resolve(),(root,upstream,work,previous))
    require(work!=previous and previous not in work.parents and work not in previous.parents,
            'runtime output must be independent of its immutable baseline')
    prior=verify_build(previous)
    require(prior['startup_checks_enabled']==checks,'runtime reuse cannot change diagnostic policy')
    require(cache_proof.get('reused') and cache_proof.get('verified_prior_artifacts'),
            'verified unchanged shader/compiler cache required')
    changes=runtime_delta(json.loads((previous/'compiler-inputs.json').read_text())['components'],
                          components(root,inputs))
    # This binds every plugin/checker/shader source to the accepted baseline.
    # A runtime shortcut cannot silently retain an out-of-date correctness gate.
    require(metal_pairing(root,upstream,prior['input_sha256'])==prior['metal_pairing_sha256'],
            'Metal plugin/checker/shader inputs changed; full build required')
    source=work/'mesa-25.0.7';bundle=work/'bundle';objects=work/'runtime-objects'
    require(not any(p.exists() for p in (source,bundle,objects,work/'result.json')),
            'runtime output already contains a build; choose a fresh work directory')
    old_source=previous/'mesa-25.0.7';build=previous/'build-freedreno'
    commands=[shlex.split(line) for line in run(['ninja','-C',build,'-t','commands',AIR_TARGET],capture=True).splitlines()]
    # APFS clones keep the original source and its build immutable without an
    # archive download, extraction, package setup or a second compiler build.
    run(['cp','-cR',old_source,source])
    run(['cp','-cR',previous/'bundle',bundle])
    objects.mkdir()
    before_air=digest((source/AIR_DIR/'air_metal.c').read_bytes())
    run(['patch','--batch','--forward','-p1','-i',root/'ports/redfin/metal-native-waits.patch'],source)
    shutil.copy2(root/'ports/redfin/metal-native-waits.inc',source/AIR_DIR/'redfin_metal_native_waits.inc')
    shutil.copy2(root/'ports/redfin/metal-queued.inc',source/AIR_DIR/'redfin_metal_queued.inc')
    pairing=metal_pairing(root,upstream,fingerprint)
    (source/AIR_DIR/'redfin_pairing.c').write_text(
        'const char *rwa_redfin_contract(void);\nconst char *rwa_redfin_contract(void){return "'+pairing+'";}\n')
    (source/'.redfin-graphics').write_text(fingerprint+'\n')
    air=bundle/'lib/libredfinair.dylib'
    commands,reused=runtime_commands(commands,build,old_source,source,objects,air)
    reused_hashes={str(p.relative_to(previous)):digest(p.read_bytes()) for p in reused}
    (work/'runtime-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    for command in commands:run(command,build)
    run(['install_name_tool','-id','/redfin/lib/libredfinair.dylib',air])
    metal=work/'metal'
    metal_abi=metal_userland.prepare(upstream,metal,cache,pairing)
    previous_sources=prior['metal_abi']['source_sha256']
    current_sources=metal_abi['source_sha256']
    require(set(current_sources)<=set(previous_sources) and
            set(previous_sources)-set(current_sources)<= {'check.air','metal-check.entitlements.plist'},
            'adapted native source inventory changed during runtime reuse')
    for name in current_sources:
        if name!='metal-abi.h':
            require(current_sources[name]==previous_sources[name],
                    'adapted Metal source changed during runtime reuse: '+name)
    plugin=bundle/'System/Library/Extensions/RedfinMetal.bundle'
    binary=plugin/'RedfinMetal'
    run(metal_plugin_command(root,clang,sdk,metal,binary))
    for target in (air,binary):
        for line in run(['otool','-L',target],capture=True).splitlines()[1:]:
            dependency=line.strip().split(' ',1)[0]
            if dependency in FRAMEWORK_NAMES:
                run(['install_name_tool','-change',dependency,FRAMEWORK_NAMES[dependency],target])
            elif 'libglapi.' in dependency:
                run(['install_name_tool','-change',dependency,'/redfin/lib/libglapi.0.dylib',target])
        run(['codesign','--force','--sign','-',target])
        run(['codesign','--verify','--strict',target])
    manifest=json.loads((bundle/'metal-build.json').read_text())
    manifest['pairing_sha256']=pairing
    for record in manifest['files'].values():
        record['sha256']=digest((bundle/record['source']).read_bytes())
    (bundle/'metal-build.json').write_text(json.dumps(manifest,indent=2)+'\n')
    metal_userland.inventory(bundle)
    allowed={'lib/libredfinair.dylib','System/Library/Extensions/RedfinMetal.bundle/RedfinMetal',
             'System/Library/Extensions/RedfinMetal.bundle/_CodeSignature/CodeResources','metal-build.json'}
    artifacts={str(p.relative_to(bundle)):digest(p.read_bytes()) for p in sorted(bundle.rglob('*')) if p.is_file()}
    require(set(artifacts)==set(prior['artifacts']),'runtime reuse changed the artifact inventory')
    require(all(artifacts[p]==h for p,h in prior['artifacts'].items() if p not in allowed),
            'unrelated GLES/compiler/checker/shader artifact changed')
    require(all(digest((previous/p).read_bytes())==h for p,h in reused_hashes.items()),
            'baseline native archive changed while relinking')
    verify_build(previous)
    audited=[bundle/'bin/gpu-render',*sorted((bundle/'lib').glob('*.dylib')),binary,bundle/'bin/metal-check']
    with Cache(cache) as actual:proof=audit_bundle(actual,audited)
    (work/'abi-check.json').write_text(json.dumps(proof,indent=2)+'\n')
    require(proof['compatible'],'runtime graphics imports fail actual iOS ABI audit')
    result=copy.deepcopy(prior)
    result.update(success=True,actual_abi_compatible=True,bundle=str(bundle),input_sha256=fingerprint,
        metal_pairing_sha256=pairing,metal_abi=metal_abi,compiler_cache=cache_proof,artifacts=artifacts,
        runtime_reuse=dict(kind='native-cold-output-waits-v1',baseline=str(previous),
            baseline_input_sha256=prior['input_sha256'],changed_inputs=changes,
            baseline_air_source_sha256=before_air,commands=str(work/'runtime-commands.json'),
            reused_link_inputs=reused_hashes,immutable_baseline_verified=True,
            compiler_GLES_shader_checker_recompiled=False,rebuilt=['AIR runtime','AIR pairing','Metal plugin']))
    (work/'compiler-inputs.json').write_text(json.dumps(cache_proof,indent=2)+'\n')
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    verify_build(work)
    return result
