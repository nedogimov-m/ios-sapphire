"""Execute the physical-input policy, FIFO owner and coalesced native worker.

Only hardware/time/IOKit primitives are substituted; the production state
machines and transaction code run, including cancellation and failed wake.
"""
import ctypes as C
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from ports.redfin import controls, mkadt
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


def compile_library(root,source,name,cpp=False):
    path=root/(name+('.cpp' if cpp else '.c'));path.write_text(source)
    result=subprocess.run(['c++' if cpp else 'cc','-std=c++17' if cpp else '-std=c11',
        '-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-Wno-misleading-indentation','-I'+str(root),'-I'+str(HERE),str(path),'-o',str(root/(name+'.so'))],
        capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    return C.CDLL(str(root/(name+'.so')))


class ControlsPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.lib=compile_library(Path(cls.tmp.name),r'''
#include "controls-policy.h"
static struct rf_keys_state state;static unsigned count,event[128][3];
static void emit(void *ctx,unsigned key,bool down,bool physical){(void)ctx;
 if(count<128){event[count][0]=key;event[count][1]=down;event[count][2]=physical;}++count;}
void reset(void){memset(&state,0,sizeof(state));count=0;}
void sample(uint64_t ns,uint64_t epoch,unsigned down,unsigned valid){rf_keys_sample(&state,ns,epoch,down,valid,emit,0);}
unsigned metric(unsigned i){unsigned a[]={count,state.armed,state.down,state.sampled};return i<4?a[i]:~0u;}
unsigned edge(unsigned at,unsigned field){return at<count&&at<128&&field<3?event[at][field]:~0u;}
int level(uint64_t nits,unsigned *dbv){return rf_panel_nits_to_dbv(nits,dbv);}
''','policy')
        cls.lib.sample.argtypes=[C.c_uint64,C.c_uint64,C.c_uint,C.c_uint]
        cls.lib.level.argtypes=[C.c_uint64,C.POINTER(C.c_uint)]

    def sample(self,ms,down=0,epoch=1,valid=7):self.lib.sample(int(ms*1e6),epoch,down,valid)
    def edges(self):return [tuple(self.lib.edge(i,j) for j in range(3)) for i in range(self.lib.metric(0))]
    def arm(self):self.lib.reset();self.sample(0);self.sample(16);self.assertEqual(self.lib.metric(1),7)

    def test_boot_hold_and_bouncing_inputs_do_not_invent_a_press(self):
        self.lib.reset();self.sample(0,1);self.sample(100,1);self.assertEqual(self.edges(),[])
        self.sample(110,0);self.sample(126,0);self.assertEqual(self.lib.metric(1),7)
        self.sample(130,1);self.sample(139,0);self.sample(145,1);self.sample(159,1)
        self.assertEqual(self.edges(),[]);self.sample(160,1);self.sample(300,1)
        self.sample(310,0);self.sample(326,0)
        self.assertEqual(self.edges(),[(0,1,1),(0,0,1)])

    def test_all_native_combinations_have_exact_edges_and_no_synthetic_repeats(self):
        self.arm();self.sample(20,7);self.sample(36,7);self.sample(5000,7)
        self.assertEqual(self.edges(),[(0,1,1),(1,1,1),(2,1,1)])
        self.sample(5010);self.sample(5026)
        self.assertEqual(self.edges()[3:],[(0,0,1),(1,0,1),(2,0,1)])

    def test_consumer_replacement_and_read_failure_cancel_only_delivered_keys(self):
        self.arm();self.sample(20,3);self.sample(36,3)
        self.sample(50,3,valid=5)
        self.assertEqual(self.edges()[-1],(1,0,0));self.assertEqual(self.lib.metric(2),1)
        self.sample(60,3,epoch=2);self.sample(1000,3,epoch=2)
        self.assertEqual(self.edges()[-1],(0,0,0));self.assertEqual(self.lib.metric(2),0)
        self.sample(1010,0,epoch=2);self.sample(1026,0,epoch=2)
        self.sample(1030,4,epoch=2);self.sample(1046,4,epoch=2)
        self.assertEqual(self.edges()[-1],(2,1,1))
        self.sample(1050,epoch=0);self.assertEqual(self.edges()[-1],(2,0,0))

    def test_native_nits_mapping_is_monotonic_and_refuses_unimplemented_HBM(self):
        out=C.c_uint();previous=0
        for nits in range(501):
            self.assertEqual(self.lib.level(nits<<16,C.byref(out)),1)
            self.assertGreaterEqual(out.value,previous);self.assertLessEqual(out.value,1023);previous=out.value
        self.assertEqual(out.value,1023)
        self.assertEqual(self.lib.level(0,C.byref(out)),1);self.assertEqual(out.value,4)
        self.assertEqual(self.lib.level((500<<16)+1,C.byref(out)),0)


PANEL_MODEL=r'''
#include <assert.h>
#include <string.h>
#include "RedfinPanelControls.h"
struct device {uint32_t reg[4][0x4000/4],packet[2];unsigned words,writes,triggers,resets,late,issue;uint64_t ns;};
static struct device dev;static struct rf_panel_control_result result;
static uint32_t rd(void *p,unsigned bank,uint32_t off){struct device *d=p;
 assert(bank<4&&off<0x4000&&!(off&3));
 if(d->issue==6&&d->triggers&&bank==RP_DSI&&off==4)return 7;
 return d->reg[bank][off/4];}
static void wr(void *p,unsigned bank,uint32_t off,uint32_t value){struct device *d=p;
 assert(bank==RP_DSI);assert(off==4||off==0x110||off==0x15c||off==0x17c||off==0x3c||off==0x4c||off==0x90||off==0x1ec);
 ++d->writes;if(d->triggers&&(d->issue==4||d->issue==5))++d->late;
 if(off==0x110){if(d->issue!=3)d->reg[bank][off/4]&=~(value&1);return;}
 if(off==0x17c){assert(d->words<2);d->packet[d->words++]=value;return;}
 if(off==0x90){++d->triggers;assert(value==1&&d->words==2);
  if(d->issue==5)d->reg[bank][0x110/4]|=1u<<24;
  else if(d->issue!=4)d->reg[bank][0x110/4]|=1;
  return;}
 if(off==0x1ec&&value==1)++d->resets;
 if(d->issue==7&&off==0x4c&&!d->triggers)return;
 d->reg[bank][off/4]=value;}
static void delay(void *p,unsigned us){((struct device *)p)->ns+=(uint64_t)us*1000;}
static uint64_t now(void *p){return ((struct device *)p)->ns;}
int run(unsigned issue,int brightness,unsigned value){memset(&dev,0,sizeof(dev));dev.issue=issue;
 unsigned clocks[]={0x2080,0x2028,0x2038,0x200c};for(unsigned i=0;i<4;++i)dev.reg[RP_CC][clocks[i]/4]=1;
 dev.reg[RP_DSI][0]=0x20040000;dev.reg[RP_DSI][4/4]=5;dev.reg[RP_DSI][0x84/4]=4;
 dev.reg[RP_DSI][0x3c/4]=0x14000000;dev.reg[RP_DSI][0x4c/4]=128;
 if(issue==1)dev.reg[RP_CC][0x2080/4]=0x80000001;
 if(issue==2)dev.reg[RP_DSI][8/4]=6;
 if(issue==3)dev.reg[RP_DSI][0x110/4]=1;
 const struct redfin_panel_io io={&dev,rd,wr,delay,now};return rf_panel_control(&io,brightness!=0,value,&result);}
unsigned metric(unsigned i){unsigned a[]={dev.writes,dev.triggers,dev.resets,dev.late,result.submitted,result.completed,result.restored,result.uncertain,
 dev.reg[RP_DSI][4/4],dev.reg[RP_DSI][0x3c/4],dev.reg[RP_DSI][0x4c/4],dev.reg[RP_DSI][0x15c/4],dev.packet[0],dev.packet[1]};return i<14?a[i]:~0u;}
'''


class PanelControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);root=Path(cls.tmp.name)
        for alias,owned in [('RedfinPanelControls.h','panel-controls.h'),('RedfinPanelMode.h','panel-mode.h'),('RedfinControlsPolicy.h','controls-policy.h')]:
            (root/alias).write_bytes((HERE/owned).read_bytes())
        cls.lib=compile_library(root,PANEL_MODEL,'panel')
        cls.lib.metric.restype=C.c_uint

    def metrics(self,*indices):return tuple(self.lib.metric(i) for i in indices)

    def test_exact_brightness_packet_payload_and_all_registers_are_restored(self):
        for level in (4,255,256,1023):
            self.assertEqual(self.lib.run(0,1,level),1)
            self.assertEqual(self.metrics(4,5,6,7),(1,1,1,0))
            self.assertEqual(self.metrics(8,9,10,11),(5,0x14000000,128,0))
            self.assertEqual(self.metrics(12,13),(0xc0390003,0xff000051|((level>>8)<<8)|((level&255)<<16)))
        self.assertEqual(self.lib.run(0,1,1024),0);self.assertEqual(self.lib.metric(0),0)

    def test_visibility_commands_use_the_short_DCS_FIFO_and_no_DMA_memory(self):
        for on in (0,1):
            self.assertEqual(self.lib.run(0,0,on),1)
            # Independent native DSI header byte order: data0,data1,type,last.
            packet=self.lib.metric(12).to_bytes(4,'little')
            self.assertEqual(packet,bytes((0x29 if on else 0x28,0,0x05,0x80)))
            self.assertEqual(self.lib.metric(13),0)
        self.assertEqual(self.lib.run(0,0,2),0);self.assertEqual(self.lib.metric(0),0)

    def test_off_clocks_busy_engine_and_stale_done_never_submit(self):
        for issue in (1,2,3,7):
            self.assertEqual(self.lib.run(issue,1,100),0)
            self.assertEqual(self.metrics(1,4,7),(0,0,0))
        self.assertEqual(self.metrics(8,9,10,11),(5,0x14000000,128,0))

    def test_uncertain_completion_never_resets_or_reuses_the_live_FIFO(self):
        for issue in (4,5):
            self.assertEqual(self.lib.run(issue,1,100),0)
            self.assertEqual(self.metrics(1,2,3,4,5,6,7),(1,0,0,1,0,0,1))
        self.assertEqual(self.lib.run(6,1,100),0)
        self.assertEqual(self.metrics(4,5,6,7),(1,1,0,1))


