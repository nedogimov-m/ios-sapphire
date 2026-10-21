#!/usr/bin/env python3
"""Set HFS+ owner/mode metadata offline by CNID, without administrator access.

Manifest: [{"cnid": 123, "uid": 0, "gid": 0, "mode": 493}, ...].
Collect CNIDs with lstat on the mounted destination before detaching it. Hard
links share a CNID and must have identical permissions. File data, names, link
targets and inode flags are left to macOS's native filesystem implementation.
"""
import argparse
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "7ac55ec64c96f7800d9818ce64c79670e7f02b67"
HELPER = r'''#include <stdio.h>
#include <stdlib.h>
#include <hfs/hfsplus.h>
char endianness;
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    uint16_t one = 1;
    endianness = *(unsigned char *)&one ? IS_LITTLE_ENDIAN : IS_BIG_ENDIAN;
    io_func *io = openFlatFile(argv[1]);
    if (!io) return 3;
    Volume *v = openVolume(io);
    if (!v) { CLOSE(io); return 4; }
    FILE *input = fopen(argv[2], "r"), *original = fopen(argv[3], "w");
    if (!input || !original) return 5;
    unsigned cnid, uid, gid, mode, count = 0;
    while (fscanf(input, "%u %u %u %o", &cnid, &uid, &gid, &mode) == 4) {
        HFSPlusCatalogRecord *record = getRecordByCNID(cnid, v);
        if (!record) { fprintf(stderr, "missing CNID %u\n", cnid); return 6; }
        HFSPlusBSDInfo *permissions = NULL;
        if (record->recordType == kHFSPlusFolderRecord)
            permissions = &((HFSPlusCatalogFolder *)record)->permissions;
        if (record->recordType == kHFSPlusFileRecord)
            permissions = &((HFSPlusCatalogFile *)record)->permissions;
        if (!permissions) return 7;
        fprintf(original, "%u %u %u %o\n", cnid, permissions->ownerID,
                permissions->groupID, permissions->fileMode & 07777);
        fflush(original);
        permissions->ownerID = uid;
        permissions->groupID = gid;
        permissions->fileMode = (permissions->fileMode & ~07777) | mode;
        if (!updateCatalog(v, record)) return 8;
        free(record);
        record = getRecordByCNID(cnid, v);
        if (!record) return 9;
        permissions = record->recordType == kHFSPlusFolderRecord ?
            &((HFSPlusCatalogFolder *)record)->permissions :
            &((HFSPlusCatalogFile *)record)->permissions;
        if (permissions->ownerID != uid || permissions->groupID != gid ||
            (permissions->fileMode & 07777) != mode) return 10;
        free(record);
        count++;
    }
    if (!feof(input)) return 11;
    fclose(input); fclose(original); closeVolume(v); CLOSE(io);
    printf("Updated and verified %u HFS catalog records\n", count);
    return 0;
}
'''


def run(command, **kwargs):
    return subprocess.run([str(item) for item in command], check=True, **kwargs)


def entries(path):
    records = json.loads(path.read_text())
    if not isinstance(records, list) or not 1 <= len(records) <= 1000000:
        raise ValueError("manifest must contain 1..1000000 metadata entries")
    unique = {}
    for record in records:
        values = tuple(record[name] for name in ("cnid", "uid", "gid", "mode"))
        if (any(type(value) is not int for value in values) or not 2 <= values[0] <= 0xFFFFFFFF
                or not all(0 <= value <= 0xFFFFFFFF for value in values[1:3])
                or not 0 <= values[3] <= 0o7777):
            raise ValueError("invalid CNID/uid/gid/mode in metadata manifest")
        if values[0] in unique and unique[values[0]] != values:
            raise ValueError("conflicting metadata for hard-linked CNID %d" % values[0])
        unique[values[0]] = values
    return list(unique.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="write metadata; default validates inputs only")
    parser.add_argument("--library", type=Path, default=ROOT / "research/hfsplus")
    args = parser.parse_args(argv)
    try:
        image, library = args.image.resolve(), args.library.resolve()
        if (ROOT / "research").resolve() not in image.parents:
            raise ValueError("image must be under this repository's ignored research directory")
        records = entries(args.manifest)
        with image.open("rb") as stream:
            stream.seek(1024)
            header = stream.read(512)
        if len(header) != 512 or header[:2] not in (b"H+", b"HX"):
            raise ValueError("expected a raw, partitionless HFS+/HFSX image")
        if not struct.unpack_from(">I", header, 4)[0] & (1 << 8):
            raise ValueError("HFS volume was not cleanly unmounted")
        devices = plistlib.loads(run(["hdiutil", "info", "-plist"], capture_output=True).stdout)
        if any(Path(info.get("image-path", "")).resolve() == image for info in devices.get("images", [])):
            raise ValueError("detach the image before editing filesystem metadata")
        if not args.apply:
            print("Validated %d distinct CNIDs; --apply is required to write" % len(records))
            return 0
        backup = image.with_name(image.name + ".before-metadata")
        original = image.with_name(image.name + ".original-metadata.tsv")
        if backup.exists() or original.exists():
            raise ValueError("metadata backup already exists; use a fresh image")
        if (ROOT / "research").resolve() not in library.parents:
            raise ValueError("--library must remain under ignored research")
        if not library.exists():
            run(["git", "clone", "https://github.com/planetbeing/libdmg-hfsplus", library])
            run(["git", "checkout", "--detach", COMMIT], cwd=library)
        if run(["git", "rev-parse", "HEAD"], cwd=library, capture_output=True, text=True).stdout.strip() != COMMIT:
            raise ValueError("unexpected libdmg-hfsplus commit")
        run(["git", "diff", "--quiet", "HEAD"], cwd=library)
        build = library / "build"
        run(["cmake", "-S", library, "-B", build, "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"])
        run(["cmake", "--build", build, "--target", "hfs", "-j8"])
        source, executable = build / "redfin-metadata.c", build / "redfin-metadata"
        source.write_text(HELPER)
        run(["cc", "-Wall", "-Wextra", "-Werror", "-I", library / "includes", source,
             build / "hfs/libhfs.a", build / "common/libcommon.a", "-lz", "-o", executable])
        # APFS clone keeps the complete original image recoverable without a
        # second physical 16 GiB allocation. Failure aborts before any edit.
        run(["cp", "-c", image, backup])
        with tempfile.NamedTemporaryFile(mode="w", dir=image.parent) as manifest:
            for cnid, uid, gid, mode in records:
                manifest.write("%d %d %d %o\n" % (cnid, uid, gid, mode))
            manifest.flush()
            run([executable, image, manifest.name, original])
        print("Updated metadata; retained clone backup: " + str(backup))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("hfs-metadata: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
