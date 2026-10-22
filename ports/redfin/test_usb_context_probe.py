"""Actual isolated owner/start C: bounded read-only context-bank observation."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch_events import function
from ports.redfin.test_usb_owned_route import PREFIX, SUFFIX, added_file
from ports.redfin.test_usb_start import PREFIX as START_PREFIX

HERE = Path(__file__).resolve().parent
CB_SIZE = 0x3e000

EXTRA = r'''
#include <stdarg.h>
static uint32_t context_pages[0x3e000/4];
static char logs[32768];static unsigned log_size;
static unsigned route_fault,platform_ok,read_hash,write_hash;
static unsigned mutation_region,mutation_offset,mutation_occurrence,mutation_hits,mutation_value;
static unsigned visits[4][0x3e000/4];
static int model_log(const char *format,...) __attribute__((format(__printf__,1,2)));
static int model_log(const char *format,...){
 va_list args;va_start(args,format);
 int n=vsnprintf(logs+log_size,sizeof(logs)-log_size,format,args);va_end(args);
 if(n<0 || (unsigned)n>=sizeof(logs)-log_size){bad++;return -1;}
 log_size+=(unsigned)n;return n;
}
#define printf model_log
bool redfin_usb_platform(void){return platform_ok;}
'''

LOOKUP = r'''
static int SecureDTLookupEntry(void *from,const char *name,DTEntry *entry){
 (void)from;if(depth<0 || depth>1)bad++;
 if(dt_variant==7)return -1;
 if(!strcmp(name,"/")){*entry=(void *)1;return kSuccess;}
 if(!strcmp(name,"/chosen")){*entry=(void *)2;return kSuccess;}
 if(!strcmp(name,"/redfin-usb-route")){*entry=(void *)3;return route_fault==1?-1:kSuccess;}
 bad++;return -1;
}
'''

PROPERTY = r'''
static int SecureDTGetProperty(DTEntry entry,const char *name,const void **value,unsigned *size){
 if(depth<0 || depth>1)bad++;
 if(entry==(void *)1 && !strcmp(name,"compatible")){
  *value=compatible;*size=compatible_size;return kSuccess;
 }
 if(entry==(void *)2 && !strcmp(name,"dram-base")){
  *value=route_fault==11?NULL:&ram_base;*size=dt_variant==8?4:8;return kSuccess;
 }
 if(entry==(void *)2 && !strcmp(name,"dram-size")){
  *value=route_fault==12?NULL:&ram_size;*size=dt_variant==9?4:8;return kSuccess;
 }
 if(entry==(void *)3){
  static uint8_t unaligned_reg[17],unaligned_sid[5];
  uint64_t reg[]={route_fault==5?0x15004000:0x15000000,route_fault==6?0x4000:0x100000};
  uint32_t sid=route_fault==10?0xe1:0xe0;
  memcpy(unaligned_reg+1,reg,16);memcpy(unaligned_sid+1,&sid,4);
  if(!strcmp(name,"reg")){
   *value=route_fault==3?NULL:unaligned_reg+1;*size=route_fault==4?15:16;
   return route_fault==2?-1:kSuccess;
  }
  if(!strcmp(name,"stream-id")){
   *value=route_fault==8?NULL:unaligned_sid+1;*size=route_fault==9?8:4;
   return route_fault==7?-1:kSuccess;
  }
 }
 bad++;return -1;
}
'''

MAP = r'''
static vm_offset_t ml_io_map(vm_offset_t physical,vm_size_t size){
 if(depth!=1)bad++;
 bool valid=(physical==0x10c000 || physical==0xa60c000 || physical==0x15000000)?size==0x4000:
  physical==0x15080000 && size==0x3e000;
 if(!valid)bad++;
 maps++;return maps==fail_map?0:physical;
}
'''

READ = r'''
static uint32_t host_read(vm_offset_t base,unsigned offset){
 int region=host_region(base);
 unsigned limit=region==3?0x3e000:0x4000;
 if(depth!=1 || region<0 || offset>=limit || (offset&3)){bad++;return 0;}
 bool valid=false;
 if(region==0)valid=offset==0x3000 || offset==0x3004 || offset==0x3010 ||
  offset==0x307c || offset==0x3080 || offset==0x3018 || offset==0x301c;
 if(region==1)valid=offset==0x120 || offset==0x140 || offset==0x110 ||
  offset==0x704 || offset==0x70c || offset==0x400 || offset==0x404 || offset==0x408 || offset==0x40c;
 if(region==2)valid=offset==0 || offset==0x20 || offset==0x24 || offset==0x28 ||
  (offset>=0x800 && offset<0x800+81*4) || (offset>=0xc00 && offset<0xc00+81*4) ||
  (offset>=0x1000 && offset<0x1000+62*4) || (offset>=0x1800 && offset<0x1800+62*4);
 if(region==3)valid=offset/0x1000<62 && ((offset%0x1000)==0 || (offset%0x1000)==0x58);
 if(!valid)bad++;
 uint32_t *page=region==3?context_pages:pages[region];
 if((unsigned)region==mutation_region && offset==mutation_offset && ++mutation_hits==mutation_occurrence)
  page[offset/4]=mutation_value;
 visits[region][offset/4]++;reads++;
 uint32_t value=page[offset/4];
 read_hash=(read_hash^(unsigned)region)*16777619u;read_hash=(read_hash^offset)*16777619u;
 read_hash=(read_hash^value)*16777619u;return value;
}
'''

RESET = r'''
 memset(context_pages,0,sizeof(context_pages));memset(visits,0,sizeof(visits));
 memset(logs,0,sizeof(logs));log_size=route_fault=0;platform_ok=1;
 mutation_region=4;mutation_offset=mutation_occurrence=mutation_hits=mutation_value=0;
 read_hash=write_hash=2166136261u;
 __atomic_store_n(&redfin_initial_usb_lease,0,__ATOMIC_RELEASE);
'''

WRAPPER = r'''
int host_observe(unsigned caller){
#ifdef TEST_CONTEXT_OBSERVER
 return redfin_usb_owned_observe_contexts(caller==1?&other_token:caller==2?NULL:&owner_token);
#else
 (void)caller;return ENOTSUP;
#endif
}
int host_start(void){return redfin_usb_start_initial();}
void host_context(unsigned bank,unsigned field,uint32_t value){
 if(bank>=62 || field>=4){bad++;return;}
 if(field==0)context_pages[bank*0x1000/4]=value;
 if(field==1)pages[2][(0x1000+bank*4)/4]=value;
 if(field==2)pages[2][(0x1800+bank*4)/4]=value;
 if(field==3)context_pages[(bank*0x1000+0x58)/4]=value;
}
void host_mutate(unsigned region,unsigned offset,unsigned occurrence,uint32_t value){
 mutation_region=region;mutation_offset=offset;mutation_occurrence=occurrence;mutation_value=value;mutation_hits=0;
}
void host_route_fault(unsigned value){route_fault=value;}
void host_platform(unsigned value){platform_ok=value;}
unsigned host_visit(unsigned region,unsigned offset){return region<4 && offset<0x3e000?visits[region][offset/4]:0;}
unsigned host_hash(unsigned which){return which?write_hash:read_hash;}
const void *host_context_page(void){return context_pages;}
const char *host_logs(void){return logs;}
unsigned host_lease(void){return __atomic_load_n(&redfin_initial_usb_lease,__ATOMIC_ACQUIRE);}
'''


class USBContextProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.libs = []
        for overlay in (False, True):
            work = root / str(overlay)
            directory = work / 'bsd/dev'
            directory.mkdir(parents=True)
            original = (HERE / 'usb-owned-route.patch').read_text()
            for name in ('redfin_usb_owned.c', 'redfin_usb_owned.h'):
                (directory / name).write_text(added_file(original, 'bsd/dev/' + name))
            (directory / 'redfin_usb_start.c').write_text(added_file(
                (HERE / 'usb-start.patch').read_text(), 'bsd/dev/redfin_usb_start.c'))
            for patch in ['usb-owned-diag.patch'] + (['usb-context-probe.patch'] if overlay else []):
                subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_usb_owned.c',
                                '--include=bsd/dev/redfin_usb_owned.h', '--include=bsd/dev/redfin_usb_start.c',
                                str(HERE / patch)], cwd=work, check=True)
            owned, start = [(directory / name).read_text() for name in ('redfin_usb_owned.c', 'redfin_usb_start.c')]
            owned = owned.replace('*(const volatile uint32_t *)(base + offset)', 'host_read(base,offset)')
            owned = owned.replace('*(volatile uint32_t *)(rf_usb_owner.smmu + offset) = value;',
                                  'host_write(rf_usb_owner.smmu,offset,value);')
            owned = re.sub(r'__asm__ volatile\([^;]*;', 'host_barrier();', owned)
            owned, start = [re.sub(r'^#include.*\n', '', s, flags=re.M) for s in (owned, start)]
            prefix = PREFIX.replace('#define printf(...) ((void)0)', '#define ARM64_BOARD_CONFIG_SWEET 1')
            prefix = prefix.replace('#define LCK_GRP_DECLARE(name, text) int name',
                                    '#define LCK_GRP_DECLARE(name, text) int name __attribute__((unused))')
            prefix = prefix.replace('static uint32_t mutate_value;', 'static uint32_t mutate_value;\n' + EXTRA)
            old_args = re.search(r'static struct host_arg args\[\] = \{.*?\n\};', prefix, re.S).group()
            new_args = re.search(r'static struct arg args\[\]=\{.*?\n\};', START_PREFIX, re.S).group()
            new_args = new_args.replace('struct arg', 'struct host_arg').replace('\n};',
                ',{"redfinusbcontexts",0,false}\n};')
            prefix = prefix.replace(old_args, new_args)
            for signature, replacement in [('static int SecureDTLookupEntry(', LOOKUP),
                                           ('static int SecureDTGetProperty(', PROPERTY),
                                           ('static vm_offset_t ml_io_map(', MAP),
                                           ('static uint32_t host_read(', READ)]:
                prefix = prefix.replace(function(prefix, signature), replacement)
            prefix = prefix.replace('if (base == 0x15000000) return 2;',
                                    'if (base == 0x15000000) return 2;\n if(base==0x15080000)return 3;')
            prefix = prefix.replace(' int region=host_region(base);\n if (depth != 1 || region != 2',
                                    ' int region=host_region(base);\n write_hash=(write_hash^(unsigned)region)*16777619u;\n'
                                    ' write_hash=(write_hash^offset)*16777619u;write_hash=(write_hash^value)*16777619u;\n'
                                    ' if (depth != 1 || region != 2')
            suffix = SUFFIX.replace('void host_reset(void)\n{', 'void host_reset(void)\n{\n' + RESET)
            suffix = suffix.replace('args[i].present=1;args[i].value=i==0 ? 3 : (i==1 || i==2 ? 1 : 0);',
                                    'args[i].present=i<12;args[i].value=i==0?3:i<4?1:0;')
            (work / 'redfin_usb_owned.h').write_text((directory / 'redfin_usb_owned.h').read_text())
            (work / 'model.c').write_text(('#define TEST_CONTEXT_OBSERVER 1\n' if overlay else '') + prefix +
                                         '#include "redfin_usb_owned.h"\n' + owned + start + suffix + WRAPPER)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
            lib.host_root.argtypes = [C.c_char_p, C.c_int, C.c_int]
            lib.host_config.argtypes = [C.c_uint, C.c_uint64]
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            lib.host_logs.restype = C.c_char_p
            for name in ('host_hash', 'host_visit', 'host_lease'):
                getattr(lib, name).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.observer = cls.libs

    def reset(self):
        self.observer.host_reset()
        self.observer.host_arg(b'redfinusbcontexts', 1, 1)

    def logs(self):
        return self.observer.host_logs().decode()

    def memory(self, lib=None):
        lib = lib or self.observer
        return b''.join(C.string_at(lib.host_page(i), 0x4000) for i in range(3)) + \
            C.string_at(lib.host_context_page(), CB_SIZE)

    def readonly(self, result=0):
        self.assertEqual(self.observer.host_stat(2), 0, 'Observer wrote MMIO')
        self.assertEqual(self.observer.host_stat(3), 0, 'Observer delayed or polled')
        self.assertEqual(self.observer.host_stat(4), 0, 'Unsafe MMIO, mapping, DT or locking')
        self.assertEqual(self.observer.host_stat(5), 0, 'Lock leaked')
        return result

    def observe(self, expected=0):
        self.assertEqual(self.observer.host_register(0), 0)
        result = self.observer.host_observe(0)
        self.assertEqual(result, expected)
        return self.readonly(result)

    def bank_evidence(self):
        pattern = (r'REDFIN USB CONTEXT: bank=(\d+) refs-all=(\d+) refs-active=(\d+) '
                   r'SCTLR=(\w+) CBAR=(\w+) CBA2R=(\w+) FSR=(\w+) '
                   r'blank-unreferenced=(\d+) ownership=0')
        values = {int(row[0]): tuple(int(value, 0) for value in row[1:])
                  for row in re.findall(pattern, self.logs())}
        self.assertEqual(len(values), 62)
        self.assertNotIn('ownership=1', self.logs())
        return values

    def test_two_complete_stable_images_are_readonly_and_consume_manager(self):
        self.reset()
        before = self.memory()
        self.observe()
        self.assertEqual(self.memory(), before)
        self.assertEqual(self.observer.host_stat(0), 4)
        self.assertEqual(self.observer.host_stat(6), 4)
        for bank in range(62):
            for region, offset in ((2, 0x1000+4*bank), (2, 0x1800+4*bank),
                                   (3, 0x1000*bank), (3, 0x1000*bank+0x58)):
                self.assertEqual(self.observer.host_visit(region, offset), 2)
        for slot in range(81):
            for offset in (0x800+slot*4, 0xc00+slot*4):
                self.assertEqual(self.observer.host_visit(2, offset), 2)
        for offset in (0, 0x20, 0x24, 0x28):
            self.assertEqual(self.observer.host_visit(2, offset), 5, 'Initial identity plus both snapshot brackets')
        self.assertIn('page-shift=12 banks=62 S2-only=0 CB-offset=0x80000 unknown-refs=0 ownership=0', self.logs())
        before_reads = self.observer.host_stat(1)
        for call in ('host_claim', 'host_revalidate', 'host_retained', 'host_observe'):
            self.assertNotEqual(getattr(self.observer, call)(0), 0)
        self.assertEqual(self.observer.host_stat(1), before_reads)
        self.readonly()

    def test_active_latent_and_unknown_stream_references_never_imply_ownership(self):
        self.reset()
        for slot in range(81):
            self.observer.host_set(2, 0x800+slot*4, 0)
            self.observer.host_set(2, 0xc00+slot*4, 0x20000)
        # Two translations share CB5; the invalid SMR still retains a latent reference.
        self.observer.host_set(2, 0x800, 0x80000021)
        self.observer.host_set(2, 0xc00, 5)
        self.observer.host_set(2, 0xc04, 5)
        # A BYPASS encoding has no translation-bank reference.
        self.observer.host_set(2, 0x808, 0x80000045)
        self.observer.host_set(2, 0xc08, 0x10006)
        for bank, field in ((7, 0), (8, 1), (9, 2), (10, 3)):
            self.observer.host_context(bank, field, 1)
        before = self.memory()
        self.observe()
        self.assertEqual(self.memory(), before)
        evidence = self.bank_evidence()
        self.assertEqual(evidence[5], (2, 1, 0, 0, 0, 0, 0))
        self.assertEqual(evidence[6], (0, 0, 0, 0, 0, 0, 1))
        for bank in range(7, 11):
            self.assertEqual(evidence[bank][-1], 0, 'Any nonzero raw field blocks the blank diagnostic')
        self.assertIn('no CB lease, route publication, writes or DMA', self.logs())
        for invalid in (62, 127, 0x30000):
            with self.subTest(unknown=invalid):
                self.reset()
                for slot in range(81):
                    self.observer.host_set(2, 0x800+slot*4, 0)
                    self.observer.host_set(2, 0xc00+slot*4, 0x20000)
                self.observer.host_set(2, 0xc00, invalid)
                self.observe()
                self.assertIn('unknown-refs=1 ownership=0', self.logs())
                self.assertTrue(all(row[-1] == 0 for row in self.bank_evidence().values()))

    def test_explicit_observer_flag_and_second_proof_remain_mandatory(self):
        for value, present in ((0, 0), (0, 1), (1, 0), (2, 1)):
            self.reset()
            self.observer.host_arg(b'redfinusbcontexts', value, present)
            self.observe(errno.EPERM)
            self.assertEqual(self.observer.host_stat(0), 0)
        self.reset()
        self.observer.host_config(2, 3)  # Registration, first policy, then deny the second policy.
        self.observe(errno.EPERM)
        self.assertEqual(self.observer.host_visit(3, 0), 1)
        self.reset()
        for key, value in ((7, 3), (8, 1), (9, 0x400), (10, 0xa244b000)):
            self.observer.host_config(key, value)
        self.observe(errno.EAGAIN)
        self.assertEqual(self.observer.host_visit(3, 0), 1)

    def test_null_wrong_unregistered_and_lost_policy_cannot_map(self):
        for caller in (0, 1, 2):
            self.reset()
            self.assertNotEqual(self.observer.host_observe(caller), 0)
            self.assertEqual(self.observer.host_stat(0), 0)
            self.readonly()
        for caller in (1, 2):
            self.reset()
            self.assertEqual(self.observer.host_register(0), 0)
            self.assertEqual(self.observer.host_observe(caller), errno.EPERM)
            self.assertEqual(self.observer.host_stat(0), 0)
            self.readonly()
        self.reset()
        self.assertEqual(self.observer.host_register(0), 0)
        self.observer.host_config(1, 0)
        self.assertEqual(self.observer.host_observe(0), errno.EPERM)
        self.assertEqual(self.observer.host_stat(0), 0)
        self.readonly()

    def test_exact_dt_route_and_ram_bounds_are_checked_before_mapping(self):
        for fault in range(1, 13):
            with self.subTest(route=fault):
                self.reset()
                self.observer.host_route_fault(fault)
                self.assertEqual(self.observer.host_register(0), 0)
                self.assertNotEqual(self.observer.host_observe(0), 0)
                self.assertEqual(self.observer.host_stat(0), 0)
                self.readonly()
        for base, size in ((0, 0x4000), (0x80000001, 0x4000), (0x80000000, 0),
                           (0x80000000, 0x4001), (1 << 36, 0x4000),
                           ((1 << 36)-0x4000, 0x8000), (0x15004000, 0x4000),
                           (0x15080000, 0x4000), (0x150fc000, 0x4000)):
            with self.subTest(base=base, size=size):
                self.reset()
                self.observer.host_config(5, base)
                self.observer.host_config(6, size)
                self.assertEqual(self.observer.host_register(0), 0)
                self.assertNotEqual(self.observer.host_observe(0), 0)
                self.assertEqual(self.observer.host_stat(0), 0)
                self.readonly()

    def test_mapping_failures_are_consumed_without_any_write(self):
        for failed in range(1, 5):
            with self.subTest(failed=failed):
                self.reset()
                self.observer.host_config(3, failed)
                self.observe(errno.ENOMEM)
                previous = self.observer.host_stat(0)
                self.assertNotEqual(self.observer.host_observe(0), 0)
                self.assertEqual(self.observer.host_stat(0), previous)
                self.readonly()

    def test_allones_and_unstable_images_fail_without_retry_or_writes(self):
        addresses = [(2, 0x20), (2, 0x24), (2, 0x28), (2, 0),
                     (2, 0x800), (2, 0xc00), (2, 0x1000), (2, 0x1800), (3, 0), (3, 0x58)]
        for region, offset in addresses:
            with self.subTest(region=region, offset=offset):
                self.reset()
                if region == 3:
                    self.observer.host_context(0, 0 if offset == 0 else 3, 0xffffffff)
                else:
                    self.observer.host_set(region, offset, 0xffffffff)
                self.observe(errno.ENOTSUP if region == 2 and offset in (0, 0x20, 0x24, 0x28) else errno.EIO)
                self.assertNotEqual(self.observer.host_observe(0), 0)
                self.readonly()
        for region, offset in addresses:
            with self.subTest(drift=(region, offset)):
                self.reset()
                occurrence = 3 if region == 2 and offset in (0, 0x20, 0x24, 0x28) else 2
                self.observer.host_mutate(region, offset, occurrence, 0x123)
                self.observe(errno.EAGAIN)
                self.assertNotEqual(self.observer.host_observe(0), 0)
                self.readonly()

    def test_unknown_identity_and_controller_activity_refuse_observation(self):
        for offset, value in ((0x20, 0x4c017e50), (0x24, 0x6000003f), (0x28, 0x5110)):
            self.reset()
            self.observer.host_set(2, offset, value)
            self.observe(errno.ENOTSUP)
        for region, offset, value in ((0, 0x3004, 0), (0, 0x3010, 0x80000001),
                                      (1, 0x704, 0x80000000), (1, 0x70c, 0),
                                      (1, 0x40c, 1), (1, 0x408, 0x1000)):
            self.reset()
            self.observer.host_set(region, offset, value)
            self.assertEqual(self.observer.host_register(0), 0)
            self.assertNotEqual(self.observer.host_observe(0), 0)
            self.readonly()

    def test_explicit_start_selects_observer_and_invalid_values_never_register(self):
        self.reset()
        self.observer.host_arg(b'redfinusbcontexts', 1, 1)
        before = self.memory()
        self.assertEqual(self.observer.host_start(), 0)
        self.assertEqual(self.observer.host_stat(6), 4)
        self.assertEqual(self.memory(), before)
        self.assertEqual(self.observer.host_lease(), 1)
        self.assertEqual(self.observer.host_start(), errno.EBUSY)
        self.readonly()
        for value in (2, 3, 0xffffffff):
            self.reset()
            self.observer.host_arg(b'redfinusbcontexts', value, 1)
            self.assertEqual(self.observer.host_start(), errno.ENOTSUP)
            self.assertEqual(self.observer.host_stat(6), 0)
            self.assertEqual(self.observer.host_lease(), 0)
            self.assertEqual(self.observer.host_stat(0), 0)
            self.readonly()

    def test_legacy_start_absent_or_zero_keeps_exact_baseline_mmio(self):
        for present in (0, 1):
            snapshots = []
            for lib in self.libs:
                lib.host_reset()
                lib.host_arg(b'redfinusbcontexts', 0, present)
                self.assertEqual(lib.host_start(), 0)
                snapshots.append(([lib.host_stat(i) for i in range(9)], self.memory(lib),
                                  lib.host_hash(0), lib.host_hash(1)))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[1][0][2], 2)
            self.assertEqual(snapshots[1][0][4:6], [0, 0])


if __name__ == '__main__':
    unittest.main()