class KeyObserverTests(unittest.TestCase):
    def test_real_read_framing_refuses_wrong_peripheral_and_lost_mapping(self):
        native=(HERE/'native-power.inc').read_text();keys=(HERE/'keys-native.inc').read_text()
        actual='\n'.join([function(native,'static bool power_match('),
            function(native,'static int power_poll('),function(keys,'static int keys_byte(')])
        source=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
typedef uintptr_t vm_offset_t;
struct power_target {unsigned ppid,apid,owner;uint32_t mapping;vm_offset_t writer;};
static power_target keys_targets[2]={{8,3,0,0x80000800,0},{0x4c4,9,0,0x8004c400,0}};
static uintptr_t power_core=1,power_observer=2,power_config=3;
static uint32_t power_version=0x50000000;static bool power_spmi_ok=true;
static unsigned commands,issue,offset_seen,value_seen;
static uint32_t power_rd(uintptr_t bank,unsigned off){
 if(bank==power_core){if(!off)return power_version;
  if(off==0x90c)return keys_targets[0].mapping^((issue==1||issue==2&&commands)?0x100:0);
  if(off==0x924)return keys_targets[1].mapping;}
 if(bank==power_config)return 0;
 if(bank==power_observer){if(off%0x80==8)return issue==3?0:1;if(off%0x80==0x18)return 0x5a;}
 return 0;}
