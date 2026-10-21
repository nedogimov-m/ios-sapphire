import argparse
import importlib.util
from pathlib import Path
import struct
import tempfile
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


if __name__ == "__main__":
    unittest.main()
