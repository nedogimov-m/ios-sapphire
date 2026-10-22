"""Validate the real GMU kernel adapter, generated ADT and native FDT checks."""
import copy
import ctypes
import errno
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from ports.redfin import gmu_probe, mkadt


HERE = Path(__file__).resolve().parent
ARGS = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfingpu=2 redfingpupower=1 redfinrpmh=1 '
        'redfinspmi=1 redfinreturn=1 redfingmu=1 redfinbootid=0x1234567890abcdef')


def fixture():
    def cells(*v):
        return struct.pack('>'+str(len(v))+'I', *v)

    gcc, gpucc = '/soc/qcom,gcc@100000', '/soc/qcom,gpucc@3d90000'
    gmu, gpu = '/soc/qcom,gmu@3d6a000', '/soc/qcom,kgsl-3d0@3d00000'
    gic, aop = '/soc/interrupt-controller@17a00000', '/soc/qcom,aopclk'
    cx = '/soc/qcom,gdsc@3d9106c'
    nodes = {
        '/': {'interrupt-parent': cells(5)},
        gcc: {'compatible': b'qcom,gcc-lito\0syscon\0',
              'reg': cells(0x100000, 0x1F0000), 'phandle': cells(1)},
        gpucc: {'compatible': b'qcom,lito-gpucc\0syscon\0',
                'reg': cells(0x3D90000, 0x9000), 'phandle': cells(2)},
        aop: {'compatible': b'qcom,aop-qmp-clk\0', 'phandle': cells(3)},
        cx: {'phandle': cells(4)},
        gic: {'compatible': b'arm,gic-v3\0', 'phandle': cells(5),
              'reg': cells(0x17A00000, 0x10000, 0x17A60000, 0x100000)},
        gpu: {'qcom,chipid': cells(0x06020001),
              'reg': cells(0x3D00000, 0x40000, 0x3D61000, 0x800,
                           0x3DE0000, 0x1000, 0x3D8B000, 0x2000)},
        gmu: {'compatible': b'qcom,gpu-gmu\0',
              'reg': cells(0x3D6A000, 0x30000, 0xB290000, 0x10000, 0xB490000, 0x10000),
              'reg-names': b'kgsl_gmu_reg\0kgsl_gmu_pdc_cfg\0kgsl_gmu_pdc_seq\0',
              'interrupts': cells(0, 304, 4, 0, 305, 4),
              'interrupt-names': b'kgsl_hfi_irq\0kgsl_gmu_irq\0',
              'clock-names': b'gmu_clk\0cxo_clk\0axi_clk\0memnoc_clk\0gpu_cc_ahb\0smmu_vote\0apb_pclk\0',
              'clocks': cells(2, 3, 2, 6, 1, 13, 1, 35, 2, 0, 2, 12, 3, 0),
              'vddcx-supply': cells(4)},
    }
    tree = mkadt.build(0x180000000, 0x80000000)
    tree.children.append(mkadt.node('redfin-gpu-power', [
        ('cx-parent', mkadt.u32(0x30000, 64, 65535, 7, 416)),
        ('chip-id', mkadt.u32(0x06020001))]))
    return tree, nodes


def properties():
    tree, nodes = fixture()
    gmu_probe.add_contract(tree, nodes)
    leaf = next(n for n in tree.children if n.name == 'redfin-gmu')
    return [mkadt.u64(0x180000000), mkadt.u64(0x80000000)] + [
        leaf.prop(name) for name in ('reg', 'chip-id', 'clock-policy',
                                     'tcm-policy', 'cx-parent', 'interrupts')]


