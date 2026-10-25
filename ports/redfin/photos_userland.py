"""Build/provision native first-library initialization; no device access here."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from ports.redfin.graphics_abi import Cache
from ports.redfin.wifi_userland import _encode_same_size

LABEL = 'com.redfin.photos-init'
PROGRAM = '/redfin/bin/photos-init'
JOB_PATH = '/System/Library/LaunchDaemons/' + LABEL + '.plist'
LOG_PATH = '/private/var/mobile/Library/Logs/redfin-photos-init.log'
ENTITLEMENTS = {'application-identifier': LABEL, 'platform-application': True,
                'keychain-access-groups': [LABEL],
                'com.apple.private.memorystatus': True,
                'com.apple.private.tcc.allow': ['kTCCServicePhotos'],
                'com.apple.photos.bourgeoisie': True,
                'com.apple.private.security.storage.Photos': True,
                'com.apple.private.security.storage.PhotosLibraries': True}
METHODS = {
    '/System/Library/Frameworks/Photos.framework/Photos': ('PHPhotoLibrary', {
        '+systemPhotoLibraryURL': '@16@0:8',
        '+createOrUpgradePhotoLibraryWithWellKnownIdentifier:error:': 'B32@0:8q16^@24',
        '+openPhotoLibraryWithWellKnownIdentifier:error:': '@32@0:8q16^@24',
        '-initWithPhotoLibraryURL:':'@24@0:8@16',
        '-createOrUpgradeLibraryUsingOptions:error:':'B32@0:8@16^@24'}),
    '/System/Library/PrivateFrameworks/PhotoLibraryServicesCore.framework/PhotoLibraryServicesCore':
        ('PLPhotoLibraryPathManager', {'+isSystemPhotoLibraryURL:': 'B24@0:8@16',
            '+wellKnownPhotoLibraryIdentifierForURL:': 'q24@0:8@16'})}


def job():
    return {'Label': LABEL, 'ProgramArguments': [PROGRAM], 'RunAtLoad': True,
            'KeepAlive': False, 'UserName': 'mobile', 'ProcessType': 'Background',
            'StandardOutPath': LOG_PATH, 'StandardErrorPath': LOG_PATH,
            'EnvironmentVariables': {'OS_ACTIVITY_DT_MODE': 'YES'},
            'JetsamProperties': {'ActiveHardMemoryLimit': 512, 'InactiveHardMemoryLimit': 512}}


def patch_launchd_cache(original):
    if not isinstance(original, bytes) or not original.startswith(b'bplist00') or not 40 <= len(original) <= 16 * 1024**2:
        raise ValueError('expected the bounded native launchd cache')
    cache = plistlib.loads(original)
    jobs = cache.get('LaunchDaemons') if isinstance(cache, dict) else None
    if not isinstance(jobs, dict) or any(not isinstance(value, dict) for value in jobs.values()):
        raise ValueError('expected native LaunchDaemons')
    found = [(key, value) for key, value in jobs.items() if value.get('Label') == LABEL]
    expected_job = job()
    if found and found != [(JOB_PATH, expected_job)]:
        raise ValueError('conflicting photo initializer job')
    if JOB_PATH in jobs and not found:
        raise ValueError('photo initializer path belongs to another job')
    expected = copy.deepcopy(cache)
    expected['LaunchDaemons'][JOB_PATH] = expected_job
    report = {'label': LABEL, 'before_sha256': hashlib.sha256(original).hexdigest(),
              'bytes': len(original), 'preserved_jobs': len(jobs) - bool(found)}
    if expected == cache:
        return original, dict(report, changed=False, after_sha256=report['before_sha256'])
    encoded, padding = _encode_same_size(expected, len(original), compact=True)
    other = plistlib.loads(encoded)
    del other['LaunchDaemons'][JOB_PATH]
    before_other = copy.deepcopy(cache)
    before_other['LaunchDaemons'].pop(JOB_PATH, None)
    if other != before_other:
        raise ValueError('photo initializer changed unrelated launchd jobs')
    return encoded, dict(report, changed=True, padding_bytes=padding,
                         after_sha256=hashlib.sha256(encoded).hexdigest())


def build(out, cache_path=None):
    out = Path(out).resolve()
    if (ROOT / 'research').resolve() not in out.parents:
        raise ValueError('native bootstrap artifacts must stay under ignored research')
    out.mkdir(parents=True, exist_ok=False)
    abi = {}
    with (Cache(cache_path) if cache_path is not None else Cache()) as cache:
        for path, (name, wanted) in METHODS.items():
            image = cache.image(path)
            actual = image.objc_methods(name)
            if any(key not in actual or actual[key]['types'] != value for key, value in wanted.items()):
                raise ValueError('native photo-library ABI differs: ' + name)
            abi[path] = {'uuid': image.uuid, 'class': name, 'methods': wanted}
        for path,wanted in [('/System/Library/Frameworks/Security.framework/Security',
            ['_SecTaskCreateFromSelf','_SecTaskCopyValueForEntitlement','_SecTaskGetCodeSignStatus']),
            ('/System/Library/PrivateFrameworks/TCC.framework/TCC',['_tcc_authorization_preflight'])]:
            image=cache.image(path);exports,_=image.exports()
            if any(not exports.get(name) for name in wanted):raise ValueError('native authorization API unavailable')
            abi[path]={'uuid':image.uuid,'exports':wanted}
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    executable = out / 'photos-init'
    command = ['xcrun', '--sdk', 'iphoneos', 'clang', '-arch', 'arm64', '-isysroot', sdk,
               '-miphoneos-version-min=16.0', '-O2', '-fblocks', '-Wall', '-Wextra', '-Werror',
               '-Wno-deprecated-declarations', '-I', str(HERE), str(HERE / 'photos-init.m'),str(HERE/'native-tcc-probe.m'),
               '-framework', 'Foundation', '-framework', 'Photos', '-framework', 'Security', '-o', str(executable)]
    with (out / 'build.log').open('wb') as log:
        subprocess.run(command, check=True, stdout=log, stderr=log)
        entitlements = out / 'photos-init.entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', LABEL, '--timestamp=none',
                        '--entitlements', str(entitlements), str(executable)], check=True, stdout=log, stderr=log)
        subprocess.run(['codesign', '--verify', '--strict', str(executable)], check=True, stdout=log, stderr=log)
    (out / 'job.plist').write_bytes(plistlib.dumps(job(), fmt=plistlib.FMT_BINARY, sort_keys=False))
    (out / 'log-initial').write_bytes(b'REDFIN native photo-library initializer; per-boot results follow.\n')
    report = {'success': True, 'abi': abi, 'source_sha256': hashlib.sha256((HERE / 'photos-init.m').read_bytes()).hexdigest(),
              'sha256': {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                         for name in ('photos-init', 'job.plist', 'log-initial')},
              'native_schema_only': True, 'apple_activation_claimed': False}
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def prepare_root(root, metadata, bundle):
    root, bundle = Path(root).resolve(), Path(bundle).resolve()
    report = json.loads((bundle / 'build.json').read_text())
    if not report.get('success') or not report.get('native_schema_only'):
        raise ValueError('verified native photo bootstrap bundle required')
    for name, target, uid, mode in [('photos-init', PROGRAM, 0, 0o755),
                                   ('job.plist', JOB_PATH, 0, 0o644),
                                   ('log-initial', LOG_PATH, 501, 0o644)]:
        source, destination = bundle / name, root / target.lstrip('/')
        if hashlib.sha256(source.read_bytes()).hexdigest() != report['sha256'][name]:
            raise ValueError('native photo bootstrap bundle changed')
        if destination.is_symlink() or root not in destination.resolve().parents:
            raise ValueError('photo bootstrap path escapes staging root')
        if destination.exists() and not destination.is_file():
            raise ValueError('photo bootstrap destination is not a regular file')
        missing = []
        parent = destination.parent
        while not parent.exists():
            missing.append(parent); parent = parent.parent
        for parent in reversed(missing):
            parent.mkdir()
            relative = str(parent.relative_to(root))
            owner = 501 if relative == 'private/var/mobile' or relative.startswith('private/var/mobile/') else 0
            metadata[relative] = dict(uid=owner, gid=owner, mode=0o755, kind=stat.S_IFDIR)
        if name != 'log-initial' and destination.exists() and destination.read_bytes() != source.read_bytes():
            raise ValueError('conflicting photo bootstrap file')
        if not destination.exists():
            shutil.copyfile(source, destination)
        if not destination.is_file():
            raise ValueError('photo bootstrap destination is not a file')
        metadata[str(destination.relative_to(root))] = dict(uid=uid, gid=uid, mode=mode, kind=stat.S_IFREG)
    path = root / 'System/Library/xpc/launchd.plist'
    if path.is_symlink() or root not in path.resolve().parents:
        raise ValueError('native launchd cache escapes staging root')
    original = path.read_bytes()
    encoded, patched = patch_launchd_cache(original)
    with path.open('r+b') as stream:
        if stream.write(encoded) != len(encoded):
            raise OSError('short native photo bootstrap cache write')
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(0)
        if stream.read() != encoded:
            raise OSError('native photo bootstrap cache readback differs')
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    report = build(args.out, args.cache)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
