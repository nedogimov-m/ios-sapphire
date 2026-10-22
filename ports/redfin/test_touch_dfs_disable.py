"""Execute the SE DFS disable fix: exact one-bit write and fail-closed ordering."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_touch_dfs_diag as dfs_model
from ports.redfin.test_touch_events import function

HERE = Path(__file__).resolve().parent

EXTRA = r'''
static unsigned disable_fault,disable_reads,disable_wrote,disable_verified,disable_trace_count;
static uint32_t disable_trace[24000][3];
'''

WRAPPERS = r'''
void disable_config(uint32_t initial,unsigned fault){
 dfs_se_initial[3]=initial;disable_fault=fault;disable_reads=disable_wrote=disable_verified=disable_trace_count=0;
 memset(disable_trace,0,sizeof(disable_trace));
}
unsigned disable_stat(unsigned n){
 const unsigned v[]={disable_reads,disable_wrote,disable_trace_count};return n<3?v[n]:0;
}
unsigned trace(unsigned n,unsigned field){return n<disable_trace_count && n<24000 && field<3?disable_trace[n][field]:0;}
'''


class TouchDFSDisableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        class Fixture(dfs_model.TouchDFSDiagnosticTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        template = (Path(Fixture.temp.name) / 'True/model.c').read_text()
        header = (Path(Fixture.temp.name) / 'True/redfin_touch_protocol.h').read_text()
        production = Path(Fixture.temp.name) / 'patches'
        target = production / 'bsd/dev/redfin_touch_setup.c'
        old = target.read_text()
        subprocess.run(['git', 'apply', str(HERE / 'touch-dfs-disable.patch')], cwd=production, check=True)
        new = target.read_text()
        # Model changes only raw MMIO and barriers; all setup and SPI C remain actual.
        before, after = [dfs_model.host_setup(s).replace(' return redfin_setup_rd(base,offset);',
            ' in_dfs++;uint32_t value=redfin_setup_rd(base,offset);in_dfs--;return value;') for s in (old, new)]
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.libs = []
        for fixed in (False, True):
            source = template
            assert source.count(before) == 1, 'Frozen production C model seam changed'
            source = source.replace(before, after if fixed else before)
            source = source.replace('static uint32_t dfs_wrapper_regs[3],dfs_se_initial[7];',
                                    'static uint32_t dfs_wrapper_regs[3],dfs_se_initial[7];\n' + EXTRA)
            source = source.replace('static uint32_t model_read(vm_offset_t base,unsigned offset){', r'''
static uint32_t model_read(vm_offset_t base,unsigned offset){
 if(base==2 && offset==0x80){
  disable_reads++;
  if((disable_fault==1 && disable_reads==1) || (disable_fault==3 && disable_wrote))return 0xffffffffu;
  if(disable_fault==4 && disable_wrote)return se[0x80/4]^0x100u;
  if(disable_fault==5 && disable_reads==2)return 0xffffffffu;
  if(disable_fault==6 && disable_reads==2)return se[0x80/4]^0x100u;
  if(disable_reads==2 && !(se[0x80/4]&1))disable_verified=1;
 }
''')
            signature = 'static void model_write(vm_offset_t base,unsigned offset,uint32_t value){'
            source = source.replace(signature, signature + r'''
#ifdef TEST_SE_DFS_DISABLED
 if(base==1 && offset==0x17024 && !disable_verified)violations++;
#endif
 if(disable_trace_count<24000){
  disable_trace[disable_trace_count][0]=(uint32_t)base;
  disable_trace[disable_trace_count][1]=offset;disable_trace[disable_trace_count][2]=value;
 }else violations++;
 disable_trace_count++;
''')
            actual = function(source, signature)
            changed = actual.replace('static const unsigned allowed[]={', 'static const unsigned allowed[]={0x80,')
            changed = changed.replace('spi_write(offset,value);return;', r'''
        if(offset==0x80){
         disable_wrote++;
         if((value&1) || value!=(se[offset/4]&~1u))violations++;
         if(disable_fault==2)return;
        }
        spi_write(offset,value);return;''')
            source = source.replace(actual, changed)
            work = root / str(fixed)
            work.mkdir()
            (work / 'redfin_touch_protocol.h').write_text(header)
            (work / 'model.c').write_text(('#define TEST_SE_DFS_DISABLED 1\n' if fixed else '') + source + WRAPPERS)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.run.argtypes = [C.c_uint] * 3 + [C.c_bool] * 2 + [C.c_uint]
            for name in ('stat', 'transport_stat', 'state', 'disable_stat', 'trace', 'dfs_evidence'):
                getattr(lib, name).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.fixed = cls.libs

    def trace(self, lib):
        count = lib.disable_stat(2)
        self.assertLess(count, 24000)
        return [tuple(lib.trace(index, field) for field in range(3)) for index in range(count)]

    def run_pair(self, initial=0x301, transport=0, issue=0, fault=0,
                 mode=2, enabled=1, rail=True, exclusive=True):
        results = []
        for lib in self.libs:
            lib.dfs_reset()
            lib.disable_config(initial, fault)
            results.append(lib.run(mode, enabled, issue, rail, exclusive, transport))
            self.assertEqual(lib.stat(8), 0, 'Unexpected register/map/write or GPIO ordering')
        return results

    def assert_only_se_dfs_write_changed(self, initial):
        before, after = [self.trace(lib) for lib in self.libs]
        extra = [(2, 0x80, initial & ~1)] if initial & 1 else []
        self.assertEqual([entry for entry in after if entry[:2] == (2, 0x80)], extra)
        self.assertEqual([entry for entry in after if entry[:2] != (2, 0x80)], before,
                         'An original MMIO write, its order or value changed')
        # Delay, framing, FIFO consumption, IRQ route cleanup and proof results stay identical.
        for index in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10):
            self.assertEqual(self.baseline.transport_stat(index), self.fixed.transport_stat(index))
        for index in range(1042):
            if index != 0x80 // 4:
                self.assertEqual(self.baseline.state(index), self.fixed.state(index))
        self.assertEqual(self.fixed.state(0x80 // 4), initial & ~1)

    def test_observed_301_clears_only_bit0_between_mclk_off_and_gcc_dfs_off(self):
        self.assertEqual(self.run_pair(), [0, 0])
        self.assert_only_se_dfs_write_changed(0x301)
        self.assertEqual(self.fixed.disable_stat(1), 1)
        trace = self.trace(self.fixed)
        offset = trace.index((2, 0x80, 0x300))
        self.assertEqual(trace[offset-1][:2], (2, 0x48))
        self.assertEqual(trace[offset-1][2] & 1, 0)
        self.assertEqual(trace[offset+1][:2], (1, 0x17024))
        self.assertEqual(trace[offset+1][2] & 1, 0)
        self.assertEqual(self.fixed.dfs_evidence(0, 3), 0x300)

    def test_future_bits_are_preserved_and_already_disabled_needs_no_new_write(self):
        for initial in (0, 1, 0x300, 0x301, 0x10000001, 0x80000301, 0xfffffffd):
            with self.subTest(initial=initial):
                self.assertEqual(self.run_pair(initial), [0, 0])
                self.assert_only_se_dfs_write_changed(initial)
                self.assertEqual(self.fixed.disable_stat(1), int(bool(initial & 1)))

    def test_allones_initial_or_bad_readback_stops_before_gcc_gpio_reset_and_id(self):
        for initial, fault in ((0xffffffff, 0), (0x301, 1), (0x301, 2), (0x301, 3),
                               (0x301, 4), (0x300, 5), (0x300, 6)):
            with self.subTest(initial=initial, fault=fault):
                results = self.run_pair(initial, fault=fault)
                self.assertEqual(results[1], errno.EIO)
                # Baseline remains unchanged; the fixed path returns immediately at its new proof.
                self.assertEqual(self.fixed.stat(4), 0, 'GPIO configuration/reset must not occur')
                self.assertEqual(self.fixed.stat(9), 0, 'Reset-high latch must not be written')
                self.assertEqual(self.fixed.stat(7), 0, 'SPI probe must not be entered')
                self.assertEqual(self.fixed.stat(6), 0, 'Failure must not add delays')
                self.assertEqual(self.fixed.stat(5), 0, 'GCC DFS/rate must not be changed after rejection')
                writes = self.trace(self.fixed)
                self.assertFalse(any(base == 1 and offset in (0x17024, 0x17014, 0x17010)
                                     for base, offset, _ in writes))
                self.assertEqual(self.fixed.disable_stat(1),
                                 0 if initial == 0xffffffff or fault == 1 or not initial & 1 else 1)

    def test_transport_failures_keep_exact_original_recovery_and_no_firmware_reset_writes(self):
        for transport in range(1, 14):
            with self.subTest(transport=transport):
                results = self.run_pair(transport=transport)
                self.assertEqual(results[0], results[1])
                self.assert_only_se_dfs_write_changed(0x301)

    def test_missing_proofs_and_foreign_host_never_touch_se_dfs(self):
        for args in ({'mode': 0}, {'mode': 1}, {'enabled': 0}, {'rail': False}, {'exclusive': False}):
            self.assertEqual(self.run_pair(**args), [errno.ENOTSUP, errno.ENOTSUP])
            self.assertEqual(self.fixed.disable_stat(0), 0)
            self.assertEqual(self.fixed.disable_stat(1), 0)
        for issue in (1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14, 17, 18, 19, 22, 30, 31, 33):
            self.run_pair(issue=issue)
            self.assertEqual(self.fixed.disable_stat(0), 0)
            self.assertEqual(self.fixed.disable_stat(1), 0)


if __name__ == '__main__':
    unittest.main()
