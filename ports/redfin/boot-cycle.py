#!/usr/bin/env python3
"""Boot one RAM image and collect logs through Android or temporary recovery."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import struct
import stat
import zlib

HERE = Path(__file__).resolve().parents[2]
CONSOLE_OFFSET, CONSOLE_LENGTH = 0x280000, 0x100000
MAX_PSTORE_BYTES = 8 * 1024 * 1024
RAMOOPS_SHA256 = "7d80a3a0cf6a6050beb6baa95ae5808107f2d70a8ca11d4b61d225caf930d3d2"
DISK_FILESYSTEMS = {"ext4", "f2fs", "hfs", "hfsplus", "apfs", "vfat", "exfat", "erofs", "squashfs"}


def recovery_proof(image):
    """Reject a recovery image whose unattended timer could boot Android."""
    manifest = json.loads(image.with_name("manifest.json").read_text())
    checksum = hashlib.sha256(image.read_bytes()).hexdigest()
    if (manifest.get("image_sha256") != checksum or manifest.get("return_target") != "bootloader"
            or manifest.get("properties", {}).get("ro.redfin.offline_recovery") != "1"
            or manifest.get("properties", {}).get("ro.redfin.return_target") != "bootloader"
            or manifest.get("data_mount_actions") is not False
            or manifest.get("userdata_writes") is not False
            or manifest.get("recovery_ui_disabled") is not True):
        raise ValueError("recovery image needs a matching read-only manifest with return_target=bootloader")
    return {"path": str(image), "sha256": checksum, "return_target": "bootloader"}


def xnu_return_proof(image):
    """Require a matching build that arms the single-CPU PMIC bootloader return."""
    manifest = json.loads(image.with_name("manifest.json").read_text())
    checksum = hashlib.sha256(image.read_bytes()).hexdigest()
    if not isinstance(manifest, dict):
        raise ValueError("XNU recovery cycle requires an object build manifest")
    checksums = manifest.get("sha256")
    arguments = manifest.get("boot_args")
    tokens = arguments.split() if isinstance(arguments, str) else []
    if (not isinstance(checksums, dict) or checksums.get("redfin-xnu.img") != checksum
            or [token for token in tokens if token.startswith("redfinreturn=")] != ["redfinreturn=1"]
            or [token for token in tokens if token.startswith("cpus=")] != ["cpus=1"]):
        raise ValueError("XNU recovery cycle requires a matching image manifest with redfinreturn=1 and cpus=1")
    return {"sha256": checksum, "pmic_bootloader_return": True, "cpus": 1}


def verify_recovery_mounts(data):
    for line in data.decode(errors="strict").splitlines():
        fields = line.split()
        if (len(fields) != 6 or not fields[1].startswith("/")
                or not {"ro", "rw"}.intersection(fields[3].split(","))
                or not fields[4].isdigit() or not fields[5].isdigit()):
            raise ValueError("malformed recovery mount table")
        source, mountpoint, filesystem = fields[:3]
        if source.startswith(("/dev/block/", "/dev/dm-")) or filesystem in DISK_FILESYSTEMS:
            raise ValueError("offline recovery has a mounted disk filesystem: " + mountpoint)
    if not data.strip():
        raise ValueError("recovery mount table is empty")


def extract_xnu(data):
    start = data.find(b"[REDFIN RAMLOG v1")
    if start < 0:
        return b""
    end = data.find(b"--- BOOT HISTORY", start)
    return data[start:end if end >= 0 else len(data)]


def userspace_evidence(data):
    """Recognize the PID1 banner even when syscall tracing splits its writes."""
    xnu = extract_xnu(data)
    heartbeat_count = xnu.count(b"REDFIN init: still alive")
    pid = re.search(rb"REDFIN PID1: syscall \d+ return code=20 error=0 value=1(?:\r?\n|$)", xnu)
    banner = b"REDFIN userspace: init running as PID "
    alive = heartbeat_count > 0 and (banner + b"1" in xnu or (banner in xnu and pid is not None))
    return {"pid1_alive": alive, "getpid_1": pid is not None, "heartbeats": heartbeat_count}


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


def atomic(path, data, mode=None):
    temporary = path.with_name(path.name + ".partial")
    if mode is None:
        temporary.write_bytes(data)
    else:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), mode)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
    os.replace(temporary, path)


def valid_name(name):
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", name) is not None


def primed_metadata(data):
    """Validate the vendor mincrypt public block and cleared wrapped AES key."""
    if len(data) != 4096 or struct.unpack_from("<5I", data) != (0x4b6c6243, 0, 0x794b6250, 0x13, 524):
        raise ValueError("primed ramoops control/public block is invalid")
    end = 0x14 + 524
    if zlib.crc32(data[8:end]) != struct.unpack_from("<I", data, end)[0]:
        raise ValueError("primed ramoops public block CRC mismatch")
    if any(data[0x408:0x808]):
        raise ValueError("primed ramoops AES block was not cleared")


class Cycle:
    def __init__(self, args):
        self.args, self.out = args, args.out
        for name, default in {"recovery_image": None, "from_bootloader": False, "leave_bootloader": False,
                              "collect_only": False, "raw_ramoops": False, "ramoops_helper": None,
                              "ramoops_key_dir": None,
                              "timeout": 300}.items():
            if not hasattr(args, name):
                setattr(args, name, default)
        self.recovery_verified = False
        self.android_verified = False
        self.manifest = {"started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         "status": "starting", "commands": [], "files": {}}

    def call(self, tool, command, timeout=15, input_data=None):
        prefix = [tool] + (["-s", self.args.serial] if self.args.serial else [])
        started = time.monotonic()
        try:
            result = subprocess.run(prefix + list(command), capture_output=True,
                                    timeout=timeout, check=False, input=input_data)
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

    def adb(self, *command, input_data=None):
        if input_data is not None:
            return self.call("adb", command, input_data=input_data)
        return self.call("adb", command)

    def verify_ramoops_key_dir(self):
        if not self.args.recovery_image or self.args.ramoops_helper:
            raise ValueError("--ramoops-key-dir requires recovery and cannot be combined with --ramoops-helper")
        self.key_files = {name: self.args.ramoops_key_dir / name for name in ("priv.pem", "pub.pem", "ramoops")}
        for name, path in self.key_files.items():
            item = path.lstat()
            if not stat.S_ISREG(item.st_mode) or item.st_uid != os.geteuid():
                raise ValueError("ramoops key inputs must be regular files owned by the current user")
            if name.endswith(".pem") and (stat.S_IMODE(item.st_mode) != 0o600 or not 0 < item.st_size <= 65536):
                raise ValueError("ramoops PEM files must have mode 0600 and a valid size")
        if hashlib.sha256(self.key_files["ramoops"].read_bytes()).hexdigest() != RAMOOPS_SHA256:
            raise ValueError("ramoops binary SHA256 does not match the verified vendor executable")

    def verify_recovery_storage(self):
        code, mounts, _ = self.adb("exec-out", "cat", "/proc/mounts")
        if code:
            raise ValueError("cannot verify recovery mount state")
        verify_recovery_mounts(mounts)
        code, swaps, _ = self.adb("exec-out", "cat", "/proc/swaps")
        if code or len(swaps.splitlines()) != 1 or not swaps.startswith(b"Filename"):
            raise ValueError("offline recovery has active or unverifiable swap")

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
        self.android_verified = True

    def wait_fastboot(self, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code, output, error = self.call("fastboot", ["getvar", "product"])
            if code == 0:
                if not re.search(rb"(?:^|\n)(?:\(bootloader\) )?product:\s*redfin\s*(?:\r?\n|$)", output + error):
                    raise ValueError("fastboot identity is not redfin")
                return True
            time.sleep(2)
        return False

    def boot(self, image, log_name):
        code, output, error = self.call("fastboot", ["boot", str(image)], timeout=30)
        self.save(log_name, output + error)
        if code:
            raise ValueError("fastboot boot failed; see " + log_name)

    def wait_adb(self, recovery=False):
        deadline = time.monotonic() + self.args.timeout
        property_name = "ro.redfin.offline_recovery" if recovery else "ro.product.device"
        expected = b"1" if recovery else b"redfin"
        while time.monotonic() < deadline:
            code, output, _ = self.adb("exec-out", "getprop", property_name)
            if code == 0 and output.strip() == expected:
                return True
            time.sleep(2)
        return False

    def verify_recovery(self):
        for command, expected in ((["getprop", "ro.product.device"], b"redfin"),
                                  (["getprop", "ro.redfin.offline_recovery"], b"1"),
                                  (["id", "-u"], b"0"),
                                  (["getprop", "ro.redfin.return_target"], b"bootloader")):
            code, output, _ = self.adb("exec-out", *command)
            if code or output.strip() != expected:
                raise ValueError("expected root redfin offline recovery returning to bootloader")
        self.verify_recovery_storage()
        self.recovery_verified = True
        code, _, _ = self.adb("exec-out", "setprop", "ctl.stop", "recovery-return")
        if code:
            raise ValueError("cannot stop recovery-return timer")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            code, output, _ = self.adb("exec-out", "getprop", "init.svc.recovery-return")
            if code == 0 and output.strip() == b"stopped":
                self.manifest["recovery"] = {"verified": True, "disk_filesystems_mounted": False,
                                             "swap_active": False, "return_timer_stopped": True}
                return
            time.sleep(0.2)
        raise ValueError("recovery-return timer did not stop")

    def enter_recovery(self):
        self.boot(self.args.recovery_image.resolve(), "recovery-fastboot.txt")
        if not self.wait_adb(recovery=True):
            raise ValueError("offline recovery did not provide its ADB marker before timeout")

    def leave_bootloader(self):
        if not (self.recovery_verified if self.args.recovery_image else self.android_verified):
            raise ValueError("refusing to reboot an unverified ADB environment")
        checks = [(["getprop", "ro.product.device"], b"redfin"), (["id", "-u"], b"0")]
        if self.args.recovery_image:
            checks += [(["getprop", "ro.redfin.offline_recovery"], b"1"),
                       (["getprop", "ro.redfin.return_target"], b"bootloader")]
        for command, expected in checks:
            code, output, _ = self.adb("exec-out", *command)
            if code or output.strip() != expected:
                raise ValueError("ADB identity changed before bootloader reboot")
        code, _, _ = self.adb("reboot", "bootloader")
        if code or not self.wait_fastboot():
            raise ValueError("could not leave the device in verified redfin fastboot")
        self.manifest["left_in_bootloader"] = True

    def save(self, relative, data, status="ok", private=False):
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic(path, data, mode=0o600 if private else None)
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
        code, raw, _ = self.adb("exec-out", "head", "-c", str(0x400000 + 1), "/dev/access-ramoops")
        if code or len(raw) != 0x400000:
            self.manifest["raw_ramoops"] = {"status": "unavailable", "bytes": len(raw)}
            return []
        self.save("after/alt-ramoops.raw", raw, private=True)
        try:
            data = extract_ring(raw)
            self.save("after/redfin-console.txt", data)
            self.manifest["raw_ramoops"] = {"status": "ok", "bytes": len(raw)}
            return [("after/redfin-console.txt", data)]
        except ValueError as error:
            self.manifest["raw_ramoops"] = {"status": "invalid", "error": str(error)}
            return []

    def ramoops_metadata(self, relative):
        code, data, _ = self.adb("exec-out", "head", "-c", "4097", "/dev/access-metadata")
        if code or len(data) != 4096:
            raise ValueError("ramoops metadata capture must be exactly 4096 bytes")
        self.save(relative, data, private=True)
        return data

    def keyed_ramoops(self, artifacts):
        # Capture every input before changing next boot's encryption metadata.
        raw_path = self.out / "after/alt-ramoops.raw"
        if not raw_path.is_file() or raw_path.stat().st_size != 0x400000:
            raise ValueError("raw ramoops capture failed; public-key priming was not attempted")
        metadata = self.ramoops_metadata("after/alt-ramoops.metadata")
        if not artifacts:
            spec = importlib.util.spec_from_file_location("redfin_decrypt_ramoops", Path(__file__).with_name("decrypt-ramoops.py"))
            decryptor = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(decryptor)
            try:
                plaintext = decryptor.decrypt_capture(raw_path.read_bytes(), metadata, self.key_files["priv.pem"])
                self.save("after/alt-ramoops.decrypted.raw", plaintext, private=True)
                console = extract_ring(plaintext)
                self.save("after/redfin-console.txt", console)
                artifacts = [("after/redfin-console.txt", console)]
                self.manifest["ramoops_decryption"] = {"status": "authenticated"}
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                self.manifest["ramoops_decryption"] = {"status": "failed", "error": str(error)}
                raise ValueError("ramoops authentication/extraction failed; public-key priming was not attempted") from error
        else:
            self.manifest["ramoops_decryption"] = {"status": "plaintext-capture"}
        self.prime_ramoops_public()
        return artifacts

    def prime_ramoops_public(self):
        self.manifest["ramoops_public_prime"] = {"status": "starting"}
        try:
            code, _, _ = self.adb("push", str(self.key_files["ramoops"]), "/tmp/redfin-ramoops")
            if code:
                raise ValueError("cannot push verified ramoops executable")
            setup = b"set -eu\numask 077\nmkdir -p /tmp/redfin-ramoops-public\nchmod 700 /tmp/redfin-ramoops /tmp/redfin-ramoops-public\n"
            code, _, _ = self.adb("shell", "-T", "sh", "-s", input_data=setup)
            if code:
                raise ValueError("cannot prepare RAM-only public-key directory")
            code, _, _ = self.adb("push", str(self.key_files["pub.pem"]), "/tmp/redfin-ramoops-public/pub.pem")
            if code:
                raise ValueError("cannot push ramoops public key")
            prime = (b"set -eu\nchmod 600 /tmp/redfin-ramoops-public/pub.pem\n"
                     b"LD_LIBRARY_PATH=/system/lib64 /system/bin/linker64 /tmp/redfin-ramoops -l -c -k /tmp/redfin-ramoops-public\n")
            code, _, _ = self.adb("shell", "-T", "sh", "-s", input_data=prime)
            if code:
                raise ValueError("ramoops public-key priming failed")
            primed_metadata(self.ramoops_metadata("after/primed-ramoops.metadata"))
            self.verify_recovery_storage()
            self.manifest["ramoops_public_prime"] = {"status": "verified", "aes_block_clear": True}
        except (OSError, ValueError) as error:
            self.manifest["ramoops_public_prime"] = {"status": "failed", "error": str(error)}
            raise

    def recover(self, verified_identity=False, recovery=False):
        if recovery:
            self.verify_recovery()
        else:
            self.verify_android(verified_identity)
        # Opening the raw misc device claims the alt bank and can race Android's
        # decrypt-and-mount service. Prefer pstore; raw access is opt-in only.
        artifacts = self.raw_ramoops() if recovery or self.args.raw_ramoops else []
        if self.args.ramoops_key_dir:
            artifacts = self.keyed_ramoops(artifacts)
        if self.args.ramoops_helper:
            remote = "/tmp/redfin-readramoops" if recovery else "/data/local/tmp/redfin-readramoops"
            code, _, _ = self.adb("push", str(self.args.ramoops_helper), remote)
            if code == 0:
                code, _, _ = self.adb("shell", "chmod", "700", remote)
            if code == 0:
                code, raw, _ = self.adb("exec-out", remote)
                if code == 0 and len(raw) <= MAX_PSTORE_BYTES:
                    self.save("after/helper-ramoops.raw", raw, private=True)
                    try:
                        data = extract_ring(raw)
                        self.save("after/redfin-console.txt", data)
                        artifacts.append(("after/redfin-console.txt", data))
                    except ValueError as error:
                        self.manifest["ramoops"] = {"status": "invalid", "error": str(error)}
                else:
                    self.manifest["ramoops"] = {"status": "helper-failed-or-oversize"}
        before_hashes = {entry.get("sha256") for name, entry in self.manifest["files"].items()
                         if name.startswith("before/") and entry.get("sha256")}
        self.manifest["log_freshness"] = ({"status": "baseline-compared"} if before_hashes else
            {"status": "unproven", "reason": "No pre-boot baseline; status describes saved log observations, not proof of this boot"})
        deadline = time.monotonic() + self.args.timeout
        captured = dict(artifacts)
        while True:
            captured.update(self.pstore("after"))
            current = b"\n".join(data for name, data in captured.items()
                                   if self.manifest["files"][name]["sha256"] not in before_hashes)
            if userspace_evidence(current)["pid1_alive"] or b"[REDFIN RAMLOG v1" in current or time.monotonic() >= deadline:
                break
            time.sleep(2)
        evidence = userspace_evidence(current)
        self.manifest["userspace"] = evidence
        self.manifest["status"] = ("userspace-alive" if evidence["pid1_alive"] else
                                     "logs-collected" if b"REDFIN" in current else "no-log")
        self.manifest["captured_bytes"] = len(current)
        xnu = extract_xnu(current)
        if xnu:
            self.save("xnu-console.txt", xnu)

    def run(self):
        result = 1
        try:
            if self.args.ramoops_key_dir:
                self.verify_ramoops_key_dir()
            if self.args.recovery_image:
                self.manifest["recovery_image"] = recovery_proof(self.args.recovery_image.resolve())
                if not self.args.collect_only:
                    self.manifest["xnu_return"] = xnu_return_proof(self.args.image.resolve())
            if not self.args.collect_only:
                if not self.args.from_bootloader:
                    self.verify_android()
                    self.pstore("before")
                    code, _, _ = self.adb("reboot", "bootloader")
                    if code:
                        raise ValueError("adb reboot bootloader failed")
                image = self.args.image.resolve()
                self.manifest["image"] = {"path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
                if not self.wait_fastboot():
                    raise ValueError("redfin did not appear in fastboot within 60 seconds")
                self.boot(image, "fastboot.txt")
                if self.args.recovery_image:
                    # Avoid observing the original fastboot transport during
                    # the immediate handoff from ABL to the RAM kernel.
                    time.sleep(2)
                    if not self.wait_fastboot(self.args.timeout):
                        self.manifest.update(status="no-log", reason="XNU did not return to fastboot before timeout; boot outcome is unknown")
                        return 1
                    self.enter_recovery()
                elif not self.wait_adb():
                    self.manifest.update(status="no-log", reason="Android did not return before timeout; boot outcome is unknown")
                    return 1
            elif self.args.from_bootloader:
                if not self.wait_fastboot():
                    raise ValueError("redfin did not appear in fastboot within 60 seconds")
                self.enter_recovery()
            self.recover(verified_identity=not self.args.collect_only,
                         recovery=bool(self.args.recovery_image))
            result = 0 if self.manifest["status"] == "userspace-alive" else 1
        except (OSError, ValueError) as error:
            self.manifest.update(status="runner-error", error=str(error))
        finally:
            if self.args.leave_bootloader:
                if not (self.recovery_verified if self.args.recovery_image else self.android_verified):
                    self.manifest["left_in_bootloader"] = False
                    self.manifest["leave_reason"] = "ADB environment was not verified; no ADB reboot was issued"
                else:
                    try:
                        self.leave_bootloader()
                    except (OSError, ValueError) as error:
                        self.manifest.update(status="runner-error", error=str(error))
                        result = 1
            atomic(self.out / "manifest.json", (json.dumps(self.manifest, indent=2) + "\n").encode())
            print(self.manifest["status"] + ": " + str(self.out / "manifest.json"))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "logs/redfin" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--timeout", type=int, default=300, help="seconds per boot-return, ADB and log wait")
    parser.add_argument("--serial")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--recovery-image", type=Path, help="temporary root-ADB image with a matching bootloader-return manifest.json")
    parser.add_argument("--from-bootloader", action="store_true", help="start in fastboot; skip initial Android access")
    parser.add_argument("--leave-bootloader", action="store_true", help="reboot to verified redfin fastboot after collecting")
    parser.add_argument("--ramoops-helper", type=Path)
    parser.add_argument("--ramoops-key-dir", type=Path, help="host-only priv.pem, public pub.pem (both 0600), and verified vendor ramoops executable; recovery only")
    parser.add_argument("--raw-ramoops", action="store_true", help="diagnostic only: may block Android's alt-bank switch")
    args = parser.parse_args(argv)
    if not args.collect_only and (not args.image or not args.image.is_file()):
        parser.error("an existing image is required unless --collect-only is used")
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")
    if args.ramoops_helper and not args.ramoops_helper.is_file():
        parser.error("--ramoops-helper must be an existing Android executable")
    if args.recovery_image and not args.recovery_image.is_file():
        parser.error("--recovery-image must be an existing RAM boot image")
    if args.collect_only and args.from_bootloader and not args.recovery_image:
        parser.error("--collect-only --from-bootloader requires --recovery-image")
    try:
        args.out.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(str(error))
    return Cycle(args).run()


if __name__ == "__main__":
    sys.exit(main())
