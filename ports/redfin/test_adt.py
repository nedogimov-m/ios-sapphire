"""Check the redfin ADT's hardware contract and rejection of invalid RAM ranges."""
import importlib.util
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('redfin_mkadt', Path(__file__).with_name('mkadt.py'))
mkadt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mkadt)


def child(root, name):
    return next(item for item in root.children if item.name == name)


class RedfinADTTests(unittest.TestCase):
    # Synthetic addresses for serialization tests, not a device RAM recommendation.
    BASE, SIZE = 0x200000000, 0x40000000

    def test_apple_userspace_identity_cannot_import_hardware_or_identifiers(self):
        source = mkadt.node('device-tree', [
            ('model', mkadt.cstr('iPhone10,3')), ('target-sub-type', mkadt.cstr('D22AP')),
            ('serial-number', b'source-private-identifier\0')], [
                mkadt.node('product', [('artwork-display-gamut', b'P3\0'), ('device-class', b'iPhone\0')]),
                mkadt.node('arm-io', [('reg', bytes(32))])])
        source.children[0].props.append(('serial-placeholder', 1, b'placeholder'))
        root = mkadt.build(self.BASE, self.SIZE, seed=bytes(64))
        original_hardware = {name: mkadt.adt.serialize(child(root, name)) for name in ('cpus', 'arm-io')}
        mkadt.apple_userspace_identity(root, mkadt.adt.serialize(source))
        self.assertEqual(root.prop('model'), b'iPhone10,3\0')
        self.assertIn(b'google,redfin\0', root.prop('compatible'))
        for name, expected in original_hardware.items():
            self.assertEqual(mkadt.adt.serialize(child(root, name)), expected)
        chosen = child(root, 'chosen')
        self.assertEqual(child(root, 'defaults').prop('no-effaceable-storage'), mkadt.u32(1))
        self.assertEqual(chosen.prop('dram-base'), mkadt.u64(self.BASE))
        self.assertEqual(chosen.prop('dram-size'), mkadt.u64(self.SIZE))
        self.assertEqual(child(root, 'product').prop('artwork-display-gamut'), b'sRGB\0')
        self.assertIsNone(child(root, 'product').prop('serial-placeholder'))
        self.assertNotIn(b'source-private-identifier', mkadt.adt.serialize(root))
        self.assertEqual(child(chosen, 'asmb').prop('lp-sip0'), mkadt.u64(0x6f))
        self.assertEqual(len(chosen.prop('boot-manifest-hash')), 48)
        with self.assertRaises(ValueError):
            mkadt.apple_userspace_identity(root, mkadt.adt.serialize(source))
        source.props = [(key, flag, b'wrong\0' if key == 'model' else value)
                        for key, flag, value in source.props]
        with self.assertRaises(ValueError):
            mkadt.apple_userspace_identity(mkadt.build(self.BASE, self.SIZE), mkadt.adt.serialize(source))

    def test_serialized_hardware_contract(self):
        blob = mkadt.adt.serialize(mkadt.build(self.BASE, self.SIZE, 0x700, bytes(64)))
        root, end = mkadt.adt.parse(blob)
        self.assertEqual(end, len(blob))
        self.assertEqual(child(root, 'defaults').prop('no-effaceable-storage'), mkadt.u32(1))
        self.assertEqual({item.name for item in root.children}, {'chosen', 'defaults', 'cpus', 'arm-io'})
        chosen = child(root, 'chosen')
        self.assertEqual(struct.unpack('<Q', chosen.prop('dram-base'))[0], self.BASE)
        self.assertEqual(struct.unpack('<Q', chosen.prop('dram-size'))[0], self.SIZE)
        self.assertEqual(chosen.prop('random-seed'), bytes(64))
        self.assertEqual([item.name for item in chosen.children], ['memory-map'])
        cpus = child(root, 'cpus')
        self.assertEqual(len(cpus.children), 1)
        self.assertEqual(struct.unpack('<I', cpus.children[0].prop('reg'))[0], 0x700)
        self.assertEqual(struct.unpack('<I', cpus.children[0].prop('timebase-frequency'))[0], 19200000)
        arm_io = child(root, 'arm-io')
        self.assertEqual([item.name for item in arm_io.children], ['gic'])
        gic = child(arm_io, 'gic')
        self.assertEqual(struct.unpack('<4Q', gic.prop('reg')), (0x16A00000, 0x10000, 0x16A60000, 0x100000))
        self.assertEqual(struct.unpack('<I', gic.prop('virtual-timer-intid'))[0], 19)
        self.assertIn(b'google,redfin\0', root.prop('compatible'))
        self.assertIn(b'xiaomi,sweet\0', root.prop('compatible'))

    def test_ramdisk_payload_integration(self):
        from tools import mkpayload
        root = mkadt.build(self.BASE, self.SIZE, seed=bytes(64))
        blob = mkadt.adt.serialize(root)
        self.assertEqual(mkpayload.adt_dram(blob), (self.BASE, self.SIZE))
        root, _ = mkadt.adt.parse(mkpayload.add_ramdisk_to_adt(blob, self.BASE + 0x4000, 0x8000))
        ramdisk = child(child(root, 'chosen'), 'memory-map').prop('RAMDisk')
        self.assertEqual(struct.unpack('<2Q', ramdisk), (self.BASE + 0x4000, 0x8000))

    def test_explicit_display_contract_is_absolute_and_serializable(self):
        root = mkadt.build(self.BASE, self.SIZE, seed=bytes(64))
        original_gic = mkadt.adt.serialize(child(child(root, 'arm-io'), 'gic'))
        mkadt.add_linear_display(root, 0xa0000000, 0x02300000, 0xa0000000)
        blob = mkadt.adt.serialize(root)
        root, end = mkadt.adt.parse(blob)
        self.assertEqual(end, len(blob))
        display = child(child(root, 'arm-io'), 'disp0')
        self.assertEqual(display.prop('device_type'), b'display-subsystem\0')
        self.assertEqual(display.prop('compatible'), b'sweet,display\0')
        self.assertEqual(display.prop('redfin,abl-copy-only'), mkadt.u32(1))
        self.assertEqual(display.prop('redfin,framebuffer'), mkadt.u64(0xa0000000, 0x02300000))
        self.assertIsNone(display.prop('reg'))
        self.assertEqual(display.prop('pixel-format'), b'BGRA\0')
        for key, expected in (('width', 1080), ('height', 2340), ('stride', 4320),
                              ('canvas-width', 1125), ('canvas-height', 2436)):
            self.assertEqual(display.prop(key), mkadt.u32(expected))
        self.assertEqual(mkadt.adt.serialize(child(child(root, 'arm-io'), 'gic')), original_gic)
        with self.assertRaises(ValueError):
            mkadt.add_linear_display(root, 0xa0000000, 0x02300000, 0xa0000000)

    def test_display_rejects_unobserved_geometry_before_mutating_tree(self):
        good = [0xa0000000, 0x02300000, 0xa0000000, 1080, 2340, 4320]
        for index in range(len(good)):
            for bad in (-1, 0, True, good[index] + 1, 1 << 64):
                values = good.copy()
                values[index] = bad
                root = mkadt.build(self.BASE, self.SIZE, seed=bytes(64))
                before = mkadt.adt.serialize(root)
                with self.subTest(index=index, bad=bad), self.assertRaises(ValueError):
                    mkadt.add_linear_display(root, *values)
                self.assertEqual(mkadt.adt.serialize(root), before)

    def test_display_driver_guard_accepts_serialized_contract_only(self):
        compiler = shutil.which('cc')
        if compiler is None:
            self.skipTest('host compiler unavailable')
        patch = Path(__file__).with_name('display.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        guard = added.split('/* REDFIN_FB_TEST_BEGIN:', 1)[1].split('/* REDFIN_FB_TEST_END */', 1)[0]
        guard = guard.split('*/', 1)[1]
        root = mkadt.add_linear_display(mkadt.build(self.BASE, self.SIZE, seed=bytes(64)),
                                       0xa0000000, 0x02300000, 0xa0000000)
        root, _ = mkadt.adt.parse(mkadt.adt.serialize(root))
        display = child(child(root, 'arm-io'), 'disp0')
        values = list(struct.unpack('<2Q', display.prop('redfin,framebuffer')))
        values += [int.from_bytes(display.prop(key), 'little') for key in
                   ('width', 'height', 'stride', 'canvas-width', 'canvas-height')]
        source = '#include <stdint.h>\n#include <stdbool.h>\n#include <stdlib.h>\n' + guard
        source += '''\nint main(int argc, char **argv) {
    if (argc != 8) return 2;
    return !redfin_fb_geometry(strtoull(argv[1], 0, 0), strtoull(argv[2], 0, 0),
        (uint32_t)strtoull(argv[3], 0, 0), (uint32_t)strtoull(argv[4], 0, 0),
        (uint32_t)strtoull(argv[5], 0, 0), (uint32_t)strtoull(argv[6], 0, 0),
        (uint32_t)strtoull(argv[7], 0, 0));
}\n'''
        with tempfile.TemporaryDirectory() as temporary:
            path, executable = Path(temporary) / 'guard.c', Path(temporary) / 'guard'
            path.write_text(source)
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=undefined', str(path), '-o', str(executable)], check=True)
            self.assertEqual(subprocess.run([str(executable), *map(str, values)]).returncode, 0)
            for index in range(len(values)):
                for bad in (0, values[index] + 1):
                    invalid = values.copy()
                    invalid[index] = bad
                    self.assertEqual(subprocess.run([str(executable), *map(str, invalid)]).returncode, 1)

    def test_reject_invalid_ranges_and_topology(self):
        invalid = [(0, self.SIZE), (self.BASE, 0), (-0x4000, self.SIZE),
                   (self.BASE + 1, self.SIZE), (self.BASE, self.SIZE + 1),
                   (1 << 36, 0x4000), ((1 << 36) - 0x4000, 0x8000),
                   (1 << 64, 1 << 64)]
        for base, size in invalid:
            with self.subTest(base=base, size=size), self.assertRaises(ValueError):
                mkadt.build(base, size)
        mkadt.build((1 << 36) - 0x4000, 0x4000)
        for mpidr in range(0, 0x800, 0x100):
            mkadt.build(self.BASE, self.SIZE, mpidr)
        for mpidr in (-1, 1, 0x103, 0x800, True):
            with self.subTest(mpidr=mpidr), self.assertRaises(ValueError):
                mkadt.build(self.BASE, self.SIZE, mpidr)

    def test_cli_requires_explicit_memory_and_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'redfin.adt'
            for args in ([], ['--memory-base', '0x4001', '--memory-size', '0x4000']):
                result = subprocess.run([sys.executable, str(Path(mkadt.__file__)), str(output), *args],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
