"""Run the actual runtime callbacks with full snapshots and boundary faults."""
import ctypes
import errno
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class RuntimeSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        raw = (HERE / 'gpu-runtime.inc').read_text()
        body = raw[raw.index('static bool gr_snapshot_valid('):raw.index('int redfin_gpu_audit(')]
        prefix = r'''
#include <string.h>
#include "redfin_gpu_context.h"
#include "redfin_gmu_tcm.h"
struct gm_context {unsigned smmu_mode;uintptr_t smmu,cb,base[3];};
static struct gm_context context;
static struct {struct gm_context *context;bool poisoned;
 struct {struct {unsigned active,poisoned;struct rf_gs_snapshot expected;}state;}mapping;}gx;
static uint32_t global[0x8000/4],banks[0x2000/4];
static uint32_t gcc[0x80000/4],gpucc[0x9000/4];
static unsigned issue,reads,live_checks,payload_checks,power_lost,payload_lost,ready,caller;
static const uint32_t gm_chip=RF_GS_CHIP;
static bool redfin_gpu_ready(void){return ready;}
static bool redfin_gui_cpu0(void){return false;}
static bool redfin_gpu_runtime_caller(void){return caller;}
static int gr_live(void){live_checks++;return power_lost?EIO:0;}
static bool gm_payloads_valid(void *c){payload_checks++;return c==&context && !payload_lost;}
static uint32_t gm_scalar_read(uintptr_t at){
 reads++;
 if(reads==17){
  if(issue==1)power_lost=1;if(issue==2)payload_lost=1;if(issue==3)ready=0;
  if(issue==4)caller=0;if(issue==5)gx.mapping.state.active=0;if(issue==6)gx.poisoned=true;
 }
 if(issue==7 && reads==58)global[0x20/4]^=1;
 if(reads==8){if(issue==21)power_lost=1;if(issue==22)caller=0;}
 return *(uint32_t *)at;
}
'''
        suffix = r'''
int run(unsigned problem){
 memset(global,0,sizeof(global));memset(banks,0,sizeof(banks));memset(&gx,0,sizeof(gx));
 issue=problem;reads=live_checks=payload_checks=power_lost=payload_lost=0;ready=caller=1;
 context=(struct gm_context){.smmu_mode=6,.smmu=(uintptr_t)global,.cb=(uintptr_t)banks};gx.context=&context;
 gx.mapping.state.active=1;
 gx.mapping.state.expected=(struct rf_gs_snapshot){.page_bytes=0x1000,.global_bytes=0x8000,.streams=16,.contexts=8};
 global[0x20/4]=(1u<<30)|(1u<<27)|(11u<<9)|16;
 global[0x24/4]=(2u<<28)|8;global[0x28/4]=(1u<<12)|(2u<<8)|(1u<<4)|1;
 for(unsigned i=0;i<16;i++)global[(0xc00+4*i)/4]=2u<<16;
 if(issue==8)power_lost=1;if(issue==9)payload_lost=1;if(issue==10)caller=0;
 struct rf_gs_snapshot g;struct rf_gc_snapshot b;
 return gr_snapshot(&context,&g,&b);
}
unsigned metric(unsigned n){unsigned values[]={reads,live_checks,payload_checks};return n<3?values[n]:999;}
int direct(unsigned block,uint32_t at){uint32_t value;return gr_snapshot_read(&context,block,at,&value);}
int source_check(unsigned problem){
 if(run(0))return EIO;reads=live_checks=payload_checks=0;issue=problem;
 memset(gcc,0,sizeof(gcc));memset(gpucc,0,sizeof(gpucc));
 context.base[0]=(uintptr_t)gcc;context.base[1]=(uintptr_t)gpucc;
 gcc[0x71004/4]=1;gcc[0]=0xc0100000;gcc[4/4]=problem==20?32:31;gcc[0xc/4]=0x103;gcc[0x40/4]=0x4000;
 gcc[0x52010/4]=1;gcc[0x52000/4]=0x10000;gcc[0x71028/4]=3;
 gpucc[0x1540/4]=0x80000000;gpucc[0x1124/4]=0x602;gpucc[0x1098/4]=gpucc[0x109c/4]=1;
 const struct rf_gt_ops ops={.context=&context,.valid=gr_snapshot_valid,.read=gr_source_read};
 struct rf_gt_report clock={0};int error=gr_live();
 if(!error)error=rf_gt_source_live_power(&ops,&clock,true,true);
 if(!error)error=gr_live();return error;
}
int source_direct(unsigned unit,uint32_t at){uint32_t value;return gr_source_read(&context,unit,at,&value);}
'''
        source, library = root / 'snapshot.c', root / 'snapshot.so'
        source.write_text(prefix + body + suffix)
        subprocess.run(['cc', '-std=c11', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-I', str(HERE / 'include'), source,
                        '-o', library], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(library))

    def test_complete_twice_read_global_and_banks_use_two_full_boundary_checks(self):
        self.assertEqual(self.lib.run(0), 0)
        self.assertEqual([self.lib.metric(i) for i in range(3)], [162, 2, 2])

    def test_lost_power_or_firmware_is_rejected_at_boundary(self):
        for issue, expected in ((1, errno.EIO), (2, errno.ECANCELED)):
            self.assertEqual(self.lib.run(issue), expected)
            self.assertEqual(self.lib.metric(0), 162)
        for issue, expected in ((8, errno.EIO), (9, errno.ECANCELED)):
            self.assertEqual(self.lib.run(issue), expected)
            self.assertEqual(self.lib.metric(0), 0)

    def test_lost_caller_mapping_or_runtime_stops_nested_reads(self):
        for issue in (3, 4, 5, 6):
            self.assertEqual(self.lib.run(issue), errno.ECANCELED)
            self.assertEqual(self.lib.metric(0), 17)
        self.assertEqual(self.lib.run(10), errno.ECANCELED)
        self.assertEqual(self.lib.metric(0), 0)

    def test_changed_foreign_state_and_out_of_scope_addresses_are_rejected(self):
        self.assertEqual(self.lib.run(7), errno.EAGAIN)
        self.assertEqual(self.lib.run(0), 0)
        for block, offset in ((0, 0x4000), (0, 0x801), (1, 0x1000), (1, 0x800), (2, 0)):
            before = self.lib.metric(0)
            self.assertEqual(self.lib.direct(block, offset), errno.EPERM)
            self.assertEqual(self.lib.metric(0), before)

    def test_complete_source_check_reads_all_sixteen_registers_without_recursive_parent_mmio(self):
        self.assertEqual(self.lib.source_check(0), 0)
        self.assertEqual([self.lib.metric(i) for i in range(3)], [16, 2, 0])
        self.assertEqual(self.lib.source_check(20), errno.EAGAIN)
        self.assertEqual(self.lib.metric(0), 16)
        self.assertEqual(self.lib.source_check(21), errno.EIO)
        self.assertEqual(self.lib.metric(0), 16)
        self.assertEqual(self.lib.source_check(22), errno.ECANCELED)
        self.assertEqual(self.lib.metric(0), 8)
        self.assertEqual(self.lib.source_check(0), 0)
        for unit, offset in ((2, 0x14000), (0, 0x80000), (1, 0x9000), (0, 3)):
            self.assertEqual(self.lib.source_direct(unit, offset), errno.EPERM)
            self.assertEqual(self.lib.metric(0), 16)


if __name__ == '__main__':
    unittest.main()