static void power_wr(uintptr_t bank,unsigned off,uint32_t value){assert(bank==power_observer);
 ++commands;offset_seen=off;value_seen=value;}
static void IODelay(unsigned us){(void)us;}
'''+actual+r'''
int main(){uint8_t byte=0;
 assert(!keys_byte(0,0x0810,&byte)&&byte==0x5a);assert(commands==1&&offset_seen==3*0x80&&value_seen==((1u<<27)|0x100));
 assert(!keys_byte(1,0xc410,&byte)&&commands==2&&offset_seen==9*0x80);
 assert(keys_byte(0,0x1310,&byte)==ENXIO&&commands==2);
 assert(keys_byte(2,0x0810,&byte)==EINVAL&&commands==2);
 issue=1;commands=0;assert(keys_byte(0,0x0810,&byte)==ENXIO&&commands==0);
 issue=2;assert(keys_byte(0,0x0810,&byte)==EAGAIN&&commands==1&&!power_spmi_ok);
 issue=0;assert(keys_byte(0,0x0810,&byte)==ENXIO&&commands==1);
 issue=3;commands=0;power_spmi_ok=true;
 assert(keys_byte(0,0x0810,&byte)==ETIMEDOUT&&commands==1&&!power_spmi_ok);
 assert(keys_byte(0,0x0810,&byte)==ENXIO&&commands==1);
 return 0;}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'keys.cpp';path.write_text(source)
            compiled=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-Wno-logical-op-parentheses',str(path),'-o',str(root/'keys')],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(root/'keys')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


class DisplayControlWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);root=Path(cls.tmp.name)
        actual=(HERE/'display-controls.inc').read_text()
        start=actual.index('struct redfin_display_controls {')
        state=actual[start:actual.index('};',start)+2]
        worker='\n'.join(function(actual,name) for name in (
            'static void redfin_control_queue(', 'IOReturn AppleCLCD::redfinSetBrightness(',
            'IOReturn AppleCLCD::redfinSetDisplayPower(', 'void AppleCLCD::redfinControlsWork('))
        source=r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "controls-policy.h"
#ifndef __unused
#define __unused __attribute__((unused))
#endif
using IOReturn=int;using thread_call_t=void *;using thread_call_param_t=void *;
enum {kIOReturnSuccess,kIOReturnUnsupported,kIOReturnBadArgument,kIOReturnNotReady};
struct IOLock {bool locked;};static void IOLockLock(IOLock *l){assert(!l->locked);l->locked=true;}
static void IOLockUnlock(IOLock *l){assert(l->locked);l->locked=false;}
struct redfin_panel_maps {unsigned unused;};class AppleARMBacklight;
struct redfin_display_controls;struct redfin_panel_io {void *context;void *read,*write,*delay,*time;};
static void *redfin_panel_read,*redfin_panel_write,*redfin_panel_delay,*redfin_panel_time;
struct rf_panel_control_result {bool submitted,completed,restored,uncertain;uint32_t status;};
static unsigned queued,packets,kind[64],values[64],issue;static bool injected;
static void thread_call_enter(thread_call_t p){(void)p;queued=1;}
static void IOLog(const char *format,...){(void)format;}
class AppleCLCD {public:redfin_display_controls *fRedfinControls;
 void setProperty(const char *key,uint64_t value,unsigned width=0){(void)key;(void)value;(void)width;}
 IOReturn redfinSetBrightness(uint64_t);IOReturn redfinSetDisplayPower(bool);
 static void redfinControlsWork(thread_call_param_t,thread_call_param_t);};
static AppleCLCD fb;
static bool redfin_backlight_parameters(AppleARMBacklight *backlight,uint32_t level){(void)backlight;(void)level;return true;}
static bool rf_panel_control(const redfin_panel_io *io,bool brightness,uint32_t value,rf_panel_control_result *r){
 (void)io;assert(packets<64);kind[packets]=brightness;values[packets++]=value;
 if(issue==1){r->submitted=true;r->uncertain=true;return false;}
 if(issue==2)return false;
 if(issue==3&&!injected){injected=true;assert(fb.redfinSetBrightness(350ULL<<16)==kIOReturnSuccess);}
 r->submitted=r->completed=r->restored=true;return true;}
