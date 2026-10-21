"""Synthetic FDTs test address ownership and parser failures without a device."""
import struct
import unittest

from memory import memory_map, validate_window


def fixture(banks=((0x100000000, 0x100000000),), fixed=(), header=(), dynamic=False,
            compatible=b"google,redfin-sm7250\0", ranges=b"", cells=2):
    strings, body = bytearray(), bytearray()

    def word(n):
        return struct.pack(">I", n)

    def begin(name):
        data = name.encode() + b"\0"
        body.extend(word(1) + data + bytes(-len(data) % 4))

    def prop(name, data):
        offset = len(strings)
        strings.extend(name.encode() + b"\0")
        body.extend(word(3) + word(len(data)) + word(offset) + data + bytes(-len(data) % 4))

    def reg(values):
        return b"".join(struct.pack(">QQ", *pair) for pair in values)

    begin("")
    prop("compatible", compatible)
    for name in ("#address-cells", "#size-cells"):
        prop(name, word(2))
    begin("memory")
    prop("reg", reg(banks))
    body.extend(word(2))
    begin("reserved-memory")
    for name in ("#address-cells", "#size-cells"):
        prop(name, word(cells))
    prop("ranges", ranges)
    begin("fixed")
    prop("reg", reg(fixed or ((0x80000000, 0x4000),)))
    body.extend(word(2))
    if dynamic:
        begin("pool")
        prop("size", struct.pack(">Q", 0x10000))
        prop("alloc-ranges", reg(banks))
        body.extend(word(2))
    body.extend(word(2) + word(2) + word(9))
    reservations = reg(header) + bytes(16)
    start = 40 + len(reservations)
    return (struct.pack(">10I", 0xD00DFEED, start + len(body) + len(strings), start,
                        start + len(body), 40, 17, 16, 0, len(strings), len(body))
            + reservations + body + strings)


class MemoryTests(unittest.TestCase):
    def test_boundary_and_dynamic_rules(self):
        blob = fixture(dynamic=True)
        self.assertTrue(validate_window(blob, 0x100000000, 0x100000000))
        self.assertEqual(len(memory_map(blob)["dynamic_pools"]), 1)

    def test_every_reg_and_header_reservation_checked(self):
        for blob in (fixture(fixed=((0x80000000, 0x4000), (0x180000000, 0x4000))),
                     fixture(header=((0x180000000, 0x4000),))):
            with self.assertRaisesRegex(ValueError, "reservation"):
                validate_window(blob, 0x17fffc000, 0x8000)
            self.assertTrue(validate_window(blob, 0x17fffc000, 0x4000))

    def test_rejects_unaligned_outside_and_cross_bank(self):
        blob = fixture(banks=((0x100000000, 0x4000), (0x100004000, 0x4000)))
        for base, size in ((0x100000001, 0x4000), (0x100000000, 1),
                           (0x100000000, 0x8000), (0x200000000, 0x4000),
                           (0x100000000, 0), ((1 << 64) - 0x4000, 0x8000)):
            with self.assertRaises(ValueError):
                validate_window(blob, base, size)

    def test_rejects_unknown_identity_translation_and_cells(self):
        for blob in (fixture(compatible=b"google,bramble\0"), fixture(ranges=bytes(16)),
                     fixture(cells=1), fixture(fixed=((0x100000000, 0),))):
            with self.assertRaises(ValueError):
                validate_window(blob, 0x100000000, 0x4000)

    def test_rejects_truncation_corrupt_blocks_and_unterminated_names(self):
        valid = fixture()
        bad = [valid[:n] for n in (0, 39, len(valid) - 1)]
        for index, value in ((0, 0), (2, 41), (3, 40), (4, 41), (8, 0xffffffff)):
            blob = bytearray(valid)
            struct.pack_into(">I", blob, index * 4, value)
            bad.append(bytes(blob))
        bad.append(valid[:-1] + b"x")
        for blob in bad:
            with self.assertRaises(ValueError):
                validate_window(blob, 0x100000000, 0x4000)


if __name__ == "__main__":
    unittest.main()
