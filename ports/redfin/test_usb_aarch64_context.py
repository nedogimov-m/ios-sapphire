"""Actual USB owner C: optional RW64 changes only the leased bank and route."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_bypass_context as bypass
from ports.redfin import test_usb_bypass_diagnostic as diagnostic
from ports.redfin import test_usb_enumeration_start as enumeration

HERE = Path(__file__).resolve().parent
FOUR = [(3, 0x4000, 0), (2, 0x1010, 0x10000),
        (2, 0xc10, 0x304), (2, 0x810, 0x800000e0)]
FIVE = FOUR[:1] + [(2, 0x1810, 1)] + FOUR[1:]

EXTRA = r'''
static unsigned a64_expected_steps=4,a64_pending,a64_readbacks[5];
static bool a64_raw_override;
static char a64_raw[128];
'''

WRITER = r'''
static __attribute__((unused)) void host_bypass_write(vm_offset_t base,unsigned offset,uint32_t value){
 unsigned n=bypass_attempts++,bank=expected_bank,slot=expected_slot;
 int region=host_region(base);
 const unsigned regions4[]={3,2,2,2},regions5[]={3,2,2,2,2};
 const unsigned offsets4[]={bank*0x1000,0x1000+bank*4,0xc00+slot*4,0x800+slot*4};
 const unsigned offsets5[]={bank*0x1000,0x1800+bank*4,0x1000+bank*4,0xc00+slot*4,0x800+slot*4};
 const uint32_t values4[]={0,0x10000,0x300|bank,0x800000e0};
 const uint32_t values5[]={0,1,0x10000,0x300|bank,0x800000e0};
 const unsigned *regions=a64_expected_steps==5?regions5:regions4;
 const unsigned *offsets=a64_expected_steps==5?offsets5:offsets4;
 const uint32_t *values=a64_expected_steps==5?values5:values4;
 if(depth!=1 || n>=a64_expected_steps || a64_pending || region!=(int)regions[n] ||
    offset!=offsets[n] || value!=values[n]){bad++;return;}
 bypass_bases[n]=(unsigned)region;bypass_offsets[n]=offset;bypass_values[n]=value;
 a64_pending=n+1;stores++;
 uint32_t *page=region==3?context_pages:pages[region];
 uint32_t *shadow=region==3?shadow_context:shadow_pages[region];
 if(!(bypass_fault==1 && n+1==bypass_fault_step)){
  uint32_t observed=bypass_fault==2 && n+1==bypass_fault_step?value^1u:value;
  page[offset/4]=shadow[offset/4]=observed;
 }
 if(memcmp(pages,shadow_pages,sizeof(pages)) || memcmp(context_pages,shadow_context,sizeof(context_pages)))bad++;
 if(bypass_drift_step==n+1)context_pages[(10*0x1000)/4]^=0x100u;
}
static __attribute__((unused)) bool PE_parse_boot_arg_str(const char *name,char *value,int size){
 if(strcmp(name,"redfinusbrw64") || size<=0){bad++;return false;}
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(args[i].name,name)){
  if(!args[i].present)return false;
  char rendered[32];snprintf(rendered,sizeof(rendered),"%u",args[i].value);
  const char *text=a64_raw_override?a64_raw:rendered;
  size_t count=strlen(text);if(count>=(size_t)size)count=(size_t)size-1;
  memcpy(value,text,count);value[count]=0;return true;
 }
 bad++;return false;
}
'''

WRAPPERS = r'''
void a64_reset(unsigned steps){
 a64_expected_steps=steps;a64_pending=0;memset(a64_readbacks,0,sizeof(a64_readbacks));
 a64_raw_override=false;memset(a64_raw,0,sizeof(a64_raw));
}
void a64_text(const char *text){
 a64_raw_override=true;snprintf(a64_raw,sizeof(a64_raw),"%s",text);
}
unsigned a64_readback(unsigned step){return step<5?a64_readbacks[step]:0;}
unsigned a64_steps(void){
#ifdef TEST_AARCH64_CONTEXT
 return rf_usb_bypass.steps;
#else
 return 4;
#endif
}
unsigned a64_target(void){
#ifdef TEST_AARCH64_CONTEXT
 return rf_usb_bypass_target_steps();
#else
 return 4;
#endif
}
void a64_store_count(unsigned stores){rf_usb_bypass.stores=stores;}
'''


class USBAArch64ContextTests(unittest.TestCase):
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
        start = original / 'bsd/dev/redfin_usb_start.c'
        initial = owned.read_text()
        initial_start = start.read_text()
        for patch in ('usb-bypass-diagnostic.patch', 'usb-fault-diagnostic.patch'):
            subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_usb_owned.c',
                            str(HERE / patch)], cwd=original, check=True)
        before = owned.read_text()
        subprocess.run(['git', 'apply', str(HERE / 'usb-aarch64-context.patch')],
                       cwd=original, check=True)
        after, after_start = owned.read_text(), start.read_text()
        cls.actual = after
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.libs = []
        for name, actual, caller in (('base', before, initial_start),
                                     ('rw64', after, after_start)):
            source = template
            seams = ((bypass.host_owned(initial), bypass.host_owned(actual)),
                     (re.sub(r'^#include.*\n', '', initial_start, flags=re.M),
                      re.sub(r'^#include.*\n', '', caller, flags=re.M)),
                     (bypass.WRITER, WRITER),
                     ('bypass_bases[4],bypass_offsets[4],bypass_values[4];',
                      'bypass_bases[5],bypass_offsets[5],bypass_values[5];\n' + EXTRA),
                     ('return n<4?(field==0?', 'return n<5?(field==0?'),
                     ('{"redfinusbsecs",0,false}',
                      '{"redfinusbsecs",0,false},{"redfinusbrw64",0,false}'),
                     ('if(!valid)bad++;\n uint32_t *page=', '''
 if(region==3 && offset/0x1000==4 &&
    ((offset%0x1000)==0x60 || (offset%0x1000)==0x64 ||
     (offset%0x1000)==0x68 || (offset%0x1000)==0x6c))valid=true;
 if(region==2 && offset==0x1410)valid=true;
 if(!valid)bad++;
 if(a64_pending){
  unsigned n=a64_pending-1;
  if((unsigned)region!=bypass_bases[n] || offset!=bypass_offsets[n])bad++;
  a64_readbacks[n]++;a64_pending=0;
 }
 uint32_t *page='''))
            for old, new in seams:
                if source.count(old) != 1:
                    raise AssertionError(f'Actual C model seam changed: {old[:70]}')
                source = source.replace(old, new)
            wrappers = diagnostic.WRAPPERS.replace('void diag_reset(void){diag_barriers=0;}', '')
            wrappers = wrappers.replace('unsigned diag_barrier_count(void){return diag_barriers;}', '')
            work = Path(cls.tmp.name) / name
            work.mkdir()
            for header in original.glob('*.h'):
                shutil.copy2(header, work / header.name)
            model = work / 'model.c'
            model.write_text(('#define TEST_AARCH64_CONTEXT 1\n' if name == 'rw64' else '') +
                             source + wrappers + WRAPPERS)
            library = work / 'model.so'
            result = subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-O0',
                                     '-Wall', '-Wextra', '-Werror', '-I', str(work),
                                     str(model), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
            lib.host_set.argtypes = lib.bypass_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
            lib.host_mutate.argtypes = [C.c_uint, C.c_uint, C.c_uint, C.c_uint32]
            lib.a64_text.argtypes = [C.c_char_p]
            lib.host_logs.restype = C.c_char_p
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            for symbol in ('host_hash', 'host_visit', 'bypass_trace', 'bypass_stat',
                           'a64_steps', 'a64_target', 'a64_readback'):
                getattr(lib, symbol).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.lib = cls.libs

    def reset(self, lib=None, *, value=1, present=1, gadget=0):
        lib = lib or self.lib
        lib.host_reset()
        lib.bypass_reset()
        lib.bypass_fixture()
        lib.enum_reset()
        lib.a64_reset(5 if present and value == 1 else 4)
        lib.host_arg(b'redfinusbcontexts', 0, 1)
        lib.host_arg(b'redfinusbbypass', 1, 1)
        lib.host_arg(b'redfinusbgadget', gadget, 1)
        lib.host_arg(b'redfinusbrw64', value, present)
        return lib

    def memory(self, lib=None):
        lib = lib or self.lib
        return b''.join(C.string_at(lib.host_page(i), 0x4000) for i in range(3)) + \
            C.string_at(lib.host_context_page(), bypass.CB_SIZE)

    def trace(self, lib=None):
        lib = lib or self.lib
        return [tuple(lib.bypass_trace(n, field) for field in range(3))
                for n in range(lib.host_stat(2))]

    def snapshot(self, lib=None):
        lib = lib or self.lib
        stats = tuple(lib.host_stat(i) for i in range(9))
        self.assertEqual(stats[4:6], (0, 0), 'unexpected MMIO/store/order/map/lock')
        return stats, tuple(lib.host_hash(i) for i in range(2)), self.trace(lib), self.memory(lib)

    def claim(self, lib=None):
        lib = lib or self.lib
        lib.bypass_seal()
        self.assertEqual(lib.host_register(0), 0)
        return lib.bypass_claim(0)

    def assert_quarantined(self, lib=None):
        lib = lib or self.lib
        frozen = self.snapshot(lib)
        for call in ('bypass_claim', 'bypass_verify', 'host_claim', 'host_revalidate', 'host_retained'):
            self.assertEqual(getattr(lib, call)(0), errno.EBUSY)
        self.assertEqual(self.snapshot(lib), frozen)

    def test_five_exact_stores_readbacks_and_every_other_byte_preserved(self):
        lib = self.reset()
        expected = bytearray(self.memory())
        self.assertEqual(self.claim(), 0)
        self.assertEqual(self.trace(), FIVE)
        self.assertEqual(lib.a64_steps(), 5)
        self.assertEqual([lib.a64_readback(i) for i in range(5)], [1] * 5)
        self.assertEqual([lib.bypass_stat(i) for i in range(4)], [4, 5, 1, 5])
        for region, offset, value in FIVE:
            at = 0xc000 + offset if region == 3 else region * 0x4000 + offset
            expected[at:at+4] = value.to_bytes(4, 'little')
        self.assertEqual(self.memory(), bytes(expected), 'foreign bank, TTBR/TCR/MAIR, FSR or TLBI changed')
        self.assertEqual(lib.bypass_verify(0), 0)
        self.snapshot()

    def test_absent_and_explicit_zero_preserve_original_four_store_io(self):
        for gadget in (0, 1):
            expected = None
            for lib, present in ((self.baseline, 0), (self.lib, 0), (self.lib, 1)):
                with self.subTest(gadget=gadget, baseline=lib is self.baseline, present=present):
                    self.reset(lib, value=0, present=present, gadget=gadget)
                    lib.bypass_seal()
                    self.assertEqual(lib.host_start(), 0)
                    self.assertEqual(self.trace(lib), FOUR)
                    snapshot = self.snapshot(lib)
                    if expected is None:
                        expected = snapshot
                    self.assertEqual(snapshot, expected)
                    self.assertEqual(lib.a64_steps(), 4)

    def test_invalid_numeric_and_text_flags_fail_before_any_store(self):
        malformed = [(2, None), (0xffffffff, None), (1, b'4294967297'),
                     (0, b'4294967296'), (1, b'0x1'), (1, b'01'), (1, b'1suffix'),
                     (0, b''), (1, b'+1'), (0, b'-0'), (49, b'1'),
                     (1, b'0x100000001'), (1, b'1' * 100)]
        for value, text in malformed:
            for front in (False, True):
                with self.subTest(value=value, text=text, front=front):
                    lib = self.reset(value=value)
                    if text is not None:
                        lib.a64_text(text)
                    self.assertEqual(lib.a64_target(), 0)
                    result = lib.host_start() if front else self.claim()
                    self.assertNotEqual(result, 0)
                    self.assertEqual(lib.host_stat(2), 0)
                    self.assertEqual(lib.host_stat(0), 0)
                    self.assertEqual(lib.enum_stat(0), 0)
                    self.snapshot()

    def test_five_readback_failures_quarantine_each_exact_prefix_without_retry(self):
        for kind in (1, 2, 3):
            for step in range(1, 6):
                with self.subTest(kind=kind, step=step):
                    lib = self.reset()
                    lib.bypass_inject(kind, step)
                    self.assertEqual(self.claim(), errno.EIO)
                    self.assertEqual(self.trace(), FIVE[:step])
                    self.assertEqual(lib.bypass_stat(1), step)
                    self.assertEqual(lib.host_stat(3), 1000)
                    self.assert_quarantined()

    def test_each_boundary_reimports_all_banks_and_stops_after_foreign_drift(self):
        lib = self.reset()
        lib.host_mutate(3, 0x8000, 2, 0x12345678)
        self.assertEqual(self.claim(), errno.EAGAIN)
        self.assertEqual(self.trace(), [])
        self.assert_quarantined()
        for step in range(1, 6):
            with self.subTest(step=step):
                lib = self.reset()
                lib.bypass_drift(step)
                self.assertEqual(self.claim(), errno.EAGAIN)
                self.assertEqual(self.trace(), FIVE[:step])
                self.assertEqual(lib.host_stat(3), 0)
                self.assert_quarantined()

    def test_owned_and_foreign_cba2r_drift_revoke_without_repair(self):
        for offset, value in ((0x1810, 0), (0x1810, 3), (0x1814, 1)):
            with self.subTest(offset=offset, value=value):
                lib = self.reset()
                self.assertEqual(self.claim(), 0)
                lib.bypass_set(2, offset, value)
                before = self.memory()
                self.assertEqual(lib.bypass_verify(0), errno.EAGAIN)
                self.assertEqual(self.memory(), before)
                self.assertEqual(self.trace(), FIVE)
                self.assert_quarantined()

    def test_selected_mode_is_frozen_and_rw64_requires_bypass(self):
        for value in (0, 2):
            lib = self.reset()
            self.assertEqual(self.claim(), 0)
            lib.host_arg(b'redfinusbrw64', value, 1)
            before = self.snapshot()
            self.assertEqual(lib.bypass_verify(0), errno.EPERM)
            self.assertEqual(lib.a64_steps(), 5)
            expected = list(before[0])
            expected[6] = 3  # Permanent quarantine changes only software state.
            self.assertEqual(self.snapshot(), (tuple(expected),) + before[1:])
            self.assert_quarantined()
        lib = self.reset()
        lib.host_arg(b'redfinusbbypass', 0, 1)
        self.assertNotEqual(lib.host_start(), 0)
        self.assertEqual(lib.host_stat(2), 0)
        self.snapshot()

    def test_active_enumeration_accepts_exact_five_and_keeps_halt_authority(self):
        lib = self.reset(gadget=1)
        lib.bypass_seal()
        self.assertEqual(lib.host_start(), 0)
        self.assertEqual(self.trace(), FIVE)
        self.assertEqual([lib.enum_stat(i) for i in range(4)], [1, 0, 0, 0])
        self.assertEqual(lib.enum_authorize(1, 0), 0)
        lib.bypass_set(2, 0x1810, 0)
        self.assertEqual(lib.enum_authorize(1, 0), errno.EAGAIN)
        self.assertEqual(lib.enum_authorize(1, 0), errno.EBUSY)
        self.assertEqual(lib.enum_authorize(2, 0), 0)
        self.assertEqual(self.trace(), FIVE)
        self.snapshot()

    def test_fault_diagnostic_accepts_five_with_only_seven_readonly_words(self):
        for stores in (4, 5, 6):
            lib = self.reset(gadget=1)
            lib.bypass_seal()
            self.assertEqual(lib.host_start(), 0)
            reads = lib.host_stat(1)
            self.assertEqual(lib.diag_verify(0, 0), 0)
            import_reads = lib.host_stat(1) - reads
            lib.a64_store_count(stores)
            for region, offset, value in ((3, 0x4058, 2), (3, 0x4060, 0x82e55000),
                                          (3, 0x4064, 1), (3, 0x4068, 1),
                                          (3, 0x406c, 0), (2, 0x1410, 0xe0)):
                lib.bypass_set(region, offset, value)
            before = self.memory()
            visits = [lib.host_visit(region, offset) for region, offset in
                      ((3, 0x4058), (3, 0x4060), (3, 0x4064), (3, 0x4068),
                       (3, 0x406c), (2, 0x1410))]
            reads = lib.host_stat(1)
            self.assertEqual(lib.diag_verify(0, 0), errno.EAGAIN)
            self.assertEqual(lib.host_stat(1) - reads, import_reads + (7 if stores == 5 else 0))
            self.assertEqual(self.memory(), before)
            self.assertEqual(self.trace(), FIVE)
            delta = [lib.host_visit(region, offset) - count for (region, offset), count in zip(
                ((3, 0x4058), (3, 0x4060), (3, 0x4064), (3, 0x4068),
                 (3, 0x406c), (2, 0x1410)), visits)]
            log = lib.host_logs().decode()
            if stores == 5:
                self.assertEqual(delta, [3, 1, 1, 1, 1, 1])  # snapshot FSR plus 7 diagnostic reads
                self.assertIn('FSR=0x2 FAR-words=0x1:82e55000 FSYNR0=0x1 '
                              'FSYNR1=0 CBFRSYNRA=0xe0; diagnostic only', log)
            else:
                self.assertEqual(delta, [1, 0, 0, 0, 0, 0])
                self.assertNotIn('fault-snapshot', log)
            frozen = self.snapshot()
            self.assertEqual(lib.diag_verify(0, 0), errno.EBUSY)
            self.assertEqual(lib.diag_verify(1, 0), errno.EBUSY)
            self.assertEqual(lib.host_start(), errno.EBUSY)
            self.assertEqual(self.snapshot(), frozen)


if __name__ == '__main__':
    unittest.main()
