"""Private serial provisioning must not import hardware or leak its value."""
import copy
import ctypes
import json
from pathlib import Path
import tempfile
import unittest

from ports.redfin import device_identity, mkadt
from test_smp_gui import compile_shared, patched_source

HERE = Path(__file__).resolve().parent
FIXTURE = dict(format_version=1, product='redfin', serial_number='TEST-DEVICE-01', source='synthetic test fixture')


class DeviceIdentityTests(unittest.TestCase):
    def test_private_serial_is_explicit_mirrored_and_leaves_every_hardware_node_intact(self):
        source = mkadt.node('device-tree', [('model', b'iPhone10,3\0'), ('target-sub-type', b'D22AP\0'),
                           ('serial-number', b'not-this-device\0')],
                           [mkadt.node('product', [('device-class', b'iPhone\0')])])
        root = mkadt.build(0x200000000, 0x40000000, seed=bytes(64))
        hardware = {c.name: mkadt.adt.serialize(c) for c in root.children if c.name in ('cpus', 'arm-io')}
        mkadt.apple_userspace_identity(root, mkadt.adt.serialize(source), FIXTURE)
        chosen = next(c for c in root.children if c.name == 'chosen')
        self.assertEqual(root.prop('serial-number'), b'TEST-DEVICE-01\0')
        self.assertEqual(chosen.prop('serial-number'), root.prop('serial-number'))
        self.assertEqual(chosen.prop('redfin-identity-version'), mkadt.u32(1))
        self.assertNotIn(b'not-this-device', mkadt.adt.serialize(root))
        for child in root.children:
            if child.name in hardware:
                self.assertEqual(mkadt.adt.serialize(child), hardware[child.name])

    def test_invalid_or_conflicting_identity_never_partially_changes_the_tree(self):
        for value in ('', 'bad value', 'bad/path', 'x\0y', 'x' * 65, 'не-серийник'):
            with self.assertRaises(ValueError):
                device_identity.validate(dict(FIXTURE, serial_number=value))
        for update in ({'format_version': True}, {'product': 'another-device'}, {'chip-id': 1}):
            with self.assertRaises(ValueError):
                device_identity.validate(dict(FIXTURE, **update))
        root = mkadt.build(0x200000000, 0x40000000, seed=bytes(64))
        next(c for c in root.children if c.name == 'chosen').props.append(('serial-number', 0, b'existing\0'))
        before = mkadt.adt.serialize(root)
        with self.assertRaises(ValueError):
            device_identity.apply(root, FIXTURE)
        self.assertEqual(mkadt.adt.serialize(root), before)

    def test_manifest_contains_only_provenance_and_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private.json'
            path.write_text(json.dumps(FIXTURE))
            value = device_identity.load(path)
            self.assertEqual(value, FIXTURE)
            report = device_identity.report(path, value)
            self.assertNotIn(FIXTURE['serial_number'], json.dumps(report))
            self.assertTrue(report['physical_redfin_serial'])
            self.assertFalse(report['apple_activation_identity'])

    def test_native_serial_parser_rejects_unterminated_embedded_nul_and_invalid_bytes(self):
        self.assertEqual(patched_source('iokit/Kernel/arm/RedfinDeviceIdentity.h'),
                         (HERE / 'device-identity.h').read_text())
        with tempfile.TemporaryDirectory() as directory:
            lib = compile_shared(Path(directory), '#include "device-identity.h"\n'
                                 'int accepted(const void *p,unsigned n){return redfin_device_serial(p,n);}\n', 'identity')
            lib.accepted.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            valid = b'TEST-DEVICE-01\0'
            self.assertEqual(lib.accepted(valid, len(valid)), 1)
            for value in (b'', b'short\0', valid[:-1], b'TEST\0DEVICE\0', b'TEST/DEVICE\0', b'X' * 65 + b'\0'):
                self.assertEqual(lib.accepted(value, len(value)), 0)
            self.assertEqual(lib.accepted(None, len(valid)), 0)


if __name__ == '__main__':
    unittest.main()
