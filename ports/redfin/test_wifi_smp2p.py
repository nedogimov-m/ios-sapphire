"""Execute the native APPS/MPSS allocator and SMP2P state machine over SMEM."""
import ctypes as C
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_wifi_smem import fixture, PART, PART_SIZE, TOC, SIZE

HERE = Path(__file__).resolve().parent
PORT = HERE
CHECK = C.CFUNCTYPE(C.c_int, C.c_void_p)
NUMBER = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32)
WRITE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.c_uint32)
CLOCK = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(C.c_uint64))


class Session(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('attempted', 'stage', 'poisoned', 'allocator_locked')]
    _fields_ += [('error', C.c_int), ('platform_error', C.c_int)]
    _fields_ += [(name, C.c_uint32) for name in
                ('partition', 'partition_bytes', 'cacheline', 'entry', 'data', 'hosts', 'version', 'toc_count', 'toc_entry')]
    _fields_ += [('toc', C.c_uint32 * 12), ('own', C.c_uint32 * 86)]
    _fields_ += [(name, C.c_uint32) for name in
                ('peer', 'peer_seen', 'peer_features', 'peer_restart', 'peer_valid',
                 'slave_index', 'slave_found', 'last_state', 'handover')]
    _fields_ += [('names', (C.c_uint8 * 16) * 16), ('stores', C.c_uint32), ('kicks', C.c_uint32)]
    _fields_ += [(name, C.c_uint32) for name in ('ipa_index', 'ipa_found', 'ipa_state', 'ipa_responses')]
    _fields_ += [(name, C.c_uint32) for name in ('wlan_index', 'wlan_found', 'wlan_state')]


class Ops(C.Structure):
    _fields_ = [('smem', C.c_void_p), ('smem_bytes', C.c_size_t), ('context', C.c_void_p),
                ('check', CHECK), ('pas_reset', CHECK), ('pas_started', CHECK),
                ('lock', NUMBER), ('unlock', CHECK), ('write32', WRITE),
                ('barrier', CHECK), ('kick', CHECK), ('now_ms', CLOCK), ('pause_us', NUMBER)]


