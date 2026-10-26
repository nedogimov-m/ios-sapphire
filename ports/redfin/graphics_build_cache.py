"""Verified native-artifact reuse and shader cache compatibility; no device I/O."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import time

VERSION=1
# Reviewed native transport/dependency bookkeeping and runtime observations never change serialized
# AIR/NIR, Adreno programs or shader options. Every other input stays strict.
TRANSPORT_INPUTS=frozenset('ports/redfin/'+name for name in (
    'drm-profile.h','metal-scoped-submission.patch','include/redfin_gpu_scope.h',
    'mesa-scoped-submit.inc','mesa-submit-merge.patch','mesa-submit-merge.h',
    'mesa-submit-merge.inc','include/redfin_gpu_access.h',
    'mesa-resource-access.patch','mesa-access-submit.inc',
    'metal-frontend-profile.patch','metal-frontend-profile.h','metal-frontend-profile.inc'))
TRANSPORT_PATCH_TARGETS=frozenset((
    'src/freedreno/drm/freedreno_bo.c','src/freedreno/drm/freedreno_priv.h',
    'src/freedreno/drm/freedreno_ringbuffer.h','src/freedreno/drm/freedreno_ringbuffer_sp.h',
    'src/freedreno/drm/freedreno_ringbuffer_sp.c','src/freedreno/drm/msm/msm_bo.c',
    'src/freedreno/drm/msm/msm_pipe.c','src/freedreno/drm/msm/msm_ringbuffer_sp.c',
    'src/redwood-drm/redwood_drm.c','src/redwood-drm/xf86drm.h',
    'src/gallium/drivers/freedreno/freedreno_resource.h',
    'src/gallium/drivers/freedreno/freedreno_batch.c'))
RUNTIME_PATCH_TARGETS={
    # This reviewed overlay only wraps existing runtime calls with counters.
    # Keep its exception separate from the general native-transport targets.
    'ports/redfin/metal-frontend-profile.patch':frozenset(('src/compiler/air/air_metal.c',)),
}


def require(ok,message):
    if not ok:raise ValueError(message)


def digest(data):return hashlib.sha256(data).hexdigest()


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def components(root,inputs):
    root=Path(root).resolve();records=[]
    for path in inputs:
        path=Path(path).resolve();name=path.relative_to(root).as_posix()
        if name in TRANSPORT_INPUTS and name.endswith('.patch'):
            targets=re.findall(r'^\+\+\+ b/([^\n]+)$',path.read_text(),re.M)
            allowed=RUNTIME_PATCH_TARGETS.get(name,TRANSPORT_PATCH_TARGETS)
            require(targets and set(targets)<=allowed,
                    'transport patch touches an unreviewed compiler input: '+name)
        records.append({'path':name,'sha256':digest(path.read_bytes())})
    require(len({r['path'] for r in records})==len(records),'duplicate graphics source input')
    return records


def semantic_identity(compiler_identity,records):
    kept=[];seen=set()
    for record in records:
        name=record['path']
        require(isinstance(name,str) and not Path(name).is_absolute() and
                '..' not in Path(name).parts and name not in seen,'unsafe/duplicate compiler input')
        require(re.fullmatch('[0-9a-f]{64}',record['sha256']),'invalid compiler source digest')
        seen.add(name)
        if name not in TRANSPORT_INPUTS:kept.append(record)
    require(kept,'missing shader/compiler inputs')
    # Patch/source order is itself a compiler input. Transport-only additions
    # can disappear from this sequence; semantic patches may not be reordered.
    return digest(canonical({'version':VERSION,'compiler':compiler_identity,'sources':kept}))


def verify_build(work):
    work=Path(work).resolve();bundle=work/'bundle'
    result=json.loads((work/'result.json').read_text())
    require(result.get('success') and result.get('actual_abi_compatible') and
            json.loads((work/'abi-check.json').read_text()).get('compatible'),
            'complete actual-ABI native build required for reuse')
    artifacts=result.get('artifacts',{})
    require(artifacts,'native artifact inventory is absent')
    for name,expected in artifacts.items():
        path=bundle/name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and
                path.is_file() and not path.is_symlink() and
                bundle in path.resolve().parents,'unsafe native artifact')
        require(digest(path.read_bytes())==expected,'native artifact changed: '+name)
    return result


def compiler_cache(root,inputs,identity,fingerprint,previous=None):
    records=components(root,inputs);semantic=semantic_identity(identity,records)
    cache_id='redfin-ios16-arm64-'+semantic
    report={'version':VERSION,'input_sha256':fingerprint,'compiler_identity':identity,
            'components':records,'semantic_sha256':semantic,'cache_id':cache_id,
            'reused':False}
    if previous is None:return report
    previous=Path(previous).resolve();native=verify_build(previous)
    prior=json.loads((previous/'compiler-inputs.json').read_text())
    require(prior.get('version')==VERSION and prior.get('input_sha256')==native['input_sha256'],
            'prior compiler provenance differs from the native build')
    require(prior.get('compiler_identity')==identity,'compiler/toolchain/options changed; shader cache reuse refused')
    require(semantic_identity(identity,prior['components'])==semantic,
            'shader/compiler/serialization input changed; shader cache reuse refused')
    cache_id=prior['cache_id']
    require(bool(re.fullmatch('redfin-ios16-arm64-[0-9a-f]{64}',cache_id)),
            'invalid native shader cache identity')
    source=previous/'mesa-25.0.7'
    require((source/'.redfin-graphics').read_text().strip()==native['input_sha256'],
            'prior native source stamp differs')
    expected='#define REDFIN_MESA_CACHE_BUILD_ID '+json.dumps(cache_id)+'\n'
    require((source/'src/util/redfin_mesa_cache_build.h').read_text()==expected,
            'prior native cache marker differs')
    report.update(cache_id=cache_id,reused=True,reused_from=str(previous),
                  verified_prior_artifacts=True,full_binary_pairing_preserved=True)
    return report


def atomic_write(path,data):
    path=Path(path);temporary=path.with_name(path.name+'.policy-partial')
    require(not temporary.exists(),'unfinished native policy write')
    temporary.write_bytes(data);temporary.replace(path)


def startup_policy(work,enabled):
    """Keep exact existing native binaries; change only diagnostic job policy."""
    from ports.redfin import gpu_userland,metal_userland
    require(type(enabled) is bool,'startup policy must be boolean')
    work=Path(work).resolve();bundle=work/'bundle';result=verify_build(work)
    paths=[gpu_userland.JOB_PATH];jobs=[gpu_userland.job(enabled)]
    metal_path=bundle/'metal-build.json';metal=None
    if metal_path.exists():
        metal_userland.inventory(bundle)
        metal=json.loads(metal_path.read_text());paths.append(metal_userland.JOB_PATH)
        jobs.append(metal_userland.job(enabled))
    previous_jobs=[plistlib.loads((bundle/p.lstrip('/')).read_bytes()) for p in paths]
    for previous,wanted in zip(previous_jobs,jobs):
        # The fast path cannot silently apply a newer program/environment
        # recipe to an older native executable. Only these two policy keys
        # may differ from the reviewed diagnostic identity.
        normalize=lambda job:{k:v for k,v in job.items() if k not in ('Disabled','RunAtLoad')}
        require(normalize(previous)==normalize(wanted),'diagnostic recipe changed; policy-only reuse refused')
    if result.get('startup_checks_enabled')==enabled and all(
            previous==j for previous,j in zip(previous_jobs,jobs)):
        return result
    changes={bundle/p.lstrip('/'):plistlib.dumps(j,fmt=plistlib.FMT_BINARY,sort_keys=False)
             for p,j in zip(paths,jobs)}
    if metal is not None:
        metal['startup_checks_enabled']=enabled
        metal['files'][metal_userland.JOB_PATH]['sha256']=digest(changes[bundle/metal_userland.JOB_PATH.lstrip('/')])
        changes[metal_path]=(json.dumps(metal,indent=2)+'\n').encode()
    allowed={str(p.relative_to(bundle)) for p in changes}
    require(allowed<=set(result['artifacts']),'startup artifacts missing from original inventory')
    evidence=work/('policy-evidence-'+str(time.time_ns()));evidence.mkdir()
    (evidence/'result.json').write_bytes((work/'result.json').read_bytes())
    (evidence/'abi-check.json').write_bytes((work/'abi-check.json').read_bytes())
    for path in changes:
        relative=path.relative_to(bundle);backup=evidence/relative
        backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(path.read_bytes())
    for path,data in changes.items():atomic_write(path,data)
    for name,expected in result['artifacts'].items():
        actual=digest((bundle/name).read_bytes())
        require(name in allowed or actual==expected,'unrelated native binary changed during policy update')
        result['artifacts'][name]=actual
    result.update(startup_checks_enabled=enabled,policy_only_update={
        'source_evidence':str(evidence),'native_recompiled':False,
        'compiler_identity_unchanged':True,'changed_artifacts':sorted(allowed)})
    atomic_write(work/'result.json',(json.dumps(result,indent=2)+'\n').encode())
    verify_build(work)
    if metal is not None:metal_userland.inventory(bundle)
    return result
