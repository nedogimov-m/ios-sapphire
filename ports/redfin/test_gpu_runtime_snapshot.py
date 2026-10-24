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
struct gm_context {unsigned smmu_mode;uintptr_t smmu,cb;};
static struct gm_context context;
static struct {struct gm_context *context;bool poisoned;
 struct {struct {unsigned active,poisoned;struct rf_gs_snapshot expected;}state;}mapping;}gx;
static uint32_t global[0x8000/4],banks[0x2000/4];
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
 return *(uint32_t *)at;
}
'''
        suffix = r'''
int run(unsigned problem){
 memset(global,0,sizeof(global));memset(banks,0,sizeof(banks));memset(&gx,0,sizeof(gx));
 issue=problem;reads=live_checks=payload_checks=power_lost=payload_lost=0;ready=caller=1;
 context=(struct gm_context){6,(uintptr_t)global,(uintptr_t)banks};gx.context=&context;
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


if __name__ == '__main__':
    unittest.main()