class RedfinGMUContractTests(unittest.TestCase):
    def test_overlay_applies_only_new_files_and_copies_source_headers_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = HERE/'gmu-probe.patch'
            subprocess.run(['git', 'apply', '--check', str(patch)], cwd=root,
                           check=True, capture_output=True)
            subprocess.run(['git', 'apply', str(patch)], cwd=root,
                           check=True, capture_output=True)
            wanted = {
                'bsd/dev/redfin_gmu_probe.c': HERE/'gmu-probe.c',
                'bsd/dev/redfin_gmu_probe.h': HERE/'gmu-probe.h',
                'bsd/dev/redfin_gmu_tcm.h': HERE/'include/redfin_gmu_tcm.h',
            }
            actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
            self.assertEqual(actual, set(wanted))
            for target, source in wanted.items():
                self.assertEqual((root/target).read_bytes(), source.read_bytes())

    def test_exact_native_fixture_emits_correct_gic_and_no_dma_authority(self):
        tree, nodes = fixture()
        gmu_probe.add_contract(tree, nodes)
        leaf = next(n for n in tree.children if n.name == 'redfin-gmu')
        self.assertEqual(struct.unpack('<8Q', leaf.prop('reg')),
                         (0x100000, 0x1F0000, 0x3D90000, 0x9000,
                          0x3D6A000, 0x30000, 0x17A00000, 0x4000))
        self.assertNotEqual(struct.unpack('<8Q', leaf.prop('reg'))[6], 0x017A0000)
        self.assertEqual(leaf.prop('interrupts'), mkadt.u32(336, 337))
        self.assertEqual({name for name, _, _ in leaf.props},
                         {'name', 'reg', 'chip-id', 'clock-policy', 'tcm-policy',
                          'cx-parent', 'interrupts'})

    def test_each_checked_native_property_corruption_or_omission_is_atomic(self):
        tree, nodes = fixture()
        for path, values in nodes.items():
            for key, value in values.items():
                for omitted in (False, True):
                    changed = copy.deepcopy(nodes)
                    if omitted:
                        del changed[path][key]
                    else:
                        altered = bytearray(value)
                        altered[0] ^= 0x80
                        changed[path][key] = bytes(altered)
                    candidate = copy.deepcopy(tree)
                    before = len(candidate.children)
                    with self.assertRaises(ValueError, msg=(path, key, omitted)):
                        gmu_probe.add_contract(candidate, changed)
                    self.assertEqual(len(candidate.children), before)

    def test_duplicate_gmu_or_missing_or_mismatched_parent_is_rejected(self):
        for problem in ('duplicate', 'missing', 'wrong-parent'):
            tree, nodes = fixture()
            if problem == 'duplicate':
                tree.children.append(mkadt.node('redfin-gmu'))
            elif problem == 'missing':
                tree.children = [n for n in tree.children if n.name != 'redfin-gpu-power']
            else:
                tree.children[-1].props.append(('chip-id', 0, mkadt.u32(0x06010001)))
                tree.children[-1].props = [(k, f, mkadt.u32(0x06010001) if k == 'chip-id' else v)
                                            for k, f, v in tree.children[-1].props]
            with self.assertRaises(ValueError):
                gmu_probe.add_contract(tree, nodes)

    def test_ambiguous_controller_phandle_and_wrong_interrupt_parent_are_rejected(self):
        tree, nodes = fixture()
        nodes['/bogus'] = {'phandle': nodes['/soc/qcom,gcc@100000']['phandle']}
        with self.assertRaises(ValueError):
            gmu_probe.add_contract(tree, nodes)
        tree, nodes = fixture()
        nodes['/soc/qcom,gmu@3d6a000']['interrupt-parent'] = struct.pack('>I', 1)
        with self.assertRaises(ValueError):
            gmu_probe.add_contract(tree, nodes)


def adapter_source():
    code = (HERE/'gmu-probe.c').read_text()
    code = '\n'.join(line for line in code.splitlines() if not line.startswith('#include'))
    code = code.replace('__builtin_arm_rsr64("CurrentEL")', 'host_el')
    code = code.replace('__builtin_arm_rsr64("MPIDR_EL1")', 'host_mpidr')
    for instruction in ('dmb oshld', 'dmb oshst', 'dsb osh'):
        code = code.replace('__asm__ volatile("'+instruction+'" ::: "memory");', '')
    read = 'uint32_t value = *(volatile const uint32_t *)address;'
    write = '*(volatile uint32_t *)address = value;'
    assert code.count(read) == code.count(write) == 1
    return code.replace(read, 'uint32_t value = host_mmio_read(address);').replace(
        write, 'host_mmio_write(address, value);')


HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <sys/errno.h>
#include "redfin_gmu_probe.h"
#include "redfin_gmu_tcm.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
typedef void *DTEntry;
static uint32_t gcc[0x1f0000/4],gpucc[0x9000/4],gmu[0x30000/4],gic[0x4000/4];
static char live_args[608],parent_args[608];
static unsigned arg_bytes,scenario,maps,bad,raw_reads,raw_writes,dtcm_writes;
static unsigned parent_calls,fail_parent,after_loss,map_mask;
static uint64_t host_el,host_mpidr,now_ns;
static bool parent_lost;
static int parent_cookie;
struct property {uint8_t data[128];unsigned bytes;bool present;};
static struct property props[8];
static const char *keys[8]={"dram-base","dram-size","reg","chip-id","clock-policy","tcm-policy","cx-parent","interrupts"};
static int log_sink(const char *text,...) {(void)text;return 0;}
#define printf log_sink
const char *PE_boot_args(void){return scenario==1?NULL:live_args;}
int redfin_spmi_return_ready(void){return scenario==3?0:1;}
int SecureDTLookupEntry(void *root,const char *path,DTEntry *out) {
 (void)root;
 if(!strcmp(path,"/chosen")){*out=(void*)1;return 0;}
 if(!strcmp(path,"/redfin-gmu")){*out=(void*)2;return 0;}
 return -1;
}
int SecureDTGetProperty(DTEntry node,const char *key,const void **out,unsigned *n) {
 for(unsigned i=0;i<8;i++)if(node==(void*)(uintptr_t)(i<2?1:2)&&!strcmp(key,keys[i])&&props[i].present) {
  *out=props[i].data;*n=props[i].bytes;return 0;
 }
 return -1;
}
static bool parent_valid(void *context) {
 parent_calls++;
 if(context!=&parent_cookie) {bad++;return false;}
 if(scenario==2 || (fail_parent&&parent_calls>=fail_parent))parent_lost=true;
 return !parent_lost;
}
vm_offset_t ml_io_map(vm_offset_t address,vm_size_t size) {
 maps++;
 if(scenario>=6&&scenario<=9&&maps==scenario-5)return 0;
 if(address==0x100000&&size==sizeof(gcc)){map_mask|=1;return (uintptr_t)gcc;}
 if(address==0x3d90000&&size==sizeof(gpucc)){map_mask|=2;return (uintptr_t)gpucc;}
 if(address==0x17a00000&&size==sizeof(gic)){map_mask|=4;return (uintptr_t)gic;}
 if(address==0x3d6a000&&size==sizeof(gmu)){map_mask|=8;return (uintptr_t)gmu;}
 bad++;return 0;
}
static int unit_and_offset(vm_offset_t address,unsigned *unit,uint32_t *at) {
 uintptr_t bases[]={(uintptr_t)gcc,(uintptr_t)gpucc,(uintptr_t)gmu,(uintptr_t)gic};
 size_t sizes[]={sizeof(gcc),sizeof(gpucc),sizeof(gmu),sizeof(gic)};
 for(unsigned i=0;i<4;i++)if(address>=bases[i]&&address-bases[i]<sizes[i]&&!(address&3)) {
  *unit=i;*at=(uint32_t)(address-bases[i]);return 1;
 }
 bad++;return 0;
}
static uint32_t host_mmio_read(vm_offset_t address) {
 unsigned unit;uint32_t at;
 if(!unit_and_offset(address,&unit,&at))return UINT32_MAX;
 if(parent_lost)after_loss++;
 if(unit==3?(at!=0x128&&at!=0x228&&at!=0x328):!rf_gt_allowed(unit,at,false))bad++;
 raw_reads++;now_ns+=scenario==26?1000:20;
 if(unit==RF_GT_GMU && at==0x14220)return 0x12340000u+(uint32_t)(now_ns*192/10000);
 return *(uint32_t*)address;
}
static void host_mmio_write(vm_offset_t address,uint32_t value) {
 unsigned unit;uint32_t at;
 if(!unit_and_offset(address,&unit,&at))return;
 if(parent_lost)after_loss++;
 if(!rf_gt_allowed(unit,at,true)||(unit==RF_GT_GMU&&at==0x14000&&value!=1))bad++;
 raw_writes++;now_ns+=scenario==26?1000:20;
 *(uint32_t*)address=value;
 if((unit==RF_GT_GCC&&(at==0x71154||at==0x7100c||at==0x71018)) ||
    (unit==RF_GT_GPUCC&&(at==0x1078||at==0x109c||at==0x5000||at==0x1098))) {
  if(value&1)*(uint32_t*)address&=~0x80000000u;
  if(unit==RF_GT_GPUCC&&at==0x1098&&(value&1)) {
   if(gmu[0x14000/4]!=1)bad++;
   gpucc[0x1120/4]&=~0x80000000u;
  }
 }
 if(unit==RF_GT_GPUCC&&at==0x1120) {
  if(value&2)gpucc[0x1120/4]&=~0x80000000u;
  else if(!(gpucc[0x1098/4]&1))gpucc[0x1120/4]|=0x80000000u;
  gpucc[0x1120/4]&=~1u;
 }
 if(unit==RF_GT_GMU&&(at==0x7000||at==0x7004))dtcm_writes++;
 if(raw_writes==1) {
  if(scenario==17)live_args[0]='X';
  if(scenario==18)parent_args[0]='X';
  if(scenario==19)parent_lost=true;
  if(scenario==20)props[2].data[0]^=1;
  if(scenario==21)gic[0x228/4]|=1u<<16;
 }
}
void delay(int us){if(us<0){bad++;return;}now_ns+=(uint64_t)(unsigned)us*1000;}
uint64_t mach_absolute_time(void){return now_ns;}
void absolutetime_to_nanoseconds(uint64_t time,uint64_t *out){*out=time;}
ACTUAL_SOURCE
void host_reset(const char *args,unsigned n,unsigned issue,unsigned failure) {
 memset(gcc,0,sizeof(gcc));memset(gpucc,0,sizeof(gpucc));memset(gmu,0,sizeof(gmu));memset(gic,0,sizeof(gic));
 memset(live_args,0,sizeof(live_args));memset(parent_args,0,sizeof(parent_args));
 if(n>608)abort();memcpy(live_args,args,n);memcpy(parent_args,args,n);arg_bytes=n;
 scenario=issue;fail_parent=failure;maps=bad=raw_reads=raw_writes=dtcm_writes=parent_calls=after_loss=map_mask=0;
 parent_lost=false;host_el=issue==4?0:4;host_mpidr=issue==5?0x100:0;now_ns=1000000;
 gm_attempted=false;
 gcc[0x71004/4]=issue==10?0x80000001:1;gcc[0]=0xc0100001;gcc[4/4]=issue==16?32:31;
 gcc[0xc/4]=0x107;gcc[0x40/4]=0x4000;gcc[0x71028/4]=3;
 gcc[0x52010/4]=0x40000000;gcc[0x52000/4]=0x8000;
 gcc[0x71154/4]=gcc[0x7100c/4]=gcc[0x71018/4]=0x80000200;
 gpucc[0x106c/4]=issue==12?0x222001:0x222000;
 gpucc[0x1540/4]=issue==11?0:0x80001fe0;
 gpucc[0x100c/4]=1;gpucc[0x1064/4]=gpucc[0x1098/4]=0x80000000;
 gpucc[0x109c/4]=gpucc[0x1078/4]=gpucc[0x5000/4]=0x80000000;
 gpucc[0x1120/4]=0x80000000;
 gmu[0x7000/4]=0x12345678;gmu[0x7004/4]=0xfedcba98;
 if(issue==13)gic[0x128/4]=1u<<16;
 if(issue==14)gic[0x228/4]=1u<<17;
 if(issue==15)gic[0x328/4]=1u<<16;
}
void host_property(unsigned index,const void *p,unsigned n,int present) {
 if(index>=8||n>128)abort();memset(&props[index],0,sizeof(props[index]));
 if(n)memcpy(props[index].data,p,n);props[index].bytes=n;props[index].present=present!=0;
}
int host_contract(void){return redfin_gmu_probe_contract(parent_args,arg_bytes);}
int host_probe(void){return redfin_gmu_probe(scenario==22?NULL:parent_args,arg_bytes,
 scenario==24?NULL:&parent_cookie,scenario==23?NULL:parent_valid);}
