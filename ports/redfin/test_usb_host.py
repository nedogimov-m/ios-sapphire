"""CDC host diagnostic: independent wire checks and fake libusb lifecycle."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
HOST_MAC = bytes.fromhex('02005e77ee01')
PHONE_MAC = bytes.fromhex('02005e77ee02')
HOST_IP = bytes((192, 168, 7, 1))
PHONE_IP = bytes((192, 168, 7, 2))
BOOT_ID = '0123456789abcdef'


def wire_checksum(data):
    """Independent one's-complement checksum for packet assertions."""
    if len(data) & 1:
        data += b'\0'
    total = sum(struct.unpack('!%dH' % (len(data) // 2), data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return (~total) & 0xffff


def incoming_ipv4(payload, protocol, *, source=PHONE_IP, destination=HOST_IP,
                  source_mac=PHONE_MAC, destination_mac=HOST_MAC, fragment=0):
    header = bytearray(struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(payload),
                                   0x1234, fragment, 64, protocol, 0, source, destination))
    struct.pack_into('!H', header, 10, wire_checksum(bytes(header)))
    return destination_mac + source_mac + b'\x08\x00' + bytes(header) + payload


def incoming_arp(*, operation=1, source=PHONE_IP, destination=HOST_IP,
                 source_mac=PHONE_MAC, target_mac=bytes(6), destination_mac=HOST_MAC):
    return destination_mac + source_mac + b'\x08\x06' + struct.pack(
        '!HHBBH6s4s6s4s', 1, 0x0800, 6, 4, operation,
        source_mac, source, target_mac, destination)


def incoming_udp(payload, *, port=5140, source_port=5140, checksum=True, **kwargs):
    source = kwargs.get('source', PHONE_IP)
    destination = kwargs.get('destination', HOST_IP)
    udp = bytearray(struct.pack('!HHHH', source_port, port, len(payload) + 8, 0) + payload)
    if checksum:
        pseudo = source + destination + struct.pack('!BBH', 0, 17, len(udp))
        struct.pack_into('!H', udp, 6, wire_checksum(pseudo + bytes(udp)) or 0xffff)
    return incoming_ipv4(bytes(udp), 17, **kwargs)


def load_host():
    import ctypes.util  # Python 3.15 imports libc here; allow this before guarding USB loads.
    spec = importlib.util.spec_from_file_location('redfin_usb_host_tested', HERE / 'usb-host.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with mock.patch('ctypes.CDLL', side_effect=AssertionError('tests must not open native USB')):
        spec.loader.exec_module(module)
    return module


def incoming_echo(boot_id=BOOT_ID, *, identifier=0x5246, sequence=1, **kwargs):
    icmp = bytearray(struct.pack('!BBHHH', 0, 0, 0, identifier, sequence) +
                     b'REDFIN USB ' + boot_id.encode('ascii'))
    struct.pack_into('!H', icmp, 2, wire_checksum(bytes(icmp)))
    return incoming_ipv4(bytes(icmp), 1, **kwargs)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeHandle:
    def __init__(self, host, clock, *, configuration=0, failure=None, frames=None):
        self.host, self.clock = host, clock
        self.configuration, self.failure = configuration, failure
        self.calls = []
        self.frames = list(frames if frames is not None else (
            incoming_arp(operation=2, target_mac=HOST_MAC), incoming_echo(),
            incoming_udp(f'REDFIN BOOT ID: {BOOT_ID}\n'.encode(), source_port=31337)))
        self.closed = 0
        self.short_write = False

    def record(self, name, *args):
        self.calls.append((name, *args))
        if self.failure and self.failure[0] == name:
            raise self.host.USBError(self.failure[1], 'injected ' + name)

    def get_configuration(self):
        self.record('get_configuration')
        return self.configuration

    def set_configuration(self, value):
        self.record('set_configuration', value)
        self.configuration = value

    def claim_interface(self, interface):
        self.record('claim_interface', interface)

    def set_alt_setting(self, interface, alternate):
        self.record('set_alt_setting', interface, alternate)

    def control_transfer(self, request_type, request, value, index, data, timeout_ms):
        self.record('control_transfer', request_type, request, value, index, data)
        if not (0 < timeout_ms <= 120000):
            raise AssertionError('unbounded control timeout')
        return b''

    def bulk_read(self, endpoint, size, timeout_ms):
        self.record('bulk_read', endpoint, size)
        if endpoint != 0x81 or size > 16384 or not (0 < timeout_ms <= 120000):
            raise AssertionError('invalid or unbounded bulk read')
        self.clock.now += 0.2
        if not self.frames:
            return b''  # NativeHandle discards partial IN data on LIBUSB_ERROR_TIMEOUT.
        frame = self.frames.pop(0)
        if isinstance(frame, int):
            raise self.host.USBError(frame, 'injected bulk IN')
        return frame

    def bulk_write(self, endpoint, data, timeout_ms):
        self.record('bulk_write', endpoint, bytes(data))
        if endpoint != 1 or len(data) > 2048 or not (0 < timeout_ms <= 120000):
            raise AssertionError('invalid or unbounded bulk write')
        return len(data) - int(self.short_write)

    def release_interface(self, interface):
        self.record('release_interface', interface)

    def close(self):
        self.closed += 1
        self.record('close')
        if self.closed != 1:
            raise AssertionError('USB handle closed more than once')

    def detach_kernel_driver(self, *args):
        raise AssertionError('kernel detach is forbidden')

    def reset(self):
        raise AssertionError('USB reset is forbidden')


class FakeBackend:
    def __init__(self, host, clock, *, snapshots=None, handle=None, open_error=None):
        self.host, self.clock = host, clock
        self.google = host.DeviceInfo(3, (2, 4), 0x18d1, 0x4ee0, 'google')
        self.gadget = host.DeviceInfo(3, (2, 4), 0x1209, 1, 'gadget')
        self.snapshots = list(snapshots if snapshots is not None else
                              ([self.google], [self.gadget]))
        self.handle = handle or FakeHandle(host, clock)
        self.open_error = open_error
        self.calls, self.depth = [], 0

    @contextlib.contextmanager
    def snapshot(self):
        self.calls.append(('snapshot',))
        items = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        self.depth += 1
        try:
            yield items
        finally:
            self.depth -= 1

    def open(self, device):
        if self.depth != 1:
            raise AssertionError('native device opened after snapshot lifetime ended')
        self.calls.append(('open', device))
        if self.open_error is not None:
            raise self.host.USBError(self.open_error, 'injected open')
        return self.handle


class USBHostProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = load_host()

    def test_checksum_and_outgoing_arp_echo_have_exact_lengths_addresses_and_checksums(self):
        self.assertEqual(self.host.checksum(b'\x00\x01\xf2\x03\xf4\xf5\xf6\xf7'), 0x220d)
        self.assertEqual(self.host.checksum(b'abc'), wire_checksum(b'abc'))
        protocol = self.host.Protocol(BOOT_ID)
        arp = protocol.arp_request()
        self.assertEqual(arp[:14], bytes.fromhex('ffffffffffff') + HOST_MAC + b'\x08\x06')
        self.assertIn(len(arp), (42, 60))
        self.assertEqual(arp[42:], bytes(len(arp) - 42))
        self.assertEqual(struct.unpack('!HHBBH6s4s6s4s', arp[14:42]),
                         (1, 0x800, 6, 4, 1, HOST_MAC, HOST_IP, bytes(6), PHONE_IP))
        echo = protocol.echo_request()
        self.assertEqual(echo[:14], PHONE_MAC + HOST_MAC + b'\x08\x00')
        self.assertEqual(echo[26:34], HOST_IP + PHONE_IP)
        self.assertEqual(wire_checksum(echo[14:34]), 0)
        self.assertEqual(wire_checksum(echo[34:]), 0)
        self.assertEqual(echo[34:36], b'\x08\x00')
        self.assertEqual(echo[38:42], struct.pack('!HH', 0x5246, 1))
        self.assertEqual(echo[42:], b'REDFIN USB ' + BOOT_ID.encode())
        self.assertEqual(struct.unpack_from('!H', echo, 16)[0], len(echo) - 14)

    def test_arp_request_reply_handshake_and_strict_sender_identity(self):
        protocol = self.host.Protocol(BOOT_ID)
        replies = protocol.feed(incoming_arp(destination_mac=bytes.fromhex('ffffffffffff')))
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][:14], PHONE_MAC + HOST_MAC + b'\x08\x06')
        self.assertEqual(struct.unpack('!HHBBH6s4s6s4s', replies[0][14:42]),
                         (1, 0x800, 6, 4, 2, HOST_MAC, HOST_IP, PHONE_MAC, PHONE_IP))
        protocol = self.host.Protocol(BOOT_ID)
        self.assertEqual(protocol.feed(incoming_arp(operation=2, target_mac=HOST_MAC)), [])
        self.assertTrue(protocol.arp_seen)
        invalid = [incoming_arp(source=b'\xc0\xa8\x07\x03'),
                   incoming_arp(destination=b'\xc0\xa8\x07\x03'),
                   incoming_arp(source_mac=b'\x02' * 6), incoming_arp(operation=3)]
        for offset, replacement in ((14, b'\0\2'), (16, b'\x86\xdd'),
                                    (18, b'\x05'), (19, b'\x06'), (22, b'\x02' * 6)):
            frame = bytearray(incoming_arp())
            frame[offset:offset+len(replacement)] = replacement
            invalid.append(bytes(frame))
        for frame in invalid:
            with self.subTest(frame=frame.hex()):
                protocol = self.host.Protocol(BOOT_ID)
                self.assertEqual(protocol.feed(frame), [])
                self.assertFalse(protocol.arp_seen)

    def test_echo_requires_current_boot_exact_payload_identifier_sequence_and_checksum(self):
        protocol = self.host.Protocol(BOOT_ID)
        self.assertEqual(protocol.feed(incoming_echo()), [])
        self.assertTrue(protocol.echo_seen)
        broken = bytearray(incoming_echo())
        broken[-1] ^= 1
        frames = [incoming_echo('fedcba9876543210'), incoming_echo(identifier=3),
                  incoming_echo(sequence=2), bytes(broken),
                  incoming_echo(source=b'\xc0\xa8\x07\x03'),
                  incoming_echo(source_mac=b'\x02' * 6)]
        for frame in frames:
            protocol = self.host.Protocol(BOOT_ID)
            protocol.feed(frame)
            self.assertFalse(protocol.echo_seen)

    def test_ipv4_udp_lengths_checksums_fragments_and_identity_are_checked_before_logging(self):
        good = incoming_udp(b'hello', source_port=31337)
        protocol = self.host.Protocol(BOOT_ID)
        protocol.feed(good + bytes(60 - len(good)))
        self.assertEqual(protocol.log, b'hello')
        malformed = [good[:13], good[:33], good[:-1],
                     incoming_udp(b'bad', source=b'\xc0\xa8\x07\x03'),
                     incoming_udp(b'bad', destination=b'\xc0\xa8\x07\x03'),
                     incoming_udp(b'bad', source_mac=b'\x02' * 6),
                     incoming_udp(b'bad', destination_mac=b'\x02' * 6),
                     incoming_udp(b'bad', port=5141),
                     incoming_udp(b'bad', source_port=0),
                     incoming_udp(b'bad', fragment=0x2000), incoming_udp(b'bad', fragment=1)]
        broken = bytearray(good)
        broken[-1] ^= 1
        malformed.append(bytes(broken))
        broken = bytearray(good)
        broken[22] ^= 1  # Bad IP checksum with unchanged addresses and transport bytes.
        malformed.append(bytes(broken))
        for length in (7, 14):
            broken = bytearray(good)
            struct.pack_into('!HH', broken, 38, length, 0)  # IPv4 permits zero UDP checksum.
            malformed.append(bytes(broken))
        for field, value in ((14, 0x44), (14, 0x65), (16, 1), (17, 19), (17, 255)):
            frame = bytearray(good)
            frame[field] = value
            frame[24:26] = bytes(2)
            frame[24:26] = struct.pack('!H', wire_checksum(bytes(frame[14:34])))
            malformed.append(bytes(frame))
        for frame in malformed:
            with self.subTest(frame=frame.hex()):
                protocol = self.host.Protocol(BOOT_ID)
                self.assertEqual(protocol.feed(frame), [])
                self.assertEqual(protocol.log, b'')

    def test_udp_log_is_bounded_and_boot_marker_freshness_is_exact_across_datagrams(self):
        protocol = self.host.Protocol(BOOT_ID, log_limit=32)
        protocol.feed(incoming_udp(b'A' * 20))
        protocol.feed(incoming_udp(b'B' * 20))
        self.assertEqual(protocol.log, b'A' * 20 + b'B' * 12)
        self.assertTrue(protocol.log_overflow)
        protocol.feed(incoming_udp(b'C' * 20))
        self.assertEqual(len(protocol.log), 32)
        protocol = self.host.Protocol(BOOT_ID)
        self.assertEqual(protocol.log_freshness, 'missing')
        protocol.feed(incoming_udp(b'REDFIN BOOT ID: 01234567', checksum=False))
        self.assertNotEqual(protocol.log_freshness, 'matched')
        protocol.feed(incoming_udp(b'89abcdef\r\n', source_port=31337))
        self.assertEqual(protocol.log_freshness, 'matched')
        protocol.feed(incoming_udp(f'REDFIN BOOT ID: {BOOT_ID}\n'.encode()))
        self.assertEqual(protocol.log_freshness, 'duplicate')
        protocol = self.host.Protocol(BOOT_ID)
        protocol.feed(incoming_udp(b'REDFIN BOOT ID: fedcba9876543210\n'))
        self.assertEqual(protocol.log_freshness, 'mismatch')
        protocol = self.host.Protocol(BOOT_ID)
        protocol.feed(incoming_udp(f'xREDFIN BOOT ID: {BOOT_ID}\n'.encode()))
        self.assertEqual(protocol.log_freshness, 'missing')

    def test_manifest_boot_id_is_explicit_nonzero_and_unambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps({'boot_args': f'cpus=1 redfinbootid=0x{BOOT_ID}'}))
            self.assertEqual(self.host.read_boot_id(path), BOOT_ID)
            for args in ('cpus=1', 'redfinbootid=0', 'redfinbootid=0x10000000000000000',
                         f'redfinbootid=0x{BOOT_ID} redfinbootid=0x{BOOT_ID}'):
                path.write_text(json.dumps({'boot_args': args}))
                with self.subTest(args=args), self.assertRaises((ValueError, RuntimeError)):
                    self.host.read_boot_id(path)


class USBHostLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = load_host()

    def run_fake(self, *, configuration=0, failure=None, frames=None):
        clock = FakeClock()
        handle = FakeHandle(self.host, clock, configuration=configuration, failure=failure, frames=frames)
        backend = FakeBackend(self.host, clock, handle=handle)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out = Path(directory.name) / 'capture'
        return backend, handle, clock, out

    def test_exact_configuration_interface_alt_filter_and_close_lifecycle(self):
        backend, handle, clock, out = self.run_fake()
        result = self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertIsInstance(result, dict)
        self.assertEqual(result['status'], 'link-ready')
        self.assertTrue(result['arp_seen'])
        self.assertTrue(result['echo_seen'])
        self.assertEqual(result['udp_log_freshness'], 'matched')
        self.assertFalse(result['capture_authenticated'])
        self.assertEqual(result['evidence'], 'direct-usb')
        self.assertEqual(handle.calls[:5], [
            ('get_configuration',), ('set_configuration', 1), ('claim_interface', 1),
            ('set_alt_setting', 1, 1), ('control_transfer', 0x21, 0x43, 0xf, 0, b'')])
        self.assertEqual(handle.calls[-2:], [('release_interface', 1), ('close',)])
        self.assertEqual(handle.closed, 1)
        self.assertEqual(sum(call[0] == 'open' for call in backend.calls), 1)
        self.assertEqual(out.stat().st_mode & 0o777, 0o700)
        for artifact in out.iterdir():
            if artifact.is_file():
                self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        self.assertLessEqual(clock.now, 1.21)
        writes = [call[2] for call in handle.calls if call[0] == 'bulk_write']
        self.assertTrue(any(frame[12:14] == b'\x08\x06' for frame in writes))
        self.assertTrue(any(frame[12:14] == b'\x08\x00' and frame[34:36] == b'\x08\x00'
                            for frame in writes))

    def test_configuration_one_is_kept_and_filter_pipe_is_the_only_optional_control_error(self):
        backend, handle, clock, out = self.run_fake(configuration=1, failure=('control_transfer', -9))
        self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertFalse(any(call[0] == 'set_configuration' for call in handle.calls))
        self.assertEqual(handle.closed, 1)

    def test_access_and_busy_errors_never_retry_detach_or_reset_and_close_owned_handle_once(self):
        for code in (-3, -6):
            backend, handle, clock, out = self.run_fake()
            backend.open_error = code
            with self.subTest(code=code, stage='open'), self.assertRaises(self.host.USBError):
                self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
            self.assertEqual(sum(call[0] == 'open' for call in backend.calls), 1)
            self.assertEqual(handle.closed, 0)
            for method in ('get_configuration', 'set_configuration', 'claim_interface',
                           'set_alt_setting', 'control_transfer', 'bulk_write', 'bulk_read'):
                backend, handle, clock, out = self.run_fake(failure=(method, code))
                with self.subTest(code=code, stage=method), self.assertRaises(self.host.USBError):
                    self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
                self.assertEqual(sum(call[0] == method for call in handle.calls), 1)
                self.assertEqual(handle.closed, 1)
                self.assertEqual(sum(call[0] == 'open' for call in backend.calls), 1)
                expected_release = int(method in ('set_alt_setting', 'control_transfer',
                                                  'bulk_write', 'bulk_read'))
                self.assertEqual(sum(call[0] == 'release_interface' for call in handle.calls),
                                 expected_release)

    def test_short_out_is_fatal_without_resend_and_release_failure_still_closes(self):
        backend, handle, clock, out = self.run_fake()
        handle.short_write = True
        with self.assertRaises((self.host.USBError, RuntimeError)):
            self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertEqual(sum(call[0] == 'bulk_write' for call in handle.calls), 1)
        self.assertEqual(handle.closed, 1)
        backend, handle, clock, out = self.run_fake(failure=('release_interface', -6))
        try:
            self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        except self.host.USBError:
            pass
        self.assertEqual(handle.closed, 1)

    def test_nonmatching_echo_and_stale_log_never_claim_fresh_evidence(self):
        frames = [incoming_arp(operation=2, target_mac=HOST_MAC),
                  incoming_echo('fedcba9876543210'),
                  incoming_udp(b'REDFIN BOOT ID: fedcba9876543210\n')]
        backend, handle, clock, out = self.run_fake(frames=frames)
        result = self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertEqual(result['status'], 'probe-incomplete')
        self.assertFalse(result['echo_seen'])
        self.assertEqual(result['udp_log_freshness'], 'mismatch')
        self.assertFalse(result['capture_authenticated'])
        self.assertEqual(handle.closed, 1)

    def test_unexpected_active_configuration_is_not_replaced(self):
        backend, handle, clock, out = self.run_fake(configuration=2)
        with self.assertRaises((self.host.USBError, ValueError, RuntimeError)):
            self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertEqual(handle.calls, [('get_configuration',), ('close',)])

    def test_log_overflow_stops_reads_and_closes_without_waiting_for_deadline(self):
        backend, handle, clock, out = self.run_fake(frames=[incoming_udp(b'X' * 32)])
        original = self.host.Protocol
        with mock.patch.object(self.host, 'Protocol',
                               side_effect=lambda boot, *args, **kwargs: original(boot, log_limit=8)):
            result = self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertEqual(result['log_bytes'], 8)
        self.assertTrue(result['log_overflow'])
        self.assertEqual(sum(call[0] == 'bulk_read' for call in handle.calls), 1)
        self.assertLess(clock.now, 1)
        self.assertEqual(handle.closed, 1)

    def test_disconnect_after_echo_keeps_link_evidence_and_without_progress_is_incomplete(self):
        ready = [incoming_arp(operation=2, target_mac=HOST_MAC), incoming_echo(), -4]
        for frames, status in ((ready, 'link-ready'), ([-4], 'probe-incomplete')):
            for release_error in (None, ('release_interface', -4)):
                backend, handle, clock, out = self.run_fake(frames=frames, failure=release_error)
                result = self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
                self.assertEqual(result['status'], status)
                self.assertEqual(handle.closed, 1)
                self.assertEqual(sum(call[0] == 'release_interface' for call in handle.calls), 1)

    def test_disconnect_does_not_hide_other_release_errors(self):
        for code in (-3, -6):
            backend, handle, clock, out = self.run_fake(frames=[-4],
                                                        failure=('release_interface', code))
            with self.assertRaises(self.host.USBError) as raised:
                self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(handle.closed, 1)

    def test_unsolicited_echo_before_successful_out_is_not_link_evidence(self):
        for frames in ([incoming_echo()],
                       [incoming_echo(), incoming_arp(operation=2, target_mac=HOST_MAC)]):
            backend, handle, clock, out = self.run_fake(frames=frames)
            result = self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
            self.assertEqual(result['status'], 'probe-incomplete')
            self.assertFalse(result['echo_seen'])
            self.assertEqual(handle.closed, 1)

    def test_baseline_failure_still_writes_private_error_manifest_without_open(self):
        backend, handle, clock, out = self.run_fake()
        backend.snapshots = [[]]
        with self.assertRaises(ValueError):
            self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        result = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(result['status'], 'error')
        self.assertFalse(any(call[0] == 'open' for call in backend.calls))
        self.assertEqual((out / 'manifest.json').stat().st_mode & 0o777, 0o600)

    def test_cli_preflight_never_initializes_libusb_for_invalid_duration_or_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'image.json'
            manifest.write_text(json.dumps({'boot_args': f'redfinbootid=0x{BOOT_ID}'}))
            for seconds, existing in ((0, False), (121, False), (1, True)):
                out = root / f'capture-{seconds}-{existing}'
                if existing:
                    out.mkdir()
                with mock.patch.object(self.host, 'LibUSB',
                                       side_effect=AssertionError('invalid CLI must not touch USB')), \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(self.host.main(['--image-manifest', str(manifest),
                                                       '--seconds', str(seconds), '--out', str(out)]), 0)


class USBHostNativeHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = load_host()

    def native(self, result, count):
        calls = []

        def transfer(handle, endpoint, buffer, size, actual, timeout):
            calls.append(('transfer', endpoint, size, timeout))
            actual._obj.value = count
            for index in range(min(size, count)):
                buffer[index] = 0xa5
            return result

        def check(value, operation):
            if value < 0:
                raise self.host.USBError(value, operation)
            return value

        backend = SimpleNamespace(lib=SimpleNamespace(libusb_bulk_transfer=transfer,
                                                      libusb_close=lambda handle: calls.append(('close',))),
                                  check=check)
        return self.host.Handle(backend, 0x1234), calls

    def test_native_in_timeout_discards_every_partial_byte_and_close_is_idempotent(self):
        handle, calls = self.native(-7, 64)
        self.assertEqual(handle.bulk_read(0x81, 2048, 25), b'')
        handle.close()
        handle.close()
        self.assertEqual(calls, [('transfer', 0x81, 2048, 25), ('close',)])

    def test_native_short_out_and_timeout_never_retransmit(self):
        for code, count in ((0, 3), (-7, 2)):
            handle, calls = self.native(code, count)
            with self.assertRaises(self.host.USBError):
                handle.bulk_write(0x01, b'frame', 25)
            self.assertEqual(calls, [('transfer', 0x01, 5, 25)])
            handle.close()


