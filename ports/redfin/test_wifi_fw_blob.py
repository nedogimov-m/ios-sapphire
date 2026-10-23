"""Pack verified firmware without changing common loaders or root filesystems."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings

import wifi_fw_blob as P
from test_fdt import Hardware, tree
from test_loader import mock_kernel
from test_wifi_firmware import EXCLUDED, bundle, fdt
from test_wifi_fw_source import private_bundle
from tools import mkpayload

HERE = Path(__file__).resolve().parent
ARGS = ('cpus=1 rd=md0 modem=0 wifi=0 gpu=0 sweetusb=0 redfinspmi=1 redfinreturn=1 '
        'redfinbootid=0x0000000000000001')


class WifiFirmwareImportTests(unittest.TestCase):
    def test_payload_tools_cannot_shadow_the_board_adt(self):
        script = '''
import sys
from pathlib import Path
board = Path(sys.argv[1])
sys.path[:0] = [str(board.parents[1] / 'tools'), str(board)]
import mkadt
assert Path(mkadt.__file__).parent.name == 'tools'
import wifi_fw_blob
assert Path(wifi_fw_blob.mkadt.__file__).resolve() == (board / 'mkadt.py').resolve()
tree = wifi_fw_blob.mkadt.build(0x180000000, 0x80000000, seed=bytes(64))
assert tree.prop('compatible')
'''
        result = subprocess.run([sys.executable, '-c', script, str(HERE)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class WifiFirmwareBlobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.verifier = cls.directory / 'source-check'
        command = [compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(HERE),
                   str(HERE / 'wifi-fw-source-check.c'), str(HERE / 'wifi_fw_source.c'), '-o', str(cls.verifier)]
        if sys.platform != 'darwin':
            command.append('-lcrypto')
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        (cls.directory / 'config.h').write_text('#define XNU_PAYLOAD_SIZE 65536\n')
        library = cls.directory / 'loader.so'
        subprocess.run([compiler, '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-DREDFIN_LOADER_TEST', '-I', str(cls.directory), str(HERE / 'loader.c'),
                        str(HERE / 'fdt.c'), '-o', str(library)], check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        cls.library.redfin_validate.argtypes = [C.c_void_p, C.c_uint64, C.c_uint64, C.c_uint64,
                                               C.c_uint64, C.POINTER(Hardware), C.c_uint64]
        cls.library.redfin_validate.restype = C.c_char_p
        cls.library.redfin_fdt.argtypes = [C.c_void_p, C.POINTER(Hardware)]
        kernel, adt, ramdisk = [cls.directory / name for name in ('kernel', 'device.adt', 'init')]
        kernel.write_bytes(mock_kernel())
        adt.write_bytes(P.mkadt.adt.serialize(P.mkadt.build(0x180000000, 0x80000000, seed=bytes(64))))
        ramdisk.write_bytes(b'private static PID1 placeholder')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            cls.payload, _info = mkpayload.build(kernel, adt, ARGS, ramdisk)
        cls.firmware = bundle()
        cls.digest = hashlib.sha256(cls.firmware).hexdigest()
        cls.bundle_file = cls.directory / 'firmware.bundle'; cls.bundle_file.write_bytes(cls.firmware)
        cls.report = P.verify_bundle(cls.verifier, cls.bundle_file, cls.digest, EXCLUDED)

    def accepted(self, payload):
        live_fdt = C.create_string_buffer(tree(banks=[(0x180000000, 0x80000000)]))
        hardware = Hardware()
        self.assertEqual(self.library.redfin_fdt(live_fdt, C.byref(hardware)), 0)
        storage = C.create_string_buffer(len(payload) + P.PAGE)
        source = (C.addressof(storage) + P.PAGE - 1) & -P.PAGE
        C.memmove(source, payload, len(payload))
        return self.library.redfin_validate(source, len(payload), source - P.PAGE, source + len(payload),
                                            C.addressof(live_fdt), C.byref(hardware), 0)

    def packed(self, cap=0x8000000):
        return P.pack(self.payload, self.firmware, self.digest, self.report, cap)

    def test_real_native_verifier_and_payload_loader_accept_one_additional_segment(self):
        self.assertEqual((self.report['phdrs'], self.report['segments'], self.report['assets']), (5, 3, 3))
        result, report = self.packed()
        self.assertIsNone(self.accepted(result))
        self.assertEqual(report['segments'], 4)
        self.assertFalse(report['rootfs_dependency'])
        self.assertFalse(report['abl_limits_proven'])
        before = P.payload_info(self.payload)
        count = struct.unpack_from('<I', result, 12)[0]
        pieces = [struct.unpack_from('<4Q', result, 680 + 32 * index) for index in range(count)]
        for old, new in zip(before['segments'], pieces):
            self.assertEqual(old[:2], new[:2])
            self.assertEqual(self.payload[old[2]:old[2] + old[3]], result[new[2]:new[2] + new[3]])
        self.assertEqual(result[72:680], self.payload[72:680])
        self.assertEqual(pieces[-1][:2], (before['end'], report['source_reserved']))
        self.assertEqual(result[pieces[-1][2]:pieces[-1][2] + pieces[-1][3]], self.firmware)
        offset, length, end = struct.unpack_from('<3Q', result, 32)
        root, consumed = P.mkadt.adt.parse(result[offset:offset + length])
        self.assertEqual(consumed, length)
        node = next(child for child in root.children if child.name == 'redfin-wifi-fw')
        self.assertEqual(node.prop('reg'), P.mkadt.u64(report['source_physical'], report['source_reserved']))
        self.assertEqual(node.prop('bundle-bytes'), P.mkadt.u64(len(self.firmware)))
        self.assertEqual(node.prop('bundle-sha256'), bytes.fromhex(self.digest))
        self.assertEqual(node.prop('source-contract'), P.mkadt.u32(*P.CONTRACT))
        self.assertEqual(report['adt_physical'], 0x180000000 + end - before['virt'])

    def test_native_report_hash_explicit_cap_and_original_profile_are_required(self):
        for digest, report, cap in [('0' * 64, self.report, 0x8000000),
                                    (self.digest, {}, 0x8000000), (self.digest, self.report, 1),
                                    (self.digest, self.report, P.MAX_PAYLOAD + 1)]:
            with self.subTest(digest=digest, cap=cap), self.assertRaises(ValueError):
                P.pack(self.payload, self.firmware, digest, report, cap)
        for command in (ARGS.replace('cpus=1', 'cpus=8'), ARGS + ' cpus=1', ARGS.replace('rd=md0', 'rd=ufsroot0'),
                        ARGS.replace('0000000000000001', '0000000000000000')):
            payload = bytearray(self.payload); payload[72:680] = command.encode().ljust(608, b'\0')
            with self.assertRaises(ValueError):
                P.pack(payload, self.firmware, self.digest, self.report, 0x8000000)

    def test_malformed_payload_header_segments_adt_and_duplicate_blob_are_rejected(self):
        for offset, format, value in [(0, 'B', 0), (12, 'I', 64), (56, 'Q', 0),
                                      (64, 'Q', 0x4000), (32, 'Q', len(self.payload)),
                                      (696, 'Q', 0), (712, 'Q', 0), (48, 'Q', 0)]:
            payload = bytearray(self.payload); struct.pack_into('<' + format, payload, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                P.pack(payload, self.firmware, self.digest, self.report, 0x8000000)
        packed, _report = self.packed()
        with self.assertRaises(ValueError):
            P.pack(packed, self.firmware, self.digest, self.report, 0x8000000)

    def test_host_checker_refuses_corrupt_hash_assets_symlinks_fifos_and_bad_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            link = directory / 'link'; link.symlink_to(self.bundle_file)
            fifo = directory / 'fifo'; os.mkfifo(fifo)
            broken = directory / 'broken'; data = bytearray(self.firmware); data[-16] ^= 1; broken.write_bytes(data)
            for path, digest, excluded in [(self.bundle_file, '0' * 64, EXCLUDED),
                                          (link, self.digest, EXCLUDED), (fifo, self.digest, EXCLUDED),
                                          (broken, hashlib.sha256(data).hexdigest(), EXCLUDED),
                                          (self.bundle_file, self.digest, EXCLUDED + ((0x8c000000, 4096),))]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    P.verify_bundle(self.verifier, path, digest, excluded)

    def test_publication_is_mode0600_no_overwrite_and_leaves_no_temporary_artifacts(self):
        payload, _report = self.packed()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory); output = directory / 'private.payload'
            P.publish(output, payload)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                P.publish(output, payload)
            link = directory / 'link'; link.symlink_to(output)
            with self.assertRaises(FileExistsError):
                P.publish(link, payload)
            self.assertEqual(sorted(path.name for path in directory.iterdir()), ['link', 'private.payload'])

    def test_cli_uses_live_fdt_and_native_adapter_and_produces_only_a_private_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            payload = directory / 'input.payload'; payload.write_bytes(self.payload)
            dtb = directory / 'device.dtb'; dtb.write_bytes(fdt())
            output = directory / 'result.payload'
            result = subprocess.run([sys.executable, str(HERE / 'wifi_fw_blob.py'), '--payload', str(payload),
                                     '--bundle', str(self.bundle_file), '--bundle-sha256', self.digest,
                                     '--verifier', str(self.verifier), '--dtb', str(dtb),
                                     '--max-payload-bytes', '0x8000000', '--output', str(output)],
                                    capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report['payload_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertFalse(report['hardware_started'])
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertIsNone(self.accepted(output.read_bytes()))

    @unittest.skipUnless(os.environ.get('REDFIN_WIFI_PRIVATE_BUNDLE'), 'private bundle not requested')
    def test_private_bundle_and_actual_kernel_payload_pass_full_native_loader(self):
        source = Path(os.environ['REDFIN_WIFI_PRIVATE_BUNDLE'])
        payload_path = Path(os.environ.get('REDFIN_WIFI_PRIVATE_PAYLOAD', 'ports/redfin/out/wifi-native-v1/payload.bin'))
        dtb_path = Path(os.environ.get('REDFIN_WIFI_PRIVATE_DTB', 'research/redfin-root/device.dtb'))
        firmware, selected = private_bundle(); digest = selected['bundle_sha256']
        report = P.verify_bundle(self.verifier, source, digest, P.live_layout(dtb_path.read_bytes(), 0x180000000, 0x80000000))
        result, packed = P.pack(payload_path.read_bytes(), firmware, digest, report, 0x8000000)
        self.assertIsNone(self.accepted(result))
        self.assertEqual(packed['segments'], 12)
        self.assertEqual(packed['bundle_bytes'], 99395632)
        self.assertEqual(packed['source_reserved'], 99401728)
        self.assertLess(packed['payload_bytes'], 0x8000000)


if __name__ == '__main__':
    unittest.main()
