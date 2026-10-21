"""GPT metadata checks distinguish partition edits from unrelated boot padding."""
import struct
import unittest
import zlib

from gpt import fingerprint


def fixture(block=4096, count=19, entry_size=128):
    data = bytearray(65536)
    data[450] = 0xee
    data[510:512] = b"\x55\xaa"
    entries = bytearray(count * entry_size)
    entries[0] = 1
    struct.pack_into("<QQ", entries, 32, 16, 100)
    header = bytearray(92)
    header[:8] = b"EFI PART"
    struct.pack_into("<4I", header, 8, 0x10000, 92, 0, 0)
    struct.pack_into("<4Q", header, 24, 1, 1023, 16, 1022)
    struct.pack_into("<Q3I", header, 72, 2, count, entry_size, zlib.crc32(entries))
    struct.pack_into("<I", header, 16, zlib.crc32(header))
    data[block:block + 92] = header
    data[2 * block:2 * block + len(entries)] = entries
    return data


def repair(data, block=4096):
    lba, count, size = struct.unpack_from("<QII", data, block + 72)
    entries = data[lba * block:lba * block + count * size]
    struct.pack_into("<I", data, block + 88, zlib.crc32(entries))
    struct.pack_into("<I", data, block + 16, 0)
    length = struct.unpack_from("<I", data, block + 12)[0]
    struct.pack_into("<I", data, block + 16, zlib.crc32(data[block:block + length]))


class GPTTests(unittest.TestCase):
    def test_padding_does_not_change_metadata(self):
        before = fixture()
        after = bytearray(before)
        after[33836] ^= 0xff
        after[4096 + 92] ^= 1
        self.assertEqual(fingerprint(bytes(before)), fingerprint(bytes(after)))
        self.assertEqual(fingerprint(bytes(before))["entry_count"], 19)

    def test_partition_change_with_valid_crc_changes_fingerprint(self):
        before = fixture()
        after = bytearray(before)
        struct.pack_into("<Q", after, 8192 + 40, 101)
        repair(after)
        self.assertNotEqual(fingerprint(bytes(before)), fingerprint(bytes(after)))

    def test_rejects_corrupt_header_and_array_crc(self):
        for offset in (4096 + 32, 8192 + 48):
            data = fixture()
            data[offset] ^= 1
            with self.assertRaisesRegex(ValueError, "CRC"):
                fingerprint(bytes(data))

    def test_rejects_truncated_array_and_non_gpt(self):
        data = fixture()
        for blob in (bytes(data[:8192 + 19 * 128 - 1]), b"\xd0\x0d\xfe\xed" + bytes(65532)):
            with self.assertRaises(ValueError):
                fingerprint(blob)

    def test_rejects_bad_geometry_and_excessive_entry_fields(self):
        for offset, fmt, value in ((24, "Q", 2), (32, "Q", 100), (72, "Q", 1),
                                   (80, "I", 0xffffffff), (84, "I", 120), (84, "I", 129)):
            data = fixture()
            struct.pack_into("<" + fmt, data, 4096 + offset, value)
            struct.pack_into("<I", data, 4096 + 16, 0)
            struct.pack_into("<I", data, 4096 + 16, zlib.crc32(data[4096:4188]))
            with self.assertRaises(ValueError):
                fingerprint(bytes(data))

    def test_512_byte_blocks_and_invalid_partition_range(self):
        data = fixture(block=512, count=3)
        self.assertEqual(fingerprint(bytes(data), 512)["block_size"], 512)
        struct.pack_into("<Q", data, 1024 + 32, 1)
        repair(data, 512)
        with self.assertRaisesRegex(ValueError, "usable"):
            fingerprint(bytes(data), 512)


if __name__ == "__main__":
    unittest.main()
