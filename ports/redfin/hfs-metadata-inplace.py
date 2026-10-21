#!/usr/bin/env python3
"""Restore HFS ownership by scanning catalog leaves twice, without rebuilding keys.

Uses the same CNID manifest as hfs-metadata.py. Requires its pinned library to
already be built; never rewrites that library, its build files or the old helper.
The first pass validates every node and resolves all CNIDs before image writes.
The second pass changes owner/group/mode bytes only, with readback per leaf.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("redfin_hfs_metadata_common", Path(__file__).with_name("hfs-metadata.py"))
COMMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMON)
HELPER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <hfs/hfsplus.h>
char endianness;
struct item { uint32_t cnid, uid, gid, mode, seen; };
static uint16_t b16(const unsigned char *p) { return (uint16_t)p[0] << 8 | p[1]; }
static uint32_t b32(const unsigned char *p) { return (uint32_t)b16(p) << 16 | b16(p + 2); }
static void w16(unsigned char *p, uint16_t v) { p[0] = v >> 8; p[1] = v; }
static void w32(unsigned char *p, uint32_t v) { w16(p, v >> 16); w16(p + 2, v); }
static int order(const void *a, const void *b) {
    uint32_t x = ((const struct item *)a)->cnid, y = ((const struct item *)b)->cnid;
    return (x > y) - (x < y);
}
static int scan(Volume *v, struct item *items, size_t count, FILE *original, int apply) {
    BTree *t = v->catalogTree;
    uint32_t size = t->headerRec->nodeSize, total = t->headerRec->totalNodes;
    uint32_t node = t->headerRec->firstLeafNode, previous = 0;
    if (size < 512 || size > 32768 || (size & (size - 1)) || !total || total > (1u << 24)) return 20;
    unsigned char *buffer = malloc(size), *verify = malloc(size), *seen = calloc((total + 7) / 8, 1);
    if (!buffer || !verify || !seen) return 21;
    uint64_t records = 0, leaves = 0, writes = 0;
    for (size_t i = 0; i < count; i++) items[i].seen = 0;
    while (node) {
        if (node >= total || (seen[node / 8] & (1u << (node & 7)))) return 22;
        seen[node / 8] |= 1u << (node & 7);
        off_t offset = (off_t)node * size;
        if (!READ(t->io, offset, size, buffer)) return 23;
        uint32_t next = b32(buffer), back = b32(buffer + 4);
        unsigned n = b16(buffer + 10);
        if (buffer[8] != 0xff || buffer[9] != 1 || back != previous ||
            n > (size - 14) / 2 || (next && next >= total)) return 24;
        unsigned limit = size - 2 * (n + 1), changed = 0;
        for (unsigned i = 0; i < n; i++) {
            unsigned begin = b16(buffer + size - 2 * (i + 1));
            unsigned end = b16(buffer + size - 2 * (i + 2));
            if (begin < 14 || end < begin || end > limit || end - begin < 10) return 25;
            unsigned key_size = b16(buffer + begin);
            if (key_size < 6 || key_size > 516 || (key_size & 1) || key_size + 2 > end - begin ||
                b16(buffer + begin + 6) > 255 || 6 + 2u * b16(buffer + begin + 6) != key_size) return 26;
            unsigned data = begin + 2 + key_size;
            if (end - data < 2) return 27;
            unsigned type = b16(buffer + data);
            records++;
            if (type != kHFSPlusFileRecord && type != kHFSPlusFolderRecord) continue;
            unsigned expected = type == kHFSPlusFileRecord ? sizeof(HFSPlusCatalogFile) : sizeof(HFSPlusCatalogFolder);
            if (end - data != expected) return 28;
            struct item key = { .cnid = b32(buffer + data + 8) };
            struct item *m = bsearch(&key, items, count, sizeof(*items), order);
            if (!m) continue;
            if (++m->seen != 1) return 29;
            unsigned char *p = buffer + data + 32;
            uint32_t uid = b32(p), gid = b32(p + 4);
            uint16_t mode = b16(p + 10), desired = (mode & (uint16_t)~07777) | m->mode;
            if (!apply) {
                if (fprintf(original, "%u %u %u %o\n", m->cnid, uid, gid, mode & 07777) < 0) return 30;
            } else if (uid != m->uid || gid != m->gid || mode != desired) {
                /* Only these ten bytes change: flags + special/linkCount stay intact. */
                w32(p, m->uid); w32(p + 4, m->gid); w16(p + 10, desired);
                changed = 1;
            }
        }
        if (changed) {
            if (!WRITE(t->io, offset, size, buffer) || !READ(t->io, offset, size, verify) || memcmp(buffer, verify, size)) return 31;
            writes++;
        }
        previous = node; node = next; leaves++;
    }
    if (previous != t->headerRec->lastLeafNode || records != t->headerRec->leafRecords) return 32;
    for (size_t i = 0; i < count; i++) if (items[i].seen != 1) {
        fprintf(stderr, "CNID %u missing or duplicated\n", items[i].cnid); return 33;
    }
    free(buffer); free(verify); free(seen);
    printf("%s: %zu CNIDs, %llu leaf records, %llu leaves, %llu leaf writes\n",
           apply ? "Updated/verified" : "Preflight", count,
           (unsigned long long)records, (unsigned long long)leaves, (unsigned long long)writes);
    fflush(stdout);
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    uint16_t one = 1;
    endianness = *(unsigned char *)&one ? IS_LITTLE_ENDIAN : IS_BIG_ENDIAN;
    FILE *input = fopen(argv[2], "r"), *original = fopen(argv[3], "wx");
    if (!input || !original) return 3;
    size_t count = 0, cap = 4096;
    struct item *items = malloc(cap * sizeof(*items));
    if (!items) return 4;
    unsigned cnid, uid, gid, mode;
    while (fscanf(input, "%u %u %u %o", &cnid, &uid, &gid, &mode) == 4) {
        if (cnid < 2 || mode > 07777 || count == 1000000) return 5;
        if (count == cap) { cap *= 2; void *p = realloc(items, cap * sizeof(*items)); if (!p) return 4; items = p; }
        items[count++] = (struct item){cnid, uid, gid, mode, 0};
    }
    if (!feof(input) || !count) return 5;
    fclose(input);
    qsort(items, count, sizeof(*items), order);
    for (size_t i = 1; i < count; i++) if (items[i].cnid == items[i-1].cnid) return 6;
    io_func *io = openFlatFile(argv[1]);
    if (!io) return 7;
    Volume *v = openVolume(io);
    if (!v) return 8;
    int result = scan(v, items, count, original, 0);
    if (fflush(original) || fsync(fileno(original))) return 9;
    if (result) return result; /* No image writes have happened before this point. */
    result = scan(v, items, count, original, 1);
    if (fflush((FILE *)io->data) || fsync(fileno((FILE *)io->data))) return 10;
    fclose(original); closeVolume(v); CLOSE(io); free(items);
    return result;
}
'''


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, **kwargs)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fsck_read_only(image):
    info = plistlib.loads(run(["hdiutil", "attach", "-nomount", "-readonly", "-plist", image], capture_output=True).stdout)
    devices = [x["dev-entry"] for x in info.get("system-entities", []) if x.get("dev-entry", "").startswith("/dev/disk")]
    if not devices:
        raise ValueError("hdiutil returned no image device")
    try:
        run(["/sbin/fsck_hfs", "-fn", devices[-1].replace("/dev/disk", "/dev/rdisk", 1)])
    finally:
        run(["hdiutil", "detach", devices[0]])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--library", type=Path, default=ROOT / "research/hfsplus")
    args = parser.parse_args(argv)
    image, library = args.image.resolve(), args.library.resolve()
    report = {"success": False, "algorithm": "two-pass catalog leaf metadata update", "library_commit": COMMON.COMMIT,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    started = time.monotonic()
    try:
        research = (ROOT / "research").resolve()
        if research not in image.parents or research not in library.parents:
            raise ValueError("image and library must remain under ignored research")
        records = COMMON.entries(args.manifest)
        with image.open("rb") as stream:
            stream.seek(1024)
            header = stream.read(512)
        if len(header) != 512 or header[:2] not in (b"H+", b"HX") or not struct.unpack_from(">I", header, 4)[0] & (1 << 8):
            raise ValueError("expected a cleanly unmounted raw HFS+/HFSX image")
        info = plistlib.loads(run(["hdiutil", "info", "-plist"], capture_output=True).stdout)
        if any(Path(x.get("image-path", "")).resolve() == image for x in info.get("images", [])):
            raise ValueError("detach this image before metadata editing")
        report.update(records=len(records), manifest_sha256=sha256(args.manifest))
        if not args.apply:
            print(f"Validated {len(records)} CNIDs; --apply is required to write")
            return 0
        backup = image.with_name(image.name + ".before-inplace-metadata")
        original = image.with_name(image.name + ".inplace-original-metadata.tsv")
        if backup.exists() or original.exists():
            raise ValueError("in-place backup already exists; use a fresh image")
        commit = run(["git", "rev-parse", "HEAD"], cwd=library, capture_output=True, text=True).stdout.strip()
        if commit != COMMON.COMMIT:
            raise ValueError("unexpected libdmg-hfsplus commit")
        run(["git", "diff", "--quiet", "HEAD"], cwd=library)
        archives = [library / "build/hfs/libhfs.a", library / "build/common/libcommon.a"]
        if not all(x.is_file() for x in archives):
            raise ValueError("build the pinned HFS libraries first; this helper never changes their build directory")
        with tempfile.TemporaryDirectory(prefix="hfs-leaf-", dir=image.parent) as temp:
            temp = Path(temp)
            source, executable, manifest = temp / "metadata.c", temp / "metadata", temp / "input.tsv"
            source.write_text(HELPER)
            run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-I", library / "includes", source, *archives, "-lz", "-o", executable])
            manifest.write_text("".join("%u %u %u %o\n" % values for values in records))
            run(["cp", "-c", image, backup])
            run([executable, image, manifest, original])
        fsck_read_only(image)
        report["success"] = True
        print(f"Updated and verified {len(records)} CNIDs without catalog restructuring")
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        print("hfs-metadata-inplace: " + str(error), file=sys.stderr)
        return 1
    finally:
        if args.apply and image.parent.is_dir() and (ROOT / "research").resolve() in image.parents:
            report.update(seconds=time.monotonic() - started, finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            output = image.with_name(image.name + ".inplace-metadata.json")
            temporary = output.with_name(output.name + ".tmp")
            temporary.write_text(json.dumps(report, indent=2) + "\n")
            temporary.replace(output)


if __name__ == "__main__":
    raise SystemExit(main())
