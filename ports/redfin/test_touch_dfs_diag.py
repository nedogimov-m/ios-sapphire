"""Actual combined setup/SPI: DFS diagnostics add only bounded allowlisted reads."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_touch_platform_diag as platform_model
from ports.redfin.test_touch import added_file

HERE = Path(__file__).resolve().parent
ADDRESSES = [(2, n) for n in (0x70, 0x74, 0x78, 0x80, 0xe30, 0x2b0, 0x2b4)] + [
    (8, n) for n in (4, 0x118, 0x120)]

EXTRA = r'''
static unsigned in_dfs,dfs_reads,dfs_lines,dfs_ram_fault,dfs_map_fault;
static unsigned dfs_bases[32],dfs_offsets[32],dfs_report_cancels[2],dfs_report_routes[2];
static uint64_t dfs_ram_base,dfs_ram_size;
static uint32_t dfs_wrapper_regs[3],dfs_se_initial[7];
'''
READ = r'''
 if(in_dfs){
  const unsigned se_offsets[]={0x70,0x74,0x78,0x80,0xe30,0x2b0,0x2b4};
  bool allowed=false;
  if(base==2)for(unsigned i=0;i<7;i++)if(offset==se_offsets[i])allowed=true;
  if(base==8 && (offset==4 || offset==0x118 || offset==0x120))allowed=true;
  if(!allowed)violations++;
  if(dfs_reads<32){dfs_bases[dfs_reads]=(unsigned)base;dfs_offsets[dfs_reads]=offset;}dfs_reads++;
 }
 if(base==8){
  if(offset==4)return dfs_wrapper_regs[0];
  if(offset==0x118)return dfs_wrapper_regs[1];
  if(offset==0x120)return dfs_wrapper_regs[2];
  violations++;return 0;
 }
'''
PROPERTIES = r'''
    if(!strcmp(name,"dram-base")){
     *out=dfs_ram_fault==2?NULL:&dfs_ram_base;*n=dfs_ram_fault==3?7:8;return dfs_ram_fault==6?-1:0;
    }
    if(!strcmp(name,"dram-size")){
     *out=dfs_ram_fault==4?NULL:&dfs_ram_size;*n=dfs_ram_fault==5?7:8;return dfs_ram_fault==7?-1:0;
    }
'''
WRAPPERS = r'''
void dfs_reset(void){
 in_dfs=dfs_reads=dfs_lines=dfs_ram_fault=dfs_map_fault=0;
 memset(dfs_bases,0,sizeof(dfs_bases));memset(dfs_offsets,0,sizeof(dfs_offsets));
 memset(dfs_report_cancels,0,sizeof(dfs_report_cancels));memset(dfs_report_routes,0,sizeof(dfs_report_routes));
 dfs_ram_base=0x80000000ULL;dfs_ram_size=0x200000000ULL;
 dfs_wrapper_regs[0]=0x30010000;dfs_wrapper_regs[1]=dfs_wrapper_regs[2]=1;
 const uint32_t initial[]={1,1,0,1,0xf,0x1000,1};memcpy(dfs_se_initial,initial,sizeof(initial));
#ifdef RF_TOUCH_DFS_DIAG
 redfin_dfs_diag_wrapper=0;redfin_dfs_diag_memory_safe=false;
#endif
}
unsigned dfs_stat(unsigned n){
 const unsigned v[]={dfs_reads,dfs_lines,in_dfs,dfs_report_cancels[0],dfs_report_cancels[1],dfs_report_routes[1]};
 return n<6?v[n]:0;
}
unsigned dfs_address(unsigned n,unsigned field){return n<dfs_reads && n<32?(field?dfs_offsets[n]:dfs_bases[n]):0;}
unsigned dfs_evidence(unsigned phase,unsigned field){
#ifdef RF_TOUCH_DFS_DIAG
 if(phase>1)return 0;
 const struct redfin_platform_snapshot *d=&redfin_platform_snapshots[phase];
 if(field<7)return d->dfs_se[field];if(field<10)return d->dfs_wrapper[field-7];
 return field==10?d->dfs_se_read:field==11?d->dfs_wrapper_read:0;
#else
 (void)phase;(void)field;return 0;
#endif
}
void dfs_memory(uint64_t base,uint64_t size,unsigned fault){dfs_ram_base=base;dfs_ram_size=size;dfs_ram_fault=fault;}
void dfs_fail_map(void){dfs_map_fault=1;}
void dfs_initial(unsigned field,uint32_t value){
 if(field<7)dfs_se_initial[field]=value;
 else if(field<10)dfs_wrapper_regs[field-7]=value;
}
'''


def host_setup(source):
    signature = 'redfin_platform_diag_rd(vm_offset_t base,unsigned offset)\n{\n'
    source = source.replace(signature + ' return redfin_setup_rd(base,offset);', signature +
                            ' in_platform++;uint32_t value=redfin_setup_rd(base,offset);in_platform--;return value;')
    source = source.replace('*(volatile const uint32_t *)(base + offset)', 'model_read(base,offset)')
    source = source.replace('*(volatile uint32_t *)(base + offset) = value;', 'model_write(base,offset,value);')
    source = re.sub(r'^#include.*\n', '', source, flags=re.M)
    return re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', source)


class TouchDFSDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        # Reuse the frozen full setup/SPI MMIO model and its exact production baseline.
        class Fixture(platform_model.TouchPlatformDiagnosticTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        template = (Path(Fixture.temp.name) / 'True/model.c').read_text()
        header = (Path(Fixture.temp.name) / 'True/redfin_touch_protocol.h').read_text()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        tree = root / 'patches'
        dev = tree / 'bsd/dev'
        dev.mkdir(parents=True)
        for name, patch in (('setup', 'touch-setup.patch'), ('spi', 'touch-spi.patch')):
            (dev / f'redfin_touch_{name}.c').write_text(added_file(
                (HERE / patch).read_text(), f'bsd/dev/redfin_touch_{name}.c'))
        for patch in ('touch-events.patch', 'touch-spi-diag.patch', 'touch-platform-diag.patch'):
            subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_touch_setup.c',
                            '--include=bsd/dev/redfin_touch_spi.c', str(HERE / patch)], cwd=tree, check=True)
        before = (dev / 'redfin_touch_setup.c').read_text()
        subprocess.run(['git', 'apply', str(HERE / 'touch-dfs-diag.patch')], cwd=tree, check=True)
        after = (dev / 'redfin_touch_setup.c').read_text()
        cls.libs = []
        for overlay, setup in ((False, before), (True, after)):
            source = template
            original = host_setup(before)
            assert source.count(original) == 1, 'Frozen setup model seam changed'
            setup = host_setup(setup)
            if overlay:
                setup = setup.replace(' return redfin_setup_rd(base,offset);',
                                      ' in_dfs++;uint32_t value=redfin_setup_rd(base,offset);in_dfs--;return value;')
            source = source.replace(original, setup)
            source = source.replace('static uint32_t write_trace,delay_trace;',
                                    'static uint32_t write_trace,delay_trace;\n' + EXTRA)
            source = source.replace(' if(strstr(f,"REDFIN TOUCH PLATFORM:")){', r'''
 if(strstr(f,"REDFIN TOUCH DFS:")){
  dfs_lines++;
  va_list args;va_start(args,f);const char *phase=va_arg(args,const char *);
  unsigned n=!strcmp(phase,"before-first-tx")?0:1;
  dfs_report_cancels[n]=cancels;dfs_report_routes[n]=se[0xe1c/4];va_end(args);
 }
 if(strstr(f,"REDFIN TOUCH PLATFORM:")){''')
            source = source.replace('(void)root;(void)name;*out=(void *)1;',
                                    '(void)root;if(!strcmp(name,"/chosen") && dfs_ram_fault==1)return -1;*out=(void *)1;')
            source = source.replace('    (void)node;\n', '    (void)node;\n' + PROPERTIES)
            source = source.replace('    maps++;',
                                    '    maps++;if(p==0x8c0000 && size==0x2000)return dfs_map_fault?0:8;')
            source = source.replace('static uint32_t model_read(vm_offset_t base,unsigned offset){',
                                    'static uint32_t model_read(vm_offset_t base,unsigned offset){\n' + READ)
            source = source.replace('se[0x48/4]=0x11;se[0x84/4]=0x12345678;', r'''
    se[0x48/4]=0x11;se[0x84/4]=0x12345678;
    const unsigned initial_offsets[]={0x70,0x74,0x78,0x80,0xe30,0x2b0,0x2b4};
    for(unsigned i=0;i<7;i++)se[initial_offsets[i]/4]=dfs_se_initial[i];''')
            source = source.replace('if(kind==33){cfg^=0x100u;pins[3][0]^=0x40u;return;}',
                                    'if(kind==33){cfg^=0x100u;pins[3][0]^=0x40u;return;}\n'
                                    '            if(kind==34){se[0x80/4]=0x21;dfs_wrapper_regs[2]^=1;return;}')
            work = root / str(overlay)
            work.mkdir()
            (work / 'redfin_touch_protocol.h').write_text(header)
            (work / 'model.c').write_text(source + WRAPPERS)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.run.argtypes = [C.c_uint] * 3 + [C.c_bool] * 2 + [C.c_uint]
            lib.dfs_memory.argtypes = [C.c_uint64, C.c_uint64, C.c_uint]
            for name in ('stat', 'transport_stat', 'platform_stat', 'state', 'dfs_stat', 'dfs_address', 'dfs_evidence'):
                getattr(lib, name).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.diag = cls.libs

    def pair(self, fault=0, issue=0, mode=2, enabled=1, rail=True, exclusive=True, configure=None):
        results = []
        for lib in self.libs:
            lib.dfs_reset()
            if configure:
                configure(lib)
            results.append(lib.run(mode, enabled, issue, rail, exclusive, fault))
        self.assertEqual(results[0], results[1])
        for index in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
            self.assertEqual(self.baseline.stat(index), self.diag.stat(index), f'Setup behavior changed: {index}')
        self.assertEqual(self.diag.stat(8), 0, 'Unexpected read/write/map or GPIO ordering')
        self.assertEqual([self.baseline.transport_stat(i) for i in range(11)],
                         [self.diag.transport_stat(i) for i in range(11)], 'Transport/write/delay/FIFO changed')
        self.assertEqual([self.baseline.state(i) for i in range(1042)],
                         [self.diag.state(i) for i in range(1042)], 'Final SE/pad/GCC state changed')
        self.assertEqual([self.baseline.platform_stat(i) for i in range(3)],
                         [self.diag.platform_stat(i) for i in range(3)], 'Frozen platform read budget changed')
        self.assertLessEqual(self.diag.dfs_stat(0), 20)
        self.assertLessEqual(self.diag.dfs_stat(1), 6)
        self.assertEqual(self.diag.dfs_stat(2), 0)
        return results[1]

    def test_exact_allowlist_one_map_and_snapshot_before_first_tx(self):
        self.assertEqual(self.pair(), 0)
        self.assertEqual(self.diag.stat(0)-self.baseline.stat(0), 1)
        self.assertEqual([self.diag.dfs_stat(i) for i in range(3)], [10, 3, 0])
        self.assertEqual([(self.diag.dfs_address(i, 0), self.diag.dfs_address(i, 1)) for i in range(10)], ADDRESSES)
        self.assertEqual([self.diag.dfs_evidence(0, i) for i in range(12)],
                         [1, 1, 0, 1, 0xf, 0x1000, 1, 0x30010000, 1, 1, 1, 1])
        self.assertEqual(self.diag.dfs_stat(3), 0)

    def test_failures_and_pending_dfs_wrapper_drift_preserve_recovery(self):
        for fault in list(range(1, 14)) + [31, 32, 33, 34]:
            with self.subTest(fault=fault):
                self.pair(fault)
                if fault in (1, 2, 3, 34):
                    self.assertEqual([self.diag.dfs_stat(i) for i in range(2)], [20, 6])
                    self.assertEqual([self.diag.dfs_stat(i) for i in (4, 5)], [1, 0])
                if fault in (31, 32):
                    self.assertEqual(self.diag.dfs_stat(0), 10)
                    self.assertEqual(self.diag.dfs_evidence(1, 10), 0)
                if fault == 34:
                    self.assertEqual(self.diag.dfs_evidence(0, 3), 1)
                    self.assertEqual(self.diag.dfs_evidence(1, 3), 0x21)
                    self.assertEqual(self.diag.dfs_evidence(1, 9), 0)

    def test_wrapper_map_failure_skips_only_wrapper_evidence(self):
        self.assertEqual(self.pair(configure=lambda lib: lib.dfs_fail_map()), 0)
        self.assertEqual(self.diag.dfs_stat(0), 7)
        self.assertEqual(self.diag.dfs_evidence(0, 10), 1)
        self.assertEqual(self.diag.dfs_evidence(0, 11), 0)

    def test_malformed_or_overlapping_ram_adds_no_map_or_mmio(self):
        cases = [(0x80000000, 0x200000000, fault) for fault in range(1, 8)] + [
            (0, 0x4000, 0), (0x80000001, 0x4000, 0), (0x80000000, 0, 0),
            (0x80000000, 0x4001, 0), (1 << 36, 0x4000, 0), ((1 << 36)-0x4000, 0x8000, 0),
            (0x880000, 0x4000, 0), (0x8c0000, 0x4000, 0), (0x87c000, 0x8000, 0)]
        for base, size, fault in cases:
            with self.subTest(base=base, size=size, fault=fault):
                self.assertEqual(self.pair(configure=lambda lib: lib.dfs_memory(base, size, fault)), 0)
                self.assertEqual(self.diag.stat(0), self.baseline.stat(0))
                self.assertEqual(self.diag.dfs_stat(0), 0)
                self.assertEqual(self.diag.dfs_evidence(0, 10), 0)

    def test_missing_setup_proofs_and_early_failures_never_map_wrapper(self):
        for issue in (1, 2, 10, 11, 12, 14, 15, 16, 30, 31, 33):
            self.assertNotEqual(self.pair(issue=issue), 0)
            self.assertEqual(self.diag.stat(0), self.baseline.stat(0))
            self.assertEqual(self.diag.dfs_stat(0), 0)
        for args in ({'mode': 0}, {'mode': 1}, {'enabled': 0}, {'rail': False}, {'exclusive': False}):
            self.assertEqual(self.pair(**args), errno.ENOTSUP)
            self.assertEqual(self.diag.stat(0), 0)

    def test_raw_allones_and_repeated_reports_never_change_policy_or_budget(self):
        for field in range(10):
            self.assertEqual(self.pair(configure=lambda lib: lib.dfs_initial(field, 0xffffffff)), 0)
            self.assertEqual(self.diag.dfs_evidence(0, field), 0xffffffff)
        self.pair(3)
        before = [self.diag.transport_stat(i) for i in range(11)]
        for phase in (0, 1, 2, 0xffffffff):
            self.diag.repeat(phase)
        self.assertEqual([self.diag.dfs_stat(i) for i in range(2)], [20, 6])
        self.assertEqual([self.diag.transport_stat(i) for i in range(11)], before)

    def test_each_physical_clock_guard_applies_to_all_new_reads(self):
        for guard in range(9):
            with self.subTest(guard=guard):
                self.pair()
                before = [self.diag.transport_stat(i) for i in range(11)]
                self.diag.manual_capture(guard)
                allowed = guard in (0, 5)  # Original native S_AHB HWCG path and non-HWCG running path.
                self.assertEqual(self.diag.dfs_stat(0), 20 if allowed else 10)
                self.assertEqual(self.diag.dfs_evidence(1, 10), int(allowed))
                self.assertEqual(self.diag.dfs_evidence(1, 11), int(allowed))
                self.assertEqual([self.diag.transport_stat(i) for i in range(11)], before)


if __name__ == '__main__':
    unittest.main()
