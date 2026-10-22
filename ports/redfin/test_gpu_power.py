"""Execute the actual CX-only leaf against a bounded register/RPMh model."""
import ctypes as C
from pathlib import Path
import re
import tempfile
import unittest

from test_smp_gui import compile_shared, patched_source

HERE = Path(__file__).resolve().parent


class GPUPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root / 'redfin_rpmh.h').write_text(patched_source('bsd/dev/redfin_rpmh.h'))
        (root / 'redfin_gpu_power.h').write_text((HERE / 'gpu-power.h').read_text())
        source = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "redfin_gpu_power.h"
static uint32_t regs[4][0x20000];
static unsigned fault,writes,gpu_writes,triggers,acks,bad,table_calls,valid_calls,waits;
static bool held,triggered;
static struct rf_gp_report report;
static bool valid(void *ctx){valid_calls++;if(ctx)bad++;return fault!=1 && !(fault==14&&writes>=3);}
static bool table(void *ctx){if(ctx)bad++;table_calls++;return fault!=2 && !(fault==15&&table_calls==3);}
static uint32_t read_reg(void *ctx,unsigned unit,unsigned at){
 if(ctx || unit>3 || at%4 || at/4>=0x20000){bad++;return UINT32_MAX;}
 if(unit==RF_GP_GPUCC && at==0x1540 && (!held || !gpu_writes))bad++;
 if(fault==6 && unit==RF_GP_RSC && at==RF_GP_TCS(5)+0x38 && table_calls>=2)return 3;
 if(fault==8 && unit==RF_GP_RSC && at==RF_GP_TCS(0)+0x30 && writes)return 0;
 return regs[unit][at/4];
}
static void write_reg(void *ctx,unsigned unit,unsigned at,uint32_t value){
 if(ctx || unit>2 || at%4 || at/4>=0x20000){bad++;return;}
 writes++;
 if(unit==RF_GP_GPUCC){
  gpu_writes++;if(!held || at!=0x106c || value!=0x222000 || acks!=1)bad++;
  regs[unit][at/4]=value;
  regs[unit][0x1540/4]=fault==13?0:0x80000000u;return;
 }
 if(unit!=RF_GP_RSC){bad++;return;}
 unsigned base=RF_GP_TCS(0);
 if(at==0xd08){if(value!=1||!triggered)bad++;acks++;regs[unit][0xd04/4]=0;return;}
 if(at<base || at>base+0x38){bad++;return;}
 regs[unit][at/4]=value;
 if(at==base+0x14 && value==0x1010000){
  triggers++;triggered=true;
  if(regs[unit][(base+0x30)/4]!=0x10108 || regs[unit][(base+0x34)/4]!=0x30000 ||
     regs[unit][(base+0x38)/4]!=7 || regs[unit][(base+0x10)/4]!=1 || regs[unit][(base+0x1c)/4]!=1)bad++;
  if(fault!=9)regs[unit][0xd04/4]=fault==12?3:1;
  regs[unit][(base+0x18)/4]=fault==10?0:1;
  regs[unit][(base+0x3c)/4]=fault==11?0:0x10100;
  if(fault!=9&&fault!=10&&fault!=11&&fault!=12)held=true;
 }
}
static void pause_us(void *ctx,unsigned us){if(ctx||us!=1)bad++;waits++;}
int run(unsigned issue){
 memset(regs,0,sizeof(regs));memset(&report,0,sizeof(report));
 fault=issue;writes=gpu_writes=triggers=acks=bad=table_calls=valid_calls=waits=0;held=triggered=false;
 regs[RF_GP_GCC][0x71004/4]=fault==3?0x80000001:1;
 regs[RF_GP_GPUCC][0x106c/4]=fault==4?0x222003:0x222001;
 regs[RF_GP_RSC][0]=0x20000;regs[RF_GP_RSC][0xc/4]=(16u<<27)|(8u<<12);
 regs[RF_GP_RSC][0xd00/4]=1;
 for(unsigned t=0;t<8;t++)regs[RF_GP_RSC][(RF_GP_TCS(t)+0x18)/4]=1;
 unsigned at=RF_GP_TCS(5);
 regs[RF_GP_RSC][(at+0x1c)/4]=1;
 regs[RF_GP_RSC][(at+0x30)/4]=0x10108;regs[RF_GP_RSC][(at+0x34)/4]=0x30000;
 regs[RF_GP_RSC][(at+0x38)/4]=fault==7?8:2;
 if(fault==5)regs[RF_GP_GIC][0x104/4]=1u<<5;
 const struct rf_gp_ops ops={NULL,valid,read_reg,write_reg,pause_us,table};
 int rc=rf_gp_run(&ops,&report);
 if(bad)return -100-(int)bad;
 if(!fault && (rc||!report.parent_held||!report.cx_on||gpu_writes!=1||triggers!=1||acks!=1))return -2;
 if(fault>=1&&fault<=7 && writes)return -3;
 if(fault>=8&&fault<=12 && gpu_writes)return -4;
 if(fault==14 && gpu_writes)return -5;
 if(fault==15 && gpu_writes)return -6;
 return rc;
}
unsigned stat(unsigned n){unsigned v[]={writes,gpu_writes,triggers,acks,table_calls,waits,report.parent_held,report.cx_on};return n<8?v[n]:0;}
int table_case(unsigned issue){
 struct rf_cmddb_resource r={0};uint16_t v[]={0,16,64,128,192,256,384,416,0,0,0,0,0,0,0,0};
 r.address=0x30000;r.type=3;r.aux_version=0x1000;r.aux_bytes=32;r.level_count=16;
 memcpy(r.levels,v,sizeof(v));
 if(issue>=1&&issue<=16)r.levels[issue-1]++;
 if(issue==17)r.address++;if(issue==18)r.type++;if(issue==19)r.aux_version++;if(issue==20)r.aux_bytes--;if(issue==21)r.level_count--;
 return rf_gp_table(&r);
}
'''
        cls.lib = compile_shared(root, source, 'gpu-power')
        cls.lib.run.argtypes = cls.lib.stat.argtypes = cls.lib.table_case.argtypes = [C.c_uint]

    def test_highest_legal_selector_is_held_before_single_cx_write(self):
        self.assertEqual(self.lib.run(0), 0)
        self.assertEqual([self.lib.stat(i) for i in (1, 2, 3, 6, 7)], [1, 1, 1, 1, 1])

    def test_every_exact_arc_table_field_and_trailing_zero_is_required(self):
        self.assertEqual(self.lib.table_case(0), 1)
        for issue in range(1, 22):
            self.assertEqual(self.lib.table_case(issue), 0, issue)
        self.assertEqual(patched_source('bsd/dev/redfin_gpu_power.h'), (HERE / 'gpu-power.h').read_text())
        self.assertEqual(patched_source('bsd/dev/redfin_gpu_power.c'), (HERE / 'gpu-power.c').read_text())

    def test_wrong_policy_table_clock_handoff_irq_and_changed_templates_never_write(self):
        for issue in range(1, 8):
            self.assertGreater(self.lib.run(issue), 0, issue)
            self.assertEqual(self.lib.stat(0), 0)

    def test_failed_writes_incomplete_idle_irq_status_and_lost_contract_never_enable_cx(self):
        for issue in (8, 9, 10, 11, 12, 14, 15):
            self.assertGreater(self.lib.run(issue), 0, issue)
            self.assertEqual(self.lib.stat(1), 0)

    def test_domain_timeout_is_bounded_and_keeps_parent_vote_held(self):
        self.assertGreater(self.lib.run(13), 0)
        self.assertEqual(self.lib.stat(1), 1)
        self.assertEqual(self.lib.stat(6), 1)
        self.assertEqual(self.lib.stat(7), 0)
        self.assertEqual(self.lib.stat(5), 1001)


if __name__ == '__main__':
    unittest.main()
