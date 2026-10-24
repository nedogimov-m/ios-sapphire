#!/usr/bin/env python3
"""Remove the stock wifid hardware gate from Redfin's launchd cache.

Adapted from hackios-xnu-userland's mkjobs.py at
906425b75e02b4f99eb5d7bb1ef7c9583472d772. Only com.apple.wifid changes.
The binary cache keeps its exact length so an existing root can retain its
file allocation and catalog metadata. This module never accesses a device.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct

CACHE_PATH = Path("System/Library/xpc/launchd.plist")
LABEL = "com.apple.wifid"
GATE = "_LimitLoadToDeviceTree"
STOCK_NODES = ["wlan", "marconi-wifi"]


def _encode_same_size(expected, size, compact=False):
    """Pad before the offset table; optionally share equal plist containers."""
    if compact:
        containers = {}

        def intern(value):
            if isinstance(value, dict):
                children = [(key, intern(child)) for key, child in value.items()]
                identity = (dict, tuple((key, child_key) for key, (child_key, _) in children))
                result = {key: child for key, (_, child) in children}
            elif isinstance(value, list):
                children = [intern(child) for child in value]
                identity = (list, tuple(key for key, _ in children))
                result = [child for _, child in children]
            else:
                return (type(value), value), value
            return identity, containers.setdefault(identity, result)

        _, expected_for_encoding = intern(expected)
    else:
        expected_for_encoding = expected
    encoded = plistlib.dumps(expected_for_encoding, fmt=plistlib.FMT_BINARY, sort_keys=False)
    padding = size - len(encoded)
    if padding < 0:
        raise ValueError("patched cache grew; cannot preserve the existing allocation")
    trailer = bytearray(encoded[-32:])
    table_offset = struct.unpack_from(">Q", trailer, 24)[0]
    result = encoded[:table_offset] + bytes(padding) + encoded[table_offset:-32]
    struct.pack_into(">Q", trailer, 24, table_offset + padding)
    result += trailer
    if len(result) != size or plistlib.loads(result) != expected:
        raise ValueError("same-size cache failed complete semantic verification")
    return result, padding


def patch_launchd_cache(original):
    """Return a same-size cache and report; reject unexpected daemon identity."""
    if not original.startswith(b"bplist00") or not 40 <= len(original) <= 16 * 1024 * 1024:
        raise ValueError("expected a bounded binary launchd cache")
    try:
        cache = plistlib.loads(original)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("invalid binary launchd cache") from error
    jobs = cache.get("LaunchDaemons") if isinstance(cache, dict) else None
    if not isinstance(jobs, dict) or any(not isinstance(job, dict) for job in jobs.values()):
        raise ValueError("expected a LaunchDaemons dictionary")
    matches = [(key, job) for key, job in jobs.items() if job.get("Label") == LABEL]
    if len(matches) != 1:
        raise ValueError("expected exactly one com.apple.wifid job")
    key, job = matches[0]
    services = job.get("MachServices")
    if (job.get("Program") != "/usr/sbin/wifid" or job.get("Disabled") is not False
            or job.get("RunAtLoad") is not True or job.get("KeepAlive") is not True
            or not isinstance(services, dict)
            or services.get("com.apple.wifi-xpc") is not True
            or services.get("com.apple.private.corewifi-xpc") is not True):
        raise ValueError("unexpected wifid program, startup policy or Mach services")
    report = {"label": LABEL, "job_key": key, "jobs": len(jobs),
              "bytes": len(original), "changed": GATE in job,
              "before_sha256": hashlib.sha256(original).hexdigest()}
    if GATE not in job:
        report["after_sha256"] = report["before_sha256"]
        return original, report
    if job[GATE] != STOCK_NODES:
        raise ValueError("unexpected wifid DeviceTree gate")

    expected = copy.deepcopy(cache)
    # Replace this dictionary alone, even if the plist shares dictionary objects.
    expected["LaunchDaemons"][key] = dict(expected["LaunchDaemons"][key])
    del expected["LaunchDaemons"][key][GATE]
    result, padding = _encode_same_size(expected, len(original))
    report.update(removed_gate=STOCK_NODES, padding_bytes=padding,
                  after_sha256=hashlib.sha256(result).hexdigest())
    return result, report


def daemon_log_cache(original):
    """Opt-in upstream-style wifid console logging; leave other jobs intact."""
    patched, report = patch_launchd_cache(original)
    cache = plistlib.loads(patched)
    jobs = cache["LaunchDaemons"]
    key = report["job_key"]
    job = dict(jobs[key])
    job["EnvironmentVariables"] = dict(job.get("EnvironmentVariables", {}))
    job["EnvironmentVariables"]["OS_ACTIVITY_DT_MODE"] = "YES"
    job["StandardErrorPath"] = "/dev/console"
    job["StandardOutPath"] = "/dev/console"
    jobs[key] = job
    result, padding = _encode_same_size(cache, len(original), compact=True)
    report.update(changed=result != original, daemon_console_logging=True,
                  padding_bytes=padding, after_sha256=hashlib.sha256(result).hexdigest())
    return result, report


def prepare_root(root):
    """Patch a mounted staging root without replacing its file or ownership."""
    root = Path(root).resolve()
    path = root / CACHE_PATH
    if path.is_symlink() or root not in path.resolve().parents or not path.is_file():
        raise ValueError("launchd cache must be a regular file inside the staging root")
    with path.open("r+b") as stream:
        original = stream.read()
        patched, report = patch_launchd_cache(original)
        if report["changed"]:
            stream.seek(0)
            if stream.write(patched) != len(patched):
                raise OSError("short launchd cache write")
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            if stream.read() != patched:
                raise OSError("launchd cache readback differs")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="create a separate patched cache; default reports only")
    parser.add_argument("--daemon-logs", action="store_true", help="also enable wifid's console log for diagnosis")
    args = parser.parse_args()
    patch = daemon_log_cache if args.daemon_logs else patch_launchd_cache
    patched, report = patch(args.input.read_bytes())
    if args.output:
        with args.output.open("xb") as stream:
            stream.write(patched)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
