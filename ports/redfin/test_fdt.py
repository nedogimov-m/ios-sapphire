"""Exercise the freestanding parser on host memory, without a device."""

import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


class Region(ctypes.Structure):
    _fields_ = [("base", ctypes.c_uint64), ("size", ctypes.c_uint64)]


class Hardware(ctypes.Structure):
    _fields_ = [("memory", Region * 16), ("splash", Region),
                ("banks", ctypes.c_uint), ("redfin", ctypes.c_int),
                ("psci_smc", ctypes.c_int), ("reserved", Region * 128),
                ("reservations", ctypes.c_uint), ("watchdog", Region)]


def u32(value):
    return struct.pack(">I", value)


def aligned(data):
    return data + bytes(-len(data) % 4)


def dtb(structure, strings):
    # A terminated reservation map precedes the structure and strings blocks.
    total = 56 + len(structure) + len(strings)
    return (struct.pack(">10I", 0xD00DFEED, total, 56,
                        56 + len(structure), 40, 17, 16, 0,
                        len(strings), len(structure))
            + bytes(16) + structure + strings)


def tree(compat=b"google,redfin-sm7250\0qcom,sm7250\0", banks=None,
         root_cells=(2, 2), reserved_cells=(2, 2), memory_reg=None,
         watchdog=b"qcom,msm-watchdog\0", watchdog_reg=None, reg_first=False):
    structure = bytearray()
    strings = bytearray()
    offsets = {}

    def begin(name):
        structure.extend(u32(1) + aligned(name.encode() + b"\0"))

    def end():
        structure.extend(u32(2))

    def prop(name, value):
        if name not in offsets:
            offsets[name] = len(strings)
            strings.extend(name.encode() + b"\0")
        structure.extend(u32(3) + u32(len(value)) + u32(offsets[name]) + aligned(value))

    begin("")
    prop("compatible", compat)
    prop("#address-cells", u32(root_cells[0]))
    prop("#size-cells", u32(root_cells[1]))
    begin("memory@140000000")
    if banks is None:
        banks = [(0x140000000, 0x100000000), (0x80000000, 0x20000000)]
    prop("reg", memory_reg if memory_reg is not None else
         b"".join(struct.pack(">QQ", base, size) for base, size in banks))
    end()
    begin("reserved-memory")
    prop("#address-cells", u32(reserved_cells[0]))
    prop("#size-cells", u32(reserved_cells[1]))
    begin("cont_splash_region")
    prop("reg", struct.pack(">QQ", 0x9C000000, 0x2400000))
    end()
    end()
    begin("psci")
    prop("compatible", b"arm,psci-1.0\0")
    prop("method", b"smc\0")
    end()
    begin("soc")
    prop("#address-cells", u32(1))
    prop("#size-cells", u32(1))
    begin("watchdog@17c10000")
    if watchdog_reg is None:
        watchdog_reg = struct.pack(">II", 0x17C10000, 0x1000)
    items = [("compatible", watchdog), ("reg", watchdog_reg)]
    for name, value in reversed(items) if reg_first else items:
        prop(name, value)
    end()
    end()
    end()
    structure.extend(u32(9))
    return dtb(bytes(structure), bytes(strings))


class FdtParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("host cc is required for the C parser tests")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        source = Path(__file__).with_name("fdt.c")
        library = Path(cls.temporary.name) / "redfin-fdt.so"
        result = subprocess.run(
            [compiler, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
             str(source), "-o", str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("host parser compile failed:\n" + result.stderr)
        cls.library = ctypes.CDLL(str(library))
        cls.library.redfin_fdt.argtypes = [ctypes.c_void_p, ctypes.POINTER(Hardware)]
        cls.library.redfin_fdt.restype = ctypes.c_int

    def parse(self, blob):
        # Use writable host memory so any accidental write is observable.
        original = bytes(blob)
        source = bytearray(blob)
        buffer = (ctypes.c_ubyte * len(source)).from_buffer(source)
        hardware = Hardware()
        status = self.library.redfin_fdt(buffer, ctypes.byref(hardware))
        self.assertEqual(bytes(source), original, "parser modified its FDT input")
        return status, hardware

    def test_redfin_high_memory_splash_and_psci(self):
        for compat in (b"google,redfin-sm7250\0qcom,sm7250\0", b"google,redfin\0"):
            with self.subTest(compatible=compat):
                status, hardware = self.parse(tree(compat=compat))
                self.assertEqual(status, 0)
                self.assertEqual((hardware.redfin, hardware.psci_smc, hardware.banks), (1, 1, 2))
                self.assertEqual((hardware.memory[0].base, hardware.memory[0].size),
                                 (0x140000000, 0x100000000))
                self.assertEqual((hardware.memory[1].base, hardware.memory[1].size),
                                 (0x80000000, 0x20000000))
                self.assertEqual((hardware.splash.base, hardware.splash.size),
                                 (0x9C000000, 0x2400000))
                self.assertEqual((hardware.watchdog.base, hardware.watchdog.size),
                                 (0x17C10000, 0x1000))

    def test_watchdog_reg_order_cells_and_compatible(self):
        for reg in (struct.pack(">II", 0x17C10000, 0x1000),
                    struct.pack(">QQ", 0x17C10000, 0x1000)):
            for first in (False, True):
                status, hw = self.parse(tree(watchdog_reg=reg, reg_first=first))
                self.assertEqual((status, hw.watchdog.base, hw.watchdog.size),
                                 (0, 0x17C10000, 0x1000))
        status, hw = self.parse(tree(watchdog=b"qcom,unrelated\0"))
        self.assertEqual((status, hw.watchdog.base, hw.watchdog.size), (0, 0, 0))
        for reg in (bytes(7), struct.pack(">II", 0x17C10000, 0)):
            self.assertEqual(self.parse(tree(watchdog_reg=reg))[0], -1)

    def test_unknown_device_parses_without_redfin_identity(self):
        status, hardware = self.parse(tree(compat=b"google,bramble\0qcom,sm7250\0"))
        self.assertEqual(status, 0)
        self.assertEqual(hardware.redfin, 0)
        self.assertEqual(hardware.banks, 2)

    def test_rejects_bad_header_offsets_sizes_and_versions(self):
        for offset, value in ((0, 0xEDFE0DD0), (4, 39), (4, 0xFFFFFFFF),
                              (8, 39), (8, 57), (8, 0xFFFFFFFF),
                              (12, 39), (12, 0xFFFFFFFF), (20, 16),
                              (24, 18), (32, 0xFFFFFFFF), (36, 0xFFFFFFFF)):
            damaged = bytearray(tree())
            struct.pack_into(">I", damaged, offset, value)
            with self.subTest(header_offset=offset, value=value):
                self.assertEqual(self.parse(damaged)[0], -1)

    def test_rejects_unterminated_node_name(self):
        self.assertEqual(self.parse(dtb(u32(1) + b"no-nul!!", b"compatible\0"))[0], -1)

    def test_rejects_unterminated_property_name(self):
        structure = (u32(1) + bytes(4) + u32(3) + u32(4) + u32(0)
                     + b"test" + u32(2) + u32(9))
        self.assertEqual(self.parse(dtb(structure, b"compatible"))[0], -1)

    def test_rejects_property_name_offset_outside_strings(self):
        structure = (u32(1) + bytes(4) + u32(3) + u32(4) + u32(0xFFFFFFFF)
                     + b"test" + u32(2) + u32(9))
        self.assertEqual(self.parse(dtb(structure, b"compatible\0"))[0], -1)

    def test_rejects_truncated_property_header_or_value(self):
        structures = [u32(1) + bytes(4) + u32(3) + u32(4),
                      u32(1) + bytes(4) + u32(3) + u32(8) + u32(0) + b"four"]
        for structure in structures:
            with self.subTest(structure=structure):
                self.assertEqual(self.parse(dtb(structure, b"compatible\0"))[0], -1)

    def test_memory_bank_limit(self):
        banks = [(0x140000000 + index * 0x100000, 0x100000) for index in range(16)]
        status, hardware = self.parse(tree(banks=banks))
        self.assertEqual((status, hardware.banks), (0, 16))
        self.assertEqual(self.parse(tree(banks=banks + [(0x200000000, 0x1000)]))[0], -1)

    def test_rejects_wrapping_and_empty_regions(self):
        for region in ((0xFFFFFFFFFFFFFFF0, 0x20), (0x140000000, 0)):
            with self.subTest(region=region):
                self.assertEqual(self.parse(tree(banks=[region]))[0], -1)

    def test_rejects_invalid_cell_counts_and_reg_lengths(self):
        for cells in ((0, 2), (3, 2), (2, 0), (2, 3), (0xFFFFFFFF, 2)):
            for keyword in ("root_cells", "reserved_cells"):
                with self.subTest(cells=cells, node=keyword):
                    self.assertEqual(self.parse(tree(**{keyword: cells}))[0], -1)
        self.assertEqual(self.parse(tree(memory_reg=bytes(15)))[0], -1)

    def test_null_input_is_rejected_and_clears_output(self):
        hardware = Hardware()
        hardware.redfin = hardware.banks = 99
        self.assertEqual(self.library.redfin_fdt(None, ctypes.byref(hardware)), -1)
        self.assertEqual((hardware.redfin, hardware.banks), (0, 0))


if __name__ == "__main__":
    unittest.main()
