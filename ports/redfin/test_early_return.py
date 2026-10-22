"""Execute actual shared leaf and protected wrapper with recorded MMIO only."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).parent
ARGS = ('debug=0xc serial=3 cpus=1 rd=md0 redfinearlyreturn=1 redfinspmi=1 redfinreturn=1 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfinbootid=0x0123456789abcdef')

PREFIX = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
typedef struct {unsigned cpu_id,phys_id;} ml_topology_cpu_t;
typedef struct {unsigned num_cpus;ml_topology_cpu_t *boot_cpu;} ml_topology_info_t;
static ml_topology_cpu_t boot={0,0};
static ml_topology_info_t topology={1,&boot};
static struct {
 bool ready; vm_offset_t core,observer,config; uint32_t version;
 unsigned apid,owner; uint8_t subtype;
} redfin_spmi_proof={true,0x1000,0x2000,0x3000,0x50000000,7,0,4};
static char args[608];
static uint64_t fault[24],counter,mpidr;
static unsigned transactions,polls,waits,violations,maps,logs,masked,restored;
static unsigned write_commands,imem_writes,wdatas,register_reads;
static unsigned observe_count,sequence,imem_value;
static unsigned selected_apid=7,pmic_spare=4,subtype=4;
static bool irqs=true,return_ready=true;
static uint64_t rf_er_mpidr(void){return mpidr;}
static uint64_t rf_er_el(void){return fault[20]?fault[20]:4;}
static uint32_t redfin_er_rd(uintptr_t,unsigned);
static void redfin_er_wr(uintptr_t,unsigned,uint32_t);
static void redfin_er_read_start(void);
static void redfin_er_data_done(void);
static void redfin_er_command_done(void);
static void redfin_er_imem_done(void);
static uint64_t redfin_er_counter(void);
static uint64_t redfin_er_frequency(void);
static void redfin_er_relax(void);
static const char *PE_boot_args(void){return args;}
static const ml_topology_info_t *ml_get_topology_info(void){return fault[19]?NULL:&topology;}
int redfin_spmi_return_ready(void){return return_ready;}
static bool ml_set_interrupts_enabled(bool enabled){
 bool old=irqs;irqs=enabled;if(enabled)restored++;else masked++;return old;
}
static int fake_printf(const char *fmt,...){(void)fmt;logs++;if(!irqs)violations++;return 0;}
#define printf fake_printf
static bool redfin_return_ranges(const uint64_t *reg,unsigned bytes){
 const uint64_t expected[]={0x0c600000,0x2000000,0x146ab65c,4};
 return reg && bytes==sizeof(expected) && !memcmp(reg,expected,sizeof(expected));
}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
 (void)root;if(fault[13]==1)return 1;
 if(!strcmp(path,"/")){*out=(void*)1;return 0;}
 if(!strcmp(path,"/redfin-return")){*out=(void*)2;return 0;}
 violations++;return 1;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *bytes){
 static const char compat[]="google,redfin\0qcom,sm7250";
 static const char wrong[]="google,other\0qcom,sm7250";
 static uint64_t reg[]={0x0c600000,0x2000000,0x146ab65c,4};
 if(node==(void*)1 && !strcmp(name,"compatible")){
  *out=fault[13]==2?wrong:compat;*bytes=fault[13]==2?sizeof(wrong):sizeof(compat);
  if(fault[13]==3)(*bytes)--;if(fault[13]==4)*out=NULL;return 0;
 }
 if(node==(void*)2 && !strcmp(name,"reg")){
  reg[2]=fault[13]==5?0x146ab660:0x146ab65c;*out=reg;*bytes=fault[13]==6?24:32;return 0;
 }
 violations++;return 1;
}
static vm_offset_t ml_io_map(vm_offset_t base,vm_size_t bytes){
 maps++;if(!irqs)violations++;
 if(fault[14]==1)args[0]='!';if(fault[14]==2)return_ready=false;
 if(fault[12] && maps==fault[12])return 0;
 if(base==0x0c600000ULL+selected_apid*0x10000ULL && bytes==0x20)return 0x4000;
 if(base==0x146ab65c && bytes==4)return 0x5000;
 violations++;return 0;
}
'''

SUFFIX = r'''
#undef printf
static uint32_t redfin_er_rd(uintptr_t base,unsigned off){
 register_reads++;
 if(base==0x1000){
  if(!off)return fault[11]?fault[11]:0x50000000;
  if(off<0x900 || off>=0x1100 || (off&3)){violations++;return 0;}
  if(off==0x900+selected_apid*4 && !fault[9]){
   if(fault[6] && transactions>=fault[6])return 0x900;
   return 0x800;
  }
  return 0;
 }
 if(base==0x3000){if(off!=0x700+selected_apid*4)violations++;return fault[10];}
 if(base==0x2000 || base==0x4000){
  unsigned expected=base==0x2000?selected_apid*0x80:0;
  if(off==expected+8){polls++;return fault[0]==transactions?9:fault[1]==transactions?0:1;}
  if(base==0x2000 && off==expected+0x18){
   if(observe_count==1)return subtype;
   return observe_count==3 && fault[4]?pmic_spare^2:pmic_spare;
  }
  violations++;return 0;
 }
 if(base==0x5000 && !off)return fault[5]?0:imem_value;
 violations++;return 0;
}
static void redfin_er_wr(uintptr_t base,unsigned off,uint32_t value){
 if(irqs)violations++;
 if(base==0x2000){
  if(off!=selected_apid*0x80 || (value!=0x8000050 && value!=0x80008f0) || sequence!=1)violations++;
  if((observe_count==0 && value!=0x8000050) || (observe_count>0 && value!=0x80008f0))violations++;
  observe_count++;transactions++;sequence=2;return;
 }
 if(base==0x4000 && off==0x10){
  if(observe_count!=2 || sequence!=3 || value!=((pmic_spare&1)|4))violations++;
  pmic_spare=value;wdatas++;sequence=4;return;
 }
 if(base==0x4000 && !off){
  if(value!=0x8f0 || sequence!=5)violations++;
  write_commands++;transactions++;sequence=2;return;
 }
 if(base==0x5000 && !off){
  if(value!=0x77665500 || observe_count!=3 || sequence!=3)violations++;
  imem_value=value;imem_writes++;sequence=6;return;
 }
 violations++;
}
static void redfin_er_read_start(void){sequence=1;}
static void redfin_er_data_done(void){if(sequence!=4)violations++;sequence=5;}
static void redfin_er_command_done(void){if(sequence!=2)violations++;sequence=3;}
static void redfin_er_imem_done(void){if(sequence!=6)violations++;sequence=7;}
static uint64_t redfin_er_counter(void){
 if(fault[7]==1 || (fault[7]==3 && transactions))return counter;
 counter+=20;return counter;
}
static uint64_t redfin_er_frequency(void){return fault[8]?fault[8]:19200000;}
static void redfin_er_relax(void){waits++;}
void reset(const char *text){
 memset(fault,0,sizeof(fault));memset(args,0,sizeof(args));strncpy(args,text,sizeof(args)-1);
 transactions=polls=waits=violations=maps=logs=masked=restored=0;
 write_commands=imem_writes=wdatas=register_reads=observe_count=sequence=imem_value=0;
 pmic_spare=4;subtype=4;selected_apid=7;counter=0;mpidr=0;irqs=return_ready=true;
 boot.cpu_id=boot.phys_id=0;topology.num_cpus=1;topology.boot_cpu=&boot;
 redfin_spmi_proof.ready=true;redfin_spmi_proof.apid=7;
 rf_er_attempted=rf_er_frozen_bytes=0;memset(rf_er_frozen,0,sizeof(rf_er_frozen));
}
void set(unsigned kind,uint64_t value){
 if(kind<24)fault[kind]=value;else violations++;
 if(kind==2)subtype=value;if(kind==3)pmic_spare=value;
 if(kind==7 && value==2)counter=UINT64_MAX-5;
 if(kind==15)return_ready=value;if(kind==16)topology.num_cpus=value;
 if(kind==17)boot.phys_id=value;if(kind==18)mpidr=value;
 if(kind==21)redfin_spmi_proof.ready=value;
}
unsigned stat(unsigned n){
 const unsigned values[]={transactions,polls,waits,violations,maps,logs,masked,restored,
  write_commands,imem_writes,wdatas,register_reads,irqs,rf_er_attempted};
 return n<14?values[n]:0;
}
int raw(unsigned apid,unsigned invalid){
 struct redfin_er_target target;
 struct redfin_er_io io={0x1000,0x2000,0x3000,0x4000,0x5000};
 struct redfin_er_report report;
 int result=redfin_er_find(io.core,io.config,&target);
 if(result)return result;
 target.apid=apid;if(invalid==1)io.channel=0;if(invalid==2)io.imem=UINTPTR_MAX-2;
 irqs=false;result=redfin_er_arm(&io,&target,&report);irqs=true;return result;
}
int flags(const char *text,unsigned bytes){uint64_t nonce=0;return rf_er_flags(text,bytes,&nonce);}
'''


def added(path):
    return '\n'.join(line[1:] for line in path.read_text().splitlines()
                     if line.startswith('+') and not line.startswith('+++'))


class EarlyReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        header = (HERE / 'early-return.h').read_text()
        header = re.sub(r'/\* REDFIN_EARLY_RETURN_HW_BEGIN \*/.*?/\* REDFIN_EARLY_RETURN_HW_END \*/', '', header, flags=re.S)
        backend = added(HERE / 'early-return.patch').split('/* REDFIN_EARLY_RETURN_PROBE_BEGIN', 1)[1].split('/* REDFIN_EARLY_RETURN_PROBE_END */', 1)[0]
        backend = '/* REDFIN_EARLY_RETURN_PROBE_BEGIN' + backend
        backend = re.sub(r'/\* RF_ER_RUNTIME_HW_BEGIN \*/.*?/\* RF_ER_RUNTIME_HW_END \*/', '', backend, flags=re.S)
        source = root / 'early.c'
        source.write_text(PREFIX + header + backend + SUFFIX)
        cls.library = root / 'early.so'
        subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-shared', '-fPIC', '-O2',
                        '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                        str(source), '-o', str(cls.library)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(cls.library))
        cls.lib.reset.argtypes = [C.c_char_p]
        cls.lib.set.argtypes = [C.c_uint, C.c_uint64]
        cls.lib.stat.argtypes = [C.c_uint]
        cls.lib.raw.argtypes = [C.c_uint, C.c_uint]
        cls.lib.flags.argtypes = [C.c_char_p, C.c_uint]

    def setUp(self):
        self.reset()

    def reset(self, args=ARGS):
        self.lib.reset(args.encode())

    def stats(self):
        return [self.lib.stat(i) for i in range(14)]

    def test_protected_success_exact_transactions_and_irq_restoration(self):
        self.assertEqual(self.lib.redfin_early_return_probe(), 0)
        s = self.stats()
        self.assertEqual(s[:2], [4, 4])
        self.assertEqual(s[3:11], [0, 2, 1, 1, 1, 1, 1, 1])
        self.assertEqual(s[12:], [1, 1])
        self.assertEqual(self.lib.redfin_early_return_probe(), errno.EBUSY)
        self.assertEqual(self.stats(), s)

    def test_all_spare_bytes_preserve_only_bit_zero(self):
        for spare in range(256):
            self.reset();self.lib.set(3, spare)
            self.assertEqual(self.lib.redfin_early_return_probe(), 0)
            self.assertEqual(self.lib.stat(3), 0)

    def test_each_transaction_error_and_timeout_stops_without_retry(self):
        for fault, expected in ((0, errno.EIO), (1, errno.ETIMEDOUT)):
            for transaction in range(1, 5):
                with self.subTest(fault=fault, transaction=transaction):
                    self.reset();self.lib.set(fault, transaction)
                    self.assertEqual(self.lib.redfin_early_return_probe(), expected)
                    self.assertEqual(self.lib.stat(0), transaction)
                    self.assertEqual(self.lib.stat(1), transaction if fault == 0 else transaction + 999)
                    self.assertEqual(self.lib.stat(9), 0)
                    self.assertEqual(self.lib.stat(3), 0)
                    self.assertEqual(self.lib.stat(12), 1)

    def test_subtype_clock_readback_and_mapping_failures(self):
        cases = ((2, 5, errno.EIO, 1, 0), (8, 24000000, errno.ENOTSUP, 0, 0),
                 (7, 1, errno.ENOTSUP, 0, 0), (4, 1, errno.EIO, 4, 0),
                 (5, 1, errno.EIO, 4, 1), (6, 2, errno.EAGAIN, 2, 0),
                 (6, 4, errno.EAGAIN, 4, 0))
        for kind, value, result, transactions, imem in cases:
            with self.subTest(kind=kind, value=value):
                self.reset();self.lib.set(kind, value)
                self.assertEqual(self.lib.redfin_early_return_probe(), result)
                self.assertEqual(self.lib.stat(0), transactions)
                self.assertEqual(self.lib.stat(9), imem)
                self.assertEqual(self.lib.stat(3), 0)
                self.assertEqual((self.lib.stat(6), self.lib.stat(7), self.lib.stat(12)), (1, 1, 1))

    def test_stalled_counter_after_command_is_bounded(self):
        self.lib.set(1, 1);self.lib.set(7, 3)
        self.assertEqual(self.lib.redfin_early_return_probe(), errno.ENOTSUP)
        self.assertEqual((self.lib.stat(0), self.lib.stat(1), self.lib.stat(2)), (1, 1, 4096))
        self.assertEqual((self.lib.stat(8), self.lib.stat(9)), (0, 0))

    def test_counter_wrap_is_valid(self):
        self.lib.set(7, 2)
        self.assertEqual(self.lib.redfin_early_return_probe(), 0)

    def test_runtime_policy_blocks_all_mmio_before_discovery(self):
        for kind, value in ((15, 0), (16, 2), (17, 0x600), (18, 0x100000000),
                            (18, 0x600), (19, 1), (20, 8), (21, 0)):
            with self.subTest(kind=kind, value=value):
                self.reset();self.lib.set(kind, value)
                self.assertIn(self.lib.redfin_early_return_probe(), (errno.ENOTSUP, errno.ENXIO))
                self.assertEqual((self.lib.stat(0), self.lib.stat(11)), (0, 0))
                self.assertEqual(self.lib.stat(13), 1)

    def test_changed_or_invalid_mappings_never_reach_leaf(self):
        cases = ((9, 1), (10, 1), (11, 0x40000000), (12, 1), (12, 2),
                 (13, 1), (13, 2), (13, 3), (13, 4), (13, 5), (13, 6),
                 (14, 1), (14, 2))
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                self.reset();self.lib.set(kind, value)
                self.assertNotEqual(self.lib.redfin_early_return_probe(), 0)
                self.assertEqual((self.lib.stat(0), self.lib.stat(6)), (0, 0))

    def test_frozen_flags_require_exact_nonce_up_md0_and_disabled_writers(self):
        changed = [ARGS.replace(token, replacement) for token, replacement in (
            ('cpus=1', 'cpus=2'), ('rd=md0', 'rd=ufsroot0'),
            ('redfinearlyreturn=1', 'redfinearlyreturn'), ('redfinearlyreturn=1', 'redfinearlyreturn=0'),
            ('redfinreturn=1', 'redfinreturn=0'), ('redfinspmi=1', 'redfinspmi=0'),
            ('sweettouch=0', 'sweettouch=1'), ('sweetusb=0', 'sweetusb=2'),
            ('0x0123456789abcdef', '0x0000000000000000'), ('0x0123456789abcdef', '0x0123456789abcdeF'))]
        changed += [ARGS + ' ' + token for token in ('redfincpu=1', 'redfinsmp=1', 'redfinfb=1',
                    'redfinroot=1', 'redfinufs=3', 'redfinusb=1', 'ufsrw=1', 'rootrw=1',
                    'ufsroot=userdata', 'cpumask=3', 'redfinfuture=0', 'cpus=1', 'sweetlog=1')]
        for text in changed:
            with self.subTest(text=text):
                self.reset(text)
                self.assertEqual(self.lib.redfin_early_return_probe(), errno.ENOTSUP)
                self.assertEqual((self.lib.stat(0), self.lib.stat(11)), (0, 0))
        self.reset(ARGS + ' redfincpu=0 redfinsmp=0 sweetlog=0')
        self.assertEqual(self.lib.redfin_early_return_probe(), 0)
        for text in (b'', b'a' * 608, b'cpus=1'):
            self.assertEqual(self.lib.flags(text, len(text)), 0)

    def test_raw_leaf_rejects_invalid_apid_and_window_without_transactions(self):
        for apid, invalid in ((512, 0), (0xffffffff, 0), (7, 1), (7, 2)):
            self.reset()
            self.assertEqual(self.lib.raw(apid, invalid), 1)
            self.assertEqual(self.lib.stat(0), 0)

    def test_overlay_header_is_byte_identical_to_shared_shim_header(self):
        stanza = (HERE / 'early-return.patch').read_text().split(
            'diff --git a/bsd/dev/redfin_early_return.h', 1)[1]
        header = ''.join(line[1:] + '\n' for line in stanza.splitlines()
                         if line.startswith('+') and not line.startswith('+++'))
        self.assertEqual(header, (HERE / 'early-return.h').read_text())

    def test_native_freestanding_leaf_compiles_without_external_calls(self):
        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang unavailable')
        root = Path(self.temp.name)
        source = root / 'native.c'
        source.write_text('#include "early-return.h"\nint exercise(struct redfin_er_io *io, struct redfin_er_report *r) {'
                          'struct redfin_er_target t; int e=redfin_er_find(io->core,io->config,&t);'
                          'return e?e:redfin_er_arm(io,&t,r);}\n')
        result = subprocess.run([compiler, '--target=aarch64-none-elf', '-march=armv8-a',
                                 '-mcpu=cortex-a55', '-mno-outline-atomics', '-ffreestanding',
                                 '-fno-builtin', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-I', str(HERE), '-S', str(source), '-o', str(root / 'native.s')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        assembly = (root / 'native.s').read_text()
        self.assertNotRegex(assembly, r'(?m)^\s*blr\s')
        definitions = set(re.findall(r'(?m)^([A-Za-z_][A-Za-z_0-9]*):', assembly))
        calls = set(re.findall(r'(?m)^\s*bl\s+([A-Za-z_][A-Za-z_0-9]*)', assembly))
        self.assertTrue(calls <= definitions, calls - definitions)
        self.assertIn('cntpct_el0', assembly.lower())
        self.assertIn('dsb\toshst', assembly.lower())
        result = subprocess.run([compiler, '--target=aarch64-none-elf', '-march=armv8-a',
                                 '-mcpu=cortex-a55', '-mno-outline-atomics', '-ffreestanding',
                                 '-fno-builtin', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-I', str(HERE), '-c', str(source), '-o', str(root / 'native.o')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_protected_backend_with_real_arm64_register_and_mmio_wrappers_compiles(self):
        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang unavailable')
        prefix = re.sub(r'^static uint64_t rf_er_(?:mpidr|el)\(void\).*$', '', PREFIX, flags=re.M)
        backend = added(HERE / 'early-return.patch').split('/* REDFIN_EARLY_RETURN_PROBE_BEGIN', 1)[1].split(
            '/* REDFIN_EARLY_RETURN_PROBE_END */', 1)[0]
        backend = '/* REDFIN_EARLY_RETURN_PROBE_BEGIN' + backend
        root = Path(self.temp.name)
        source = root / 'backend-native.c'
        source.write_text(prefix + (HERE / 'early-return.h').read_text() + backend)
        result = subprocess.run([compiler, '-arch', 'arm64', '-mcpu=cortex-a55',
                                 '-mno-outline-atomics', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-Wno-unused-variable', '-Wno-unused-function',
                                 '-Wno-misleading-indentation', '-c', str(source),
                                 '-o', str(root / 'backend-native.o')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
