"""Execute the native Redfin AOP transport over a fault-injected word bus."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
UP, DOWN = 0xffff, 0xffff0000
TX, RX = 0x800, 0x600  # Both beyond upstream's hardcoded 1 KiB mapping.
CHECK = C.CFUNCTYPE(C.c_int, C.c_void_p)
READ = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32))
WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.c_uint32)
PAUSE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32)


class Snapshot(C.Structure):
    _fields_ = [('word', C.c_uint32 * 16), ('tx_length', C.c_uint32), ('rx_length', C.c_uint32)]


class Session(C.Structure):
    _fields_ = [('baseline', Snapshot)] + [(name, C.c_uint32) for name in
                ('attempted', 'open', 'poisoned', 'load_state', 'stores', 'notifications','adsp_load_state')]
    _fields_ += [('error', C.c_int)]


class Ops(C.Structure):
    _fields_ = [('context', C.c_void_p), ('check', CHECK), ('read32', READ),
                ('write32', WRITE), ('notify_aop', CHECK), ('pause_us', PAUSE)]


class Bus:
    def __init__(self, opened=False):
        self.words = [0] * 1024
        self.words[:16] = [0x4d41494c, 1, 0, UP, DOWN, DOWN, DOWN, 128, RX,
                           DOWN, DOWN, DOWN, DOWN, 128, TX, 0]
        if opened:
            for index in (3, 4, 5, 6, 9, 10, 11, 12):
                self.words[index] = UP
        self.log, self.received = [], []
        self.reads = self.writes = self.notifications = self.pauses = self.checks = 0
        self.fail_read = self.fail_write = self.fail_notify = self.owner_lost = 0
        self.no_link_ack = self.no_channel = self.no_channel_ack = self.no_tx_ack = False
        self.fail_pause = self.early_ack = False
        self.corrupt_write = None
        self.on_read = self.on_write = None
        self.callbacks = (CHECK(self.check), READ(self.read), WRITE(self.write),
                          CHECK(self.notify), PAUSE(self.pause))
        self.ops = Ops(None, *self.callbacks)

    def check(self, _context):
        self.checks += 1
        return -13 if self.owner_lost and self.checks >= self.owner_lost else 0

    def read(self, _context, offset, value):
        self.reads += 1
        self.log.append(('r', offset))
        if self.on_read:
            self.on_read(self, offset)
        if offset % 4 or offset >= 4096:
            self.log.append(('invalid-read', offset))
            return -90
        if self.reads == self.fail_read:
            return -14
        value[0] = self.words[offset // 4]
        return 0

    def consume(self):
        if self.words[TX // 4] == 64:
            self.received.append(struct.pack('<16I', *self.words[TX // 4 + 1:TX // 4 + 17]))
            self.words[TX // 4] = 0

    def write(self, _context, offset, value):
        self.writes += 1
        self.log.append(('w', offset, value))
        if offset % 4 or offset >= 4096:
            self.log.append(('invalid-write', offset))
            return -90
        if self.writes == self.fail_write:
            return -15
        self.words[offset // 4] = value ^ 1 if self.corrupt_write == offset else value
        if self.on_write:
            self.on_write(self, offset)
        if self.early_ack and offset == TX and value == 64:
            self.consume()
        return 0

    def notify(self, _context):
        self.notifications += 1
        self.log.append(('n',))
        if self.notifications == self.fail_notify:
            return -16
        if self.words[9] == UP and not self.no_link_ack:
            self.words[10] = UP
        if self.words[11] == UP and not self.no_channel:
            self.words[5] = UP
        if self.words[6] == UP and not self.no_channel_ack:
            self.words[12] = UP
        if not self.no_tx_ack:
            self.consume()
        return 0

    def pause(self, _context, microseconds):
        self.pauses += 1
        if microseconds != 1000:
            self.log.append(('invalid-pause', microseconds))
            return -90
        return -17 if self.fail_pause else 0


class WifiAopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        library = cls.directory / 'wifi-aop.so'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        str(HERE / 'wifi_aop.c'), '-o', str(library)], check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        cls.library.rf_wifi_aop_observe.argtypes = [C.POINTER(Ops), C.POINTER(Snapshot)]
        cls.library.rf_wifi_aop_open.argtypes = [C.POINTER(Session), C.POINTER(Ops)]
        cls.library.rf_wifi_aop_load_state.argtypes = [C.POINTER(Session), C.POINTER(Ops), C.c_int]
        cls.library.rf_wifi_aop_adsp_state.argtypes = [C.POINTER(Session), C.POINTER(Ops), C.c_int]

    def test_modem_and_adsp_share_the_mailbox_but_keep_separate_acknowledged_lifecycles(self):
        bus=Bus(opened=True);session=Session()
        self.assertEqual(self.library.rf_wifi_aop_open(C.byref(session),C.byref(bus.ops)),0)
        self.assertEqual(self.library.rf_wifi_aop_load_state(C.byref(session),C.byref(bus.ops),1),0)
        self.assertEqual(self.library.rf_wifi_aop_adsp_state(C.byref(session),C.byref(bus.ops),1),0)
        self.assertEqual((session.load_state,session.adsp_load_state),(1,1))
        self.assertNotEqual(self.library.rf_wifi_aop_adsp_state(C.byref(session),C.byref(bus.ops),1),0)
        self.assertEqual(self.library.rf_wifi_aop_adsp_state(C.byref(session),C.byref(bus.ops),0),0)
        self.assertEqual((session.load_state,session.adsp_load_state),(1,2))

    def observe(self, bus):
        snapshot = Snapshot()
        C.memset(C.byref(snapshot), 0xa5, C.sizeof(snapshot))
        before = bytes(snapshot)
        status = self.library.rf_wifi_aop_observe(C.byref(bus.ops), C.byref(snapshot))
        if status:
            self.assertEqual(bytes(snapshot), before, 'partial descriptor must remain unpublished')
        self.assertFalse(any(event[0].startswith('invalid') for event in bus.log))
        return status, snapshot

    def open(self, bus):
        session = Session()
        status = self.library.rf_wifi_aop_open(C.byref(session), C.byref(bus.ops))
        return status, session

    def send(self, bus, session, on):
        return self.library.rf_wifi_aop_load_state(C.byref(session), C.byref(bus.ops), on)

    def test_observer_only_reads_full_redfin_mapping_and_lengths(self):
        bus = Bus()
        before = bus.words.copy()
        status, snapshot = self.observe(bus)
        self.assertEqual(status, 0)
        self.assertEqual(bus.reads, 36)
        self.assertEqual((snapshot.word[14], snapshot.word[8]), (TX, RX))
        self.assertEqual(bus.words, before)
        self.assertTrue(all(event[0] == 'r' for event in bus.log))

    def test_malformed_geometry_is_rejected_before_indirect_access(self):
        for index, value in ((0, 0), (1, 2), (2, 1), (15, 1), (3, 0),
                             (14, 4096), (14, 63), (14, 65), (14, 0xfffffff0),
                             (13, 64), (13, 0xffffffff), (8, TX), (7, 67), (7, 4096)):
            with self.subTest(index=index, value=value):
                bus = Bus()
                bus.words[index] = value
                self.assertEqual(self.observe(bus)[0], 3)
                self.assertTrue(all(event[1] < 64 for event in bus.log))
                self.assertEqual(bus.writes, 0)

    def test_descriptor_changes_are_not_published_or_used(self):
        bus = Bus()
        bus.on_read = lambda b, _o: b.words.__setitem__(14, TX + 16) if b.reads == 19 else None
        self.assertEqual(self.observe(bus)[0], 4)
        self.assertEqual(bus.writes, 0)

    def test_warm_open_adopts_without_writes_or_doorbells(self):
        bus = Bus(opened=True)
        status, session = self.open(bus)
        self.assertEqual((status, session.open, session.poisoned), (0, 1, 0))
        self.assertEqual((bus.writes, bus.notifications), (0, 0))
        self.assertEqual(self.library.rf_wifi_aop_open(C.byref(session), C.byref(bus.ops)), 6)

    def test_cold_open_writes_only_four_apps_words_and_three_aop_notifications(self):
        bus = Bus()
        status, session = self.open(bus)
        self.assertEqual((status, session.open, session.poisoned), (0, 1, 0))
        writes = [event for event in bus.log if event[0] == 'w']
        self.assertEqual(writes, [('w', 0x10, UP), ('w', 0x24, UP), ('w', 0x2c, UP), ('w', 0x18, UP)])
        self.assertEqual((session.stores, session.notifications, bus.notifications), (4, 3, 3))
        self.assertEqual(bus.received, [])

    def test_partial_handoff_and_pending_messages_never_reset_or_discarded(self):
        for index, value in ((9, UP), (5, UP), (10, UP), (11, UP), (12, UP),
                             (TX // 4, 64), (RX // 4, 64)):
            bus = Bus()
            bus.words[index] = value
            before = bus.words.copy()
            with self.subTest(index=index):
                status, session = self.open(bus)
                self.assertIn(status, (5, 6))
                self.assertTrue(session.poisoned)
                self.assertEqual(bus.words, before)
                self.assertEqual((bus.writes, bus.notifications), (0, 0))

    def test_exact_modem_messages_on_then_off_with_zero_padding(self):
        bus = Bus(opened=True)
        _, session = self.open(bus)
        self.assertEqual(self.send(bus, session, 0), 6)
        self.assertEqual(self.send(bus, session, 2), 1)
        self.assertEqual(self.send(bus, session, 1), 0)
        self.assertEqual(session.load_state, 1)
        self.assertEqual(self.send(bus, session, 1), 6)
        self.assertEqual(self.send(bus, session, 0), 0)
        self.assertEqual(session.load_state, 2)
        self.assertEqual(self.send(bus, session, 0), 6)
        self.assertEqual(bus.received, [
            b'{class: image, res: load_state, name: modem, val: on}'.ljust(64, b'\0'),
            b'{class: image, res: load_state, name: modem, val: off}'.ljust(64, b'\0')])
        self.assertEqual((bus.writes, bus.notifications), (34, 2))
        self.assertEqual([event[1] for event in bus.log if event[0] == 'w'],
                         list(range(TX + 4, TX + 68, 4)) + [TX] +
                         list(range(TX + 4, TX + 68, 4)) + [TX])

    def test_fast_remote_consumption_before_readback_is_still_acknowledged(self):
        bus = Bus(opened=True)
        bus.early_ack = True
        _, session = self.open(bus)
        self.assertEqual(self.send(bus, session, 1), 0)
        self.assertEqual(len(bus.received), 1)
        self.assertEqual(bus.notifications, 1)

    def test_payload_readback_failure_prevents_length_publication_and_notification(self):
        for offset in range(TX + 4, TX + 68, 4):
            bus = Bus(opened=True)
            _, session = self.open(bus)
            bus.corrupt_write = offset
            with self.subTest(offset=offset):
                self.assertEqual(self.send(bus, session, 1), 4)
                self.assertTrue(session.poisoned)
                self.assertEqual((bus.words[TX // 4], bus.notifications), (0, 0))

    def test_all_control_and_payload_store_failures_stop_without_retry(self):
        for failure in range(1, 5):
            bus = Bus()
            bus.fail_write = failure
            with self.subTest(control=failure):
                status, session = self.open(bus)
                self.assertEqual(status, 2)
                self.assertEqual(bus.writes, failure)
                self.assertTrue(session.poisoned)
        for failure in range(1, 18):
            bus = Bus(opened=True)
            _, session = self.open(bus)
            bus.fail_write = failure
            with self.subTest(payload=failure):
                self.assertEqual(self.send(bus, session, 1), 2)
                self.assertEqual(bus.writes, failure)
                self.assertTrue(session.poisoned)
                self.assertEqual(bus.notifications, 0)
                self.assertEqual(self.send(bus, session, 1), 6)
                self.assertEqual(bus.writes, failure)

    def test_all_open_read_failures_and_lease_loss_allow_no_later_operations(self):
        complete = Bus()
        self.open(complete)
        for failure in range(1, complete.reads + 1):
            bus = Bus()
            bus.fail_read = failure
            with self.subTest(read=failure):
                status, session = self.open(bus)
                self.assertEqual(status, 2)
                self.assertEqual(bus.reads, failure)
                self.assertTrue(session.poisoned)
        for failure in (1, 37, 80, complete.checks):
            bus = Bus()
            bus.owner_lost = failure
            with self.subTest(check=failure):
                status, session = self.open(bus)
                self.assertEqual(status, 2)
                self.assertTrue(session.poisoned)
                old = bus.writes, bus.notifications, bus.reads
                self.assertEqual(self.send(bus, session, 1), 6)
                self.assertEqual((bus.writes, bus.notifications, bus.reads), old)

    def test_geometry_or_owned_control_change_before_send_prevents_writes(self):
        for index in (0, 1, 2, 4, 6, 7, 8, 9, 11, 13, 14, 15):
            bus = Bus(opened=True)
            _, session = self.open(bus)
            bus.words[index] ^= 1
            with self.subTest(index=index):
                self.assertEqual(self.send(bus, session, 1), 4)
                self.assertTrue(session.poisoned)
                self.assertEqual(bus.writes, 0)

    def test_foreign_message_appearing_during_payload_is_never_overwritten(self):
        bus = Bus(opened=True)
        _, session = self.open(bus)
        bus.on_write = lambda b, offset: b.words.__setitem__(TX // 4, 32) if offset == TX + 64 else None
        self.assertEqual(self.send(bus, session, 1), 5)
        self.assertEqual((bus.words[TX // 4], bus.notifications), (32, 0))
        self.assertEqual(bus.writes, 16)

    def test_notify_failure_and_tx_timeout_leave_message_intact_and_poison_session(self):
        for failure in ('notify', 'timeout', 'pause'):
            bus = Bus(opened=True)
            _, session = self.open(bus)
            bus.fail_notify = 1 if failure == 'notify' else 0
            bus.no_tx_ack = True
            bus.fail_pause = failure == 'pause'
            with self.subTest(failure=failure):
                self.assertEqual(self.send(bus, session, 1), 7 if failure == 'timeout' else 2)
                self.assertTrue(session.poisoned)
                self.assertEqual(bus.words[TX // 4], 64)
                self.assertEqual(bus.pauses, 1000 if failure == 'timeout' else 1 if failure == 'pause' else 0)
                self.assertEqual([event for event in bus.log if event[0] == 'w' and event[1] == TX], [('w', TX, 64)])
                before = bus.writes, bus.notifications
                self.assertEqual(self.send(bus, session, 0), 6)
                self.assertEqual((bus.writes, bus.notifications), before)

    def test_bounded_handshake_timeouts_do_not_reset_or_close_channel(self):
        for failure, stores in (('no_link_ack', 2), ('no_channel', 3), ('no_channel_ack', 4)):
            bus = Bus()
            setattr(bus, failure, True)
            with self.subTest(failure=failure):
                status, session = self.open(bus)
                self.assertEqual(status, 7)
                self.assertTrue(session.poisoned)
                self.assertEqual((bus.pauses, bus.writes), (5000, stores))
                self.assertTrue(all(event[2] == UP for event in bus.log if event[0] == 'w'))

    def test_actual_source_compiles_as_cpp_and_freestanding_arm64(self):
        compiler = shutil.which('c++')
        if compiler:
            subprocess.run([compiler, '-x', 'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsyntax-only', str(HERE / 'wifi_aop.c')], check=True, capture_output=True)
        clang = shutil.which('clang')
        if clang:
            output = self.directory / 'aop-arm64.o'
            subprocess.run([clang, '-target', 'aarch64-none-elf', '-ffreestanding', '-O2', '-std=c11',
                            '-Wall', '-Wextra', '-Werror', '-fstack-usage', '-c', str(HERE / 'wifi_aop.c'),
                            '-o', str(output)], check=True, capture_output=True)
            frames = [int(line.split('\t')[1]) for line in output.with_suffix('.su').read_text().splitlines()]
            self.assertTrue(frames)
            self.assertLess(sum(frames), 2048)

    def test_kernel_overlay_contains_the_same_native_transport(self):
        from test_overlay_sources import sensor_overlay
        patch = (HERE / 'wifi-aop.patch').read_text()
        for source, destination in [('wifi_aop.h', 'redfin_wifi_aop.h'),
                                    ('wifi_aop.c', 'redfin_wifi_aop.c')]:
            section = patch.split('+++ b/bsd/dev/' + destination + '\n', 1)[1]
            section = section.split('diff --git ', 1)[0]
            actual = ''.join(line[1:] for line in section.splitlines(keepends=True) if line.startswith('+'))
            actual=sensor_overlay(actual,'bsd/dev/'+destination)
            expected = (HERE / source).read_text().replace('#include "wifi_aop.h"',
                                                          '#include "redfin_wifi_aop.h"')
            self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
