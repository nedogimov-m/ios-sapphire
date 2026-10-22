"""Actual SMP return verifier: observer reads only, frozen policy, no UP latch."""
import ctypes as C
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).parent
ARGS = ('debug=0xc serial=3 cpus=2 keepsyms=1 -noprogress rd=md0 sweettouch=0 '
        'sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 '
        'redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfinbootid=0x0123456789abcdef')
PREFIX = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#define PAGE_SIZE 16384
#define CPU_TOPOLOGY_VERSION 1
#define CLUSTER_TYPE_SMP 0
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
typedef struct {unsigned cpu_id,phys_id,cluster_id,die_id,cluster_type,l2_cache_id,l3_cache_id,l2_cache_size,l3_cache_size;} ml_topology_cpu_t;
typedef struct {unsigned cluster_id,cluster_type,num_cpus,first_cpu_id;uint64_t cpu_mask;} ml_topology_cluster_t;
typedef struct {unsigned version,num_cpus,max_cpu_id,num_clusters,max_cluster_id,max_die_id;
 ml_topology_cpu_t *cpus,*boot_cpu;ml_topology_cluster_t *clusters,*boot_cluster;} ml_topology_info_t;
static ml_topology_cpu_t cpus[2];
static ml_topology_cluster_t cluster;
static ml_topology_info_t topology;
static char args[608];
static unsigned fault,dt_fault,map_fault,mutation,reads,writes,maps,polls,relaxes,violations;
static unsigned logs,masked,restored,observes,imem_reads,old_calls,old_ready,cas_fault,cas_tries;
static unsigned spare,subtype;
static uint64_t counter,frequency,mpidr,current_el,sctlr;
static bool irqs;
static uint64_t rf_smr_mpidr(void){return mpidr;}
static uint64_t rf_smr_el(void){return current_el;}
static uint64_t rf_smr_sctlr(void){return sctlr;}
static const char *PE_boot_args(void){return args;}
static const ml_topology_info_t *ml_get_topology_info(void){return mutation==9?NULL:&topology;}
int redfin_spmi_return_ready(void){old_calls++;return old_ready;}
static bool ml_set_interrupts_enabled(bool value){bool old=irqs;irqs=value;if(value)restored++;else masked++;return old;}
static int fake_printf(const char *fmt,...){(void)fmt;logs++;if(!irqs)violations++;return 0;}
#define printf fake_printf
static uint32_t redfin_er_rd(uintptr_t,unsigned);
static void redfin_er_wr(uintptr_t,unsigned,uint32_t);
static void redfin_er_read_start(void);
static void redfin_er_data_done(void);
static void redfin_er_command_done(void);
static void redfin_er_imem_done(void);
static uint64_t redfin_er_counter(void);
static uint64_t redfin_er_frequency(void);
static void redfin_er_relax(void);
static bool fake_cas(uint32_t *p,uint32_t *expected,uint32_t desired,bool weak,int success,int failure){
 cas_tries++;if(!weak)violations++;
 if(cas_fault){*expected=__atomic_load_n(p,__ATOMIC_RELAXED);return false;}
 return __atomic_compare_exchange_n(p,expected,desired,weak,success,failure);
}
#define __atomic_compare_exchange_n fake_cas
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
 (void)root;if(dt_fault==1)return 1;
 const char *paths[]={"/","/chosen","/cpus/cpu0","/cpus/cpu1","/redfin-spmi","/redfin-return"};
 for(unsigned i=0;i<6;i++)if(!strcmp(path,paths[i])){*out=(void*)(uintptr_t)(i+1);return 0;}
 violations++;return 1;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *bytes){
 static const char compatible[]="google,redfin\0qcom,sm7250";
 static const char wrong[]="google,other\0qcom,sm7250";
 static unsigned char unaligned[49];
 uint64_t values[6]={0};unsigned n=(unsigned)(uintptr_t)node;
 if(n==1 && !strcmp(name,"compatible")){
  *out=dt_fault==2?wrong:compatible;*bytes=dt_fault==2?sizeof(wrong):sizeof(compatible);
  if(dt_fault==3)(*bytes)--;if(dt_fault==4)*out=NULL;return 0;
 }
 if(n==2 && !strcmp(name,"dram-base")){values[0]=0x180000000ULL+(dt_fault==5);*bytes=8;}
 else if(n==2 && !strcmp(name,"dram-size")){values[0]=0x80000000ULL+(dt_fault==6);*bytes=8;}
 else if(n==3 && !strcmp(name,"reg")){values[0]=dt_fault==7?1:0;*bytes=4;}
 else if(n==4 && !strcmp(name,"reg")){values[0]=dt_fault==8?0x100:0x600;*bytes=4;}
 else if(n==5 && !strcmp(name,"ee")){values[0]=dt_fault==15?1:0;*bytes=4;}
 else if(n==5 && !strcmp(name,"reg")){
  const uint64_t fixed[]={0xc440000,0x1100,0xe600000,0x100000,0xc40a000,0x26000};
  memcpy(values,fixed,48);if(dt_fault>=9 && dt_fault<=14)values[dt_fault-9]++;*bytes=48;
 }
 else if(n==6 && !strcmp(name,"reg")){
  const uint64_t fixed[]={0xc600000,0x2000000,0x146ab65c,4};
  memcpy(values,fixed,32);if(dt_fault>=16 && dt_fault<=19)values[dt_fault-16]++;*bytes=32;
 }else{violations++;return 1;}
 memcpy(unaligned+1,values,*bytes);*out=unaligned+1;if(dt_fault==20)(*bytes)--;return 0;
}
static vm_offset_t ml_io_map(vm_offset_t base,vm_size_t bytes){
 maps++;if(!irqs)violations++;
 if(mutation==1)args[0]='!';if(mutation==2)mpidr=0x600;
 if(map_fault==maps)return 0;
 if(map_fault==5)return 0x1001;
 if(map_fault==6)return UINTPTR_MAX-3;
 if(base==0xc440000 && bytes==0x1100)return 0x1000;
 if(base==0xe600000 && bytes==0x100000)return 0x2000;
 if(base==0xc40a000 && bytes==0x26000)return 0x3000;
 if(base==0x146ab65c && bytes==4)return 0x5000;
 violations++;return 0;
}
'''
SUFFIX = r'''
#undef printf
#undef __atomic_compare_exchange_n
static uint32_t redfin_er_rd(uintptr_t base,unsigned offset){
 reads++;if(irqs)violations++;
 if(base==0x1000){
  if(!offset)return fault==1?0x40000000:0x50000000;
  if(offset<0x900 || offset>=0x1100 || (offset&3)){violations++;return 0;}
  if(offset==0x900+210*4){
   if(fault==2)return 0;
   if((fault==6 && observes>=1) || (fault==7 && observes>=2) || (fault==8 && observes>=3))return 0x900;
   return 0x800;
  }
  return 0;
 }
 if(base==0x3000){if(offset!=0x700+210*4)violations++;return fault==3?1:0;}
 if(base==0x2000){
  if(offset==210*0x80+8){polls++;return fault==10+observes?9:(fault==20+observes || (fault==31 && observes==1))?0:1;}
  if(offset==210*0x80+0x18){
   if(observes==1)return subtype;
   return fault==9 && observes==3?spare^1:spare;
  }
  violations++;return 0;
 }
 if(base==0x5000 && !offset){
  imem_reads++;return fault==4 || (fault==5 && imem_reads==2)?0:0x77665500;
 }
 violations++;return 0;
}
static void redfin_er_wr(uintptr_t base,unsigned offset,uint32_t value){
 writes++;if(irqs)violations++;
 if(base!=0x2000 || offset!=210*0x80 || value!=(observes?0x80008f0:0x8000050))violations++;
 observes++;
 if(mutation==3 && observes==3)args[0]='!';
 if(mutation==4 && observes==3)mpidr=0x600;
}
static void redfin_er_read_start(void){}
static void redfin_er_data_done(void){violations++;}
static void redfin_er_command_done(void){}
static void redfin_er_imem_done(void){violations++;}
static uint64_t redfin_er_counter(void){if(fault!=30 && !(fault==31 && observes))counter+=20;return counter;}
static uint64_t redfin_er_frequency(void){return frequency;}
static void redfin_er_relax(void){relaxes++;}
void reset(const char *text){
 memset(args,0,sizeof(args));strncpy(args,text,sizeof(args)-1);
 memset(cpus,0,sizeof(cpus));cpus[1].cpu_id=1;cpus[1].phys_id=0x600;cpus[1].l2_cache_id=1;
 memset(&cluster,0,sizeof(cluster));cluster.num_cpus=2;cluster.cpu_mask=3;
 memset(&topology,0,sizeof(topology));topology.version=1;topology.num_cpus=2;topology.max_cpu_id=1;
 topology.num_clusters=1;topology.cpus=topology.boot_cpu=cpus;topology.clusters=topology.boot_cluster=&cluster;
 rf_smr_state=rf_smr_bytes=0;rf_smr_nonce=0;memset(rf_smr_frozen,0,sizeof(rf_smr_frozen));
 memset(&rf_smr_report,0,sizeof(rf_smr_report));memset(&rf_smr_target,0,sizeof(rf_smr_target));
 fault=dt_fault=map_fault=mutation=reads=writes=maps=polls=relaxes=violations=logs=masked=restored=0;
 observes=imem_reads=old_calls=old_ready=cas_fault=cas_tries=0;
 spare=subtype=4;counter=mpidr=0;frequency=19200000;current_el=4;sctlr=5;irqs=true;
}
void set(unsigned kind,uint64_t value){
 switch(kind){case 0:fault=value;break;case 1:dt_fault=value;break;case 2:map_fault=value;break;
 case 3:mutation=value;break;case 4:spare=value;break;case 5:subtype=value;break;
 case 6:frequency=value;break;case 7:mpidr=value;break;case 8:current_el=value;break;
 case 9:sctlr=value;break;case 10:counter=value;break;case 11:rf_smr_state=value;break;
 case 12:cas_fault=value;break;default:violations++;}
}
void topology_fault(unsigned kind){
 switch(kind){case 0:topology.version++;break;case 1:topology.num_cpus=1;break;
 case 2:topology.max_cpu_id=2;break;case 3:topology.num_clusters=2;break;
 case 4:topology.max_cluster_id=1;break;case 5:topology.max_die_id=1;break;
 case 6:topology.cpus=NULL;break;case 7:topology.clusters=NULL;break;
 case 8:topology.boot_cpu=&cpus[1];break;case 9:topology.boot_cluster=NULL;break;
 case 10:cpus[0].cpu_id=1;break;case 11:cpus[0].phys_id=0x600;break;
 case 12:cpus[1].cpu_id=0;break;case 13:cpus[1].phys_id=0x100;break;
 case 14:cpus[0].cluster_id=1;break;case 15:cpus[1].die_id=1;break;
 case 16:cpus[1].cluster_type=1;break;case 17:cpus[0].l2_cache_id=1;break;
 case 18:cpus[1].l2_cache_id=0;break;case 19:cpus[1].l3_cache_id=1;break;
 case 20:cpus[0].l2_cache_size=1;break;case 21:cpus[1].l3_cache_size=1;break;
 case 22:cluster.cluster_id=1;break;case 23:cluster.cluster_type=1;break;
 case 24:cluster.num_cpus=1;break;case 25:cluster.first_cpu_id=1;break;
 case 26:cluster.cpu_mask=1;break;default:violations++;}
}
void change_args(const char *text){memset(args,0,sizeof(args));strncpy(args,text,sizeof(args)-1);}
unsigned stat(unsigned n){
 const unsigned values[]={reads,writes,maps,polls,relaxes,violations,logs,masked,restored,
  observes,imem_reads,old_calls,old_ready,rf_smr_state,rf_smr_report.stage,irqs,cas_tries};
 return n<17?values[n]:0;
}
int flags(const char *text,unsigned bytes){uint64_t nonce=0;return rf_smr_flags(text,bytes,&nonce);}
'''


def backend():
    patch = (HERE / 'smp-return.patch').read_text()
    added = '\n'.join(line[1:] for line in patch.splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    return added.split('/* REDFIN_SMP_RETURN_BEGIN', 1)[0] + '/* REDFIN_SMP_RETURN_BEGIN' + added.split(
        '/* REDFIN_SMP_RETURN_BEGIN', 1)[1].split('/* REDFIN_SMP_RETURN_END */', 1)[0]


class SMPReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        header = (HERE / 'early-return.h').read_text()
        header = re.sub(r'/\* REDFIN_EARLY_RETURN_HW_BEGIN \*/.*?/\* REDFIN_EARLY_RETURN_HW_END \*/', '', header, flags=re.S)
        body = re.sub(r'/\* RF_SMR_RUNTIME_HW_BEGIN \*/.*?/\* RF_SMR_RUNTIME_HW_END \*/', '', backend(), flags=re.S)
        source = root / 'return.c'
        source.write_text(PREFIX + header + body + SUFFIX)
        output = root / 'return.so'
        subprocess.run([shutil.which('cc') or 'cc', '-O2', '-std=c11', '-shared', '-fPIC',
                        '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-misleading-indentation',
                        str(source), '-o', str(output)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(output))
        cls.lib.reset.argtypes = cls.lib.change_args.argtypes = [C.c_char_p]
        cls.lib.set.argtypes = [C.c_uint, C.c_uint64]
        cls.lib.topology_fault.argtypes = cls.lib.stat.argtypes = [C.c_uint]
        cls.lib.flags.argtypes = [C.c_char_p, C.c_uint]

    def setUp(self):
        self.reset()

    def reset(self, text=ARGS):
        self.lib.reset(text.encode())

    def test_success_is_read_only_coherent_and_does_not_touch_up_ready(self):
        for spare in (4, 5):
            self.reset();self.lib.set(4, spare)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
            self.assertEqual([self.lib.stat(i) for i in range(1, 16)],
                             [3, 4, 3, 0, 0, 1, 1, 1, 3, 2, 0, 0, 3, 6, 1])
            counts = [self.lib.stat(i) for i in range(17)]
            self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
            self.assertEqual([self.lib.stat(i) for i in range(17)], counts)

    def test_closed_exact_whitelist_and_optional_trace(self):
        words = ARGS.split()
        for index in range(len(words)):
            for replacement in ('', words[index], 'unknown=0'):
                changed = words[:index] + ([replacement] if replacement else []) + words[index + 1:]
                if replacement == words[index]:
                    changed += [replacement]
                self.reset(' '.join(changed))
                self.assertEqual(self.lib.redfin_smp_return_ready(), 0, changed)
                self.assertEqual((self.lib.stat(0), self.lib.stat(1)), (0, 0))
        for token in ('redfincpu=0', 'redfinearlyreturn=0', 'redfinfb=0', 'redfinufs=0', 'redfinusb=0',
                      'redfinspmi=1', 'redfinreturn=1', 'ufsrw=0', 'rootrw=0', 'ufsroot=userdata',
                      'cpumask=3', 'sweetlog=0', '-enable_kprintf_spam -enable_kprintf_spam'):
            self.reset(ARGS + ' ' + token)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0, token)
            self.assertEqual(self.lib.stat(0), 0)
        self.reset(ARGS + ' -enable_kprintf_spam')
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        for nonce in ('0x0000000000000000', '0x0123456789abcdeF', '0x0123456789abcde', '0123456789abcdef',
                      '0x00123456789abcdef', '0x0123456789abcdeg'):
            self.reset(ARGS.replace('0x0123456789abcdef', nonce))
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0, nonce)
            self.assertEqual(self.lib.stat(0), 0)

    def test_topology_and_runtime_fail_before_any_maps_or_mmio(self):
        for kind in range(27):
            self.reset();self.lib.topology_fault(kind)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0, kind)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 2)], [0, 0, 0])
        for kind, value in ((7, 0x600), (7, 0x100000000), (8, 8), (9, 0), (9, 1), (9, 4), (3, 9)):
            self.reset();self.lib.set(kind, value)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 2)], [0, 0, 0])

    def test_all_dt_windows_and_identity_fail_closed_even_unaligned(self):
        for fault in range(1, 21):
            self.reset();self.lib.set(1, fault)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0, fault)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 2)], [0, 0, 0])

    def test_mapping_failures_and_post_mapping_profile_mutations_issue_no_commands(self):
        for fault in range(1, 7):
            self.reset();self.lib.set(2, fault)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual((self.lib.stat(0), self.lib.stat(1)), (0, 0))
        for mutation in (1, 2):
            self.reset();self.lib.set(3, mutation)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual((self.lib.stat(0), self.lib.stat(1)), (0, 0))

    def test_all_noncanonical_spare_values_and_subtypes_are_rejected(self):
        for spare in range(256):
            if spare in (4, 5):
                continue
            self.reset();self.lib.set(4, spare)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual((self.lib.stat(1), self.lib.stat(10)), (2, 0))
        for subtype in (0, 1, 3, 5, 255):
            self.reset();self.lib.set(5, subtype)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual(self.lib.stat(1), 1)

    def test_imem_mapping_and_bit_zero_drift_are_denied(self):
        for fault in range(1, 10):
            self.reset();self.lib.set(0, fault)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0, fault)
            self.assertEqual(self.lib.stat(5), 0)
            self.assertEqual(self.lib.stat(15), 1)

    def test_each_observer_error_timeout_and_clock_stall_is_final(self):
        for base in (10, 20):
            for transaction in range(1, 4):
                self.reset();self.lib.set(0, base + transaction)
                self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
                self.assertEqual(self.lib.stat(1), transaction)
                self.assertEqual(self.lib.stat(3), transaction + (999 if base == 20 else 0))
                counts = [self.lib.stat(i) for i in range(17)]
                self.lib.set(0, 0)
                self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
                self.assertEqual([self.lib.stat(i) for i in range(17)], counts)
        for fault in (30, 31):
            self.reset();self.lib.set(0, fault)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual(self.lib.stat(4), 4096)
            self.assertEqual(self.lib.stat(1), int(fault == 31))
        for frequency in (0, 24000000, 1000000000):
            self.reset();self.lib.set(6, frequency)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual(self.lib.stat(0), 0)

    def test_cached_success_revalidates_and_permanently_denies_changed_frozen_state(self):
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        counts = [self.lib.stat(i) for i in (0, 1, 2)]
        self.lib.change_args((ARGS + ' ').encode())
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.lib.change_args(ARGS.encode())
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.assertEqual([self.lib.stat(i) for i in (0, 1, 2)], counts)
        for kind in (12, 13, 26):
            self.reset();self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
            self.lib.topology_fault(kind)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)

    def test_mutation_during_last_observer_cannot_publish_success(self):
        for mutation in (3, 4):
            self.reset();self.lib.set(3, mutation)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual(self.lib.stat(13), 2)

    def test_once_owner_budget_is_bounded_and_in_progress_never_spins(self):
        self.lib.set(12, 1)
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.assertEqual((self.lib.stat(16), self.lib.stat(0)), (256, 0))
        self.lib.set(12, 0)
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.assertEqual((self.lib.stat(16), self.lib.stat(13)), (256, 2))
        self.reset();self.lib.set(11, 1)
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.assertEqual((self.lib.stat(16), self.lib.stat(0)), (0, 0))

    def test_native_actual_backend_and_shared_mmio_compile_to_arm64(self):
        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang unavailable')
        prefix = re.sub(r'^static uint64_t rf_smr_(?:mpidr|el|sctlr)\(void\).*$', '', PREFIX, flags=re.M)
        prefix = prefix.replace('#define __atomic_compare_exchange_n fake_cas', '')
        root = Path(self.temp.name)
        source = root / 'native.c'
        source.write_text(prefix + (HERE / 'early-return.h').read_text() + backend())
        result = subprocess.run([compiler, '-arch', 'arm64', '-mcpu=cortex-a55', '-mno-outline-atomics',
                                 '-mgeneral-regs-only', '-mstrict-align', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-Wno-unused-variable', '-Wno-unused-function', '-Wno-misleading-indentation',
                                 '-c', str(source), '-o', str(root / 'native.o')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
