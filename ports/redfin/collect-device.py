#!/usr/bin/env python3
"""Collect read-only Pixel 5 bring-up inputs through an already available adbd."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


FDT_MAGIC = 0xD00DFEED
ARTIFACTS = {
    "product-device.txt": ("getprop", "ro.product.device"),
    "bootloader.txt": ("getprop", "ro.bootloader"),
    "device.dtb": ("cat", "/sys/firmware/fdt"),
    "iomem.txt": ("cat", "/proc/iomem"),
    "cpuinfo.txt": ("cat", "/proc/cpuinfo"),
}


def validate_fdt(data):
    """Validate an FDT v17-compatible header and its bounded, separate blocks."""
    if len(data) < 40:
        raise ValueError("truncated FDT header (need 40 bytes)")
    (magic, size, off_struct, off_strings, off_reserve, version, compatible,
     boot_cpu, size_strings, size_struct) = struct.unpack_from(">10I", data)
    if magic != FDT_MAGIC:
        raise ValueError("bad FDT magic (expected big-endian 0xd00dfeed)")
    if version < 17 or compatible > 17 or compatible > version:
        raise ValueError("unsupported FDT version/compatibility")
    if size < 40 or size > len(data):
        raise ValueError("FDT totalsize is outside the captured data")
    if off_struct % 4 or size_struct % 4 or off_reserve % 8:
        raise ValueError("misaligned FDT structure/reservation offset")
    blocks = []
    for name, offset, length in (("structure", off_struct, size_struct),
                                 ("strings", off_strings, size_strings)):
        if offset < 40 or offset > size or length > size - offset:
            raise ValueError("FDT %s block is outside totalsize" % name)
        blocks.append((offset, offset + length, name))
    if size_struct < 4:
        raise ValueError("empty FDT structure block")
    if off_reserve < 40 or off_reserve > size - 16:
        raise ValueError("FDT reservation map is outside totalsize")
    cursor = off_reserve
    while True:
        if cursor > size - 16:
            raise ValueError("unterminated FDT reservation map")
        address, length = struct.unpack_from(">QQ", data, cursor)
        cursor += 16
        if not address and not length:
            break
    blocks.append((off_reserve, cursor, "reservation"))
    for index, (start, end, name) in enumerate(blocks):
        for other_start, other_end, other_name in blocks[index + 1:]:
            if start < other_end and other_start < end:
                raise ValueError("overlapping FDT %s/%s blocks" % (name, other_name))
    return {"totalsize": size, "version": version,
            "last_compatible_version": compatible, "boot_cpu_id": boot_cpu}


def adb_read(arguments, serial=None):
    command = ["adb"]
    if serial:
        command += ["-s", serial]
    command += ["exec-out", *arguments]
    try:
        result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    except subprocess.TimeoutExpired:
        return None, "adb command timed out after 20 seconds"
    except OSError as error:
        return None, "cannot execute adb: %s" % error
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        if serial:
            detail = detail.replace(serial, "<selected device>")
        return None, "adb exited %d: %s" % (result.returncode, detail[:4096])
    return result.stdout, None


def write_atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def collect(out, serial=None, force=False):
    out = Path(out)
    if out.is_symlink() or (out.exists() and not out.is_dir()):
        raise ValueError("output must be a directory, not a file or symlink")
    if out.exists() and not force:
        raise FileExistsError("output already exists; choose another --out or use --force")
    out.mkdir(parents=True, exist_ok=force)
    # --force replaces only this collector's known outputs. A failed read must
    # never leave an old dump looking like the current capture.
    for name in (*ARTIFACTS, "manifest.json"):
        path = out / name
        if path.exists() or path.is_symlink():
            if path.is_dir() and not path.is_symlink():
                raise ValueError("output artifact is a directory: %s" % path)
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "expected_product": "redfin",
        "product": None,
        "success": False,
        "files": {},
    }

    def capture(name):
        data, error = adb_read(ARTIFACTS[name], serial)
        path = out / name
        if error:
            path.unlink(missing_ok=True)
            if name == "device.dtb":
                error += ("; /sys/firmware/fdt may require a root-enabled adbd. "
                          "This collector does not enable root or invoke su.")
            manifest["files"][name] = {"status": "error", "error": error}
            return None
        write_atomic(path, data)
        manifest["files"][name] = {
            "status": "ok", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        return data

    product_data = capture("product-device.txt")
    product = None if product_data is None else product_data.decode(
        "utf-8", errors="replace").strip()
    manifest["product"] = product
    if product != "redfin":
        if product_data is not None:
            manifest["files"]["product-device.txt"].update(
                status="invalid", error="expected redfin, received %r" % product)
        for name in ARTIFACTS:
            if name != "product-device.txt":
                (out / name).unlink(missing_ok=True)
                manifest["files"][name] = {
                    "status": "skipped", "error": "redfin identity was not verified"}
    else:
        capture("bootloader.txt")
        dtb = capture("device.dtb")
        if dtb is not None:
            try:
                manifest["files"]["device.dtb"]["fdt"] = validate_fdt(dtb)
            except ValueError as error:
                manifest["files"]["device.dtb"].update(status="invalid", error=str(error))
        capture("iomem.txt")
        capture("cpuinfo.txt")
        manifest["success"] = manifest["files"]["device.dtb"]["status"] == "ok"
    write_atomic(out / "manifest.json",
                 (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if manifest["success"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="select an adb device; never written to the manifest")
    parser.add_argument("--out", type=Path, default=Path("research/redfin"),
                        help="capture directory (default: research/redfin; ignored by git)")
    parser.add_argument("--force", action="store_true", help="replace previous collector outputs")
    args = parser.parse_args(argv)
    try:
        status = collect(args.out, serial=args.serial, force=args.force)
        if status:
            manifest = json.loads((args.out / "manifest.json").read_text())
            for name in ("product-device.txt", "device.dtb"):
                entry = manifest["files"][name]
                if entry["status"] in ("error", "invalid"):
                    print("collect-device: %s: %s" % (name, entry["error"]), file=sys.stderr)
    except (OSError, ValueError) as error:
        print("collect-device: %s" % error, file=sys.stderr)
        return 2
    print("%s: %s" % ("collected" if status == 0 else "incomplete capture",
                       args.out / "manifest.json"))
    return status


if __name__ == "__main__":
    sys.exit(main())
