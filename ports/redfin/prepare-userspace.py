#!/usr/bin/env python3
"""Extract the verified D22AP iOS images; optionally mount them read-only on macOS.

No root-image writes, device access, global installs, or ownership changes.
"""
import argparse
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "OS": "087-86698-044.dmg",
    "Cryptex1,SystemOS": "087-86593-047.dmg",
    "Cryptex1,AppOS": "087-86715-047.dmg",
    "DeviceTree": "Firmware/all_flash/DeviceTree.d22ap.im4p",
}
spec = importlib.util.spec_from_file_location("redfin_fetch", Path(__file__).with_name("fetch-userspace.py"))
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def write_atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def reuse_readonly_mount(image, mount):
    """Reuse only this exact image, mounted read-only with real ownership."""
    response = subprocess.run(["hdiutil", "info", "-plist"], capture_output=True,
                              check=True, timeout=30)
    for attached in plistlib.loads(response.stdout).get("images", []):
        if Path(attached.get("image-path", "")).resolve() != image.resolve():
            continue
        entities = attached.get("system-entities", [])
        if not any(Path(entity.get("mount-point", "/")).resolve() == mount.resolve()
                   for entity in entities if entity.get("mount-point")):
            continue
        info = plistlib.loads(subprocess.run(["diskutil", "info", "-plist", str(mount)],
                             capture_output=True, check=True, timeout=30).stdout)
        if not info.get("GlobalPermissionsEnabled") or not os.statvfs(mount).f_flag & os.ST_RDONLY:
            raise ValueError("existing source mount must be read-only with ownership enabled: " + str(mount))
        return entities
    return None