int host_args(const char *s,unsigned n){return redfin_gmu_args_valid(s,n);}
unsigned host_metric(unsigned index) {
 unsigned v[]={maps,bad,raw_reads,raw_writes,dtcm_writes,parent_calls,after_loss,map_mask};
 return index<8?v[index]:999;
}
uint32_t host_final(unsigned index) {
 uint32_t v[]={gmu[0x14000/4],gmu[0x7000/4],gmu[0x7004/4],gcc[0x52010/4],gcc[0x52000/4]};
 return index<5?v[index]:0;
}
'''


class RedfinGMUAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root/'redfin_gmu_probe.h').write_text((HERE/'gmu-probe.h').read_text())
        source = root/'adapter.c'
        source.write_text(HARNESS.replace('ACTUAL_SOURCE', adapter_source()))
        subprocess.run([shutil.which('clang') or 'cc', '-std=c11', '-Wall', '-Wextra',
                        '-Werror', '-shared', '-fPIC', '-I', str(root),
                        '-I', str(HERE/'include'), str(source), '-o', str(root/'adapter.dylib')],
                       check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(root/'adapter.dylib'))
        cls.lib.host_reset.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        cls.lib.host_property.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
        cls.lib.host_args.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        cls.lib.host_final.restype = ctypes.c_uint32

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def reset(self, scenario=0, failure=0, args=ARGS, values=None):
        encoded = args.encode()+b'\0'
        self.lib.host_reset(encoded, len(encoded), scenario, failure)
        for i, value in enumerate(properties() if values is None else values):
            self.lib.host_property(i, value or b'', len(value or b''), value is not None)

    def metrics(self):
        values = tuple(self.lib.host_metric(i) for i in range(8))
        self.assertEqual(values[1], 0)
        self.assertEqual(values[6], 0)
        return values

    def test_generated_adt_contract_is_read_only_and_real_adapter_executes_leaf(self):
        self.reset()
        self.assertEqual(self.lib.host_contract(), 0)
        self.assertEqual(self.metrics(), (0,)*8)
        self.assertEqual(self.lib.host_probe(), 0)
        metrics = self.metrics()
        self.assertEqual((metrics[0], metrics[4], metrics[7]), (4, 4, 15))
        self.assertEqual(tuple(self.lib.host_final(i) for i in range(5)),
                         (1, 0x12345678, 0xFEDCBA98, 0x40000001, 0x18000))

    def test_every_property_bit_mutation_is_rejected_before_mapping(self):
        baseline = properties()
        for index, value in enumerate(baseline):
            for bit in range(len(value)*8):
                changed = list(baseline)
                altered = bytearray(value)
                altered[bit//8] ^= 1 << (bit % 8)
                changed[index] = bytes(altered)
                self.reset(values=changed)
                self.assertEqual(self.lib.host_probe(), errno.ENXIO)
                self.assertEqual(self.metrics(), (0,)*8)

    def test_each_missing_or_wrong_size_property_is_rejected_before_mapping(self):
        baseline = properties()
        for index, value in enumerate(baseline):
            for replacement in (None, b'', value[:-1], value+b'\0'):
                changed = list(baseline)
                changed[index] = replacement
                self.reset(values=changed)
                self.assertEqual(self.lib.host_probe(), errno.ENXIO)
                self.assertEqual(self.metrics(), (0,)*8)

    def test_gic_zero_loss_typo_is_rejected_and_never_mapped(self):
        values = properties()
        bad_reg = bytearray(values[2])
        struct.pack_into('<Q', bad_reg, 6*8, 0x017A0000)
        values[2] = bytes(bad_reg)
        self.reset(values=values)
        self.assertEqual(self.lib.host_probe(), errno.ENXIO)
        self.assertEqual(self.metrics(), (0,)*8)

    def test_argument_words_are_exact_unique_and_unknown_modes_do_not_map(self):
        for word in ARGS.split():
            for changed in (ARGS+' '+word, ARGS.replace(word, '', 1)):
                self.reset(args=changed)
                self.assertEqual(self.lib.host_probe(), errno.ENOTSUP)
                self.assertEqual(self.metrics(), (0,)*8)
        for extra in ('redfingmu=2', 'redfinufs=1', 'redfingui=1', 'wifi=1', 'gpu=1'):
            self.reset(args=ARGS+' '+extra)
            self.assertEqual(self.lib.host_probe(), errno.ENOTSUP)
            self.assertEqual(self.metrics(), (0,)*8)
        for nonce in ('0000000000000000', '1234567890abcdeF', '1234567890abcdeg'):
            self.reset(args=ARGS.replace('1234567890abcdef', nonce))
            self.assertEqual(self.lib.host_probe(), errno.ENOTSUP)

    def test_trace_flag_is_optional_but_unique(self):
        self.reset(args=ARGS+' -enable_kprintf_spam')
        self.assertEqual(self.lib.host_probe(), 0)
        self.reset(args=ARGS+' -enable_kprintf_spam -enable_kprintf_spam')
        self.assertEqual(self.lib.host_probe(), errno.ENOTSUP)

    def test_missing_parent_wrong_el_cpu_or_return_proof_rejects_before_map(self):
        for issue in (1, 2, 3, 4, 5, 22, 23, 24):
            self.reset(issue)
            self.assertNotEqual(self.lib.host_probe(), 0)
            metrics = self.metrics()
            self.assertEqual((metrics[0], metrics[2], metrics[3]), (0, 0, 0))

    def test_mapping_failure_and_inactive_clocks_or_domain_stop_before_gmu_access(self):
        for issue, expected_maps in ((6, 1), (7, 2), (8, 3), (9, 4),
                                      (10, 1), (11, 2), (12, 2)):
            self.reset(issue)
            self.assertNotEqual(self.lib.host_probe(), 0)
            metrics = self.metrics()
            self.assertEqual(metrics[0], expected_maps)
            self.assertEqual(metrics[3:5], (0, 0))

    def test_enabled_pending_or_active_gmu_irq_stops_before_gmu_map(self):
        for issue in (13, 14, 15):
            self.reset(issue)
            self.assertEqual(self.lib.host_probe(), errno.EAGAIN)
            metrics = self.metrics()
            self.assertEqual(metrics[0], 3)
            self.assertEqual(metrics[3:5], (0, 0))

    def test_mismatched_pll_identity_is_reported_without_any_write(self):
        self.reset(16)
        self.assertEqual(self.lib.host_probe(), errno.EAGAIN)
        self.assertEqual(self.metrics()[3:5], (0, 0))

    def test_late_argument_parent_binding_or_irq_change_stops_before_next_write(self):
        for issue in (17, 18, 19, 20, 21):
            self.reset(issue)
            self.assertEqual(self.lib.host_probe(), errno.ECANCELED)
            metrics = self.metrics()
            self.assertEqual(metrics[3:5], (1, 0))

    def test_every_parent_lifetime_revocation_stops_further_mmio(self):
        self.reset()
        self.assertEqual(self.lib.host_probe(), 0)
        baseline = self.metrics()[5]
        for failure in range(1, baseline+1):
            self.reset(failure=failure)
            self.assertNotEqual(self.lib.host_probe(), 0)
            metrics = self.metrics()
            self.assertEqual(metrics[5], failure)

    def test_guard_overhead_is_measured_in_the_actual_adapter_counter_window(self):
        self.reset(26)
        self.assertEqual(self.lib.host_probe(), 0)
        self.assertEqual(self.metrics()[4], 4)

    def test_repeated_entry_is_one_shot_even_after_refusal(self):
        for issue in (0, 2):
            self.reset(issue)
            self.lib.host_probe()
            before = self.metrics()
            self.assertEqual(self.lib.host_probe(), errno.EBUSY)
            self.assertEqual(self.metrics(), before)


if __name__ == '__main__':
    unittest.main()
