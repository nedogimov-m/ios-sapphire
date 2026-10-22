"""Exercise the actual no-write GPU-SMMU snapshot and its exact read scope."""
import ctypes
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class Snapshot(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'stage', 'error', 'reads', 'changed_offset', 'id0', 'id1', 'id2', 'id7', 'control', 'fault')]
    _fields_ += [('syndrome', ctypes.c_uint32 * 3)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        'page_bytes', 'global_bytes', 'streams', 'contexts', 'stage2_contexts',
        'sid_bits', 'input_bits', 'output_bits', 'virtual_bits')]
    _fields_ += [('smr', ctypes.c_uint32 * 128), ('s2cr', ctypes.c_uint32 * 128),
                 ('cbar', ctypes.c_uint32 * 8), ('cba2r', ctypes.c_uint32 * 8),
                 ('references', ctypes.c_uint32 * 8), ('active_references', ctypes.c_uint32 * 8),
                 ('gmu_matches', ctypes.c_uint32 * 2), ('gmu_slot', ctypes.c_uint32 * 2),
                 ('unreferenced_mask', ctypes.c_uint32), ('malformed_routes', ctypes.c_uint32),
                 ('stable', ctypes.c_bool), ('map_format_supported', ctypes.c_bool)]


HARNESS = r'''
#include <string.h>
#include "redfin_gpu_smmu.h"
static uint32_t regs[0x10000/4], original[0x10000/4], offsets[2048];
static unsigned reads,guards,bad,lost,guard_fail,read_fail,change_at;
static bool valid(void *context) {
 if(context)bad++;guards++;
 if(guard_fail && guards>=guard_fail)lost=1;
 return !lost;
}
static int read_reg(void *context,uint32_t at,uint32_t *out) {
 if(context || (at&3) || at>=0x8000) {bad++;return EINVAL;}
 if(lost)bad++;
 reads++;if(reads<=2048)offsets[reads-1]=at;
 if(read_fail==reads)return EIO;
 if(change_at==reads)regs[at/4]^=1;
 *out=regs[at/4];return 0;
}
int host_run(uint32_t chip,unsigned scenario,unsigned failed_guard,unsigned failed_read,
 unsigned changed_read,struct rf_gs_snapshot *out) {
 memset(regs,0,sizeof(regs));memset(offsets,0,sizeof(offsets));
 reads=guards=bad=lost=0;guard_fail=failed_guard;read_fail=failed_read;change_at=changed_read;
 regs[0x20/4]=(1u<<30)|(1u<<27)|(11u<<9)|16;
 regs[0x24/4]=(2u<<28)|8;regs[0x28/4]=(1u<<12)|(2u<<8)|(1u<<4)|1;
 regs[0x3c/4]=0x20;regs[0]=0x21;
 for(unsigned i=0;i<16;i++)regs[(0xc00+4*i)/4]=2u<<16;
 regs[0x800/4]=0x80000000;regs[0xc00/4]=0;
 regs[0x804/4]=0x84000005;regs[0xc04/4]=1;
 regs[0x808/4]=0x84000004;regs[0xc08/4]=2;
 regs[0xc0c/4]=3; /* Latent TRANS reference even though SMR invalid. */
 regs[0x810/4]=0x80000002;regs[0xc10/4]=5;
 for(unsigned i=0;i<8;i++) {regs[(0x1000+4*i)/4]=0x10000;regs[(0x1800+4*i)/4]=1;}
 switch(scenario) {
 case 1:regs[0x24/4]=(3u<<28)|8;break; /* Upstream 128KiB aperture. */
 case 2:regs[0x24/4]|=1u<<31;break;
 case 3:regs[0x20/4]|=1u<<8;break;
 case 4:regs[0x20/4]&=~(1u<<30);break;
 case 5:regs[0x20/4]&=~(1u<<27);break;
 case 6:regs[0x20/4]&=~255u;break;
 case 7:regs[0x20/4]=(regs[0x20/4]&~255u)|129;break;
 case 8:regs[0x24/4]=(regs[0x24/4]&~255u)|9;break;
 case 9:regs[0x24/4]|=9u<<16;break;
 case 10:regs[0x28/4]&=~(1u<<12);break;
 case 11:regs[0x28/4]&=~(15u<<4);break;
 case 12:regs[0x28/4]&=~(15u<<8);break;
 case 13:regs[0x818/4]=0x84000005;regs[0xc18/4]=4;break;
 case 14:regs[0x818/4]=0x84010004;regs[0xc18/4]=4;break;
 case 15:regs[0xc1c/4]=3u<<16;break;
 case 16:regs[0xc1c/4]=255;break;
 case 17:regs[0x81c/4]=0x80008007;break;
 case 18:regs[0x48/4]=0x80;regs[0x50/4]=0x500;break;
 case 19:regs[0x20/4]=(regs[0x20/4]&~255u)|128;break;
 default:break;
 }
 memcpy(original,regs,sizeof(regs));
 const struct rf_gs_ops ops={NULL,valid,read_reg};
 int result=rf_gs_snapshot_run(&ops,chip,out);
 /* One test mutation is a simulated external hardware change, not a write. */
 for(unsigned i=0;i<sizeof(regs)/sizeof(regs[0]);i++) {
  if(regs[i]!=original[i] && !(change_at && reads>=change_at && i==offsets[change_at-1]/4))bad++;
 }
 return result;
}
unsigned host_metric(unsigned n) {unsigned v[]={reads,guards,bad};return n<3?v[n]:999;}
uint32_t host_offset(unsigned n) {return n<reads&&n<2048?offsets[n]:UINT32_MAX;}
size_t host_size(void) {return sizeof(struct rf_gs_snapshot);}
int host_allowed(uint32_t at) {
 struct rf_gs_snapshot s={0};s.page_bytes=0x1000;s.global_bytes=0x8000;s.streams=16;s.contexts=8;
 return rf_gs_read_allowed(at,&s);
}
int host_match(uint32_t smr,uint32_t sid) {return rf_gs_stream_matches(smr,sid);}
'''


class RedfinGPUSMMUTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root/'smmu.c').write_text(HARNESS)
        subprocess.run([shutil.which('clang') or 'cc', '-std=c11', '-Wall', '-Wextra',
                        '-Werror', '-shared', '-fPIC', '-I', str(Path(__file__).parent/'include'),
                        str(root/'smmu.c'), '-o', str(root/'smmu.dylib')],
                       check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(root/'smmu.dylib'))
        cls.lib.host_run.argtypes = [ctypes.c_uint32, ctypes.c_uint, ctypes.c_uint,
                                     ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(Snapshot)]
        cls.lib.host_size.restype = ctypes.c_size_t
        cls.lib.host_offset.restype = ctypes.c_uint32
        cls.lib.host_match.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_snapshot(self, scenario=0, guard=0, read=0, change=0, chip=0x06020001):
        snapshot = Snapshot()
        result = self.lib.host_run(chip, scenario, guard, read, change, ctypes.byref(snapshot))
        self.assertEqual(result, snapshot.error)
        self.assertEqual(snapshot.reads, self.lib.host_metric(0))
        self.assertEqual(self.lib.host_metric(2), 0)
        offsets = [self.lib.host_offset(i) for i in range(snapshot.reads)]
        return result, snapshot, offsets

    def test_two_identical_global_snapshots_never_enter_any_context_page(self):
        self.assertEqual(ctypes.sizeof(Snapshot), self.lib.host_size())
        result, s, offsets = self.run_snapshot()
        self.assertEqual(result, 0)
        self.assertEqual(s.stage, 4)
        self.assertTrue(s.stable and s.map_format_supported)
        self.assertEqual((s.page_bytes, s.global_bytes, s.streams, s.contexts),
                         (0x1000, 0x8000, 16, 8))
        self.assertEqual((s.sid_bits, s.output_bits, s.virtual_bits), (11, 36, 40))
        self.assertEqual(len(offsets), 114)
        self.assertEqual(offsets[:57], offsets[57:])
        self.assertLess(max(offsets), 0x8000)
        self.assertEqual(tuple(s.gmu_matches), (1, 1))
        self.assertEqual(tuple(s.gmu_slot), (2, 1))

    def test_latent_and_active_references_are_counted_without_claiming_a_bank(self):
        _, s, _ = self.run_snapshot()
        self.assertEqual(tuple(s.references), (1, 1, 1, 1, 0, 1, 0, 0))
        self.assertEqual(tuple(s.active_references), (1, 1, 1, 0, 0, 1, 0, 0))
        self.assertEqual(s.unreferenced_mask, (1 << 4) | (1 << 6) | (1 << 7))
        self.assertNotIn('owned', [name for name, _ in Snapshot._fields_])

    def test_bad_chip_has_no_callback_or_mmio(self):
        for chip in (0, 0x06010001, 0x06020000, 0x06030500):
            result, _, offsets = self.run_snapshot(chip=chip)
            self.assertEqual(result, errno.EINVAL)
            self.assertFalse(offsets)
            self.assertEqual(self.lib.host_metric(1), 0)

    def test_wrong_aperture_geometry_or_unsupported_namespace_stops_after_ids(self):
        for scenario in range(1, 10):
            result, s, offsets = self.run_snapshot(scenario)
            self.assertEqual(result, errno.ENOTSUP)
            self.assertFalse(s.stable)
            self.assertEqual(offsets, [0x20, 0x24, 0x28, 0x3C])

    def test_unsupported_table_format_is_observed_without_any_write(self):
        for scenario in (10, 11, 12):
            result, s, _ = self.run_snapshot(scenario)
            self.assertEqual(result, 0)
            self.assertTrue(s.stable)
            self.assertFalse(s.map_format_supported)

    def test_duplicate_or_shared_stream_matches_remain_explicit(self):
        _, s, _ = self.run_snapshot(13)
        self.assertEqual(tuple(s.gmu_matches), (1, 2))
        self.assertEqual(tuple(s.gmu_slot), (2, 0xFFFFFFFF))
        _, s, _ = self.run_snapshot(14)
        self.assertEqual(tuple(s.gmu_matches), (2, 2))
        self.assertEqual(tuple(s.gmu_slot), (0xFFFFFFFF, 0xFFFFFFFF))

    def test_malformed_routes_disable_map_format_without_reading_bank_registers(self):
        for scenario in (15, 16, 17):
            result, s, offsets = self.run_snapshot(scenario)
            self.assertEqual(result, 0)
            self.assertTrue(s.stable)
            self.assertFalse(s.map_format_supported)
            self.assertEqual(s.malformed_routes, 1)
            self.assertLess(max(offsets), 0x8000)

    def test_existing_fault_state_is_observed_and_never_acknowledged(self):
        result, s, _ = self.run_snapshot(18)
        self.assertEqual(result, 0)
        self.assertEqual(s.fault, 0x80)
        self.assertEqual(s.syndrome[0], 0x500)

    def test_every_rechecked_register_change_stops_at_first_difference(self):
        _, _, baseline = self.run_snapshot()
        for changed in range(58, 115):
            result, s, offsets = self.run_snapshot(change=changed)
            self.assertEqual(result, errno.EAGAIN)
            self.assertFalse(s.stable)
            self.assertEqual(len(offsets), changed)
            self.assertEqual(s.changed_offset, baseline[changed-1])

    def test_every_guard_and_read_failure_stops_immediately(self):
        _, _, baseline = self.run_snapshot()
        guards = self.lib.host_metric(1)
        for failed in range(1, guards+1):
            result, s, _ = self.run_snapshot(guard=failed)
            self.assertEqual(result, errno.ECANCELED)
            self.assertFalse(s.stable)
            self.assertEqual(self.lib.host_metric(1), failed)
        for failed in range(1, len(baseline)+1):
            result, s, offsets = self.run_snapshot(read=failed)
            self.assertEqual(result, errno.EIO)
            self.assertFalse(s.stable)
            self.assertEqual(len(offsets), failed)

    def test_maximum_bounded_stream_count_does_not_extend_the_mapping(self):
        result, s, offsets = self.run_snapshot(19)
        self.assertEqual(result, 0)
        self.assertEqual(s.streams, 128)
        self.assertEqual(len(offsets), 562)
        self.assertLess(max(offsets), 0x8000)

    def test_read_allowlist_excludes_cbs_tcu_tbu_tlbs_and_unused_registers(self):
        for at in (0x4, 0x2C, 0x40, 0x64, 0x70, 0x74, 0x840,
                   0x1020, 0x1820, 0x8000, 0x8020, 0xD000, 0xF000,
                   0xFFFF, 0x10000, 0x22000):
            self.assertEqual(self.lib.host_allowed(at), 0)
        for at in (0x20, 0x24, 0x28, 0x3C, 0x48, 0x800, 0xC00, 0x1000, 0x181C):
            self.assertEqual(self.lib.host_allowed(at), 1)

    def test_stream_mask_matches_kernel_alias_without_merging_user_and_kernel(self):
        for sid in (5, 0x405):
            self.assertEqual(self.lib.host_match(0x84000005, sid), 1)
        for sid in (4, 6, 0x404, 0x805):
            self.assertEqual(self.lib.host_match(0x84000005, sid), 0)
        self.assertEqual(self.lib.host_match(0x04000005, 5), 0)


if __name__ == '__main__':
    unittest.main()
