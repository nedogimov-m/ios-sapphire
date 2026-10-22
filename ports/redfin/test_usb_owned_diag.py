"""Compare baseline and diagnostic actual-C owner managers, including every MMIO."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    from ports.redfin.test_usb_owned_route import PREFIX, SUFFIX, added_file
except ModuleNotFoundError as error:
    if error.name != 'ports':
        raise
    from test_usb_owned_route import PREFIX, SUFFIX, added_file

HERE = Path(__file__).resolve().parent
LOGGER = r'''
#include <stdarg.h>
static char model_logs[8192];
static size_t model_log_used;
static int model_log(const char *format,...) __attribute__((format(__printf__,1,2)));
static int model_log(const char *format,...)
{
 va_list args;
 va_start(args,format);
 int n=vsnprintf(model_logs+model_log_used,sizeof(model_logs)-model_log_used,format,args);
 va_end(args);
 if(n<0 || (size_t)n>=sizeof(model_logs)-model_log_used){bad++;return -1;}
 model_log_used+=(size_t)n;
 return n;
}
#define printf model_log
'''


class USBOwnedDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        source_dir = root/'bsd'/'dev'
        source_dir.mkdir(parents=True)
        base = (HERE/'usb-owned-route.patch').read_text()
        header = added_file(base, 'bsd/dev/redfin_usb_owned.h')
        baseline = added_file(base, 'bsd/dev/redfin_usb_owned.c')
        (source_dir/'redfin_usb_owned.h').write_text(header)
        actual = source_dir/'redfin_usb_owned.c'
        actual.write_text(baseline)
        applied = subprocess.run(['git', 'apply', str(HERE/'usb-owned-diag.patch')],
                                 cwd=root, capture_output=True, text=True)
        if applied.returncode:
            raise RuntimeError(applied.stderr)
        diagnostic = actual.read_text()
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise RuntimeError('actual-C diagnostic tests require a C compiler')
        cls.libraries = []
        for name, code in (('base', baseline), ('diag', diagnostic)):
            code = '\n'.join(line for line in code.splitlines()
                             if not line.startswith('#include ')
                             and line != '#if defined(ARM64_BOARD_CONFIG_SWEET)'
                             and line != '#endif')
            seams = {
                'uint32_t value = *(const volatile uint32_t *)(base + offset);':
                    'uint32_t value = host_read(base,offset);',
                '*(volatile uint32_t *)(rf_usb_owner.smmu + offset) = value;':
                    'host_write(rf_usb_owner.smmu,offset,value);',
                '__asm__ volatile("dmb oshld" ::: "memory");': 'host_barrier();',
                '__asm__ volatile("dmb oshst" ::: "memory");': 'host_barrier();',
                '__asm__ volatile("dsb osh" ::: "memory");': 'host_barrier();',
            }
            for old, new in seams.items():
                if code.count(old) != 1:
                    raise AssertionError('actual C model seam changed: '+old)
                code = code.replace(old, new)
            prefix = PREFIX.replace('#define printf(...) ((void)0)', '')
            if prefix == PREFIX:
                raise AssertionError('baseline logging stub changed')
            suffix = SUFFIX.replace('void host_reset(void)\n{',
                                    'void host_reset(void)\n{\n model_log_used=0;model_logs[0]=0;')
            if suffix == SUFFIX:
                raise AssertionError('baseline reset model seam changed')
            source = root/(name+'.c')
            source.write_text(prefix+LOGGER+header+code+suffix+
                              '\nconst char *host_logs(void){return model_logs;}\n')
            library = root/(name+'.so')
            built = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                    '-Wno-unused-variable', '-shared', '-fPIC', str(source),
                                    '-o', str(library)], capture_output=True, text=True)
            if built.returncode:
                raise RuntimeError(built.stderr)
            lib = C.CDLL(str(library))
            lib.host_config.argtypes = [C.c_uint, C.c_uint64]
            lib.host_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
            lib.host_page.restype = C.c_void_p
            lib.host_store.restype = C.c_uint32
            lib.host_logs.restype = C.c_char_p
            cls.libraries.append(lib)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def snapshot(self, lib):
        stats = tuple(lib.host_stat(i) for i in range(9))
        self.assertEqual(stats[4:6], (0, 0), 'MMIO/lock/model contract violation')
        return (stats, tuple((lib.host_store(i, 0), lib.host_store(i, 1)) for i in range(2)),
                tuple(C.string_at(lib.host_page(i), 0x4000) for i in range(3)))

    def compare(self, configure=None, after=None, verify=None):
        results = []
        for lib in self.libraries:
            lib.host_reset()
            if configure:
                configure(lib)
            self.assertEqual(lib.host_register(0), 0)
            outcomes = [lib.host_claim(0)]
            if after:
                after(lib)
            if verify:
                outcomes.append(getattr(lib, verify)(0))
            snapshot = self.snapshot(lib)
            if outcomes[-1]:
                for operation in ('host_claim', 'host_revalidate', 'host_retained'):
                    self.assertNotEqual(getattr(lib, operation)(0), 0)
                self.assertEqual(self.snapshot(lib), snapshot, 'quarantine performed additional work')
            results.append((outcomes, snapshot, lib.host_logs().decode()))
        self.assertEqual(results[0][:2], results[1][:2],
                         'diagnostics changed return values, maps, reads, stores, delays, state, callbacks or MMIO images')
        self.assertLess(len(results[1][2]), 8192)
        return results[1]

    @staticmethod
    def mutation(lib, call, offset, value):
        for key, setting in ((7, call), (8, 2), (9, offset), (10, value)):
            lib.host_config(key, setting)

    def assert_smmu(self, log, phase, stores, smr, s2cr):
        self.assertIn(f'REDFIN USB OWNED: SMMU phase={phase} error={errno.EIO} stores={stores} '
                      f'ID=0x4c017e51/0x6000003e/0x5111 CR0=0x2c0406 groups=81 index=3 '
                      f'SMR={smr:#x} S2CR={s2cr:#x}\n', log)

    def test_success_logs_original_slot_without_changing_transaction(self):
        outcomes, snapshot, log = self.compare(verify='host_revalidate')
        self.assertEqual(outcomes, [0, 0])
        self.assertEqual(snapshot[0][2], 2)
        self.assertIn('lease stores=0 slot=1 imported-SMR=0x1230077 imported-S2CR=0x20044\n', log)
        self.assertIn('retained SID=e0 slot=1 bypass; no DMA authorization\n', log)

    def test_initial_allones_pair_identifies_index_before_any_store(self):
        for offset, smr, s2cr in ((0x80c, 0xffffffff, 0x2beef), (0xc0c, 0x4000000a, 0xffffffff)):
            with self.subTest(offset=offset):
                outcomes, snapshot, log = self.compare(lambda lib: lib.host_set(2, offset, 0xffffffff))
                self.assertEqual(outcomes, [errno.EIO])
                self.assertEqual(snapshot[0][2], 0)
                self.assert_smmu(log, 'claim-initial', 0, smr, s2cr)
                self.assertNotIn('lease stores=', log)

    def test_each_claim_boundary_reports_cached_phase_and_attempt_count(self):
        for call, phase, stores in ((3, 'claim-before-s2cr', 0), (4, 'claim-after-s2cr', 1),
                                    (5, 'claim-after-smr', 2)):
            with self.subTest(call=call):
                outcomes, snapshot, log = self.compare(lambda lib: self.mutation(lib, call, 0xc0c, 0xffffffff))
                self.assertEqual(outcomes, [errno.EIO])
                self.assertEqual(snapshot[0][2], stores)
                self.assert_smmu(log, phase, stores, 0x4000000a, 0xffffffff)

    def test_each_write_readback_timeout_reports_cached_final_poll(self):
        for mode, stores, offset, expected, observed in (
                (1, 1, 0xc04, 0x10300, 0x20044), (2, 1, 0xc04, 0x10300, 0x20300),
                (3, 2, 0x804, 0x800000e0, 0x1230077)):
            with self.subTest(mode=mode):
                outcomes, snapshot, log = self.compare(lambda lib: lib.host_config(11, mode))
                self.assertEqual(outcomes, [errno.EIO])
                self.assertEqual((snapshot[0][2], snapshot[0][3]), (stores, 1000))
                self.assertIn(f'write-readback error={errno.EIO} stores={stores} slot=1 '
                              f'offset={offset:#x} expected={expected:#x} observed={observed:#x} polls=1000\n', log)

    def test_strict_and_retained_checks_report_allones_without_stores(self):
        for operation, phase in (('host_revalidate', 'warm-revalidate'), ('host_retained', 'retained-route')):
            for offset, smr, s2cr in ((0x80c, 0xffffffff, 0x2beef), (0xc0c, 0x4000000a, 0xffffffff)):
                with self.subTest(operation=operation, offset=offset):
                    outcomes, snapshot, log = self.compare(after=lambda lib: lib.host_set(2, offset, 0xffffffff),
                                                           verify=operation)
                    self.assertEqual(outcomes, [0, errno.EIO])
                    self.assertEqual(snapshot[0][2], 2)
                    self.assert_smmu(log, phase, 2, smr, s2cr)

    def test_policy_and_mapping_failures_keep_existing_behavior(self):
        for key, value in ((2, 2), (2, 4), (3, 3)):
            with self.subTest(key=key, value=value):
                outcomes, _, log = self.compare(lambda lib: lib.host_config(key, value))
                self.assertNotEqual(outcomes[0], 0)
                self.assertIn('quarantined error=', log)


if __name__ == '__main__':
    unittest.main()
