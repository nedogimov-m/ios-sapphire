"""Exercise the real A620 planner, transfer boundary and HFI wire codec.

All fixture payload bytes are generated here. No vendor firmware is required
or embedded, and these tests perform no device I/O.
"""
import ctypes
import errno
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest


CHIP = 0x06020001
PREALLOCATIONS = [
    (0, 0x200, 1), (0x200, 0x200, 1), (0x400, 0x3C00, 1),
    (0x4000, 0x8000, 1), (0x10004000, 0x3FE0, 1),
    (0x10007FDC, 0x24, 1), (0x144000, 0x13000, 1),
    (0x157000, 0x9000, 1), (0x60000000, 0x1000, 7),
]
PAYLOADS = [
    (0, 0xC0), (0x200, 0x140), (0x400, 0x370C),
    (0x4000, 0x55D0), (0x157000, 0x398),
    (0x10004000, 0xEC0), (0x10007FDC, 0x18),
]
VERSIONS = (0x20010008, 0xFFFFFFFF, 0x20010008, 0, 0x20000001)


def metadata(address, requested, kind=1):
    return struct.pack('<4I', address, 0, kind, requested)


def data(address, payload):
    return struct.pack('<4I', address, len(payload), 0xEFBEADDE, 0xEFBEADDE) + payload


def firmware(preallocations=PREALLOCATIONS, payloads=PAYLOADS):
    result = b''.join(metadata(address, size, kind)
                      for address, size, kind in preallocations)
    for index, (address, size) in enumerate(payloads):
        payload = bytes((i * 37 + index * 13) & 255 for i in range(size))
        if address == 0x10007FDC and size == 0x18:
            payload = struct.pack('<6I', 0xFFFFFFFF, *VERSIONS)
        result += data(address, payload)
    return result


def replace_word(blob, offset, word):
    result = bytearray(blob)
    struct.pack_into('<I', result, offset, word)
    return bytes(result)


def payload_offsets(blob):
    result = []
    offset = 0
    while offset < len(blob):
        address, size, _, _ = struct.unpack_from('<4I', blob, offset)
        if size:
            result.append((offset, address, size))
        offset += 16 + size
    return result


class Region(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'address', 'requested_bytes', 'mapped_bytes', 'kind', 'permissions', 'persistent')]


class Payload(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'file_offset', 'address', 'bytes', 'region')]


class Plan(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'file_bytes', 'record_count', 'metadata_count', 'region_count',
        'payload_count', 'initialized_bytes', 'dma_bytes')]
    _fields_ += [('versions', ctypes.c_uint32 * 5), ('hfi_address', ctypes.c_uint32),
                 ('log_address', ctypes.c_uint32), ('regions', Region * 20),
                 ('payloads', Payload * 32)]


class Progress(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in ('attempted', 'completed', 'verified')]


class RingPlan(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'first_word', 'first_words', 'second_words', 'padding_words', 'next_write')]


