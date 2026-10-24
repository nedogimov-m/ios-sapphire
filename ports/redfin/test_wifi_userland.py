"""A launchd-cache fix must change only wifid, including with interned keys."""
import copy
from pathlib import Path
import plistlib
import tempfile
import unittest

import wifi_userland as wifi


def fixture():
    return {"LaunchDaemons": {
        "wifi-job": {"Label": wifi.LABEL, "Program": "/usr/sbin/wifid",
                     "Disabled": False, "RunAtLoad": True, "KeepAlive": True,
                     "MachServices": {"com.apple.wifi-xpc": True,
                                      "com.apple.private.corewifi-xpc": True},
                     wifi.GATE: list(wifi.STOCK_NODES)},
        "other-job": {"Label": "other", wifi.GATE: list(wifi.STOCK_NODES),
                      "Disabled": True}}, "LaunchAgents": {"retained": b"opaque"}}


def encode(cache):
    return plistlib.dumps(cache, fmt=plistlib.FMT_BINARY, sort_keys=False)


class WiFiUserlandTests(unittest.TestCase):
    def test_only_target_gate_changes_and_all_other_content_survives(self):
        cache = fixture()
        original = encode(cache)
        expected = copy.deepcopy(cache)
        del expected["LaunchDaemons"]["wifi-job"][wifi.GATE]
        patched, report = wifi.patch_launchd_cache(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(plistlib.loads(patched), expected)
        self.assertTrue(report["changed"])
        again, report = wifi.patch_launchd_cache(patched)
        self.assertEqual(again, patched)
        self.assertFalse(report["changed"])

    def test_shared_job_requiring_a_larger_allocation_is_rejected(self):
        cache = fixture()
        cache["OtherReference"] = cache["LaunchDaemons"]["wifi-job"]
        # Separating the shared dictionary costs more bytes than removing the
        # gate saves here. Refuse rather than overwrite the next file's data.
        with self.assertRaisesRegex(ValueError, "grew"):
            wifi.patch_launchd_cache(encode(cache))

    def test_wrong_program_or_startup_policy_is_rejected(self):
        for key, value in [("Program", "/usr/sbin/other"), ("Disabled", True),
                           ("RunAtLoad", False), ("KeepAlive", False), ("MachServices", {})]:
            with self.subTest(key=key):
                cache = fixture()
                cache["LaunchDaemons"]["wifi-job"][key] = value
                with self.assertRaises(ValueError):
                    wifi.patch_launchd_cache(encode(cache))

    def test_missing_duplicate_or_unexpected_gate_is_rejected(self):
        for kind in ("missing", "duplicate", "gate"):
            with self.subTest(kind=kind):
                cache = fixture()
                jobs = cache["LaunchDaemons"]
                if kind == "missing":
                    del jobs["wifi-job"]
                elif kind == "duplicate":
                    jobs["duplicate"] = dict(jobs["wifi-job"])
                else:
                    jobs["wifi-job"][wifi.GATE] = ["unreviewed-hardware"]
                with self.assertRaises(ValueError):
                    wifi.patch_launchd_cache(encode(cache))

    def test_malformed_cache_is_rejected(self):
        for data in (b"bplist00truncated", b"xml", encode({}), encode({"LaunchDaemons": []})):
            with self.subTest(data=data[:16]), self.assertRaises(ValueError):
                wifi.patch_launchd_cache(data)

    def test_staging_edit_retains_inode_mode_length_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / wifi.CACHE_PATH
            path.parent.mkdir(parents=True)
            original = encode(fixture())
            path.write_bytes(original)
            path.chmod(0o640)
            before = path.stat()
            wifi.prepare_root(root)
            after = path.stat()
            self.assertEqual((after.st_ino, after.st_uid, after.st_gid, after.st_mode, after.st_size),
                             (before.st_ino, before.st_uid, before.st_gid, before.st_mode, before.st_size))
            self.assertEqual(path.read_bytes(), wifi.patch_launchd_cache(original)[0])

    def test_opt_in_logging_compacts_containers_and_changes_only_wifid(self):
        cache = fixture()
        cache["SharedContainers"] = [{"repeat": ["some repeated container value"]} for _ in range(20)]
        expected = copy.deepcopy(cache)
        job = expected["LaunchDaemons"]["wifi-job"]
        del job[wifi.GATE]
        job["EnvironmentVariables"] = {"OS_ACTIVITY_DT_MODE": "YES"}
        job["StandardErrorPath"] = job["StandardOutPath"] = "/dev/console"
        original = encode(cache)
        patched, report = wifi.daemon_log_cache(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(plistlib.loads(patched), expected)
        self.assertTrue(report["daemon_console_logging"])
        self.assertEqual(wifi.daemon_log_cache(patched)[0], patched)


if __name__ == "__main__":
    unittest.main()
