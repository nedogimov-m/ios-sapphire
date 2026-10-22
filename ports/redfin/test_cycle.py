import argparse
import contextlib
import importlib.util
import hashlib
import json
import io
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("boot_cycle", Path(__file__).with_name("boot-cycle.py"))
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


class RingTests(unittest.TestCase):
    def test_partial_ring(self):
        raw = b"prefix" + struct.pack("<III", 0x43474244, 5, 5) + b"hello....."
        self.assertEqual(cycle.extract_ring(raw, 6, 22), b"hello")

    def test_wrapped_ring(self):
        raw = struct.pack("<III", 0x43474244, 3, 10) + b"7890123456"
        self.assertEqual(cycle.extract_ring(raw, 0, 22), b"0123456789")

    def test_corrupt_and_truncated_rings(self):
        for header in ((0, 0, 0), (0x43474244, 10, 10), (0x43474244, 0, 11), (0x43474244, 3, 5)):
            with self.subTest(header=header), self.assertRaises(ValueError):
                cycle.extract_ring(struct.pack("<III", *header) + bytes(10), 0, 22)
        with self.assertRaises(ValueError):
            cycle.extract_ring(bytes(20), 0, 22)

    def test_pstore_names_reject_traversal(self):
        self.assertTrue(cycle.valid_name("console-ramoops-0"))
        for name in ("../x", "/x", ".", "a;b", "a\nb", "a" * 161):
            self.assertFalse(cycle.valid_name(name))


class IdentityTests(unittest.TestCase):
    def runner(self):
        return cycle.Cycle(argparse.Namespace(serial=None, out=Path("unused")))

    def test_wrong_identity_never_requests_root(self):
        runner = self.runner()
        with mock.patch.object(runner, "adb", return_value=(0, b"bramble\n", b"")) as adb:
            with self.assertRaisesRegex(ValueError, "not redfin"):
                runner.verify_android()
        self.assertEqual(adb.call_count, 1)

    def test_root_device_requires_no_root_restart(self):
        runner = self.runner()
        with mock.patch.object(runner, "adb", side_effect=[(0, b"redfin\n", b""), (0, b"0\n", b"")]) as adb:
            runner.verify_android()
        self.assertEqual(adb.call_count, 2)

    def test_non_root_adb_is_restarted_and_identity_rechecked(self):
        runner = self.runner()
        with mock.patch.object(runner, "adb", side_effect=[(0, b"redfin\n", b""), (0, b"2000\n", b""),
                (0, b"", b""), (0, b"0\n", b""), (0, b"redfin\n", b"")]) as adb:
            runner.verify_android()
        self.assertEqual(adb.call_args_list[2].args, ("root",))
        self.assertEqual(adb.call_args_list[-1].args, ("exec-out", "getprop", "ro.product.device"))

    def test_leave_rechecks_identity_root_and_recovery_markers(self):
        expected = [("exec-out", "getprop", "ro.product.device"), ("exec-out", "id", "-u"),
                    ("exec-out", "getprop", "ro.redfin.offline_recovery"),
                    ("exec-out", "getprop", "ro.redfin.return_target")]
        outputs = [b"redfin", b"0", b"1", b"bootloader"]
        for changed in range(len(outputs)):
            runner = self.runner()
            runner.args.recovery_image, runner.recovery_verified = Path("recovery.img"), True
            replies = [(0, data if i != changed else b"changed", b"") for i, data in enumerate(outputs)]
            with self.subTest(changed=changed), mock.patch.object(runner, "adb", side_effect=replies) as adb:
                with self.assertRaisesRegex(ValueError, "identity changed"):
                    runner.leave_bootloader()
                self.assertEqual([call.args for call in adb.call_args_list], expected[:changed + 1])

    def test_android_leave_rechecks_without_requesting_root(self):
        runner = self.runner()
        runner.android_verified = True
        with mock.patch.object(runner, "adb", side_effect=[(0, b"redfin", b""), (0, b"2000", b"")]) as adb:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                runner.leave_bootloader()
        self.assertEqual([call.args for call in adb.call_args_list],
                         [("exec-out", "getprop", "ro.product.device"), ("exec-out", "id", "-u")])


