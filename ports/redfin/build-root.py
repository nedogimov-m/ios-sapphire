#!/usr/bin/env python3
"""Build a local HFSX iOS base root without sudo; never access a phone.

Uses the extracted D22AP images from prepare-userspace.py. Records original
ownership before copying, then restores it offline by destination CNID. This
prepares the base filesystem and cryptex links; platform-specific root tweaks
and boot verification remain separate steps.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import checkpoint_userland
import photos_userland
from ports.redfin import ui_userland,gui_check_userland
import wifi_userland

ROOT = Path(__file__).resolve().parents[2]
IMAGES = {"os": "087-86698-044.dmg", "systemos": "087-86593-047.dmg", "appos": "087-86715-047.dmg"}
PREFIX = {"os": "", "systemos": "private/preboot/Cryptexes/OS", "appos": "private/preboot/Cryptexes/App"}


def atomic(path, data):
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


class Builder:
    def __init__(self, args):
        self.args, self.out = args, args.out.resolve()
        self.manifest = {"success": False, "stage": "incomplete", "commands": [],
                         "blocked": [], "sources": {}, "mounts": []}
        self.attachments, self.metadata = [], {}
        self.empty_files = {label: [] for label in IMAGES}
        self.log = None

    def run(self, command, capture=False):
        command = [str(part) for part in command]
        self.manifest["commands"].append(command)
        if capture:
            result = subprocess.run(command, capture_output=True, check=False, timeout=3600)
            self.log.write(result.stderr.decode(errors="replace"))
        else:
            self.log.flush()
            result = subprocess.run(command, stdout=self.log, stderr=self.log, check=False, timeout=3600)
        if result.returncode:
            raise ValueError("command failed (%d): %s; see build.log" % (result.returncode, command[0]))
        return result.stdout if capture else None

    def attach(self, image, mount=None, readonly=True, owners=True):
        command = ["hdiutil", "attach", "-nobrowse", "-plist"]
        command += ["-readonly"] if readonly else []
        if mount is None:
            command += ["-nomount"]
        else:
            mount.mkdir(parents=True, exist_ok=True)
            command += ["-owners", "on" if readonly and owners else "off", "-mountpoint", mount]
        command.append(image)
        response = plistlib.loads(self.run(command, capture=True))
        entities = response.get("system-entities", [])
        device = next((item["dev-entry"] for item in entities if item.get("dev-entry")), None)
        if device is None or not device.startswith("/dev/disk"):
            raise ValueError("hdiutil did not report its image device")
        record = {"image": str(image), "device": device, "readonly": readonly,
                  "mount": str(mount) if mount else None}
        self.attachments.append(record)
        self.manifest["mounts"].append(record)
        return record

    def detach(self, record):
        self.run(["hdiutil", "detach", record["device"]])
        self.attachments.remove(record)
        record["detached"] = True

    def scan(self, root, prefix):
        def failed(error):
            self.manifest["blocked"].append({"path": str(error.filename), "error": str(error)})
        seen = set()
        for directory, folders, files in os.walk(root, followlinks=False, onerror=failed):
            paths = [Path(directory)] + [Path(directory) / name for name in folders + files]
            for path in paths:
                relative = path.relative_to(root)
                destination = str(Path(prefix) / relative) if prefix else str(relative)
                if destination == ".":
                    destination = ""
                try:
                    item = path.lstat()
                except OSError as error:
                    failed(error)
                    continue
                self.metadata[destination] = {"uid": item.st_uid, "gid": item.st_gid,
                    "mode": stat.S_IMODE(item.st_mode), "kind": stat.S_IFMT(item.st_mode), "flags": item.st_flags}
                if stat.S_ISREG(item.st_mode) and not os.access(path, os.R_OK):
                    self.manifest["blocked"].append({"path": str(path), "error": "file content is not readable with original ownership"})
                seen.add(destination)
        return len(seen)

    def resolve_protected(self, sources):
        """Use a separate read-only copy view while retaining genuine owners.

        Existing metadata comes only from owners-on. The pinned raw APFS reader
        supplies metadata for paths hidden behind protected directories, and
        cross-checks the original protected-directory metadata before copying.
        """
        spec = importlib.util.spec_from_file_location("redfin_apfs_metadata", ROOT / "ports/redfin/apfs-metadata.py")
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        initial = list(self.manifest["blocked"])
        self.manifest["originally_blocked"] = initial
        self.manifest["protected_metadata"] = {}
        self.manifest["copy_view_counts"] = {}
        unresolved = []
        for label, source in list(sources.items()):
            blocked = []
            for entry in initial:
                try:
                    blocked.append(str(Path(entry["path"]).relative_to(source)))
                except ValueError:
                    pass
            if not blocked:
                continue
            image = self.args.inputs.resolve() / IMAGES[label]
            copy_image = self.out / (label + "-copy-view.dmg")
            self.run(["cp", "-c", image, copy_image])
            copy_mount = self.out / "mounts" / (label + "-copy")
            self.attach(copy_image, copy_mount, readonly=True, owners=False)
            missing = []
            copy_paths = set()
            def failed(error):
                unresolved.append({"path": str(error.filename), "error": str(error)})
            for directory, folders, files in os.walk(copy_mount, followlinks=False, onerror=failed):
                for path in [Path(directory)] + [Path(directory) / name for name in folders + files]:
                    relative = path.relative_to(copy_mount)
                    relative_name = "" if str(relative) == "." else str(relative)
                    destination = str(Path(PREFIX[label]) / relative) if PREFIX[label] else relative_name
                    try:
                        item = path.lstat()
                    except OSError as error:
                        failed(error)
                        continue
                    copy_paths.add(relative_name)
                    known = self.metadata.get(destination)
                    if known is None:
                        missing.append(relative_name)
                    elif known["kind"] != stat.S_IFMT(item.st_mode) or known["mode"] != stat.S_IMODE(item.st_mode):
                        raise ValueError("copy-view metadata differs from owners-on: " + relative_name)
                    if stat.S_ISREG(item.st_mode) and not os.access(path, os.R_OK):
                        if item.st_size == 0:
                            # A mode-000 empty sentinel has no bytes to read.
                            # Recreate it, then restore its genuine metadata.
                            self.empty_files[label].append(relative_name)
                        else:
                            unresolved.append({"path": str(path), "error": "nonempty content is unreadable even in the separate owners-off view"})
            queried = list(dict.fromkeys(blocked + missing))
            metadata = reader.read_metadata(image, queried)
            for relative, original in metadata.items():
                destination = str(Path(PREFIX[label]) / relative) if PREFIX[label] else relative
                known = self.metadata.get(destination)
                if known is not None:
                    if any(known[key] != original[key] for key in ("uid", "gid", "mode", "kind")):
                        raise ValueError("raw APFS metadata differs from owners-on: " + relative)
                else:
                    self.metadata[destination] = original
            for relative in copy_paths:
                destination = str(Path(PREFIX[label]) / relative) if PREFIX[label] else relative
                if destination not in self.metadata:
                    raise ValueError("copy view contains a path without genuine metadata: " + relative)
            self.manifest["copy_view_counts"][label] = {
                "unique_paths": len(copy_paths), "raw_metadata_added": sorted(set(missing)),
                "all_paths_have_genuine_metadata": True}
            self.manifest["protected_metadata"][label] = metadata
            sources[label] = copy_mount
        self.manifest["blocked"] = unresolved
        self.manifest["empty_sentinels_to_recreate"] = self.empty_files

    def mkdir(self, root, relative):
        current = root
        for part in Path(relative).parts:
            current /= part
            if not current.exists():
                current.mkdir()
                key = str(current.relative_to(root))
                self.metadata.setdefault(key, {"uid": 0, "gid": 0, "mode": 0o755, "kind": stat.S_IFDIR})

    def link_cryptexes(self, root):
        cache = "System/Library/Caches/com.apple.dyld"
        self.mkdir(root, cache)
        source_cache = root / PREFIX["systemos"] / cache
        if not source_cache.is_dir():
            raise ValueError("SystemOS cryptex has no shared-cache directory")
        linked = 0
        for source in source_cache.iterdir():
            if not source.is_file() or source.is_symlink():
                raise ValueError("unexpected non-file in shared-cache directory")
            target = root / cache / source.name
            if target.exists():
                if digest(source) != digest(target):
                    raise ValueError("conflicting shared-cache file: " + source.name)
                target.unlink()
            os.link(source, target)
            self.metadata[str(target.relative_to(root))] = dict(self.metadata[str(source.relative_to(root))])
            linked += 1
        for label in ("systemos", "appos"):
            prefix = PREFIX[label]
            for source_name, metadata in list(self.metadata.items()):
                if not source_name.startswith(prefix + "/") or metadata["kind"] == stat.S_IFDIR:
                    continue
                relative = source_name[len(prefix) + 1:]
                if relative.startswith(cache + "/"):
                    continue
                source, target = root / source_name, root / relative
                if target.exists() or target.is_symlink():
                    continue
                self.mkdir(root, str(Path(relative).parent))
                if source.is_symlink():
                    os.symlink(os.readlink(source), target)
                elif source.is_file():
                    os.link(source, target)
                else:
                    raise ValueError("unsupported cryptex file type: " + source_name)
                self.metadata[relative] = dict(metadata)
                linked += 1
        self.manifest["cryptex_links"] = linked

    def verify_critical(self, image, sources):
        check_root = self.out / "mounts/verify"
        attachment = self.attach(image, check_root, readonly=True)
        checks = []
        try:
            files = []
            for name in ("sbin/launchd", "usr/lib/dyld"):
                source = next((root / name for root in sources.values()
                               if (root / name).is_file() and not (root / name).is_symlink()), None)
                if source is None:
                    raise ValueError("critical source file is absent: " + name)
                files.append((name, source, None))
            cache = "System/Library/Caches/com.apple.dyld"
            runtime = sorted((sources["systemos"] / cache).glob("dyld_shared_cache_arm64*"))
            runtime = [path for path in runtime if not path.name.endswith(".symbols")]
            if not runtime:
                raise ValueError("SystemOS has no runtime arm64 shared cache")
            for source in runtime:
                files.append((cache + "/" + source.name, source,
                              PREFIX["systemos"] + "/" + cache + "/" + source.name))
            for name, source, cryptex_name in files:
                target = check_root / name
                if target.is_symlink() or not target.is_file() or source.is_symlink():
                    raise ValueError("critical content check requires actual regular files: " + name)
                if source.stat().st_size != target.stat().st_size:
                    raise ValueError("critical file size differs: " + name)
                source_stat, target_stat = source.stat(), target.stat()
                if ((source_stat.st_uid, source_stat.st_gid, stat.S_IMODE(source_stat.st_mode)) !=
                        (target_stat.st_uid, target_stat.st_gid, stat.S_IMODE(target_stat.st_mode))):
                    raise ValueError("critical native owner/mode differs: " + name)
                expected = digest(source)
                actual = digest(target)
                if actual != expected:
                    raise ValueError("decompressed critical file bytes differ: " + name)
                record = {"path": name, "bytes": target.stat().st_size, "sha256": actual,
                          "source": str(source), "matches_decompressed_source": True,
                          "uid": target_stat.st_uid, "gid": target_stat.st_gid,
                          "mode": stat.S_IMODE(target_stat.st_mode), "native_ownership_matches": True}
                if cryptex_name:
                    cryptex = check_root / cryptex_name
                    if cryptex.is_symlink() or target.stat().st_ino != cryptex.stat().st_ino:
                        raise ValueError("root shared-cache entry is not its cryptex hard link: " + name)
                    record["cryptex_cnid"] = cryptex.stat().st_ino
                    record["link_count"] = target.stat().st_nlink
                checks.append(record)
            self.manifest["critical_content_checks"] = checks
            atomic(self.out / "critical-content.json", checks)
            source, cache = check_root / checkpoint_userland.SOURCE, check_root / checkpoint_userland.CACHE
            item = cache.stat()
            if (cache.read_bytes() != source.read_bytes() or item.st_mtime_ns != source.stat().st_mtime_ns or
                    (item.st_uid, item.st_gid, stat.S_IMODE(item.st_mode)) != (501, 501, 0o644)):
                raise ValueError("native checkpoint cache content, timestamp or ownership differs")
            self.manifest["checkpoint_verify"] = {"content_matches": True, "mtime_ns": item.st_mtime_ns,
                                                   "uid": item.st_uid, "gid": item.st_gid, "mode": 0o644}
        finally:
            self.detach(attachment)

    def execute(self):
        try:
            self.out.mkdir(parents=True, exist_ok=False)
            (self.out / "INCOMPLETE").write_text("Base root image has not passed verification.\n")
            self.log = (self.out / "build.log").open("w")
            sources = {}
            for label, image_name in IMAGES.items():
                if self.args.reuse_mounts:
                    mount = self.args.reuse_mounts.resolve() / label
                    if not mount.is_mount():
                        raise ValueError("expected an existing read-only source mount: " + str(mount))
                    info = plistlib.loads(self.run(["diskutil", "info", "-plist", mount], capture=True))
                    if not info.get("GlobalPermissionsEnabled") or not info.get("ReadOnlyVolume", info.get("VolumeReadOnly", False)):
                        # Some macOS versions omit ReadOnlyVolume; statvfs is authoritative.
                        if not info.get("GlobalPermissionsEnabled") or not os.statvfs(mount).f_flag & os.ST_RDONLY:
                            raise ValueError("source must be read-only with ownership enabled: " + str(mount))
                    self.manifest["mounts"].append({"mount": str(mount), "external": True, "readonly": True})
                else:
                    mount = self.out / "mounts" / label
                    self.attach(self.args.inputs.resolve() / image_name, mount, readonly=True)
                sources[label] = mount
                count = self.scan(mount, PREFIX[label])
                self.manifest["sources"][label] = {"mount": str(mount), "entries": count}
            if self.manifest["blocked"]:
                self.resolve_protected(sources)
            atomic(self.out / "source-metadata.json", self.metadata)
            atomic(self.out / "blocked.json", self.manifest["blocked"])
            if self.manifest["blocked"]:
                raise ValueError("source metadata has inaccessible paths; see blocked.json; no files were silently skipped")
            image = self.out / "ios16-root.img"
            # Blank images are UDRW by default. Recent hdiutil rejects an
            # explicit -format unless -srcfolder/-srcdevice is also supplied.
            self.run(["hdiutil", "create", "-size", self.args.size, "-fs", "JHFSX",
                      "-layout", "NONE", "-volname", "iOSRoot", image])
            if not image.exists() and image.with_name(image.name + ".dmg").exists():
                image.with_name(image.name + ".dmg").replace(image)
            target = self.out / "mounts/root"
            attachment = self.attach(image, target, readonly=False)
            for label, source in sources.items():
                prefix = PREFIX[label]
                if prefix:
                    self.mkdir(target, prefix)
                destination = target / prefix
                excludes = []
                for name in self.empty_files[label]:
                    pattern = "/" + "".join("\\" + char if char in "\\?*[]" else char for char in name)
                    excludes += ["--exclude=" + pattern]
                self.run(["/usr/bin/rsync", "-aH", "--no-owner", "--no-group", "--no-perms",
                          "--chmod=Du+rwx,Fu+rw", *excludes, str(source) + "/", str(destination) + "/"])
                for name in self.empty_files[label]:
                    sentinel = destination / name
                    if sentinel.exists() or sentinel.is_symlink():
                        raise ValueError("empty sentinel unexpectedly exists before reconstruction: " + str(sentinel))
                    sentinel.touch(mode=0o600)
            self.link_cryptexes(target)
            tweak_spec = importlib.util.spec_from_file_location("redfin_root_tweaks", ROOT / "tools/sweet-root-tweaks.py")
            tweaks = importlib.util.module_from_spec(tweak_spec)
            tweak_spec.loader.exec_module(tweaks)
            tweaks.apply(target, metadata=self.metadata)
            self.manifest["wifi_userland"] = wifi_userland.prepare_root(target)
            self.manifest["checkpoint_userland"] = checkpoint_userland.prepare_root(target, self.metadata)
            if self.args.photos_init_bundle:
                self.manifest["photos_init"] = photos_userland.prepare_root(target, self.metadata, self.args.photos_init_bundle)
            if self.args.ui_bundle:
                self.manifest["native_cutout"] = ui_userland.prepare_root(target,self.metadata,self.args.ui_bundle)
            if self.args.gui_check_bundle:
                self.manifest["gui_check"] = gui_check_userland.prepare_root(target,self.metadata,self.args.gui_check_bundle)
            owners = []
            for relative, metadata in self.metadata.items():
                destination = target / relative
                item = destination.lstat()
                if stat.S_IFMT(item.st_mode) != metadata["kind"]:
                    raise ValueError("copied file type mismatch: " + relative)
                owners.append({"cnid": item.st_ino, "uid": metadata["uid"], "gid": metadata["gid"],
                               "mode": metadata["mode"], "path": relative})
            atomic(self.out / "destination-metadata.json", owners)
            self.run(["sync"])
            self.detach(attachment)
            self.run([sys.executable, ROOT / "ports/redfin/hfs-metadata-inplace.py", image,
                      self.out / "destination-metadata.json", "--apply"])
            metadata_report = json.loads(image.with_name(image.name + ".inplace-metadata.json").read_text())
            if (not metadata_report.get("success") or metadata_report.get("manifest_sha256") !=
                    digest(self.out / "destination-metadata.json")):
                raise ValueError("offline metadata update/mandatory fsck did not pass")
            self.manifest["metadata_update"] = metadata_report
            self.manifest["fsck"] = {"success": True, "performed_by": "hfs-metadata-inplace.py", "log": "build.log"}
            self.verify_critical(image, sources)
            self.manifest.update(stage="root-prepared", success=True,
                image={"path": str(image), "bytes": image.stat().st_size, "sha256": digest(image)},
                remaining="Validate XNU boot and review this artifact before considering any device installation")
            (self.out / "INCOMPLETE").unlink()
            return 0
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.manifest["error"] = str(error)
            print("build-root: " + str(error), file=sys.stderr)
            return 1
        finally:
            for attachment in list(reversed(self.attachments)):
                try:
                    self.detach(attachment)
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    self.manifest.setdefault("detach_errors", []).append(str(error))
                    self.manifest["success"] = False
            if self.out.is_dir() and self.log is not None:
                self.log.close()
                atomic(self.out / "build.json", self.manifest)
            print(self.manifest["stage"] + ": " + str(self.out))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=ROOT / "research/ipsw-redfin/extracted")
    parser.add_argument("--out", type=Path, default=ROOT / "research/ipsw-redfin/root-image")
    parser.add_argument("--size", default="16g")
    parser.add_argument("--photos-init-bundle", type=Path, help="verified native first-library bootstrap from photos_userland.py")
    parser.add_argument("--ui-bundle",type=Path,help="verified native full-panel/status-bar adapter from ui_userland.py")
    parser.add_argument("--gui-check-bundle",type=Path,help="verified native opt-in app checker from gui_check_userland.py")
    parser.add_argument("--reuse-mounts", type=Path, help="use existing read-only ownership-enabled os/systemos/appos mounts; leaves these external mounts attached")
    args = parser.parse_args(argv)
    if (ROOT / "research").resolve() not in args.out.resolve().parents:
        parser.error("--out must remain under ignored research")
    if args.out.exists():
        parser.error("--out already exists; choose a fresh directory")
    return Builder(args).execute()


if __name__ == "__main__":
    sys.exit(main())
