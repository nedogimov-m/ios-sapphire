"""Compile the actual patch's pure C validators; no kernel tree or device."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib


class GPT(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("blocks", "alternate", "first", "last", "entries")] + [
        (n, ctypes.c_uint32) for n in ("count", "entry_size", "array_bytes", "header_crc", "entries_crc")]


def fixture(count=19, entry_size=128):
    entries = bytearray(count * entry_size)
    entries[0] = 1
    struct.pack_into("<QQ", entries, 32, 16, 100)
    entries[56:56 + 16] = "ios-test".encode("utf-16-le")
    header = bytearray(4096)
    header[:8] = b"EFI PART"
    struct.pack_into("<4I", header, 8, 0x10000, 92, 0, 0)
    struct.pack_into("<4Q", header, 24, 1, 1023, 16, 1022)
    struct.pack_into("<Q3I", header, 72, 2, count, entry_size, zlib.crc32(entries))
    repair_header(header)
    return header, entries


def repair_header(header):
    struct.pack_into("<I", header, 16, 0)
    size = struct.unpack_from("<I", header, 12)[0]
    struct.pack_into("<I", header, 16, zlib.crc32(header[:size]))


class UFSPartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host cc unavailable")
        patch = Path(__file__).with_name("ufs-root.patch").read_text()
        added = "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
        pure = added.split("/* REDFIN_GPT_TEST_BEGIN", 1)[1].split("/* REDFIN_GPT_TEST_END */", 1)[0]
        pure = "/* REDFIN_GPT_TEST_BEGIN" + pure
        guard = added.split("/* REDFIN_ROOT_GUARD_TEST_BEGIN", 1)[1].split("/* REDFIN_ROOT_GUARD_TEST_END */", 1)[0]
        pure += "/* REDFIN_ROOT_GUARD_TEST_BEGIN" + guard
        prefix = "#include <stdint.h>\n#include <stdbool.h>\n#include <errno.h>\n#define UFS_BLOCK 4096u\n#define BOUNCE_SIZE (1u << 20)\n"
        wrappers = """
