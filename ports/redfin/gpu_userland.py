"""Install the complete opt-in graphics startup policy in the existing cache.

Preferred upstream mkjobs.py bootstrap semantics, adapted to the current
20H392 cache. The job's program checks GUI3 before opening a GPU connection;
the already working GUI1/2 boots skip it. No device access or root write here.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib

from ports.redfin.wifi_userland import _encode_same_size

LABEL='com.redfin.gpu-render'
JOB_PATH='/System/Library/LaunchDaemons/com.redfin.gpu-render.plist'
OLD_JOB_PATH='/Library/LaunchDaemons/com.redfin.gpu-render.plist'
BACKBOARD_PATH='/System/Library/LaunchDaemons/com.apple.backboardd.plist'
LOADER='/redfin/lib/libredfin-graphics.dylib'


def backboardd_job(original):
    """Preserve the stock event server; insert only our GUI3-gated loader."""
    services=original.get('MachServices')
    if (original.get('Label')!='com.apple.backboardd' or
        original.get('ProgramArguments')!=['/usr/libexec/backboardd'] or 'Program' in original or
        original.get('RunAtLoad') is not True or original.get('KeepAlive') is not True or
        original.get('UserName')!='mobile' or original.get('POSIXSpawnType')!='Interactive' or
        not isinstance(services,dict) or 'com.apple.CARenderServer' not in services or
        'PurpleSystemEventPort' not in services):
        raise ValueError('unexpected backboardd program, event server or startup identity')
    job=copy.deepcopy(original)
    env=dict(job.get('EnvironmentVariables',{}))
    if env.get('DYLD_INSERT_LIBRARIES',LOADER)!=LOADER:
        raise ValueError('backboardd already has an unrelated inserted library')
    env['DYLD_INSERT_LIBRARIES']=LOADER
    job['EnvironmentVariables']=env
    for key in ('StandardOutPath','StandardErrorPath'):
        if job.get(key,'/dev/console')!='/dev/console':
            raise ValueError('backboardd already has a different console destination')
        job[key]='/dev/console'
    return job


def patch_launchd_cache(original,system_eagl=False):
    if not isinstance(original,bytes) or not original.startswith(b'bplist00') or not 40<=len(original)<=0x1000000:
        raise ValueError('GPU diagnostic requires the current bounded binary launchd cache')
    cache=plistlib.loads(original)
    jobs=cache.get('LaunchDaemons') if isinstance(cache,dict) else None
    if not isinstance(jobs,dict) or any(not isinstance(job,dict) for job in jobs.values()):
        raise ValueError('GPU diagnostic requires a LaunchDaemons dictionary')
    job=plistlib.loads(Path(__file__).with_name('gpu-render-job.plist').read_bytes())
    if job.get('Label')!=LABEL or job.get('ProgramArguments')!=['/redfin/bin/gpu-render']:
        raise ValueError('unexpected GPU diagnostic startup identity')
    found=[(key,value) for key,value in jobs.items() if value.get('Label')==LABEL]
    before=hashlib.sha256(original).hexdigest()
    if len(found)>1 or (found and (found[0][0] not in (JOB_PATH,OLD_JOB_PATH) or found[0][1]!=job)):
        raise ValueError('refusing an existing conflicting GPU job')
    if JOB_PATH in jobs and (not found or found[0][0]!=JOB_PATH):
        raise ValueError('GPU job path already belongs to a different daemon')
    expected=copy.deepcopy(cache)
    migrated=bool(found and found[0][0]==OLD_JOB_PATH)
    if migrated:del expected['LaunchDaemons'][OLD_JOB_PATH]
    expected['LaunchDaemons'][JOB_PATH]=job
    allowed={JOB_PATH,OLD_JOB_PATH}
    if system_eagl:
        backboards=[key for key,value in jobs.items() if value.get('Label')=='com.apple.backboardd']
        if backboards!=[BACKBOARD_PATH]:raise ValueError('expected exactly one stock System backboardd job')
        expected['LaunchDaemons'][BACKBOARD_PATH]=backboardd_job(jobs[BACKBOARD_PATH])
        allowed.add(BACKBOARD_PATH)
    common=dict(label=LABEL,job_key=JOB_PATH,system_eagl=system_eagl,migrated_from=OLD_JOB_PATH if migrated else None,
        bytes=len(original),before_sha256=before,root_writes=False)
    if expected==cache:
        return original,dict(common,changed=False,after_sha256=before)
    result,padding=_encode_same_size(expected,len(original),compact=True)
    decoded=plistlib.loads(result)
    original_other=copy.deepcopy(cache);changed_other=copy.deepcopy(decoded)
    for obj in (original_other,changed_other):
        obj['LaunchDaemons']={key:value for key,value in obj['LaunchDaemons'].items() if key not in allowed}
    if changed_other!=original_other:raise ValueError('GPU policy changed an unrelated startup dictionary')
    return result,dict(common,changed=True,padding_bytes=padding,
        after_sha256=hashlib.sha256(result).hexdigest(),preserved_jobs=len(original_other['LaunchDaemons']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--system-eagl',action='store_true')
    args=parser.parse_args()
    data,report=patch_launchd_cache(args.input.read_bytes(),args.system_eagl)
    with args.output.open('xb') as stream:stream.write(data)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
