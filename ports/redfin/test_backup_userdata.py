"""Full-backup validation and streaming tests; no physical ADB calls."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from test_install_root import evidence
from test_gpt import repair

SPEC = importlib.util.spec_from_file_location('redfin_backup', Path(__file__).with_name('backup-userdata.py'))
BACKUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKUP)


def fixture():
    primary, unused, state = evidence()
    primary = bytearray(primary)
    entry = 8192 + 14*128
    primary[entry] = 1
    struct.pack_into('<QQ', primary, entry+32, 16, 31)
    primary[entry+56:entry+72] = 'metadata'.encode('utf-16le')
    repair(primary)
    tail = bytearray(BACKUP.INSTALL.PREFIX_BLOCKS*4096)
    header = bytearray(primary[4096:4096+92])
    current, alternate = struct.unpack_from('<QQ', header, 24)
    struct.pack_into('<QQ', header, 24, alternate, current)
    struct.pack_into('<I', header, 16, 0)
    struct.pack_into('<I', header, 16, zlib.crc32(header))
    tail[-4096:-4096+92] = header
    state.update(timer='stopped', return_target='bootloader', metadata_resolved=BACKUP.METADATA,
                 metadata_block_node='1', metadata_start_sectors=str(16*8), metadata_size_sectors=str(16*8),
                 metadata_holders='', metadata_readonly='0')
    return bytes(primary), bytes(tail), state


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.primary, self.tail, self.state = fixture()
        unused, self.target = BACKUP.INSTALL.partition(self.primary)
        self.metadata = BACKUP.metadata_partition(self.primary)

    def test_valid_state_and_readonly_nodes_are_accepted(self):
        for readonly in ('0', '1'):
            BACKUP.validate_state({**self.state, 'readonly': readonly, 'metadata_readonly': readonly},
                                  self.target, self.metadata, self.primary)

    def test_identity_timer_mounts_and_metadata_geometry_are_required(self):
        changes = {'marker': '0', 'uid': '2000', 'timer': 'running', 'return_target': 'android',
                   'metadata_resolved': '/dev/block/sda14', 'metadata_block_node': '0',
                   'metadata_start_sectors': '0', 'metadata_size_sectors': '0',
                   'metadata_holders': 'dm-0', 'dm': 'dm-0', 'holders': 'dm-0',
                   'mountinfo': '1 0 8:15 / /metadata rw - ext4 /dev/block/sda15 rw\n'}
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                BACKUP.validate_state({**self.state, key: value}, self.target, self.metadata, self.primary)

    def test_exact_bounded_read_and_hash_never_write_or_round_size(self):
        size = 117155278848
        for hashed in (False, True):
            script = BACKUP.bounded_read_script(BACKUP.INSTALL.RAW, size, hashed)
            self.assertIn('count=117155278848 iflag=count_bytes status=none', script)
            for forbidden in ('of=', 'discard', 'reboot', 'setprop'):
                self.assertNotIn(forbidden, script)
        self.assertIn('set -o pipefail', BACKUP.bounded_read_script(BACKUP.METADATA, 17, True))

    def test_stream_uses_binary_shell_stdin_exact_length_private_file_and_returncode(self):
        real_popen = subprocess.Popen
        for output, code, expected_success in ((b'\x00\xff\r\nabc', 0, True), (b'ab', 0, False),
                                                (b'abcdefgh', 0, False), (b'\x00\xff\r\nabc', 7, False)):
            with self.subTest(output=output, code=code), tempfile.TemporaryDirectory() as directory:
                adb = BACKUP.ADB.__new__(BACKUP.ADB)
                adb.serial = 'private-serial'
                destination = Path(directory) / 'image.partial'
                calls = []
                def launch(command, **kwargs):
                    calls.append(command)
                    child = ('import sys; sys.stdin.buffer.read(); '
                             f'sys.stdout.buffer.write({output!r}); sys.exit({code})')
                    return real_popen([sys.executable, '-c', child], **kwargs)
                with mock.patch.object(BACKUP.subprocess, 'Popen', side_effect=launch), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if expected_success:
                        result = adb.stream(BACKUP.METADATA, 7, destination, 'metadata')
                        self.assertEqual(result['stream_sha256'], hashlib.sha256(output).hexdigest())
                        self.assertEqual(destination.read_bytes(), output)
                    else:
                        with self.assertRaises(ValueError):
                            adb.stream(BACKUP.METADATA, 7, destination, 'metadata')
                self.assertEqual(calls, [['adb', '-s', adb.serial, 'shell', '-T', 'sh', '-s']])
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_device_hash_is_independent_and_bounded(self):
        adb = BACKUP.ADB.__new__(BACKUP.ADB)
        with mock.patch.object(adb, 'command', return_value=b'a'*64+b'  -\n') as command:
            self.assertEqual(adb.device_hash(BACKUP.METADATA, 17), 'a'*64)
        self.assertEqual(command.call_args.kwargs['timeout'], 7200)
        self.assertIn('count=17 iflag=count_bytes', command.call_args.args[0])
        with mock.patch.object(adb, 'command', return_value=b'short'), self.assertRaises(ValueError):
            adb.device_hash(BACKUP.METADATA, 17)

    def run_main(self, directory, failure=None):
        out = directory / 'backup'
        expected = directory / 'expected.bin'
        expected.write_bytes(self.primary)
        target = {**self.target, 'bytes': 17}
        metadata = {**self.metadata, 'bytes': 7}
        events = []
        class FakeADB:
            serial = 'private-serial'
            def stream(inner, node, size, path, label):
                events.append(('stream', label, size))
                data = bytes([size])*size
                BACKUP.private_write(path, data)
                if failure == 'stream' and label == 'userdata':
                    raise ValueError('read failed private-serial')
                return {'bytes': size, 'stream_sha256': hashlib.sha256(data).hexdigest(), 'seconds': 0.1}
            def device_hash(inner, node, size):
                events.append(('hash', node, size))
                return '0'*64 if failure == 'hash' else hashlib.sha256(bytes([size])*size).hexdigest()
        snapshots = 0
        def snapshot(*unused):
            nonlocal snapshots
            snapshots += 1
            if failure == 'state' and snapshots > 2:
                raise ValueError('unsafe new mount')
            return self.state, self.primary, self.tail, {'capture_sha256': hashlib.sha256(self.tail).hexdigest()}
        with mock.patch.object(BACKUP, 'ADB', return_value=FakeADB()), \
                mock.patch.object(BACKUP.INSTALL, 'partition', return_value=({}, target)), \
                mock.patch.object(BACKUP, 'metadata_partition', return_value=metadata), \
                mock.patch.object(BACKUP, 'snapshot', side_effect=snapshot), \
                mock.patch.object(BACKUP.subprocess, 'run', side_effect=AssertionError('physical calls forbidden')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = BACKUP.main(['--expected-gpt', str(expected), '--out', str(out)])
        return code, out, json.loads((out / 'backup.json').read_text()), events

    def test_complete_backup_requires_both_hashes_and_state_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            code, out, report, events = self.run_main(Path(directory))
            self.assertEqual(code, 0)
            self.assertTrue(report['success'])
            self.assertEqual(out.stat().st_mode & 0o777, 0o700)
            for name in ('userdata', 'metadata'):
                self.assertEqual(report['images'][name]['status'], 'verified')
                self.assertEqual((out/(name+'.img')).stat().st_mode & 0o777, 0o600)
            self.assertEqual(len([item for item in events if item[0] == 'hash']), 2)
            self.assertNotIn('private-serial', (out/'backup.json').read_text())
            for path in out.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failures_preserve_partial_and_cannot_report_success(self):
        for failure in ('stream', 'hash', 'state'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                code, out, report, events = self.run_main(Path(directory), failure)
                self.assertEqual(code, 1)
                self.assertFalse(report['success'])
                self.assertTrue(list(out.glob('*.partial')))
                self.assertNotIn('private-serial', (out/'backup.json').read_text())

    def test_existing_backup_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'backup'
            out.mkdir()
            (out/'backup.json').write_text('original')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(BACKUP.main(['--expected-gpt', 'unused', '--out', str(out)]), 1)
            self.assertEqual((out/'backup.json').read_text(), 'original')

    def test_insufficient_space_prevents_adb_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root/'expected.bin'
            expected.write_bytes(self.primary)
            with mock.patch.object(BACKUP.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 0})()), \
                    mock.patch.object(BACKUP, 'ADB') as adb, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(BACKUP.main(['--expected-gpt', str(expected), '--out', str(root/'out')]), 1)
            adb.assert_not_called()
