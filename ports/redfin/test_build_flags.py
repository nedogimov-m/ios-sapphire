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

    def test_display_cadence_needs_explicit_display(self):
        self.refused(['--display-hz', '10'], '--display-hz requires --display')

    def test_gpu_power_requires_its_isolated_cpu0_ram_profile(self):
        self.refused(['--gpu-power-probe'],
                     '--gpu-power-probe requires kernel, live DTB, CPU0 and --return-bootloader')
        base = ['--gpu-power-probe', '--kernel', '/missing-kernel',
                '--dtb', '/missing-dtb', '--return-bootloader']
        self.refused([*base, '--boot-mpidr', '0x100'],
                     '--gpu-power-probe requires kernel, live DTB, CPU0 and --return-bootloader')
        for option in ('--display', '--splash', '--touch-events', '--ufs-root', '--ufs-rw',
                       '--capture-screen', '--userspace-stacks', '--trace-syscalls',
                       '--smp-gui', '--smp-probe', '--shim-early-return', '--usb-probe',
                       '--touch-probe', '--wifi-probe', '--rpmh-probe'):
            with self.subTest(option=option):
                self.refused([*base, option], '--gpu-power-probe requires its separate RAM-only profile')

    def test_native_wifi_observation_requires_its_isolated_cpu0_ram_profile(self):
        self.refused(['--wifi-native-probe'],
                     '--wifi-native-probe requires kernel, live DTB, CPU0 and --return-bootloader')
        base = ['--wifi-native-probe', '--kernel', '/missing-kernel',
                '--dtb', '/missing-dtb', '--return-bootloader']
        self.refused([*base, '--boot-mpidr', '0x600'],
                     '--wifi-native-probe requires kernel, live DTB, CPU0 and --return-bootloader')
        for option in ('--display', '--splash', '--touch-events', '--ufs-root',
                       '--smp-gui', '--smp-probe', '--shim-early-return', '--usb-probe',
                       '--wifi-probe', '--gpu-power-probe', '--rpmh-probe'):
            with self.subTest(option=option):
                self.refused([*base, option], '--wifi-native-probe requires its separate RAM-only profile')

    def test_gmu_tcm_requires_held_parent_profile_without_competing_writers(self):
        self.refused(['--gmu-tcm-probe'],
                     '--gmu-tcm-probe requires kernel, live DTB, CPU0 and --return-bootloader')
        base = ['--gmu-tcm-probe', '--kernel', '/missing-kernel',
                '--dtb', '/missing-dtb', '--return-bootloader']
        self.refused([*base, '--boot-mpidr', '0x700'],
                     '--gmu-tcm-probe requires kernel, live DTB, CPU0 and --return-bootloader')
        for option in ('--display', '--splash', '--touch-events', '--ufs-root',
                       '--smp-gui', '--smp-probe', '--shim-early-return', '--usb-probe',
                       '--wifi-native-probe', '--rpmh-probe'):
            with self.subTest(option=option):
                expected = '--wifi-native-probe' if option == '--wifi-native-probe' else '--gmu-tcm-probe'
                self.refused([*base, option], expected + ' requires its separate RAM-only profile')

    def test_cpu_capability_probe_requires_runtime_return_and_cpu0(self):
        self.refused(['--cpu-capability-probe'],
                     '--cpu-capability-probe requires --kernel, --dtb and --return-bootloader')
        base = ['--cpu-capability-probe', '--kernel', '/missing-kernel',
                '--dtb', '/missing-dtb', '--return-bootloader']
        self.refused([*base, '--boot-mpidr', '0x100'],
                     '--cpu-capability-probe requires boot CPU0')
        for option in ('--usb-probe', '--touch-events', '--ufs-root', '--gpu-probe', '--trace-syscalls'):
            with self.subTest(option=option):
                self.refused([*base, option],
                             '--cpu-capability-probe requires a separate RAM-only profile')

    def test_display_cadence_is_bounded(self):
        for value in ('-1', '0', '11'):
            with self.subTest(value=value):
                self.refused(['--display', '--display-hz', value],
                             '--display-hz must be in [1, 10]')

    def test_early_return_probe_is_exclusive_ram_cpu0_with_existing_return(self):
        self.refused(['--early-return-probe'],
                     '--early-return-probe requires --kernel, --dtb and --return-bootloader')
        base = ['--early-return-probe', '--kernel', '/missing-kernel',
                '--dtb', '/missing-dtb', '--return-bootloader']
        self.refused([*base, '--boot-mpidr', '0x600'],
                     '--early-return-probe requires boot CPU0')
        for option in ('--cpu-capability-probe', '--usb-probe', '--touch-events',
                       '--ufs-probe', '--ufs-root', '--gpu-probe', '--splash',
                       '--trace-syscalls', '--usb-live-log'):
            with self.subTest(option=option):
                self.refused([*base, option],
                             '--early-return-probe requires a separate RAM-only profile')

    def test_shim_prearm_requires_the_isolated_rehearsal(self):
        self.refused(['--shim-early-return'],
                     '--shim-early-return requires --early-return-probe')
        self.refused(['--shim-early-return', '--cpu-capability-probe'],
                     '--shim-early-return requires --early-return-probe')

    def test_selected_secondary_requires_capability_profile_and_exact_affinity(self):
        self.refused(['--cpu-capability-target', '0x700'],
                     '--cpu-capability-target requires --cpu-capability-probe')
        for value in ('0', '0x101', '0x800', '0x100000600'):
            self.refused(['--cpu-capability-probe', '--cpu-capability-target', value],
                         '--cpu-capability-target must be 0x100..0x700 in steps of 0x100')

    def test_smp_requires_shim_return_cpu0_and_separate_profile(self):
        self.refused(['--smp-probe'],
                     '--smp-probe requires --kernel, --dtb, --return-bootloader and --shim-early-return')
        base = ['--smp-probe', '--kernel', '/missing-kernel', '--dtb', '/missing-dtb',
                '--return-bootloader', '--shim-early-return']
        self.refused([*base, '--boot-mpidr', '0x600'], '--smp-probe requires boot CPU0')
        for option in ('--cpu-capability-probe', '--early-return-probe', '--spmi-probe',
                       '--ufs-probe', '--ufs-root', '--touch-events', '--gpu-probe', '--splash'):
            self.refused([*base, option], '--smp-probe requires a separate RAM-only profile')

    def test_smp_cpu_count_requires_explicit_smp_profile(self):
        self.refused(['--smp-cpus', '8'], '--smp-cpus requires --smp-probe')
        for count in ('1', '3', '7', '9'):
            self.refused(['--smp-cpus', count], 'invalid choice')

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
        for option in ('--touch-probe', '--touch-rail-probe', '--touch-id-probe', '--touch-scan-probe', '--touch-events', '--usb-probe', '--usb-route-probe', '--usb-owned-probe',
                       '--usb-context-probe', '--usb-bypass-probe', '--usb-enumeration-probe', '--rpmh-probe', '--gpu-probe', '--wifi-probe'):
            self.refused([option], 'peripheral observers require --kernel')

    def test_initial_touch_id_is_ram_only_with_verified_return(self):
        self.refused(['--kernel', '/missing-kernel', '--touch-id-probe'],
                     '--touch-id-probe requires --return-bootloader')
        self.refused(['--kernel', '/missing-kernel', '--touch-id-probe',
                      '--return-bootloader', '--ufs-probe'],
                     '--touch-id-probe requires the initial RAM root without UFS')

    def test_touch_scan_inherits_id_power_ram_and_return_fences(self):
        self.refused(['--kernel', '/missing-kernel', '--touch-scan-probe'],
                     '--touch-id-probe requires --return-bootloader')
        self.refused(['--kernel', '/missing-kernel', '--touch-scan-probe',
                      '--return-bootloader', '--ufs-root'],
                     '--touch-id-probe requires the initial RAM root without UFS')
        self.refused(['--kernel', '/missing-kernel', '--touch-scan-probe',
                      '--return-bootloader', '--usb-bypass-probe'],
                     'USB bypass experiment must run separately from touch ID, direct claim and context observation')

    def test_touch_events_requires_ufs_display_return_and_separate_mode(self):
        self.refused(['--kernel', '/missing-kernel', '--touch-events'],
                     '--touch-events requires --ufs-root, --display and --return-bootloader')
        for option in ('--touch-id-probe', '--touch-scan-probe'):
            self.refused(['--kernel', '/missing-kernel', '--touch-events', option],
                         'GUI touch events must run separately from RAM touch ID or scan probes')
        for option in ('--usb-probe','--usb-route-probe','--usb-owned-probe','--usb-context-probe',
                       '--usb-bypass-probe','--usb-enumeration-probe','--gpu-probe','--wifi-probe','--rpmh-probe'):
            with self.subTest(option=option):
                self.refused(['--kernel', '/missing-kernel', '--touch-events', '--ufs-root',
                              '--display', '--return-bootloader', option],
                             'GUI touch events require USB, GPU, Wi-Fi and RPMh probes disabled')

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

    def test_usb_enumeration_inherits_bypass_ram_return_and_exclusive_mode(self):
        self.refused(['--kernel', '/missing-kernel', '--usb-enumeration-probe'],
                     '--usb-bypass-probe requires --return-bootloader')
        self.refused(['--kernel', '/missing-kernel', '--usb-enumeration-probe',
                      '--return-bootloader', '--ufs-root'],
                     '--usb-bypass-probe requires the initial RAM root without UFS')
        self.refused(['--kernel', '/missing-kernel', '--usb-enumeration-probe',
                      '--return-bootloader', '--touch-scan-probe'],
                     'USB bypass experiment must run separately from touch ID, direct claim and context observation')

    def test_usb_aarch64_format_requires_a_separate_owned_bypass_experiment(self):
        for flags in ([], ['--usb-probe'], ['--usb-context-probe'], ['--touch-events']):
            with self.subTest(flags=flags):
                self.refused(['--usb-aarch64-context', *flags],
                             '--usb-aarch64-context requires --usb-bypass-probe or --usb-enumeration-probe')

    def test_usb_aarch64_format_keeps_ram_root_and_return_requirements(self):
        for probe in ('--usb-bypass-probe', '--usb-enumeration-probe'):
            with self.subTest(probe=probe):
                self.refused(['--kernel', '/missing-kernel', probe, '--usb-aarch64-context'],
                             '--usb-bypass-probe requires --return-bootloader')
                self.refused(['--kernel', '/missing-kernel', probe, '--usb-aarch64-context',
                              '--return-bootloader', '--ufs-root'],
                             '--usb-bypass-probe requires the initial RAM root without UFS')

    def test_live_log_requires_explicit_network_probe(self):
        self.refused(['--usb-live-log'], '--usb-live-log requires --usb-network-probe')

    def test_usb_network_probe_keeps_ram_return_and_exclusive_profile(self):
        self.refused(['--usb-network-probe'], 'peripheral observers require --kernel')
        self.refused(['--kernel', '/missing-kernel', '--usb-network-probe'],
                     '--usb-bypass-probe requires --return-bootloader')
        self.refused(['--kernel', '/missing-kernel', '--usb-network-probe',
                      '--return-bootloader', '--ufs-root'],
                     '--usb-bypass-probe requires the initial RAM root without UFS')
        self.refused(['--kernel', '/missing-kernel', '--usb-network-probe',
                      '--return-bootloader', '--touch-scan-probe'],
                     'USB bypass experiment must run separately from touch ID, direct claim and context observation')


if __name__ == '__main__':
    unittest.main()
