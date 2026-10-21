#!/usr/bin/env python3
"""Boot one RAM image and recover logs after Android returns; never flash."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import struct

HERE = Path(__file__).resolve().parents[2]
CONSOLE_OFFSET, CONSOLE_LENGTH = 0x280000, 0x100000
MAX_PSTORE_BYTES = 8 * 1024 * 1024


def extract_xnu(data):
    start = data.find(b"[REDFIN RAMLOG v1")
    if start < 0:
        return b""
    end = data.find(b"--- BOOT HISTORY", start)
    return data[start:end if end >= 0 else len(data)]


def extract_ring(raw, offset=CONSOLE_OFFSET, length=CONSOLE_LENGTH):
    if offset < 0 or length < 12 or offset + length > len(raw):
        raise ValueError("truncated ramoops console region")
    signature, start, size = struct.unpack_from("<III", raw, offset)
    capacity = length - 12
    if signature != 0x43474244 or start >= capacity or size > capacity:
        raise ValueError("invalid DBGC signature/cursor/size")
    data = raw[offset + 12:offset + length]
    if size < capacity:
        if start != size:
            raise ValueError("inconsistent partial DBGC ring cursor")
        return data[:size]
    return data[start:] + data[:start]


def atomic(path, data):
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def valid_name(name):
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", name) is not None


class Cycle:
    def __init__(self, args):
        self.args, self.out = args, args.out
        self.manifest = {"started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         "status": "starting", "commands": [], "files": {}}

    def call(self, tool, command, timeout=15):
        prefix = [tool] + (["-s", self.args.serial] if self.args.serial else [])
        started = time.monotonic()
        try:
            result = subprocess.run(prefix + list(command), capture_output=True,
                                    timeout=timeout, check=False)
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            code, stdout, stderr = -1, b"", str(error).encode()
        # Avoid recording the selected serial or unrelated attached devices.
        error_text = stderr.decode(errors="replace")[:4096]
        if self.args.serial:
            error_text = error_text.replace(self.args.serial, "<selected device>")
        self.manifest["commands"].append({"tool": tool, "args": list(command), "returncode": code,
                                         "seconds": round(time.monotonic() - started, 2),
                                         "stderr": error_text})
        return code, stdout, stderr

    def adb(self, *command):
        return self.call("adb", command)

    def verify_android(self, verified_identity=False):
        if not verified_identity:
            code, output, _ = self.adb("exec-out", "getprop", "ro.product.device")
            if code or output.strip() != b"redfin":
                raise ValueError("Android identity is unavailable or is not redfin")
        code, output, _ = self.adb("exec-out", "id", "-u")
        if code or output.strip() != b"0":
            code, _, _ = self.adb("root")
            if code:
                raise ValueError("adb root failed; a root-enabled Android adbd is required")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                code, output, _ = self.adb("exec-out", "id", "-u")
                if code == 0 and output.strip() == b"0":
                    break
                time.sleep(2)
            else:
                raise ValueError("adbd did not return as root")
            code, output, _ = self.adb("exec-out", "getprop", "ro.product.device")
            if code or output.strip() != b"redfin":
                raise ValueError("device identity changed after adb root")

    def save(self, relative, data, status="ok"):
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic(path, data)
        self.manifest["files"][relative] = {"status": status, "bytes": len(data),
                                             "sha256": hashlib.sha256(data).hexdigest()}

    def pstore(self, stage):
        code, names, _ = self.adb("exec-out", "ls", "-1", "/sys/fs/pstore")
        if code:
            self.manifest[stage + "_pstore"] = {"status": "unavailable"}
            return []
        artifacts = []
        for name in names.decode(errors="replace").splitlines()[:128]:
            if not valid_name(name):
                continue
            code, data, _ = self.adb("exec-out", "head", "-c", str(MAX_PSTORE_BYTES + 1),
                                      "/sys/fs/pstore/" + name)
            if code or len(data) > MAX_PSTORE_BYTES:
                self.manifest["files"][stage + "/" + name] = {"status": "error-or-oversize"}
                continue
            relative = stage + "/" + name
            self.save(relative, data)
            artifacts.append((relative, data))
        self.manifest[stage + "_pstore"] = {"status": "ok", "count": len(artifacts)}
        return artifacts

    def raw_ramoops(self):
        # Capture before Android's delayed vendor ramoops script switches banks.
        code, raw, _ = self.adb("exec-out", "cat", "/dev/access-ramoops")
        if code or len(raw) != 0x400000:
            self.manifest["raw_ramoops"] = {"status": "unavailable", "bytes": len(raw)}
            return []
        self.save("after/alt-ramoops.raw", raw)
        try:
            data = extract_ring(raw)
            self.save("after/redfin-console.txt", data)
            return [("after/redfin-console.txt", data)]
        except ValueError as error:
            self.manifest["raw_ramoops"] = {"status": "invalid", "error": str(error)}
            return []

    def recover(self, verified_identity=False):
        self.verify_android(verified_identity)
        # Opening the raw misc device claims the alt bank and can race Android's
        # decrypt-and-mount service. Prefer pstore; raw access is opt-in only.
        artifacts = self.raw_ramoops() if self.args.raw_ramoops else []
        if self.args.ramoops_helper:
            remote = "/data/local/tmp/redfin-readramoops"
            code, _, _ = self.adb("push", str(self.args.ramoops_helper), remote)
            if code == 0:
                code, _, _ = self.adb("shell", "chmod", "700", remote)
            if code == 0:
                code, raw, _ = self.adb("exec-out", remote)
                if code == 0 and len(raw) <= MAX_PSTORE_BYTES:
                    self.save("after/alt-ramoops.raw", raw)
                    try:
                        data = extract_ring(raw)
                        self.save("after/redfin-console.txt", data)
                        artifacts.append(("after/redfin-console.txt", data))
                    except ValueError as error:
                        self.manifest["ramoops"] = {"status": "invalid", "error": str(error)}
                else:
                    self.manifest["ramoops"] = {"status": "helper-failed-or-oversize"}
        before_hashes = {entry.get("sha256") for name, entry in self.manifest["files"].items()
                         if name.startswith("before/")}
        deadline = time.monotonic() + self.args.timeout
        captured = dict(artifacts)
        while True:
            captured.update(self.pstore("after"))
            current = b"\n".join(data for name, data in captured.items()
                                   if self.manifest["files"][name]["sha256"] not in before_hashes)
            if (b"REDFIN userspace: init running as PID 1" in current and
                    b"REDFIN init: still alive" in current) or b"[REDFIN RAMLOG v1" in current or time.monotonic() >= deadline:
                break
            time.sleep(2)
        self.manifest["status"] = ("userspace-alive" if b"REDFIN userspace: init running as PID 1" in current
                                     and b"REDFIN init: still alive" in current else
                                     "logs-collected" if b"REDFIN" in current else "no-log")
        self.manifest["captured_bytes"] = len(current)
        xnu = extract_xnu(current)
        if xnu:
            self.save("xnu-console.txt", xnu)

    def run(self):
        try:
            if not self.args.collect_only:
                self.verify_android()
                self.pstore("before")
                image = self.args.image.resolve()
                self.manifest["image"] = {"path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
                code, _, _ = self.adb("reboot", "bootloader")
                if code:
                    raise ValueError("adb reboot bootloader failed")
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    code, output, error = self.call("fastboot", ["getvar", "product"])
                    if code == 0:
                        if not re.search(rb"(?:^|\n)(?:\(bootloader\) )?product:\s*redfin\s*(?:\r?\n|$)", output + error):
                            raise ValueError("fastboot identity is not redfin")
                        break
                    time.sleep(2)
                else:
                    raise ValueError("redfin did not appear in fastboot within 60 seconds")
                code, output, error = self.call("fastboot", ["boot", str(image)], timeout=30)
                self.save("fastboot.txt", output + error)
                if code:
                    raise ValueError("fastboot boot failed; see fastboot.txt")
                deadline = time.monotonic() + self.args.timeout
                while time.monotonic() < deadline:
                    code, output, _ = self.adb("exec-out", "getprop", "ro.product.device")
                    if code == 0 and output.strip() == b"redfin":
                        break
                    time.sleep(2)
                else:
                    self.manifest["status"] = "no-log"
                    self.manifest["reason"] = "Android did not return before timeout; boot outcome is unknown"
                    return 1
            self.recover(verified_identity=not self.args.collect_only)
            return 0 if self.manifest["status"] == "userspace-alive" else 1
        except (OSError, ValueError) as error:
            self.manifest.update(status="runner-error", error=str(error))
            return 1
        finally:
            atomic(self.out / "manifest.json", (json.dumps(self.manifest, indent=2) + "\n").encode())
            print(self.manifest["status"] + ": " + str(self.out / "manifest.json"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "logs/redfin" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for Android after boot")
    parser.add_argument("--serial")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--ramoops-helper", type=Path)
    parser.add_argument("--raw-ramoops", action="store_true", help="diagnostic only: may block Android's alt-bank switch")
    args = parser.parse_args(argv)
    if not args.collect_only and (not args.image or not args.image.is_file()):
        parser.error("an existing image is required unless --collect-only is used")
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")
    if args.ramoops_helper and not args.ramoops_helper.is_file():
        parser.error("--ramoops-helper must be an existing Android executable")
    try:
        args.out.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(str(error))
    return Cycle(args).run()


if __name__ == "__main__":
    sys.exit(main())