int cap(uint32_t a,uint32_t b,uint64_t *o){return redfin_gpt_capacity(a,b,o);}
int hdr(const uint8_t *b,unsigned n,uint64_t cap,struct redfin_gpt *o){return redfin_gpt_header(b,n,cap,o);}
int part(const uint8_t *b,unsigned n,const struct redfin_gpt *g,const char *w,uint64_t *f,uint64_t *c){return redfin_gpt_partition(b,n,g,w,f,c);}
int allow(const uint8_t *c,unsigned n,uint32_t size,int write,uint8_t lun,uint64_t blocks){return redfin_root_read_allowed(c,n,size,write,lun,blocks);}
"""
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source, lib = Path(cls.tmp.name) / "gpt.c", Path(cls.tmp.name) / "gpt.so"
        source.write_text(prefix + pure + wrappers)
        subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.cap.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64)]
        cls.lib.hdr.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint64, ctypes.POINTER(GPT)]
        cls.lib.part.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(GPT), ctypes.c_char_p,
                                 ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
        cls.lib.allow.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint32,
                                 ctypes.c_int, ctypes.c_uint8, ctypes.c_uint64]

    def header(self, data, blocks=1024):
        g = GPT()
        status = self.lib.hdr(bytes(data), len(data), blocks, ctypes.byref(g))
        return status, g

    def partition(self, entries, g, name=b"ios-test"):
        first, count = ctypes.c_uint64(777), ctypes.c_uint64(888)
        result = self.lib.part(bytes(entries), len(entries), ctypes.byref(g), name,
                               ctypes.byref(first), ctypes.byref(count))
        return result, first.value, count.value

    def test_valid_header_entry_and_padding_exclusion(self):
        header, entries = fixture()
        status, g = self.header(header)
        self.assertEqual(status, 0)
        self.assertEqual(self.partition(entries + bytes(1024), g), (0, 16, 85))
        self.assertEqual(g.array_bytes, 19 * 128)

    def test_capacity_is_4096_only_and_rejects_saturation(self):
        out = ctypes.c_uint64()
        self.assertEqual(self.lib.cap(1023, 4096, ctypes.byref(out)), 0)
        self.assertEqual(out.value, 1024)
        for last, block in ((0xffffffff, 4096), (1, 4096), (1023, 512)):
            self.assertNotEqual(self.lib.cap(last, block, ctypes.byref(out)), 0)
            self.assertEqual(out.value, 0)

    def test_corrupt_header_and_array_crc(self):
        header, entries = fixture()
        header[24] ^= 1
        self.assertNotEqual(self.header(header)[0], 0)
        header, entries = fixture()
        status, g = self.header(header)
        entries[60] ^= 1
        self.assertNotEqual(self.partition(entries, g)[0], 0)

    def test_overflow_count_bad_entry_size_and_lba_geometry(self):
        for offset, fmt, value in ((80, "I", 0x2000001), (84, "I", 120), (84, "I", 129),
                                   (72, "Q", 0xffffffffffffffff), (72, "Q", 1),
                                   (40, "Q", 2), (32, "Q", 1022), (24, "Q", 2)):
            header, _ = fixture()
            struct.pack_into("<" + fmt, header, offset, value)
            repair_header(header)
            self.assertNotEqual(self.header(header)[0], 0)

    def test_truncation_header_crc_and_partition_bounds(self):
        header, entries = fixture()
        self.assertNotEqual(self.header(header[:91])[0], 0)
        status, g = self.header(header)
        self.assertNotEqual(self.partition(entries[:-1], g)[0], 0)
        struct.pack_into("<Q", entries, 40, 1023)
        g.entries_crc = zlib.crc32(entries)
        result, first, count = self.partition(entries, g)
        self.assertNotEqual(result, 0)
        self.assertEqual((first, count), (777, 888))

    def test_unused_entry_name_not_selected_and_extended_entry_size(self):
        header, entries = fixture(entry_size=256)
        status, g = self.header(header)
        self.assertEqual(status, 0)
        self.assertEqual(self.partition(entries, g), (0, 16, 85))
        entries[:16] = bytes(16)
        g.entries_crc = zlib.crc32(entries)
        self.assertNotEqual(self.partition(entries, g)[0], 0)

    def test_overlapping_used_partitions_rejected_with_valid_crc(self):
        header, entries = fixture()
        status, g = self.header(header)
        self.assertEqual(status, 0)
        # A differently named second partition must not overlap the root.
        entries[128] = 2
        entries[128 + 56:128 + 56 + 8] = "boot".encode("utf-16-le")
        struct.pack_into("<QQ", entries, 128 + 32, 100, 120)
        struct.pack_into("<I", header, 88, zlib.crc32(entries))
        repair_header(header)
        status, g = self.header(header)
        self.assertEqual(status, 0)
        self.assertNotEqual(self.partition(entries, g)[0], 0)
        struct.pack_into("<Q", entries, 128 + 32, 101)
        struct.pack_into("<I", header, 88, zlib.crc32(entries))
        repair_header(header)
        status, g = self.header(header)
        self.assertEqual(status, 0)
        self.assertEqual(self.partition(entries, g), (0, 16, 85))

    def test_permanent_read_only_scsi_gate(self):
        def allowed(cdb, size, write=0, lun=0, blocks=1024):
            return self.lib.allow(cdb, len(cdb), size, write, lun, blocks)

        def read(lba, count):
            return bytes([0x28, 0]) + struct.pack(">I", lba) + bytes([0]) + struct.pack(">H", count) + bytes([0])

        self.assertEqual(allowed(bytes(6), 0), 1)
        self.assertEqual(allowed(b"\x25" + bytes(9), 8), 1)
        self.assertEqual(allowed(b"\x12\0\0\0\x24\0", 36), 1)
        for lba, count in ((0, 1), (1023, 1), (768, 256)):
            self.assertEqual(allowed(read(lba, count), count * 4096), 1)
        for lba, count in ((1023, 2), (1024, 1), (0, 0), (0, 257), (0xffffffff, 1)):
            self.assertEqual(allowed(read(lba, count), count * 4096), 0)
        self.assertEqual(allowed(read(1, 1), 4096, write=1), 0)
        self.assertEqual(allowed(read(1, 1), 4096, lun=1), 0)
        self.assertEqual(allowed(read(1, 1), 512), 0)
        for index in (1, 6, 9):
            cdb = bytearray(read(1, 1))
            cdb[index] = 1
            self.assertEqual(allowed(bytes(cdb), 4096), 0)
        for cdb in (b"\x2a" + bytes(9), b"\x35" + bytes(9), b"\x1b\0\0\0\x10\0"):
            self.assertEqual(allowed(cdb, 0), 0)


if __name__ == "__main__":
    unittest.main()
