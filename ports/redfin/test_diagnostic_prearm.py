"""New UP hardware tests cannot fall back to return armed only inside XNU."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_cycle import cycle

BASE = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfinspmi=1 redfinreturn=1')
NONCE = ' redfinbootid=0x1234567890abcdef'
PROFILES = (
    (dict(gpu_power_probe=True), ' redfingpu=2 redfingpupower=1 redfinrpmh=1'),
    (dict(gpu_power_probe=True, gmu_tcm_probe=True), ' redfingpu=2 redfingpupower=1 redfinrpmh=1 redfingmu=1'),
    (dict(gpu_power_probe=True, gmu_tcm_probe=True, gpu_smmu_probe=True), ' redfingpu=2 redfingpupower=1 redfinrpmh=1 redfingmu=1 redfinsmmu=1'),
    (dict(gpu_power_probe=True, gmu_tcm_probe=True, gpu_smmu_probe=True, gpu_smmu_context_probe=True),
     ' redfingpu=2 redfingpupower=1 redfinrpmh=1 redfingmu=1 redfinsmmu=2'),
    (dict(wifi_native_probe=True), ' redfinwifi=2 redfinwifinative=1'),
    (dict(wifi_native_probe=True, wifi_power_probe=True), ' redfinwifi=2 redfinwifinative=1 redfinwifipower=1'),
    (dict(scm_probe=True), ' redfingpu=3 redfinscm=1'))


class DiagnosticPrearmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.image = self.directory / 'redfin-xnu.img'
        self.image.write_bytes(b'host fixture only')
        self.config = self.directory / 'config.h'
        self.config.write_text('#define SHIM_EARLY_RETURN 1\n#define REDFIN_SMP_PROBE 0\n#define REDFIN_SMP_GUI 0\n')

    def manifest(self, selector, args):
        return dict(**selector, diagnostic_prearm=True, shim_early_return=True,
            root_device='md0', root_writable=False, cpu_copy_display=False,
            capture_screen=False, userspace_stacks=False, syscall_tracing=False,
            splash_reservation_assumption=False, shutdown_seconds=0,
            boot_args=BASE + args + NONCE, sha256={
                'redfin-xnu.img': hashlib.sha256(self.image.read_bytes()).hexdigest(),
                'config.h': hashlib.sha256(self.config.read_bytes()).hexdigest()})

    def verify(self, manifest):
        (self.directory / 'manifest.json').write_text(json.dumps(manifest))
        return cycle.xnu_return_proof(self.image)

    def test_all_profiles_bind_prearm_and_unchanged_kernel_return_check(self):
        for selector, args in PROFILES:
            for trace in ('', ' -enable_kprintf_spam'):
                m = self.manifest(selector, args)
                m['boot_args'] += trace
                result = self.verify(m)
                self.assertEqual((result['cpus'], result['armed_by'], result['kernel_return_check']), (1, 'shim', True))
                self.assertEqual(result['boot_id'], '1234567890abcdef')

    def test_removed_or_disabled_prearm_cannot_use_legacy_up_fallback(self):
        for selector, args in PROFILES:
            for value in (False, None, 0, 1, 'yes'):
                m = self.manifest(selector, args)
                m['diagnostic_prearm'] = value
                with self.assertRaises(ValueError):
                    self.verify(m)
            m = self.manifest(selector, args)
            for key in (*selector.keys(), 'diagnostic_prearm'):
                m.pop(key)
            with self.assertRaises(ValueError):
                self.verify(m)

    def test_missing_changed_duplicate_foreign_tokens_and_nonce_fail(self):
        for selector, args in PROFILES:
            original = self.manifest(selector, args)
            for token in original['boot_args'].split():
                for replacement in ('', token + 'x'):
                    m = original.copy()
                    m['boot_args'] = m['boot_args'].replace(token, replacement)
                    with self.assertRaises(ValueError):
                        self.verify(m)
                m = original.copy()
                m['boot_args'] += ' ' + token
                with self.assertRaises(ValueError):
                    self.verify(m)
            for extra in ('redfinroot=1', 'redfinusb=3', 'redfintouch=2', 'redfinsmp=1', 'redfingui=1'):
                m = original.copy()
                m['boot_args'] += ' ' + extra
                with self.assertRaises(ValueError):
                    self.verify(m)

    def test_writers_mixed_selectors_and_nonboolean_metadata_fail(self):
        m = self.manifest(*PROFILES[0])
        for key in ('root_writable', 'cpu_copy_display', 'capture_screen', 'userspace_stacks',
                    'syscall_tracing', 'splash_reservation_assumption', 'wifi_native_probe', 'scm_probe',
                    'wifi_power_probe', 'gpu_smmu_probe', 'gpu_smmu_context_probe'):
            changed = dict(m, **{key: True})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(changed)
        for key, value in (('gpu_power_probe', 1), ('shim_early_return', 1),
                           ('gpu_smmu_context_probe', 1),
                           ('root_device', 'ufsroot0'), ('shutdown_seconds', False)):
            with self.assertRaises(ValueError):
                self.verify(dict(m, **{key: value}))

    def test_config_checksums_and_rehashed_disabled_or_duplicate_gates_fail(self):
        m = self.manifest(*PROFILES[0])
        original = self.config.read_text()
        for name, value in (('SHIM_EARLY_RETURN', 0), ('REDFIN_SMP_PROBE', 1), ('REDFIN_SMP_GUI', 1)):
            self.config.write_text(original.replace(f'{name} {1 if name=="SHIM_EARLY_RETURN" else 0}', f'{name} {value}'))
            with self.assertRaises(ValueError):
                self.verify(m)
            m['sha256']['config.h'] = hashlib.sha256(self.config.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                self.verify(m)
        self.config.write_text(original + '#define SHIM_EARLY_RETURN 1\n')
        m['sha256']['config.h'] = hashlib.sha256(self.config.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            self.verify(m)


if __name__ == '__main__':
    unittest.main()