HARNESS = r'''
#include <stdlib.h>
#include <string.h>
#include "redfin_gmu_firmware.h"

int host_plan(uint32_t chip, const void *p, size_t n, struct redfin_gmu_fw_plan *out)
{ return redfin_gmu_fw_plan_make(chip, p, n, out); }
size_t host_plan_size(void) { return sizeof(struct redfin_gmu_fw_plan); }
int host_hfi(void *p, size_t n, uint32_t address, uint32_t version)
{ return redfin_gmu_hfi_init(p, n, address, version); }
int host_ring(uint32_t read, uint32_t write, uint32_t words,
    struct redfin_gmu_hfi_write *out)
{ return redfin_gmu_hfi_write_plan(read, write, words, out); }
int host_header(uint32_t id, uint32_t words, uint32_t seq, uint32_t *out)
{ return redfin_gmu_hfi_command_header(id, words, seq, out); }
int host_tcm(const struct redfin_gmu_region *r, uint32_t offset, uint32_t n, uint32_t *out)
{ return redfin_gmu_tcm_mmio(r, offset, n, out); }
int host_started(uint32_t version, uint32_t result)
{ return redfin_gmu_started(version, result); }

struct host {
    struct redfin_gmu_fw_plan plan;
    uint8_t *memory[REDFIN_GMU_MAX_REGIONS];
    int deny, guard_fail, write_fail, publish_fail, verify_fail;
    unsigned preflights, guards, writes, publishes, verifies, bad;
};
static unsigned metrics[6];

static int preflight(void *argument, const struct redfin_gmu_fw_plan *p)
{
    struct host *h = argument;
    h->preflights++;
    if (memcmp(p, &h->plan, sizeof(*p))) h->bad++;
    return h->deny ? ENXIO : 0;
}
static int guard(void *argument)
{
    struct host *h = argument;
    h->guards++;
    return h->guard_fail == (int)h->guards ? ECANCELED : 0;
}
static int region_index(struct host *h, const struct redfin_gmu_region *r,
    uint32_t offset, uint32_t n)
{
    unsigned i;
    for (i=0; i<h->plan.region_count; i++) {
        if (!memcmp(r, &h->plan.regions[i], sizeof(*r)) && n &&
            offset < r->mapped_bytes && n <= r->mapped_bytes - offset) {
            if (r->kind == REDFIN_GMU_ITCM || r->kind == REDFIN_GMU_DTCM) {
                uint32_t mmio;
                if (redfin_gmu_tcm_mmio(r, offset, n, &mmio)) break;
                if (mmio < 0x3000 || (uint64_t)mmio+n > 0xb000) break;
            }
            return (int)i;
        }
    }
    h->bad++;
    return -1;
}
static int write_memory(void *argument, const struct redfin_gmu_region *r,
    uint32_t offset, const uint8_t *p, uint32_t n)
{
    struct host *h = argument;
    int i = region_index(h, r, offset, n);
    h->writes++;
    if (h->preflights != 1 || h->publishes || i<0) return EINVAL;
    if (h->write_fail == (int)h->writes) {
        memcpy(h->memory[i]+offset, p, n/2); /* An error may follow partial MMIO. */
        return EIO;
    }
    memcpy(h->memory[i]+offset, p, n);
    return 0;
}
static int publish(void *argument)
{
    struct host *h = argument;
    h->publishes++;
    if (h->writes != h->plan.payload_count) h->bad++;
    return h->publish_fail ? EIO : 0;
}
static int verify_memory(void *argument, const struct redfin_gmu_region *r,
    uint32_t offset, const uint8_t *p, uint32_t n)
{
    struct host *h = argument;
    int i = region_index(h, r, offset, n);
    h->verifies++;
    if (h->preflights != 1 || h->publishes != 1 || i<0) return EINVAL;
    if (h->verify_fail == (int)h->verifies) h->memory[i][offset] ^= 1;
    return memcmp(h->memory[i]+offset, p, n) ? EIO : 0;
}
int host_load(const void *image, size_t n, int deny, int guard_fail,
    int write_fail, int publish_fail, int verify_fail,
    struct redfin_gmu_load_progress *progress)
{
    struct host h = {0};
    unsigned i;
    int error;
    struct redfin_gmu_load_ops ops = {
        &h, preflight, guard, write_memory, publish, verify_memory
    };
    h.deny=deny; h.guard_fail=guard_fail; h.write_fail=write_fail;
    h.publish_fail=publish_fail; h.verify_fail=verify_fail;
    /* All host backing is allocated before the read-only preflight. */
    if (!redfin_gmu_fw_plan_make(REDFIN_GMU_CHIP_ID, image, n, &h.plan)) {
        for (i=0; i<h.plan.region_count; i++) {
            h.memory[i]=calloc(h.plan.regions[i].mapped_bytes, 1);
            if (!h.memory[i]) abort();
        }
    }
    error=redfin_gmu_fw_load(REDFIN_GMU_CHIP_ID, image, n, &ops, progress);
    metrics[0]=h.preflights; metrics[1]=h.guards; metrics[2]=h.writes;
    metrics[3]=h.publishes; metrics[4]=h.verifies; metrics[5]=h.bad;
    /* This host simulation has no hardware translation or DMA lifetime. */
    for (i=0; i<REDFIN_GMU_MAX_REGIONS; i++) free(h.memory[i]);
    return error;
}
unsigned host_metric(unsigned index) { return index<6 ? metrics[index] : 999; }
'''


class RedfinGMUFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        source = root / 'gmu.c'
        source.write_text(HARNESS)
        compiler = shutil.which('clang') or 'cc'
        cls.compile_args = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(Path(__file__).parent / 'include')]
        subprocess.run(cls.compile_args + ['-shared', '-fPIC', str(source),
                                          '-o', str(root / 'gmu.dylib')],
                       check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(root / 'gmu.dylib'))
        cls.lib.host_plan.argtypes = [ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(Plan)]
        cls.lib.host_plan_size.restype = ctypes.c_size_t
        cls.lib.host_hfi.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                     ctypes.c_uint32, ctypes.c_uint32]
        cls.lib.host_ring.argtypes = [ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_uint32, ctypes.POINTER(RingPlan)]
        cls.lib.host_tcm.argtypes = [ctypes.POINTER(Region), ctypes.c_uint32,
                                     ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        cls.lib.host_header.argtypes = [ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        cls.lib.host_started.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cls.lib.host_load.argtypes = [ctypes.c_void_p, ctypes.c_size_t] + \
            [ctypes.c_int] * 5 + [ctypes.POINTER(Progress)]
        cls.blob = firmware()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def plan(self, blob=None, chip=CHIP):
        blob = self.blob if blob is None else blob
        output = Plan()
        error = self.lib.host_plan(chip, blob, len(blob), ctypes.byref(output))
        return error, output

    def rejected(self, blob, expected=None, chip=CHIP):
        output = Plan()
        ctypes.memset(ctypes.byref(output), 0xA5, ctypes.sizeof(output))
        before = bytes(output)
        error = self.lib.host_plan(chip, blob, len(blob), ctypes.byref(output))
        if expected is None:
            self.assertNotEqual(error, 0)
        else:
            self.assertEqual(error, expected)
        self.assertEqual(bytes(output), before)

    def load(self, blob=None, deny=0, guard_fail=0, write_fail=0,
             publish_fail=0, verify_fail=0):
        blob = self.blob if blob is None else blob
        progress = Progress()
        error = self.lib.host_load(blob, len(blob), deny, guard_fail, write_fail,
                                   publish_fail, verify_fail, ctypes.byref(progress))
        metrics = tuple(self.lib.host_metric(i) for i in range(6))
        self.assertEqual(metrics[-1], 0)
        return error, tuple(getattr(progress, name) for name, _ in Progress._fields_), metrics

    def test_observed_a650_shape_is_planned_without_firmware_bytes(self):
        self.assertEqual(len(self.blob), 41548)
        self.assertEqual(ctypes.sizeof(Plan), self.lib.host_plan_size())
        error, plan = self.plan()
        self.assertEqual(error, 0)
        self.assertEqual((plan.record_count, plan.metadata_count, plan.payload_count,
                          plan.region_count), (16, 9, 7, 8))
        self.assertEqual(tuple(plan.versions), VERSIONS)
        self.assertEqual((plan.hfi_address, plan.log_address), (0x60001000, 0x60006000))
        self.assertEqual(plan.initialized_bytes, sum(n for _, n in PAYLOADS))
        self.assertEqual(plan.dma_bytes, 0x2B000)
        expected = [
            (0, 0x4000, 0), (0x10004000, 0x4000, 1), (0x4000, 0x8000, 2),
            (0x144000, 0x13000, 2), (0x157000, 0x9000, 2),
            (0x60000000, 0x1000, 3), (0x60001000, 0x5000, 4),
            (0x60006000, 0x1000, 5),
        ]
        self.assertEqual([(r.address, r.mapped_bytes, r.kind)
                          for r in plan.regions[:plan.region_count]], expected)
        self.assertEqual([r.persistent for r in plan.regions[:8]], [0]*5+[1, 0, 0])
        self.assertEqual(plan.regions[6].permissions, 3)
        self.assertEqual(plan.regions[7].permissions, 7)

    def test_all_truncations_are_rejected_before_any_plan_is_published(self):
        for size in range(len(self.blob)):
            self.rejected(self.blob[:size])

    def test_chip_and_null_contracts(self):
        for chip in (0, 0x06010001, 0x06020000, 0x06030500, 0x06050001):
            self.rejected(self.blob, errno.EINVAL, chip)
        self.assertEqual(self.lib.host_plan(CHIP, None, 100, ctypes.byref(Plan())), errno.EINVAL)
        self.assertEqual(self.lib.host_plan(CHIP, self.blob, len(self.blob), None), errno.EINVAL)
        self.rejected(self.blob + b'\0' * 0x40000, errno.EINVAL)

    def test_metadata_order_types_alignment_and_empty_request(self):
        self.rejected(replace_word(self.blob, 8, 8), errno.ENOTSUP)
        self.rejected(replace_word(self.blob, 12, 0), errno.EINVAL)
        self.rejected(replace_word(self.blob, 0, 1), errno.EINVAL)
        self.rejected(replace_word(self.blob, 12, 0x201), errno.EINVAL)
        self.rejected(self.blob + metadata(0x200000, 0x1000), errno.EINVAL)

    def test_non_tcm_prealloc_overlap_and_domain_boundaries(self):
        for index, address, size in ((7, 0x144000, 0x9000), (8, 0x7FFFF000, 0x2000),
                                     (8, 0x80000000, 0x1000), (8, 0xFFFFFFFC, 0x1000),
                                     (3, 0x1000, 0x4000), (3, 0x3FFF, 0x8000)):
            changed = replace_word(self.blob, index*16, address)
            self.rejected(replace_word(changed, index*16+12, size), errno.EINVAL)

    def test_payload_requires_its_requested_extent(self):
        headers = payload_offsets(self.blob)
        for index, address in ((3, 0xB000), (4, 0x160000), (6, 0x10007FF0),
                               (0, 0xFFFFFFFC), (0, 1), (1, 4)):
            self.rejected(replace_word(self.blob, headers[index][0], address), errno.EINVAL)
        self.rejected(replace_word(self.blob, headers[0][0]+4, 0xFFFFFFFC), errno.EINVAL)

    def test_page_padding_does_not_authorize_payload(self):
        requests = [(0x60000000, 0x1004, 7)]
        tuple_bytes = struct.pack('<6I', 0xFFFFFFFF, *VERSIONS)
        good = metadata(*requests[0]) + data(0x10007FDC, tuple_bytes)
        self.assertEqual(self.plan(good)[0], 0)
        self.rejected(good + data(0x60001000, b'\x55'*8), errno.EINVAL)

    def test_missing_or_unsupported_version_tuple(self):
        last, _, _ = payload_offsets(self.blob)[-1]
        self.rejected(self.blob[:last], errno.EINVAL)
        for version in (0, 0x10000001, 0x20010001, 0x30000001):
            self.rejected(replace_word(self.blob, len(self.blob)-4, version), errno.ENOTSUP)

    def test_record_region_and_dma_caps(self):
        extra = b''.join(metadata(0, 0, 2) for _ in range(65))
        self.rejected(extra + self.blob, errno.EINVAL)
        extra = b''.join(metadata(0x200000+i*0x1000, 0x1000) for i in range(15))
        self.rejected(extra + self.blob, errno.ENOSPC)
        self.rejected(metadata(0x200000, 0x100000) + self.blob, errno.EFBIG)

    def test_known_optional_metadata_and_opaque_data_header_words(self):
        extra = b''.join(metadata(0, kind, kind) for kind in range(2, 7))
        self.assertEqual(self.plan(extra+self.blob)[0], 0)
        first = payload_offsets(self.blob)[0][0]
        changed = replace_word(replace_word(self.blob, first+8, 0x12345678), first+12, 7)
        self.assertEqual(self.plan(changed)[0], 0)

    def test_single_bit_header_mutations_never_escape_the_declared_domains(self):
        headers = [i*16 for i in range(9)] + [h for h, _, _ in payload_offsets(self.blob)]
        for header in headers:
            for word in range(4):
                original = struct.unpack_from('<I', self.blob, header+word*4)[0]
                for bit in range(32):
                    error, plan = self.plan(replace_word(self.blob, header+word*4,
                                                          original ^ (1 << bit)))
                    if error:
                        continue
                    self.assertLessEqual(plan.dma_bytes, 0x100000)
                    for payload in plan.payloads[:plan.payload_count]:
                        region = plan.regions[payload.region]
                        self.assertGreaterEqual(payload.address, region.address)
                        self.assertLessEqual(payload.address+payload.bytes,
                                             region.address+region.requested_bytes)
                        self.assertLessEqual(payload.file_offset+payload.bytes, len(self.blob))

    def test_tcm_aperture_offsets_use_redfin_base(self):
        _, plan = self.plan()
        output = ctypes.c_uint32(0xA5A5A5A5)
        for index, offset, size, expected in ((0, 0, 4, 0x3000),
                                              (0, 0x3FFC, 4, 0x6FFC),
                                              (1, 0x3FE0, 20, 0xAFE0)):
            self.assertEqual(self.lib.host_tcm(ctypes.byref(plan.regions[index]), offset,
                                               size, ctypes.byref(output)), 0)
            self.assertEqual(output.value, expected)
        for index, offset, size in ((0, 0x4000, 4), (0, 0x3FFC, 8),
                                    (0, 1, 4), (1, 0, 0), (2, 0, 4)):
            self.assertEqual(self.lib.host_tcm(ctypes.byref(plan.regions[index]), offset,
                                               size, ctypes.byref(output)), errno.EINVAL)

    def test_native_start_result_version_boundary(self):
        for version in (0x20010004, 0x20010003):
            self.assertEqual(self.lib.host_started(version, 0xBABEFACE), 1)
            self.assertEqual(self.lib.host_started(version, 0x100), 0)
        for result, expected in ((0x100, 1), (0x80000100, 1), (0, 0), (0x101, 0),
                                  (0xE00, 0), (0xBABEFACE, 0)):
            self.assertEqual(self.lib.host_started(0x20010008, result), expected)

    def test_hfi_native_four_descriptor_layout_and_buffer_fences(self):
        backing = ctypes.create_string_buffer(b'\xA5' * (0x5000+32), 0x5000+32)
        start = ctypes.addressof(backing)+16
        self.assertEqual(self.lib.host_hfi(start, 0x5000, 0x60001000, 0x20000001), 0)
        raw = bytes(backing)
        self.assertEqual(raw[:16]+raw[-16:], b'\xA5'*32)
        self.assertEqual(struct.unpack_from('<6I', raw, 16), (0, 54, 6, 12, 4, 4))
        for index, priority in enumerate((10, 10, 40, 20)):
            header = struct.unpack_from('<12I', raw, 16+24+48*index)
            self.assertEqual(header, (int(index != 3), 0x60001000+0xE0+0x1000*index,
                                      index | priority << 8, 1024) + (0,)*8)
        self.assertEqual(raw[16+216:-16], b'\0'*(0x5000-216))

    def test_hfi_rejects_wrong_abi_size_or_iova_without_writing(self):
        for size, address, version in ((0x4000, 0x60001000, 0x20000001),
                                       (0x5000, 0x60001001, 0x20000001),
                                       (0x5000, 0x7FFFF000, 0x20000001),
                                       (0x5000, 0x60001000, 0x20010001),
                                       (0x5000, 0x4000, 0x20000001)):
            backing = ctypes.create_string_buffer(b'\xA5'*0x5000, 0x5000)
            before = bytes(backing)
            self.assertEqual(self.lib.host_hfi(backing, size, address, version), errno.EINVAL)
            self.assertEqual(bytes(backing), before)

    def test_hfi_ring_wrap_and_padding_capacity(self):
        for read, write, words, expected in (
                (0, 0, 2, (0, 2, 0, 2, 4)),
                (512, 1020, 7, (1020, 4, 3, 1, 4)),
                (0, 0, 255, (0, 255, 0, 1, 256))):
            output = RingPlan()
            self.assertEqual(self.lib.host_ring(read, write, words, ctypes.byref(output)), 0)
            self.assertEqual(tuple(getattr(output, name) for name, _ in RingPlan._fields_), expected)
        for read, write, words, error in ((0, 1020, 1, errno.ENOSPC),
                                          (0, 768, 255, errno.ENOSPC),
                                          (1024, 0, 2, errno.EINVAL),
                                          (0, 1, 2, errno.EINVAL),
                                          (0, 0, 256, errno.EINVAL),
                                          (0, 0, 0, errno.EINVAL)):
            output = RingPlan()
            ctypes.memset(ctypes.byref(output), 0xA5, ctypes.sizeof(output))
            before = bytes(output)
            self.assertEqual(self.lib.host_ring(read, write, words, ctypes.byref(output)), error)
            self.assertEqual(bytes(output), before)

    def test_hfi_command_header_rejects_wire_truncation(self):
        output = ctypes.c_uint32()
        self.assertEqual(self.lib.host_header(1, 2, 1, ctypes.byref(output)), 0)
        self.assertEqual(output.value, 0x00100201)
        for id_, words, sequence in ((256, 2, 1), (1, 256, 1), (1, 0, 1),
                                     (1, 2, 0), (1, 2, 4096)):
            self.assertEqual(self.lib.host_header(id_, words, sequence,
                                                  ctypes.byref(output)), errno.EINVAL)

    def test_load_copies_and_reads_back_every_payload_after_publication(self):
        self.assertEqual(self.load(), (0, (7, 7, 7), (1, 15, 7, 1, 7, 0)))

    def test_invalid_blob_or_refused_preflight_never_reaches_a_write(self):
        self.assertEqual(self.load(self.blob[:-4]),
                         (errno.EINVAL, (0, 0, 0), (0, 0, 0, 0, 0, 0)))
        self.assertEqual(self.load(deny=1),
                         (errno.ENXIO, (0, 0, 0), (1, 0, 0, 0, 0, 0)))

    def test_lost_guard_stops_before_the_next_write_or_read(self):
        for failed in range(1, 16):
            error, progress, metrics = self.load(guard_fail=failed)
            self.assertEqual(error, errno.ECANCELED)
            writes = min(failed-1, 7)
            verified = max(0, failed-9)
            self.assertEqual(progress, (writes, writes, verified))
            self.assertEqual(metrics, (1, failed, writes, int(failed > 8), verified, 0))

    def test_partial_write_publish_and_readback_errors_are_terminal(self):
        self.assertEqual(self.load(write_fail=3),
                         (errno.EIO, (3, 2, 0), (1, 3, 3, 0, 0, 0)))
        self.assertEqual(self.load(publish_fail=1),
                         (errno.EIO, (7, 7, 0), (1, 8, 7, 1, 0, 0)))
        self.assertEqual(self.load(verify_fail=3),
                         (errno.EIO, (7, 7, 2), (1, 11, 7, 1, 3, 0)))

    def test_random_noise_is_rejected_without_a_write(self):
        rng = random.Random(620)
        for _ in range(200):
            blob = rng.randbytes(rng.randrange(0, 1024))
            error, progress, metrics = self.load(blob)
            self.assertNotEqual(error, 0)
            self.assertEqual(progress, (0, 0, 0))
            self.assertEqual(metrics, (0, 0, 0, 0, 0, 0))


if __name__ == '__main__':
    unittest.main()
