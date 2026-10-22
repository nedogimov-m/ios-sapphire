"""Checksummed liblp fixtures; no block-device or firmware access."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import hashlib

SPEC = importlib.util.spec_from_file_location('bounded_super_inventory', Path(__file__).with_name('super_inventory.py'))
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)

MAXIMUM, SLOTS = 65536, 3
PRIMARY, BACKUP = 12288+MAXIMUM, 12288+MAXIMUM*SLOTS+MAXIMUM


def named(value):
    return value.encode().ljust(36, b'\0')


def fixture(*, partitions=None, extents=None, maximum_group=M.MAX_VENDOR, device=None):
    partitions = partitions or [('vendor_b', 4, 0, 2, 1), ('vendor_b-cow', 0, 2, 1, 2)]
    extents = extents or [(8192, 0, 2048, 0), (8, 0, 16384, 0), (8200, 0, 32768, 0)]
    device = device or (2048, 131072, 0, M.SUPER_BYTES, 'super', 0)
    partition_data = b''.join(named(n)+struct.pack('<4I', *fields) for n, *fields in partitions)
    extent_data = b''.join(struct.pack('<QIQI', *fields) for fields in extents)
    group_data = b''.join(named(n)+struct.pack('<IQ', flags, maximum) for n, flags, maximum in
                          [('default', 0, 0), ('google_dynamic_partitions_b', 0, maximum_group), ('cow', 0, 0)])
    first, alignment, alignment_offset, size, device_name, flags = device
    device_data = struct.pack('<QIIQ36sI', first, alignment, alignment_offset, size, named(device_name), flags)
    tables = partition_data+extent_data+group_data+device_data
    header = bytearray(256)
    struct.pack_into('<IHHI', header, 0, 0x414c5030, 10, 2, 256)
    struct.pack_into('<I', header, 44, len(tables))
    header[48:80] = hashlib.sha256(tables).digest()
    at = 0
    for offset, count, size in ((80, len(partitions), 52), (92, len(extents), 24), (104, 3, 48), (116, 1, 64)):
        struct.pack_into('<III', header, offset, at, count, size)
        at += count*size
    struct.pack_into('<I', header, 128, 1)
    header[12:44] = hashlib.sha256(header).digest()
    geo = bytearray(52)
    struct.pack_into('<II', geo, 0, 0x616c4467, 52)
    struct.pack_into('<III', geo, 40, MAXIMUM, SLOTS, 4096)
    geo[8:40] = hashlib.sha256(geo).digest()
    result = bytearray(12288+2*MAXIMUM*SLOTS)
    result[4096:4148] = result[8192:8244] = geo
    for offset in (PRIMARY, BACKUP):
        result[offset:offset+len(header)+len(tables)] = header+tables
    return result


def header_field(data, relative, payload, both=True):
    for offset in ((PRIMARY, BACKUP) if both else (PRIMARY,)):
        data[offset+relative:offset+relative+len(payload)] = payload
        header = bytearray(data[offset:offset+256])
        header[12:44] = bytes(32)
        data[offset+12:offset+44] = hashlib.sha256(header).digest()


class SuperInventoryTests(unittest.TestCase):
    def test_valid_plan_preserves_base_and_cow_distinction(self):
        data = fixture()
        result = M.plan(data, '(bootloader) current-slot: b\nFinished. Total time: 0.001s\n')
        self.assertEqual(result['vendor']['bytes'], 8200*512)
        self.assertEqual(result['view'], 'raw-vendor_b-base')
        self.assertFalse(result['current_effective_image_proven'])
        self.assertTrue(result['virtual_ab'])
        self.assertTrue(result['snapshot_status_unproven'])
        self.assertEqual(result['cow_partitions'][0]['name'], 'vendor_b-cow')
        extents = result['capture_extents']
        self.assertEqual([(e['source_offset_bytes'], e['output_offset_bytes'], e['bytes']) for e in extents],
                         [(2048*512, 0, 8192*512), (16384*512, 8192*512, 8*512)])
        self.assertEqual([(e['dd_block_size'], e['dd_skip'], e['dd_count']) for e in extents],
                         [(4096, 256, 1024), (4096, 2048, 1)])
        self.assertEqual(data, fixture(), 'parser changed captured bytes')

    def test_external_current_slot_proof_is_unique_and_exact(self):
        for proof in ('', 'current-slot: a\n', '_b', 'current-slot: b\ncurrent-slot: b\n',
                      'current-slot: b trailing\n', 'current-slot: b\ncurrent-slot: a\n'):
            with self.subTest(proof=proof), self.assertRaises(M.Invalid):
                M.plan(fixture(), proof)

    def test_both_geometry_copies_checksum_and_agree(self):
        for at in (4096, 8192):
            data = fixture()
            data[at+40] ^= 1
            with self.subTest(at=at), self.assertRaisesRegex(M.Invalid, 'checksum'):
                M.plan(data, 'current-slot: b')
        data = fixture()
        geo = bytearray(data[8192:8244])
        struct.pack_into('<I', geo, 48, 8192)
        geo[8:40] = bytes(32)
        geo[8:40] = hashlib.sha256(geo).digest()
        data[8192:8244] = geo
        with self.assertRaisesRegex(M.Invalid, 'geometries disagree'):
            M.plan(data, 'current-slot: b')

    def test_missing_selected_backup_range_is_refused(self):
        with self.assertRaisesRegex(M.Invalid, 'missing range'):
            M.plan(fixture()[:BACKUP], 'current-slot: b')
        with self.assertRaises(M.Invalid):
            M.plan(bytes(M.MAX_PREFIX+1), 'current-slot: b')

    def test_both_headers_tables_and_full_slot_copies_are_verified(self):
        for at in (PRIMARY+12, BACKUP+12, PRIMARY+256, BACKUP+256):
            data = fixture()
            data[at] ^= 1
            with self.subTest(at=at), self.assertRaisesRegex(M.Invalid, 'checksum|SHA256'):
                M.plan(data, 'current-slot: b')
        data = fixture()
        header_field(data, 128, struct.pack('<I', 0), both=False)
        with self.assertRaisesRegex(M.Invalid, 'copies disagree'):
            M.plan(data, 'current-slot: b')

    def test_checked_header_geometry_table_bounds_and_overlap(self):
        for relative, value in ((8, 128), (44, MAXIMUM), (80, 1), (84, 4097), (88, 48), (92, 0), (132, 1)):
            with self.subTest(relative=relative):
                data = fixture()
                header_field(data, relative, struct.pack('<I', value))
                with self.assertRaises(M.Invalid):
                    M.plan(data, 'current-slot: b')

    def test_super_identity_size_flags_and_usable_region(self):
        cases = ((2048, 131072, 0, M.SUPER_BYTES-512, 'super', 0),
                 (1, 131072, 0, M.SUPER_BYTES, 'super', 0),
                 (2048, 131072, 0, M.SUPER_BYTES, 'super', 1),
                 (2048, 131072, 0, M.SUPER_BYTES, 'other', 0),
                 (2048, 0, 0, M.SUPER_BYTES, 'super', 0))
        for device in cases:
            with self.subTest(device=device), self.assertRaises(M.Invalid):
                M.plan(fixture(device=device), 'current-slot: b')

    def test_partition_references_names_and_disabled_state(self):
        cases = ([('vendor_b', 8, 0, 2, 1)], [('vendor_b', 4, 0, 0, 1)],
                 [('vendor_b', 4, 99, 2, 1)], [('vendor_b', 4, 0, 2, 99)],
                 [('vendor/b', 4, 0, 2, 1)], [('other', 4, 0, 2, 1)],
                 [('vendor', 2, 0, 2, 1), ('vendor_b', 4, 2, 1, 1)])
        for partitions in cases:
            with self.subTest(partitions=partitions), self.assertRaises(M.Invalid):
                M.plan(fixture(partitions=partitions), 'current-slot: b')

    def test_extent_target_device_bounds_overlap_and_vendor_cap(self):
        for first in ((8192, 0, 2048, 1), (8192, 0, 1, 0),
                      (8192, 0, M.SUPER_BYTES//512, 0), (8192, 2, 2048, 0),
                      (M.MAX_VENDOR//512+8, 0, 2048, 0)):
            with self.subTest(first=first), self.assertRaises(M.Invalid):
                M.plan(fixture(extents=[first, (8, 0, 16384, 0), (8200, 0, 32768, 0)]), 'current-slot: b')
        with self.assertRaisesRegex(M.Invalid, 'overlapping'):
            M.plan(fixture(extents=[(8192, 0, 2048, 0), (8, 0, 2048, 0), (8200, 0, 32768, 0)]), 'current-slot: b')
        with self.assertRaisesRegex(M.Invalid, 'group limit'):
            M.plan(fixture(maximum_group=4096), 'current-slot: b')

    def test_zero_extents_are_host_fill_only_and_have_no_source_reads(self):
        result = M.plan(fixture(extents=[(8192, 0, 2048, 0), (8, 1, 0, 0), (8200, 0, 32768, 0)]), 'current-slot: b')
        self.assertEqual(result['capture_extents'][1], {'extent': 1, 'kind': 'zero',
                                                       'output_offset_bytes': 8192*512, 'bytes': 4096})
        with self.assertRaises(M.Invalid):
            M.plan(fixture(extents=[(8192, 0, 2048, 0), (8, 1, 1, 0), (8200, 0, 32768, 0)]), 'current-slot: b')

    def test_regular_file_bounds_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root/'prefix.raw'
            raw.write_bytes(fixture())
            self.assertEqual(M.read_regular(raw, M.MAX_PREFIX), raw.read_bytes())
            with self.assertRaises(M.Invalid):
                M.read_regular(raw, 1)
            link = root/'link'
            link.symlink_to(raw)
            with self.assertRaises(OSError):
                M.read_regular(link, M.MAX_PREFIX)


if __name__ == '__main__':
    unittest.main()