class UserspaceTests(unittest.TestCase):
    def evidence(self, body):
        return cycle.userspace_evidence(b"bootloader\n[REDFIN RAMLOG v1]\n" + body)

    def test_plain_banner_and_heartbeat(self):
        result = self.evidence(b"REDFIN userspace: init running as PID 1 ***\nREDFIN init: still alive\n")
        self.assertTrue(result["pid1_alive"])
        self.assertEqual(result["heartbeats"], 1)

    def test_banner_split_by_syscall_tracing(self):
        result = self.evidence(
            b"*** REDFIN userspace: init running as PID REDFIN PID1: syscall 2 return code=4 error=0 value=43\n"
            b"REDFIN PID1: syscall 3 return code=20 error=0 value=1\n"
            b"1REDFIN PID1: syscall 4 return code=4 error=0 value=1\n ***\n"
            b"REDFIN init: still alive\nREDFIN init: still alive\n")
        self.assertEqual(result, {"pid1_alive": True, "getpid_1": True, "heartbeats": 2})

    def test_require_heartbeat_and_pid_evidence(self):
        for body in (b"REDFIN userspace: init running as PID 1\n",
                     b"REDFIN userspace: init running as PID REDFIN init: still alive\n",
                     b"REDFIN userspace: init running as PID REDFIN PID1: syscall 3 return code=20 error=0 value=12\nREDFIN init: still alive\n"):
            self.assertFalse(self.evidence(body)["pid1_alive"])

    def test_ignore_following_boot_history(self):
        result = self.evidence(b"kernel stopped\n--- BOOT HISTORY ---\nREDFIN userspace: init running as PID 1\nREDFIN init: still alive\n")
        self.assertFalse(result["pid1_alive"])


class AppleUserspaceTests(unittest.TestCase):
    def evidence(self, body, authenticated=True):
        return cycle.apple_userspace_evidence(b"[REDFIN RAMLOG v1]\n" + body, authenticated)

    def test_actual_launchd_runtime_and_boot_tasks_with_later_panic(self):
        result = self.evidence(
            b"Darwin Ignition Sequence VersionREDFIN PID1: syscall 16 return code=4 error=0 value=32\n"
            b" 1.0.0: Tue Jul  2 20:41:23 PDT 2024; root:libignition-51~1974\r\r\n"
            b"libignition: 1:        hello: hello from launchd.1\r\r\n"
            b"com.apple.xpc.launchd|1970-01-01 00:00:51.730686 (system) <Notice>: created\r\r\n"
            b"com.apple.xpc.launchd|1970-01-01 00:00:51.740785 (fsck) <Notice>: Doing boot task\r\r\n"
            b"com.apple.xpc.launchd|1970-01-01 00:00:51.849513 (mount-phase-1) <Notice>: Doing boot task\r\r\n"
            b"REDFIN PANIC: mount[3] exited -- (signal 0, exit status 1)\n"
            b"panic(cpu 0 caller 0xfffffe0007b84950): mount[3] exited\r\n")
        self.assertEqual(result, {"capture_authenticated": True, "launchd_pid1_hello": True,
            "darwin_ignition_banner": True, "system_domain_created": True,
            "boot_tasks": ["fsck", "mount-phase-1"], "panic": True})

    def test_boot_argument_strings_and_other_pid_are_not_pid1_runtime(self):
        result = self.evidence(
            b"Boot args: launchd_unsecure_cache=1 libignition: 1: hello from launchd.1 "
            b"Darwin Ignition Sequence Version com.apple.xpc.launchd| (system) <Notice>: created "
            b"REDFIN PANIC: panic(cpu 0 caller 0x123)\n"
            b"libignition: 2: hello: hello from launchd.1\r\n"
            b"libignition: 1: hello: hello from launchd.12\r\n", authenticated=False)
        self.assertEqual(result, {"capture_authenticated": False, "launchd_pid1_hello": False,
            "darwin_ignition_banner": False, "system_domain_created": False,
            "boot_tasks": [], "panic": False})

    def test_following_boot_history_is_excluded_and_native_panic_is_recognized(self):
        result = self.evidence(b"panic(cpu 0 caller 0x123): failed\n--- BOOT HISTORY ---\n"
                              b"libignition: 1: hello: hello from launchd.1\n")
        self.assertTrue(result["panic"])
        self.assertFalse(result["launchd_pid1_hello"])

    def test_apple_launchd_entry_alone_preserves_non_success_exit_status(self):
        console = b"[REDFIN RAMLOG v1]\nlibignition: 1: hello: hello from launchd.1\n"
        with tempfile.TemporaryDirectory() as directory:
            runner = cycle.Cycle(argparse.Namespace(out=Path(directory), serial=None,
                collect_only=True, raw_ramoops=True))
            def capture():
                runner.save("after/redfin-console.txt", console)
                return [("after/redfin-console.txt", console)]
            with mock.patch.object(runner, "verify_android"), \
                    mock.patch.object(runner, "raw_ramoops", side_effect=capture), \
                    mock.patch.object(runner, "pstore", return_value=[]), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.run()
        self.assertEqual(result, 1)
        self.assertEqual(runner.manifest["status"], "logs-collected")
        self.assertTrue(runner.manifest["apple_userspace"]["launchd_pid1_hello"])
        self.assertFalse(runner.manifest["userspace"]["pid1_alive"])