'''+state+worker+r'''
static redfin_display_controls state;static IOLock locks[2];
extern "C" {
void reset(unsigned mode){memset(&state,0,sizeof(state));memset(locks,0,sizeof(locks));queued=packets=0;issue=mode;injected=false;
 state.state_lock=&locks[0];state.io_lock=&locks[1];state.desired_on=state.applied_on=true;fb.fRedfinControls=&state;}
int brightness(unsigned nits){return fb.redfinSetBrightness((uint64_t)nits<<16);}
int power(int on){return fb.redfinSetDisplayPower(on!=0);}
void drain(void){for(unsigned i=0;queued&&i<10;++i){queued=0;AppleCLCD::redfinControlsWork(&fb,nullptr);}assert(!queued);}
unsigned metric(unsigned i){unsigned a[]={packets,state.desired_level,state.applied_level,(unsigned)state.requested_seq,(unsigned)state.processed_seq,
 state.applied_on,state.uncertain,state.errors,(unsigned)(state.applied_nits>>16)};return i<9?a[i]:~0u;}
unsigned packet(unsigned at,unsigned field){return at<packets?(field?values[at]:kind[at]):~0u;}
}
'''
        cls.lib=compile_library(root,source,'worker',cpp=True)

    def test_slider_coalesces_and_off_defers_brightness_until_wake(self):
        lib=self.lib;lib.reset(0)
        for nits in (50,100,200):self.assertEqual(lib.brightness(nits),0)
        lib.drain();self.assertEqual(lib.metric(0),1);self.assertEqual(lib.metric(8),200)
        self.assertEqual(lib.power(0),0);lib.drain();self.assertEqual(lib.metric(5),0)
        self.assertEqual(lib.brightness(400),0);lib.drain();self.assertEqual(lib.metric(0),2)
        self.assertEqual(lib.power(1),0);lib.drain();self.assertEqual(lib.metric(5),1)
        self.assertEqual(lib.metric(8),400);self.assertEqual(lib.metric(3),lib.metric(4))
        self.assertEqual([(lib.packet(i,0),lib.packet(i,1)) for i in (1,2)],[(0,0),(0,1)])
        self.assertEqual(lib.metric(0),4)

    def test_request_during_a_running_transaction_has_one_coalesced_successor(self):
        lib=self.lib;lib.reset(3);lib.brightness(100);lib.drain()
        self.assertEqual(lib.metric(0),2);self.assertEqual(lib.metric(8),350)
        self.assertEqual(lib.metric(3),lib.metric(4))

    def test_uncertainty_blocks_new_requests_and_known_failure_never_advances_applied(self):
        lib=self.lib;lib.reset(1);lib.brightness(100);lib.drain()
        self.assertEqual(lib.metric(6),1);self.assertEqual(lib.metric(4),0)
        self.assertEqual(lib.brightness(200),3);self.assertEqual(lib.power(0),3)
        lib.drain();self.assertEqual(lib.metric(0),1)
        lib.reset(2);lib.brightness(100);lib.drain()
        self.assertEqual(lib.metric(6),0);self.assertEqual(lib.metric(4),0);self.assertEqual(lib.metric(7),1)


class ControlsFDTTests(unittest.TestCase):
    def test_actual_contract_and_altered_input_panel_or_provider_are_distinguished(self):
        path=HERE.parents[1]/'research/redfin-root/device.dtb'
        if not path.is_file():self.skipTest('captured Redfin FDT needed')
        blob=path.read_bytes();report=controls.validate(blob)
        self.assertEqual(tuple(report['key_contract']),controls.KEY_VALUES)
        root=mkadt.build(0x180000000,0x80000000,smp=True,smp_cpus=8)
        mkadt.add_linear_display(root,0xa0000000,0x2300000,0xa0000000)
        controls.apply(root,blob)
        with self.assertRaises(ValueError):controls.apply(root,blob)
        # Feed one changed property through the actual policy. FDT parsing is
        # separately covered; the initial valid call above uses real bytes.
        from ports.redfin.memory import _tree
        nodes,_=_tree(blob)
        changes=[('/soc/gpio_keys/vol_up','linux,code',(116).to_bytes(4,'big')),
            ('/soc/gpio_keys/vol_up','gpios',bytes(12)),
            (report['panel'],'qcom,mdss-dsi-bl-max-level',(2047).to_bytes(4,'big')),
            ('/soc/qcom,spmi@c440000','qcom,ee',(1).to_bytes(4,'big'))]
        for target,key,bad in changes:
            altered=copy.deepcopy(nodes);altered[target][key]=bad
            with mock.patch.object(controls,'_tree',return_value=(altered,[])):
                with self.assertRaises(ValueError):controls.validate(blob)


if __name__=='__main__':unittest.main()
