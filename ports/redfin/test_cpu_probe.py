"""Compile actual CPU-probe policy/ordering with virtual PSCI/cache operations."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from ports.redfin.test_usb_owned_route import added_file

PATCH = Path(__file__).with_name('cpu-probe.patch')
ARGS = ('debug=0xc serial=3 cpus=1 rd=md0 redfincpu=1 redfinspmi=1 redfinreturn=1 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfinbootid=0x0123456789abcdef')
PREFIX = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define PAGE_SIZE 16384
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef void *DTEntry;
typedef struct {unsigned cpu_id,phys_id;} ml_topology_cpu_t;
typedef struct {unsigned num_cpus;ml_topology_cpu_t *boot_cpu;} ml_topology_info_t;
static ml_topology_cpu_t boot_cpu={0,0};
static ml_topology_info_t topology={1,&boot_cpu};
static char args[1024];
static unsigned fault,dt_fault,pa_fault,smc_fault,ready_fault,mutation;
static unsigned queries,on_calls,cleans,invalidates,waits,logs,violations,order,stage;
static unsigned nested_result,reject_logs,fake_entry_bytes;
static int return_ready=1;
static unsigned char fake_entry[256] __attribute__((aligned(64)));
#define redfin_cpu_probe_entry fake_entry
#define redfin_cpu_probe_entry_end ((unsigned char *)((uintptr_t)fake_entry+fake_entry_bytes))
static char *PE_boot_args(void){return args;}
static const ml_topology_info_t *ml_get_topology_info(void){return &topology;}
int redfin_spmi_return_ready(void){return return_ready;}
static int fake_printf(const char *format,...){if(strstr(format,"REDFIN CPU PROBE:"))logs++;else violations++;if(strstr(format," reject "))reject_logs++;return 0;}
#define printf fake_printf
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
 (void)root;if(dt_fault==1)return 1;
 if(!strcmp(path,"/")){*out=(void*)1;return 0;}
 if(!strcmp(path,"/chosen")){*out=(void*)2;return 0;}
 violations++;return 1;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *bytes){
 static const char compatible[]="google,redfin\0xiaomi,sweet\0qcom,sm7250";
 static const char wrong[]="google,notredfin\0qcom,sm7250";
 static unsigned char unaligned[9];
 if(node==(void*)1 && !strcmp(name,"compatible")){
  *out=dt_fault==2?wrong:compatible;*bytes=dt_fault==2?sizeof(wrong):sizeof(compatible);
  if(dt_fault==3)*bytes-=1;if(dt_fault==4)*out=NULL;return dt_fault==5?1:0;
 }
 if(node==(void*)2 && (!strcmp(name,"dram-base") || !strcmp(name,"dram-size"))){
  uint64_t value=!strcmp(name,"dram-base")?0x180000000ULL:0x80000000ULL;
  if(dt_fault==6)value++;memcpy(unaligned+1,&value,8);*out=unaligned+1;*bytes=dt_fault==7?7:8;return 0;
 }
 violations++;return 1;
}
static uint64_t rf_cpu_reg(unsigned);
static int64_t rf_cpu_smc(uint32_t,uint64_t,uint64_t,uint64_t);
static void rf_cpu_barrier(void);
static void rf_cpu_invalidate(void);
static void delay(unsigned value){if(value!=1000)violations++;waits++;}
'''
SUFFIX = r'''
static uint64_t rf_cpu_reg(unsigned reg){
 const uint64_t values[]={4,0,0x51d0805e,0x101122,0x8444c004,5};
 if(reg>5){violations++;return 0;}
 if(fault==1 && reg==RF_CPU_EL)return 8;
 if(fault==2 && reg==RF_CPU_MPIDR)return 0x100;
 if(fault==3 && reg==RF_CPU_MIDR)return 0x410fd050;
 if(fault==4 && reg==RF_CPU_MMFR0)return 0;
 if(fault==5 && reg==RF_CPU_CTR)return 0;
 if(fault==6 && reg==RF_CPU_SCTLR)return 0;
 if(fault==7 && reg==RF_CPU_MPIDR)return 0x100000000ULL;
 return values[reg];
}
vm_offset_t ml_static_vtop(vm_offset_t va){
 uintptr_t mb=(uintptr_t)rf_cpu_mailbox,entry=(uintptr_t)fake_entry;
 if(va>=mb && va<mb+RF_CPU_PAGE){
  uint64_t base=pa_fault==1?0x180020001ULL:pa_fault==2?0x170020000ULL:0x180020000ULL;
  if(pa_fault==3 && va==mb+RF_CPU_PAGE-1)return base+RF_CPU_PAGE;
  return base+(va-mb);
 }
 if(va>=entry && va<entry+sizeof(fake_entry)){
  uint64_t base=pa_fault==4?0x180020000ULL:pa_fault==5?0x180010002ULL:0x180010000ULL;
  if(pa_fault==6 && va==entry+sizeof(fake_entry)-1)return base+sizeof(fake_entry);
  return base+(va-entry);
 }
 violations++;return 0;
}
static int64_t rf_cpu_smc(uint32_t fn,uint64_t a1,uint64_t a2,uint64_t a3){
 if(fn==RF_CPU_ON){
  on_calls++;if(stage!=4 || cleans!=2 || a1!=RF_CPU_TARGET || a2!=0x180010000ULL || a3!=0x180020000ULL)violations++;
  if(rf_cpu_mailbox->magic!=RF_CPU_MAGIC || rf_cpu_mailbox->target!=RF_CPU_TARGET || !rf_cpu_mailbox->boot_id)violations++;
  stage=5;order=order*10+5;
  if(mutation==4)strcpy(args,"redfincpu=0");
  if(mutation==5)nested_result=(unsigned)redfin_cpu_probe();
  return smc_fault==7?-3:0;
 }
 queries++;if(a2 || a3)violations++;
 if(fn==0x84000000u){if(stage!=0 || a1)violations++;stage=1;order=1;return smc_fault==1?-1:smc_fault==2?2:0x10000;}
 if(fn==0x8400000au && a1==RF_CPU_ON){if(stage!=1)violations++;stage=2;order=order*10+2;return smc_fault==3?-1:0;}
 if(fn==0x8400000au && a1==RF_CPU_AFFINITY){if(stage!=2)violations++;stage=3;order=order*10+3;return smc_fault==4?-1:0;}
 if(fn==RF_CPU_AFFINITY){if(stage!=3 || a1!=RF_CPU_TARGET)violations++;stage=4;order=order*10+4;
  if(mutation==1)strcpy(args,"redfincpu=0");
  return smc_fault==5?0:smc_fault==6?2:smc_fault==8?-1:1;
 }
 violations++;return -1;
}
void CleanPoC_DcacheRegion_Force(vm_offset_t va,size_t bytes){
 cleans++;if(on_calls || stage!=4)violations++;
 if(cleans==1 && (va!=(uintptr_t)rf_cpu_mailbox || bytes!=RF_CPU_PAGE))violations++;
 if(cleans==2 && (va!=(uintptr_t)fake_entry || bytes!=sizeof(fake_entry)))violations++;
 if(mutation==2 && cleans==2)strcpy(args,"redfincpu=0");
 if(mutation==3 && cleans==2)return_ready=0;
}
static void rf_cpu_barrier(void){ }
static void rf_cpu_invalidate(void){
 invalidates++;if(!on_calls || stage!=5)violations++;
 if(invalidates==3 && ready_fault!=1){
  rf_cpu_mailbox->midr=ready_fault==3?0x51d0805e:0x51f0804e;
  rf_cpu_mailbox->mpidr=ready_fault==4?0x100:ready_fault==9?0x100000600ULL:0x600;
  rf_cpu_mailbox->mmfr0=ready_fault==5?0:0x101122;
  rf_cpu_mailbox->current_el=ready_fault==6?12:4;
  rf_cpu_mailbox->sctlr=ready_fault==7?0x30d00801:0x30d00800;
  rf_cpu_mailbox->ctr=ready_fault==8?0:0x8444c004;
  rf_cpu_mailbox->ready=rf_cpu_boot_id+(ready_fault==2);
 }
}
void reset(const char *text){
 memset(rf_cpu_storage,0xa5,sizeof(rf_cpu_storage));rf_cpu_mailbox=NULL;memset(rf_cpu_frozen,0,sizeof(rf_cpu_frozen));
 rf_cpu_frozen_bytes=0;rf_cpu_boot_id=0;rf_cpu_attempted=0;
 fault=dt_fault=pa_fault=smc_fault=ready_fault=mutation=0;
 queries=on_calls=cleans=invalidates=waits=logs=violations=order=stage=nested_result=reject_logs=0;fake_entry_bytes=sizeof(fake_entry);
 return_ready=1;boot_cpu.cpu_id=boot_cpu.phys_id=0;topology.num_cpus=1;topology.boot_cpu=&boot_cpu;
 memset(args,0,sizeof(args));strncpy(args,text,sizeof(args)-1);
}
void set_fault(unsigned kind,unsigned value){
 switch(kind){case 0:fault=value;break;case 1:dt_fault=value;break;case 2:pa_fault=value;break;
 case 3:smc_fault=value;break;case 4:ready_fault=value;break;case 5:mutation=value;break;
 case 6:topology.num_cpus=value;break;case 7:return_ready=(int)value;break;
 case 8:boot_cpu.phys_id=value;break;case 9:topology.boot_cpu=NULL;break;case 10:fake_entry_bytes=value;break;}
}
unsigned stat(unsigned n){
 unsigned changed_outside=0;
 uintptr_t chosen=(uintptr_t)rf_cpu_mailbox,backing=(uintptr_t)rf_cpu_storage;
 for(unsigned i=0;i<sizeof(rf_cpu_storage);i++)
  if((!chosen || backing+i<chosen || backing+i>=chosen+RF_CPU_PAGE) && rf_cpu_storage[i]!=0xa5)changed_outside++;
 const unsigned values[]={queries,on_calls,cleans,invalidates,waits,logs,violations,order,rf_cpu_attempted,nested_result,
  chosen?(unsigned)(chosen-backing):0,(unsigned)(backing&(RF_CPU_PAGE-1)),changed_outside,reject_logs};
 return n<14?values[n]:0;
}
uintptr_t select_mailbox(uintptr_t backing,size_t capacity){return rf_cpu_select_mailbox(backing,capacity);}
void change_args(const char *text){memset(args,0,sizeof(args));strncpy(args,text,sizeof(args)-1);}
'''


class CPUProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        directory = Path(cls.temp.name)
        source = added_file(PATCH.read_text(), 'bsd/dev/redfin_cpu_probe.c')
        source = re.sub(r'^#include .*$','',source,flags=re.M)
        source = source.replace('static unsigned char rf_cpu_storage[2*RF_CPU_PAGE];',
            'static unsigned char rf_cpu_fixture_storage[4*RF_CPU_PAGE];\n'
            '#define rf_cpu_storage (*(unsigned char (*)[2*RF_CPU_PAGE])'
            '(((((uintptr_t)rf_cpu_fixture_storage+RF_CPU_PAGE-1)&~((uintptr_t)RF_CPU_PAGE-1)))+4096))')
        source = re.sub(r'/\* RF_CPU_HW_BEGIN:.*?/\* RF_CPU_HW_END \*/','',source,flags=re.S)
        source = re.sub(r'^extern unsigned char redfin_cpu_probe_entry\[\],redfin_cpu_probe_entry_end\[\];$','',source,flags=re.M)
        (directory/'probe.c').write_text(PREFIX+source+SUFFIX)
        library=directory/('probe.dylib' if __import__('sys').platform=='darwin' else 'probe.so')
        subprocess.run([cc,'-shared','-fPIC','-std=c11','-Wall','-Wextra','-Werror',str(directory/'probe.c'),'-o',str(library)],check=True,capture_output=True)
        cls.lib=C.CDLL(str(library))
        cls.lib.reset.argtypes=[C.c_char_p]
        cls.lib.set_fault.argtypes=[C.c_uint,C.c_uint]
        cls.lib.stat.argtypes=[C.c_uint];cls.lib.stat.restype=C.c_uint
        cls.lib.change_args.argtypes=[C.c_char_p]
        cls.lib.select_mailbox.argtypes=[C.c_size_t,C.c_size_t];cls.lib.select_mailbox.restype=C.c_size_t
        cls.lib.redfin_cpu_probe.restype=C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.lib.reset(ARGS.encode())

    def tearDown(self):
        self.assertEqual(self.lib.stat(6),0,'unsafe PSCI/cache ordering or unexpected hardware access')
        self.assertEqual(self.lib.stat(12),0,'mailbox touched bytes outside its selected owned page')

    def test_success_queries_off_cleans_then_wakes_once_and_reads_only_after_invalidate(self):
        self.assertEqual(self.lib.redfin_cpu_probe(),0)
        self.assertEqual([self.lib.stat(i) for i in (0,1,2,3,4,7,8)],[4,1,2,3,2,12345,2])
        self.assertEqual(self.lib.redfin_cpu_probe(),errno.EBUSY)
        self.assertEqual(self.lib.stat(1),1)

    def test_linker_shifted_backing_selects_complete_aligned_interior_page(self):
        self.assertEqual(self.lib.stat(11),4096)  # The fixture deliberately shifts BSS by4KiB.
        self.assertEqual(self.lib.redfin_cpu_probe(),0)
        self.assertEqual(self.lib.stat(10),12288)
        self.assertLessEqual(self.lib.stat(10)+16384,32768)
        self.assertEqual(self.lib.stat(12),0)
        self.assertEqual(self.lib.redfin_cpu_probe(),errno.EBUSY)
        self.assertEqual(self.lib.stat(10),12288)  # No re-selection/release after completion.

    def test_selection_refuses_short_overflow_or_unowned_spans(self):
        select=self.lib.select_mailbox
        self.assertEqual(select(0x1000,32768),0x4000)
        self.assertEqual(select(0x8000,32768),0x8000)
        maximum=(1<<(8*C.sizeof(C.c_size_t)))-1
        for backing,capacity in ((0,32768),(0x1000,16384),(0x1000,16383),
                                 (maximum-4096,32768),(maximum-8192,4096)):
            with self.subTest(backing=backing,capacity=capacity):
                self.assertEqual(select(backing,capacity),0)

    def test_all_required_flags_exact_and_competing_writers_off(self):
        for token in ARGS.split()[2:]:
            key=token.split('=')[0]
            for replacement in ('',key,key+'=0x100000001',key+'=2'):
                with self.subTest(token=token,replacement=replacement):
                    text=ARGS.replace(token,replacement)
                    self.lib.reset(text.encode())
                    self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
                    self.assertEqual(self.lib.stat(1),0)
                    self.assertEqual(self.lib.redfin_cpu_probe(),errno.EBUSY)
        for extra in ('redfinusb=1','redfinroot=1','redfinfb=1','redfintouchevents=1','ufsroot=userdata','cpumask=1','cpus=1','redfincpu=1'):
            self.lib.reset((ARGS+' '+extra).encode())
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
            self.assertEqual(self.lib.stat(1),0)

    def test_optional_zero_flags_are_exact_and_nonce_is_canonical_nonzero(self):
        self.lib.reset((ARGS+' redfinusb=0 redfinroot=0 redfinfb=0').encode())
        self.assertEqual(self.lib.redfin_cpu_probe(),0)
        for extra in (' redfinusb=0 redfinusb=0',' redfinfb',' redfintrace=0x100000000'):
            self.lib.reset((ARGS+extra).encode())
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
            self.assertEqual(self.lib.stat(1),0)
        for nonce in ('0x0000000000000000','0x0123456789abcdeF','0X0123456789abcdef','0x1123456789abcdef0'):
            self.lib.reset(ARGS.replace('0x0123456789abcdef',nonce).encode())
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
            self.assertEqual(self.lib.stat(1),0)

    def test_runtime_boot_core_return_topology_and_cache_capabilities_fail_before_psci(self):
        for kind,values in [(0,range(1,8)),(6,[0,2]),(7,[0]),(8,[0x100]),(9,[1])]:
            for value in values:
                with self.subTest(kind=kind,value=value):
                    self.lib.reset(ARGS.encode());self.lib.set_fault(kind,value)
                    self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
                    self.assertEqual(self.lib.stat(0),0)
                    self.assertEqual(self.lib.stat(1),0)

    def test_exact_adt_ram_and_physical_mailbox_entry_bounds_before_any_psci(self):
        for kind,values in [(1,range(1,8)),(2,range(1,7))]:
            for value in values:
                with self.subTest(kind=kind,value=value):
                    self.lib.reset(ARGS.encode());self.lib.set_fault(kind,value)
                    self.assertIn(self.lib.redfin_cpu_probe(),(errno.ENXIO,errno.EINVAL))
                    self.assertEqual(self.lib.stat(0),0)
                    self.assertEqual(self.lib.stat(1),0)
                    if kind==2:
                        self.assertEqual(self.lib.stat(13),2)

    def test_entry_size_rejection_is_diagnosed_before_psci(self):
        for size in (0,513):
            self.lib.reset(ARGS.encode());self.lib.set_fault(10,size)
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.EINVAL)
            self.assertEqual(self.lib.stat(0),0)
            self.assertEqual(self.lib.stat(1),0)
            self.assertEqual(self.lib.stat(13),1)

    def test_firmware_feature_rejection_busy_pending_and_errors_never_cpu_on(self):
        for value in (1,2,3,4,5,6,8):
            with self.subTest(value=value):
                self.lib.reset(ARGS.encode());self.lib.set_fault(3,value)
                self.assertIn(self.lib.redfin_cpu_probe(),(errno.ENOTSUP,errno.EBUSY))
                self.assertEqual(self.lib.stat(1),0)
                self.assertEqual(self.lib.stat(2),0)

    def test_frozen_flags_and_verified_return_rechecked_after_queries_and_clean(self):
        for value in (1,2,3):
            self.lib.reset(ARGS.encode());self.lib.set_fault(5,value)
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.EPERM)
            self.assertEqual(self.lib.stat(1),0)

    def test_cpu_on_failure_consumes_lease_without_poll_retry_free_or_cpu_off(self):
        self.lib.set_fault(3,7)
        self.assertEqual(self.lib.redfin_cpu_probe(),errno.EIO)
        self.assertEqual(self.lib.stat(1),1)
        self.assertEqual(self.lib.stat(3),0)
        self.assertEqual(self.lib.redfin_cpu_probe(),errno.EBUSY)

    def test_missing_or_wrong_nonce_ready_times_out_bounded_and_retains_core(self):
        for value in (1,2):
            self.lib.reset(ARGS.encode());self.lib.set_fault(4,value)
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.ETIMEDOUT)
            self.assertEqual([self.lib.stat(i) for i in (1,3,4,8)],[1,500,500,2])
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.EBUSY)

    def test_bad_secondary_capabilities_are_reported_but_never_enter_xnu(self):
        for value in range(3,10):
            self.lib.reset(ARGS.encode());self.lib.set_fault(4,value)
            self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
            self.assertEqual(self.lib.stat(1),1)
            self.assertEqual(self.lib.stat(3),3)

    def test_post_wake_policy_loss_and_recursive_attempt_never_retry(self):
        self.lib.set_fault(5,4)
        self.assertEqual(self.lib.redfin_cpu_probe(),errno.ENOTSUP)
        self.assertEqual(self.lib.stat(1),1)
        self.lib.reset(ARGS.encode());self.lib.set_fault(5,5)
        self.assertEqual(self.lib.redfin_cpu_probe(),0)
        self.assertEqual(self.lib.stat(9),errno.EBUSY)

    def test_entry_is_stackless_store_bounded_publication_last_and_wfe_only(self):
        patch=PATCH.read_text()
        entry=patch.split('+LEXT(redfin_cpu_probe_entry)\n',1)[1].split('+LEXT(redfin_cpu_probe_entry_end)',1)[0]
        self.assertNotRegex(entry,r'(?m)^\+\s*(?:bl|blr|ret|smc)\b')
        self.assertNotRegex(entry,r'\b(?:sp|ICC_[A-Z0-9_]+|TTBR[0-9A-Z_]*|TCR_EL[12])\b')
        stores=re.findall(r'^\+ str x\d+, \[x0, #(\d+)\]',entry,re.M)
        self.assertEqual(stores,['64','72','80','88','96','104','120'])
        self.assertIn('+ dsb sy\n+ str x3, [x0, #120]\n+ dsb sy',entry)
        self.assertIn('+ wfe\n+ b Lrf_cpu_probe_park',entry)
        self.assertLess(entry.index('+ tst x2, x3'),entry.index('+ str x5, [x0, #64]'))
        self.assertIn('dc ivac, %0',patch)
        self.assertIn('+ MOV64 x6, 0xff00ffffff\n+ and x5, x4, x6',entry)

    def test_aarch64_entry_and_real_register_smc_cache_wrappers_compile_without_execution(self):
        if sys.platform!='darwin':
            self.skipTest('Darwin AArch64 assembler smoke')
        compiler=shutil.which('cc')
        source=added_file(PATCH.read_text(),'bsd/dev/redfin_cpu_probe.c')
        source=re.sub(r'^#include .*$','',source,flags=re.M)
        source=re.sub(r'^extern unsigned char redfin_cpu_probe_entry\[\],redfin_cpu_probe_entry_end\[\];$','',source,flags=re.M)
        stanza=PATCH.read_text().split('diff --git a/osfmk/arm64/start.s',1)[1].split('\ndiff --git ',1)[0]
        assembly='\n'.join(line[1:] for line in stanza.splitlines() if line.startswith('+') and not line.startswith('+++'))
        macros=r'''#define EXT(x) _ ## x
#define LEXT(x) _ ## x ## :
.text
.macro MOV64
 movk $0, #((($1) >> 48) & 0xffff), lsl #48
 movk $0, #((($1) >> 32) & 0xffff), lsl #32
 movk $0, #((($1) >> 16) & 0xffff), lsl #16
 movk $0, #((($1) >> 0) & 0xffff), lsl #0
.endmacro
'''
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'hardware.c').write_text(PREFIX+source)
            (directory/'entry.S').write_text(macros+assembly+'\n')
            for name in ('hardware.c','entry.S'):
                result=subprocess.run([compiler,'-arch','arm64','-c',str(directory/name),'-o',str(directory/(name+'.o'))],capture_output=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

if __name__=='__main__':
    unittest.main()
