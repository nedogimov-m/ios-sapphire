"""Check the native cache's dictionary, timestamp and deferred ownership."""
import os
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest

import checkpoint_userland as checkpoint


class CheckpointTests(unittest.TestCase):
    def test_cache_keeps_stock_dictionary_and_destination_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root, metadata = Path(directory), {}
            source = root / checkpoint.SOURCE
            source.parent.mkdir(parents=True)
            value = {"ImageSpecifications": ["901", {"FormatId": 901, "RenderWidth": 132}],
                     "AlbumArt": ["300", {"RenderWidth": 100}], "StockExtra": [1, True, "kept"]}
            original = plistlib.dumps(value)
            source.write_bytes(original)
            os.utime(source, ns=(1234000000000, 1700000000123456789))
            report = checkpoint.prepare_root(root, metadata)
            cache = root / checkpoint.CACHE
            self.assertEqual(cache.read_bytes(), original)
            self.assertEqual(plistlib.loads(cache.read_bytes()), value)
            self.assertEqual(cache.stat().st_mtime_ns, source.stat().st_mtime_ns)
            self.assertEqual(report['mtime_ns'], source.stat().st_mtime_ns)
            self.assertEqual(metadata[str(checkpoint.CACHE)],
                             dict(uid=501, gid=501, mode=0o644, kind=stat.S_IFREG))
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(checkpoint.prepare_root(root, metadata)['changed'])

    def test_invalid_source_does_not_create_a_cache(self):
        for value in ([], {}, {"ImageSpecifications": ["901"]},
                      {"ImageSpecifications": ["901", "not a format"]}):
            with self.assertRaises(ValueError):
                checkpoint.cache_payload(plistlib.dumps(value))
        for data in (b'', b'not a plist', bytes(checkpoint.MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                checkpoint.cache_payload(data)

    def test_cache_or_parent_symlink_cannot_write_outside_staging_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root, outside = Path(directory) / 'root', Path(directory) / 'outside'
            source = root / checkpoint.SOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes(plistlib.dumps({"ImageSpecifications": ["901", {}]}))
            outside.mkdir()
            cache = root / checkpoint.CACHE
            cache.parent.mkdir(parents=True)
            target = outside / 'keep'
            target.write_bytes(b'unchanged')
            cache.symlink_to(target)
            with self.assertRaises(ValueError):
                checkpoint.prepare_root(root, {})
            self.assertEqual(target.read_bytes(), b'unchanged')
            cache.unlink()
            cache.parent.rmdir()
            cache.parent.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                checkpoint.prepare_root(root, {})
            self.assertFalse((outside / 'Checkpoint.plist').exists())


if __name__ == '__main__':
    unittest.main()
