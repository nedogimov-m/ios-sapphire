"""Cached bypass diagnostics must leave actual owner/enumeration I/O identical."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_bypass_context as bypass
from ports.redfin import test_usb_enumeration_start as enumeration

HERE = Path(__file__).resolve().parent
WRAPPERS = r'''
void diag_reset(void){diag_barriers=0;}
unsigned diag_barrier_count(void){return diag_barriers;}
int diag_verify(unsigned warm,unsigned variant){
 const void *caller=variant==1?&other_token:variant==2?NULL:rf_usb_owner.caller;
 return warm?redfin_usb_owned_revalidate_bypass(caller):redfin_usb_owned_route_retained_bypass(caller);
}
int diag_quiesce(void){return redfin_usb_owned_quiesce_bypass(rf_usb_owner.caller);}
void diag_expected(unsigned kind,uint32_t value){
 if(kind==0)rf_usb_bypass.expected.streams.smr[127]=value;
 else if(kind==1)rf_usb_bypass.expected.bank[127].fsr=value;
 else if(kind==2)rf_usb_bypass.expected.streams.groups=value;
 else bad++;
}
'''


class USBBypassDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        class Fixture(enumeration.USBEnumerationStartTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        original = Path(Fixture.temp.name)
        template = (original / 'model.c').read_text()
        owned = original / 'bsd/dev/redfin_usb_owned.c'
        before = owned.read_text()
        subprocess.run(['git', 'apply', str(HERE / 'usb-bypass-diagnostic.patch')],
                       cwd=original, check=True)
        after = owned.read_text()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        cls.libs = []
        for name, actual in (('base', before), ('diagnostic', after)):
            source = template
            if source.count(bypass.host_owned(before)) != 1:
                raise AssertionError('Actual enum owner source seam changed')
            source = source.replace(bypass.host_owned(before), bypass.host_owned(actual))
            old = 'static void host_barrier(void) { if (depth != 1) bad++; }'
            if source.count(old) != 1:
                raise AssertionError('Barrier counting seam changed')
            source = source.replace(old, 'static unsigned diag_barriers;\n' +
                                    'static void host_barrier(void) { diag_barriers++; if (depth != 1) bad++; }')
            work = root / name
            work.mkdir()
            for header in original.glob('*.h'):
                shutil.copy2(header, work / header.name)
            model = work / 'model.c'
            model.write_text(source + WRAPPERS)
            library = work / 'model.so'
            result = subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra',
                                     '-Werror', str(model), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
            lib.host_config.argtypes = [C.c_uint, C.c_uint64]
            lib.host_set.argtypes = lib.bypass_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            lib.host_logs.restype = C.c_char_p
            lib.host_hash.restype = C.c_uint
            cls.libs.append(lib)

    def reset(self, lib, gadget):
        lib.host_reset()
        lib.bypass_reset()
        lib.bypass_fixture()
        lib.enum_reset()
        lib.diag_reset()
        lib.host_arg(b'redfinusbcontexts', 0, 1)
        lib.host_arg(b'redfinusbbypass', 1, 1)
        lib.host_arg(b'redfinusbgadget', int(gadget), 1)
        lib.bypass_seal()

    def snapshot(self, lib):
        stats = tuple(lib.host_stat(key) for key in range(9))
        self.assertEqual(stats[4:6], (0, 0), 'MMIO/map/store/lock model violation')
        return (stats, lib.diag_barrier_count(), tuple(lib.host_hash(key) for key in range(2)),
                tuple(tuple(lib.bypass_trace(n, field) for field in range(3)) for n in range(4)),
                tuple(lib.bypass_stat(key) for key in range(4)),
                tuple(lib.enum_stat(key) for key in range(4)),
                b''.join(C.string_at(lib.host_page(region), 0x4000) for region in range(3)) +
                C.string_at(lib.host_context_page(), bypass.CB_SIZE))

    def compare(self, *, before=None, after=None, warm=None, gadget=False):
        results = []
        for lib in self.libs:
            self.reset(lib, gadget)
            if before:
                before(lib)
            outcomes = [lib.host_start()]
            if after:
                after(lib)
            if warm is not None:
                outcomes.append(lib.diag_verify(int(warm), 0))
            snapshot = self.snapshot(lib)
            if outcomes[-1]:
                # Quarantine cannot cause another import, attempt, cleanup or retry.
                for again in (0, 1):
                    self.assertEqual(lib.diag_verify(again, 0), errno.EBUSY)
                self.assertNotEqual(lib.host_start(), 0)
                self.assertEqual(self.snapshot(lib), snapshot)
            results.append((outcomes, snapshot, lib.host_logs().decode()))
        self.assertEqual(results[0][:2], results[1][:2],
                         'Diagnostics changed results, maps, reads/order/values, stores, delays, barriers, policy calls or MMIO images')
        self.assertLess(len(results[1][2]), 32768)
        return results[1]

    @staticmethod
    def lines(log):
        return [line for line in log.splitlines() if any(
            f'REDFIN USB BYPASS: cached-{kind}' in line for kind in ('diff', 'stream', 'bank'))]

    def test_warm_and_active_success_preserve_all_io_and_emit_no_difference(self):
        for gadget, warm in ((False, True), (True, False)):
            with self.subTest(gadget=gadget):
                outcomes, snapshot, log = self.compare(gadget=gadget, warm=warm)
                self.assertEqual(outcomes, [0, 0])
                self.assertEqual(snapshot[0][2], 4)
                self.assertEqual(self.lines(log), [])

    def test_header_drift_reports_cached_values_without_reimport(self):
        for warm in (False, True):
            outcomes, snapshot, log = self.compare(warm=warm, gadget=not warm,
                after=lambda lib: lib.bypass_set(2, 0, 0x290406))
            self.assertEqual(outcomes, [0, errno.EAGAIN])
            self.assertEqual(snapshot[0][2], 4)
            self.assertEqual(self.lines(log), [
                f'REDFIN USB BYPASS: cached-diff warm={int(warm)} stores=4 first-stream=128 first-bank=128 '
                'expected-ID=0x4c017e51/0x6000003e/0x5111 CR0=0x2c0406 groups=81 '
                'current-ID=0x4c017e51/0x6000003e/0x5111 CR0=0x290406 groups=81'])

    def test_first_stream_pair_and_each_bank_word_are_reported_exactly(self):
        for warm in (False, True):
            for region, offset, value, expected in (
                (2, 0x810, 0x800000e1, 'cached-stream=4 expected-SMR=0x800000e0 S2CR=0x304 current-SMR=0x800000e1 S2CR=0x304'),
                (2, 0xc10, 0x305, 'cached-stream=4 expected-SMR=0x800000e0 S2CR=0x304 current-SMR=0x800000e0 S2CR=0x305'),
                (3, 0x4000, 1, 'current-SCTLR=0x1 CBAR=0x10000 CBA2R=0 FSR=0'),
                (2, 0x1010, 0x20000, 'current-SCTLR=0 CBAR=0x20000 CBA2R=0 FSR=0'),
                (2, 0x1810, 1, 'current-SCTLR=0 CBAR=0x10000 CBA2R=0x1 FSR=0'),
                (3, 0x4058, 0x400, 'current-SCTLR=0 CBAR=0x10000 CBA2R=0 FSR=0x400'),
            ):
                with self.subTest(warm=warm, region=region, offset=offset):
                    outcomes, snapshot, log = self.compare(warm=warm, gadget=not warm,
                        after=lambda lib: lib.bypass_set(region, offset, value))
                    self.assertEqual(outcomes, [0, errno.EAGAIN])
                    lines = self.lines(log)
                    self.assertEqual(len(lines), 2)
                    self.assertIn(expected, lines[1])
                    if region == 3 or offset in (0x1010, 0x1810):
                        self.assertIn('first-stream=128 first-bank=4', lines[0])
                        self.assertIn('cached-bank=4 expected-SCTLR=0 CBAR=0x10000 CBA2R=0 FSR=0', lines[1])
                    else:
                        self.assertIn('first-stream=4 first-bank=128', lines[0])
                    self.assertEqual(snapshot[0][2], 4)

    def test_simultaneous_drift_reports_only_first_stream_and_bank_with_bounded_output(self):
        def mutate(lib):
            for region, offset, value in ((2, 0x808, 0x80000044), (2, 0xc0c, 0x20007),
                                           (3, 0x1000, 0xe2), (3, 0x5000, 0x38622102)):
                lib.bypass_set(region, offset, value)
        outcomes, _, log = self.compare(gadget=True, warm=False, after=mutate)
        self.assertEqual(outcomes, [0, errno.EAGAIN])
        lines = self.lines(log)
        self.assertEqual(len(lines), 3)
        self.assertIn('first-stream=2 first-bank=1', lines[0])
        self.assertIn('cached-stream=2 expected-SMR=0x80000023 S2CR=0x2 current-SMR=0x80000044 S2CR=0x2', lines[1])
        self.assertIn('cached-bank=1 expected-SCTLR=0xe0 CBAR=0x1f000 CBA2R=0x1 FSR=0x400 current-SCTLR=0xe2', lines[2])

    def test_each_claim_boundary_has_identical_exact_store_prefix(self):
        for stores in range(1, 5):
            with self.subTest(stores=stores):
                outcomes, snapshot, log = self.compare(before=lambda lib: lib.bypass_drift(stores))
                self.assertEqual(outcomes, [errno.EAGAIN])
                self.assertEqual(snapshot[0][2], stores)
                self.assertEqual(len(self.lines(log)), 2)
                self.assertIn(f'cached-diff warm=1 stores={stores} first-stream=128 first-bank=10', log)

    def test_snapshot_policy_power_core_and_readback_failures_keep_original_work(self):
        for warm in (False, True):
            for region, offset in ((2, 0x800), (2, 0xc00), (3, 0x4000), (2, 0x1010), (2, 0x1810), (3, 0x4058)):
                with self.subTest(warm=warm, region=region, offset=offset):
                    outcomes, _, log = self.compare(warm=warm, gadget=not warm,
                        after=lambda lib: lib.bypass_set(region, offset, 0xffffffff))
                    self.assertEqual(outcomes, [0, errno.EIO])
                    self.assertEqual(self.lines(log), [])
                    self.assertIn(f'cached-snapshot warm={int(warm)} error={errno.EIO} stores=4; comparison skipped\n', log)
            for mutate in (lambda lib: lib.host_arg(b'modem', 1, 1),
                           lambda lib: lib.enum_power(0, 0)):
                outcomes, _, log = self.compare(warm=warm, gadget=not warm, after=mutate)
                self.assertNotEqual(outcomes[-1], 0)
                self.assertEqual(self.lines(log), [])

    def test_snapshot_final_header_instability_reports_phase_without_partial_comparison(self):
        for warm in (False, True):
            outcomes, snapshot, log = self.compare(warm=warm, gadget=not warm,
                after=lambda lib: lib.host_mutate(2, 0, 2, 0x290406))
            self.assertEqual(outcomes, [0, errno.EAGAIN])
            self.assertEqual(snapshot[0][2], 4)
            self.assertEqual(self.lines(log), [])
            self.assertIn(f'cached-snapshot warm={int(warm)} error={errno.EAGAIN} stores=4; comparison skipped\n', log)
        outcomes, _, log = self.compare(warm=True, after=lambda lib: lib.host_set(1, 0x400, 0xa244b000))
        self.assertEqual(outcomes, [0, errno.EAGAIN])
        self.assertEqual(self.lines(log), [])
        for step in range(1, 5):
            for fault in (1, 2, 3):
                outcomes, snapshot, log = self.compare(before=lambda lib: lib.bypass_inject(fault, step))
                self.assertEqual(outcomes, [errno.EIO])
                self.assertEqual((snapshot[0][2], snapshot[0][3]), (step, 1000))
                self.assertEqual(self.lines(log), [])

    def test_full_cached_array_bounds_match_existing_memcmp_coverage(self):
        for kind, token in ((0, 'first-stream=127 first-bank=128'),
                            (1, 'first-stream=128 first-bank=127'),
                            (2, 'first-stream=128 first-bank=128')):
            outcomes, _, log = self.compare(warm=False, gadget=True,
                after=lambda lib: lib.diag_expected(kind, 1))
            self.assertEqual(outcomes, [0, errno.EAGAIN])
            self.assertIn(token, self.lines(log)[0])
            self.assertEqual(len(self.lines(log)), 1 if kind == 2 else 2)


if __name__ == '__main__':
    unittest.main()