class Model:
    def __init__(self):
        self.memory = fixture(False)
        self.array = (C.c_uint8 * len(self.memory)).from_buffer(self.memory)
        self.session = Session()
        self.events = []
        self.cancel_at = self.checks = self.stores = self.kicks = self.barriers = self.clock = 0
        self.fail_store = self.fail_barrier = self.fail_kick = 0
        self.fail_lock = self.fail_unlock = self.fail_pause = False
        self.locked = self.started = False
        self.reset_proven = True
        self.owner = 0
        self.inbound = 0
        self.corrupt_store = None
        self.on_pause = self.on_kick = self.on_check = None
        self.auto_stop_ack = True
        self.freeze_clock = self.backward_clock = False
        self.callbacks = (CHECK(self.check), CHECK(self.reset), CHECK(self.authenticated),
                          NUMBER(self.lock), CHECK(self.unlock), WRITE(self.write), CHECK(self.barrier),
                          CHECK(self.kick), CLOCK(self.now), NUMBER(self.pause))
        self.ops = Ops(C.cast(self.array, C.c_void_p), SIZE, None, *self.callbacks)

    def u32(self, offset):
        return struct.unpack_from('<I', self.memory, offset)[0]

    def put(self, offset, value):
        struct.pack_into('<I', self.memory, offset, value)

    def check(self, _context):
        self.checks += 1
        if self.on_check:
            self.on_check(self)
        return -21 if (self.cancel_at and self.checks >= self.cancel_at) or (self.locked and self.owner != 1) else 0

    def reset(self, _context):
        self.events.append(('reset',))
        return 0 if self.reset_proven and not self.started else -22

    def authenticated(self, _context):
        return 0 if self.started else -23

    def lock(self, _context, milliseconds):
        self.events.append(('lock', milliseconds))
        if self.fail_lock or self.locked or milliseconds != 1000:
            return -24
        self.locked = True
        self.owner = 1
        return 0

    def unlock(self, _context):
        self.events.append(('unlock', self.owner))
        if self.fail_unlock or not self.locked or self.owner != 1:
            return -25
        self.locked = False
        self.owner = 0
        return 0

    def write(self, _context, offset, value):
        self.events.append(('write', offset, value))
        self.stores += 1
        if offset % 4 or not 0 <= offset <= SIZE - 4:
            self.events.append(('unsafe', offset))
            return -90
        if self.stores == self.fail_store:
            return -26
        self.put(offset, value ^ 1 if self.corrupt_store == offset else value)
        return 0

    def barrier(self, _context):
        self.barriers += 1
        self.events.append(('barrier',))
        return -27 if self.barriers == self.fail_barrier else 0

    def kick(self, _context):
        self.kicks += 1
        self.events.append(('kick', 0x20002))
        if self.kicks == self.fail_kick:
            return -28
        if self.on_kick:
            self.on_kick(self)
        if self.auto_stop_ack and self.inbound:
            self.put(self.inbound + 36, self.u32(self.inbound + 36) | 8
                     if self.u32(self.session.data + 36) & 1 else self.u32(self.inbound + 36) & ~8)
        return 0

    def now(self, _context, value):
        value[0] = max(0, self.clock - 100) if self.backward_clock else self.clock
        return 0

    def pause(self, _context, microseconds):
        self.events.append(('pause', microseconds))
        if microseconds != 1000:
            self.events.append(('unsafe-pause', microseconds))
            return -90
        if not self.freeze_clock:
            self.clock += 1
        if self.on_pause:
            self.on_pause(self)
        return -29 if self.fail_pause else 0

    def peer(self, state=2, features=1, restart=0, version=1, cached=False, names=None):
        names = [('slave-kernel', state)] if names is None else names
        item = bytearray(340)
        struct.pack_into('<5I', item, 0, 0x504d5324, version | features << 8,
                         1, 16 | len(names) << 16, restart)
        for index, (name, value) in enumerate(names):
            item[20 + index * 20:36 + index * 20] = name.encode().ljust(16, b'\0')
            struct.pack_into('<I', item, 36 + index * 20, value)
        self.inbound = self.append(435, item, cached=cached)
        return self.inbound

    def append(self, item_id, payload, cached=False):
        padded = (len(payload) + 7) & ~7
        if cached:
            end = self.u32(PART + 16)
            header = PART + end - 32
            data = header - padded
            self.put(PART + 16, data - PART)
        else:
            header = PART + self.u32(PART + 12)
            data = header + 16
        struct.pack_into('<HHIHHI', self.memory, header, 0xa5a5, item_id, padded,
                         padded - len(payload), 0, 0)
        self.memory[data:data + len(payload)] = payload
        self.memory[data + len(payload):data + padded] = bytes(padded - len(payload))
        if not cached:
            self.put(PART + 12, data + padded - PART)
        return data


