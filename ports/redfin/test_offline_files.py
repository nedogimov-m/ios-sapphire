"""Regress sparse zero blocks against a device containing stale free data."""
import copy
from pathlib import Path
import tempfile
import unittest

from ports.redfin.offline_files import BLOCK_BYTES as B, plan_blocks, read_file, verify_file, zero_hole_damage


class OfflineFileTests(unittest.TestCase):
    def test_new_zero_blocks_replace_unknown_live_bytes_and_whole_file_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = [Path(directory) / name for name in ('old.img', 'new.img')]
            old.write_bytes(bytes(8 * B))
            new.write_bytes(bytes(8 * B))
            blocks = plan_blocks(old, new, range(8), {2, 3})
            self.assertEqual(blocks, [2, 3])
            device = bytearray(b'\xa7' * (8 * B))
            with new.open('rb') as stream:
                for block in blocks:
                    stream.seek(block * B)
                    device[block*B:(block+1)*B] = stream.read(B)
            record = dict(block_bytes=B, bytes=2*B, extents=[[2, 2]])
            reader = lambda start, count: bytes(device[start*B:(start+count)*B])
            verify_file(reader, record, bytes(2*B))
            device[3*B+11] = 1
            with self.assertRaisesRegex(ValueError, 'complete installed file'):
                verify_file(reader, record, bytes(2*B))

    def test_existing_unchanged_blocks_are_preserved_and_nonzero_updates_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = [Path(directory) / name for name in ('old.img', 'new.img')]
            old.write_bytes(b'a' * (8 * B))
            data = bytearray(old.read_bytes())
            data[4*B+3] = ord('b')
            new.write_bytes(data)
            self.assertEqual(plan_blocks(old, new, range(8), {2}), [2, 4])

    def test_complete_extent_order_and_owner_padding_do_not_hide_bytes(self):
        image = b''.join(bytes([n]) * B for n in range(12))
        reader = lambda start, count: image[start*B:(start+count)*B]
        record = dict(block_bytes=B, bytes=B+19, extents=[[9, 1], [2, 1]])
        self.assertEqual(read_file(reader, record), bytes([9])*B + bytes([2])*19)
        for extents in ([[2, 1], [2, 1]], [[0, 1]], [[4194303, 2]], [[2, 3]]):
            changed = copy.deepcopy(record)
            changed['extents'] = extents
            with self.assertRaises(ValueError):
                read_file(reader, changed)
        with self.assertRaisesRegex(ValueError, 'short complete-file'):
            read_file(lambda start, count: b'', record)

    def test_only_observed_zero_hole_damage_is_eligible_for_the_narrow_repair(self):
        expected = b'valid-code' + bytes(2*B) + b'valid-signature'
        actual = b'valid-code' + b'\xa7'*(2*B) + b'valid-signature'
        self.assertEqual(zero_hole_damage(actual, expected), 2*B)
        for damaged in (b'X'+actual[1:], actual[:-1], expected):
            with self.assertRaises(ValueError):
                zero_hole_damage(damaged, expected)

    def test_incomplete_staging_cannot_authorize_a_block_write(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = [Path(directory) / name for name in ('old.img', 'new.img')]
            old.write_bytes(bytes(B)); new.write_bytes(bytes(B))
            with self.assertRaisesRegex(ValueError, 'short staged'):
                plan_blocks(old, new, {1}, {1})


if __name__ == '__main__':
    unittest.main()
