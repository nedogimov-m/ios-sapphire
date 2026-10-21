"""Rootless edits must keep source owners, moved paths and generated metadata."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / 'tools/sweet-root-tweaks.py'
spec = importlib.util.spec_from_file_location('root_tweaks', SCRIPT)
tweaks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tweaks)


class DeferredOwnershipTests(unittest.TestCase):
    def test_absolute_image_symlink_cannot_write_to_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, outside = Path(temporary) / 'root', Path(temporary) / 'host'
            root.mkdir()
            outside.mkdir()
            (root / 'escape').symlink_to(outside, target_is_directory=True)
            editor = tweaks.RootEditor(root, {})
            with self.assertRaises(ValueError):
                tweaks.save(root / 'escape/output.plist', {'key': 1}, 0, 0, 0o644, editor=editor)
            self.assertFalse((outside / 'output.plist').exists())
            with self.assertRaises(ValueError):
                editor.mkdir(root / 'escape/child')
            self.assertFalse((outside / 'child').exists())

    def test_full_edits_preserve_true_owners_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def plist(relative, value):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(plistlib.dumps(value))
                return path
            launchd = plist('System/Library/xpc/launchd.plist', {'LaunchDaemons': {
                'one': {'Label': 'test', '_PanicOnCrash': True},
                'two': {'Label': 'com.apple.CommCenter'}}})
            config = plist('System/Library/Frameworks/MediaToolbox.framework/A/SubServerConfiguration.plist',
                           {'StartRecorderServer': True})
            plugin = root / 'Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin/Contents'
            plugin.mkdir(parents=True)
            (plugin / 'payload').write_bytes(b'plugin')
            plist('private/var/containers/Data/System/ABC/.com.apple.mobile_container_manager.metadata.plist',
                  {'MCMMetadataIdentifier': 'com.apple.mobileactivationd'})
            metadata = {}
            for directory, folders, files in os.walk(root):
                for name in folders + files:
                    path = Path(directory) / name
                    metadata[str(path.relative_to(root))] = {
                        'uid': 0, 'gid': 80, 'mode': 0o755 if path.is_dir() else 0o640,
                        'kind': stat.S_IFMT(path.lstat().st_mode)}
            # A native owners-off staging mount reports the host UID. The map is
            # the authority, including unusual original owner/group/mode values.
            metadata[str(config.relative_to(root))].update(uid=123, gid=456, mode=0o444)
            with mock.patch.object(tweaks.os, 'chown', side_effect=AssertionError('host chown')), \
                    contextlib.redirect_stdout(io.StringIO()):
                tweaks.apply(root, metadata)
                first = {key: dict(value) for key, value in metadata.items()}
                tweaks.apply(root, metadata)
            self.assertEqual(first, metadata)
            jobs = plistlib.loads(launchd.read_bytes())['LaunchDaemons']
            self.assertEqual(jobs, {'one': {'Label': 'test', '_PanicOnCrasX': True}})
            self.assertFalse(plistlib.loads(config.read_bytes())['StartRecorderServer'])
            self.assertEqual(metadata[str(config.relative_to(root))],
                             {'uid': 123, 'gid': 456, 'mode': 0o444, 'kind': stat.S_IFREG})
            old = 'Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin'
            new = 'Library/Audio/Plug-Ins/HAL.disabled/VirtualAudio.plugin'
            self.assertFalse(any(key == old or key.startswith(old + '/') for key in metadata))
            self.assertEqual((root / new / 'Contents/payload').read_bytes(), b'plugin')
            self.assertEqual(metadata[new + '/Contents/payload']['gid'], 80)
            self.assertEqual(metadata['private/var/containers/Bundle']['uid'], 33)
            self.assertEqual(metadata['private/var/mobile/Library/Preferences/com.apple.springboard.plist'],
                             {'uid': 501, 'gid': 501, 'mode': 0o600, 'kind': stat.S_IFREG})
            ark = 'private/var/containers/Data/System/ABC/Library/internal/data_ark.plist'
            self.assertEqual(metadata[ark]['uid'], 501)
            self.assertEqual(plistlib.loads((root / ark).read_bytes())['-ActivationState'], 'Activated')
            # Every generated directory and file must have final catalog metadata.
            for directory, folders, files in os.walk(root):
                for name in folders + files:
                    self.assertIn(str((Path(directory) / name).relative_to(root)), metadata)


if __name__ == '__main__':
    unittest.main()
