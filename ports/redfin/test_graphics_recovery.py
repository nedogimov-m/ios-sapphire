"""Actual late-fence, coherent-CPU lease and HID consumer-reconnect behavior."""
import ctypes as C
import errno
from pathlib import Path
import tempfile
import unittest

from test_smp_gui import compile_shared,patched_source
from test_touch_events import function

HERE=Path(__file__).resolve().parent


class GraphicsWaitAndLeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        lease=(HERE/'gpu-runtime.inc').read_text().split('/* REDFIN_GPU_THREAD_LEASE_BEGIN */',1)[1].split(
            '/* REDFIN_GPU_THREAD_LEASE_END */',1)[0]
        cpu=function((HERE/'gui-runtime.h').read_text(),'int redfin_gui_runtime_cpu(void)\n{')
        source=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "redfin_gpu_runtime.h"
typedef void *thread_t;
static struct {thread_t caller;unsigned state;} gr;
static unsigned selected_cpu,proof,ready,thread_id;
static thread_t current_thread(void){return (void *)(uintptr_t)thread_id;}
static int redfin_gui_ready(void){return ready;}
static int redfin_smp_verified(void){return proof;}
static unsigned rf_smp_local(void){return selected_cpu;}
static bool redfin_gpu_ready(void){return gr.state==1;}
static void redfin_gpu_poison(const char *why){(void)why;gr.state=2;}
'''+cpu+lease+r'''
void reset_lease(unsigned cpu,unsigned proved,unsigned published){
    gr.caller=NULL;gr.state=1;thread_id=1;selected_cpu=cpu;proof=proved;ready=published;
}
int acquire(void){return redfin_gpu_bind()!=NULL;}
void release_lease(void){redfin_gpu_unbind(NULL);}
void thread_id_set(unsigned n){thread_id=n;}
int owned(void){return redfin_gpu_runtime_caller();}
unsigned state(void){return gr.state;}
static uint64_t clock_ns;
static unsigned scenario,time_calls,samples,pauses,last_polls;
static uint64_t now(void *context){
    (void)context;time_calls++;
    if(scenario==1 && time_calls==2)clock_ns=600000000;
    if(scenario==5 && time_calls==2)clock_ns=0;
    return clock_ns;
}
static int sample(void *context,bool *complete){
    (void)context;samples++;
    if(scenario==4 && samples==2)return EIO;
    if(scenario==7){*complete=true;return EIO;}
    *complete=scenario!=3 && scenario!=5 && scenario!=6 && clock_ns>=20000000;
    return 0;
}
static void pause_wait(void *context,unsigned us){
    (void)context;pauses++;
    if(scenario==2 || scenario==4)clock_ns+=600000000;
    else if(scenario!=6)clock_ns+=(uint64_t)us*1000;
}
int wait_case(unsigned mode){
    scenario=mode;time_calls=samples=pauses=last_polls=0;clock_ns=mode==5?1000:0;
    const struct rf_gr_wait_ops ops={NULL,sample,now,pause_wait};
    return rf_gr_wait(&ops,500000000,&last_polls);
}
unsigned metric(unsigned which){return which==0?last_polls:which==1?samples:pauses;}
'''
        cls.lib=compile_shared(Path(cls.temp.name),source,'graphics-recovery',flags=('-I',str(HERE/'include')))

    def test_runtime_lease_needs_the_current_thread_and_a_proved_gui_cpu(self):
        for cpu in range(8):
            self.lib.reset_lease(cpu,1,1);self.assertEqual(self.lib.owned(),0)
            self.assertEqual(self.lib.acquire(),0);self.assertEqual(self.lib.owned(),1)
            self.lib.thread_id_set(2);self.assertEqual(self.lib.owned(),0)
            self.lib.thread_id_set(1);self.lib.release_lease();self.assertEqual(self.lib.owned(),0)
        for cpu,proof,ready in ((8,1,1),(0,0,1),(0,1,0)):
            self.lib.reset_lease(cpu,proof,ready);self.lib.acquire();self.assertEqual(self.lib.owned(),0)

    def test_overlapping_or_changed_thread_leases_stay_poisoned(self):
        self.lib.reset_lease(7,1,1);self.lib.acquire();self.lib.thread_id_set(2)
        self.lib.release_lease();self.assertEqual(self.lib.state(),2);self.assertEqual(self.lib.owned(),0)
        self.lib.reset_lease(7,1,1);self.lib.acquire();self.lib.thread_id_set(2)
        self.assertEqual(self.lib.acquire(),1);self.assertEqual(self.lib.state(),2)

    def test_real_completion_after_scheduler_delay_is_observed_before_timeout(self):
        for mode in (0,1,2):self.assertEqual(self.lib.wait_case(mode),0)
        self.assertEqual(self.lib.metric(0),2)
        self.assertEqual(self.lib.wait_case(1),0)
        self.assertEqual(self.lib.metric(0),2);self.assertEqual(self.lib.metric(2),0)

    def test_missing_fences_faults_and_clock_errors_never_fabricate_completion(self):
        for mode in (3,6):
            self.assertEqual(self.lib.wait_case(mode),errno.ETIMEDOUT)
            self.assertLessEqual(self.lib.metric(0),5001)
        self.assertEqual(self.lib.wait_case(4),errno.EIO)
        self.assertEqual(self.lib.wait_case(5),errno.EINVAL)
        self.assertEqual(self.lib.wait_case(7),errno.EIO)


class HIDReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        directory=Path(cls.temp.name)
        for name in ('redfin_touch_events.h','redfin_touch_protocol.h'):
            (directory/name).write_text(patched_source('bsd/dev/'+name))
        helper=(HERE/'touch-reconnect.inc').read_text()
        if helper!=patched_source('bsd/dev/redfin_touch_reconnect.inc'):raise RuntimeError('reconnect overlay drift')
        source=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include "redfin_touch_events.h"
#define printf(...) ((void)0)
static uint64_t now_ns,ready_at;
static unsigned scenario,reads,clears,downs,ups,violations,event_at;
static bool redfin_events_delivery_failed;
static uint64_t mach_absolute_time(void){return now_ns;}
static bool redfin_events_owned(void){return scenario!=2 || now_ns<40000000;}
static bool sweet_hid_redfin_touch_ready(void){return now_ns>=ready_at;}
static void redfin_events_wait(unsigned ms){now_ns+=(uint64_t)ms*1000000;}
static void redfin_events_emit_hid(void *context,unsigned finger,int down,unsigned x,unsigned y){
    (void)context;(void)finger;(void)x;(void)y;
    if(down){downs++;if(!sweet_hid_redfin_touch_ready())violations++;}else ups++;
}
static void contact(uint8_t *out,unsigned action){
    memset(out,0,8);out[0]=(uint8_t)((action<<6)|4);out[1]=31;out[2]=62;out[3]=0x48;
}
static int read_event(void *context,unsigned reg,unsigned count,uint8_t *out){
    (void)context;if(!redfin_events_owned() || !sweet_hid_redfin_touch_ready())violations++;
    if(reg!=0x60 || count!=8){violations++;return EINVAL;}reads++;memset(out,0,count);
    if(scenario==1 && reads==1){ready_at=now_ns+40000000;return EPIPE;}
    if(scenario==4 && !clears){out[0]=4;out[7]=32;return 0;}
    if(scenario==5){out[0]=9;out[2]=0x20;return 0;}
    if(!event_at++)contact(out,1);
    return 0;
}
static int clear_events(void *context){(void)context;clears++;return 0;}
static int redfin_events_resynchronize(struct redfin_events_state *s,const struct redfin_events_ops *ops){
    return redfin_events_recover(s,ops);
}
'''+helper+r'''
int reconnect(unsigned mode){
    scenario=mode;now_ns=0;ready_at=80000000;reads=clears=downs=ups=violations=event_at=0;
    redfin_events_delivery_failed=true;
    struct redfin_events_state s={.down=1,.synchronized=true};
    const struct redfin_events_ops ops={read_event,redfin_events_emit_hid,NULL,clear_events};
    int result=redfin_events_reconnect(&s,&ops,mode==3?60000000:200000000);
    if(!result) {
        uint8_t event[8];contact(event,2);redfin_events_accept(&s,event,true,redfin_events_emit_hid,NULL);
        if(downs)violations++;
        contact(event,3);redfin_events_accept(&s,event,true,redfin_events_emit_hid,NULL);
        contact(event,1);redfin_events_accept(&s,event,true,redfin_events_emit_hid,NULL);
    }
    return violations?-999:result;
}
unsigned metric(unsigned n){return n==0?reads:n==1?clears:n==2?downs:ups;}
'''
        cls.lib=compile_shared(directory,source,'hid-reconnect')

    def test_consumer_replacement_keeps_hardware_session_and_suppresses_old_gestures(self):
        for mode in (0,1,4):
            self.assertEqual(self.lib.reconnect(mode),0)
            self.assertEqual(self.lib.metric(2),1)
            self.assertEqual(self.lib.metric(3),1)
            self.assertEqual(self.lib.metric(1),int(mode==4))

    def test_deadline_hardware_lease_loss_and_controller_reset_remain_fatal(self):
        for mode,error in ((2,errno.EBUSY),(3,errno.ETIMEDOUT),(5,errno.EIO)):
            self.assertEqual(self.lib.reconnect(mode),error)
            self.assertEqual(self.lib.metric(2),0)
        self.lib.reconnect(3);self.assertEqual(self.lib.metric(0),0)


if __name__=='__main__':unittest.main()
