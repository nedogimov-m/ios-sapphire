"""Provision verified native files into a fresh host staging root only."""
import hashlib
from pathlib import Path
import shutil
import stat


def prepare(root,metadata,items):
    root=Path(root).resolve()
    for source,target,uid,mode,digest,preserve in items:
        source=Path(source);data=source.read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError('native bundle file changed: '+source.name)
        destination=root/target.lstrip('/')
        if destination.is_symlink() or root not in destination.resolve().parents:
            raise ValueError('native staging path escapes root')
        if destination.exists() and not destination.is_file():
            raise ValueError('native destination must be a regular file')
        missing=[];parent=destination.parent
        while not parent.exists():missing.append(parent);parent=parent.parent
        for parent in reversed(missing):
            parent.mkdir();relative=str(parent.relative_to(root))
            owner=501 if relative=='private/var/mobile' or relative.startswith('private/var/mobile/') else 0
            metadata[relative]=dict(uid=owner,gid=owner,mode=0o755,kind=stat.S_IFDIR)
        if destination.exists() and not preserve and destination.read_bytes()!=data:
            raise ValueError('conflicting native bundle file')
        if not destination.exists():shutil.copyfile(source,destination)
        metadata[str(destination.relative_to(root))]=dict(uid=uid,gid=uid,mode=mode,kind=stat.S_IFREG)
