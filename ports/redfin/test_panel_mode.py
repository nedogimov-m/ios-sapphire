"""Execute the production FIFO/TE mode transaction with hardware fault injection."""
import copy
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest
from ports.redfin import panel_mode,mkadt
from ports.redfin.memory import _tree

HERE=Path(__file__).resolve().parent
HARNESS=r'''
#include <assert.h>
#include <string.h>
#include "panel-mode.h"
struct device {uint32_t reg[4][0x4000/4];uint64_t ns;unsigned hz,issue,writes,triggers,resets,late_writes,seen_trigger;};
static struct device dev;static struct redfin_panel_result result;
static uint32_t rd(void *p,unsigned b,uint32_t off){
 struct device *d=p;assert(b<4 && !(off&3) && off<0x4000);
 if(b==RP_GPIO && off==4){if(d->issue==2)return 0;return (d->ns%(1000000000/d->hz))<150000;}
 if(b==RP_INTF && off==0xac)return (uint32_t)(d->ns/(1000000000/60)); /* independent DPU counter */
 if(d->issue==1 && b==RP_CC)return 0x80000001;
 return d->reg[b][off/4];
}
static void wr(void *p,unsigned b,uint32_t off,uint32_t value){
 struct device *d=p;assert(b==RP_DSI || (b==RP_INTF && off==0x288));assert(!(off&3));d->writes++;
 if(d->issue==4 && d->seen_trigger)d->late_writes++;
 if(b==RP_DSI){assert(off==4 || off==0x110 || off==0x15c || off==0x17c || off==0x3c || off==0x4c || off==0x90 || off==0x1ec);
  if(off==0x110){if(d->issue!=5)d->reg[b][off/4]&=~(value&1u);return;}
  if(off==0x17c){if(value==0x80153853)d->reg[b][0x54/4]=90;
   else if(value==0x80152853)d->reg[b][0x54/4]=60;else assert(!value);return;}
  if(off==0x90){assert(value==1);d->triggers++;d->seen_trigger=1;
   if(d->issue!=4){d->reg[b][0x110/4]|=1;
    unsigned rate=d->reg[b][0x54/4];assert(rate==60 || rate==90);
    if(d->issue!=3 || rate==60)d->hz=rate;}
   return;}
  if(off==0x1ec && value==1)d->resets++;
 }
 d->reg[b][off/4]=value;
}
static uint64_t now(void *p){return ((struct device *)p)->ns;}
static void delay(void *p,unsigned us){((struct device *)p)->ns+=(uint64_t)us*1000;}
int run(unsigned issue){
 memset(&dev,0,sizeof(dev));dev.issue=issue;dev.hz=issue==9?90:60;dev.ns=1000000000;
 dev.reg[RP_CC][0x2080/4]=dev.reg[RP_CC][0x2028/4]=dev.reg[RP_CC][0x2038/4]=dev.reg[RP_CC][0x200c/4]=1;
 dev.reg[RP_DSI][0]=0x20040000;dev.reg[RP_DSI][4/4]=5;dev.reg[RP_DSI][0x84/4]=4;
 dev.reg[RP_DSI][0x3c/4]=0x14000000;dev.reg[RP_DSI][0x4c/4]=128;
 dev.reg[RP_INTF][0x284/4]=1;dev.reg[RP_INTF][0x288/4]=0x100038;
 dev.reg[RP_INTF][0x2b4/4]=0x80000001;dev.reg[RP_GPIO][0]=4;
 if(issue==5)dev.reg[RP_DSI][0x110/4]=1;
 if(issue==6)dev.reg[RP_DSI][0]=0x20030000;
 if(issue==7)dev.reg[RP_INTF][0x2b4/4]=0;
 if(issue==8)dev.reg[RP_DSI][4/4]=3;
 if(issue==10)dev.reg[RP_GPIO][0]=0x204;
 if(issue==11)dev.reg[RP_DSI][8/4]=6;
 const struct redfin_panel_io io={&dev,rd,wr,delay,now};return redfin_panel_switch_90(&io,&result);
}
unsigned metric(unsigned i){unsigned m[]={result.actual_hz,result.stage,dev.writes,dev.triggers,dev.resets,
 result.command_done,result.rollback_done,result.uncertain,dev.late_writes,dev.hz,
 dev.reg[RP_DSI][4/4],dev.reg[RP_DSI][0x3c/4],dev.reg[RP_DSI][0x4c/4],dev.reg[RP_DSI][0x15c/4],
 dev.reg[RP_INTF][0x288/4],result.after.mean_us,result.before.mean_us,result.after.frames};return i<sizeof(m)/sizeof(m[0])?m[i]:~0u;}
'''


class PanelModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);root=Path(cls.temp.name)
        (root/'panel.c').write_text(HARNESS)
        r=subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-I',str(HERE),
            str(root/'panel.c'),'-o',str(root/'panel.so')],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr)
        cls.lib=C.CDLL(str(root/'panel.so'));cls.lib.metric.restype=C.c_uint

    def metrics(self,*indices):return tuple(self.lib.metric(i) for i in indices)

    def test_fresh_fifo_completion_and_actual_panel_edges_are_required(self):
        self.assertEqual(self.lib.run(0),1)
        self.assertEqual(self.metrics(0,1,3,4,5,6,7,9),(90,8,1,1,1,0,0,90))
        self.assertEqual(self.metrics(10,11,12,13),(5,0x14000000,128,0))
        self.assertEqual(self.lib.metric(14),0x100025)
        self.assertLess(abs(self.lib.metric(15)-11111),10)
        self.assertLess(abs(self.lib.metric(16)-16666),10)
        self.assertLess(self.lib.metric(17),25) # TE proves90 despite the separate60Hz DPU fixture.

    def test_existing90_needs_no_command_and_off_clocks_cause_no_device_writes(self):
        self.assertEqual(self.lib.run(9),1);self.assertEqual(self.metrics(0,2,3),(90,0,0))
        self.assertEqual(self.lib.run(1),0);self.assertEqual(self.metrics(0,1,2),(0,1,0))
        for issue in (2,6,7,8,10,11):
            self.assertEqual(self.lib.run(issue),0)
            self.assertEqual(self.metrics(2,3),(0,0),issue)

    def test_command_ack_without90_edges_rolls_back_and_verifies60(self):
        self.assertEqual(self.lib.run(3),0)
        self.assertEqual(self.metrics(0,1,3,4,5,6,7,9),(60,7,2,2,1,1,0,60))
        self.assertEqual(self.metrics(10,11,12,13,14),(5,0x14000000,128,0,0x100038))

    def test_stale_done_and_uncertain_completion_never_claim90_or_reset_live_fifo(self):
        self.assertEqual(self.lib.run(5),0);self.assertEqual(self.metrics(0,3,4,7),(60,0,0,0))
        self.assertEqual(self.lib.run(4),0)
        self.assertEqual(self.metrics(0,3,4,7,8),(0,1,0,1,0))

    def test_live_fdt_mode_contract_requires_exact_primary_panel_gpio_and_both_commands(self):
        path=HERE.parents[1]/'research/redfin-root/device.dtb'
        if not path.is_file():self.skipTest('actual captured Redfin FDT required')
        nodes,_=_tree(path.read_bytes())
        def tree():
            t=mkadt.build(0x180000000,0x80000000,smp=True,smp_cpus=8)
            return mkadt.add_linear_display(t,0xa0000000,0x2300000,0xa0000000)
        native=tree();report=panel_mode.add_contract(native,nodes)
        self.assertEqual(report['requested_hz'],90);self.assertTrue(report['physical_refresh_requires_TE_verification'])
        with self.assertRaises(ValueError):panel_mode.add_contract(native,nodes)
        panel=report['panel']+'/qcom,mdss-dsi-display-timings/timing@1'
        for p,key,bad in [(panel,'qcom,mdss-dsi-timing-switch-command',bytes.fromhex('150100000000025328')),
            (panel,'qcom,mdss-dsi-panel-clockrate',(555000000).to_bytes(4,'big')),
            ('/soc/qcom,dsi-display-primary','qcom,platform-te-gpio',bytes(12))]:
            modified=copy.deepcopy(nodes);modified[p][key]=bad
            with self.assertRaises(ValueError):panel_mode.add_contract(tree(),modified)


if __name__=='__main__':unittest.main()