class USBHostSelectionTests(unittest.TestCase):
    run_fake = USBHostLifecycleTests.run_fake

    @classmethod
    def setUpClass(cls):
        cls.host = load_host()

    def test_physical_topology_is_pinned_and_ambiguous_baselines_are_refused(self):
        clock = FakeClock()
        backend = FakeBackend(self.host, clock)
        self.assertEqual(self.host.select_baseline([backend.google]), (3, (2, 4)))
        with self.assertRaises((ValueError, RuntimeError)):
            self.host.select_baseline([])
        other = self.host.DeviceInfo(3, (2, 5), 0x18d1, 0x4ee0, 'other')
        with self.assertRaises((ValueError, RuntimeError)):
            self.host.select_baseline([backend.google, other])
        impostor = self.host.DeviceInfo(3, (2, 5), 0x1209, 1, 'wrong-port')
        backend.snapshots = [[impostor]]
        with self.assertRaises((ValueError, RuntimeError, self.host.USBError)):
            self.host.open_gadget(backend, (3, (2, 4)), 0.2, clock=clock, sleep=clock.sleep)
        self.assertFalse(any(call[0] == 'open' for call in backend.calls))
        backend.snapshots = [[backend.gadget, backend.gadget]]
        with self.assertRaises((ValueError, RuntimeError, self.host.USBError)):
            self.host.open_gadget(backend, (3, (2, 4)), clock.now + 1,
                                  clock=clock, sleep=clock.sleep)

    def test_existing_output_or_invalid_duration_fails_before_usb_access(self):
        for seconds in (0, -1, 121):
            backend, handle, clock, out = self.run_fake()
            with self.assertRaises((ValueError, RuntimeError)):
                self.host.run_probe(backend, BOOT_ID, seconds, out, clock=clock, sleep=clock.sleep)
            self.assertEqual(backend.calls, [])
        backend, handle, clock, out = self.run_fake()
        out.mkdir()
        sentinel = out / 'keep'
        sentinel.write_bytes(b'unchanged')
        with self.assertRaises((FileExistsError, ValueError, RuntimeError)):
            self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        self.assertEqual(sentinel.read_bytes(), b'unchanged')
        self.assertEqual(backend.calls, [])


