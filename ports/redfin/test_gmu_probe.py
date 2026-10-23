"""Validate the real GMU kernel adapter, generated ADT and native FDT checks."""
import copy
import ctypes
import errno
from pathlib import Path
import re
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
SMMU_ARGS = ARGS + ' redfinsmmu=1'


def fixture(smmu=False):
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
    if smmu:
        modern, legacy = '/soc/kgsl-smmu@3da0000', '/soc/qcom,kgsl-iommu@3da0000'
        clocks = cells(1, 35, 1, 36, 2, 0, 2, 12)
        nodes[modern] = {
            'compatible': b'qcom,qsmmu-v500\0', 'phandle': cells(6),
            'reg': cells(0x3DA0000, 0x10000, 0x3DC2000, 0x20),
            'reg-names': b'base\0tcu-base\0', '#iommu-cells': cells(2),
            'qcom,skip-init': b'', 'qcom,use-3-lvl-tables': b'', 'qcom,no-dynamic-asid': b'',
            '#global-interrupts': cells(1), 'vdd-supply': cells(4), 'clocks': clocks,
            'clock-names': b'gcc_gpu_memnoc_gfx\0gcc_gpu_snoc_dvm_gfx\0gpu_cc_ahb\0'
                           b'gpu_cc_hlos1_vote_gpu_smmu_clk\0',
            'interrupts': cells(*(word for irq in (673, *range(678, 686)) for word in (0, irq, 4))),
        }
        nodes[legacy] = {
            'compatible': b'qcom,kgsl-smmu-v2\0', 'reg': cells(0x3DA0000, 0x10000),
            'qcom,protect': cells(0xA0000, 0xC000), 'qcom,secure_align_mask': cells(0xFFF),
            'qcom,retention': b'', 'qcom,hyp_secure_alloc': b'', 'clocks': clocks,
            'clock-names': b'gcc_gpu_memnoc_gfx\0gcc_gpu_snoc_dvm_gfx\0gpu_cc_ahb\0smmu_vote\0',
        }
        for child, stream, kind in (('gmu_user', 4, b'qcom,smmu-gmu-user-cb\0'),
                                     ('gmu_kernel', 5, b'qcom,smmu-gmu-kernel-cb\0')):
            nodes[gmu + '/' + child] = {
                'compatible': kind, 'iommus': cells(6, stream, 0x400),
                'qcom,iommu-dma': b'disabled\0',
            }
    tree = mkadt.build(0x180000000, 0x80000000)
    tree.children.append(mkadt.node('redfin-gpu-power', [
        ('cx-parent', mkadt.u32(0x30000, 64, 65535, 7, 416)),
        ('chip-id', mkadt.u32(0x06020001))]))
    return tree, nodes