class Smp2pTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        helper = cls.directory / 'size.c'
        helper.write_text('#include "wifi_smp2p.h"\nunsigned session_size(void){return sizeof(struct rf_wifi_smp2p_session);}\n')
        library = cls.directory / 'smp2p.so'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE), '-I', str(PORT), str(HERE / 'wifi_smp2p.c'), str(helper),
                        '-o', str(library)], check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        for name in ('prepare', 'auth_begin', 'alive', 'ipa_respond'):
            getattr(cls.library, 'rf_wifi_smp2p_' + name).argtypes = [C.POINTER(Session), C.POINTER(Ops)]
        for name in ('wait_ready', 'stop'):
            getattr(cls.library, 'rf_wifi_smp2p_' + name).argtypes = [C.POINTER(Session), C.POINTER(Ops), C.c_uint32]
        assert cls.library.session_size() == C.sizeof(Session)

    def call(self, model, name, timeout=None):
        args = [C.byref(model.session), C.byref(model.ops)]
        if timeout is not None:
            args.append(timeout)
        status = getattr(self.library, 'rf_wifi_smp2p_' + name)(*args)
        self.assertFalse(any(event[0].startswith('unsafe') for event in model.events))
        return status

    def prepared(self):
        model = Model()
        self.assertEqual(self.call(model, 'prepare'), 0)
        return model

    def armed(self):
        model = self.prepared()
        self.assertEqual(self.call(model, 'auth_begin'), 0)
        model.started = True
        model.reset_proven = False
        return model

    def ready(self, **peer):
        model = self.armed()
        model.peer(**peer)
        self.assertEqual(self.call(model, 'wait_ready', 10), 0)
        return model

    def test_native_ipa_query_publishes_only_the_owned_absent_vote_once_after_ready(self):
        model = self.ready(names=[('slave-kernel', 6), ('ipa', 1)])
        before = model.session.stores
        self.assertEqual(self.call(model, 'ipa_respond'), 0)
        self.assertEqual(model.u32(model.session.data + 56), 1)
        self.assertEqual(model.session.ipa_responses, 1)
        self.assertEqual(model.session.stores, before + 1)
        self.assertEqual(self.call(model, 'ipa_respond'), 0)
        self.assertEqual(model.session.stores, before + 1)
        model = self.ready(names=[('slave-kernel', 6), ('ipa', 0)])
        before = model.session.stores
        self.assertEqual(self.call(model, 'ipa_respond'), 0)
        self.assertEqual(model.session.stores, before)
        not_started = self.prepared()
        self.assertNotEqual(self.call(not_started, 'ipa_respond'), 0)

    def test_native_wlan_state_is_raw_validated_metadata_without_any_new_reply(self):
        model = self.ready()
        self.assertEqual((model.session.wlan_found, model.session.wlan_state), (0, 0))
        before = (model.session.stores, model.session.kicks)
        # Remote appends its native WLAN entry to this same fresh peer. Zero
        # is a valid state, distinct from the previous absence of the entry.
        model.put(model.inbound + 12, 16 | 2 << 16)
        model.memory[model.inbound + 40:model.inbound + 56] = b'wlan'.ljust(16, b'\0')
        for state in (0, 1, 2, 3, 0xffffffff):
            model.put(model.inbound + 56, state)
            self.assertEqual(self.call(model, 'alive'), 0)
            self.assertEqual((model.session.wlan_found, model.session.wlan_index, model.session.wlan_state), (1, 1, state))
            self.assertEqual((model.session.stores, model.session.kicks), before)
        model.memory[model.inbound + 40:model.inbound + 56] = b'changed'.ljust(16, b'\0')
        self.assertNotEqual(self.call(model, 'alive'), 0)
        self.assertEqual((model.session.stores, model.session.kicks), before)

    def test_prepare_appends_only_exact_outbound_and_publishes_version_last(self):
        model = Model()
        before = bytes(model.memory)
        self.assertEqual(self.call(model, 'prepare'), 0)
        session = model.session
        self.assertEqual((session.stage, session.partition, session.entry, session.data), (2, PART, PART + 32, PART + 48))
        self.assertEqual(model.u32(PART + 12), 32 + 16 + 344)
        expected = bytearray(344)
        struct.pack_into('<5I', expected, 0, 0x504d5324, 0x101, 0x10000, 0x20010, 0)
        expected[20:36] = b'master-kernel'.ljust(16, b'\0')
        expected[40:56] = b'ipa'.ljust(16, b'\0')
        self.assertEqual(model.memory[session.data:session.data + 344], expected)
        self.assertEqual(struct.unpack_from('<4I', model.memory, session.entry), (428 << 16 | 0xa5a5, 344, 4, 0))
        writes = [event for event in model.events if event[0] == 'write']
        self.assertEqual(len(writes), 92)
        self.assertEqual(writes[-2:], [('write', PART + 12, 392), ('write', session.data + 4, 0x101)])
        self.assertEqual(model.events[-2:], [('barrier',), ('kick', 0x20002)])
        self.assertEqual(sum(event[0] == 'unlock' for event in model.events), 1)
        self.assertFalse(model.locked)
        allowed = set(range(PART + 12, PART + 16)) | set(range(PART + 32, PART + 392))
        self.assertTrue(all(before[i] == value for i, value in enumerate(model.memory) if i not in allowed))

    def test_reset_stale_smem_existing_items_and_exhaustion_refuse_without_writes(self):
        cases = ['reset', 'inbound', 'outbound', 'glink', 'space', 'version', 'corrupt']
        for case in cases:
            model = Model()
            if case == 'reset':
                model.reset_proven = False
            elif case == 'inbound':
                model.peer()
            elif case == 'outbound':
                model.append(428, bytes(340))
            elif case == 'glink':
                model.append(478, bytes(32))
            elif case == 'space':
                model.put(PART + 16, 32 + 352)
            elif case == 'version':
                model.put(0x5c, 11 << 16)
            else:
                model.put(PART, 0)
            before = bytes(model.memory)
            with self.subTest(case=case):
                self.assertNotEqual(self.call(model, 'prepare'), 0)
                self.assertEqual(model.stores, 0)
                self.assertEqual(model.memory, before)
                self.assertFalse(model.locked)
                self.assertTrue(model.session.poisoned)

    def test_every_initial_store_failure_is_bounded_and_releases_owned_lock(self):
        for failure in range(1, 93):
            model = Model()
            model.fail_store = failure
            with self.subTest(store=failure):
                self.assertEqual(self.call(model, 'prepare'), 2)
                self.assertEqual(model.stores, failure)
                self.assertFalse(model.locked)
                self.assertTrue(model.session.poisoned)
                self.assertEqual(sum(event[0] == 'unlock' for event in model.events), 1)
                if failure <= 91:
                    self.assertEqual(model.u32(PART + 12), 32)
                self.assertEqual(self.call(model, 'prepare'), 6)

    def test_readback_barrier_kick_unlock_and_owner_failures_quarantine(self):
        for case in ('readback', 'barrier', 'kick', 'unlock', 'cancel', 'foreign-lock'):
            model = Model()
            if case == 'readback':
                model.corrupt_store = PART + 48
            elif case == 'barrier':
                model.fail_barrier = 1
            elif case == 'kick':
                model.fail_kick = 1
            elif case == 'unlock':
                model.fail_unlock = True
            elif case == 'cancel':
                model.cancel_at = 30
            else:
                model.on_check = lambda m: setattr(m, 'owner', 2) if m.checks == 30 else None
            with self.subTest(case=case):
                self.assertNotEqual(self.call(model, 'prepare'), 0)
                self.assertTrue(model.session.poisoned)
                self.assertEqual(sum(event[0] == 'unlock' for event in model.events), 1)
                if case == 'cancel':
                    self.assertFalse(model.locked)
                if case == 'foreign-lock':
                    self.assertEqual(model.owner, 2)

    def test_fresh_pas_gate_new_inbound_and_ready_are_required(self):
        model = self.prepared()
        self.assertEqual(self.call(model, 'wait_ready', 10), 6)
        model.peer()
        self.assertEqual(self.call(model, 'auth_begin'), 4)
        self.assertTrue(model.session.poisoned)
        model = self.prepared()
        self.assertEqual(self.call(model, 'auth_begin'), 0)
        model.peer()
        self.assertEqual(self.call(model, 'wait_ready', 10), 6)
        self.assertTrue(model.session.poisoned)
        model = self.armed()
        self.assertEqual(self.call(model, 'wait_ready', 3), 11)
        self.assertEqual((model.session.stage, model.session.poisoned), (5, 0))
        self.assertEqual(self.call(model, 'wait_ready', 3), 6)

    def test_fresh_uncached_and_cached_peer_support_ready_and_handover(self):
        for cached in (False, True):
            model = self.armed()
            model.peer(state=6, cached=cached)
            if cached:
                model.append(900, bytes(8), cached=True)
            with self.subTest(cached=cached):
                self.assertEqual(self.call(model, 'wait_ready', 10), 0)
                self.assertEqual((model.session.stage, model.session.handover, model.session.last_state), (4, 1, 6))
                self.assertEqual(model.session.peer, model.inbound)

    def test_peer_version_zero_waits_until_header_is_published(self):
        model = self.armed()
        model.peer(version=0)
        model.on_pause = lambda m: m.put(m.inbound + 4, 0x101)
        self.assertEqual(self.call(model, 'wait_ready', 10), 0)
        self.assertEqual(model.clock, 1)

    def test_feature_negotiation_and_initial_restart_ack_only_touch_our_words(self):
        for features, restart, expected_version, expected_flags in ((0, 0, 1, 0), (1, 1, 0x101, 2)):
            model = self.armed()
            model.peer(features=features, restart=restart)
            inbound_before = bytes(model.memory[model.inbound:model.inbound + 340])
            before = model.stores
            with self.subTest(features=features, restart=restart):
                self.assertEqual(self.call(model, 'wait_ready', 10), 0)
                writes = [event for event in model.events if event[0] == 'write'][before:]
                self.assertTrue(all(event[1] in (model.session.data + 4, model.session.data + 16) for event in writes))
                self.assertEqual((model.u32(model.session.data + 4), model.u32(model.session.data + 16)),
                                 (expected_version, expected_flags))
                self.assertEqual(model.memory[model.inbound:model.inbound + 340], inbound_before)

    def test_restart_after_ack_is_not_mistaken_for_ready_of_another_boot(self):
        model = self.armed()
        model.peer(restart=1)
        model.on_kick = lambda m: m.put(m.inbound + 16, 0)
        self.assertEqual(self.call(model, 'wait_ready', 10), 10)
        self.assertTrue(model.session.poisoned)

    def test_bad_peer_identity_names_duplicates_and_fatal_are_rejected(self):
        for offset, value, expected in ((0, 0, 8), (4, 0x102, 8), (8, 13, 8),
                                        (12, 17 | 1 << 16, 8), (12, 16 | 17 << 16, 8),
                                        (16, 4, 8), (36, 3, 9)):
            model = self.armed()
            model.peer()
            model.put(model.inbound + offset, value)
            with self.subTest(offset=offset):
                self.assertEqual(self.call(model, 'wait_ready', 10), expected)
                self.assertTrue(model.session.poisoned)
        model = self.armed()
        model.peer(names=[('slave-kernel', 2), ('slave-kernel', 2)])
        self.assertEqual(self.call(model, 'wait_ready', 10), 8)

    def test_owned_header_names_toc_and_value_corruption_prevent_future_writes(self):
        for kind, relative in [('header', -16), ('own', 20), ('own', 36), ('toc', 0), ('partition', 4)]:
            model = self.armed()
            model.peer()
            if kind == 'header':
                offset = model.session.data + relative
            elif kind == 'toc':
                offset = TOC + 32
            elif kind == 'partition':
                offset = PART + relative
            else:
                offset = model.session.data + relative
            model.put(offset, model.u32(offset) ^ 1)
            before = model.stores
            with self.subTest(kind=kind, relative=relative):
                self.assertNotEqual(self.call(model, 'wait_ready', 10), 0)
                self.assertEqual(model.stores, before)
                self.assertTrue(model.session.poisoned)

    def test_stop_requires_fresh_ack_and_clears_only_our_force_bit_after_ack(self):
        model = self.ready()
        before = model.stores
        self.assertEqual(self.call(model, 'stop', 10), 0)
        self.assertEqual(model.session.stage, 7)
        writes = [event for event in model.events if event[0] == 'write'][before:]
        self.assertEqual(writes, [('write', model.session.data + 36, 1), ('write', model.session.data + 36, 0)])
        self.assertEqual(model.u32(model.session.data + 36), 0)
        self.assertEqual(self.call(model, 'stop', 10), 6)
        stale = self.ready()
        stale.put(stale.inbound + 36, 10)
        before = stale.stores
        self.assertEqual(self.call(stale, 'stop', 10), 6)
        self.assertEqual(stale.stores, before)

    def test_missing_stop_ack_retains_force_bit_and_quarantines_without_retry(self):
        model = self.ready()
        model.auto_stop_ack = False
        self.assertEqual(self.call(model, 'stop', 3), 11)
        self.assertEqual((model.session.stage, model.session.poisoned), (8, 1))
        self.assertEqual(model.u32(model.session.data + 36), 1)
        count = model.stores
        self.assertEqual(self.call(model, 'stop', 3), 6)
        self.assertEqual(model.stores, count)

    def test_ready_timeout_still_permits_one_graceful_shutdown_attempt(self):
        model = self.armed()
        model.peer(state=0)
        self.assertEqual(self.call(model, 'wait_ready', 3), 11)
        self.assertEqual(self.call(model, 'stop', 3), 0)
        self.assertEqual(model.session.stage, 7)

    def test_cancelled_lease_prevents_stop_and_any_smem_write(self):
        model = self.ready()
        model.cancel_at = model.checks + 1
        before = model.stores, model.kicks
        self.assertEqual(self.call(model, 'stop', 3), 2)
        self.assertEqual((model.stores, model.kicks), before)
        self.assertTrue(model.session.poisoned)

    def test_timeout_remains_bounded_when_platform_clock_stalls(self):
        model = self.armed()
        model.freeze_clock = True
        self.assertEqual(self.call(model, 'wait_ready', 4), 11)
        self.assertEqual(sum(event[0] == 'pause' for event in model.events), 4)

    def test_kernel_overlay_contains_exact_native_allocator_and_state_machine(self):
        patch = (HERE / 'wifi-smp2p.patch').read_text()
        for source, target in [('wifi_smp2p.h', 'redfin_wifi_smp2p.h'),
                               ('wifi_smp2p.c', 'redfin_wifi_smp2p.c')]:
            section = patch.split('+++ b/bsd/dev/' + target + '\n', 1)[1]
            section = section.split('diff --git ', 1)[0]
            actual = ''.join(line[1:] for line in section.splitlines(keepends=True) if line.startswith('+'))
            expected = (HERE / source).read_text()
            expected = expected.replace('"wifi_smem.h"', '"../../iokit/bsddev/redfin_wifi_smem.h"')
            expected = expected.replace('"wifi_smp2p.h"', '"redfin_wifi_smp2p.h"')
            self.assertEqual(actual, expected)

    def test_arm64_and_cpp_compile_without_large_stack_arrays(self):
        compiler = shutil.which('c++')
        if compiler:
            subprocess.run([compiler, '-x', 'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(PORT), '-fsyntax-only', str(HERE / 'wifi_smp2p.c')], check=True, capture_output=True)
        clang = shutil.which('clang')
        if clang:
            output = self.directory / 'smp2p-arm64.o'
            subprocess.run([clang, '-target', 'aarch64-none-elf', '-ffreestanding', '-O2', '-std=c11',
                            '-Wall', '-Wextra', '-Werror', '-fstack-usage', '-I', str(PORT),
                            '-c', str(HERE / 'wifi_smp2p.c'), '-o', str(output)], check=True, capture_output=True)
            frames = [int(line.split('\t')[1]) for line in output.with_suffix('.su').read_text().splitlines()]
            self.assertTrue(frames)
            self.assertLess(max(frames), 2048)


class NativeWifiChainTests(unittest.TestCase):
    """Run real MDT/PAS orchestration + real AOP + real SMP2P in one model."""
    @classmethod
    def setUpClass(cls):
        import test_wifi_firmware as F
        import test_wifi_aop as A
        cls.F, cls.A = F, A
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / 'chain.c'
        source.write_text('#include "wifi_firmware.h"\n'
                          'static struct redfin_mpss_workspace workspace;\n'
                          'int start(struct redfin_mpss_session *s,const uint8_t *b,size_t n,'
                          'const struct redfin_mpss_range *r,size_t nr,const struct redfin_mpss_ops *o)'
                          '{return redfin_mpss_boot(s,b,n,r,nr,&workspace,o);}\n'
                          'int finish(struct redfin_mpss_session *s,const struct redfin_mpss_ops *o)'
                          '{return redfin_mpss_shutdown(s,o);}\n')
        library = directory / 'chain.so'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE), '-I', str(PORT), str(source), str(HERE / 'wifi_smp2p.c'),
                        str(PORT / 'wifi_aop.c'), '-o', str(library)], check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        for name in ('prepare', 'auth_begin'):
            getattr(cls.library, 'rf_wifi_smp2p_' + name).argtypes = [C.POINTER(Session), C.POINTER(Ops)]
        for name in ('wait_ready', 'stop'):
            getattr(cls.library, 'rf_wifi_smp2p_' + name).argtypes = [C.POINTER(Session), C.POINTER(Ops), C.c_uint32]
        cls.library.rf_wifi_aop_open.argtypes = [C.POINTER(A.Session), C.POINTER(A.Ops)]
        cls.library.rf_wifi_aop_load_state.argtypes = [C.POINTER(A.Session), C.POINTER(A.Ops), C.c_int]

        class Request(C.Structure):
            _fields_ = [('command', C.c_uint32), ('arginfo', C.c_uint32), ('argument', C.c_uint64 * 3)]
        ACQUIRE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(F.Plan))
        SWITCH = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int)
        COPY = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint64, C.c_void_p, C.c_uint32)
        ZERO = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint64, C.c_uint32)
        SYNC = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint64, C.c_uint64)
        SCM = C.CFUNCTYPE(C.c_int, C.c_void_p, C.POINTER(Request), C.POINTER(C.c_uint64))
        RELEASE = C.CFUNCTYPE(None, C.c_void_p, C.c_int)

        class FirmwareOps(C.Structure):
            _fields_ = [('context', C.c_void_p), ('sha256', F.SHA), ('acquire', ACQUIRE),
                        ('check', CHECK), ('aop', SWITCH), ('proxy', SWITCH), ('write', COPY),
                        ('zero', ZERO), ('sync', SYNC), ('scm', SCM), ('wait_ready', NUMBER),
                        ('stop', NUMBER), ('release', RELEASE)]
        cls.FirmwareOps = FirmwareOps
        cls.library.start.argtypes = [C.POINTER(F.Session), C.c_void_p, C.c_size_t,
                                     C.POINTER(F.Range), C.c_size_t, C.POINTER(FirmwareOps)]
        cls.library.finish.argtypes = [C.POINTER(F.Session), C.POINTER(FirmwareOps)]
        cls.callbacks = (ACQUIRE, CHECK, SWITCH, COPY, ZERO, SYNC, SCM, NUMBER, RELEASE)

    def driver(self):
        F, A, library = self.F, self.A, self.library
        m = Model()
        m.aop = A.Bus(opened=True)
        m.aop_session = A.Session()
        m.firmware_session = F.Session()
        m.pool = bytearray([0xa5]) * 0x40000
        m.acquired = m.proxy_on = m.quarantined = False
        m.chain_events = []
        m.bundle = C.create_string_buffer(F.bundle())
        m.excluded = (F.Range * len(F.EXCLUDED))(*(F.Range(*pair) for pair in F.EXCLUDED))

        def acquire(_context, _plan):
            m.chain_events.append(('acquire',))
            status = library.rf_wifi_aop_open(C.byref(m.aop_session), C.byref(m.aop.ops))
            if not status:
                status = library.rf_wifi_smp2p_prepare(C.byref(m.session), C.byref(m.ops))
            m.acquired = status == 0
            return status

        def check(_context):
            return 0 if m.acquired else -40

        def aop(_context, on):
            m.chain_events.append(('aop', on))
            return library.rf_wifi_aop_load_state(C.byref(m.aop_session), C.byref(m.aop.ops), on)

        def proxy(_context, on):
            m.chain_events.append(('proxy', on))
            m.proxy_on = bool(on)
            return 0

        def write(_context, physical, data, size):
            at = physical - F.BASE
            if at < 0 or at + size > len(m.pool):
                return -41
            m.pool[at:at + size] = C.string_at(data, size)
            return 0

        def zero(_context, physical, size):
            at = physical - F.BASE
            if at < 0 or at + size > len(m.pool):
                return -42
            m.pool[at:at + size] = bytes(size)
            return 0

        def sync(_context, _physical, _size):
            m.chain_events.append(('sync',))
            return 0

        def scm(_context, request, result):
            command = request.contents.command
            m.chain_events.append(('pas', command))
            if command == 1:
                if not m.proxy_on or m.aop_session.load_state != 1:
                    return -43
                metadata = F.firmware()[0]
                if m.pool[:len(metadata)] != metadata:
                    return -44
            if command == 5:
                status = library.rf_wifi_smp2p_auth_begin(C.byref(m.session), C.byref(m.ops))
                if status:
                    return status
                m.started = True
                m.reset_proven = False
                m.peer(state=6)
            if command == 6:
                if m.started and m.session.stage != 7:
                    return -45
                m.started = False
                m.reset_proven = True
            result[0] = 0
            return 0

        def ready(_context, timeout):
            m.chain_events.append(('ready',))
            return library.rf_wifi_smp2p_wait_ready(C.byref(m.session), C.byref(m.ops), timeout)

        def stop(_context, timeout):
            m.chain_events.append(('stop',))
            return library.rf_wifi_smp2p_stop(C.byref(m.session), C.byref(m.ops), timeout)

        def release(_context, quarantine):
            m.chain_events.append(('release', quarantine))
            m.quarantined = bool(quarantine)
            if not quarantine:
                m.acquired = False

        ACQUIRE, CHECK_TYPE, SWITCH, COPY, ZERO, SYNC, SCM, NUMBER_TYPE, RELEASE = self.callbacks
        m.firmware_callbacks = (ACQUIRE(acquire), CHECK_TYPE(check), SWITCH(aop), SWITCH(proxy),
                                COPY(write), ZERO(zero), SYNC(sync), SCM(scm), NUMBER_TYPE(ready),
                                NUMBER_TYPE(stop), RELEASE(release))
        m.firmware_ops = self.FirmwareOps(None, F.sha256, *m.firmware_callbacks)
        return m

    def start(self, m):
        return self.library.start(C.byref(m.firmware_session), m.bundle, len(self.F.bundle()),
                                  m.excluded, len(self.F.EXCLUDED), C.byref(m.firmware_ops))

    def test_complete_native_bundle_aop_smem_pas_ready_and_acknowledged_shutdown(self):
        m = self.driver()
        self.assertEqual(self.start(m), 0)
        self.assertEqual((m.firmware_session.ready, m.session.stage, m.aop_session.load_state), (1, 4, 1))
        self.assertEqual([event for event in m.chain_events if event[0] == 'pas'], [('pas', 1), ('pas', 2), ('pas', 5)])
        self.assertEqual(self.library.finish(C.byref(m.firmware_session), C.byref(m.firmware_ops)), 0)
        self.assertEqual(m.chain_events[-5:], [('stop',), ('pas', 6), ('proxy', 0), ('aop', 0), ('release', 0)])
        self.assertEqual((m.firmware_session.ready, m.session.stage, m.aop_session.load_state), (0, 7, 2))
        self.assertFalse(m.acquired or m.proxy_on or m.started or m.quarantined)
        self.assertEqual(m.aop.received, [
            b'{class: image, res: load_state, name: modem, val: on}'.ljust(64, b'\0'),
            b'{class: image, res: load_state, name: modem, val: off}'.ljust(64, b'\0')])

    def test_stop_ack_failure_prevents_pas_shutdown_power_or_aop_release(self):
        m = self.driver()
        self.assertEqual(self.start(m), 0)
        m.auto_stop_ack = False
        before = len(m.chain_events)
        self.assertEqual(self.library.finish(C.byref(m.firmware_session), C.byref(m.firmware_ops)), 11)
        self.assertEqual(m.chain_events[before:], [('stop',), ('release', 1)])
        self.assertTrue(m.proxy_on and m.started and m.acquired and m.quarantined)
        self.assertEqual(m.u32(m.session.data + 36), 1)

    def test_corrupt_bundle_never_enters_any_transport_or_allocator(self):
        m = self.driver()
        offset = len(self.F.bundle()) - 8
        m.bundle[offset] = bytes([m.bundle[offset][0] ^ 1])
        before = hashlib.sha256(m.memory).digest()
        self.assertEqual(self.start(m), 9)
        self.assertEqual(m.chain_events, [])
        self.assertEqual(m.aop.log, [])
        self.assertEqual((m.stores, m.kicks), (0, 0))
        self.assertEqual(hashlib.sha256(m.memory).digest(), before)


if __name__ == '__main__':
    unittest.main()
