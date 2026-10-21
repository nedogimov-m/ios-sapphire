"""Host-only recovery fallback tests; generated tiny boot-v3 fixtures."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('redfin_recovery', Path(__file__).with_name('build-recovery.py'))
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


def vendor_entries():
    names = ('system/bin/recovery', 'system/bin/init', 'system/bin/adbd', 'system/bin/sh',
             'system/bin/toybox', 'system/bin/toolbox', 'system/bin/sleep', 'system/bin/setprop',
             'lib/modules/modules.load', 'sepolicy', 'init.recovery.redfin.rc')
    result = {name: RECOVERY.file_entry(b'fixture') for name in names}
    result['prop.default'] = RECOVERY.file_entry(b'ro.secure=1\nro.redfin.return_target=stale\n')
    result['system/etc/init/hw/init.rc'] = RECOVERY.file_entry(
        b'on boot\n    class_start default\n    class_start hal\n'
        b'service recovery /system/bin/recovery\n    user root\n')
    return result


class RecoveryTests(unittest.TestCase):
    def test_default_android_and_bootloader_rc_properties(self):
        for target in ('android', 'bootloader'):
            tree = RECOVERY.recovery_tree(vendor_entries(), target)
            rc = tree['system/etc/init/hw/init.rc'][1].decode()
            props = tree['prop.default'][1].decode()
            command = 'reboot' if target == 'android' else 'reboot,bootloader'
            self.assertIn(f'/system/bin/sleep 120; /system/bin/setprop sys.powerctl {command}"', rc)
            self.assertIn(f'ro.redfin.return_target={target}\n', props)
            self.assertNotIn('ro.redfin.return_target=stale', props)
            self.assertIn('service recovery /system/bin/recovery\n    disabled\n', rc)
            self.assertIn('start recovery-return', rc)
        self.assertEqual(RECOVERY.recovery_properties()['ro.redfin.return_target'], 'android')
        with self.assertRaises(ValueError):
            RECOVERY.recovery_tree(vendor_entries(), 'untrusted,target')

    @unittest.skipUnless(shutil.which('lz4'), 'lz4 required for boot-image fixture')
    def test_manifest_and_both_cpio_roots_match_selected_target(self):
        def compress(data):
            return subprocess.run(['lz4', '-l', '-c'], input=data, capture_output=True, check=True).stdout
        generic = compress(RECOVERY.archive({'init': RECOVERY.file_entry(b'generic-init')}))
        vendor = compress(RECOVERY.archive(vendor_entries()))
        header = bytearray(4096)
        header[:8] = b'ANDROID!'
        struct.pack_into('<9I', header, 8, 4, len(generic), 0x200001, 1580, 0, 0, 0, 0, 3)
        boot = bytes(header) + b'KERN' + bytes(4092) + generic + bytes(-len(generic) % 4096)
        vendor_header = bytearray(4096)
        vendor_header[:8] = b'VNDRBOOT'
        struct.pack_into('<II', vendor_header, 8, 3, 4096)
        struct.pack_into('<I', vendor_header, 24, len(vendor))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'boot.img').write_bytes(boot)
            (root/'vendor.img').write_bytes(bytes(vendor_header) + vendor)
            for target in ('android', 'bootloader'):
                output = root/target
                args = ['--boot', str(root/'boot.img'), '--vendor-boot', str(root/'vendor.img'), '--out', str(output)]
                if target != 'android':
                    args += ['--return-target', target]
                with contextlib.redirect_stdout(io.StringIO()):
                    RECOVERY.main(args)
                manifest = json.loads((output/'manifest.json').read_text())
                self.assertEqual(manifest['return_target'], target)
                self.assertEqual(manifest['return_after_seconds'], 120)
                self.assertEqual(manifest['properties']['ro.redfin.return_target'], target)
                self.assertEqual('return_to_android_seconds' in manifest, target == 'android')
                image = (output/'recovery-adb-only.img').read_bytes()
                kernel, ramdisk = struct.unpack_from('<II', image, 8)
                start = 4096 + RECOVERY.align(kernel)
                entries = RECOVERY.records(RECOVERY.decompress(image[start:start+ramdisk]))
                for prefix in ('', 'first_stage_ramdisk/'):
                    self.assertIn(f'ro.redfin.return_target={target}\n'.encode(), entries[prefix+'prop.default'][1])
                    command = b'reboot"' if target == 'android' else b'reboot,bootloader"'
                    self.assertIn(b'sys.powerctl '+command, entries[prefix+'system/etc/init/hw/init.rc'][1])


if __name__ == '__main__':
    unittest.main()
