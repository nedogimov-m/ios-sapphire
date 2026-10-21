"""Installer safety checks run exclusively on host fixtures and fake ADB."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from test_gpt import fixture, repair

SPEC = importlib.util.spec_from_file_location('redfin_installer', Path(__file__).with_name('install-root.py'))
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


def evidence():
    data = fixture()
    data.extend(bytes(INSTALL.PREFIX_BLOCKS*4096-len(data)))
    data[8192:8192+19*128] = bytes(19*128)
    index = 8192+18*128
    data[index] = 1
    blocks, begin, end = 8388608, 1024, 8388602
    struct.pack_into('<QQ', data, index+32, begin, end)
    data[index+56:index+72] = 'userdata'.encode('utf-16le')
    struct.pack_into('<4Q', data, 4096+24, 1, blocks-1, 16, end)
    repair(data)
    tail = bytearray(INSTALL.PREFIX_BLOCKS*4096)
    header = bytearray(data[4096:4096+92])
    struct.pack_into('<QQ', header, 24, blocks-1, 1)
    struct.pack_into('<Q', header, 72, blocks-2)
    struct.pack_into('<I', header, 16, 0)
    struct.pack_into('<I', header, 16, zlib.crc32(header))
    tail[-4096:-4096+92] = header
    tail[-8192:-8192+19*128] = data[8192:8192+19*128]
    state = {'uid': '0', 'marker': '1', 'product': 'redfin', 'resolved': INSTALL.RAW,
             'block_node': '1', 'logical_block_size': '4096', 'readonly': '0',
             'start_sectors': str(begin*8), 'size_sectors': str((end-begin+1)*8),
             'disk_sectors': str(blocks*8), 'holders': '', 'dm': '', 'timer': 'running', 'uptime': '10.0 9.0',
             'mountinfo': '1 0 0:1 / / rw - rootfs rootfs rw\n2 1 0:2 / /proc rw - proc proc rw\n',
             'swaps': 'Filename\tType\tSize\tUsed\tPriority\n'}
    return bytes(data), bytes(tail), state


def manifest(image):
    return {'success': True, 'stage': 'root-prepared', 'blocked': [],
            'image': {'path': str(image), 'bytes': INSTALL.IMAGE_BYTES, 'sha256': 'a'*64},
            'commands': [['/sbin/fsck_hfs', '-fn', '/dev/rdisk9']],
            'critical_content_checks': [{'path': name, 'matches_decompressed_source': True}
                for name in ('sbin/launchd', 'usr/lib/dyld',
                             'System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64')]}


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.primary, self.backup, self.state = evidence()
        self.proof, self.target = INSTALL.partition(self.primary)

    def test_valid_offline_recovery_and_both_crc_valid_gpts(self):
        INSTALL.validate_state(self.state, self.target, self.primary)
        self.assertEqual(len(INSTALL.backup_fingerprint(self.primary, self.backup)), 64)

    def test_secondary_arrays_allow_reserved_padding_without_assuming_adjacency(self):
        current, unused, first, last = struct.unpack_from('<4Q', self.backup, len(self.backup)-4096+24)
        length = 19*128
        array = self.primary[8192:8192+length]
        for location in range(last+1, current):
            tail = bytearray(len(self.backup))
            tail[-4096:] = self.backup[-4096:]
            offset = (location-(current+1-INSTALL.PREFIX_BLOCKS))*4096
            tail[offset:offset+length] = array
            struct.pack_into('<Q', tail, len(tail)-4096+72, location)
            struct.pack_into('<I', tail, len(tail)-4096+16, 0)
            struct.pack_into('<I', tail, len(tail)-4096+16, zlib.crc32(tail[-4096:-4096+92]))
            proof = INSTALL.backup_proof(self.primary, bytes(tail))
            self.assertEqual(proof['entries_reference'], 'secondary-array')
            self.assertTrue(proof['independent_array_verified'])
            self.assertEqual(proof['physical_array_lba'], location)

    def test_vendor_secondary_header_can_reference_primary_without_claiming_independent_copy(self):
        tail = bytearray(len(self.backup))
        tail[-4096:] = self.backup[-4096:]
        struct.pack_into('<Q', tail, len(tail)-4096+72, 2)
        struct.pack_into('<I', tail, len(tail)-4096+16, 0)
        struct.pack_into('<I', tail, len(tail)-4096+16, zlib.crc32(tail[-4096:-4096+92]))
        proof = INSTALL.backup_proof(self.primary, bytes(tail))
        self.assertEqual(proof['entries_reference'], 'primary-array')
        self.assertFalse(proof['independent_array_verified'])
        self.assertIsNone(proof['physical_array_lba'])
        self.assertEqual(proof['capture_sha256'], hashlib.sha256(tail).hexdigest())
        # Reserved padding participates in preservation even when it is not a GPT array.
        changed = bytearray(tail); changed[0] ^= 1
        self.assertNotEqual(INSTALL.backup_fingerprint(self.primary, bytes(tail)),
                            INSTALL.backup_fingerprint(self.primary, bytes(changed)))
        for location in (0, 1, struct.unpack_from('<Q', self.primary, 4096+48)[0]):
            bad = bytearray(tail)
            struct.pack_into('<Q', bad, len(bad)-4096+72, location)
            struct.pack_into('<I', bad, len(bad)-4096+16, 0)
            struct.pack_into('<I', bad, len(bad)-4096+16, zlib.crc32(bad[-4096:-4096+92]))
            with self.assertRaises(ValueError):
                INSTALL.backup_proof(self.primary, bytes(bad))

    def test_normal_android_mounts_swap_dm_holders_and_geometry_are_rejected(self):
        changes = {'uid': ['2000'], 'marker': ['', '0'], 'product': ['other'],
                   'resolved': ['/dev/block/sda', '/dev/block/sda18', '/data/root.img'],
                   'block_node': ['0'], 'logical_block_size': ['512'], 'readonly': ['1'],
                   'start_sectors': ['0'], 'size_sectors': ['0'], 'disk_sectors': ['0'],
                   'holders': ['dm-0'], 'dm': ['dm-0'],
                   'swaps': [self.state['swaps']+'/dev/zram0 partition 100 0 -2\n']}
        for key, values in changes.items():
            for value in values:
                state = {**self.state, key: value}
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    INSTALL.validate_state(state, self.target, self.primary)
        for filesystem, mount in [('ext4', '/system'), ('f2fs', '/data'), ('erofs', '/vendor'),
                                  ('vfat', '/firmware'), ('tmpfs', '/data'), ('tmpfs', '/metadata'),
                                  ('tmpfs', '/metadata/child'), ('tmpfs', '/d\\141ta')]:
            state = {**self.state, 'mountinfo': f'1 0 0:1 / {mount} rw - {filesystem} source rw\n'}
            with self.subTest(filesystem=filesystem, mount=mount), self.assertRaises(ValueError):
                INSTALL.validate_state(state, self.target, self.primary)

    def test_corrupt_primary_backup_or_wrong_userdata_entry_are_rejected(self):
        for position in (4096+32, 8192+18*128+40):
            data = bytearray(self.primary); data[position] ^= 1
            with self.assertRaises(ValueError):
                INSTALL.partition(bytes(data))
        for position in (-4096+32, -8192+40):
            data = bytearray(self.backup); data[position] ^= 1
            with self.assertRaises(ValueError):
                INSTALL.backup_fingerprint(self.primary, bytes(data))
        data = bytearray(self.primary)
        data[8192+18*128+56:8192+18*128+72] = bytes(16)
        repair(data)
        with self.assertRaises(ValueError):
            INSTALL.partition(bytes(data))

    def test_hfsx_requires_clean_journaled_exact_16_gib_and_both_headers(self):
        header = bytearray(512)
        header[:4] = b'HX\x00\x05'
        attributes = (1 << 8) | (1 << 13)
        struct.pack_into('>I', header, 4, attributes)
        struct.pack_into('>II', header, 40, 4096, INSTALL.IMAGE_BYTES//4096)
        self.assertTrue(INSTALL.hfs_header(header, header, INSTALL.IMAGE_BYTES)['clean'])
        for flags in (0, 1 << 8, 1 << 13, attributes | (1 << 11)):
            bad = bytearray(header); struct.pack_into('>I', bad, 4, flags)
            with self.assertRaises(ValueError):
                INSTALL.hfs_header(bad, header, INSTALL.IMAGE_BYTES)
        stale_alternate = bytearray(header)
        struct.pack_into('>I', stale_alternate, 4, 1 << 13)
        self.assertTrue(INSTALL.hfs_header(header, stale_alternate, INSTALL.IMAGE_BYTES)['clean'])
        struct.pack_into('>I', stale_alternate, 4, attributes | (1 << 11))
        with self.assertRaises(ValueError):
            INSTALL.hfs_header(header, stale_alternate, INSTALL.IMAGE_BYTES)
        for length in (0, INSTALL.IMAGE_BYTES-4096, INSTALL.IMAGE_BYTES+512):
            with self.assertRaises(ValueError):
                INSTALL.hfs_header(header, header, length)

    def test_successful_build_and_critical_content_proof_are_mandatory(self):
        image = Path('/tmp/root.img')
        record = manifest(image)
        self.assertEqual(INSTALL.build_record(record, image), 'a'*64)
        for key, value in (('success', False), ('stage', 'incomplete'), ('blocked', ['x']),
                           ('detach_errors', ['x']), ('critical_content_checks', []), ('commands', [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                INSTALL.build_record({**record, key: value}, image)

    def test_explicit_fsck_log_proof_accepts_success_without_command_format_coupling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image, build, log = root/'root.img', root/'build.json', root/'metadata.log'
            data = (b"Can't open initial raw node: Permission denied\n"
                    b'Executing fsck_hfs (version hfs-751).\n'
                    b'** Checking Journaled HFS Plus volume.\n'
                    b'** Detected a case-sensitive volume.\n'
                    b'** The volume iOSRoot appears to be OK.\n')
            log.write_bytes(data)
            record = manifest(image)
            record['commands'] = []
            record['fsck'] = {'success': True, 'log': 'metadata.log',
                              'sha256': hashlib.sha256(data).hexdigest()}
            self.assertEqual(INSTALL.build_record(record, image, build), 'a'*64)
            for value in ({**record['fsck'], 'success': False},
                          {**record['fsck'], 'sha256': '0'*64},
                          {**record['fsck'], 'log': '../metadata.log'},
                          {**record['fsck'], 'log': str(log)}):
                with self.subTest(proof=value), self.assertRaises(ValueError):
                    INSTALL.build_record({**record, 'fsck': value}, image, build)
            (root/'link.log').symlink_to(log)
            with self.assertRaises(ValueError):
                INSTALL.build_record({**record, 'fsck': {**record['fsck'], 'log': 'link.log'}}, image, build)
            (root/'linked').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                INSTALL.build_record({**record, 'fsck': {**record['fsck'], 'log': 'linked/metadata.log'}}, image, build)
            for replacement in (data.replace(b'appears to be OK.', b'could not be verified.'),
                                data + b'Executing fsck_hfs\nfailed\n',
                                data + b'FILE SYSTEM WAS MODIFIED\n'):
                log.write_bytes(replacement)
                proof = {**record['fsck'], 'sha256': hashlib.sha256(replacement).hexdigest()}
                with self.assertRaises(ValueError):
                    INSTALL.build_record({**record, 'fsck': proof}, image, build)

    def run_fixture(self, root, erase=False, fake=None):
        primary, tail, state = root/'primary.bin', root/'backup.bin', root/'state.json'
        primary.write_bytes(self.primary); tail.write_bytes(self.backup)
        state.write_text(json.dumps({'state': self.state, 'primary_path': str(primary), 'backup_path': str(tail)}))
        args = ['--image', str(root/'image.img'), '--build-manifest', str(root/'build.json'),
                '--expected-gpt', str(primary), '--out', str(root/'result')]
        if erase:
            args += ['--erase-userdata']
        else:
            args += ['--state-json', str(state)]
        image = {'path': str(root/'image.img'), 'bytes': INSTALL.IMAGE_BYTES, 'sha256': 'a'*64, 'stat': [1, 2, 3, 4]}
        with patch.object(INSTALL, 'local_image', return_value=image), \
             patch.object(INSTALL, 'ADB', return_value=fake) as constructor, \
             patch.object(INSTALL.subprocess, 'run', side_effect=AssertionError('physical commands forbidden')), \
             contextlib.redirect_stdout(io.StringIO()):
            code = INSTALL.main(args)
        return code, json.loads((root/'result/check.json').read_text()), constructor

    def test_default_offline_check_produces_concrete_plan_without_adb_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report, constructor = self.run_fixture(Path(directory))
        self.assertEqual(code, 0)
        self.assertEqual(report['mode'], 'check-only')
        self.assertFalse(report['disk_write_started'])
        self.assertEqual(report['action']['node'], INSTALL.RAW)
        self.assertEqual(report['action']['bytes'], INSTALL.IMAGE_BYTES)
        constructor.assert_not_called()

    def test_write_cannot_start_until_timer_stopped_and_fresh_checks_pass(self):
        primary, backup, state = self.primary, self.backup, self.state
        for failure in ('timer', 'new_mount', 'normal_android', 'new_gpt', 'expired_timer'):
            calls = []
            class Fake:
                def state(self):
                    calls.append('state')
                    result = {**state, 'timer': 'stopped' if 'stop' in calls else 'running'}
                    if 'stop' in calls and failure == 'new_mount':
                        result['mountinfo'] += '3 1 8:19 / /data rw - f2fs /dev/block/sda19 rw\n'
                    if failure == 'normal_android':
                        result['marker'] = ''
                    if failure == 'expired_timer':
                        result['uptime'] = '120.1 100.0'
                    return result
                def gpt(self, unused):
                    calls.append('gpt')
                    if 'stop' in calls and failure == 'new_gpt':
                        return bytes(len(primary)), backup
                    return primary, backup
                def stop_timer(self):
                    calls.append('stop')
                    if failure == 'timer':
                        raise ValueError('timer stop failed')
                def stream(self, *unused):
                    calls.append('WRITE')
                    raise AssertionError('unsafe write was attempted')
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                code, report, unused = self.run_fixture(Path(directory), erase=True, fake=Fake())
                self.assertEqual(code, 1)
                self.assertNotIn('WRITE', calls)
                self.assertFalse(report['disk_write_started'])

    def test_timer_stop_polls_actual_service_state_without_storage_commands(self):
        adb = INSTALL.ADB.__new__(INSTALL.ADB)
        with patch.object(adb, 'command', side_effect=[b'', b'running', b'stopped']) as command, \
             patch.object(INSTALL.time, 'sleep'):
            adb.stop_timer()
        self.assertEqual(command.call_args_list[0].args[0], 'setprop ctl.stop recovery-return')
        self.assertTrue(all('dd ' not in call.args[0] for call in command.call_args_list))
        with patch.object(adb, 'command', return_value=b'running'), \
             patch.object(INSTALL.time, 'sleep'), self.assertRaises(ValueError):
            adb.stop_timer()

    def test_adb_script_transport_uses_shell_v2_stdin_and_preserves_bytes_and_exit_status(self):
        adb = INSTALL.ADB.__new__(INSTALL.ADB)
        adb.serial = 'private-test-target'
        script = 'set -e\nprintf "a\\0b"\n'
        output = b'a\0b\xff\r\n'
        result = INSTALL.subprocess.CompletedProcess([], 0, stdout=output, stderr=b'')
        with patch.object(INSTALL.subprocess, 'run', return_value=result) as run:
            self.assertEqual(adb.command(script), output)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['adb', '-s', adb.serial, 'shell', '-T', 'sh', '-s'])
        self.assertEqual(kwargs['input'], script.encode())
        self.assertNotIn(script, args[0])
        failed = INSTALL.subprocess.CompletedProcess([], 127, stdout=b'', stderr=b'script failed')
        with patch.object(INSTALL.subprocess, 'run', return_value=failed), self.assertRaises(ValueError):
            adb.command(script)

    def test_non_recovery_identity_evidence_parses_and_is_refused_before_sysfs_fields(self):
        adb = INSTALL.ADB.__new__(INSTALL.ADB)
        partial = b'uid\x002000\x00marker\x00\x00product\x00redfin\x00'
        with patch.object(adb, 'command', return_value=partial):
            state = adb.state()
        self.assertEqual(state, {'uid': '2000', 'marker': '', 'product': 'redfin'})
        with self.assertRaisesRegex(ValueError, 'normal Android is refused'):
            INSTALL.validate_state(state, self.target, self.primary)

    def test_binary_stream_uses_direct_bounded_dd_argv_and_shell_v2_status(self):
        data = bytes(range(256))*17
        class Sink(io.BytesIO):
            def close(self):
                self.saved = self.getvalue()
                super().close()
        class Process:
            def __init__(self, code):
                self.stdin = self.sink = Sink()
                self.returncode = code
            def communicate(self, timeout=None):
                return b'', b''
            def kill(self):
                raise AssertionError('unexpected kill')
        adb = INSTALL.ADB.__new__(INSTALL.ADB)
        adb.serial = 'private-test-target'
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory)/'image.img'; image.write_bytes(data)
            item = image.stat()
            expected = {'stat': [item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns],
                        'sha256': hashlib.sha256(data).hexdigest()}
            process = Process(0)
            with patch.object(INSTALL, 'IMAGE_BYTES', len(data)), \
                 patch.object(INSTALL.subprocess, 'Popen', return_value=process) as popen:
                adb.stream(image, expected)
            self.assertEqual(process.sink.saved, data)
            self.assertEqual(popen.call_args.args[0], ['adb', '-s', adb.serial, 'shell', '-T', 'dd',
                f'of={INSTALL.RAW}', f'bs={INSTALL.MIB}', f'count={len(data)}',
                'iflag=count_bytes', 'conv=fsync'])
            with patch.object(INSTALL, 'IMAGE_BYTES', len(data)), \
                 patch.object(INSTALL.subprocess, 'Popen', return_value=Process(1)), \
                 self.assertRaisesRegex(ValueError, 'raw userdata write failed'):
                adb.stream(image, expected)
    def test_simulated_write_records_full_readback_failure_and_checks_gpt_afterward(self):
        primary, backup, state = self.primary, self.backup, self.state
        calls = []
        class Fake:
            def state(self):
                calls.append('state')
                return {**state, 'timer': 'stopped' if 'stop' in calls else 'running'}
            def gpt(self, unused):
                calls.append('gpt')
                return primary, backup
            def stop_timer(self):
                calls.append('stop')
            def stream(self, *unused):
                calls.append('WRITE_SIMULATED')
            def readback(self):
                calls.append('readback')
                return 'b'*64
        with tempfile.TemporaryDirectory() as directory:
            code, report, unused = self.run_fixture(Path(directory), erase=True, fake=Fake())
        self.assertEqual(code, 1)
        self.assertTrue(report['timer_stopped'])
        self.assertEqual(report['gpt_before'], report['gpt_after'])
        self.assertEqual(report['backup_gpt_before'], report['backup_gpt_after'])
        self.assertLess(calls.index('stop'), calls.index('WRITE_SIMULATED'))
        self.assertEqual(calls[-1], 'gpt')

    def test_replay_can_never_authorize_write(self):
        with patch.object(INSTALL.subprocess, 'run', side_effect=AssertionError('physical commands forbidden')), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            INSTALL.main(['--image', 'x', '--build-manifest', 'b', '--expected-gpt', 'g',
                          '--out', 'o', '--state-json', 's', '--erase-userdata'])
        self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
