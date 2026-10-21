import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "collect_device", Path(__file__).with_name("collect-device.py"))
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def valid_dtb():
    structure = struct.pack(">I", 1) + b"\0\0\0\0" + struct.pack(">II", 2, 9)
    return (struct.pack(">10I", collector.FDT_MAGIC, 73, 56, 72, 40,
                        17, 16, 0, 1, len(structure))
            + bytes(16) + structure + b"\0")


def successful_reads(command, **kwargs):
    operation = tuple(command[command.index("exec-out") + 1:])
    data = {
        ("getprop", "ro.product.device"): b"redfin\n",
        ("getprop", "ro.bootloader"): b"r3-example\n",
        ("cat", "/sys/firmware/fdt"): valid_dtb(),
        ("cat", "/proc/iomem"): b"00000000-00000000 : System RAM\n",
        ("cat", "/proc/cpuinfo"): b"processor : 0\nCPU part : 0xd05\n",
    }[operation]
    return subprocess.CompletedProcess(command, 0, data, b"")


class FdtValidationTests(unittest.TestCase):
    def test_valid_header_is_big_endian(self):
        self.assertEqual(collector.validate_fdt(valid_dtb())["totalsize"], 73)

    def test_rejects_corrupt_headers_and_block_bounds(self):
        examples = [b"", valid_dtb()[:39], valid_dtb()[:-1]]
        for index, value in ((0, 0xEDFE0DD0), (1, 999), (2, 999),
                             (3, 39), (4, 41), (5, 16), (6, 18),
                             (8, 999), (9, 999)):
            damaged = bytearray(valid_dtb())
            struct.pack_into(">I", damaged, index * 4, value)
            examples.append(bytes(damaged))
        for damaged in examples:
            with self.subTest(header=damaged[:40]):
                with self.assertRaises(ValueError):
                    collector.validate_fdt(damaged)

    def test_rejects_overlapping_blocks(self):
        damaged = bytearray(valid_dtb())
        struct.pack_into(">I", damaged, 12, 56)
        with self.assertRaisesRegex(ValueError, "overlapping"):
            collector.validate_fdt(damaged)

    def test_rejects_unterminated_reservation_map(self):
        damaged = bytearray(valid_dtb())
        damaged[40:] = b"\xff" * (len(damaged) - 40)
        with self.assertRaisesRegex(ValueError, "unterminated"):
            collector.validate_fdt(damaged)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / "capture"

    def manifest(self):
        return json.loads((self.out / "manifest.json").read_text())

    @mock.patch.object(collector.subprocess, "run", side_effect=successful_reads)
    def test_collects_binary_dtb_and_hashes_with_selected_device(self, run):
        self.assertEqual(collector.collect(self.out, serial="test-device"), 0)
        manifest = self.manifest()
        self.assertTrue(manifest["success"])
        self.assertEqual((self.out / "device.dtb").read_bytes(), valid_dtb())
        self.assertEqual(manifest["files"]["device.dtb"]["sha256"],
                         hashlib.sha256(valid_dtb()).hexdigest())
        self.assertNotIn("test-device", (self.out / "manifest.json").read_text())
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:4], ["adb", "-s", "test-device", "exec-out"])
        operations = [call.args[0][4:] for call in run.call_args_list]
        self.assertEqual(operations, [list(value) for value in collector.ARTIFACTS.values()])

    @mock.patch.object(collector.subprocess, "run")
    def test_adb_failure_stops_before_dumping(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, b"", b"device unauthorized")
        self.assertEqual(collector.collect(self.out), 1)
        self.assertEqual(run.call_count, 1)
        manifest = self.manifest()
        self.assertEqual(manifest["files"]["product-device.txt"]["status"], "error")
        self.assertEqual(manifest["files"]["device.dtb"]["status"], "skipped")

    @mock.patch.object(collector.subprocess, "run")
    def test_wrong_device_stops_before_dumping(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b"bramble\n", b"")
        self.assertEqual(collector.collect(self.out), 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.manifest()["product"], "bramble")
        self.assertFalse((self.out / "device.dtb").exists())

    def test_missing_or_corrupt_dtb_fails_and_reports_reason(self):
        for failure in (b"corrupt dtb", None):
            def read(command, **kwargs):
                if command[-1] == "/sys/firmware/fdt":
                    if failure is None:
                        return subprocess.CompletedProcess(command, 1, b"", b"Permission denied")
                    return subprocess.CompletedProcess(command, 0, failure, b"")
                return successful_reads(command, **kwargs)
            with self.subTest(failure=failure), mock.patch.object(
                    collector.subprocess, "run", side_effect=read):
                self.assertEqual(collector.collect(self.out, force=True), 1)
                entry = self.manifest()["files"]["device.dtb"]
                self.assertEqual(entry["status"], "error" if failure is None else "invalid")
                if failure is None:
                    self.assertIn("root-enabled adbd", entry["error"])
                    self.assertFalse((self.out / "device.dtb").exists())

    @mock.patch.object(collector.subprocess, "run", side_effect=FileNotFoundError("adb"))
    def test_missing_adb_is_recorded(self, run):
        self.assertEqual(collector.collect(self.out), 1)
        self.assertIn("cannot execute adb", self.manifest()["files"]["product-device.txt"]["error"])

    @mock.patch.object(collector.subprocess, "run", side_effect=subprocess.TimeoutExpired("adb", 20))
    def test_adb_timeout_is_recorded(self, run):
        self.assertEqual(collector.collect(self.out), 1)
        self.assertIn("timed out", self.manifest()["files"]["product-device.txt"]["error"])

    @mock.patch.object(collector.subprocess, "run")
    def test_existing_output_requires_force_before_adb(self, run):
        self.out.mkdir()
        original = self.out / "device.dtb"
        original.write_bytes(b"old capture")
        with self.assertRaises(FileExistsError):
            collector.collect(self.out)
        self.assertEqual(original.read_bytes(), b"old capture")
        run.assert_not_called()

    @mock.patch.object(collector.subprocess, "run", side_effect=successful_reads)
    def test_force_preserves_unrelated_files(self, run):
        self.out.mkdir()
        (self.out / "notes.txt").write_text("keep")
        (self.out / "device.dtb").write_bytes(b"old capture")
        self.assertEqual(collector.collect(self.out, force=True), 0)
        self.assertEqual((self.out / "notes.txt").read_text(), "keep")
        self.assertEqual((self.out / "device.dtb").read_bytes(), valid_dtb())


if __name__ == "__main__":
    unittest.main()