def properties(smmu=False):
    tree, nodes = fixture(smmu)
    gmu_probe.add_contract(tree, nodes, smmu=smmu)
    leaf = next(n for n in tree.children if n.name == 'redfin-gmu')
    result = [mkadt.u64(0x180000000), mkadt.u64(0x80000000)] + [
        leaf.prop(name) for name in ('reg', 'chip-id', 'clock-policy',
                                     'tcm-policy', 'cx-parent', 'gic-intids')]
    if smmu:
        leaf = next(n for n in tree.children if n.name == 'redfin-gpu-smmu')
        result += [leaf.prop(name) for name in ('reg', 'chip-id', 'stream-map',
                                              'format-policy', 'clock-policy', 'gic-intids')]
    return result


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
                'bsd/dev/redfin_gpu_smmu.h': HERE/'include/redfin_gpu_smmu.h',
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
        self.assertEqual(leaf.prop('gic-intids'), mkadt.u32(336, 337))
        # Ownership metadata must not invoke IOKit's interrupt mapper.
        self.assertIsNone(leaf.prop('interrupts'))
        self.assertIsNone(leaf.prop('interrupt-parent'))
        self.assertEqual({name for name, _, _ in leaf.props},
                         {'name', 'reg', 'chip-id', 'clock-policy', 'tcm-policy',
                          'cx-parent', 'gic-intids'})

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

    def test_optional_smmu_contract_uses_native_resource_streams_clocks_and_irqs(self):
        tree, nodes = fixture(True)
        gmu_probe.add_contract(tree, nodes, smmu=True)
        leaf = next(n for n in tree.children if n.name == 'redfin-gpu-smmu')
        expected = {
            'reg': mkadt.u64(0x3DA0000, 0x10000), 'chip-id': mkadt.u32(0x06020001),
            'stream-map': mkadt.u32(4, 0x400, 5, 0x400),
            'format-policy': mkadt.u32(0x1000, 0x8000, 128, 8, 39, 36),
            'clock-policy': mkadt.u32(0, 0x7100C, 0x80000001, 1, 0, 0x71018, 0x80000001, 1,
                                      1, 0x1078, 1, 1, 1, 0x5000, 0x80000001, 1),
            'gic-intids': mkadt.u32(705, *range(710, 718)),
        }
        self.assertEqual({k for k, _, _ in leaf.props}, {'name', *expected})
        for key, value in expected.items():
            self.assertEqual(leaf.prop(key), value)

    def test_all_selected_native_properties_fail_atomically_on_corruption_or_omission(self):
        tree, nodes = fixture(True)
        for path, values in nodes.items():
            for key, value in values.items():
                for omitted in (False, True):
                    changed = copy.deepcopy(nodes)
                    if omitted:
                        del changed[path][key]
                    else:
                        altered = bytearray(value or b'\0')
                        altered[0] ^= 0x80
                        changed[path][key] = bytes(altered)
                    candidate = copy.deepcopy(tree)
                    before = mkadt.adt.serialize(candidate)
                    with self.assertRaises(ValueError, msg=(path, key, omitted)):
                        gmu_probe.add_contract(candidate, changed, smmu=True)
                    self.assertEqual(mkadt.adt.serialize(candidate), before)

    def test_smmu_stream_phandle_id_mask_and_upstream_aperture_are_not_substitutable(self):
        for child in ('gmu_user', 'gmu_kernel'):
            path = '/soc/qcom,gmu@3d6a000/' + child
            for field in range(3):
                for bit in range(32):
                    tree, nodes = fixture(True)
                    words = list(struct.unpack('>3I', nodes[path]['iommus']))
                    words[field] ^= 1 << bit
                    nodes[path]['iommus'] = struct.pack('>3I', *words)
                    with self.assertRaises(ValueError):
                        gmu_probe.add_contract(tree, nodes, smmu=True)
        for path in ('/soc/kgsl-smmu@3da0000', '/soc/qcom,kgsl-iommu@3da0000'):
            tree, nodes = fixture(True)
            values = bytearray(nodes[path]['reg'])
            struct.pack_into('>I', values, 4, 0x20000)
            nodes[path]['reg'] = bytes(values)
            with self.assertRaises(ValueError):
                gmu_probe.add_contract(tree, nodes, smmu=True)

    def test_smmu_phandle_irq_parent_duplicate_and_nonboolean_selection_fail(self):
        for problem in ('phandle', 'irq-parent', 'duplicate', 'nonboolean'):
            tree, nodes = fixture(True)
            selected = True
            if problem == 'phandle':
                nodes['/bogus'] = {'phandle': nodes['/soc/kgsl-smmu@3da0000']['phandle']}
            elif problem == 'irq-parent':
                nodes['/soc/kgsl-smmu@3da0000']['interrupt-parent'] = struct.pack('>I', 1)
            elif problem == 'duplicate':
                tree.children.append(mkadt.node('redfin-gpu-smmu'))
            else:
                selected = 1
            before = mkadt.adt.serialize(tree)
            with self.assertRaises(ValueError):
                gmu_probe.add_contract(tree, nodes, smmu=selected)
            self.assertEqual(mkadt.adt.serialize(tree), before)

    def test_unselected_smmu_needs_no_native_smmu_resources_or_contract(self):
        tree, nodes = fixture()
        gmu_probe.add_contract(tree, nodes)
        self.assertFalse(any(n.name == 'redfin-gpu-smmu' for n in tree.children))


def adapter_source():
    code = (HERE/'gmu-probe.c').read_text()
    code = '\n'.join(line for line in code.splitlines() if not line.startswith('#include'))
    code = code.replace('__builtin_arm_rsr64("CurrentEL")', 'host_el')
    code = code.replace('__builtin_arm_rsr64("MPIDR_EL1")', 'host_mpidr')
    for instruction in ('dmb oshld', 'dmb oshst', 'dsb osh'):
        code = code.replace('__asm__ volatile("'+instruction+'" ::: "memory");', '')
    read = 'uint32_t value = *(volatile const uint32_t *)address;'
    write = '*(volatile uint32_t *)address = value;'
    scalar = '__asm__ volatile("ldr %w0, [%1]" : "=r"(raw) : "r"(address) : "memory");'
    assert code.count(read) == code.count(write) == 1
    assert code.count(scalar) == 1
    return code.replace(scalar, 'raw = host_smmu_read(address);').replace(
        read, 'uint32_t value = host_mmio_read(address);').replace(
        write, 'host_mmio_write(address, value);')


HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdio.h>
#include <sys/errno.h>
#include "redfin_gmu_probe.h"
#include "redfin_gmu_tcm.h"
#include "redfin_gpu_smmu.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
typedef void *DTEntry;
static uint32_t gcc[0x1f0000/4],gpucc[0x9000/4],gmu[0x30000/4],gic[0x4000/4];
static uint32_t smmu[0x8000/4],smmu_offsets[1024],write_trace[128][3];
static char live_args[608],parent_args[608];
static unsigned arg_bytes,scenario,maps,bad,raw_reads,raw_writes,dtcm_writes;
static unsigned parent_calls,fail_parent,after_loss,map_mask;
static uint64_t host_el,host_mpidr,now_ns;
static bool parent_lost;
static int parent_cookie;
static unsigned smmu_reads,smmu_maps,smmu_gic_reads,changed_smmu_read,revoke_smmu_read;
static unsigned event_clock,events[6],logs,log_events[512];
static char log_lines[512][320];
struct property {uint8_t data[128];unsigned bytes;bool present;};
static struct property props[14];
static const char *keys[14]={"dram-base","dram-size","reg","chip-id","clock-policy","tcm-policy","cx-parent","gic-intids",
 "reg","chip-id","stream-map","format-policy","clock-policy","gic-intids"};
