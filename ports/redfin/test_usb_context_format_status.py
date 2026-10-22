"""Actual owner C: predict only owned read-only FORMAT after accepted RW64."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_aarch64_context as a64

HERE = Path(__file__).resolve().parent
FAULT = 0xc00001fe
FORMAT = 0x600

EXTRA = r'''
static unsigned format_value=0x400,format_extra,format_foreign;
'''
SIDE_EFFECT = r'''
  /* Hardware changes read-only FORMAT when CBA2R.RW64 really takes. */
  if(region==2 && offset==0x1800+bank*4 && value==1 && observed==1){
   unsigned at=(bank*0x1000+0x58)/4;
   uint32_t status=(context_pages[at]&~0x600u)|format_value|format_extra;
   context_pages[at]=shadow_context[at]=status;
  }
'''
WRAPPERS = r'''
void format_reset(void){format_value=0x400;format_extra=format_foreign=0;}
void format_inject(unsigned value,unsigned extra,unsigned foreign){
 format_value=value;format_extra=extra;format_foreign=foreign;
}
uint32_t format_expected(void){return rf_usb_bypass.expected.bank[rf_usb_bypass.bank].fsr;}
uint32_t format_observed(void){return context_pages[(rf_usb_bypass.bank*0x1000+0x58)/4];}
int format_replay_transition(uint32_t prior){
 /* Exercise the actual post-readback update with every prior status bit.
  * Full claim tests separately enforce the allocator's native-fault exclusion. */
 unsigned bank=rf_usb_bypass.bank,at=(bank*0x1000+0x58)/4;
 context_pages[bank*0x1000/4]=shadow_context[bank*0x1000/4]=0;
 pages[2][(0x1800+bank*4)/4]=shadow_pages[2][(0x1800+bank*4)/4]=0;
 context_pages[at]=shadow_context[at]=prior;
 rf_usb_bypass.expected.bank[bank].sctlr=0;
 rf_usb_bypass.expected.bank[bank].cba2r=0;
 rf_usb_bypass.expected.bank[bank].fsr=prior;
 rf_usb_bypass.stores=rf_usb_owner.diag_stores=stores=bypass_attempts=1;
 lck_mtx_lock(&rf_usb_lock);
 int error=rf_usb_bypass_store(1);
 lck_mtx_unlock(&rf_usb_lock);
 return error;
}
'''


class USBContextFormatStatusTests(unittest.TestCase):
    reset_owner = a64.USBAArch64ContextTests.reset
    memory = a64.USBAArch64ContextTests.memory
    trace = a64.USBAArch64ContextTests.trace
    snapshot = a64.USBAArch64ContextTests.snapshot
    claim = a64.USBAArch64ContextTests.claim
    assert_quarantined = a64.USBAArch64ContextTests.assert_quarantined

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')

        class Fixture(a64.USBAArch64ContextTests):
            pass

        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        template = (Path(Fixture.tmp.name) / 'rw64/model.c').read_text()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        owned = root / 'bsd/dev/redfin_usb_owned.c'
        owned.parent.mkdir(parents=True)
        owned.write_text(Fixture.actual)
        subprocess.run(['git', 'apply', str(HERE / 'usb-context-format-status.patch')],
                       cwd=root, check=True)
        cls.actual = owned.read_text()
        cls.libs = []
        for name, actual in (('base', Fixture.actual), ('format', cls.actual)):
            source = template
            old = a64.bypass.host_owned(Fixture.actual)
            if source.count(old) != 1:
                raise AssertionError('Actual AArch64 owner C seam changed')
            source = source.replace(old, a64.bypass.host_owned(actual))
            seams = (('static unsigned a64_expected_steps=4,',
                      EXTRA + '\nstatic unsigned a64_expected_steps=4,'),
                     ('page[offset/4]=shadow[offset/4]=observed;',
                      'page[offset/4]=shadow[offset/4]=observed;\n' + SIDE_EFFECT),
                     (' if(bypass_drift_step==n+1)context_pages[(10*0x1000)/4]^=0x100u;',
                      '''
 if(n==1 && a64_expected_steps==5 && format_foreign)
  context_pages[(5*0x1000+0x58)/4]^=format_foreign;
 if(bypass_drift_step==n+1)context_pages[(10*0x1000)/4]^=0x100u;'''))
            for old, new in seams:
                if source.count(old) != 1:
                    raise AssertionError(f'Actual model seam changed: {old[:60]}')
                source = source.replace(old, new)
            work = root / name
            work.mkdir()
            for header in (Path(Fixture.tmp.name) / 'rw64').glob('*.h'):
                shutil.copy2(header, work / header.name)
            model = work / 'model.c'
            model.write_text(source + WRAPPERS)
            library = work / 'model.so'
            result = subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-O0',
                                     '-Wall', '-Wextra', '-Werror', '-I', str(work),
                                     str(model), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
            lib.host_set.argtypes = lib.bypass_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            lib.host_logs.restype = C.c_char_p
            lib.format_replay_transition.argtypes = [C.c_uint32]
            for symbol in ('host_hash', 'host_visit', 'bypass_trace', 'bypass_stat',
                           'a64_steps', 'a64_target', 'a64_readback',
                           'format_expected', 'format_observed'):
                getattr(lib, symbol).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.lib = cls.libs

    def reset(self, lib=None, **kwargs):
        lib = self.reset_owner(lib, **kwargs)
        lib.format_reset()
        return lib

    def test_observed_format_transition_calibrates_old_failure_and_new_five_store_success(self):
        lib = self.reset(self.baseline)
        self.assertEqual(self.claim(lib), errno.EAGAIN)
        self.assertEqual(self.trace(lib), a64.FIVE[:2])
        self.assertEqual(lib.format_expected(), 0)
        self.assertEqual(lib.format_observed(), 0x400)
        self.assert_quarantined(lib)
        lib = self.reset()
        expected = bytearray(self.memory())
        self.assertEqual(self.claim(), 0)
        self.assertEqual(self.trace(), a64.FIVE)
        self.assertEqual(lib.format_expected(), 0x400)
        self.assertEqual(lib.format_observed(), 0x400)
        for region, offset, value in a64.FIVE + [(3, 0x4058, 0x400)]:
            at = 0xc000 + offset if region == 3 else region * 0x4000 + offset
            expected[at:at+4] = value.to_bytes(4, 'little')
        self.assertEqual(self.memory(), bytes(expected))
        self.assertEqual(lib.bypass_verify(0), 0)
        self.snapshot()

    def test_wrong_format_each_real_fault_and_other_status_drift_stop_after_two_stores(self):
        cases = [(value, 0) for value in (0, 0x200, 0x600)]
        cases += [(0x400, 1 << bit) for bit in range(32) if not (FORMAT & (1 << bit))]
        for value, extra in cases:
            with self.subTest(value=value, extra=extra):
                lib = self.reset()
                lib.format_inject(value, extra, 0)
                self.assertEqual(self.claim(), errno.EAGAIN)
                self.assertEqual(self.trace(), a64.FIVE[:2])
                self.assertEqual(lib.format_expected(), 0x400)
                self.assertEqual(lib.format_observed(), value | extra)
                self.assertEqual(lib.host_visit(3, 0x4060), 0, 'incomplete claim cannot read fault syndromes')
                self.assert_quarantined()

    def test_foreign_format_change_is_not_authorized_or_repaired(self):
        for value in (0x200, 0x400, 0x600):
            with self.subTest(value=value):
                lib = self.reset()
                lib.format_inject(0x400, 0, value)
                self.assertEqual(self.claim(), errno.EAGAIN)
                self.assertEqual(self.trace(), a64.FIVE[:2])
                self.assert_quarantined()

    def test_full_claim_preserves_every_eligible_prior_nonformat_bit(self):
        eligible = [1 << bit for bit in range(32) if not ((FAULT | FORMAT) & (1 << bit))]
        for prior in eligible + [sum(eligible) | 0x600]:
            with self.subTest(prior=prior):
                lib = self.reset()
                lib.bypass_set(3, 0x4058, prior)
                self.assertEqual(self.claim(), 0)
                expected = (prior & ~FORMAT) | 0x400
                self.assertEqual(lib.format_expected(), expected)
                self.assertEqual(lib.format_observed(), expected)
                self.assertEqual(self.trace(), a64.FIVE)
                self.snapshot()

    def test_actual_post_readback_update_preserves_every_prior_nonformat_bit(self):
        for prior in [1 << bit for bit in range(32) if not (FORMAT & (1 << bit))] + [0xffffffff]:
            with self.subTest(prior=prior):
                lib = self.reset()
                self.assertEqual(self.claim(), 0)
                self.assertEqual(lib.format_replay_transition(prior), 0)
                expected = (prior & ~FORMAT) | 0x400
                self.assertEqual(lib.format_expected(), expected)
                self.assertEqual(lib.format_observed(), expected)
                self.assertEqual(lib.host_stat(4), 0)
                self.assertEqual(lib.host_stat(5), 0)

    def test_uncertain_cba2r_readback_never_updates_expected_format_or_routes(self):
        for kind in (1, 2, 3):
            with self.subTest(kind=kind):
                lib = self.reset()
                lib.bypass_inject(kind, 2)
                self.assertEqual(self.claim(), errno.EIO)
                self.assertEqual(self.trace(), a64.FIVE[:2])
                self.assertEqual(lib.format_expected(), 0)
                self.assertEqual(lib.format_observed(), 0x400 if kind == 3 else 0)
                self.assertEqual(lib.host_stat(3), 1000)
                self.assert_quarantined()

    def test_default_four_store_mode_preserves_all_original_io_and_bytes(self):
        for gadget in (0, 1):
            expected = None
            for lib, present in ((self.baseline, 0), (self.lib, 0), (self.lib, 1)):
                self.reset(lib, value=0, present=present, gadget=gadget)
                lib.bypass_seal()
                self.assertEqual(lib.host_start(), 0)
                self.assertEqual(self.trace(lib), a64.FOUR)
                self.assertEqual(lib.format_observed(), 0)
                snapshot = self.snapshot(lib)
                if expected is None:
                    expected = snapshot
                self.assertEqual(snapshot, expected)

    def test_active_enumeration_and_402_fault_keep_exact_full_proof_and_seven_read_diagnostic(self):
        lib = self.reset(gadget=1)
        lib.bypass_seal()
        self.assertEqual(lib.host_start(), 0)
        self.assertEqual([lib.enum_stat(i) for i in range(4)], [1, 0, 0, 0])
        self.assertEqual(self.trace(), a64.FIVE)
        self.assertEqual(lib.format_expected(), 0x400)
        reads = lib.host_stat(1)
        self.assertEqual(lib.enum_authorize(1, 0), 0)
        import_reads = lib.host_stat(1) - reads
        for region, offset, value in ((3, 0x4058, 0x402), (3, 0x4060, 0x82e55000),
                                      (3, 0x4064, 1), (3, 0x4068, 1),
                                      (3, 0x406c, 0), (2, 0x1410, 0xe0)):
            lib.bypass_set(region, offset, value)
        before = self.memory()
        reads = lib.host_stat(1)
        self.assertEqual(lib.enum_authorize(1, 0), errno.EAGAIN)
        self.assertEqual(lib.host_stat(1) - reads, import_reads + 7)
        self.assertEqual(self.memory(), before)
        self.assertEqual(self.trace(), a64.FIVE)
        self.assertIn('FSR=0x402 FAR-words=0x1:82e55000 FSYNR0=0x1 '
                      'FSYNR1=0 CBFRSYNRA=0xe0; diagnostic only', lib.host_logs().decode())
        frozen = self.snapshot()
        self.assertEqual(lib.enum_authorize(1, 0), errno.EBUSY)
        self.assertEqual(self.snapshot(), frozen)
        self.assertEqual(lib.enum_authorize(2, 0), 0)
        self.assertEqual(self.trace(), a64.FIVE)
        self.snapshot()


if __name__ == '__main__':
    unittest.main()
