"""Actual C/C++ SNOC SMMU observer: fixed reads, stable evidence, no grants."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import mkadt
import wifi_platform as P
from test_wifi_wlan import source_nodes

HERE = Path(__file__).resolve().parent
IRQS = (132, 81, 415, 416, 417, 86, 94, 96, 82, 119, 120, 87)


def snoc_nodes():
    source = source_nodes()
    w = lambda *v: struct.pack('>' + 'I' * len(v), *v)
    source['/soc/qcom,icnss@18800000'].update({
        'reg': w(0x18800000, 0x800000, 0xb0000000, 0x10000),
        'reg-names': b'membase\0smmu_iova_ipa\0', 'iommus': w(0x18, 0xc0, 1),
        'qcom,iommu-dma-addr-pool': w(0xa0000000, 0x10000000), 'qcom,iommu-dma': b'fastmap\0',
        'qcom,iommu-faults': b'stall-disable\0HUPCF\0non-fatal\0',
        'interrupts': w(*(value for spi in IRQS for value in (0, spi, 4)))})
    source['/soc/apps-smmu@15000000'] = {
        'phandle': w(0x18), 'compatible': b'qcom,qsmmu-v500\0',
        'reg': w(0x15000000, 0x100000, 0x15182000, 0x20), 'reg-names': b'base\0tcu-base\0',
        '#iommu-cells': w(2), 'qcom,skip-init': b'', 'qcom,use-3-lvl-tables': b''}
    return source


HARNESS = r'''
#include <string.h>
#include "wifi_snoc.h"
static uint32_t gr[0x4000/4],cb[0x40000/4],before_gr[0x4000/4],before_cb[0x40000/4];
static struct rf_snoc_snapshot snapshot;
static unsigned checks,reads,violations,check_failure,read_failure,change_at;
static int check(void *ctx){
 ++checks;if(ctx!=&gr)violations++;
 return check_failure && checks>=check_failure ? ECANCELED : 0;
}
static int read_register(void *ctx,unsigned block,uint32_t at,uint32_t *out){
 ++reads;if(ctx!=&gr || !rf_snoc_read_allowed(block,at)){violations++;return EINVAL;}
 if(read_failure && reads>=read_failure)return EIO;
 *out=block ? cb[at/4] : gr[at/4];
 if(change_at && reads==change_at)*out^=1;
 return 0;
}
#ifdef __cplusplus
extern "C" {
#endif
void reset(void){
 memset(gr,0,sizeof(gr));memset(cb,0,sizeof(cb));
 checks=reads=violations=check_failure=read_failure=change_at=0;
 gr[0x20/4]=0x4c017e51;gr[0x24/4]=0x6000003e;gr[0x28/4]=0x5111;gr[0]=0x400;
 for(unsigned i=0;i<RF_SNOC_STREAMS;i++)gr[(0xc00+4*i)/4]=0x10300;
 gr[(0x800+4*3)/4]=0x800100c0;gr[(0xc00+4*3)/4]=5;
 gr[(0x800+4*4)/4]=0x80000521;gr[(0xc00+4*4)/4]=7;
 gr[(0xc00+4*80)/4]=9;
 cb[(5*0x1000)/4]=0x37;gr[(0x1000+4*5)/4]=0x10000;gr[(0x1800+4*5)/4]=1;
 cb[(12*0x1000+0x58)/4]=2;
}
void set_register(unsigned block,unsigned at,uint32_t value){if(rf_snoc_read_allowed(block,at)){if(block)cb[at/4]=value;else gr[at/4]=value;}}
void failure(unsigned which,unsigned at){if(which==0)check_failure=at;else if(which==1)read_failure=at;else change_at=at;}
int run(void){
 const struct rf_snoc_ops ops={&gr,check,read_register};
 memcpy(before_gr,gr,sizeof(gr));memcpy(before_cb,cb,sizeof(cb));
 int error=rf_snoc_observe(&ops,&snapshot);
 if(memcmp(before_gr,gr,sizeof(gr)) || memcmp(before_cb,cb,sizeof(cb)))violations++;
 return error;
}
uint32_t metric(unsigned which){
 uint32_t values[]={checks,reads,violations,snapshot.stage,snapshot.stable,snapshot.reads,snapshot.error,
 snapshot.wlan_matches[0],snapshot.wlan_matches[1],snapshot.wlan_slot[0],snapshot.wlan_slot[1],
 snapshot.ipa_matches,snapshot.malformed_routes,snapshot.blank_unreferenced,snapshot.changed_block,snapshot.changed_offset};
 return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
uint32_t refs(unsigned bank,unsigned active){return bank<RF_SNOC_CONTEXTS ? (active ? snapshot.active_references[bank] : snapshot.references[bank]) : 0;}
int allowed(unsigned block,uint32_t at){return rf_snoc_read_allowed(block,at);}
int invalid(unsigned which){
 struct rf_snoc_ops ops={&gr,check,read_register};
 if(which==0)return rf_snoc_observe(NULL,&snapshot);
 if(which==1)return rf_snoc_observe(&ops,NULL);
 if(which==2)ops.check=NULL;
 if(which==3)ops.read=NULL;
 return rf_snoc_observe(&ops,&snapshot);
}
#ifdef __cplusplus
}
#endif
'''


class SnocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc') or not shutil.which('c++'):
            raise unittest.SkipTest('host C/C++ compilers unavailable')
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        cls.libs = []
        for compiler, suffix, standard in (('cc', 'c', 'c11'), ('c++', 'cpp', 'c++17')):
            source, library = directory / ('observer.' + suffix), directory / ('observer-' + suffix + '.so')
            source.write_text(HARNESS)
            result = subprocess.run([compiler, '-std=' + standard, '-O2', '-Wall', '-Wextra', '-Werror',
                '-shared', '-fPIC', '-I', str(HERE), str(source), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library)); lib.metric.restype = lib.refs.restype = C.c_uint32
            cls.libs.append(lib)

    def setUp(self):
        for lib in self.libs: lib.reset()

    def test_stable_double_snapshot_separates_wlan_ipa_and_latent_foreign_references(self):
        for lib in self.libs:
            self.assertEqual(lib.run(), 0)
            self.assertEqual([lib.metric(i) for i in (1, 2, 3, 4, 5, 6)], [836, 0, 4, 1, 836, 0])
            self.assertEqual([lib.metric(i) for i in range(7, 14)], [1, 1, 3, 3, 1, 0, 58])
            self.assertEqual([lib.refs(i, 0) for i in (0, 5, 7, 9, 12)], [0, 1, 1, 1, 0])
            self.assertEqual([lib.refs(i, 1) for i in (5, 7, 9)], [1, 1, 0])

    def test_every_owner_check_and_read_failure_stops_at_the_failure_without_more_io(self):
        for lib in self.libs:
            for which, total in ((0, 837), (1, 836)):
                for at in range(1, total + 1):
                    lib.reset(); lib.failure(which, at)
                    self.assertEqual(lib.run(), errno.ECANCELED if which == 0 else errno.EIO)
                    self.assertEqual(lib.metric(1), at - 1 if which == 0 else at)
                    self.assertEqual(lib.metric(4), 0); self.assertEqual(lib.metric(2), 0)

    def test_every_changed_second_pass_register_refuses_a_stable_snapshot(self):
        for lib in self.libs:
            for at in range(419, 837):
                lib.reset(); lib.failure(2, at)
                self.assertEqual(lib.run(), errno.EAGAIN)
                self.assertEqual(lib.metric(1), at); self.assertEqual(lib.metric(4), 0)

    def test_unknown_ids_or_control_layouts_never_reach_context_registers(self):
        for lib in self.libs:
            for at, value in ((0x20, 0), (0x24, 0x6000003f), (0x28, 0), (0, 0x401), (0, 0x408), (0, 0)):
                lib.reset(); lib.set_register(0, at, value)
                self.assertEqual(lib.run(), errno.ENOTSUP)
                self.assertLessEqual(lib.metric(1), 4); self.assertEqual(lib.metric(4), 0)

    def test_duplicate_broad_and_missing_wlan_routes_are_evidence_without_a_unique_slot(self):
        for lib in self.libs:
            lib.set_register(0, 0x800 + 4*27, 0x800100c0)
            self.assertEqual(lib.run(), 0)
            self.assertEqual([lib.metric(i) for i in (7, 8, 9, 10)], [2, 2, 0xffffffff, 0xffffffff])
            lib.reset(); lib.set_register(0, 0x800 + 4*3, 0)
            self.assertEqual(lib.run(), 0)
            self.assertEqual([lib.metric(i) for i in (7, 8, 9, 10)], [0, 0, 0xffffffff, 0xffffffff])
            lib.reset(); lib.set_register(0, 0x800 + 4*3, 0x87ff00c0)
            self.assertEqual(lib.run(), 0)
            self.assertEqual(lib.metric(11), 2)

    def test_malformed_foreign_routes_cannot_leave_any_blank_bank_candidate(self):
        for lib in self.libs:
            for smr, s2cr in ((0, 0x30000), (0, 62), (0x80008000, 0x10000)):
                lib.reset(); lib.set_register(0, 0x800 + 4*27, smr); lib.set_register(0, 0xc00 + 4*27, s2cr)
                self.assertEqual(lib.run(), 0)
                self.assertEqual(lib.metric(12), 1); self.assertEqual(lib.metric(13), 0)

    def test_exact_read_allowlist_excludes_tlbs_tables_fault_ack_and_tcu_tbu_windows(self):
        global_offsets = {0, 0x20, 0x24, 0x28, 0x48, 0x50, 0x54, 0x58}
        global_offsets.update(base + 4*i for base, count in ((0x800, 81), (0xc00, 81), (0x1000, 62), (0x1800, 62)) for i in range(count))
        context_offsets = {0x1000*i + at for i in range(62) for at in (0, 0x58)}
        for lib in self.libs:
            for block, size, allowed in ((0, 0x4000, global_offsets), (1, 0x40000, context_offsets)):
                for at in range(size): self.assertEqual(bool(lib.allowed(block, at)), at in allowed)
            self.assertEqual(lib.allowed(2, 0), 0); self.assertEqual(lib.allowed(0, 0xffffffff), 0)

    def test_invalid_ops_and_inaccessible_values_do_not_claim_stability(self):
        for lib in self.libs:
            for which in range(4): self.assertEqual(lib.invalid(which), errno.EINVAL)
            for block, at in ((0, 0x20), (0, 0x800), (0, 0x1000), (1, 0x58)):
                lib.reset(); lib.set_register(block, at, 0xffffffff)
                self.assertEqual(lib.run(), errno.EIO); self.assertEqual(lib.metric(4), 0)

    def tree(self, source):
        root = mkadt.build(0x180000000, 0x80000000)
        P.add_wlfw_contract(root, source)
        P.add_wlan_observer_contract(root, source, power=True, bdf=True)
        return root

    def test_producer_binds_actual_snoc_wlan_stream_abi_and_requires_completed_profile(self):
        source = snoc_nodes(); root = self.tree(source)
        P.add_snoc_observer_contract(root, source)
        node = next(n for n in root.children if n.name == 'redfin-wifi-snoc')
        self.assertEqual(struct.unpack('<8I', node.prop('source-contract')), (1, 0xc0, 1, 81, 62, 0x4000, 0x80000, 0x1000))
        self.assertEqual(struct.unpack('<12I', node.prop('ce-intids')), tuple(i + 32 for i in IRQS))
        self.assertEqual(node.prop('observe-only'), struct.pack('<I', 1))
        with self.assertRaises(ValueError): P.add_snoc_observer_contract(root, source)
        with self.assertRaises(ValueError): P.add_snoc_observer_contract(mkadt.build(0x180000000, 0x80000000), source)

    def test_changed_routes_provider_iova_or_interrupts_never_produce_a_contract(self):
        for case in ('sid', 'ipa', 'mask', 'provider', 'alias', 'duplicate', 'disabled', 'reg', 'irq', 'iova', 'clock', 'static'):
            source = snoc_nodes(); wlan = source['/soc/qcom,icnss@18800000']; smmu = source['/soc/apps-smmu@15000000']
            w = lambda *v: struct.pack('>' + 'I' * len(v), *v)
            if case == 'sid': wlan['iommus'] = w(0x18, 0xe0, 0)
            if case == 'ipa': wlan['iommus'] = w(0x18, 0x521, 0)
            if case == 'mask': wlan['iommus'] = w(0x18, 0xc0, 0)
            if case == 'provider': smmu['#iommu-cells'] = w(1)
            if case == 'alias': smmu['linux,phandle'] = w(0x19)
            if case == 'duplicate': source['/duplicate'] = {'phandle': w(0x18)}
            if case == 'disabled': smmu['status'] = b'disabled\0'
            if case == 'reg': wlan['reg'] = w(0x18800000, 0x800000)
            if case == 'irq': wlan['interrupts'] = wlan['interrupts'][:-4] + w(1)
            if case == 'iova': wlan['qcom,iommu-dma-addr-pool'] = w(0xb0000000, 0x10000)
            if case == 'clock': smmu['clocks'] = bytes(8)
            if case == 'static': smmu['qcom,static-cb'] = b''
            with self.assertRaises(ValueError, msg=case): P.add_snoc_observer_contract(self.tree(source), source)


if __name__ == '__main__':
    unittest.main()