static int log_sink(const char *text,...) {
 if(logs>=512){bad++;return 0;}
 va_list ap;va_start(ap,text);vsnprintf(log_lines[logs],sizeof(log_lines[logs]),text,ap);va_end(ap);
 log_events[logs]=++event_clock;
 if(strstr(log_lines[logs],"REDFIN GMU: result=0 stage=10"))events[5]=event_clock;
 if(scenario==53&&strstr(log_lines[logs],"unit=0 offset=0 first-read"))parent_lost=true;
 if(scenario==54&&strstr(log_lines[logs],"REDFIN SMMU ACCESS: phase=ids"))parent_lost=true;
 if(strstr(text,"REDFIN SMMU STEP: fresh GMU DONE")) {
  if(scenario==39)gpucc[0x1124/4]^=0x100;
  if(scenario==40)gmu[0x14000/4]=0;
  if(scenario==41)gcc[0x7100c/4]|=0x80000000u;
  if(scenario==42)gpucc[0x100c/4]=0;
  if(scenario==44)live_args[0]='X';
  if(scenario==45)parent_args[0]='X';
  if(scenario==50)props[8].data[0]^=1;
  if(scenario==56)gcc[0x71018/4]|=0x80000000u;
  if(scenario==57)gpucc[0x1078/4]&=~1u;
  if(scenario==58)gpucc[0x5000/4]&=~1u;
  if(scenario==59)gcc[0x71028/4]=2;
  if(scenario==60)gmu[0x14070/4]=1;
  if(scenario==61)gmu[0x14600/4]=1;
  if(scenario==62)gpucc[0x109c/4]&=~1u;
  if(scenario==63)gcc[0x40/4]++;
  if(scenario==64)gcc[0x52010/4]&=~1u;
  if(scenario==65)gcc[0x52000/4]&=~0x10000u;
  if(scenario==66)gpucc[0x1120/4]|=1u;
  if(scenario==67)gpucc[0x1098/4]&=~1u;
  if(scenario==68)gpucc[0x1064/4]=1;
 }
 logs++;return 0;
}
#define printf log_sink
const char *PE_boot_args(void){return scenario==1?NULL:live_args;}
int redfin_spmi_return_ready(void){return scenario==3?0:1;}
int SecureDTLookupEntry(void *root,const char *path,DTEntry *out) {
 (void)root;
 if(!strcmp(path,"/chosen")){*out=(void*)1;return 0;}
 if(!strcmp(path,"/redfin-gmu")){*out=(void*)2;return 0;}
 if(!strcmp(path,"/redfin-gpu-smmu")){*out=(void*)3;return 0;}
 return -1;
}
int SecureDTGetProperty(DTEntry node,const char *key,const void **out,unsigned *n) {
 for(unsigned i=0;i<14;i++)if(node==(void*)(uintptr_t)(i<2?1:i<8?2:3)&&!strcmp(key,keys[i])&&props[i].present) {
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
 if(address==RF_GS_PHYS&&size==sizeof(smmu)) {
  smmu_maps++;events[4]=++event_clock;
  if(scenario==30)return 0;
  map_mask|=16;return (uintptr_t)smmu;
 }
 bad++;return 0;
}
static int unit_and_offset(vm_offset_t address,unsigned *unit,uint32_t *at) {
 uintptr_t bases[]={(uintptr_t)gcc,(uintptr_t)gpucc,(uintptr_t)gmu,(uintptr_t)gic,(uintptr_t)smmu};
 size_t sizes[]={sizeof(gcc),sizeof(gpucc),sizeof(gmu),sizeof(gic),sizeof(smmu)};
 for(unsigned i=0;i<5;i++)if(address>=bases[i]&&address-bases[i]<sizes[i]&&!(address&3)) {
  *unit=i;*at=(uint32_t)(address-bases[i]);return 1;
 }
 bad++;return 0;
}
static uint32_t host_mmio_read(vm_offset_t address) {
 unsigned unit;uint32_t at;
 if(!unit_and_offset(address,&unit,&at))return UINT32_MAX;
 if(parent_lost)after_loss++;
 if(unit==3) {
  if(at!=0x128&&at!=0x228&&at!=0x328&&at!=0x158&&at!=0x258&&at!=0x358)bad++;
  if(at==0x158||at==0x258||at==0x358)smmu_gic_reads++;
 } else if(!rf_gt_allowed(unit,at,false))bad++;
 unsigned event=++event_clock;
 if(unit==0&&at==0&&!events[0])events[0]=event;
 if(unit==2&&at==0x14000&&!events[1])events[1]=event;
 if(unit==2&&at==0x14220&&!events[2])events[2]=event;
 raw_reads++;now_ns+=scenario==26?1000:20;
 if(unit==RF_GT_GMU && at==0x14220)return 0x12340000u+(uint32_t)(now_ns*192/10000);
 if(scenario==46&&unit==RF_GT_GMU&&at==0x7000&&dtcm_writes==2)return *(uint32_t*)address^1;
 return *(uint32_t*)address;
}
static void host_mmio_write(vm_offset_t address,uint32_t value) {
 unsigned unit;uint32_t at;
 if(!unit_and_offset(address,&unit,&at))return;
 if(parent_lost)after_loss++;
 if(!rf_gt_allowed(unit,at,true)||(unit==RF_GT_GMU&&at==0x14000&&value!=1))bad++;
 if(smmu_maps)bad++;
 if(raw_writes<128) {
  write_trace[raw_writes][0]=unit;write_trace[raw_writes][1]=at;write_trace[raw_writes][2]=value;
 } else bad++;
 event_clock++;
 raw_writes++;now_ns+=scenario==26?1000:20;
 *(uint32_t*)address=value;
 if((unit==RF_GT_GCC&&(at==0x71154||at==0x7100c||at==0x71018)) ||
    (unit==RF_GT_GPUCC&&(at==0x1078||at==0x109c||at==0x5000||at==0x1098))) {
  if(value&1)*(uint32_t*)address&=~0x80000000u;
  if(unit==RF_GT_GPUCC&&at==0x1098&&(value&1)) {
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
static uint32_t host_smmu_read(vm_offset_t address) {
 unsigned unit;uint32_t at;
 if(!unit_and_offset(address,&unit,&at))return UINT32_MAX;
 if(unit!=4||at>=0x8000||!events[5]||gmu[0x14000/4]!=1||
  (gpucc[0x1124/4]&0x10371fu)!=0x602u||!(map_mask&16))bad++;
 bool allowed=at==0||at==0x20||at==0x24||at==0x28||at==0x3c||
  at==0x48||at==0x50||at==0x54||at==0x58||
  (at>=0x800&&at<0x840)||(at>=0xc00&&at<0xc40)||
  (at>=0x1000&&at<0x1020)||(at>=0x1800&&at<0x1820);
 if(!allowed)bad++;
 if(parent_lost)after_loss++;
 if(smmu_reads<1024)smmu_offsets[smmu_reads]=at;else bad++;
 smmu_reads++;raw_reads++;now_ns+=20;unsigned event=++event_clock;
 if(!events[3])events[3]=event;
 if(changed_smmu_read==smmu_reads|| (scenario==36&&smmu_reads==67))*(uint32_t*)address^=1;
 uint32_t value=*(uint32_t*)address;
 if(revoke_smmu_read==smmu_reads||(scenario==37&&smmu_reads==1))parent_lost=true;
 if(scenario==38&&smmu_reads==1)props[8].data[0]^=1;
 if(scenario==43&&smmu_reads==1)gic[0x258/4]|=1u<<7;
 if(scenario==51&&smmu_reads==1)gpucc[0x1098/4]&=~1u;
 return value;
}
void delay(int us){if(us<0){bad++;return;}now_ns+=(uint64_t)(unsigned)us*1000;}
uint64_t mach_absolute_time(void){return now_ns;}
void absolutetime_to_nanoseconds(uint64_t time,uint64_t *out){*out=time;}
ACTUAL_SOURCE
void host_reset(const char *args,unsigned n,unsigned issue,unsigned failure) {
 memset(gcc,0,sizeof(gcc));memset(gpucc,0,sizeof(gpucc));memset(gmu,0,sizeof(gmu));memset(gic,0,sizeof(gic));
 memset(smmu,0,sizeof(smmu));memset(props,0,sizeof(props));memset(events,0,sizeof(events));
 memset(write_trace,0,sizeof(write_trace));smmu_reads=smmu_maps=smmu_gic_reads=0;
 changed_smmu_read=revoke_smmu_read=event_clock=logs=0;
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
 if(issue==31)gic[0x158/4]=1u<<1;
 if(issue==32)gic[0x258/4]=1u<<7;
 if(issue==33)gic[0x358/4]=1u<<13;
 if(issue==47)gmu[0x14070/4]=1;
 smmu[0x20/4]=(1u<<30)|(1u<<27)|(11u<<9)|16;
 smmu[0x24/4]=(2u<<28)|8;smmu[0x28/4]=(1u<<12)|(2u<<8)|(1u<<4)|1;smmu[0x3c/4]=0x20;
 smmu[0x800/4]=0x84000004;smmu[0x804/4]=0x84000005;
 for(unsigned i=0;i<16;i++)smmu[(0xc00+4*i)/4]=i<2?i:(2u<<16);
 for(unsigned i=0;i<8;i++){smmu[(0x1000+4*i)/4]=0x10000;smmu[(0x1800+4*i)/4]=1;}
 if(issue==34)smmu[0x24/4]=(3u<<28)|8;
 if(issue==35)smmu[0x28/4]&=~(1u<<12);
 if(issue==48)smmu[0x24/4]|=1u<<31;
 if(issue==49)smmu[0x20/4]|=1u<<8;
}
void host_property(unsigned index,const void *p,unsigned n,int present) {
 if(index>=14||n>128)abort();memset(&props[index],0,sizeof(props[index]));
 if(n)memcpy(props[index].data,p,n);props[index].bytes=n;props[index].present=present!=0;
}
int host_contract(void){return redfin_gmu_probe_contract(parent_args,arg_bytes);}
int host_probe(void){return redfin_gmu_probe(scenario==22?NULL:parent_args,arg_bytes,
 scenario==24?NULL:&parent_cookie,scenario==23?NULL:parent_valid);}
int host_args(const char *s,unsigned n){return redfin_gmu_args_valid(s,n);}
int host_select(const char *s,unsigned n,bool *out){return redfin_gmu_args_select(s,n,out);}
void host_smmu_fault(unsigned change,unsigned revoke){changed_smmu_read=change;revoke_smmu_read=revoke;}
unsigned host_smmu_metric(unsigned i) {
 unsigned v[]={smmu_reads,smmu_maps,smmu_gic_reads,logs};return i<4?v[i]:999;
}
uint32_t host_smmu_offset(unsigned i){return i<smmu_reads&&i<1024?smmu_offsets[i]:UINT32_MAX;}
const char *host_log(unsigned i){return i<logs?log_lines[i]:"";}
unsigned host_log_event(unsigned i){return i<logs?log_events[i]:0;}
unsigned host_event(unsigned i){return i<6?events[i]:0;}
uint32_t host_write_trace(unsigned i,unsigned part){return i<raw_writes&&i<128&&part<3?write_trace[i][part]:UINT32_MAX;}
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
        cls.lib.host_select.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_bool)]
        cls.lib.host_final.restype = ctypes.c_uint32
        cls.lib.host_smmu_offset.restype = ctypes.c_uint32
        cls.lib.host_write_trace.restype = ctypes.c_uint32
        cls.lib.host_log.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def reset(self, scenario=0, failure=0, args=None, values=None, smmu=False):
        args = (SMMU_ARGS if smmu else ARGS) if args is None else args
        encoded = args.encode()+b'\0'
        self.lib.host_reset(encoded, len(encoded), scenario, failure)
        for i, value in enumerate(properties(smmu) if values is None else values):
            self.lib.host_property(i, value or b'', len(value or b''), value is not None)

    def metrics(self):
        values = tuple(self.lib.host_metric(i) for i in range(8))
        self.assertEqual(values[1], 0)
        self.assertEqual(values[6], 0)
        return values

    def logs(self):
        return [self.lib.host_log(i).decode() for i in range(self.lib.host_smmu_metric(3))]

    def writes(self):
        return [tuple(self.lib.host_write_trace(i, j) for j in range(3))
                for i in range(self.metrics()[3])]

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

    def test_optional_smmu_selection_is_exact_unique_and_cannot_escape_gmu_mode(self):
        for args, expected in ((ARGS, False), (SMMU_ARGS, True),
                               (SMMU_ARGS+' -enable_kprintf_spam', True)):
            selected = ctypes.c_bool(not expected)
            raw = args.encode()+b'\0'
            self.assertEqual(self.lib.host_select(raw, len(raw), ctypes.byref(selected)), 1)
            self.assertEqual(selected.value, expected)
        bad = [ARGS+' '+word for word in ('redfinsmmu=0', 'redfinsmmu=2', 'redfinsmmu=01',
                                          'redfinsmmu=1x', 'redfinsmmu=+1',
                                          'redfinsmmu=1 redfinsmmu=1')]
        bad += [SMMU_ARGS.replace(word, '', 1) for word in ('redfingmu=1', 'redfinreturn=1', 'rd=md0')]
        bad += [SMMU_ARGS.replace('cpus=1', 'cpus=8'), SMMU_ARGS+' redfingui=1']
        for args in bad:
            for previous in (False, True):
                selected = ctypes.c_bool(previous)
                raw = args.encode()+b'\0'
                self.assertEqual(self.lib.host_select(raw, len(raw), ctypes.byref(selected)), 0)
                self.assertEqual(selected.value, previous)
            self.reset(args=args, smmu=True)
            self.assertEqual(self.lib.host_contract(), errno.ENOTSUP)
            self.assertEqual(self.lib.host_probe(), errno.ENOTSUP)
            self.assertEqual(self.metrics(), (0,)*8)

    def test_selected_contract_is_read_only_and_snapshot_preserves_all_gmu_writes(self):
        self.reset()
        self.assertEqual(self.lib.host_probe(), 0)
        original_writes = self.writes()
        self.reset(smmu=True)
        self.assertEqual(self.lib.host_contract(), 0)
        self.assertEqual(self.metrics(), (0,)*8)
        self.assertEqual(self.lib.host_probe(), 0)
        self.assertEqual(self.writes(), original_writes)
        self.assertEqual((self.metrics()[0], self.metrics()[4], self.metrics()[7]), (5, 4, 31))
        self.assertEqual(self.lib.host_smmu_metric(0), 114)
        first = [0x20, 0x24, 0x28, 0x3C, 0, 0x48, 0x50, 0x54, 0x58]
        first += [at for i in range(16) for at in (0x800+4*i, 0xC00+4*i)]
        first += [at for i in range(8) for at in (0x1000+4*i, 0x1800+4*i)]
        offsets = [self.lib.host_smmu_offset(i) for i in range(114)]
        self.assertEqual(offsets, first*2)
        self.assertLess(max(offsets), 0x8000)
        self.assertLess(self.lib.host_event(5), self.lib.host_event(4))
        self.assertLess(self.lib.host_event(4), self.lib.host_event(3))
        messages = self.logs()
        self.assertEqual(sum('REDFIN SMMU ROUTE:' in line for line in messages), 16)
        self.assertEqual(sum('REDFIN SMMU GR1:' in line for line in messages), 8)
        self.assertTrue(any('stable=1 format=1' in line for line in messages))
        self.assertTrue(any('unreferenced is not owned' in line for line in messages))

    def test_each_smmu_property_bit_is_rejected_by_pre_arc_contract_before_mapping(self):
        baseline = properties(True)
        for index in range(8, 14):
            value = baseline[index]
            for bit in range(len(value)*8):
                changed = list(baseline)
                altered = bytearray(value)
                altered[bit//8] ^= 1 << (bit % 8)
                changed[index] = bytes(altered)
                self.reset(smmu=True, values=changed)
                self.assertEqual(self.lib.host_contract(), errno.ENXIO)
                self.assertEqual(self.lib.host_probe(), errno.ENXIO)
                self.assertEqual(self.metrics(), (0,)*8)

    def test_missing_or_wrong_size_smmu_property_fails_before_parent_power_authority(self):
        baseline = properties(True)
        for index in range(8, 14):
            for replacement in (None, b'', baseline[index][:-1], baseline[index]+b'\0'):
                changed = list(baseline)
                changed[index] = replacement
                self.reset(smmu=True, values=changed)
                self.assertEqual(self.lib.host_contract(), errno.ENXIO)
                self.assertEqual(self.lib.host_probe(), errno.ENXIO)
                self.assertEqual(self.metrics(), (0,)*8)
        self.reset(smmu=True, values=properties())
        self.assertEqual(self.lib.host_contract(), errno.ENXIO)
        self.assertEqual(self.metrics(), (0,)*8)

    def test_unselected_smmu_properties_and_irqs_do_not_enable_any_access(self):
        for issue in (0, 31, 32, 33):
            changed = properties(True)
            changed[8] = b'invalid unselected SMMU'
            self.reset(issue, args=ARGS, values=changed)
            self.assertEqual(self.lib.host_probe(), 0)
            self.assertEqual(self.lib.host_smmu_metric(0), 0)
            self.assertEqual(self.lib.host_smmu_metric(1), 0)
            self.assertEqual(self.lib.host_smmu_metric(2), 0)
            self.assertEqual(self.metrics()[0], 4)

    def test_inherited_smmu_enable_pending_or_active_irq_stops_before_gmu_map(self):
        for issue in (31, 32, 33):
            self.reset(issue, smmu=True)
            self.assertEqual(self.lib.host_probe(), errno.EAGAIN)
            self.assertEqual(self.metrics()[0], 3)
            self.assertEqual(self.metrics()[3:5], (0, 0))
            self.assertEqual(self.lib.host_smmu_metric(0), 0)
            self.assertEqual(self.lib.host_smmu_metric(1), 0)

    def test_smmu_needs_this_calls_successful_fully_restored_tcm_result(self):
        for issue, expected in ((16, errno.EAGAIN), (46, errno.EIO), (47, errno.EBUSY)):
            self.reset(issue, smmu=True)
            self.assertEqual(self.lib.host_probe(), expected)
            self.metrics()
            self.assertEqual(self.lib.host_smmu_metric(0), 0)
            self.assertEqual(self.lib.host_smmu_metric(1), 0)
        self.reset(46, smmu=True)
        self.assertEqual(self.lib.host_probe(), errno.EIO)
        self.assertEqual(tuple(self.lib.host_final(i) for i in range(3)),
                         (1, 0x12345678, 0xFEDCBA98))

    def test_fresh_source_reset_bus_gx_args_and_binding_proofs_precede_smmu_map(self):
        for issue in (39, 40, 41, 42, 44, 45, 50, *range(56, 69)):
            self.reset(issue, smmu=True)
            self.assertEqual(self.lib.host_probe(), errno.ECANCELED)
            self.assertEqual(self.metrics()[0], 4)
            self.assertEqual(self.metrics()[4], 4)
            self.assertNotEqual(self.lib.host_event(5), 0)
            self.assertEqual(self.lib.host_smmu_metric(0), 0)
            self.assertEqual(self.lib.host_smmu_metric(1), 0)

    def test_smmu_map_failure_does_not_access_any_global_or_change_completed_tcm(self):
        self.reset(30, smmu=True)
        self.assertEqual(self.lib.host_probe(), errno.ENOMEM)
        self.assertEqual(self.metrics()[0], 5)
        self.assertEqual(self.metrics()[4], 4)
        self.assertEqual(self.lib.host_smmu_metric(0), 0)

    def test_unsupported_native_id_geometry_stops_after_four_explicit_global_reads(self):
        for issue in (34, 48, 49):
            self.reset(issue, smmu=True)
            self.assertEqual(self.lib.host_probe(), errno.ENOTSUP)
            self.metrics()
            self.assertEqual(self.lib.host_smmu_metric(0), 4)
            self.assertEqual([self.lib.host_smmu_offset(i) for i in range(4)],
                             [0x20, 0x24, 0x28, 0x3C])
            self.assertFalse(any('REDFIN SMMU GR1:' in line for line in self.logs()))

    def test_unsupported_table_format_is_observed_without_acquiring_or_writing_a_context(self):
        self.reset(35, smmu=True)
        self.assertEqual(self.lib.host_probe(), 0)
        self.metrics()
        self.assertEqual(self.lib.host_smmu_metric(0), 114)
        self.assertTrue(any('stable=1 format=0' in line for line in self.logs()))

    def test_every_second_pass_register_change_is_reported_at_first_difference(self):
        self.reset(smmu=True)
        self.assertEqual(self.lib.host_probe(), 0)
        baseline = [self.lib.host_smmu_offset(i) for i in range(114)]
        for changed in range(58, 115):
            self.reset(smmu=True)
            self.lib.host_smmu_fault(changed, 0)
            self.assertEqual(self.lib.host_probe(), errno.EAGAIN)
            self.metrics()
            self.assertEqual(self.lib.host_smmu_metric(0), changed)
            summary = next(line for line in self.logs() if line.startswith('REDFIN SMMU:'))
            match = re.search(r'changed=(0x[0-9a-f]+|0)', summary)
            self.assertEqual(int(match.group(1), 0), baseline[changed-1])
            self.assertIn('stable=0 format=0', summary)

    def test_every_smmu_read_lifetime_revocation_stops_before_any_further_mmio(self):
        for revoked in range(1, 115):
            self.reset(smmu=True)
            self.lib.host_smmu_fault(0, revoked)
            self.assertEqual(self.lib.host_probe(), errno.ECANCELED)
            self.metrics()
            self.assertEqual(self.lib.host_smmu_metric(0), revoked)
            summary = next(line for line in self.logs() if line.startswith('REDFIN SMMU:'))
            self.assertIn('stable=0 format=0', summary)

    def test_late_parent_binding_irq_and_clock_changes_stop_before_next_global_read(self):
        for issue in (37, 38, 43, 51):
            self.reset(issue, smmu=True)
            self.assertEqual(self.lib.host_probe(), errno.ECANCELED)
            self.metrics()
            self.assertEqual(self.lib.host_smmu_metric(0), 1)

    def test_breadcrumbs_precede_critical_accesses_and_never_repeat_in_polls(self):
        self.reset(smmu=True)
        self.assertEqual(self.lib.host_probe(), 0)
        self.metrics()
        messages = self.logs()
        for text, event in (('unit=0 offset=0 first-read', 0),
                            ('unit=2 offset=0x14000 first-read', 1),
                            ('unit=2 offset=0x14220 first-read', 2),
                            ('REDFIN SMMU ACCESS: phase=ids', 3)):
            index = next(i for i, line in enumerate(messages) if text in line)
            self.assertLess(self.lib.host_log_event(index), self.lib.host_event(event))
        accesses = [line for line in messages if line.startswith('REDFIN GMU ACCESS:')]
        self.assertEqual(len(accesses), len(set(accesses)))
        self.assertLessEqual(len(accesses), 46)
        self.assertEqual(sum('DTCM restore begins' in line for line in messages), 1)
        smmu_accesses = [line for line in messages if line.startswith('REDFIN SMMU ACCESS:')]
        self.assertEqual(len(smmu_accesses), 5)
        self.assertEqual(len(smmu_accesses), len(set(smmu_accesses)))

    def test_breadcrumb_logging_cannot_bypass_the_fresh_lease(self):
        self.reset(53)
        self.assertEqual(self.lib.host_probe(), errno.ECANCELED)
        self.metrics()
        self.assertEqual(self.lib.host_event(0), 0)
        self.assertEqual(self.metrics()[3], 0)
        self.reset(54, smmu=True)
        self.assertEqual(self.lib.host_probe(), errno.ECANCELED)
        self.metrics()
        self.assertEqual(self.lib.host_smmu_metric(0), 0)
        self.assertEqual(self.lib.host_smmu_metric(1), 1)

    def test_selected_smmu_entry_remains_one_shot_after_success_or_refusal(self):
        for issue in (0, 31):
            self.reset(issue, smmu=True)
            self.lib.host_probe()
            before = self.metrics()
            self.assertEqual(self.lib.host_probe(), errno.EBUSY)
            self.assertEqual(self.metrics(), before)

    def test_every_selected_parent_lease_revocation_stops_further_mmio(self):
        self.reset(smmu=True)
        self.assertEqual(self.lib.host_probe(), 0)
        baseline = self.metrics()[5]
        for failure in range(1, baseline+1):
            self.reset(failure=failure, smmu=True)
            self.assertNotEqual(self.lib.host_probe(), 0)
            self.assertEqual(self.metrics()[5], failure)


if __name__ == '__main__':
    unittest.main()
