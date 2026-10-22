"""Reject unsafe diagnostic combinations before reading host artifacts."""
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).with_name('build.py')


class BuildFlagTests(unittest.TestCase):
    def refused(self, flags, message):
        result = subprocess.run([sys.executable, str(SCRIPT), '--stock-boot', '/missing-stock-boot',
                                 *flags], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(message, result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_display_needs_validated_framebuffer_and_apple_identity(self):
        self.refused(['--display', '--kernel', '/missing-kernel'],
                     '--display requires --kernel, --apple-adt and --splash')

    def test_shutdown_needs_recovery_return(self):
        self.refused(['--kernel', '/missing-kernel', '--ufs-root', '--shutdown-seconds', '120'],
                     '--shutdown-seconds requires --kernel, --ufs-root and --return-bootloader')

    def test_shutdown_is_bounded(self):
        for value in ('-1', '4', '301'):
            with self.subTest(value=value):
                self.refused(['--shutdown-seconds', value],
                             '--shutdown-seconds must be zero or in [5, 300]')

    def test_syscall_diagnostics_need_kernel(self):
        self.refused(['--trace-syscalls'], '--trace-syscalls requires --kernel')

    def test_screen_capture_requires_display(self):
        self.refused(['--capture-screen'], '--capture-screen requires --display')

    def test_userspace_stacks_need_timed_shutdown(self):
        self.refused(['--userspace-stacks'], '--userspace-stacks requires --shutdown-seconds')

    def test_peripheral_observers_require_kernel(self):
        for option in ('--touch-probe', '--touch-rail-probe', '--touch-id-probe', '--usb-probe', '--usb-route-probe', '--usb-owned-probe',
                       '--usb-context-probe', '--usb-bypass-probe', '--rpmh-probe', '--gpu-probe', '--wifi-probe'):
            self.refused([option], 'peripheral observers require --kernel')

    def test_initial_touch_id_is_ram_only_with_verified_return(self):
        self.refused(['--kernel', '/missing-kernel', '--touch-id-probe'],
                     '--touch-id-probe requires --return-bootloader')
        self.refused(['--kernel', '/missing-kernel', '--touch-id-probe',
                      '--return-bootloader', '--ufs-probe'],
                     '--touch-id-probe requires the initial RAM root without UFS')

    def test_owned_usb_is_ram_only_with_verified_return_and_separate_touch(self):
        self.refused(['--kernel', '/missing-kernel', '--usb-owned-probe'],
                     '--usb-owned-probe requires --return-bootloader')
        self.refused(['--kernel', '/missing-kernel', '--usb-owned-probe',
                      '--return-bootloader', '--ufs-probe'],
                     '--usb-owned-probe requires the initial RAM root without UFS')
        self.refused(['--kernel', '/missing-kernel', '--usb-owned-probe',
                      '--return-bootloader', '--touch-id-probe'],
                     'initial touch ID and owned USB experiments must run separately')

    def test_usb_context_observation_is_separate_ram_only_with_return(self):
        self.refused(['--kernel', '/missing-kernel', '--usb-context-probe'],
                     '--usb-context-probe requires --return-bootloader')
        for option in ('--ufs-probe', '--ufs-read-probe', '--ufs-wake-probe', '--ufs-root-probe', '--ufs-root'):
            with self.subTest(option=option):
                self.refused(['--kernel', '/missing-kernel', '--usb-context-probe',
                              '--return-bootloader', option],
                             '--usb-context-probe requires the initial RAM root without UFS')
        for option in ('--touch-id-probe', '--usb-owned-probe'):
            with self.subTest(option=option):
                self.refused(['--kernel', '/missing-kernel', '--usb-context-probe',
                              '--return-bootloader', option],
                             'USB context observation must run separately from touch ID and owned USB experiments')

    def test_usb_bypass_is_separate_ram_only_with_return(self):
        self.refused(['--kernel', '/missing-kernel', '--usb-bypass-probe'],
                     '--usb-bypass-probe requires --return-bootloader')
        for option in ('--ufs-probe', '--ufs-read-probe', '--ufs-wake-probe', '--ufs-root-probe', '--ufs-root'):
            with self.subTest(option=option):
                self.refused(['--kernel', '/missing-kernel', '--usb-bypass-probe',
                              '--return-bootloader', option],
                             '--usb-bypass-probe requires the initial RAM root without UFS')
        for option in ('--touch-id-probe', '--usb-owned-probe', '--usb-context-probe'):
            with self.subTest(option=option):
                self.refused(['--kernel', '/missing-kernel', '--usb-bypass-probe',
                              '--return-bootloader', option],
                             'USB bypass experiment must run separately from touch ID, direct claim and context observation')


if __name__ == '__main__':
    unittest.main()
