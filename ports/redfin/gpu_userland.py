"""Add the bounded GPU rendering diagnostic to the existing launchd cache.

Preferred upstream mkjobs.py bootstrap semantics, adapted to the current
20H392 cache. The job's program checks GUI3 before opening a GPU connection;
the already working GUI1/2 boots skip it. No device access or root write here.
"""
import copy
import hashlib
from pathlib import Path
import plistlib

from ports.redfin.wifi_userland import _encode_same_size

LABEL='com.redfin.gpu-render'
JOB_PATH='/Library/LaunchDaemons/com.redfin.gpu-render.plist'


def patch_launchd_cache(original):
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
    if found:
        if found!=[(JOB_PATH,job)]:raise ValueError('refusing an existing conflicting GPU job')
        return original,dict(changed=False,before_sha256=before,after_sha256=before,label=LABEL)
    if JOB_PATH in jobs:raise ValueError('GPU job path already belongs to a different daemon')
    expected=copy.deepcopy(cache);expected['LaunchDaemons'][JOB_PATH]=job
    result,padding=_encode_same_size(expected,len(original),compact=True)
    decoded=plistlib.loads(result);remaining=dict(decoded['LaunchDaemons']);del remaining[JOB_PATH]
    if remaining!=jobs:raise ValueError('GPU job changed an unrelated startup dictionary')
    return result,dict(changed=True,label=LABEL,job_key=JOB_PATH,bytes=len(result),padding_bytes=padding,
        before_sha256=before,after_sha256=hashlib.sha256(result).hexdigest(),preserved_jobs=len(jobs),
        root_writes=False)
