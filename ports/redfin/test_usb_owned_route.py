"""Compile the actual isolated USB owner manager against a bounded MMIO model."""
import ctypes as C
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def added_file(patch, path):
    marker = '+++ b/' + path + '\n'
    section = patch.split(marker, 1)[1].split('\ndiff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+')) + '\n'


PREFIX = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#define printf(...) ((void)0)
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
#define kSuccess 0
#define LCK_GRP_DECLARE(name, text) int name
#define LCK_MTX_DECLARE(name, group) int name
static uint32_t pages[3][0x4000 / 4];
static int maps, reads, stores, delays, bad, depth, policy_calls;
static uint32_t store_offsets[2], store_values[2];
static int ready, policy_ok, deny_at, fail_map, dt_variant, write_mode;
static int mutate_at, mutate_region;
static unsigned mutate_offset;
static uint32_t mutate_value;
static uint64_t ram_base, ram_size;
static char root_arg[16];
static int root_present, ufsroot_present;
static char compatible[256];
static unsigned compatible_size;
static int owner_token, other_token, context_token;
struct host_arg { const char *name; uint32_t value; int present; };
static struct host_arg args[] = {
 {"redfinusb",3,1},{"cpus",1,1},{"redfinreturn",1,1},
 {"sweetusb",0,1},{"modem",0,1},{"wifi",0,1},{"gpu",0,1},
 {"redfinufs",0,1},{"ufsrw",0,1},{"rootrw",0,1},{"redfinroot",0,1}
};
static void lck_mtx_lock(int *lock) { (void)lock; if (depth++) bad++; }
static void lck_mtx_unlock(int *lock) { (void)lock; if (--depth) bad++; }
static void host_barrier(void) { if (depth != 1) bad++; }
static void delay(unsigned us) { if (depth != 1 || us != 1) bad++; delays++; }
static int redfin_spmi_return_ready(void) { return ready; }
static bool PE_parse_boot_argn(const char *name, void *value, size_t size)
{
 for (unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++) {
  if (!strcmp(name,args[i].name)) {
   if (!args[i].present) return false;
   if (size != 4) { bad++; return false; }
   memcpy(value,&args[i].value,4);return true;
  }
 }
 if (!strcmp(name,"rd")) {
  if (!root_present) return false;
  if (size != sizeof(root_arg)) { bad++; return false; }
  memcpy(value,root_arg,size);return true;
 }
 if (!strcmp(name,"ufsroot")) {
  if (!ufsroot_present) return false;
  if (size) ((char *)value)[0]=0;
  return true;
 }
 bad++;return false;
}
static int SecureDTLookupEntry(void *from,const char *name,DTEntry *entry)
{
 (void)from;
 if (depth != 1) bad++;
 if (dt_variant == 7) return -1;
 if (!strcmp(name,"/")) { *entry=(void *)1;return kSuccess; }
 if (!strcmp(name,"/chosen")) { *entry=(void *)2;return kSuccess; }
 bad++;return -1;
}
static int SecureDTGetProperty(DTEntry entry,const char *name,const void **value,unsigned *size)
{
 if (depth != 1) bad++;
 if (entry == (void *)1 && !strcmp(name,"compatible")) {
  *value=compatible;*size=compatible_size;return kSuccess;
 }
 if (entry == (void *)2 && !strcmp(name,"dram-base")) {
  *value=&ram_base;*size=dt_variant == 8 ? 4 : 8;return kSuccess;
 }
 if (entry == (void *)2 && !strcmp(name,"dram-size")) {
  *value=&ram_size;*size=dt_variant == 9 ? 4 : 8;return kSuccess;
 }
 bad++;return -1;
}
static vm_offset_t ml_io_map(vm_offset_t physical,vm_size_t size)
{
 if (depth != 1 || size != 0x4000) bad++;
 maps++;
 if (physical != 0x10c000 && physical != 0xa60c000 && physical != 0x15000000) bad++;
 return maps == fail_map ? 0 : physical;
}
static int host_region(vm_offset_t base)
{
 if (base == 0x10c000) return 0;
 if (base == 0xa60c000) return 1;
 if (base == 0x15000000) return 2;
 bad++;return -1;
}
static uint32_t host_read(vm_offset_t base,unsigned offset)
{
 int region=host_region(base);
 if (depth != 1 || region < 0 || offset >= 0x4000 || (offset & 3)) { bad++;return 0; }
 bool valid=false;
 if (region == 0) valid=offset==0x3000 || offset==0x3004 || offset==0x3010 ||
  offset==0x307c || offset==0x3080 || offset==0x3018 || offset==0x301c;
 if (region == 1) valid=offset==0x120 || offset==0x140 || offset==0x110 ||
  offset==0x704 || offset==0x70c || offset==0x400 || offset==0x404 ||
  offset==0x408 || offset==0x40c;
 if (region == 2) valid=offset==0 || offset==0x20 || offset==0x24 || offset==0x28 ||
  (offset>=0x800 && offset<0x800+81*4) || (offset>=0xc00 && offset<0xc00+81*4);
 if (!valid) bad++;
 reads++;return pages[region][offset/4];
}
static void host_write(vm_offset_t base,unsigned offset,uint32_t value)
{
 int region=host_region(base);
 if (depth != 1 || region != 2 || stores >= 2 ||
     !((offset==0xc04 && value==0x10300) || (offset==0x804 && value==0x800000e0))) {
  bad++;return;
 }
 if (stores == 0 && (offset != 0xc04 || (pages[2][0x804/4] & 0x80000000))) bad++;
 if (stores == 1 && (offset != 0x804 || pages[2][0xc04/4] != 0x10300)) bad++;
 store_offsets[stores]=offset;store_values[stores]=value;stores++;
 if (offset == 0xc04 && write_mode == 1) return;
 if (offset == 0xc04 && write_mode == 2) value=0x20300;
 if (offset == 0x804 && write_mode == 3) return;
 pages[2][offset/4]=value;
}
static bool host_policy(const void *caller,void *context)
{
 policy_calls++;
 if (!caller || context != &context_token) { bad++;return false; }
 if (policy_calls == mutate_at) pages[mutate_region][mutate_offset/4]=mutate_value;
 return policy_ok && (!deny_at || policy_calls < deny_at);
}
'''


SUFFIX = r'''
void host_reset(void)
{
 memset(&rf_usb_owner,0,sizeof(rf_usb_owner));
 memset(pages,0,sizeof(pages));
 maps=reads=stores=delays=bad=depth=policy_calls=0;
 memset(store_offsets,0,sizeof(store_offsets));memset(store_values,0,sizeof(store_values));
 ready=policy_ok=1;deny_at=fail_map=dt_variant=write_mode=0;
 mutate_at=mutate_region=0;mutate_offset=mutate_value=0;
 ram_base=0x80000000ULL;ram_size=0x200000000ULL;
 memset(root_arg,0,sizeof(root_arg));memcpy(root_arg,"md0",3);
 root_present=1;ufsroot_present=0;
 memset(compatible,0,sizeof(compatible));
 const char initial[]="google,redfin\0qcom,sm7250";
 memcpy(compatible,initial,sizeof(initial));compatible_size=sizeof(initial);
 for (unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++) {
  args[i].present=1;args[i].value=i==0 ? 3 : (i==1 || i==2 ? 1 : 0);
 }
 pages[0][0x3004/4]=0x80000000;
 const unsigned clocks[]={0x3010,0x307c,0x3080,0x3018,0x301c};
 for (unsigned i=0;i<5;i++) pages[0][clocks[i]/4]=1;
 pages[1][0x120/4]=0x5533330a;pages[1][0x140/4]=0x40000000;
 pages[1][0x110/4]=0x2000;pages[1][0x704/4]=0x10f00000;
 pages[1][0x70c/4]=0xd3510c;pages[1][0x400/4]=0xa244a000;
 pages[1][0x408/4]=0x80001000;
 pages[2][0x20/4]=0x4c017e51;pages[2][0x24/4]=0x6000003e;
 pages[2][0x28/4]=0x5111;pages[2][0]=0x2c0406;
 pages[2][0x800/4]=0x80000021;pages[2][0xc00/4]=0x302;
 pages[2][0x804/4]=0x01230077;pages[2][0xc04/4]=0x20044;
 pages[2][0x808/4]=0x80000045;pages[2][0xc08/4]=0x10301;
 pages[2][0x80c/4]=0x4000000a;pages[2][0xc0c/4]=0x2beef;
}
void host_arg(const char *name,uint32_t value,int present)
{
 for (unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)
  if (!strcmp(name,args[i].name)) { args[i].value=value;args[i].present=present;return; }
 bad++;
}
void host_root(const char *value,int present,int ufs_present)
{
 memset(root_arg,0,sizeof(root_arg));
 size_t count=strlen(value);if (count>sizeof(root_arg)) count=sizeof(root_arg);
 memcpy(root_arg,value,count);root_present=present;ufsroot_present=ufs_present;
}
void host_config(unsigned key,uint64_t value)
{
 switch (key) {
 case 0:ready=value;break;case 1:policy_ok=value;break;case 2:deny_at=value;break;
 case 3:fail_map=value;break;case 4:
  dt_variant=value;
  if (value==1) compatible_size=0;
  if (value==2) { strcpy(compatible,"qcom,sm7250");compatible_size=strlen(compatible)+1; }
  if (value==3) { strcpy(compatible,"google,redfin");compatible_size=strlen(compatible)+1; }
  if (value==4) compatible[compatible_size-1]='x';
  if (value==5) compatible[0]=0;
  if (value==6) compatible_size=257;
  break;
 case 5:ram_base=value;break;case 6:ram_size=value;break;
 case 7:mutate_at=value;break;case 8:mutate_region=value;break;
 case 9:mutate_offset=value;break;case 10:mutate_value=value;break;
 case 11:write_mode=value;break;default:bad++;break;
 }
}
void host_set(unsigned region,unsigned offset,uint32_t value)
{ if (region>=3 || offset>=0x4000 || (offset&3)) bad++;else pages[region][offset/4]=value; }
const void *host_page(unsigned region) { return region<3 ? pages[region] : NULL; }
int host_register(unsigned variant)
{
 struct redfin_usb_owned_policy policy={host_policy,&context_token};
 if (variant==3) policy.exclusive=NULL;
 if (variant==4) policy_ok=0;
 return redfin_usb_owned_register(variant==1 ? NULL : (variant==5 ? &other_token : &owner_token),
                                  variant==2 ? NULL : &policy);
}
int host_claim(unsigned caller)
{ return redfin_usb_owned_claim(caller==1 ? &other_token : (caller==2 ? NULL : &owner_token)); }
int host_revalidate(unsigned caller)
{ return redfin_usb_owned_revalidate(caller==1 ? &other_token : (caller==2 ? NULL : &owner_token)); }
int host_retained(unsigned caller)
{ return redfin_usb_owned_route_retained(caller==1 ? &other_token : (caller==2 ? NULL : &owner_token)); }
int host_stat(unsigned key)
{
 switch (key) { case 0:return maps;case 1:return reads;case 2:return stores;
 case 3:return delays;case 4:return bad;case 5:return depth;case 6:return rf_usb_owner.state;
 case 7:return rf_usb_owner.slot;case 8:return policy_calls;default:return -1; }
}
uint32_t host_store(unsigned index,unsigned field)
{ return index<2 ? (field ? store_values[index] : store_offsets[index]) : 0; }
'''


class USBOwnedRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        patch = Path(__file__).with_name('usb-owned-route.patch').read_text()
        header = added_file(patch, 'bsd/dev/redfin_usb_owned.h')
        code = added_file(patch, 'bsd/dev/redfin_usb_owned.c')
        code = '\n'.join(line for line in code.splitlines()
                         if not line.startswith('#include ')
                         and line != '#if defined(ARM64_BOARD_CONFIG_SWEET)'
                         and line != '#endif')
        replacements = {
            'uint32_t value = *(const volatile uint32_t *)(base + offset);':
                'uint32_t value = host_read(base,offset);',
            '*(volatile uint32_t *)(rf_usb_owner.smmu + offset) = value;':
                'host_write(rf_usb_owner.smmu,offset,value);',
            '__asm__ volatile("dmb oshld" ::: "memory");': 'host_barrier();',
            '__asm__ volatile("dmb oshst" ::: "memory");': 'host_barrier();',
            '__asm__ volatile("dsb osh" ::: "memory");': 'host_barrier();',
        }
        for old, new in replacements.items():
            if code.count(old) != 1:
                raise AssertionError('actual C model seam changed: ' + old)
            code = code.replace(old, new)
        source = root / 'owned.c'
        source.write_text(PREFIX + header + code + SUFFIX)
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise RuntimeError('C compiler required for the actual owner manager test')
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-variable', '-shared', '-fPIC', str(source),
                        '-o', str(root / 'owned.so')], check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(root / 'owned.so'))
        cls.lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
        cls.lib.host_root.argtypes = [C.c_char_p, C.c_int, C.c_int]
        cls.lib.host_config.argtypes = [C.c_uint, C.c_uint64]
        cls.lib.host_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
        cls.lib.host_page.argtypes = [C.c_uint]
        cls.lib.host_page.restype = C.c_void_p
        cls.lib.host_store.restype = C.c_uint32

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.lib.host_reset()

    def tearDown(self):
        self.assertEqual(self.stat(4), 0, 'out-of-contract MMIO, mapping, or lock use')
        self.assertEqual(self.stat(5), 0, 'owner lock left held')

    def stat(self, key):
        return self.lib.host_stat(key)

    def config(self, key, value):
        self.lib.host_config(key, value)

    def reg(self, region, offset, value):
        self.lib.host_set(region, offset, value)

    def images(self):
        return tuple(C.string_at(self.lib.host_page(region), 0x4000) for region in range(3))

    def claim(self):
        self.assertEqual(self.lib.host_register(0), 0)
        return self.lib.host_claim(0)

    def quarantined(self, stores=0):
        self.assertEqual(self.stat(6), 3)
        self.assertEqual(self.stat(2), stores)
        before = (self.stat(0), self.stat(1), self.stat(2))
        self.assertNotEqual(self.lib.host_claim(0), 0)
        self.assertNotEqual(self.lib.host_revalidate(0), 0)
        self.assertNotEqual(self.lib.host_retained(0), 0)
        self.assertEqual((self.stat(0), self.stat(1), self.stat(2)), before)

    def mutate_on_policy(self, call, region, offset, value):
        for key, setting in ((7, call), (8, region), (9, offset), (10, value)):
            self.config(key, setting)

    def test_registration_requires_trusted_callback(self):
        for variant in (1, 2, 3, 4):
            with self.subTest(variant=variant):
                self.lib.host_reset()
                self.assertNotEqual(self.lib.host_register(variant), 0)
                self.assertNotEqual(self.lib.host_claim(0), 0)
                self.assertEqual((self.stat(0), self.stat(1), self.stat(2), self.stat(6)), (0, 0, 0, 0))

    def test_single_owner_and_caller_identity(self):
        self.assertEqual(self.lib.host_register(0), 0)
        self.assertNotEqual(self.lib.host_register(5), 0)
        for caller in (1, 2):
            self.assertNotEqual(self.lib.host_claim(caller), 0)
            self.assertNotEqual(self.lib.host_revalidate(caller), 0)
            self.assertNotEqual(self.lib.host_retained(caller), 0)
        self.assertEqual((self.stat(0), self.stat(1), self.stat(2), self.stat(6)), (0, 0, 0, 1))
        self.assertEqual(self.lib.host_claim(0), 0)

    def test_required_runtime_args(self):
        for name, wrong in ((b'redfinusb', 1), (b'cpus', 2), (b'redfinreturn', 0)):
            for present in (0, 1):
                with self.subTest(name=name, present=present):
                    self.lib.host_reset()
                    self.lib.host_arg(name, wrong, present)
                    self.assertNotEqual(self.claim(), 0)
                    self.assertEqual(self.stat(0), 0)
                    self.quarantined()

    def test_competing_paths_and_write_flags(self):
        for name in (b'sweetusb', b'modem', b'wifi', b'gpu', b'redfinufs', b'ufsrw', b'rootrw', b'redfinroot'):
            with self.subTest(name=name):
                self.lib.host_reset()
                self.lib.host_arg(name, 1, 1)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(0), 0)
                self.quarantined()

    def test_disabled_optional_args_may_be_absent(self):
        for name in (b'sweetusb', b'modem', b'wifi', b'gpu', b'redfinufs', b'ufsrw', b'rootrw', b'redfinroot'):
            self.lib.host_arg(name, 0, 0)
        self.assertEqual(self.claim(), 0)

    def test_md0_only_and_return_proof(self):
        for value, present, ufs in ((b'disk0s1', 1, 0), (b'md0', 0, 0),
                                    (b'md0', 1, 1), (b'md0xxxxxxxxxxxxx', 1, 0)):
            with self.subTest(value=value, present=present, ufs=ufs):
                self.lib.host_reset()
                self.lib.host_root(value, present, ufs)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(0), 0)
                self.quarantined()
        self.lib.host_reset()
        self.config(0, 0)
        self.assertNotEqual(self.claim(), 0)
        self.assertEqual(self.stat(0), 0)

    def test_platform_and_ram_are_validated_before_mapping(self):
        for variant in range(1, 10):
            with self.subTest(variant=variant):
                self.lib.host_reset()
                self.config(4, variant)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(0), 0)
                self.quarantined()
        for base, size in ((0, 0x4000), (0x80000000, 0), (0x80000001, 0x4000),
                           (0x80000000, 1), (1 << 36, 0x4000),
                           ((1 << 36)-0x4000, 0x8000),
                           (0x10c000, 0x4000), (0xa60c000, 0x4000), (0x15000000, 0x4000)):
            with self.subTest(base=base, size=size):
                self.lib.host_reset()
                self.config(5, base)
                self.config(6, size)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(0), 0)
                self.quarantined()

    def test_mapping_failures_never_store(self):
        for mapping in (1, 2, 3):
            with self.subTest(mapping=mapping):
                self.lib.host_reset()
                self.config(3, mapping)
                self.assertNotEqual(self.claim(), 0)
                self.quarantined()

    def test_power_reset_and_each_clock_gate(self):
        failures = [(0x3004, 0), (0x3004, 0x80000001), (0x3000, 1)]
        failures += [(offset, value) for offset in (0x3010, 0x307c, 0x3080, 0x3018, 0x301c)
                     for value in (0, 0x80000001)]
        for offset, value in failures:
            with self.subTest(offset=offset, value=value):
                self.lib.host_reset()
                self.reg(0, offset, value)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(0), 2)
                self.quarantined()

    def test_core_identity_reset_halt_and_event_ring_gates(self):
        failures = ((0x120, 0), (0x140, 0x20000000), (0x110, 0x1000),
                    (0x110, 0x2800), (0x704, 0x90f00000), (0x704, 0x50f00000), (0x704, 0x30f00000),
                    (0x70c, 0), (0x400, 0), (0x400, 0xa244a001),
                    (0x404, 16), (0x408, 0x1000), (0x408, 0x80002000), (0x40c, 4))
        for offset, value in failures:
            with self.subTest(offset=offset, value=value):
                self.lib.host_reset()
                self.reg(1, offset, value)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(0), 2)
                self.quarantined()

    def test_smmu_format_and_fault_policy_gates(self):
        for offset, value in ((0x20, 0), (0x24, 0x6000003f), (0x28, 0x5112),
                              (0, 0x2c0407), (0, 0x2c040e), (0, 0x2c0006),
                              (0x80c, 0xffffffff), (0xc0c, 0xffffffff)):
            with self.subTest(offset=offset, value=value):
                self.lib.host_reset()
                self.reg(2, offset, value)
                self.assertNotEqual(self.claim(), 0)
                self.quarantined()

    def test_existing_exact_or_masked_usb_route_is_rejected(self):
        for smr in (0x800000e0, 0x800100e1, 0x80ff0000):
            with self.subTest(smr=smr):
                self.lib.host_reset()
                self.reg(2, 0x808, smr)
                self.assertNotEqual(self.claim(), 0)
                self.quarantined()

    def test_no_invalid_slot_is_rejected(self):
        for slot in range(81):
            self.reg(2, 0x800+slot*4, 0x80001000+slot)
        self.assertNotEqual(self.claim(), 0)
        self.quarantined()

    def test_success_only_changes_one_imported_pair_in_order(self):
        before = self.images()
        self.assertEqual(self.claim(), 0)
        self.assertEqual((self.stat(0), self.stat(2), self.stat(3), self.stat(6), self.stat(7)),
                         (3, 2, 0, 2, 1))
        self.assertEqual([(self.lib.host_store(i, 0), self.lib.host_store(i, 1)) for i in range(2)],
                         [(0xc04, 0x10300), (0x804, 0x800000e0)])
        expected = bytearray(before[2])
        expected[0xc04:0xc08] = (0x10300).to_bytes(4, 'little')
        expected[0x804:0x808] = (0x800000e0).to_bytes(4, 'little')
        self.assertEqual(self.images(), (before[0], before[1], bytes(expected)))
        self.assertEqual(self.lib.host_revalidate(0), 0)
        self.assertEqual(self.stat(2), 2)
        self.assertNotEqual(self.lib.host_claim(0), 0)
        self.assertEqual(self.stat(2), 2)

    def test_full_cr0_is_preserved_without_hardcoding_observation(self):
        self.reg(2, 0, 0x2c0406 ^ 0x10000)
        self.assertEqual(self.claim(), 0)

    def test_nonmatching_route_becoming_matching_prevents_first_write(self):
        self.mutate_on_policy(3, 2, 0x808, 0x800000e0)
        self.assertNotEqual(self.claim(), 0)
        self.quarantined()

    def test_import_mutations_after_first_write_prevent_publication(self):
        for offset, value in ((0x808, 0x800000e0), (0xc08, 0x10000),
                              (0x80c, 0x4000000b), (0xc0c, 0x2beee), (0, 0x2d0406)):
            with self.subTest(offset=offset):
                self.lib.host_reset()
                self.mutate_on_policy(4, 2, offset, value)
                self.assertNotEqual(self.claim(), 0)
                self.quarantined(1)
                self.assertEqual(self.images()[2][0x804:0x808], (0x01230077).to_bytes(4, 'little'))

    def test_bypass_refusal_has_bounded_readback_and_no_fallback(self):
        for mode in (1, 2):
            with self.subTest(mode=mode):
                self.lib.host_reset()
                self.config(11, mode)
                self.assertNotEqual(self.claim(), 0)
                self.assertEqual(self.stat(3), 1000)
                self.quarantined(1)

    def test_smr_readback_failure_is_not_retried_or_rolled_back(self):
        self.config(11, 3)
        self.assertNotEqual(self.claim(), 0)
        self.assertEqual(self.stat(3), 1000)
        self.quarantined(2)
        self.assertEqual(self.images()[2][0xc04:0xc08], (0x10300).to_bytes(4, 'little'))

    def test_policy_loss_at_each_transaction_boundary_quarantines(self):
        for call, stores in ((2, 0), (3, 0), (4, 1), (5, 2)):
            with self.subTest(call=call):
                self.lib.host_reset()
                self.config(2, call)
                self.assertNotEqual(self.claim(), 0)
                self.quarantined(stores)

    def test_halt_or_mask_loss_after_first_write_prevents_publication(self):
        for offset, value in ((0x70c, 0), (0x704, 0x90f00000),
                              (0x408, 0x1000), (0x40c, 4), (0x400, 0xa244b000)):
            with self.subTest(offset=offset):
                self.lib.host_reset()
                self.mutate_on_policy(4, 1, offset, value)
                self.assertNotEqual(self.claim(), 0)
                self.quarantined(1)

    def test_postpublication_mutation_retains_route_and_quarantines(self):
        self.mutate_on_policy(5, 2, 0xc08, 0x10000)
        self.assertNotEqual(self.claim(), 0)
        self.quarantined(2)
        self.assertEqual(self.images()[2][0x804:0x808], (0x800000e0).to_bytes(4, 'little'))

    def test_revalidation_is_read_only_and_detects_any_imported_change(self):
        for region, offset, value in ((2, 0x808, 0x800000e0), (2, 0xc0c, 1),
                                     (2, 0x804, 0x800100e0), (2, 0xc04, 0x20300),
                                     (0, 0x3010, 0), (1, 0x40c, 4)):
            with self.subTest(region=region, offset=offset):
                self.lib.host_reset()
                self.assertEqual(self.claim(), 0)
                self.reg(region, offset, value)
                before = self.images()
                self.assertNotEqual(self.lib.host_revalidate(0), 0)
                self.assertEqual(self.images(), before)
                self.quarantined(2)

    def test_active_route_check_allows_core_changes_but_never_writes(self):
        self.assertEqual(self.claim(), 0)
        self.reg(1, 0x704, 0x90f00000)
        self.reg(1, 0x70c, 0)
        self.reg(1, 0x400, 0x10004000)
        self.reg(1, 0x408, 0x1000)
        self.reg(1, 0x40c, 4)
        before = self.images()
        reads = self.stat(1)
        self.assertEqual(self.lib.host_retained(0), 0)
        self.assertEqual(self.stat(1)-reads, 4+2*81, 'active check only reads SMMU')
        self.assertEqual(self.images(), before)
        self.assertEqual(self.stat(2), 2)
        self.assertNotEqual(self.lib.host_revalidate(0), 0)
        self.quarantined(2)

    def test_active_route_check_keeps_full_route_and_owner_policy(self):
        for region, offset, value in ((2, 0x808, 0x800000e0), (2, 0xc0c, 1),
                                     (2, 0x804, 0x800100e0), (2, 0xc04, 0x20300),
                                     (2, 0, 0x2d0406), (2, 0x24, 0x6000003f)):
            with self.subTest(region=region, offset=offset):
                self.lib.host_reset()
                self.assertEqual(self.claim(), 0)
                self.reg(region, offset, value)
                before = self.images()
                self.assertNotEqual(self.lib.host_retained(0), 0)
                self.assertEqual(self.images(), before)
                self.quarantined(2)
        for kind in ('policy', 'runtime', 'platform'):
            with self.subTest(kind=kind):
                self.lib.host_reset()
                self.assertEqual(self.claim(), 0)
                if kind == 'policy':
                    self.config(1, 0)
                elif kind == 'runtime':
                    self.lib.host_arg(b'redfinroot', 1, 1)
                else:
                    self.config(4, 2)
                self.assertNotEqual(self.lib.host_retained(0), 0)
                self.quarantined(2)

    def test_active_route_check_requires_a_published_route(self):
        self.assertNotEqual(self.lib.host_retained(0), 0)
        self.assertEqual(self.lib.host_register(0), 0)
        self.assertNotEqual(self.lib.host_retained(0), 0)
        self.assertEqual((self.stat(0), self.stat(1), self.stat(2), self.stat(6)), (0, 0, 0, 1))


if __name__ == '__main__':
    unittest.main()
