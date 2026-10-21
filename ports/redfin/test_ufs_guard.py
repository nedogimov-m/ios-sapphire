"""Host-check actual SCSI/Query fences; no device or controller access."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BLOCK = 4096
COMMANDS = {
    0x00: (bytes(6), 0),  # TEST UNIT READY
    0x12: (bytes([0x12, 0, 0, 0, 36, 0]), 36),  # Standard INQUIRY, EVPD=0.
    0x25: (bytes([0x25]) + bytes(9), 8),  # READ CAPACITY(10)
    0x28: (bytes([0x28, 0, 0, 0, 0, 1, 0, 0, 1, 0]), BLOCK),  # GPT header only.
}
WAKE_COMMANDS = {
    0x03: (bytes([0x03, 0, 0, 0, 18, 0]), 18),  # Device WLUN REQUEST SENSE.
    0x1B: (bytes([0x1B, 0, 0, 0, 0x10, 0]), 0),  # ACTIVE, DMA_NONE.
}


def actual_guard():
    lines = (HERE / 'ufs-read-probe.patch').read_text().splitlines()
    marker = '+\tif (redfin_ufs_read_only) {'
    if lines.count(marker) != 1:
        raise AssertionError('expected one complete added SCSI fence in patch')
    body, depth = [], 0
    for line in lines[lines.index(marker):]:
        if not line.startswith('+') or line.startswith('+++'):
            raise AssertionError('SCSI fence must be completely represented by added C lines')
        code = line[1:]
        body.append(code)
        depth += code.count('{') - code.count('}')
        if depth == 0:
            return '\n'.join(body)
    raise AssertionError('unterminated SCSI fence')


def actual_function(name):
    added = '\n'.join(line[1:] for line in (HERE / 'ufs-read-probe.patch').read_text().splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    signature = added.index(name + '(')
    start = added.rfind('\nstatic ', 0, signature) + 1
    opening = added.index('{', signature)
    depth = 0
    for end in range(opening, len(added)):
        depth += (added[end] == '{') - (added[end] == '}')
        if depth == 0:
            return added[start:end + 1]
    raise AssertionError('unterminated added function: ' + name)


class UfsReadFenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if compiler is None:
            raise unittest.SkipTest('host C compiler required for the actual SCSI fence')
        cls.temporary = tempfile.TemporaryDirectory()
        directory = Path(cls.temporary.name)
        source = '''#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <strings.h>
#define UFS_BLOCK 4096u
static bool redfin_ufs_read_only = true;
static bool redfin_ufs_capacity_valid;
static bool redfin_ufs_wake_active;
static struct { unsigned lun; } su;
''' + '\n'.join(actual_function(name) for name in (
            'redfin_ufs_be32', 'redfin_ufs_query_allowed', 'redfin_ufs_query_request',
            'redfin_ufs_query_response', 'redfin_ufs_gpt_allowed')) + '''
int query_allowed(uint8_t op, uint8_t id) { return redfin_ufs_query_allowed(op, id); }
int query_request(uint8_t *r, unsigned size, uint8_t op, uint8_t id, uint8_t tag)
{ return redfin_ufs_query_request(r, size, op, id, tag); }
int query_response(const uint8_t *r, unsigned size, uint8_t op, uint8_t id, uint8_t tag, uint32_t *value)
{ return redfin_ufs_query_response(r, size, op, id, tag, value); }
int gpt_allowed(int error, uint32_t last, uint32_t block)
{ return redfin_ufs_gpt_allowed(error, last, block); }
int fence(const uint8_t *cdb, unsigned cdb_len, uint32_t len, bool write, unsigned lun, bool capacity, bool wake)
{
    su.lun = lun;
    redfin_ufs_capacity_valid = capacity;
    redfin_ufs_wake_active = wake;
''' + actual_guard() + '\n    return 0;\n}\n'
        (directory / 'fence.c').write_text(source)
        library = directory / 'fence.so'
        subprocess.run([compiler, '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(directory / 'fence.c'), '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.fence = cls.library.fence
        cls.fence.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint32,
                             ctypes.c_bool, ctypes.c_uint, ctypes.c_bool, ctypes.c_bool]
        cls.fence.restype = ctypes.c_int
        cls.library.query_allowed.argtypes = [ctypes.c_uint8, ctypes.c_uint8]
        cls.library.query_request.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                            ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8]
        cls.library.query_response.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint8,
                                             ctypes.c_uint8, ctypes.c_uint8,
                                             ctypes.POINTER(ctypes.c_uint32)]
        cls.library.gpt_allowed.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def result(self, command, length, write=False, lun=0, cdb_len=None, capacity=True, wake=False):
        buffer = None if command is None else ctypes.create_string_buffer(command)
        size = len(command) if cdb_len is None and command is not None else (cdb_len or 0)
        return self.fence(buffer, size, length, write, lun, capacity, wake)

    def test_wake_commands_require_device_wlun_and_scoped_mode3_capability(self):
        for opcode in range(256):
            command, length = WAKE_COMMANDS.get(opcode, (bytes([opcode]) + bytes(5), 0))
            for wake in (False, True):
                for write in (False, True):
                    allowed = opcode in WAKE_COMMANDS and wake and not write
                    self.assertEqual(self.result(command, length, write, 0xD0, wake=wake) == 0,
                                     allowed, (opcode, wake, write))
        for command, length in WAKE_COMMANDS.values():
            for lun in range(256):
                self.assertEqual(self.result(command, length, lun=lun, wake=True) == 0,
                                 lun == 0xD0, lun)
            for size in (0, 1, 5, 7, 10, 16, 0xFFFFFFFF):
                self.assertNotEqual(self.result(command, length, lun=0xD0, cdb_len=size, wake=True), 0)
            for transfer in (0, 1, 17, 18, 19, 36, BLOCK, 0xFFFFFFFF):
                if transfer != length:
                    self.assertNotEqual(self.result(command, transfer, lun=0xD0, wake=True), 0)
            for field in range(6):
                for value in range(256):
                    if value == command[field]:
                        continue
                    corrupt = bytearray(command)
                    corrupt[field] = value
                    self.assertNotEqual(self.result(bytes(corrupt), length, lun=0xD0, wake=True), 0,
                                        (command.hex(), field, value))

    def test_all_opcodes_directions_and_luns(self):
        for opcode in range(256):
            command, length = COMMANDS.get(opcode, (bytes([opcode]) + bytes(9), 0))
            for write in (False, True):
                for lun in (0, 1):
                    with self.subTest(opcode=opcode, write=write, lun=lun):
                        allowed = opcode in COMMANDS and not write and lun == 0
                        self.assertEqual(self.result(command, length, write, lun) == 0, allowed)

    def test_gpt_read_cannot_reach_other_lbas_counts_or_flags(self):
        command, length = COMMANDS[0x28]
        # Exercise every byte value of the complete LBA, count and flag fields.
        for field in range(1, 10):
            for value in range(256):
                if value == command[field]:
                    continue
                mutated = bytearray(command)
                mutated[field] = value
                with self.subTest(field=field, value=value):
                    self.assertNotEqual(self.result(bytes(mutated), length), 0)

    def test_inquiry_cannot_request_vpd_pages_or_serial_number(self):
        command, length = COMMANDS[0x12]
        for field in (1, 2):
            for value in range(1, 256):
                mutated = bytearray(command)
                mutated[field] = value
                with self.subTest(field=field, value=value):
                    self.assertNotEqual(self.result(bytes(mutated), length), 0)

    def test_command_and_transfer_lengths_are_exact_and_bounded(self):
        for opcode, (command, length) in COMMANDS.items():
            for size in (0, 1, 5, 6, 7, 9, 10, 11, 16, 0xFFFFFFFF):
                if size != len(command):
                    with self.subTest(opcode=opcode, cdb_len=size):
                        self.assertNotEqual(self.result(command, length, cdb_len=size), 0)
            for transfer in (0, 1, 7, 8, 9, 35, 36, 37, BLOCK - 1, BLOCK, BLOCK + 1,
                             512 << 10, (512 << 10) + 1, 0xFFFFFFFF):
                if transfer != length:
                    with self.subTest(opcode=opcode, transfer=transfer):
                        self.assertNotEqual(self.result(command, transfer), 0)
            self.assertNotEqual(self.result(command, length, lun=255), 0)
        self.assertNotEqual(self.result(None, 0, cdb_len=0), 0)
        self.assertNotEqual(self.result(None, 0, cdb_len=10), 0)

    def test_gpt_reads_require_successful_capacity_with_supported_block_size(self):
        command, length = COMMANDS[0x28]
        self.assertNotEqual(self.result(command, length, capacity=False), 0)
        for error in (0, 5, 6, 22, 30, 60):
            for last in (0, 1, 0x1000, 0xFFFFFFFF):
                for block in (0, 512, 4096, 8192):
                    with self.subTest(error=error, last=last, block=block):
                        allowed = error == 0 and last not in (0, 0xFFFFFFFF) and block == BLOCK
                        self.assertEqual(self.library.gpt_allowed(error, last, block) != 0, allowed)

    def test_queries_allow_only_current_power_attribute_and_init_flag_reads(self):
        for opcode in range(256):
            for idn in range(256):
                allowed = (opcode, idn) in ((3, 2), (5, 1))
                self.assertEqual(self.library.query_allowed(opcode, idn) != 0, allowed,
                                 (opcode, idn))
        for opcode, idn in ((3, 2), (5, 1)):
            buffer = ctypes.create_string_buffer(bytes([0xAA]) * 64)
            self.assertEqual(self.library.query_request(buffer, 64, opcode, idn, 42), 0)
            expected = bytearray(32)
            expected[0], expected[3], expected[5] = 0x16, 42, 1
            expected[12], expected[13] = opcode, idn
            self.assertEqual(buffer.raw[:32], expected)
            self.assertEqual(buffer.raw[32:64], bytes([0xAA]) * 32)
            for size in range(32):
                before = buffer.raw
                self.assertNotEqual(self.library.query_request(buffer, size, opcode, idn, 42), 0)
                self.assertEqual(buffer.raw, before)
        for opcode, idn in ((4, 2), (6, 1), (7, 1), (8, 1), (1, 5)):
            self.assertNotEqual(self.library.query_request(buffer, 64, opcode, idn, 42), 0)
        self.assertNotEqual(self.library.query_request(None, 32, 3, 2, 42), 0)

    def test_query_response_rejects_truncation_mismatch_and_data_payloads(self):
        def packet(opcode, idn, value):
            response = bytearray(32)
            response[0], response[3], response[12], response[13] = 0x36, 42, opcode, idn
            response[20:24] = value.to_bytes(4, 'big')
            return response

        for opcode, idn, value in ((3, 2, 3), (5, 1, 0), (5, 1, 1)):
            response = packet(opcode, idn, value)
            output = ctypes.c_uint32(0xDEADBEEF)
            buffer = ctypes.create_string_buffer(bytes(response))
            self.assertEqual(self.library.query_response(buffer, 32, opcode, idn, 42,
                                                         ctypes.byref(output)), 0)
            self.assertEqual(output.value, value)
            for size in range(32):
                output.value = 0xDEADBEEF
                self.assertNotEqual(self.library.query_response(buffer, size, opcode, idn, 42,
                                                                ctypes.byref(output)), 0)
                self.assertEqual(output.value, 0xDEADBEEF)
            for field in (0, 1, 2, 3, 6, 7, 8, 10, 11, 12, 13, 14, 15, 18, 19):
                corrupt = bytearray(response)
                corrupt[field] ^= 0xFF
                output.value = 0xDEADBEEF
                self.assertNotEqual(self.library.query_response(ctypes.create_string_buffer(bytes(corrupt)),
                    32, opcode, idn, 42, ctypes.byref(output)), 0, field)
                self.assertEqual(output.value, 0xDEADBEEF)
        response = ctypes.create_string_buffer(bytes(packet(5, 1, 2)))
        self.assertNotEqual(self.library.query_response(response, 32, 5, 1, 42, ctypes.byref(output)), 0)
        self.assertNotEqual(self.library.query_response(None, 32, 3, 2, 42, ctypes.byref(output)), 0)
        self.assertNotEqual(self.library.query_response(buffer, 32, 3, 2, 42, None), 0)


if __name__ == '__main__':
    unittest.main()
