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
    encoded = plistlib.dumps(expected, fmt=plistlib.FMT_BINARY, sort_keys=False)
    padding = len(original) - len(encoded)
    if padding < 0:
        raise ValueError("patched cache grew; cannot preserve the existing allocation")
    trailer = bytearray(encoded[-32:])
    table_offset = struct.unpack_from(">Q", trailer, 24)[0]
    # Object offsets stay valid. Only the offset table's own location moves.
    result = encoded[:table_offset] + bytes(padding) + encoded[table_offset:-32]
    struct.pack_into(">Q", trailer, 24, table_offset + padding)
    result += trailer
    if len(result) != len(original) or plistlib.loads(result) != expected:
        raise ValueError("same-size cache failed complete semantic verification")
    report.update(removed_gate=STOCK_NODES, padding_bytes=padding,
                  after_sha256=hashlib.sha256(result).hexdigest())
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
    args = parser.parse_args()
    patched, report = patch_launchd_cache(args.input.read_bytes())
    if args.output:
        with args.output.open("xb") as stream:
            stream.write(patched)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