def raw_adt(im4p):
    sys.path.insert(0, str(ROOT / "tools"))
    import adt
    tag, start, end = adt.der(im4p, 0)
    if tag != 0x30 or end != len(im4p):
        raise ValueError("invalid DeviceTree IM4P wrapper")
    values = []
    while start < end:
        tag, value_start, value_end = adt.der(im4p, start)
        if value_end > end:
            raise ValueError("invalid DeviceTree IM4P item")
        values.append((tag, im4p[value_start:value_end]))
        start = value_end
    if (len(values) < 4 or values[0][1] != b"IM4P" or values[1][1] != b"dtre"
            or any(tag == 4 for tag, _ in values[4:])):
        raise ValueError("unexpected or encrypted DeviceTree IM4P")
    payload = values[3][1]
    if payload[:4] == b"bvx2":
        library = ctypes.CDLL("/usr/lib/libcompression.dylib")
        library.compression_decode_buffer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                                       ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
        library.compression_decode_buffer.restype = ctypes.c_size_t
        output = ctypes.create_string_buffer(4 * 1024 * 1024)
        source = ctypes.create_string_buffer(payload)
        length = library.compression_decode_buffer(output, len(output), source, len(payload), None, 0x801)
        if not 0 < length < len(output):
            raise ValueError("native LZFSE decode failed")
        payload = output.raw[:length]
    tree, end = adt.parse(payload)
    if end != len(payload) or not any(child.name == "product" for child in tree.children):
        raise ValueError("invalid decompressed D22AP ADT")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipsw", type=Path, default=ROOT / "research/ipsw-redfin/iPhoneX16.7.16.ipsw")
    parser.add_argument("--out", type=Path, default=ROOT / "research/ipsw-redfin/extracted")
    parser.add_argument("--mount-readonly", action="store_true", help="leave images mounted under OUT/mounts; detach commands are recorded")
    args = parser.parse_args(argv)
    ipsw, out = args.ipsw.resolve(), args.out.resolve()
    research = (ROOT / "research").resolve()
    if research not in out.parents:
        parser.error("--out must remain under this repository's ignored research directory")
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / ".prepare.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print("prepare-userspace: another preparation is active; existing manifests were preserved", file=sys.stderr)
        return 2
    manifest = {"ipsw": str(ipsw), "success": False, "files": {}, "mounts": []}
    try:
        if not ipsw.is_file() or ipsw.stat().st_size != fetch.SIZE or fetch.sha256(ipsw) != fetch.SHA256:
            raise ValueError("IPSW must match the pinned iPhone X 16.7.16 size and SHA256")
        with zipfile.ZipFile(ipsw) as archive:
            build_bytes = archive.read("BuildManifest.plist")
            build = plistlib.loads(build_bytes)
            if build.get("ProductBuildVersion") != "20H392" or build.get("ProductVersion") != "16.7.16":
                raise ValueError("unexpected iOS version in BuildManifest")
            identities = [item for item in build["BuildIdentities"]
                          if item["Info"].get("DeviceClass") == "d22ap"
                          and item["Info"].get("RestoreBehavior") == "Erase"]
            if len(identities) != 1:
                raise ValueError("expected exactly one D22AP Erase identity")
            identity = identities[0]
            for component, name in EXPECTED.items():
                if identity["Manifest"][component]["Info"]["Path"] != name:
                    raise ValueError("unexpected %s component path" % component)
            write_atomic(out / "BuildManifest.plist", build_bytes)
            entries = [archive.getinfo(name) for name in EXPECTED.values()]
            required = sum(item.file_size for item in entries if not (out / Path(item.filename).name).exists())
            if shutil.disk_usage(out).free < required + 128 * 1024 * 1024:
                raise ValueError("insufficient space for extracted DMGs")
            for entry in entries:
                target = out / Path(entry.filename).name
                if target.exists():
                    if not target.is_file() or target.is_symlink() or target.stat().st_size != entry.file_size:
                        raise ValueError("refusing to overwrite mismatched artifact: " + str(target))
                else:
                    partial = target.with_name(target.name + ".partial")
                    if partial.is_symlink():
                        raise ValueError("refusing symlink partial artifact")
                    print("Extracting " + entry.filename, flush=True)
                    with archive.open(entry) as source, partial.open("wb") as dest:
                        shutil.copyfileobj(source, dest, 4 * 1024 * 1024)
                    partial.replace(target)
                checksum, crc = hashlib.sha256(), 0
                with target.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                        checksum.update(chunk)
                        crc = zlib.crc32(chunk, crc)
                if crc != entry.CRC:
                    raise ValueError("extracted ZIP CRC mismatch: " + str(target))
                manifest["files"][target.name] = {"bytes": target.stat().st_size, "sha256": checksum.hexdigest()}
        adt_path = out / "d22ap.adt"
        write_atomic(adt_path, raw_adt((out / "DeviceTree.d22ap.im4p").read_bytes()))
        manifest["files"][adt_path.name] = {"bytes": adt_path.stat().st_size, "sha256": fetch.sha256(adt_path)}
        if args.mount_readonly:
            for label, component in (("os", "OS"), ("systemos", "Cryptex1,SystemOS"), ("appos", "Cryptex1,AppOS")):
                mount = out / "mounts" / label
                mount.mkdir(parents=True, exist_ok=True)
                image = out / EXPECTED[component]
                entities = reuse_readonly_mount(image, mount)
                reused = entities is not None
                if not reused and (mount.is_mount() or any(mount.iterdir())):
                    raise ValueError("mount directory is not empty: " + str(mount))
                if not reused:
                    command = ["hdiutil", "attach", "-readonly", "-nobrowse", "-owners", "on", "-mountpoint", str(mount), "-plist", str(image)]
                    result = subprocess.run(command, capture_output=True, check=True, timeout=180)
                    entities = plistlib.loads(result.stdout).get("system-entities", [])
                manifest["mounts"].append({"label": label, "path": str(mount), "read_only": True,
                                            "reused": reused, "entities": entities,
                                            "detach": ["hdiutil", "detach", str(mount)]})
        manifest["success"] = True
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        manifest["error"] = str(error)
        print("prepare-userspace: " + str(error), file=sys.stderr)
    # Failed duplicates cannot erase the record of an already successful run.
    data = (json.dumps(manifest, indent=2, default=str) + "\n").encode()
    write_atomic(out / "prepare-attempt.json", data)
    previous_success = False
    if (out / "prepare.json").is_file():
        try:
            previous_success = bool(json.loads((out / "prepare.json").read_text()).get("success"))
        except (ValueError, OSError):
            pass
    if manifest["success"] or not previous_success:
        write_atomic(out / "prepare.json", data)
    lock.close()
    print(("Prepared: " if manifest["success"] else "Preparation incomplete: ") + str(out))
    return 0 if manifest["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
