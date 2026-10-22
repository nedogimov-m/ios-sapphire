"""Compile the actual native MPSS loader; exercise bounded files and PAS lifetime."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest

import wifi_firmware as F

HERE = Path(__file__).resolve().parent
BASE, REGION = 0x8c000000, 0x11800000
EXCLUDED = ((0x180000000, 0x80000000), (0xa0000000, 0x2300000), (0xb7e41000, 0x400000))


class Range(C.Structure):
    _fields_ = [('base', C.c_uint64), ('bytes', C.c_uint64)]


class Segment(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ('index', 'flags', 'source_address', 'file_bytes', 'memory_bytes')]
    _fields_ += [('physical_address', C.c_uint64)]


class Plan(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('metadata_bytes', 'phdrs', 'segments', 'alignment')]
    _fields_ += [(name, C.c_uint64) for name in
                ('source_base', 'physical_base', 'memory_bytes', 'entry_address', 'file_bytes', 'zero_bytes')]
    _fields_ += [('segment', Segment * 64)]


class Asset(C.Structure):
    _fields_ = [('data', C.c_void_p), ('index', C.c_uint32), ('bytes', C.c_uint32)]


class Image(C.Structure):
    _fields_ = [('bundle', C.c_void_p), ('bundle_bytes', C.c_size_t),
                ('assets', C.c_uint32), ('asset', Asset * 65)]


class Session(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('attempted', 'stage', 'failing_stage')]
    _fields_ += [('platform_error', C.c_int), ('shutdown_error', C.c_int)]
    _fields_ += [(name, C.c_uint32) for name in ('initialized', 'authenticated', 'ready', 'quarantined')]
    _fields_ += [('copied_bytes', C.c_uint64), ('zeroed_bytes', C.c_uint64)]


class Event(C.Structure):
    _fields_ = [('kind', C.c_uint32), ('arginfo', C.c_uint32),
                ('address', C.c_uint64), ('bytes', C.c_uint64), ('pas', C.c_uint64)]


SHA = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p, C.c_size_t, C.c_void_p)


@SHA
def sha256(_context, data, size, output):
    digest = hashlib.sha256(C.string_at(data, size)).digest()
    C.memmove(output, digest, 32)
    return 0


def firmware():
    blobs = {2: bytes((i * 7 + 3) % 256 for i in range(70003)),
             4: bytes((i * 13 + 91) % 256 for i in range(4097))}
    programs = [
        (0, 0, 0, 0, 52 + 5 * 32, 0, 7 << 24, 0),
        (0, 4096, BASE + REGION, BASE + REGION, 64, 4096, 2 << 24, 4096),
        (1, 16384, 0xc0000000, BASE, len(blobs[2]), 0x13000, 0x8000005, 0x100000),
        (1, 0x20000, 0xc0013000, BASE + 0x13000, 0, 0x1000, 0x8000006, 4096),
        (1, 0x21000, 0xc0014000, BASE + 0x14000, len(blobs[4]), 0x2000, 0x8000006, 4096),
    ]
    header = struct.pack('<16sHHIIIIIHHHHHH', b'\x7fELF\1\1\1' + bytes(9),
                         2, 164, 1, BASE, 52, 0, 0x67, 52, 32, len(programs), 0, 0, 0)
    metadata = header + b''.join(struct.pack('<8I', *program) for program in programs) + bytes(range(64))
    return metadata, blobs


def bundle(metadata=None, blobs=None, selections=None):
    default_metadata, default_blobs = firmware()
    metadata = default_metadata if metadata is None else bytes(metadata)
    blobs = default_blobs if blobs is None else blobs
    selections = [(0xffffffff, metadata)] + sorted(blobs.items()) if selections is None else selections
    at = 64 + 48 * len(selections)
    table, payload = bytearray(), bytearray()
    for index, data in selections:
        table.extend(struct.pack('<IIQ32s', index, len(data), at, hashlib.sha256(data).digest()))
        payload.extend(data)
        payload.extend(bytes(-len(data) % 8))
        at += (len(data) + 7) & ~7
    return struct.pack('<8s4I3Q16x', b'RFWIFI1\0', 1, len(selections), 48, 0, at, BASE, REGION) + table + payload


def fdt(changes=None, extra=(), header=()):
    changes = changes or {}
    props = {
        '/': {'compatible': b'google,redfin\0', '#address-cells': struct.pack('>I', 2),
              '#size-cells': struct.pack('>I', 2)},
        '/memory': {'device_type': b'memory\0', 'reg': struct.pack('>4Q', 0x80000000, 0x40000000,
                                                                 0x180000000, 0x100000000)},
        '/reserved-memory': {'#address-cells': struct.pack('>I', 2),
                             '#size-cells': struct.pack('>I', 2), 'ranges': b''},
        '/reserved-memory/modem_wlan_region@8c000000': {
            'reg': struct.pack('>QQ', BASE, REGION), 'no-map': b'', 'phandle': struct.pack('>I', 7)},
        '/reserved-memory/smem_region@80900000': {
            'reg': struct.pack('>QQ', F.SMEM_BASE, F.SMEM_BYTES), 'no-map': b''},
        '/reserved-memory/cont_splash_region': {'reg': struct.pack('>QQ', F.DISPLAY_BASE, F.DISPLAY_BYTES)},
        '/reserved-memory/ramoops': {'reg': struct.pack('>QQ', 0xb7e41000, 0x400000), 'no-map': b''},
        '/soc': {},
        '/soc/qcom,mss@4080000': {'compatible': b'qcom,pil-tz-generic\0',
                                'qcom,firmware-name': b'modem\0', 'qcom,pas-id': struct.pack('>I', 4),
                                'memory-region': struct.pack('>I', 7), 'qcom,signal-aop': b''},
    }
    for name, attributes in extra:
        props[name] = attributes
    for name, values in changes.items():
        props[name].update(values)
        props[name] = {key: value for key, value in props[name].items() if value is not None}
    strings, body = bytearray(), bytearray()

    def word(value):
        return struct.pack('>I', value)

    def node(path):
        name = (path.rsplit('/', 1)[-1] if path != '/' else '').encode() + b'\0'
        body.extend(word(1) + name + bytes(-len(name) % 4))
        for key, value in props[path].items():
            offset = len(strings)
            strings.extend(key.encode() + b'\0')
            body.extend(word(3) + word(len(value)) + word(offset) + value + bytes(-len(value) % 4))
        prefix = path.rstrip('/') + '/'
        for child in props:
            if child.startswith(prefix) and child != '/' and '/' not in child[len(prefix):]:
                node(child)
        body.extend(word(2))

    node('/')
    body.extend(word(9))
    reservations = b''.join(struct.pack('>QQ', *pair) for pair in header) + bytes(16)
    start = 40 + len(reservations)
    return struct.pack('>10I', 0xd00dfeed, start + len(body) + len(strings), start,
                       start + len(body), 40, 17, 16, 0, len(strings), len(body)) + reservations + body + strings


HARNESS = r'''
#include "wifi_firmware.h"
#include <string.h>
#define EVENT_MAX 512
struct event { uint32_t kind, arginfo; uint64_t address, bytes, pas; };
static struct event events[EVENT_MAX];
static uint32_t event_count, failing_event, failing_check, checks, pas_failure;
static uint8_t memory[0x40000];
static struct redfin_mpss_ops operations;
static struct redfin_mpss_workspace workspace;
static int record(uint32_t kind, uint64_t address, uint64_t bytes, uint32_t info, uint64_t pas) {
    if (event_count >= EVENT_MAX) return -91;
    events[event_count++] = (struct event){kind, info, address, bytes, pas};
    return event_count == failing_event ? -73 : 0;
}
static int acquire(void *c, const struct redfin_mpss_plan *p) {
    (void)c; return record(1, p->physical_base, p->memory_bytes, 0, 0);
}
static int check(void *c) { (void)c; ++checks; return failing_check && checks >= failing_check ? -74 : 0; }
static int aop(void *c, int on) { (void)c; return record(on ? 3 : 4, 0, 0, 0, 0); }
static int proxy(void *c, int on) { (void)c; return record(on ? 5 : 6, 0, 0, 0, 0); }
static int write_memory(void *c, uint64_t a, const uint8_t *p, uint32_t n) {
    (void)c; int error = record(7, a, n, 0, 0); if (error) return error;
    if (a < REDFIN_MPSS_BASE || a - REDFIN_MPSS_BASE > sizeof(memory) ||
        n > sizeof(memory) - (a - REDFIN_MPSS_BASE) || n > REDFIN_MPSS_COPY_CHUNK) return -92;
    memcpy(memory + (size_t)(a - REDFIN_MPSS_BASE), p, n); return 0;
}
static int zero_memory(void *c, uint64_t a, uint32_t n) {
    (void)c; int error = record(8, a, n, 0, 0); if (error) return error;
    if (a < REDFIN_MPSS_BASE || a - REDFIN_MPSS_BASE > sizeof(memory) ||
        n > sizeof(memory) - (a - REDFIN_MPSS_BASE) || n > REDFIN_MPSS_COPY_CHUNK) return -92;
    memset(memory + (size_t)(a - REDFIN_MPSS_BASE), 0, n); return 0;
}
static int sync_memory(void *c, uint64_t a, uint64_t n) { (void)c; return record(9, a, n, 0, 0); }
static int scm(void *c, const struct redfin_mpss_scm *r, uint64_t *result) {
    (void)c; *result = r->command == pas_failure ? 7 : 0;
    return record(100 + r->command, r->argument[1], r->argument[2], r->arginfo, r->argument[0]);
}
static int wait_ready(void *c, uint32_t timeout) { (void)c; return record(10, 0, timeout, 0, 0); }
static int stop(void *c, uint32_t timeout) { (void)c; return record(11, 0, timeout, 0, 0); }
static void release(void *c, int quarantine) { (void)c; (void)record(quarantine ? 13 : 12, 0, 0, 0, 0); }
int inspect(const uint8_t *p, size_t n, const struct redfin_mpss_range *r, size_t nr, struct redfin_mpss_plan *out) {
    return redfin_mpss_plan(p, n, r, nr, out, &workspace.scratch.plan);
}
int open_bundle(const uint8_t *p, size_t n, const struct redfin_mpss_range *r, size_t nr,
    redfin_mpss_sha256_fn hash, struct redfin_mpss_plan *plan, struct redfin_mpss_image *image) {
    return redfin_mpss_bundle_open(p, n, r, nr, hash, NULL, plan, image, &workspace.scratch);
}
void reset(redfin_mpss_sha256_fn hash, uint32_t fail, uint32_t owner_lost, uint32_t pas_bad) {
    memset(memory, 0xa5, sizeof(memory)); memset(events, 0, sizeof(events));
    memset(&workspace, 0, sizeof(workspace));
    event_count = 0; failing_event = fail; failing_check = owner_lost; checks = 0; pas_failure = pas_bad;
    operations = (struct redfin_mpss_ops){NULL, hash, acquire, check, aop, proxy,
        write_memory, zero_memory, sync_memory, scm, wait_ready, stop, release};
}
int boot(struct redfin_mpss_session *s, const uint8_t *p, size_t n,
    const struct redfin_mpss_range *r, size_t nr) { return redfin_mpss_boot(s, p, n, r, nr, &workspace, &operations); }
int shutdown_session(struct redfin_mpss_session *s) { return redfin_mpss_shutdown(s, &operations); }
const struct event *get_events(void) { return events; }
uint32_t get_event_count(void) { return event_count; }
uint32_t get_check_count(void) { return checks; }
uint32_t get_workspace_bytes(void) { return (uint32_t)sizeof(workspace); }
const uint8_t *get_memory(void) { return memory; }
void fail_at(uint32_t value) { failing_event = value; }
void lose_owner_at(uint32_t value) { failing_check = value; }
void bad_pas(uint32_t value) { pas_failure = value; }
'''


class NativeFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        source = cls.directory / 'harness.c'
        source.write_text(HARNESS)
        library = cls.directory / 'harness.so'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE), str(source), '-o', str(library)], check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        cls.library.inspect.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Range), C.c_size_t, C.POINTER(Plan)]
        cls.library.open_bundle.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(Range), C.c_size_t,
                                          SHA, C.POINTER(Plan), C.POINTER(Image)]
        cls.library.reset.argtypes = [SHA, C.c_uint32, C.c_uint32, C.c_uint32]
        cls.library.boot.argtypes = [C.POINTER(Session), C.c_void_p, C.c_size_t, C.POINTER(Range), C.c_size_t]
        cls.library.shutdown_session.argtypes = [C.POINTER(Session)]
        cls.library.get_events.restype = C.POINTER(Event)
        cls.library.get_memory.restype = C.POINTER(C.c_uint8)
        cls.planner = cls.directory / 'wifi-firmware-plan'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'wifi-firmware-plan.c'), '-o', str(cls.planner)], check=True, capture_output=True)

    def ranges(self, ranges=EXCLUDED):
        return (Range * len(ranges))(*(Range(*pair) for pair in ranges))

    def plan(self, metadata=None, excluded=EXCLUDED):
        metadata = firmware()[0] if metadata is None else bytes(metadata)
        buffer = C.create_string_buffer(metadata)
        result = Plan()
        C.memset(C.byref(result), 0xa5, C.sizeof(result))
        before = bytes(result)
        status = self.library.inspect(buffer, len(metadata), self.ranges(excluded), len(excluded), C.byref(result))
        self.assertEqual(buffer.raw[:-1], metadata)
        if status:
            self.assertEqual(bytes(result), before, 'rejection must not publish a partial plan')
        return status, result

    def open(self, data=None):
        data = bundle() if data is None else bytes(data)
        buffer = C.create_string_buffer(data)
        plan, image = Plan(), Image()
        C.memset(C.byref(plan), 0xa5, C.sizeof(plan))
        C.memset(C.byref(image), 0xa5, C.sizeof(image))
        before = bytes(plan), bytes(image)
        status = self.library.open_bundle(buffer, len(data), self.ranges(), len(EXCLUDED), sha256,
                                          C.byref(plan), C.byref(image))
        self.assertEqual(buffer.raw[:-1], data)
        if status:
            self.assertEqual((bytes(plan), bytes(image)), before)
        return status, plan, image, buffer

    def run_boot(self, data=None, fail=0, owner_lost=0, pas_bad=0):
        data = bundle() if data is None else bytes(data)
        buffer = C.create_string_buffer(data)
        session = Session()
        self.library.reset(sha256, fail, owner_lost, pas_bad)
        status = self.library.boot(C.byref(session), buffer, len(data), self.ranges(), len(EXCLUDED))
        return status, session, buffer

    def events(self):
        return [self.library.get_events()[i] for i in range(self.library.get_event_count())]

    def test_native_plan_preserves_zero_blob_and_original_phdr_indices(self):
        status, plan = self.plan()
        self.assertEqual(status, 0)
        self.assertEqual((plan.phdrs, plan.segments, plan.source_base, plan.physical_base,
                          plan.memory_bytes, plan.entry_address), (5, 3, BASE, BASE, 0x16000, BASE))
        self.assertEqual([plan.segment[i].index for i in range(plan.segments)], [2, 3, 4])
        self.assertEqual([plan.segment[i].file_bytes for i in range(plan.segments)], [70003, 0, 4097])
        self.assertEqual((plan.file_bytes, plan.zero_bytes), (74100, 0x16000 - 74100))

    def test_all_metadata_truncations_fail_without_publication(self):
        metadata, _ = firmware()
        for size in range(len(metadata)):
            with self.subTest(size=size):
                self.assertNotEqual(self.plan(metadata[:size])[0], 0)

    def test_elf_and_compact_metadata_invariants(self):
        metadata, _ = firmware()
        changes = [(0, b'FAIL'), (4, b'\2'), (5, b'\2'), (6, b'\0'),
                   (16, struct.pack('<H', 3)), (18, struct.pack('<H', 183)),
                   (20, struct.pack('<I', 0)), (28, struct.pack('<I', 53)),
                   (40, struct.pack('<H', 64)), (42, struct.pack('<H', 56)),
                   (44, struct.pack('<H', 0)), (44, struct.pack('<H', 65)),
                   (52, struct.pack('<I', 1)), (56, struct.pack('<I', 1)),
                   (68, struct.pack('<I', 1)), (72, struct.pack('<I', 1)),
                   (84, struct.pack('<I', 1)), (100, struct.pack('<I', 0)),
                   (108, struct.pack('<I', 0)), (108, struct.pack('<I', 7 << 24))]
        for offset, value in changes:
            with self.subTest(offset=offset, value=value):
                bad = bytearray(metadata)
                bad[offset:offset + len(value)] = value
                self.assertNotEqual(self.plan(bad)[0], 0)
        self.assertNotEqual(self.plan(metadata + b'\0')[0], 0)

    def test_segment_range_overlap_alignment_entry_and_nonrelocatable_refused(self):
        metadata, _ = firmware()
        ph = 52 + 2 * 32
        cases = [(ph, 0), (ph + 12, 0), (ph + 16, 0xffffffff), (ph + 20, 0),
                 (ph + 20, 0xffffffff), (ph + 24, 5), (ph + 28, 3),
                 (52 + 3 * 32 + 12, BASE + 4096), (24, BASE + 0x13000),
                 (24, 0xffffffff), (52 + 4 * 32 + 12, BASE + REGION)]
        for offset, value in cases:
            with self.subTest(offset=offset, value=value):
                bad = bytearray(metadata)
                struct.pack_into('<I', bad, offset, value)
                self.assertNotEqual(self.plan(bad)[0], 0)

    def test_forbidden_ranges_include_full_carveout_and_validate_arithmetic(self):
        for excluded in ((), EXCLUDED[:1], ((0, 0), EXCLUDED[1]),
                         ((0xfffffffffffffff0, 32), EXCLUDED[1]),
                         EXCLUDED + ((BASE + REGION - 1, 1),),
                         EXCLUDED + ((BASE - 1, 2),), EXCLUDED + ((BASE, REGION),)):
            with self.subTest(excluded=excluded):
                self.assertNotEqual(self.plan(excluded=excluded)[0], 0)
        self.assertEqual(self.plan(excluded=EXCLUDED + ((BASE + REGION, 4096),))[0], 0)

    def test_integrity_checked_bundle_has_exact_assets(self):
        status, plan, image, _ = self.open()
        self.assertEqual(status, 0)
        self.assertEqual(plan.segments, 3)
        self.assertEqual(image.assets, 3)
        self.assertEqual([image.asset[i].index for i in range(image.assets)], [0xffffffff, 2, 4])
        for i in range(image.assets):
            data = C.string_at(image.asset[i].data, image.asset[i].bytes)
            self.assertEqual(data, firmware()[0] if i == 0 else firmware()[1][image.asset[i].index])

    def test_bundle_header_alias_padding_and_extra_bytes_refused(self):
        valid = bundle()
        edits = [(0, b'WRONG'), (8, struct.pack('<I', 2)), (12, struct.pack('<I', 66)),
                 (16, struct.pack('<I', 47)), (20, struct.pack('<I', 1)),
                 (24, struct.pack('<Q', len(valid) + 1)), (32, struct.pack('<Q', 0xe0000000)),
                 (40, struct.pack('<Q', REGION - 1)), (48, b'\1'),
                 (64, struct.pack('<I', 0)), (68, struct.pack('<I', 0)),
                 (72, struct.pack('<Q', 64)), (64 + 48, struct.pack('<I', 4)),
                 (64 + 96, struct.pack('<I', 2)), (64 + 96 + 8, struct.pack('<Q', 1 << 63))]
        for offset, value in edits:
            with self.subTest(offset=offset, value=value):
                bad = bytearray(valid)
                bad[offset:offset + len(value)] = value
                self.assertNotEqual(self.open(bad)[0], 0)
        for data in (valid + b'\0', valid[:-1], valid[:100]):
            self.assertNotEqual(self.open(data)[0], 0)
        bad = bytearray(valid)
        metadata, _ = firmware()
        bad[64 + 3 * 48 + len(metadata)] = 1
        self.assertEqual(self.open(bad)[0], 8)

    def test_hash_corruption_or_asset_mismatch_precedes_all_platform_operations(self):
        valid = bytearray(bundle())
        valid[-8] ^= 1
        status, session, _ = self.run_boot(valid)
        self.assertEqual((status, session.failing_stage, self.library.get_event_count()), (9, 1, 0))
        metadata, blobs = firmware()
        for selections in ([(0xffffffff, metadata), (2, blobs[2])],
                           [(0xffffffff, metadata), (2, blobs[2]), (3, b'extra'), (4, blobs[4])],
                           [(0xffffffff, metadata), (2, blobs[2][:-1]), (4, blobs[4])]):
            self.assertEqual(self.open(bundle(selections=selections))[0], 10)

    def test_real_loader_copies_bss_and_scm_arguments_then_retains_ready_lease(self):
        status, session, _ = self.run_boot()
        self.assertEqual((status, session.stage, session.ready, session.quarantined), (0, 9, 1, 0))
        self.assertEqual((session.copied_bytes, session.zeroed_bytes), (74100, 0x16000 - 74100))
        events = self.events()
        self.assertEqual([event.kind for event in events],
                         [1, 3, 5, 7, 9, 101, 102, 7, 7, 8, 8, 7, 8, 9, 105, 10])
        scm_events = [event for event in events if event.kind >= 100]
        self.assertEqual([(event.kind, event.arginfo, event.address, event.bytes, event.pas)
                          for event in scm_events],
                         [(101, 0x82, BASE, 0, 4), (102, 3, BASE, 0x16000, 4), (105, 1, 0, 0, 4)])
        memory = C.string_at(self.library.get_memory(), 0x40000)
        _, blobs = firmware()
        self.assertEqual(memory[:len(blobs[2])], blobs[2])
        self.assertEqual(memory[len(blobs[2]):0x14000], bytes(0x14000 - len(blobs[2])))
        self.assertEqual(memory[0x14000:0x14000 + len(blobs[4])], blobs[4])
        self.assertEqual(memory[0x14000 + len(blobs[4]):0x16000], bytes(0x2000 - len(blobs[4])))
        self.assertEqual(memory[0x16000:], bytes([0xa5]) * (0x40000 - 0x16000))
        self.assertTrue(all(event.bytes <= 65536 for event in events if event.kind in (7, 8)))
        self.assertEqual(self.library.shutdown_session(C.byref(session)), 0)
        self.assertEqual([event.kind for event in self.events()][-5:], [11, 106, 6, 4, 12])
        self.assertEqual((session.stage, session.ready, session.initialized, session.authenticated), (10, 0, 0, 0))

    def test_attempt_once_and_no_double_shutdown(self):
        _, session, buffer = self.run_boot()
        previous = self.library.get_event_count()
        self.assertEqual(self.library.boot(C.byref(session), buffer, len(bundle()), self.ranges(),
                                           len(EXCLUDED)), 12)
        self.assertEqual(self.library.get_event_count(), previous)
        self.assertEqual(self.library.shutdown_session(C.byref(session)), 0)
        previous = self.library.get_event_count()
        self.assertEqual(self.library.shutdown_session(C.byref(session)), 12)
        self.assertEqual(self.library.get_event_count(), previous)

    def test_every_platform_failure_stops_before_later_start_stages(self):
        _, _, _ = self.run_boot()
        count = self.library.get_event_count()
        for failure in range(1, count + 1):
            with self.subTest(event=failure):
                status, session, _ = self.run_boot(fail=failure)
                self.assertEqual(status, 11)
                self.assertEqual(session.platform_error, -73)
                events = [event.kind for event in self.events()]
                self.assertEqual(events[:failure], [1, 3, 5, 7, 9, 101, 102, 7, 7, 8, 8, 7, 8, 9, 105, 10][:failure])
                if failure < 15:
                    self.assertNotIn(105, events)
                if failure > 1:
                    self.assertEqual(events[-1], 12)
                self.assertFalse(session.ready)

    def test_ownership_loss_prohibits_cleanup_writes_and_quarantines(self):
        self.run_boot()
        count = self.library.get_check_count()
        for failure in range(1, count + 1):
            with self.subTest(check=failure):
                status, session, _ = self.run_boot(owner_lost=failure)
                self.assertEqual(status, 11)
                self.assertFalse(session.ready)
                self.assertEqual((session.stage, session.quarantined), (11, 1))
                self.assertEqual([event.kind for event in self.events()][-1], 13)

    def test_stop_or_pas_shutdown_failure_keeps_power_and_aop_quarantined(self):
        for failure in ('stop', 'shutdown', 'proxy', 'aop'):
            with self.subTest(failure=failure):
                _, session, _ = self.run_boot()
                before = self.library.get_event_count()
                self.library.fail_at(before + {'stop': 1, 'shutdown': 2, 'proxy': 3, 'aop': 4}[failure])
                self.assertEqual(self.library.shutdown_session(C.byref(session)), 11)
                new = [event.kind for event in self.events()][before:]
                self.assertEqual(new[-1], 13)
                self.assertEqual((session.stage, session.quarantined, session.shutdown_error), (11, 1, -73))
                if failure == 'stop':
                    self.assertEqual(new, [11, 13])
                if failure == 'shutdown':
                    self.assertEqual(new, [11, 106, 13])

    def test_nonzero_pas_result_is_not_transport_success(self):
        for command in (1, 2, 5):
            with self.subTest(command=command):
                status, session, _ = self.run_boot(pas_bad=command)
                self.assertEqual(status, 11)
                self.assertFalse(session.ready)
                self.assertEqual(session.platform_error, -1)
                kinds = [event.kind for event in self.events()]
                self.assertIn(106, kinds)
                if command == 5:
                    self.assertLess(kinds.index(11), kinds.index(106))

    def test_cpp_and_freestanding_arm64_compile_actual_loader(self):
        source = self.directory / 'compile.c'
        source.write_text('#include "wifi_firmware.h"\nstatic struct redfin_mpss_workspace workspace;\n'
                          'int run(struct redfin_mpss_session *s, const unsigned char *b, unsigned long n, '
                          'const struct redfin_mpss_range *r, const struct redfin_mpss_ops *o) '
                          '{ return redfin_mpss_boot(s,b,n,r,2,&workspace,o); }\n')
        cpp = shutil.which('c++')
        if cpp:
            subprocess.run([cpp, '-x', 'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(HERE), '-fsyntax-only', str(source)], check=True, capture_output=True)
        clang = shutil.which('clang')
        if clang:
            subprocess.run([clang, '-target', 'aarch64-none-elf', '-ffreestanding', '-O2', '-std=c11',
                            '-Wall', '-Wextra', '-Werror', '-fstack-usage', '-I', str(HERE), '-c', str(source),
                            '-o', str(self.directory / 'native-arm64.o')], check=True, capture_output=True)
            frames = [int(line.split('\t')[1]) for line in
                      (self.directory / 'native-arm64.su').read_text().splitlines()]
            self.assertTrue(frames)
            self.assertLess(sum(frames), 1024, 'large scratch must remain outside the kernel stack')
        self.assertEqual(self.library.get_workspace_bytes(), 2 * (C.sizeof(Plan) + C.sizeof(Image)))

    def test_kernel_overlay_embeds_actual_compiled_header_and_sha_adapter(self):
        patch = (HERE / 'wifi-firmware.patch').read_text()
        for source, destination in [('wifi_firmware.h', 'redfin_wifi_firmware.h'),
                                    ('wifi-firmware-sha256.cpp', 'RedfinWiFiFirmware.cpp')]:
            section = patch.split('+++ b/iokit/Kernel/arm/' + destination + '\n', 1)[1]
            section = section.split('diff --git ', 1)[0]
            actual = ''.join(line[1:] for line in section.splitlines(keepends=True)
                             if line.startswith('+'))
            self.assertEqual(actual, (HERE / source).read_text())

    def test_host_cli_plans_actual_c_and_refuses_special_files_symlinks_and_overlap(self):
        root = Path(tempfile.mkdtemp(dir=self.directory))
        metadata = root / 'modem.mdt'
        metadata.write_bytes(firmware()[0])
        command = [str(self.planner), str(metadata)] + [hex(value) for pair in EXCLUDED for value in pair]
        result = subprocess.run(command, capture_output=True, check=True)
        plan = json.loads(result.stdout)
        self.assertEqual([item['index'] for item in plan['segments']], [2, 3, 4])
        for path in (root / 'link', root / 'fifo', root):
            if path.name == 'link':
                path.symlink_to(metadata)
            if path.name == 'fifo':
                os.mkfifo(path)
            bad = command.copy()
            bad[1] = str(path)
            self.assertNotEqual(subprocess.run(bad, capture_output=True, timeout=3).returncode, 0)
        self.assertNotEqual(subprocess.run(command + [hex(BASE), '1'], capture_output=True).returncode, 0)


class HostBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.planner = cls.directory / 'wifi-firmware-plan'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'wifi-firmware-plan.c'), '-o', str(cls.planner)], check=True, capture_output=True)

    def assets(self):
        root = Path(tempfile.mkdtemp(dir=self.directory))
        metadata, blobs = firmware()
        files = [('modem.mdt', metadata, None)] + [(f'modem.b{index:02d}', data, index)
                                                  for index, data in sorted(blobs.items())]
        records = []
        for name, data, index in files:
            (root / name).write_bytes(data)
            records.append({'name': name, 'bytes': len(data), 'phdr_index': index,
                            'sha256': hashlib.sha256(data).hexdigest()})
        inventory = {'image_sha256': 'ab' * 32, 'image_bytes': 128 * 1024 * 1024,
                     'initial_boot': {'prefix': 'modem', 'pas_id': 4, 'required_files': records}}
        (root / 'inventory.json').write_text(json.dumps(inventory))
        (root / 'live.dtb').write_bytes(fdt())
        return root, inventory

    def prepare(self, root):
        return F.prepare(root / 'inventory.json', root, root / 'live.dtb', self.planner,
                         0x180000000, 0x80000000)

    def test_live_fdt_binds_modem_smem_display_and_preserves_recovery_exclusions(self):
        excluded = F.live_layout(fdt(), 0x180000000, 0x80000000)
        self.assertEqual(excluded[:2], [(0x180000000, 0x80000000), (0xa0000000, 0x2300000)])
        self.assertIn((0xb7e41000, 0x400000), excluded)
        self.assertIn((F.SMEM_BASE, F.SMEM_BYTES), excluded)
        self.assertNotIn((BASE, REGION), excluded)
        mutations = [
            {'/soc/qcom,mss@4080000': {'compatible': b'qcom,wpss-pil\0'}},
            {'/soc/qcom,mss@4080000': {'qcom,pas-id': struct.pack('>I', 6)}},
            {'/soc/qcom,mss@4080000': {'qcom,firmware-name': b'wpss\0'}},
            {'/soc/qcom,mss@4080000': {'qcom,signal-aop': None}},
            {'/soc/qcom,mss@4080000': {'memory-region': struct.pack('>2I', 7, 7)}},
            {'/soc/qcom,mss@4080000': {'status': b'disabled\0'}},
            {'/reserved-memory/modem_wlan_region@8c000000': {'no-map': None}},
            {'/reserved-memory/modem_wlan_region@8c000000': {'reusable': b''}},
            {'/reserved-memory/modem_wlan_region@8c000000': {'reg': struct.pack('>QQ', BASE, REGION - 4096)}},
            {'/reserved-memory/smem_region@80900000': {'no-map': None}},
            {'/reserved-memory/cont_splash_region': {'reg': struct.pack('>QQ', 0x9c000000, 0x2300000)}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                F.live_layout(fdt(mutation), 0x180000000, 0x80000000)

    def test_duplicate_phandles_and_modem_alias_reservations_fail(self):
        for extra in ((('/soc/duplicate', {'phandle': struct.pack('>I', 7)}),),
                      (('/reserved-memory/alias', {'reg': struct.pack('>QQ', BASE, REGION)}),)):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                F.live_layout(fdt(extra=extra), 0x180000000, 0x80000000)
        with self.assertRaises(ValueError):
            F.live_layout(fdt(header=((BASE, 4096),)), 0x180000000, 0x80000000)

    def test_host_pipeline_matches_native_bundle_and_publishes_private_no_overwrite(self):
        root, _ = self.assets()
        report, selections = self.prepare(root)
        output = root / 'private.bundle'
        F.write_bundle(output, root, report, selections)
        self.assertEqual(output.read_bytes(), bundle())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            F.write_bundle(output, root, report, selections)
        self.assertEqual(output.read_bytes(), bundle())
        self.assertFalse(list(root.glob('.redfin-wifi-*')))

    def test_bad_manifest_hash_original_index_and_extra_blobs_fail(self):
        for kind in ('hash', 'index', 'length', 'extra', 'traversal', 'pas', 'source'):
            root, inventory = self.assets()
            record = inventory['initial_boot']['required_files'][1]
            if kind == 'hash':
                record['sha256'] = '00' * 32
            elif kind == 'index':
                record['phdr_index'] = 3
            elif kind == 'length':
                record['bytes'] += 1
            elif kind == 'extra':
                inventory['initial_boot']['required_files'].append(
                    {'name': 'modem.b03', 'bytes': 4, 'phdr_index': 3, 'sha256': '00' * 32})
            elif kind == 'traversal':
                record['name'] = '../modem.b02'
            elif kind == 'pas':
                inventory['initial_boot']['pas_id'] = 6
            else:
                inventory['image_sha256'] = ''
            (root / 'inventory.json').write_text(json.dumps(inventory))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.prepare(root)

    def test_changed_asset_before_output_aborts_without_partial_publication(self):
        root, _ = self.assets()
        report, selections = self.prepare(root)
        asset = root / 'modem.b04'
        data = bytearray(asset.read_bytes())
        data[0] ^= 1
        asset.write_bytes(data)
        output = root / 'private.bundle'
        with self.assertRaisesRegex(ValueError, 'changed during'):
            F.write_bundle(output, root, report, selections)
        self.assertFalse(output.exists())
        self.assertFalse(list(root.glob('.redfin-wifi-*')))

    def test_symlink_fifo_directory_and_source_replacement_refused(self):
        for kind in ('symlink', 'fifo', 'directory'):
            root, _ = self.assets()
            asset = root / 'modem.b04'
            asset.unlink()
            if kind == 'symlink':
                asset.symlink_to(root / 'modem.b02')
            elif kind == 'fifo':
                os.mkfifo(asset)
            else:
                asset.mkdir()
            with self.subTest(kind=kind), self.assertRaises((OSError, ValueError)):
                self.prepare(root)


if __name__ == '__main__':
    unittest.main()
