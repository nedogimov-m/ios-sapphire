# SPDX-License-Identifier: MIT
"""Bounded read-only FAT16/32 access to captured modem firmware images."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import struct

MAX_IMAGE = 512 * 1024 * 1024
MAX_FAT = 16 * 1024 * 1024
MAX_DIRECTORY = 8 * 1024 * 1024
MAX_ENTRIES = 65536
MAX_MDT = 4 * 1024 * 1024
MAX_PHDR = 4096


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


@dataclass(frozen=True)
class Entry:
    name: str
    attributes: int
    cluster: int
    size: int

    @property
    def directory(self):
        return bool(self.attributes & 0x10)


class FAT:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            self.original = os.fstat(self.fd)
            require(stat.S_ISREG(self.original.st_mode), 'input must be a regular image file')
            require(512 <= self.original.st_size <= MAX_IMAGE, 'image size outside 512 B..512 MiB')
            self.limit = self.original.st_size
            boot = self.read(0, 512)
            require(boot[510:512] == b'\x55\xaa', 'missing FAT boot signature')
            self.bps = struct.unpack_from('<H', boot, 11)[0]
            self.spc, reserved, fats = boot[13], struct.unpack_from('<H', boot, 14)[0], boot[16]
            root_entries, total16, fat16 = (struct.unpack_from('<H', boot, off)[0] for off in (17, 19, 22))
            total32 = struct.unpack_from('<I', boot, 32)[0]
            require(self.bps in (512, 1024, 2048, 4096), 'unsupported sector size')
            require(self.spc and self.spc <= 128 and not self.spc & (self.spc-1), 'invalid cluster size')
            require(reserved and fats in (1, 2), 'invalid reserved-sector/FAT count')
            require(not (total16 and total32), 'ambiguous total-sector fields')
            total = total16 or total32
            require(total and total*self.bps <= self.limit, 'volume extends beyond image')
            self.volume_bytes = total*self.bps
            self.cluster_bytes = self.spc*self.bps
            self.root_bytes = root_entries*32
            root_sectors = (self.root_bytes+self.bps-1)//self.bps
            self.fat_sectors = fat16 or struct.unpack_from('<I', boot, 36)[0]
            require(self.fat_sectors, 'empty FAT')
            first_data = reserved+fats*self.fat_sectors+root_sectors
            require(first_data < total, 'no data region')
            self.clusters = (total-first_data)//self.spc
            require(4085 <= self.clusters < 0x0ffffff5, 'FAT12 or oversized cluster geometry')
            self.bits = 16 if self.clusters < 65525 else 32
            require((self.bits == 16 and fat16 and root_entries) or
                    (self.bits == 32 and not fat16 and not root_entries), 'FAT type/geometry mismatch')
            fat_bytes = self.fat_sectors*self.bps
            require(fat_bytes <= MAX_FAT and fat_bytes//(self.bits//8) >= self.clusters+2,
                    'FAT capacity invalid')
            self.data_offset = first_data*self.bps
            self.root_offset = (reserved+fats*self.fat_sectors)*self.bps
            self.root_cluster = 0 if self.bits == 16 else struct.unpack_from('<I', boot, 44)[0]
            flags = 0 if self.bits == 16 else struct.unpack_from('<H', boot, 40)[0]
            active = flags & 15 if flags & 0x80 else 0
            require(active < fats, 'active FAT index invalid')
            copies = [self.read((reserved+i*self.fat_sectors)*self.bps, fat_bytes) for i in range(fats)]
            if not flags & 0x80:
                require(all(copy == copies[0] for copy in copies), 'mirrored FAT copies disagree')
            self.table = copies[active]
            self.directory_clusters = set()
            self.file_clusters = set()
        except Exception:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def unchanged(self):
        now = os.fstat(self.fd)
        return all(getattr(now, key) == getattr(self.original, key)
                   for key in ('st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_ino', 'st_dev'))

    def read(self, offset, size):
        require(0 <= offset <= self.limit and 0 <= size <= min(MAX_FAT, self.limit-offset),
                'read outside image or bounded read size')
        data = os.pread(self.fd, size, offset)
        require(len(data) == size, 'short image read')
        return data

    def chain(self, first, maximum):
        require(0 < maximum <= self.clusters, 'invalid chain bound')
        seen, result = set(), []
        current = first
        eoc, reserved = (0xfff8, 0xfff0) if self.bits == 16 else (0x0ffffff8, 0x0ffffff0)
        while True:
            require(2 <= current < min(self.clusters+2, reserved), 'cluster outside data region or reserved')
            require(current not in seen, 'cluster-chain cycle')
            require(len(result) < maximum, 'cluster chain exceeds object limit')
            seen.add(current)
            result.append(current)
            width = self.bits//8
            value = int.from_bytes(self.table[current*width:(current+1)*width], 'little')
            value &= 0xffff if self.bits == 16 else 0x0fffffff
            if value >= eoc:
                return result
            require(2 <= value < reserved, 'free, bad, or reserved cluster in chain')
            current = value

    @staticmethod
    def lfn_checksum(short):
        checksum = 0
        for value in short:
            checksum = (((checksum & 1) << 7)+(checksum >> 1)+value) & 255
        return checksum

    def directory(self, first=None):
        if first is None and self.bits == 16:
            raw = self.read(self.root_offset, self.root_bytes)
        else:
            first = self.root_cluster if first is None else first
            chain = self.chain(first, min(self.clusters, MAX_DIRECTORY//self.cluster_bytes))
            require(not self.directory_clusters.intersection(chain), 'directory cluster alias')
            self.directory_clusters.update(chain)
            require(len(self.directory_clusters)*self.cluster_bytes+self.root_bytes <= MAX_DIRECTORY,
                    'total directory allocation exceeds bound')
            raw = b''.join(self.read(self.data_offset+(c-2)*self.cluster_bytes, self.cluster_bytes) for c in chain)
        require(len(raw) <= MAX_DIRECTORY, 'oversized directory')
        records, names, lfn = [], set(), []
        remaining = checksum = 0
        for offset in range(0, len(raw), 32):
            entry = raw[offset:offset+32]
            if entry[0] == 0:
                require(not lfn, 'unterminated long filename')
                break
            if entry[0] == 0xe5:
                lfn, remaining = [], 0
                continue
            attr = entry[11]
            if attr == 15:
                sequence = entry[0]
                index = sequence & 31
                require(not sequence & 0xa0 and 1 <= index <= 20 and not entry[12] and entry[26:28] == b'\0\0',
                        'invalid long filename entry')
                if sequence & 0x40:
                    require(not lfn, 'overlapping long filenames')
                    lfn, remaining, checksum = [], index, entry[13]
                require(index == remaining and entry[13] == checksum, 'long filename sequence/checksum mismatch')
                lfn.append(entry[1:11]+entry[14:26]+entry[28:32])
                remaining -= 1
                continue
            short = entry[:11]
            if attr & 8:
                require(not lfn, 'long filename before volume label')
                continue
            require(not attr & 0xc0, 'reserved file attribute')
            require(all(32 <= value < 127 for value in short), 'non-ASCII short filename')
            name = short[:8].decode().rstrip() + ('.'+short[8:].decode().rstrip() if short[8:].strip() else '')
            if lfn:
                require(remaining == 0 and self.lfn_checksum(short) == checksum, 'long filename checksum mismatch')
                units = struct.unpack('<'+'H'*(len(lfn)*13), b''.join(reversed(lfn)))
                end = units.index(0) if 0 in units else len(units)
                require(all(unit == 0xffff for unit in units[end+1:]), 'invalid long filename padding')
                require(0 < end <= 255 and 0xffff not in units[:end], 'invalid long filename length')
                try:
                    name = struct.pack('<'+'H'*end, *units[:end]).decode('utf-16le', errors='strict')
                except UnicodeError as error:
                    raise Invalid('invalid UTF-16 filename') from error
                lfn = []
            require(name and not any(c in name for c in '/\\\0') and not any(ord(c) < 32 for c in name),
                    'unsafe directory name')
            if name in ('.', '..'):
                continue
            require(name.casefold() not in names, 'ambiguous duplicate filename')
            names.add(name.casefold())
            high, low = struct.unpack_from('<H', entry, 20)[0], struct.unpack_from('<H', entry, 26)[0]
            require(self.bits == 32 or not high, 'FAT16 high cluster word is nonzero')
            cluster = (high << 16 | low) & 0x0fffffff
            size = struct.unpack_from('<I', entry, 28)[0]
            require(size <= self.volume_bytes, 'file size exceeds volume')
            records.append(Entry(name, attr, cluster, size))
            require(len(records) <= MAX_ENTRIES, 'too many directory entries')
        require(not lfn, 'unattached long filename')
        return records

    def chunks(self, entry, claim=True):
        require(not entry.directory, 'cannot read directory as file')
        count = (entry.size+self.cluster_bytes-1)//self.cluster_bytes
        if not count:
            require(not entry.cluster, 'empty file has allocated cluster')
            return
        chain = self.chain(entry.cluster, count)
        require(len(chain) == count, 'file chain shorter than declared length')
        if claim:
            require(not self.file_clusters.intersection(chain), 'selected firmware files share clusters')
            require(not self.directory_clusters.intersection(chain), 'file aliases a directory')
            self.file_clusters.update(chain)
        left = entry.size
        for cluster in chain:
            take = min(left, self.cluster_bytes)
            yield self.read(self.data_offset+(cluster-2)*self.cluster_bytes, take)
            left -= take

    def image_hash(self):
        digest = hashlib.sha256()
        for offset in range(0, self.limit, 1024*1024):
            digest.update(self.read(offset, min(1024*1024, self.limit-offset)))
        return digest.hexdigest()

    def extents(self, entry):
        count = (entry.size+self.cluster_bytes-1)//self.cluster_bytes
        if not count:
            require(not entry.cluster, 'empty file has allocated cluster')
            return []
        chain = self.chain(entry.cluster, count)
        require(len(chain) == count, 'file chain shorter than declared length')
        result, left = [], entry.size
        for cluster in chain:
            offset, size = self.data_offset+(cluster-2)*self.cluster_bytes, min(left, self.cluster_bytes)
            if result and result[-1]['image_offset']+result[-1]['bytes'] == offset:
                result[-1]['bytes'] += size
            else:
                result.append({'image_offset': offset, 'bytes': size})
            left -= size
        return result