class USBHostDiscoveryTests(unittest.TestCase):
    run_fake = USBHostLifecycleTests.run_fake

    @classmethod
    def setUpClass(cls):
        cls.host = load_host()

    def test_discovery_records_only_changes_and_never_tokens_or_snapshot_order(self):
        first = self.host.DeviceInfo(3, (2, 4), 0x18d1, 0x4ee0, object())
        same = self.host.DeviceInfo(3, (2, 4), 0x18d1, 0x4ee0, object())
        other = self.host.DeviceInfo(3, (2, 5), 0x1209, 1, object())
        discovery = self.host.Discovery()
        discovery.observe([first, other])
        discovery.observe([other, same])
        discovery.observe([same])
        discovery.observe([])
        discovery.observe([])
        expected_first = [{'vendor': 0x1209, 'product': 1, 'bus': 3, 'ports': [2, 5]},
                          {'vendor': 0x18d1, 'product': 0x4ee0, 'bus': 3, 'ports': [2, 4]}]
        self.assertEqual(discovery.entries, [expected_first, expected_first[1:], []])
        self.assertEqual(discovery.transitions_dropped, 0)
        self.assertFalse(discovery.devices_truncated)
        json.dumps(discovery.entries)  # Opaque native tokens must never enter telemetry.

    def test_transition_and_device_caps_remain_bounded_and_last_state_advances_after_cap(self):
        device = self.host.DeviceInfo(3, (2, 4), 0x18d1, 1)
        discovery = self.host.Discovery(limit=2, device_limit=2)
        for snapshot in ([device], [], [device], [device], [], []):
            discovery.observe(snapshot)
        self.assertEqual(len(discovery.entries), 2)
        self.assertEqual(discovery.transitions_dropped, 2)
        many = [self.host.DeviceInfo(3, (2, index), 0x18d1, index) for index in range(1, 5)]
        discovery = self.host.Discovery(limit=2, device_limit=2)
        discovery.observe(list(reversed(many)))
        self.assertTrue(discovery.devices_truncated)
        self.assertEqual(len(discovery.entries[0]), 2)
        self.assertEqual([entry['product'] for entry in discovery.entries[0]], [1, 2])

    def test_callback_runs_inside_snapshot_before_screening_or_opening(self):
        clock = FakeClock()
        backend = FakeBackend(self.host, clock)
        wrong = self.host.DeviceInfo(3, (2, 5), 0x1209, 1, object())
        backend.snapshots = [[wrong]]
        discovery = self.host.Discovery()

        def observe(devices):
            self.assertEqual(backend.depth, 1)
            backend.calls.append(('observe',))
            discovery.observe(devices)

        with self.assertRaises(ValueError):
            self.host.open_gadget(backend, (3, (2, 4)), 1, clock, clock.sleep, observe)
        self.assertEqual(backend.calls, [('snapshot',), ('observe',)])
        self.assertEqual(discovery.entries[0][0]['ports'], [2, 5])
        backend.calls.clear()
        backend.snapshots = [[backend.gadget]]
        self.assertIs(self.host.open_gadget(backend, (3, (2, 4)), 1,
                                           clock, clock.sleep, observe), backend.handle)
        self.assertEqual([call[0] for call in backend.calls], ['snapshot', 'observe', 'open'])
        backend.handle.close()

    def test_failed_topology_check_keeps_seen_devices_and_baseline_without_implicit_open(self):
        backend, handle, clock, out = self.run_fake()
        wrong = self.host.DeviceInfo(3, (2, 5), 0x1209, 1, object())
        backend.snapshots = [[backend.google], [wrong]]
        with self.assertRaises(ValueError):
            self.host.run_probe(backend, BOOT_ID, 1, out, clock=clock, sleep=clock.sleep)
        result = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['baseline'], {'bus': 3, 'ports': [2, 4]})
        self.assertEqual(result['discovery'], [
            [{'vendor': 0x18d1, 'product': 0x4ee0, 'bus': 3, 'ports': [2, 4]}],
            [{'vendor': 0x1209, 'product': 1, 'bus': 3, 'ports': [2, 5]}]])
        self.assertEqual(result['discovery_transitions_dropped'], 0)
        self.assertFalse(result['discovery_devices_truncated'])
        self.assertFalse(any(call[0] == 'open' for call in backend.calls))
        self.assertEqual(handle.closed, 0)

    def test_failure_artifact_caps_transition_history_while_preserving_observation_counts(self):
        backend, handle, clock, out = self.run_fake()
        backend.snapshots = [[backend.google]] + [
            [self.host.DeviceInfo(3, (2, 4), 0x18d1, 0x5000 + number, object())]
            for number in range(100)]
        with self.assertRaises(TimeoutError):
            self.host.run_probe(backend, BOOT_ID, 15, out, clock=clock, sleep=clock.sleep)
        result = json.loads((out / 'manifest.json').read_text())
        self.assertEqual(len(result['discovery']), 64)
        self.assertEqual(result['discovery_transitions_dropped'], 37)
        self.assertTrue(all(len(snapshot) <= 32 for snapshot in result['discovery']))
        self.assertFalse(any(call[0] == 'open' for call in backend.calls))


if __name__ == '__main__':
    unittest.main()
