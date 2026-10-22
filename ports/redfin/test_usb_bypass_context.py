"""Actual SMMU bypass-context allocator: owned writes, fresh proof and quarantine."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_context_probe as context_model

HERE = Path(__file__).resolve().parent
CB_SIZE = 0x3e000
EXTRA = r'''
static unsigned marker_fault,bypass_attempts,bypass_fault,bypass_fault_step,bypass_drift_step;
static unsigned expected_bank,expected_slot,bypass_bases[4],bypass_offsets[4],bypass_values[4];
static uint32_t shadow_pages[3][0x4000/4],shadow_context[0x3e000/4];
'''

WRITER = r'''
static __attribute__((unused)) void host_bypass_write(vm_offset_t base,unsigned offset,uint32_t value){
 unsigned n=bypass_attempts++,bank=expected_bank,slot=expected_slot;
 int region=host_region(base);
 const unsigned regions[]={3,2,2,2};
 const unsigned offsets[]={bank*0x1000,0x1000+bank*4,0xc00+slot*4,0x800+slot*4};
 const uint32_t values[]={0,0x10000,0x300|bank,0x800000e0};
 if(depth!=1 || n>=4 || region!=(int)regions[n] || offset!=offsets[n] || value!=values[n]){bad++;return;}
 bypass_bases[n]=(unsigned)region;bypass_offsets[n]=offset;bypass_values[n]=value;
 stores++;
 uint32_t *page=region==3?context_pages:pages[region];
 uint32_t *shadow=region==3?shadow_context:shadow_pages[region];
 if(!(bypass_fault==1 && n+1==bypass_fault_step)){
  uint32_t observed=bypass_fault==2 && n+1==bypass_fault_step?value^1u:value;
  page[offset/4]=shadow[offset/4]=observed;
 }
 if(memcmp(pages,shadow_pages,sizeof(pages)) || memcmp(context_pages,shadow_context,sizeof(context_pages)))bad++;
 /* A foreign change after this store must stop the next boundary, never be repaired. */
 if(bypass_drift_step==n+1)context_pages[(10*0x1000)/4]^=0x100u;
}
'''

WRAPPERS = r'''
void bypass_reset(void){
 marker_fault=bypass_attempts=bypass_fault=bypass_fault_step=bypass_drift_step=0;
 expected_bank=4;expected_slot=4;
 memset(bypass_bases,0,sizeof(bypass_bases));memset(bypass_offsets,0,sizeof(bypass_offsets));
 memset(bypass_values,0,sizeof(bypass_values));
#ifdef TEST_BYPASS_CONTEXT
 memset(&rf_usb_bypass,0,sizeof(rf_usb_bypass));
#endif
}
void bypass_fixture(void){
 for(unsigned slot=0;slot<81;slot++){pages[2][(0x800+slot*4)/4]=0;pages[2][(0xc00+slot*4)/4]=0x20000;}
 for(unsigned bank=0;bank<62;bank++){
  context_pages[bank*0x1000/4]=bank==4?0xa0ac116:0x38622100;
  context_pages[(bank*0x1000+0x58)/4]=0;
  pages[2][(0x1000+bank*4)/4]=pages[2][(0x1800+bank*4)/4]=0;
  /* Untouched TTBR/TCR/MAIR bytes carry independent sentinels. */
  for(unsigned offset=4;offset<0x1000;offset+=4)
   if(offset!=0x58)context_pages[(bank*0x1000+offset)/4]=0xa5000000u^(bank<<12)^offset;
 }
 for(unsigned bank=0;bank<3;bank++){
  pages[2][(0x800+bank*4)/4]=0x80000021u+bank;
  pages[2][(0xc00+bank*4)/4]=bank;
  context_pages[bank*0x1000/4]=0xe0;context_pages[(bank*0x1000+0x58)/4]=0x400;
  pages[2][(0x1000+bank*4)/4]=0x1f000;pages[2][(0x1800+bank*4)/4]=1;
 }
 pages[2][0x80c/4]=0x80000100; /* Valid fault route keeps stream slot3 occupied. */
 pages[2][0xc14/4]=0; /* Invalid SMR5 still retains a latent CB0 translation reference. */
 pages[2][0xc10/4]=0x20044; /* Chosen invalid slot4 must retain this until its own store. */
 context_pages[3*0x1000/4]=0xe0;context_pages[(3*0x1000+0x58)/4]=0x400;
 pages[2][0x100c/4]=0x100ff;pages[2][0x180c/4]=1;
}
void bypass_seal(void){memcpy(shadow_pages,pages,sizeof(pages));memcpy(shadow_context,context_pages,sizeof(context_pages));}
void bypass_expected(unsigned bank,unsigned slot){expected_bank=bank;expected_slot=slot;}
void bypass_inject(unsigned kind,unsigned step){bypass_fault=kind;bypass_fault_step=step;}
void bypass_drift(unsigned step){bypass_drift_step=step;}
void bypass_marker(unsigned fault){marker_fault=fault;}
void bypass_set(unsigned region,unsigned offset,uint32_t value){
 if(region==3 && offset<sizeof(context_pages) && !(offset&3))context_pages[offset/4]=value;
 else host_set(region,offset,value);
}
int bypass_claim(unsigned caller){
#ifdef TEST_BYPASS_CONTEXT
 return redfin_usb_owned_claim_bypass(caller==1?&other_token:caller==2?NULL:&owner_token);
#else
 (void)caller;return ENOTSUP;
#endif
}
int bypass_verify(unsigned caller){
#ifdef TEST_BYPASS_CONTEXT
 return redfin_usb_owned_revalidate_bypass(caller==1?&other_token:caller==2?NULL:&owner_token);
#else
 (void)caller;return ENOTSUP;
#endif
}
unsigned bypass_stat(unsigned key){
#ifdef TEST_BYPASS_CONTEXT
 if(key==0)return rf_usb_bypass.bank;if(key==1)return rf_usb_bypass.stores;
 if(key==2)return rf_usb_bypass.lease;if(key==3)return rf_usb_owner.diag_stores;
 if(key>=10 && key<138)return rf_usb_bypass.reserved[key-10];
#else
 (void)key;
#endif
 return 0;
}
unsigned bypass_trace(unsigned n,unsigned field){
 return n<4?(field==0?bypass_bases[n]:field==1?bypass_offsets[n]:bypass_values[n]):0;
}
'''


def host_owned(source):
    source = source.replace('*(const volatile uint32_t *)(base + offset)', 'host_read(base,offset)')
    source = source.replace('*(volatile uint32_t *)(rf_usb_owner.smmu + offset) = value;',
                            'host_write(rf_usb_owner.smmu,offset,value);')
    pattern = r'__asm__ volatile\("str %w0, \[%1\]"\s*:\s*:\s*"r"\(value\),\s*"r"\(base\+offset\)\s*:\s*"memory"\);'
    source = re.sub(pattern, 'host_bypass_write(base,offset,value);', source)
    source = re.sub(r'__asm__ volatile\([^;]*;', 'host_barrier();', source)
    return re.sub(r'^#include.*\n', '', source, flags=re.M)


class USBBypassContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        class Fixture(context_model.USBContextProbeTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        original_root = Path(Fixture.temp.name) / 'True'
        template = (original_root / 'model.c').read_text()
        dev = original_root / 'bsd/dev'
        before_owned = (dev / 'redfin_usb_owned.c').read_text()
        before_start = (dev / 'redfin_usb_start.c').read_text()
        subprocess.run(['git', 'apply', str(HERE / 'usb-bypass-context.patch')], cwd=original_root, check=True)
        after_owned = (dev / 'redfin_usb_owned.c').read_text()
        after_start = (dev / 'redfin_usb_start.c').read_text()
        # Verify the production write seam before replacing it for the host compiler.
        cls.writer_source = after_owned.split('rf_usb_bypass_hw_store(', 1)[1].split('\n}', 1)[0]
        if '"r"(value)' not in cls.writer_source or '"rZ"' in cls.writer_source:
            raise AssertionError('Zero store must use the plain-r GPR constraint')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.libs = []
        for fixed in (False, True):
            source = template
            assert source.count(host_owned(before_owned)) == 1
            source = source.replace(host_owned(before_owned), host_owned(after_owned if fixed else before_owned))
            before = re.sub(r'^#include.*\n', '', before_start, flags=re.M)
            after = re.sub(r'^#include.*\n', '', after_start, flags=re.M)
            assert source.count(before) == 1
            source = source.replace(before, after if fixed else before)
            source = source.replace('static unsigned visits[4][0x3e000/4];',
                                    'static unsigned visits[4][0x3e000/4];\n' + EXTRA)
            source = source.replace('static bool host_policy(', WRITER + '\nstatic bool host_policy(')
            source = source.replace('{"redfinusbcontexts",0,false}',
                                    '{"redfinusbcontexts",0,false},{"redfinusbbypass",0,false}')
            source = source.replace(' if(entry==(void *)3){', r'''
 if(entry==(void *)3 && !strcmp(name,"ns-context-allocator")){
  static uint8_t raw_marker[5];uint32_t marker=marker_fault==4?0:marker_fault==5?2:1;
  memcpy(raw_marker+1,&marker,4);*value=marker_fault==2?NULL:raw_marker+1;*size=marker_fault==3?3:4;
  return marker_fault==1?-1:kSuccess;
 }
 if(entry==(void *)3){''')
            source = source.replace('uint32_t value=page[offset/4];', r'''
 uint32_t value=page[offset/4];
 if(bypass_fault==3 && bypass_attempts==bypass_fault_step && bypass_attempts &&
    (unsigned)region==bypass_bases[bypass_attempts-1] && offset==bypass_offsets[bypass_attempts-1])value=0xffffffffu;
''')
            work = root / str(fixed)
            work.mkdir()
            # The extended header is harmless for baseline and keeps declarations identical.
            (work / 'redfin_usb_owned.h').write_text((dev / 'redfin_usb_owned.h').read_text())
            (work / 'model.c').write_text(('#define TEST_BYPASS_CONTEXT 1\n' if fixed else '') + source + WRAPPERS)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
            lib.host_root.argtypes = [C.c_char_p, C.c_int, C.c_int]
            lib.host_config.argtypes = [C.c_uint, C.c_uint64]
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            lib.host_logs.restype = C.c_char_p
            for name in ('host_hash', 'host_visit', 'host_lease', 'bypass_stat', 'bypass_trace'):
                getattr(lib, name).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.fixed = cls.libs

    def reset(self, realistic=True, lib=None):
        lib = lib or self.fixed
        lib.host_reset()
        lib.bypass_reset()
        if realistic:
            lib.bypass_fixture()
        lib.host_arg(b'redfinusbcontexts', 0, 1)
        lib.host_arg(b'redfinusbbypass', 1, 1)

    def memory(self, lib=None):
        lib = lib or self.fixed
        return b''.join(C.string_at(lib.host_page(i), 0x4000) for i in range(3)) + C.string_at(lib.host_context_page(), CB_SIZE)

    def claim(self, expected=0):
        self.fixed.bypass_seal()
        self.assertEqual(self.fixed.host_register(0), 0)
        result = self.fixed.bypass_claim(0)
        self.assertEqual(result, expected)
        self.clean()
        return result

    def clean(self):
        self.assertEqual(self.fixed.host_stat(4), 0, 'Unexpected MMIO/map, foreign mutation, write order or lock')
        self.assertEqual(self.fixed.host_stat(5), 0)
        self.assertLessEqual(self.fixed.host_stat(2), 4)

    def trace(self):
        return [tuple(self.fixed.bypass_trace(n, field) for field in range(3)) for n in range(self.fixed.host_stat(2))]

    def test_first_fit4_has_four_exact_stores_and_preserves_every_other_byte(self):
        self.reset()
        before = bytearray(self.memory())
        self.claim()
        self.assertEqual(self.fixed.host_stat(6), 5)
        self.assertEqual([self.fixed.bypass_stat(i) for i in range(4)], [4, 4, 1, 4])
        self.assertEqual(self.trace(), [(3, 0x4000, 0), (2, 0x1010, 0x10000),
                                        (2, 0xc10, 0x304), (2, 0x810, 0x800000e0)])
        for region, offset, value in self.trace():
            at = 3*0x4000+offset if region == 3 else region*0x4000+offset
            before[at:at+4] = value.to_bytes(4, 'little')
        self.assertEqual(self.memory(), bytes(before))
        self.assertEqual(self.fixed.host_stat(3), 0)
        self.assertEqual(self.fixed.bypass_verify(0), 0)
        self.assertEqual(self.fixed.host_stat(2), 4)
        for call in ('host_claim', 'host_revalidate', 'host_retained', 'host_observe', 'bypass_claim'):
            self.assertEqual(getattr(self.fixed, call)(0), errno.EBUSY)
        self.clean()

    def test_allocator_reserves_latent_refs_gr1_m1_and_each_native_fault_bit(self):
        reservations = [(3, 0x4000, 1), (2, 0x1010, 1), (2, 0x1810, 1)] + [
            (3, 0x4058, 1 << bit) for bit in (1, 2, 3, 4, 5, 6, 7, 8, 30, 31)] + [(2, 0xc14, 4)]
        for region, offset, value in reservations:
            with self.subTest(region=region, offset=offset, value=value):
                self.reset()
                self.fixed.bypass_set(region, offset, value)
                self.fixed.bypass_expected(5, 4)
                self.claim()
                self.assertEqual(self.fixed.bypass_stat(0), 5)
                self.assertEqual(self.fixed.bypass_stat(14), 1)
        # Non-fault FSR bit10 and inherited SCTLR fields with M=0 do not grant ownership or reserve a bank.
        self.reset()
        self.fixed.bypass_set(3, 0x4058, 0x400)
        self.claim()
        self.assertEqual(self.fixed.bypass_stat(0), 4)

    def test_unknown_refs_existing_sid_or_exhausted_resources_never_write(self):
        for s2cr in (62, 127, 0x30000):
            self.reset()
            self.fixed.bypass_set(2, 0xc14, s2cr)
            self.claim(errno.ENOTSUP)
            self.assertEqual(self.fixed.host_stat(2), 0)
        self.reset()
        self.fixed.bypass_set(2, 0x800, 0x800000e0)
        self.claim(errno.EEXIST)
        self.assertEqual(self.fixed.host_stat(2), 0)
        self.reset()
        for bank in range(4, 62):
            self.fixed.bypass_set(3, bank*0x1000, 1)
        self.claim(errno.ENOSPC)
        self.assertEqual(self.fixed.host_stat(2), 0)
        self.reset()
        for slot in range(81):
            self.fixed.bypass_set(2, 0x800+slot*4, 0x80000100+slot)
        self.claim(errno.ENOSPC)
        self.assertEqual(self.fixed.host_stat(2), 0)

    def test_each_write_drop_coercion_or_allones_quarantines_exact_prefix_without_retry(self):
        full = [(3, 0x4000, 0), (2, 0x1010, 0x10000), (2, 0xc10, 0x304), (2, 0x810, 0x800000e0)]
        for kind in (1, 2, 3):
            for step in range(1, 5):
                with self.subTest(kind=kind, step=step):
                    self.reset()
                    self.fixed.bypass_inject(kind, step)
                    self.claim(errno.EIO)
                    self.assertEqual(self.trace(), full[:step])
                    self.assertEqual(self.fixed.bypass_stat(1), step)
                    self.assertEqual(self.fixed.host_stat(6), 3)
                    self.assertEqual(self.fixed.host_stat(3), 1000)
                    before = (self.fixed.host_stat(1), self.fixed.host_stat(2), self.memory())
                    self.assertEqual(self.fixed.bypass_claim(0), errno.EBUSY)
                    self.assertEqual(self.fixed.bypass_verify(0), errno.EBUSY)
                    self.assertEqual((self.fixed.host_stat(1), self.fixed.host_stat(2), self.memory()), before)
                    self.clean()

    def test_fresh_import_and_each_store_boundary_drift_prevent_next_store(self):
        self.reset()
        self.fixed.host_mutate(3, 0x8000, 2, 0x12345678)
        self.claim(errno.EAGAIN)
        self.assertEqual(self.fixed.host_stat(2), 0)
        for step in range(1, 5):
            with self.subTest(step=step):
                self.reset()
                self.fixed.bypass_drift(step)
                self.claim(errno.EAGAIN)
                self.assertEqual(self.fixed.host_stat(2), step)
                self.assertEqual(self.fixed.host_stat(3), 0)
                self.assertEqual(self.fixed.host_stat(6), 3)

    def test_revalidation_checks_owned_cb_stream_and_all_imported_state(self):
        targets = [(3, 0x4000, 1), (2, 0x1010, 0x20000), (2, 0x1810, 1), (3, 0x4058, 2),
                   (2, 0xc10, 0x305), (2, 0x810, 0x800000e1), (3, 0x5000, 0),
                   (2, 0xc00, 1), (2, 0, 0x2c0407), (1, 0x400, 0xa244b000)]
        for region, offset, value in targets:
            with self.subTest(region=region, offset=offset):
                self.reset()
                self.claim()
                self.fixed.bypass_set(region, offset, value)
                self.assertNotEqual(self.fixed.bypass_verify(0), 0)
                self.assertEqual(self.fixed.host_stat(6), 3)
                self.assertEqual(self.fixed.host_stat(2), 4)
                self.assertEqual(self.fixed.bypass_verify(0), errno.EBUSY)
                self.clean()

    def test_exact_dt_marker_ram_policy_caller_and_map_failures_cannot_publish(self):
        for fault in range(1, 6):
            self.reset()
            self.fixed.bypass_marker(fault)
            self.claim(errno.EPERM)
            self.assertEqual(self.fixed.host_stat(0), 0)
        for base, size in ((0x15004000, 0x4000), (0x15080000, 0x4000), (0x150fc000, 0x4000),
                           (0, 0x4000), (0x80000001, 0x4000), (1 << 36, 0x4000)):
            self.reset()
            self.fixed.host_config(5, base)
            self.fixed.host_config(6, size)
            self.claim(errno.EPERM)
            self.assertEqual(self.fixed.host_stat(0), 0)
        for failed in range(1, 5):
            self.reset()
            self.fixed.host_config(3, failed)
            self.claim(errno.ENOMEM)
            self.assertEqual(self.fixed.host_stat(2), 0)
        for caller in (1, 2):
            self.reset()
            self.assertEqual(self.fixed.host_register(0), 0)
            self.assertEqual(self.fixed.bypass_claim(caller), errno.EPERM)
            self.assertEqual(self.fixed.host_stat(0), 0)
            self.clean()

    def test_unknown_allones_state_or_lost_policy_never_publishes_or_retries(self):
        addresses = [(2, 0), (2, 0x20), (2, 0x24), (2, 0x28), (2, 0x940), (2, 0xd40),
                     (2, 0x10f4), (2, 0x18f4), (3, 0x3d000), (3, 0x3d058)]
        for region, offset in addresses:
            with self.subTest(allones=(region, offset)):
                self.reset()
                self.fixed.bypass_set(region, offset, 0xffffffff)
                self.claim(errno.ENOTSUP if region == 2 and offset < 0x30 else errno.EIO)
                self.assertEqual(self.fixed.host_stat(2), 0)
                reads = self.fixed.host_stat(1)
                self.assertEqual(self.fixed.bypass_claim(0), errno.EBUSY)
                self.assertEqual(self.fixed.host_stat(1), reads)
        self.reset()
        self.claim()
        calls = self.fixed.host_stat(8)
        for denied in range(2, calls+1):
            with self.subTest(denied=denied):
                self.reset()
                self.fixed.host_config(2, denied)
                self.claim(errno.EPERM)
                self.assertEqual(self.fixed.host_stat(6), 3)
                self.assertEqual(self.fixed.host_stat(3), 0)
                self.assertEqual(self.fixed.bypass_claim(0), errno.EBUSY)
        for bypass, present, contexts in ((0, 0, 0), (0, 1, 0), (1, 1, 1), (2, 1, 0)):
            self.reset()
            self.fixed.host_arg(b'redfinusbbypass', bypass, present)
            self.fixed.host_arg(b'redfinusbcontexts', contexts, 1)
            self.claim(errno.EPERM)
            self.assertEqual(self.fixed.host_stat(0), 0)

    def test_dsts_allones_cannot_prove_controller_halt_on_any_route_path(self):
        self.reset()
        self.fixed.host_set(1, 0x70c, 0xffffffff)
        self.claim(errno.EBUSY)
        self.assertEqual(self.fixed.host_stat(2), 0)
        self.reset()
        self.claim()
        self.fixed.host_set(1, 0x70c, 0xffffffff)
        self.assertEqual(self.fixed.bypass_verify(0), errno.EBUSY)
        self.assertEqual(self.fixed.host_stat(6), 3)
        self.assertEqual(self.fixed.host_stat(2), 4)
        self.clean()
        for contexts in (0, 1):
            self.reset(realistic=False)
            self.fixed.host_arg(b'redfinusbbypass', 0, 1)
            self.fixed.host_arg(b'redfinusbcontexts', contexts, 1)
            self.fixed.host_set(1, 0x70c, 0xffffffff)
            self.assertEqual(self.fixed.host_start(), errno.EBUSY)
            self.assertEqual(self.fixed.host_stat(2), 0)
            self.clean()

    def test_start_mutual_exclusion_invalid_flags_and_legacy_apis_stay_unchanged(self):
        self.reset()
        self.fixed.bypass_seal()
        self.assertEqual(self.fixed.host_start(), 0)
        self.assertEqual(self.fixed.host_stat(6), 5)
        self.assertEqual(self.fixed.host_stat(2), 4)
        self.clean()
        for bypass, contexts in ((1, 1), (2, 0), (0xffffffff, 0)):
            self.reset()
            self.fixed.host_arg(b'redfinusbbypass', bypass, 1)
            self.fixed.host_arg(b'redfinusbcontexts', contexts, 1)
            self.assertEqual(self.fixed.host_start(), errno.ENOTSUP)
            self.assertEqual(self.fixed.host_stat(0), 0)
            self.assertEqual(self.fixed.host_stat(6), 0)
            self.clean()
        for present in (0, 1):
            snapshots = []
            for lib in self.libs:
                self.reset(realistic=False, lib=lib)
                lib.host_arg(b'redfinusbbypass', 0, present)
                self.assertEqual(lib.host_start(), 0)
                snapshots.append(([lib.host_stat(i) for i in range(9)], self.memory(lib), lib.host_hash(0), lib.host_hash(1)))
            self.assertEqual(snapshots[0], snapshots[1])


if __name__ == '__main__':
    unittest.main()
