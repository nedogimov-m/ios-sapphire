#!/usr/bin/env python3
"""Read APFS inode ownership directly from a local image, without mounting it.

The pinned apfs-fuse library opens image data read-only and supports Apple's
compressed UDIF images. No FUSE installation, administrator access or writes
to the input image are needed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "66b86bd525e8cb90f9012543be89b1f092b75cf3"
LZFSE_COMMIT = "e634ca58b4821d9f3d560cdc6df5dec02ffc93fd"
HELPER = r'''#include <ApfsLib/ApfsContainer.h>
#include <ApfsLib/ApfsVolume.h>
#include <ApfsLib/ApfsDir.h>
#include <ApfsLib/Device.h>
#include <ApfsLib/GptPartitionMap.h>
#include <cstdio>
#include <memory>
#include <sstream>
#include <string>
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    std::unique_ptr<Device> device(Device::OpenDevice(argv[1]));
    if (!device) return 3;
    uint64_t offset = 0, size = device->GetSize();
    GptPartitionMap gpt;
    if (gpt.LoadAndVerify(*device)) {
        int partition = gpt.FindFirstAPFSPartition();
        if (partition < 0) return 4;
        gpt.GetPartitionOffsetAndSize(partition, offset, size);
    }
    ApfsContainer container(device.get(), offset, size);
    if (!container.Init()) return 5;
    std::unique_ptr<ApfsVolume> volume(container.GetVolume(0));
    if (!volume) return 6;
    ApfsDir directory(*volume);
    for (int arg = 2; arg < argc; arg++) {
        uint64_t id = 2;
        std::stringstream stream(argv[arg]);
        std::string component;
        while (std::getline(stream, component, '/')) {
            if (component.empty() || component == ".") continue;
            if (component == "..") return 7;
            ApfsDir::DirRec entry;
            if (!directory.LookupName(entry, id, component.c_str())) {
                fprintf(stderr, "APFS lookup failed: %s\n", argv[arg]); return 8;
            }
            id = entry.file_id;
        }
        ApfsDir::Inode inode;
        if (!directory.GetInode(inode, id)) return 9;
        printf("REDFIN_META\t%s\t%llu\t%u\t%u\t%u\t%u\t%u\n", argv[arg],
               (unsigned long long)id, inode.owner, inode.group,
               inode.mode & 07777, inode.mode & 0170000, inode.bsd_flags);
    }
    return 0;
}
'''


def run(command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, timeout=600, **kwargs)


def read_metadata(image, paths, library=ROOT / "research/apfs-reader"):
    image, library = Path(image).resolve(), Path(library).resolve()
    research = (ROOT / "research").resolve()
    if research not in image.parents or not image.is_file():
        raise ValueError("APFS image must be a regular file under ignored research")
    if research not in library.parents:
        raise ValueError("APFS helper library must remain under ignored research")
    paths = list(dict.fromkeys(str(path) for path in paths))
    if not paths or len(paths) > 4096:
        raise ValueError("query must contain 1..4096 paths")
    for path in paths:
        if Path(path).is_absolute() or ".." in Path(path).parts or any(c in path for c in "\t\n\r\0"):
            raise ValueError("APFS paths must be safe relative names")
    if not library.exists():
        run(["git", "clone", "https://github.com/sgan81/apfs-fuse", library])
        run(["git", "checkout", "--detach", COMMIT], cwd=library)
        run(["git", "submodule", "update", "--init", "--recursive"], cwd=library)
    if run(["git", "rev-parse", "HEAD"], cwd=library, capture_output=True, text=True).stdout.strip() != COMMIT:
        raise ValueError("unexpected APFS library revision")
    if run(["git", "rev-parse", "HEAD"], cwd=library / "3rdparty/lzfse", capture_output=True, text=True).stdout.strip() != LZFSE_COMMIT:
        raise ValueError("unexpected APFS LZFSE dependency revision")
    run(["git", "diff", "--quiet", "HEAD"], cwd=library)
    build = library / "build"
    run(["cmake", "-S", library, "-B", build, "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"], stdout=sys.stderr)
    run(["cmake", "--build", build, "--target", "apfs", "-j8"], stdout=sys.stderr)
    source, executable = build / "redfin-apfs-metadata.cpp", build / "redfin-apfs-metadata"
    source.write_text(HELPER)
    run(["c++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", library,
         "-I", library / "3rdparty/lzfse/src", source, build / "libapfs.a",
         build / "liblzfse.a", build / "libcrypto.a", "-lz", "-lbz2", "-o", executable])
    output = run([executable, image, *paths], capture_output=True, text=True).stdout
    metadata = {}
    for line in output.splitlines():
        if not line.startswith("REDFIN_META\t"):
            continue
        _, path, inode, uid, gid, mode, kind, flags = line.split("\t")
        metadata[path] = dict(zip(("source_cnid", "uid", "gid", "mode", "kind", "flags"),
                                 map(int, (inode, uid, gid, mode, kind, flags))))
    if set(metadata) != set(paths):
        raise ValueError("APFS reader did not return every requested inode")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        metadata = read_metadata(args.image, args.paths)
        data = json.dumps({"library_commit": COMMIT, "image": str(args.image.resolve()), "metadata": metadata}, indent=2) + "\n"
        if args.out:
            if (ROOT / "research").resolve() not in args.out.resolve().parents:
                raise ValueError("--out must remain under ignored research")
            args.out.write_text(data)
        else:
            print(data, end="")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("apfs-metadata: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
