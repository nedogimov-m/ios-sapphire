"""The native bootstrap adds one job and preserves user photo files/logs."""
import copy
import hashlib
from pathlib import Path
import json
import plistlib
import stat
import tempfile
import unittest

from ports.redfin import photos_userland as photos
from ports.redfin.wifi_userland import _encode_same_size


def cache():
    value = {'LaunchDaemons': {'stock': {'Label': 'stock', 'Program': '/stock',
             'MachServices': {'stock.service': True}}}, 'Keep': b'preserve'}
    raw = plistlib.dumps(value, fmt=plistlib.FMT_BINARY)
    return _encode_same_size(value, len(raw) + 4096)[0]


class PhotoBootstrapTests(unittest.TestCase):
    def test_same_size_cache_adds_only_the_bootstrap_and_is_idempotent(self):
        original = cache()
        patched, report = photos.patch_launchd_cache(original)
        self.assertEqual(len(patched), len(original))
        decoded = plistlib.loads(patched)
        self.assertEqual(decoded['LaunchDaemons'].pop(photos.JOB_PATH), photos.job())
        self.assertEqual(decoded, plistlib.loads(original))
        self.assertTrue(report['changed'])
        self.assertEqual(photos.patch_launchd_cache(patched)[0], patched)
        self.assertFalse(photos.patch_launchd_cache(patched)[1]['changed'])

    def test_conflicting_job_identity_is_refused(self):
        for jobs in ({'different': dict(photos.job(), ProgramArguments=['/another'])},
                     {photos.JOB_PATH: {'Label': 'somebody-else'}}):
            with self.assertRaises(ValueError):
                photos.patch_launchd_cache(plistlib.dumps({'LaunchDaemons': jobs, 'Keep': bytes(8192)},
                                                         fmt=plistlib.FMT_BINARY))

    def test_staging_keeps_existing_library_and_log_and_defers_native_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root, bundle = Path(directory) / 'root', Path(directory) / 'bundle'
            bundle.mkdir(); root.mkdir()
            payloads = {'photos-init': b'fixture program', 'job.plist': plistlib.dumps(photos.job()),
                        'log-initial': b'initial log\n'}
            for name, value in payloads.items():
                (bundle / name).write_bytes(value)
            (bundle / 'build.json').write_text(json.dumps(dict(success=True, native_schema_only=True,
                sha256={name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()})))
            native_cache = root / 'System/Library/xpc/launchd.plist'
            native_cache.parent.mkdir(parents=True); native_cache.write_bytes(cache())
            database = root / 'private/var/mobile/Media/PhotoData/Photos.sqlite'
            database.parent.mkdir(parents=True); database.write_bytes(b'existing user library must stay intact')
            log = root / photos.LOG_PATH.lstrip('/')
            log.parent.mkdir(parents=True); log.write_bytes(b'previous boot log\n')
            metadata = {}
            photos.prepare_root(root, metadata, bundle)
            photos.prepare_root(root, metadata, bundle)
            self.assertEqual(database.read_bytes(), b'existing user library must stay intact')
            self.assertEqual(log.read_bytes(), b'previous boot log\n')
            self.assertEqual(metadata[str(log.relative_to(root))], dict(uid=501, gid=501, mode=0o644, kind=stat.S_IFREG))
            program = root / photos.PROGRAM.lstrip('/')
            self.assertEqual(program.read_bytes(), payloads['photos-init'])
            self.assertEqual(metadata[str(program.relative_to(root))]['mode'], 0o755)


if __name__ == '__main__':
    unittest.main()
