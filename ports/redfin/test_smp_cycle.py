"""The temporary recovery cycle accepts SMP only through its compiled shim profile."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_cycle import cycle

ARGS = ('debug=0xc serial=3 cpus=2 keepsyms=1 -noprogress rd=md0 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 '
        'redfinbootid=0x123456789abcdef0')


class SMPCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.image = self.directory / 'redfin-xnu.img'
        self.image.write_bytes(b'synthetic boot image for host policy only')
        self.config = self.directory / 'config.h'
        self.config.write_bytes(b'#define SHIM_EARLY_RETURN 1\n#define REDFIN_SMP_PROBE 1\n')
        self.manifest = dict(smp_probe=True, shim_early_return=True, root_device='md0',
            root_writable=False, cpu_copy_display=False, capture_screen=False,
            userspace_stacks=False, syscall_tracing=False, splash_reservation_assumption=False,
            shutdown_seconds=0, boot_args=ARGS, sha256={
                'redfin-xnu.img': hashlib.sha256(self.image.read_bytes()).hexdigest(),
                'config.h': hashlib.sha256(self.config.read_bytes()).hexdigest()})

    def verify(self):
        (self.directory / 'manifest.json').write_text(json.dumps(self.manifest))
        return cycle.xnu_return_proof(self.image)

    def test_exact_profile_with_or_without_trace(self):
        for trace in ('', ' -enable_kprintf_spam'):
            self.manifest['boot_args'] = ARGS + trace
            proof = self.verify()
            self.assertEqual(proof['cpus'], 2)
            self.assertEqual(proof['armed_by'], 'shim')
            self.assertEqual(proof['boot_id'], '123456789abcdef0')

    def test_every_required_word_is_unique_and_cannot_be_changed_or_removed(self):
        for token in ARGS.split():
            for replacement in ('', token + 'x'):
                self.manifest['boot_args'] = ARGS.replace(token, replacement)
                with self.subTest(token=token, replacement=replacement), self.assertRaises(ValueError):
                    self.verify()
            self.manifest['boot_args'] = ARGS + ' ' + token
            with self.subTest(duplicate=token), self.assertRaises(ValueError):
                self.verify()

    def test_writers_whitespace_and_malformed_nonce_fail(self):
        for extra in ('redfincpu=1', 'redfinusb=0', 'redfinroot=1', 'redfinearlyreturn=1',
                      'redfinreturn=1', 'rd=ufsroot0', 'redfinbootid', '-enable_kprintf_spam -enable_kprintf_spam'):
            self.manifest['boot_args'] = ARGS + ' ' + extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.verify()
        for value in ('0x0000000000000000', '0x123456789abcdeF0', '0x123456789abcdef00'):
            self.manifest['boot_args'] = ARGS.replace('0x123456789abcdef0', value)
            with self.assertRaises(ValueError):
                self.verify()
        self.manifest['boot_args'] = ARGS.replace(' ', '\t', 1)
        with self.assertRaises(ValueError):
            self.verify()

    def test_root_gui_and_nonboolean_proof_fields_fail(self):
        for key in ('smp_probe', 'shim_early_return', 'root_writable', 'cpu_copy_display',
                    'capture_screen', 'userspace_stacks', 'syscall_tracing', 'splash_reservation_assumption'):
            old = self.manifest[key]
            for value in (None, 1, 0, not old):
                self.manifest[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.verify()
            self.manifest[key] = old
        for key, value in (('root_device', 'ufsroot0'), ('shutdown_seconds', 120), ('shutdown_seconds', False)):
            old = self.manifest[key]
            self.manifest[key] = value
            with self.assertRaises(ValueError):
                self.verify()
            self.manifest[key] = old

    def test_configuration_and_image_hashes_are_bound(self):
        original = self.config.read_bytes()
        for config in (b'', original.replace(b'SHIM_EARLY_RETURN 1', b'SHIM_EARLY_RETURN 0'),
                       original.replace(b'REDFIN_SMP_PROBE 1', b'REDFIN_SMP_PROBE 0'),
                       original + b'#define SHIM_EARLY_RETURN 1\n', original + b'\0'):
            self.config.write_bytes(config)
            self.manifest['sha256']['config.h'] = hashlib.sha256(config).hexdigest()
            with self.assertRaises(ValueError):
                self.verify()
        self.config.write_bytes(original)
        self.manifest['sha256']['config.h'] = '0' * 64
        with self.assertRaises(ValueError):
            self.verify()
        self.manifest['sha256']['config.h'] = hashlib.sha256(original).hexdigest()
        self.image.write_bytes(b'modified image')
        with self.assertRaises(ValueError):
            self.verify()

    def test_eight_cpus_need_matching_args_manifest_and_compiled_count(self):
        original = self.config.read_bytes()
        self.manifest['boot_args'] = ARGS.replace('cpus=2', 'cpus=8')
        self.manifest['smp_cpus'] = 8
        for config in (original, original + b'#define REDFIN_SMP_CPUS 2\n'):
            self.config.write_bytes(config)
            self.manifest['sha256']['config.h'] = hashlib.sha256(config).hexdigest()
            with self.assertRaises(ValueError):
                self.verify()
        config = original + b'#define REDFIN_SMP_CPUS 8\n'
        self.config.write_bytes(config)
        self.manifest['sha256']['config.h'] = hashlib.sha256(config).hexdigest()
        self.assertEqual(self.verify()['cpus'], 8)
        self.manifest['boot_args'] = ARGS
        with self.assertRaises(ValueError):
            self.verify()
        self.manifest['boot_args'] = ARGS.replace('cpus=2', 'cpus=8')
        for count in (None, True, 0, 2, 7, 16, '8'):
            self.manifest['smp_cpus'] = count
            with self.assertRaises(ValueError):
                self.verify()


if __name__ == '__main__':
    unittest.main()
