"""Reject inconsistent EFS labels, geometry and GPT corruption before reads."""
import importlib.util
from pathlib import Path
import struct
import unittest

from test_gpt import fixture, repair

SPEC = importlib.util.spec_from_file_location('capture_rmtfs', Path(__file__).with_name('capture-rmtfs.py'))
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class RmtfsCaptureTests(unittest.TestCase):
    def prefix(self):
        data = fixture()
        data[8192 + 56:8192 + 128] = 'modemst1'.encode('utf-16le').ljust(72, b'\0')
        repair(data)
        return data

    def test_partition_size_comes_from_crc_checked_gpt_and_matches_link_number(self):
        prefix = self.prefix()
        size, proof = capture.gpt_partition(bytes(prefix), 'modemst1', 1)
        first, last = struct.unpack_from('<QQ', prefix, 8192 + 32)
        self.assertEqual(size, (last - first + 1) * 4096)
        self.assertEqual(proof['block_size'], 4096)
        for label, number in (('modemst2', 1), ('modemst1', 2)):
            with self.assertRaises(ValueError):
                capture.gpt_partition(bytes(prefix), label, number)

    def test_bad_crc_and_oversize_geometry_never_produce_a_read_length(self):
        prefix = self.prefix(); prefix[8192 + 56] ^= 1
        with self.assertRaises(ValueError):
            capture.gpt_partition(bytes(prefix), 'modemst1', 1)
        prefix = self.prefix()
        struct.pack_into('<Q', prefix, 4096 + 32, 4096)
        struct.pack_into('<Q', prefix, 4096 + 48, 4095)
        struct.pack_into('<QQ', prefix, 8192 + 32, 16, 2048)
        repair(prefix)
        with self.assertRaisesRegex(ValueError, 'bounds'):
            capture.gpt_partition(bytes(prefix), 'modemst1', 1)


if __name__ == '__main__':
    unittest.main()
