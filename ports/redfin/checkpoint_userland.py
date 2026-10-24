"""Seed MobileCheckpoint's native dictionary cache from the installed XML.

20H392 libMobileCheckpoint accepts this cache only when both mtime seconds
and nanoseconds match Checkpoint.xml. Use the destination filesystem's XML
timestamp, never the host extraction's timestamp. No Apple binary is patched.
"""
import hashlib
import os
from pathlib import Path
import plistlib
import stat

SOURCE = Path("System/Library/CoreServices/Checkpoint.xml")
CACHE = Path("private/var/mobile/Library/Caches/Checkpoint.plist")
MAX_BYTES = 1024 * 1024


def cache_payload(source):
    """Preserve the stock dictionary verbatim, including its image formats."""
    if not 0 < len(source) <= MAX_BYTES:
        raise ValueError("expected a bounded Checkpoint.xml")
    try:
        value = plistlib.loads(source)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("invalid Checkpoint.xml") from error
    formats = value.get("ImageSpecifications") if isinstance(value, dict) else None
    if (not isinstance(formats, list) or not formats or len(formats) % 2 or
            any(not isinstance(formats[i], str) or not isinstance(formats[i + 1], dict)
                for i in range(0, len(formats), 2))):
        raise ValueError("expected the native image-format dictionary")
    return source, {"source": "/" + str(SOURCE), "cache": "/" + str(CACHE),
                    "bytes": len(source), "sha256": hashlib.sha256(source).hexdigest(),
                    "image_formats": len(formats) // 2, "stock_dictionary_preserved": True}


def prepare_root(root, metadata):
    """Prepare a mounted fresh root; defer mobile ownership to its CNID pass."""
    root = Path(root).resolve()
    source, cache = root / SOURCE, root / CACHE
    for path in (source, cache):
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("checkpoint path must stay inside the staging root")
    if not source.is_file() or (cache.exists() and not cache.is_file()):
        raise ValueError("checkpoint paths must be regular files")
    payload, report = cache_payload(source.read_bytes())
    original = source.stat()
    missing = []
    parent = cache.parent
    while not parent.exists():
        if parent == root:
            raise ValueError("checkpoint cache parent is absent")
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir()
        relative = str(parent.relative_to(root))
        uid = 501 if relative == "private/var/mobile" or relative.startswith("private/var/mobile/") else 0
        metadata[relative] = {"uid": uid, "gid": uid, "mode": 0o755, "kind": stat.S_IFDIR}
    changed = not cache.exists() or cache.read_bytes() != payload
    if changed:
        with cache.open("wb") as stream:
            if stream.write(payload) != len(payload):
                raise OSError("short checkpoint cache write")
            stream.flush()
            os.fsync(stream.fileno())
    os.utime(cache, ns=(original.st_atime_ns, original.st_mtime_ns))
    metadata[str(CACHE)] = {"uid": 501, "gid": 501, "mode": 0o644, "kind": stat.S_IFREG}
    if cache.read_bytes() != payload or cache.stat().st_mtime_ns != source.stat().st_mtime_ns:
        raise OSError("checkpoint cache content or native timestamp differs")
    report.update(changed=changed, mtime_ns=cache.stat().st_mtime_ns, uid=501, gid=501, mode=0o644)
    return report
