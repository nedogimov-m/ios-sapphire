#!/usr/bin/env python3
"""Fetch the pinned official iPhone X iOS 16.7.16 IPSW into ignored research."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
URL = ("https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-77006/"
       "1158E502-D76D-4226-AA06-ED5E30CD1111/"
       "iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw")
SIZE = 6171035648
SHA256 = "ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb"


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "research/ipsw-redfin/iPhoneX16.7.16.ipsw")
    parser.add_argument("--max-seconds", type=int, default=7200, help="bounded curl transfer time")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.max_seconds <= 86400:
        parser.error("--max-seconds must be in [1, 86400]")
    target = args.out.resolve()
    research = (ROOT / "research").resolve()
    if research not in target.parents:
        parser.error("--out must remain under this repository's ignored research directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    manifest_path = target.with_name(target.name + ".json")
    manifest = {"url": URL, "identifier": "iPhone10,3", "version": "16.7.16", "build": "20H392",
                "expected_bytes": SIZE, "expected_sha256": SHA256, "success": False,
                "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        if target.exists():
            candidate = target
        elif args.verify_only:
            raise ValueError("verified IPSW does not exist")
        else:
            if partial.is_symlink() or (partial.exists() and not partial.is_file()):
                raise ValueError("partial path is not a regular file")
            have = partial.stat().st_size if partial.exists() else 0
            if have > SIZE:
                raise ValueError("partial download is larger than the pinned IPSW")
            if shutil.disk_usage(target.parent).free < SIZE - have + 128 * 1024 * 1024:
                raise ValueError("insufficient free disk space for the IPSW")
            if have < SIZE:
                print("Downloading official iOS 16.7.16 IPSW (%d bytes; resume at %d)" % (SIZE, have), flush=True)
                command = ["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                           "--retry", "3", "--connect-timeout", "30", "--max-time", str(args.max_seconds),
                           "--continue-at", "-", "--output", str(partial), URL]
                subprocess.run(command, check=True, timeout=args.max_seconds * 4 + 180)
            candidate = partial
        actual_size = candidate.stat().st_size
        manifest["bytes"] = actual_size
        if actual_size != SIZE:
            raise ValueError("IPSW length mismatch: %d != %d" % (actual_size, SIZE))
        print("Verifying SHA256", flush=True)
        actual_hash = sha256(candidate)
        manifest["sha256"] = actual_hash
        if actual_hash != SHA256:
            raise ValueError("IPSW SHA256 mismatch; file preserved for inspection")
        if candidate == partial:
            partial.replace(target)
        manifest["success"] = True
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        manifest["error"] = str(error)
        print("fetch-userspace: " + str(error), file=sys.stderr)
    manifest["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(manifest_path)
    if manifest["success"]:
        print("Verified: " + str(target))
    return 0 if manifest["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
