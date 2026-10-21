"""Compile the actual raw-read patch with host DMA/uio stubs, without hardware."""
import ctypes
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BLOCK, BOUNCE, FIRST, BANKS = 4096, 3 * 4096, 37, 32


def patched_function():
    patch = Path(__file__).with_name("ufs-raw-read.patch").read_text()
    additions = "\n".join(line[1:] for line in patch.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
    start = additions.index("static int\nredfin_ufs_raw_read(")
    opening = additions.index("{", start)
    depth = 0
    for index in range(opening, len(additions)):
        depth += (additions[index] == "{") - (additions[index] == "}")
        if depth == 0:
            return additions[start:index + 1]
    raise ValueError("raw-read helper is truncated in the patch")


HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#define UFS_BLOCK 4096U
#define BOUNCE_SIZE (3U * UFS_BLOCK)
#define DMA_BOUNCE 128U
#define MIN(a,b) ((a) < (b) ? (a) : (b))
struct uio { int64_t offset, resid, moved, capacity, fault_after; unsigned char *dest; };
struct result {
    int64_t offset, resid, moved;
    int reads, uiomoves, locks, unlocks, depth, invalid;
    uint64_t lbas[16]; uint32_t blocks[16];
};
static struct { int ready; uint64_t nblocks, first_block; uintptr_t dma; } su;
static int redfin_ufs_root_read_only, sweet_ufs_lock, dma_failure;
static unsigned char dma[DMA_BOUNCE + BOUNCE_SIZE + 32];
static struct result result;
static int64_t uio_offset(struct uio *uio) { return uio->offset; }
static int64_t uio_resid(struct uio *uio) { return uio->resid; }
static void lck_mtx_lock(int *lock) {
    (void)lock; if (result.depth) result.invalid++;
    result.depth++; result.locks++;
}
static void lck_mtx_unlock(int *lock) {
    (void)lock; if (result.depth != 1) result.invalid++;
    result.depth--; result.unlocks++;
}
static unsigned char pattern(uint64_t position) {
    return (unsigned char)((position * 17) ^ (position >> 8) ^ (position >> 16) ^ 0x5a);
}
static int ufs_read_blocks(uint64_t lba, uint32_t blocks) {
    int call = result.reads++;
    if (result.depth != 1) result.invalid++;
    if (call < 16) { result.lbas[call] = lba; result.blocks[call] = blocks; }
    if (dma_failure && result.reads == dma_failure) return EIO;
    if (!blocks || blocks > BOUNCE_SIZE / UFS_BLOCK || lba < su.first_block ||
        lba >= su.first_block + su.nblocks || blocks > su.first_block + su.nblocks - lba) {
        result.invalid++; return EIO;
    }
    for (uint32_t index = 0; index < blocks * UFS_BLOCK; index++)
        dma[DMA_BOUNCE + index] = pattern(lba * UFS_BLOCK + index);
    return 0;
}
static int uiomove(const char *source, int count, struct uio *uio) {
    result.uiomoves++;
    if (result.depth != 1 || count < 0 || count > uio->resid ||
        count > uio->capacity - uio->moved) { result.invalid++; return EFAULT; }
    int copied = count, error = 0;
    if (uio->fault_after >= 0 && uio->moved + copied > uio->fault_after) {
        copied = (int)(uio->fault_after - uio->moved); error = EFAULT;
    }
    memcpy(uio->dest + uio->moved, source, (size_t)copied);
    uio->moved += copied; uio->offset += copied; uio->resid -= copied;
    return error;
}
ACTUAL_FUNCTION
int host_read(int64_t offset, int64_t resid, uint64_t banks, uint64_t first,
              int ready, int gate, int fail_dma, int64_t fault_after,
              unsigned char *output, int64_t capacity, struct result *out) {
    memset(&result, 0, sizeof(result)); memset(dma, 0xa5, sizeof(dma));
    su.ready = ready; su.nblocks = banks; su.first_block = first; su.dma = (uintptr_t)dma;
    redfin_ufs_root_read_only = gate; dma_failure = fail_dma;
    struct uio uio = {offset, resid, 0, capacity, fault_after, output};
    int error = redfin_ufs_raw_read(&uio);
    for (unsigned index = 0; index < DMA_BOUNCE; index++)
        if (dma[index] != 0xa5) result.invalid++;
    for (unsigned index = DMA_BOUNCE + BOUNCE_SIZE; index < sizeof(dma); index++)
        if (dma[index] != 0xa5) result.invalid++;
    result.offset = uio.offset; result.resid = uio.resid; result.moved = uio.moved;
    *out = result; return error;
}
'''


class Result(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("offset", "resid", "moved")] + [
        (name, ctypes.c_int) for name in ("reads", "uiomoves", "locks", "unlocks", "depth", "invalid")
    ] + [("lbas", ctypes.c_uint64 * 16), ("blocks", ctypes.c_uint32 * 16)]


def expected(offset, length, first=FIRST):
    start = first * BLOCK + offset
    return bytes(((position * 17) ^ (position >> 8) ^ (position >> 16) ^ 0x5A) & 255
                 for position in range(start, start + length))


class RawUfsReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("host C compiler required")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / "raw-read.c"
        source.write_text(HARNESS.replace("ACTUAL_FUNCTION", patched_function()))
        library = directory / "raw-read.so"
        subprocess.run([compiler, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(source), "-o", str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.host_read.argtypes = [ctypes.c_int64, ctypes.c_int64, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int64,
            ctypes.c_void_p, ctypes.c_int64, ctypes.POINTER(Result)]
        cls.library.host_read.restype = ctypes.c_int

    def read(self, offset, length, banks=BANKS, ready=1, gate=1, fail_dma=0, fault_after=-1):
        output = ctypes.create_string_buffer(max(1, length))
        result = Result()
        error = self.library.host_read(offset, length, banks, FIRST, ready, gate, fail_dma,
                                       fault_after, output, len(output), ctypes.byref(result))
        self.assertEqual(result.depth, 0, "raw-read helper leaked the DMA mutex")
        self.assertEqual(result.locks, result.unlocks)
        self.assertEqual(result.invalid, 0, "DMA bounds, locking, uio length or canary violation")
        return error, output.raw[:max(0, length)], result

    def test_unaligned_read_preserves_exact_byte_pattern(self):
        error, data, result = self.read(37, 711)
        self.assertEqual(error, 0)
        self.assertEqual(data, expected(37, 711))
        self.assertEqual((result.offset, result.resid, result.moved), (748, 0, 711))
        self.assertEqual((result.reads, result.lbas[0], result.blocks[0]), (1, FIRST, 1))

    def test_aligned_read_starts_at_partition_first_block(self):
        error, data, result = self.read(0, BLOCK)
        self.assertEqual(error, 0)
        self.assertEqual(data, expected(0, BLOCK))
        self.assertEqual((result.lbas[0], result.blocks[0], result.resid), (FIRST, 1, 0))

    def test_multiple_chunks_and_unaligned_start(self):
        offset, length = BLOCK - 7, 2 * BOUNCE + 901
        error, data, result = self.read(offset, length)
        self.assertEqual(error, 0)
        self.assertEqual(data, expected(offset, length))
        self.assertEqual((result.reads, result.uiomoves, result.resid), (3, 3, 0))
        self.assertEqual(list(result.lbas)[:3], [FIRST, FIRST + 3, FIRST + 6])
        self.assertEqual(list(result.blocks)[:3], [3, 3, 2])

    def test_partition_end_returns_short_read_without_crossing_partition(self):
        offset = BANKS * BLOCK - 9
        error, data, result = self.read(offset, 30)
        self.assertEqual(error, 0)
        self.assertEqual(data[:9], expected(offset, 9))
        self.assertEqual(data[9:], bytes(21))
        self.assertEqual((result.offset, result.resid, result.moved), (BANKS * BLOCK, 21, 9))
        self.assertEqual((result.lbas[0], result.blocks[0]), (FIRST + BANKS - 1, 1))

    def test_eof_and_empty_partition_do_not_issue_dma(self):
        for offset, banks in ((BANKS * BLOCK, BANKS), (BANKS * BLOCK + 99, BANKS), (0, 0)):
            with self.subTest(offset=offset, banks=banks):
                error, data, result = self.read(offset, 17, banks=banks)
                self.assertEqual((error, result.reads, result.resid, result.moved), (0, 0, 17, 0))
                self.assertEqual(data, bytes(17))

    def test_zero_length_does_not_issue_dma(self):
        error, _, result = self.read(7, 0)
        self.assertEqual((error, result.reads, result.uiomoves, result.offset), (0, 0, 0, 7))

    def test_negative_offset_or_residual_is_rejected_before_locking(self):
        for offset, length in ((-1, 5), (0, -1)):
            with self.subTest(offset=offset, length=length):
                error, _, result = self.read(offset, length)
                self.assertEqual((error, result.reads, result.locks), (errno.EINVAL, 0, 0))

    def test_not_ready_and_root_gate_reject_before_locking(self):
        for ready, gate in ((0, 1), (1, 0), (0, 0)):
            with self.subTest(ready=ready, gate=gate):
                error, data, result = self.read(0, 17, ready=ready, gate=gate)
                self.assertEqual((error, result.reads, result.locks), (errno.ENXIO, 0, 0))
                self.assertEqual(data, bytes(17))

    def test_dma_failure_leaves_uio_unchanged_and_unlocks(self):
        error, data, result = self.read(19, 600, fail_dma=1)
        self.assertEqual((error, result.offset, result.resid, result.uiomoves), (errno.EIO, 19, 600, 0))
        self.assertEqual(data, bytes(600))

    def test_later_dma_failure_preserves_previous_chunk_progress(self):
        error, data, result = self.read(11, 2 * BOUNCE, fail_dma=2)
        copied = BOUNCE - 11
        self.assertEqual(error, errno.EIO)
        self.assertEqual((result.moved, result.offset, result.resid), (copied, BOUNCE, 2 * BOUNCE - copied))
        self.assertEqual(data[:copied], expected(11, copied))
        self.assertEqual(data[copied:], bytes(2 * BOUNCE - copied))

    def test_uio_fault_returns_efault_with_partial_progress_and_unlocks(self):
        for copied in (0, 17, BOUNCE + 9):
            with self.subTest(copied=copied):
                error, data, result = self.read(23, 2 * BOUNCE, fault_after=copied)
                self.assertEqual(error, errno.EFAULT)
                self.assertEqual((result.offset, result.resid, result.moved), (23 + copied, 2 * BOUNCE - copied, copied))
                self.assertEqual(data[:copied], expected(23, copied))
                self.assertEqual(data[copied:], bytes(2 * BOUNCE - copied))


if __name__ == "__main__":
    unittest.main()