class FakeClock:
    def __init__(self):
        self.now = 0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


RAMLOG = b"[REDFIN RAMLOG v1]\nREDFIN userspace: init running as PID 1\nREDFIN init: still alive\n"


def raw_ring(console=RAMLOG):
    raw = bytearray(0x400000)
    struct.pack_into("<III", raw, cycle.CONSOLE_OFFSET, 0x43474244, len(console), len(console))
    raw[cycle.CONSOLE_OFFSET + 12:cycle.CONSOLE_OFFSET + 12 + len(console)] = console
    return bytes(raw)


def public_metadata():
    data = bytearray(4096)
    struct.pack_into("<5I", data, 0, 0x4b6c6243, 0, 0x794b6250, 0x13, 524)
    struct.pack_into("<I", data, 0x14 + 524, cycle.zlib.crc32(data[8:0x14 + 524]))
    return bytes(data)


class FakeDevice:
    """Simulate both transports; an unexpected command fails the test."""
    def __init__(self, clock, fastboot=False, recovery=False):
        self.clock, self.calls = clock, []
        self.state = "fastboot" if fastboot else "recovery" if recovery else "android"
        self.product, self.uid = b"redfin", b"0"
        self.timer_running, self.return_fastboot, self.booted = True, True, False
        self.marker, self.stop_works = b"1", True
        self.polls = 0
        self.mounts = b"rootfs / rootfs rw 0 0\nnone /sys/fs/pstore pstore rw 0 0\n"

    def __call__(self, tool, command, timeout=15, input_data=None):
        command = tuple(command)
        self.clock.now += 0.1
        self.calls.append((tool, command))
        if tool == "fastboot":
            if command == ("getvar", "product"):
                if self.state == "xnu":
                    self.polls += 1
                    if self.return_fastboot and self.polls >= 2:
                        self.state = "fastboot"
                if self.state != "fastboot":
                    return 1, b"", b"waiting"
                return 0, b"", b"(bootloader) product: " + self.product + b"\n"
            if command[0] == "boot":
                if self.state != "fastboot":
                    raise AssertionError("boot before verified fastboot")
                if Path(command[1]).name == "recovery.img":
                    self.state = "recovery"
                else:
                    self.state, self.booted, self.polls = "xnu", True, 0
                return 0, b"", b"OKAY\nFinished\n"
            raise AssertionError((tool, command))
        if command == ("reboot", "bootloader"):
            if self.state not in ("android", "recovery"):
                raise AssertionError("ADB reboot outside an ADB environment")
            self.state = "fastboot"
            return 0, b"", b""
        if command == ("exec-out", "getprop", "ro.product.device") and self.state == "xnu":
            self.polls += 1
            if self.polls >= 2:
                self.state = "android"
        if self.state not in ("android", "recovery"):
            return 1, b"", b"offline"
        if command[:2] == ("exec-out", "getprop"):
            values = {"ro.product.device": self.product,
                      "ro.redfin.offline_recovery": self.marker if self.state == "recovery" else b"",
                      "ro.redfin.return_target": b"bootloader",
                      "init.svc.recovery-return": b"running" if self.timer_running else b"stopped"}
            return 0, values[command[2]] + b"\n", b""
        if command == ("exec-out", "id", "-u"):
            return 0, self.uid + b"\n", b""
        if command == ("exec-out", "cat", "/proc/mounts"):
            return 0, self.mounts, b""
        if command == ("exec-out", "cat", "/proc/swaps"):
            return 0, b"Filename Type Size Used Priority\n", b""
        if command == ("exec-out", "setprop", "ctl.stop", "recovery-return"):
            if self.stop_works:
                self.timer_running = False
            return 0, b"", b""
        if command == ("exec-out", "head", "-c", "4194305", "/dev/access-ramoops"):
            if self.state != "recovery" or self.timer_running:
                raise AssertionError("raw recovery read before verified recovery/timer stop")
            return 0, raw_ring(), b""
        if command == ("exec-out", "ls", "-1", "/sys/fs/pstore"):
            return 0, b"" if self.state == "recovery" else b"console-ramoops-0\n", b""
        if command[:3] == ("exec-out", "head", "-c"):
            return 0, RAMLOG if self.booted else b"previous boot\n", b""
        raise AssertionError((tool, command))


class CycleStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.image, self.recovery = self.base / "xnu.img", self.base / "recovery.img"
        self.image.write_bytes(b"XNU")
        self.recovery.write_bytes(b"RECOVERY")
        self.proof = {"image_sha256": hashlib.sha256(b"RECOVERY").hexdigest(), "return_target": "bootloader",
                      "properties": {"ro.redfin.offline_recovery": "1", "ro.redfin.return_target": "bootloader"},
                      "data_mount_actions": False, "userdata_writes": False, "recovery_ui_disabled": True,
                      "sha256": {"redfin-xnu.img": hashlib.sha256(b"XNU").hexdigest()},
                      "boot_args": "-v cpus=1 redfinreturn=1"}
        self.write_proof()

    def write_proof(self):
        (self.base / "manifest.json").write_text(json.dumps(self.proof))

    def run_cycle(self, recovery=True, from_bootloader=True, collect_only=False,
                  leave=False, device=None):
        out = self.base / "logs"
        out.mkdir()
        args = argparse.Namespace(serial=None, out=out, image=self.image, timeout=6,
            recovery_image=self.recovery if recovery else None, from_bootloader=from_bootloader,
            collect_only=collect_only, leave_bootloader=leave)
        runner = cycle.Cycle(args)
        clock = device.clock if device else FakeClock()
        device = device or FakeDevice(clock, fastboot=from_bootloader)
        with mock.patch.object(runner, "call", side_effect=device), \
                mock.patch.object(cycle.time, "sleep", side_effect=clock.sleep), \
                mock.patch.object(cycle.time, "monotonic", side_effect=clock.monotonic), \
                contextlib.redirect_stdout(io.StringIO()):
            status = runner.run()
        return status, runner, device

    def test_fastboot_xnu_recovery_raw_capture_and_leave_bootloader(self):
        status, runner, device = self.run_cycle(leave=True)
        self.assertEqual(status, 0)
        self.assertEqual(device.state, "fastboot")
        self.assertTrue(runner.manifest["left_in_bootloader"])
        self.assertEqual((self.base / "logs/xnu-console.txt").read_bytes(), RAMLOG)
        boots = [command[1] for tool, command in device.calls if tool == "fastboot" and command[0] == "boot"]
        self.assertEqual(boots, [str(self.image), str(self.recovery)])
        self.assertEqual(sum(command == ("exec-out", "head", "-c", "4194305", "/dev/access-ramoops") for _, command in device.calls), 1)
        self.assertEqual(runner.manifest["raw_ramoops"], {"status": "ok", "bytes": 0x400000})
        self.assertEqual(runner.manifest["log_freshness"]["status"], "unproven")
        self.assertTrue(runner.manifest["xnu_return"]["pmic_bootloader_return"])
        self.assertFalse(any(command == ("root",) or "/data/local/tmp/" in " ".join(command) for _, command in device.calls))
        self.assertFalse(any(command == ("reboot",) for _, command in device.calls))
        stop = device.calls.index(("adb", ("exec-out", "setprop", "ctl.stop", "recovery-return")))
        mounts = device.calls.index(("adb", ("exec-out", "cat", "/proc/mounts")))
        self.assertGreater(stop, mounts)
        self.assertEqual(device.calls.count(("adb", ("exec-out", "cat", "/proc/mounts"))), 1)
        self.assertEqual(device.calls.count(("adb", ("exec-out", "setprop", "ctl.stop", "recovery-return"))), 1)

    def test_default_android_path_still_collects_without_raw_or_recovery_boot(self):
        status, runner, device = self.run_cycle(recovery=False, from_bootloader=False)
        self.assertEqual(status, 0)
        self.assertEqual(device.state, "android")
        self.assertNotIn("recovery", runner.manifest)
        self.assertFalse(any("/dev/access-ramoops" in command for _, command in device.calls))
        self.assertEqual(sum(tool == "fastboot" and command[0] == "boot" for tool, command in device.calls), 1)
        self.assertEqual(runner.manifest["log_freshness"]["status"], "baseline-compared")

    def test_collect_only_can_enter_recovery_directly_from_fastboot(self):
        status, _, device = self.run_cycle(collect_only=True)
        self.assertEqual(status, 0)
        self.assertEqual([command for tool, command in device.calls if tool == "fastboot" and command[0] == "boot"],
                         [("boot", str(self.recovery))])

    def test_xnu_return_timeout_never_falls_back_to_android(self):
        device = FakeDevice(FakeClock(), fastboot=True)
        device.return_fastboot = False
        status, runner, device = self.run_cycle(device=device)
        self.assertEqual(status, 1)
        self.assertEqual(runner.manifest["status"], "no-log")
        self.assertEqual(sum(tool == "fastboot" and command[0] == "boot" for tool, command in device.calls), 1)
        self.assertFalse(any(tool == "adb" for tool, _ in device.calls))

    def test_wrong_fastboot_identity_prevents_both_ram_boots(self):
        device = FakeDevice(FakeClock(), fastboot=True)
        device.product = b"bramble"
        status, runner, device = self.run_cycle(device=device)
        self.assertEqual(status, 1)
        self.assertIn("not redfin", runner.manifest["error"])
        self.assertEqual(device.calls, [("fastboot", ("getvar", "product"))])

    def test_recovery_marker_timeout_does_not_try_android_or_stop_the_timer(self):
        device = FakeDevice(FakeClock(), fastboot=True)
        device.marker = b""
        status, runner, device = self.run_cycle(device=device)
        self.assertEqual(status, 1)
        self.assertIn("marker before timeout", runner.manifest["error"])
        self.assertTrue(device.timer_running)
        self.assertFalse(any(command == ("reboot",) or "/dev/access-ramoops" in command for _, command in device.calls))

    def test_timer_stop_timeout_leaves_verified_recovery_in_fastboot_when_requested(self):
        device = FakeDevice(FakeClock(), recovery=True)
        device.stop_works = False
        status, runner, device = self.run_cycle(from_bootloader=False, collect_only=True, leave=True, device=device)
        self.assertEqual(status, 1)
        self.assertIn("timer did not stop", runner.manifest["error"])
        self.assertTrue(runner.manifest["left_in_bootloader"])
        self.assertEqual(device.state, "fastboot")
        self.assertFalse(any("/dev/access-ramoops" in command for _, command in device.calls))

    def test_android_return_recovery_manifest_is_rejected_before_device_commands(self):
        self.proof["return_target"] = "android"
        self.write_proof()
        status, _, device = self.run_cycle()
        self.assertEqual(status, 1)
        self.assertEqual(device.calls, [])

    def test_recovery_hash_mismatch_is_rejected_before_device_commands(self):
        self.recovery.write_bytes(b"changed image")
        status, _, device = self.run_cycle()
        self.assertEqual(status, 1)
        self.assertEqual(device.calls, [])

    def test_xnu_return_manifest_is_required_before_device_commands(self):
        for arguments in (None, "cpus=1", "redfinreturn=1", "cpus=2 redfinreturn=1",
                          "cpus=1 redfinreturn=1 redfinreturn=0", "cpus=1 redfinreturn=10"):
            with self.subTest(arguments=arguments):
                self.proof["boot_args"] = arguments
                self.write_proof()
                out = self.base / "logs"
                if out.exists():
                    (out / "manifest.json").unlink()
                    out.rmdir()
                status, runner, device = self.run_cycle()
                self.assertEqual(status, 1)
                self.assertIn("redfinreturn=1 and cpus=1", runner.manifest["error"])
                self.assertEqual(device.calls, [])

    def test_xnu_hash_mismatch_is_rejected_before_device_commands(self):
        self.image.write_bytes(b"unmatched XNU")
        status, runner, device = self.run_cycle()
        self.assertEqual(status, 1)
        self.assertIn("matching image manifest", runner.manifest["error"])
        self.assertEqual(device.calls, [])

    def test_bad_android_identity_does_not_reboot_even_with_leave_flag(self):
        device = FakeDevice(FakeClock())
        device.product = b"bramble"
        status, runner, device = self.run_cycle(recovery=False, from_bootloader=False, leave=True, device=device)
        self.assertEqual(status, 1)
        self.assertFalse(runner.manifest["left_in_bootloader"])
        self.assertEqual(device.calls, [("adb", ("exec-out", "getprop", "ro.product.device"))])

    def test_mounted_userdata_prevents_timer_stop_raw_capture_and_adb_reboot(self):
        device = FakeDevice(FakeClock(), recovery=True)
        device.mounts += b"/dev/block/sda19 /data f2fs rw 0 0\n"
        status, runner, device = self.run_cycle(from_bootloader=False, collect_only=True, leave=True, device=device)
        self.assertEqual(status, 1)
        self.assertIn("mounted disk", runner.manifest["error"])
        self.assertFalse(runner.manifest["left_in_bootloader"])
        self.assertFalse(any(command == ("exec-out", "setprop", "ctl.stop", "recovery-return")
                                 or "/dev/access-ramoops" in command or command == ("reboot", "bootloader")
                                 for _, command in device.calls))

    def test_nonroot_recovery_does_not_enable_root_or_read_raw(self):
        device = FakeDevice(FakeClock(), recovery=True)
        device.uid = b"2000"
        status, _, device = self.run_cycle(from_bootloader=False, collect_only=True, device=device)
        self.assertEqual(status, 1)
        self.assertFalse(any(command == ("root",) or "/dev/access-ramoops" in command for _, command in device.calls))

    def test_mount_permission_error_text_is_not_accepted_as_a_mount_table(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            cycle.verify_recovery_mounts(b"cat: /proc/mounts: Permission denied\n")

    def test_helper_raw_does_not_overwrite_original_capture(self):
        out = self.base / "helper-logs"
        out.mkdir()
        runner = cycle.Cycle(argparse.Namespace(serial=None, out=out, ramoops_helper=Path("helper")))
        original, helper = raw_ring(), raw_ring(RAMLOG + b"helper-only\n")
        def raw_capture():
            runner.save("after/alt-ramoops.raw", original)
            return []
        with mock.patch.object(runner, "verify_android"), mock.patch.object(runner, "raw_ramoops", side_effect=raw_capture), \
                mock.patch.object(runner, "pstore", return_value=[]), \
                mock.patch.object(runner, "adb", side_effect=[(0, b"", b""), (0, b"", b""), (0, helper, b"")]):
            runner.args.raw_ramoops = True
            runner.recover()
        self.assertEqual((out / "after/alt-ramoops.raw").read_bytes(), original)
        self.assertEqual((out / "after/helper-ramoops.raw").read_bytes(), helper)
        self.assertEqual(runner.manifest["status"], "userspace-alive")


class KeyedRamoopsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.out = self.base / "logs"
        self.out.mkdir()
        self.runner = cycle.Cycle(argparse.Namespace(serial=None, out=self.out,
            recovery_image=Path("recovery.img"), ramoops_key_dir=self.base))
        for name in ("priv.pem", "pub.pem", "ramoops"):
            path = self.base / name
            path.write_bytes(("fixture-" + name).encode())
            path.chmod(0o600)
        self.runner.key_files = {name: self.base / name for name in ("priv.pem", "pub.pem", "ramoops")}

    def test_local_inputs_require_verified_binary_and_private_permissions(self):
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.runner.verify_ramoops_key_dir()
        expected = hashlib.sha256((self.base / "ramoops").read_bytes()).hexdigest()
        with mock.patch.object(cycle, "RAMOOPS_SHA256", expected):
            self.runner.verify_ramoops_key_dir()
            (self.base / "pub.pem").chmod(0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                self.runner.verify_ramoops_key_dir()
            (self.base / "pub.pem").unlink()
            (self.base / "pub.pem").symlink_to(self.base / "priv.pem")
            with self.assertRaisesRegex(ValueError, "regular files"):
                self.runner.verify_ramoops_key_dir()

    def test_bounded_metadata_capture_requires_exact_size_and_is_private(self):
        for size in (4095, 4097):
            with self.subTest(size=size), mock.patch.object(self.runner, "adb", return_value=(0, bytes(size), b"")):
                with self.assertRaisesRegex(ValueError, "exactly 4096"):
                    self.runner.ramoops_metadata("after/metadata")
        with mock.patch.object(self.runner, "adb", return_value=(0, bytes(4096), b"")) as adb:
            self.runner.ramoops_metadata("after/metadata")
        adb.assert_called_once_with("exec-out", "head", "-c", "4097", "/dev/access-metadata")
        self.assertEqual((self.out / "after/metadata").stat().st_mode & 0o777, 0o600)

    def test_host_authentication_precedes_save_and_public_prime(self):
        ciphertext, plaintext = bytes([0x9a]) * 0x400000, raw_ring()
        self.runner.save("after/alt-ramoops.raw", ciphertext, private=True)
        decrypt = mock.Mock(return_value=plaintext)
        with mock.patch.object(self.runner, "ramoops_metadata", return_value=bytes(4096)), \
                mock.patch.object(cycle.importlib.util, "module_from_spec", return_value=types.SimpleNamespace(decrypt_capture=decrypt)), \
                mock.patch.object(cycle.importlib.machinery.SourceFileLoader, "exec_module"), \
                mock.patch.object(self.runner, "prime_ramoops_public") as prime:
            self.assertEqual(self.runner.keyed_ramoops([]), [("after/redfin-console.txt", RAMLOG)])
        decrypt.assert_called_once_with(ciphertext, bytes(4096), self.base / "priv.pem")
        prime.assert_called_once_with()
        self.assertEqual((self.out / "after/alt-ramoops.raw").read_bytes(), ciphertext)
        self.assertEqual((self.out / "after/alt-ramoops.decrypted.raw").read_bytes(), plaintext)
        self.assertEqual((self.out / "after/alt-ramoops.decrypted.raw").stat().st_mode & 0o777, 0o600)

    def test_failed_authentication_preserves_raw_and_never_primes(self):
        ciphertext = bytes([0x9a]) * 0x400000
        self.runner.save("after/alt-ramoops.raw", ciphertext, private=True)
        decrypt = mock.Mock(side_effect=ValueError("authentication failed"))
        with mock.patch.object(self.runner, "ramoops_metadata", return_value=bytes(4096)), \
                mock.patch.object(cycle.importlib.util, "module_from_spec", return_value=types.SimpleNamespace(decrypt_capture=decrypt)), \
                mock.patch.object(cycle.importlib.machinery.SourceFileLoader, "exec_module"), \
                mock.patch.object(self.runner, "prime_ramoops_public") as prime:
            with self.assertRaisesRegex(ValueError, "priming was not attempted"):
                self.runner.keyed_ramoops([])
        prime.assert_not_called()
        self.assertFalse((self.out / "after/alt-ramoops.decrypted.raw").exists())
        self.assertEqual((self.out / "after/alt-ramoops.raw").read_bytes(), ciphertext)

    def test_missing_raw_capture_never_primes(self):
        with mock.patch.object(self.runner, "prime_ramoops_public") as prime, \
                self.assertRaisesRegex(ValueError, "raw ramoops capture failed"):
            self.runner.keyed_ramoops([])
        prime.assert_not_called()

    def test_public_only_prime_uses_checked_shell_stdin_and_rechecks_storage(self):
        with mock.patch.object(self.runner, "adb", return_value=(0, b"", b"")) as adb, \
                mock.patch.object(self.runner, "ramoops_metadata", return_value=public_metadata()), \
                mock.patch.object(self.runner, "verify_recovery_storage") as storage:
            self.runner.prime_ramoops_public()
        pushes = [call.args for call in adb.call_args_list if call.args[0] == "push"]
        self.assertEqual(pushes, [("push", str(self.base / "ramoops"), "/tmp/redfin-ramoops"),
                                 ("push", str(self.base / "pub.pem"), "/tmp/redfin-ramoops-public/pub.pem")])
        shells = [call for call in adb.call_args_list if call.args[0] == "shell"]
        self.assertEqual(len(shells), 2)
        for call in shells:
            self.assertEqual(call.args, ("shell", "-T", "sh", "-s"))
            self.assertNotIn(b"priv.pem", call.kwargs["input_data"])
        self.assertIn(b"linker64 /tmp/redfin-ramoops -l -c -k /tmp/redfin-ramoops-public", shells[-1].kwargs["input_data"])
        storage.assert_called_once_with()
        self.assertEqual(self.runner.manifest["ramoops_public_prime"]["status"], "verified")

    def test_invalid_public_metadata_and_failed_script_are_reported(self):
        for offset in (0, 8, 0x20, 0x408):
            data = bytearray(public_metadata())
            data[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                cycle.primed_metadata(data)
        with mock.patch.object(self.runner, "adb", side_effect=[(0, b"", b""), (1, b"", b"failed")]) as adb, \
                mock.patch.object(self.runner, "ramoops_metadata") as metadata:
            with self.assertRaisesRegex(ValueError, "prepare RAM-only"):
                self.runner.prime_ramoops_public()
        self.assertEqual(adb.call_count, 2)
        metadata.assert_not_called()
        self.assertEqual(self.runner.manifest["ramoops_public_prime"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
