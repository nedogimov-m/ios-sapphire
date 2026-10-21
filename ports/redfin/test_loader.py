"""Exercise the C loader's preflight using the real payload and ADT packers.

The kernel is a synthetic Mach-O: no Apple binaries, physical RAM mappings,
ARM execution or writes to relocation destinations are needed on the host.
"""
import ctypes
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings

from test_fdt import Hardware, tree

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('loader_mkadt', HERE / 'mkadt.py')
mkadt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mkadt)
from tools import mkpayload

PAGE = 0x4000
BASE, MEMORY, VIRT = 0x180000000, 0x1000000, 0xFFFFFE0006000000


def mock_kernel():
    def segment(name, va, size, offset, length):
        return struct.pack('<II16sQQQQIIII', 0x19, 72, name, va, size, offset, length, 7, 5, 0, 0)

    state = [0] * 33
    state[32] = VIRT + PAGE + 0x1000
    thread = struct.pack('<4I33QII', 5, 288, 6, 68, *state, 0, 0)
    commands = (segment(b'__TEXT', VIRT + PAGE, 2 * PAGE, 0, PAGE)
                + segment(b'__DATA', VIRT + 3 * PAGE, PAGE, PAGE, 0x1000) + thread)
    header = struct.pack('<8I', 0xFEEDFACF, 0x100000C, 0, 2, 3, len(commands), 0, 0)
    return (header + commands).ljust(PAGE + 0x1000, b'\0')


class LoaderPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if compiler is None:
            raise unittest.SkipTest('host C compiler required')
        cls.temporary = tempfile.TemporaryDirectory()
        directory = Path(cls.temporary.name)
        (directory / 'config.h').write_text('#define XNU_PAYLOAD_SIZE 65536\n')
        library = directory / 'loader.so'
        subprocess.run([compiler, '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-DREDFIN_LOADER_TEST', '-I', str(directory), str(HERE / 'loader.c'),
                        str(HERE / 'fdt.c'), '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.validate = cls.library.redfin_validate
        cls.validate.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64,
                                 ctypes.c_uint64, ctypes.c_uint64, ctypes.POINTER(Hardware), ctypes.c_uint64]
        cls.validate.restype = ctypes.c_char_p
        cls.library.redfin_fdt.argtypes = [ctypes.c_void_p, ctypes.POINTER(Hardware)]
        cls.library.redfin_fdt.restype = ctypes.c_int
        kernel, device_tree, ramdisk = (directory / name for name in ('kernel', 'redfin.adt', 'init'))
        kernel.write_bytes(mock_kernel())
        device_tree.write_bytes(mkadt.adt.serialize(mkadt.build(BASE, MEMORY, seed=bytes(64))))
        ramdisk.write_bytes(b'static Darwin PID1 placeholder')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)  # Existing packer's open().read().
            cls.payload, cls.info = mkpayload.build(kernel, device_tree, 'cpus=1 rd=md0', ramdisk)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.fdt = ctypes.create_string_buffer(tree(banks=[(BASE, MEMORY)]))
        self.hw = Hardware()
        self.assertEqual(self.library.redfin_fdt(self.fdt, ctypes.byref(self.hw)), 0)

    def check(self, payload=None, mpidr=0, image=None):
        data = self.payload if payload is None else payload
        storage = ctypes.create_string_buffer(len(data) + PAGE)
        source = (ctypes.addressof(storage) + PAGE - 1) & ~(PAGE - 1)
        ctypes.memmove(source, data, len(data))
        return self.validate(source, len(data), source - PAGE if image is None else image,
                             source + len(data), ctypes.addressof(self.fdt), ctypes.byref(self.hw), mpidr)

    def altered(self, offset, value, format='Q'):
        result = bytearray(self.payload)
        struct.pack_into('<' + format, result, offset, value)
        return bytes(result)

    def test_real_packers_produce_accepted_kernel_and_ramdisk_layout(self):
        self.assertIsNone(self.check())
        self.assertEqual(struct.unpack_from('<I', self.payload, 12)[0], 3)
        self.assertIsNotNone(self.info['ramdisk'])
        # The first file offset is only eight-byte aligned in the v1 ABI.
        self.assertEqual(struct.unpack_from('<Q', self.payload, 696)[0] % 16, 8)

    def test_rejects_malformed_header_and_missing_command_terminator(self):
        for offset, format, value in ((0, 'B', 0), (8, 'I', 2), (12, 'I', 0), (12, 'I', 65),
                                      (32, 'Q', 713), (40, 'Q', len(self.payload) + 1)):
            with self.subTest(offset=offset, value=value):
                self.assertIsNotNone(self.check(self.altered(offset, value, format)))
        unterminated = bytearray(self.payload)
        unterminated[72:680] = b'x' * 608
        self.assertIsNotNone(self.check(bytes(unterminated)))
        self.assertIsNotNone(self.check(self.payload[:680]))

    def test_rejects_unbacked_reserved_or_wrapping_ram_window(self):
        self.hw.memory[0].size = PAGE
        self.assertIsNotNone(self.check())
        self.hw.memory[0].size = MEMORY
        self.hw.reserved[0].base, self.hw.reserved[0].size = BASE + 0x400000, PAGE
        self.hw.reservations = 1
        self.assertIsNotNone(self.check())
        self.hw.reservations = 0
        for offset, value in ((56, 0), (56, 1 << 36), (64, MEMORY + 1), (64, (1 << 64) - PAGE)):
            with self.subTest(offset=offset, value=value):
                self.assertIsNotNone(self.check(self.altered(offset, value)))
        self.assertIsNotNone(self.check(image=BASE))

    def test_rejects_overlapping_segments_and_out_of_file_source_ranges(self):
        first_va = struct.unpack_from('<Q', self.payload, 680)[0]
        for offset, value in ((712, first_va), (696, 680), (696, len(self.payload)),
                              (704, 3 * PAGE), (688, (1 << 64) - PAGE), (680, first_va + 1)):
            with self.subTest(offset=offset, value=value):
                self.assertIsNotNone(self.check(self.altered(offset, value)))
        first_offset = struct.unpack_from('<Q', self.payload, 696)[0]
        self.assertIsNotNone(self.check(self.altered(728, first_offset)))

    def test_rejects_entry_in_zero_fill_invalid_kernel_end_and_small_bootargs_window(self):
        first_va = struct.unpack_from('<Q', self.payload, 680)[0]
        self.assertIsNotNone(self.check(self.altered(24, first_va + PAGE + 0x100)))
        kernel_end = struct.unpack_from('<Q', self.payload, 48)[0]
        self.assertIsNotNone(self.check(self.altered(48, kernel_end + PAGE)))
        # No room remains for the ADT or boot_args beyond the last segment.
        self.assertIsNotNone(self.check(self.altered(64, kernel_end - (VIRT & ~(0x2000000 - 1)))))

    def test_rejects_dtb_and_adt_cpu_or_ram_mismatch(self):
        self.assertIsNotNone(self.check(mpidr=0x100))
        self.assertIsNotNone(self.check(mpidr=1))
        self.assertIsNotNone(self.check(self.altered(56, BASE + PAGE)))
        adt_offset = struct.unpack_from('<Q', self.payload, 32)[0]
        self.assertIsNotNone(self.check(self.altered(adt_offset, 0)))
        self.fdt[0] = b'\0'
        self.assertIsNotNone(self.check())


if __name__ == '__main__':
    unittest.main()
