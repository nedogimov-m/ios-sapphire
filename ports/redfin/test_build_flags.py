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
        for option in ('--touch-probe', '--usb-probe', '--usb-route-probe',
                       '--rpmh-probe', '--gpu-probe', '--wifi-probe'):
            self.refused([option], 'peripheral observers require --kernel')


if __name__ == '__main__':
    unittest.main()
