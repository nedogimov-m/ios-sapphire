"""Real queue recovery and exact SEC clear frame, with lost ownership/faults."""
import ctypes as C
import errno
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_smp_gui import patched_source, compile_shared
from test_touch_events import function
from ports.redfin import test_touch_events_worker as worker_model

HERE = Path(__file__).resolve().parent


class TouchOverflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        for name in ('redfin_touch_protocol.h', 'redfin_touch_events.h'):
            (root / name).write_text(patched_source('bsd/dev/' + name))
        source = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
#include "redfin_touch_events.h"
static struct redfin_events_state state;
static unsigned scenario,reads,clears,emits,down,violations,after_clear;
static void coordinate(uint8_t *p,unsigned action,unsigned remaining){
 memset(p,0,8);p[0]=(uint8_t)((action<<6)|4);p[1]=20;p[2]=30;p[7]=(uint8_t)remaining;
}
static void emit(void *ctx,unsigned finger,int pressed,unsigned x,unsigned y){
 if(ctx || finger || x>=1080 || y>=2340)violations++;
 emits++;down=pressed;
}
static int clear(void *ctx){
 if(ctx || down || state.synchronized || state.startup_reset)violations++;
 clears++;after_clear=1;return scenario==1?EIO:scenario==2?EBUSY:scenario==3?EPIPE:0;
}
static int read(void *ctx,unsigned reg,unsigned n,uint8_t *out){
 if(ctx || reg!=0x60 || n!=8){violations++;return EINVAL;}
 reads++;memset(out,0,n);
 if(!after_clear){coordinate(out,1,32);return 0;}
 if(scenario==4)return EIO;
 if(scenario==5){coordinate(out,1,32);return 0;}
 if(scenario==6){coordinate(out,2,0);return 0;}
 if(scenario==7){out[0]=9;out[1]=0;out[2]=0x10;return 0;}
 if(scenario==8 && reads==2)coordinate(out,2,0);
 return 0;
}
static const struct redfin_events_ops ops={read,emit,NULL,clear};
int run(unsigned issue){
 scenario=issue;reads=clears=emits=down=violations=after_clear=0;memset(&state,0,sizeof(state));
 state.synchronized=true;state.down=1;state.x[0]=100;state.y[0]=200;state.contacts=1;down=1;
 int error=redfin_events_batch(&state,&ops,true);
 if(error!=EOVERFLOW || emits || state.overflows!=1 || (state.overflow_event[7]&63)!=32)return -1;
 error=redfin_events_recover(&state,&ops);
 if(violations || down || state.down || emits!=1 || state.releases!=1 || clears!=1)return -2;
 if(!error && (!state.synchronized || state.startup_reset || state.recoveries!=1))return -3;
 if(error && (state.synchronized || state.recoveries))return -4;
 return error;
}
int event(unsigned b0,unsigned b1){
 uint8_t e[8]={0};e[0]=(uint8_t)b0;e[1]=(uint8_t)b1;
 struct redfin_events_state s={0};s.synchronized=true;
 return redfin_events_accept(&s,e,true,NULL,NULL);
}
int frame(unsigned mutation){
 uint8_t p[8];if(redfin_touch_clear_frame(p)!=8)return -1;
 if(mutation<64)p[mutation/8]^=1u<<(mutation%8);
 return redfin_touch_tx_valid(p,8);
}
unsigned stat(unsigned n){const unsigned v[]={reads,clears,emits,down,violations,state.overflows,state.recoveries,state.suppressed};return n<8?v[n]:0;}
'''
        cls.lib = compile_shared(root, source, 'queue')
        cls.lib.run.argtypes = cls.lib.frame.argtypes = cls.lib.stat.argtypes = [C.c_uint]
        cls.lib.event.argtypes = [C.c_uint, C.c_uint]

    def test_source_clear_frame_exact_bytes_and_each_corruption_rejected(self):
        self.assertEqual(self.lib.frame(64), 1)
        for bit in range(64):
            self.assertEqual(self.lib.frame(bit), 0, bit)

    def test_count_overflow_releases_before_clear_and_resynchronizes_without_new_down(self):
        for issue, reads in ((0, 2), (8, 3)):
            self.assertEqual(self.lib.run(issue), 0)
            self.assertEqual(self.lib.stat(0), reads)
            self.assertEqual(self.lib.stat(6), 1)
        self.assertEqual(self.lib.stat(7), 1)  # Held old contact remains suppressed.

    def test_transport_ownership_consumer_reset_and_persistent_queue_errors_stay_fatal(self):
        for issue, error in ((1, errno.EIO), (2, errno.EBUSY), (3, errno.EPIPE),
                             (4, errno.EIO), (5, errno.EOVERFLOW), (6, errno.EBUSY), (7, errno.EIO)):
            self.assertEqual(self.lib.run(issue), error, issue)
            self.assertEqual(self.lib.stat(1), 1)
            self.assertEqual(self.lib.stat(6), 0)
            self.assertLessEqual(self.lib.stat(0), 5)

    def test_only_native_queue_full_status_is_recoverable_other_errors_and_resets_are_fatal(self):
        self.assertEqual(self.lib.event(5, 1), errno.EOVERFLOW)
        for value in (0, 2, 3, 255):
            self.assertEqual(self.lib.event(5, value), errno.EIO)
        self.assertEqual(self.lib.event(9, 0), errno.EIO)


class TouchOverflowSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root / 'redfin_touch_protocol.h').write_text(patched_source('bsd/dev/redfin_touch_protocol.h'))
        spi = patched_source('bsd/dev/redfin_touch_spi.c')
        actual = function(spi, 'int\nredfin_touch_spi_events_clear(void)')
        text = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
#include "redfin_touch_protocol.h"
struct redfin_spi {uintptr_t se;unsigned tx_depth,rx_depth;bool dead,command_owned;};
static struct redfin_spi redfin_spi_event_context;
static bool redfin_spi_event_open,redfin_spi_event_sensing,redfin_spi_scan_active;
static uintptr_t redfin_spi_verified_se;
static unsigned redfin_spi_verified_hz,redfin_spi_event_clears;
static unsigned transfers,closes,bad;
static int failed;
#define printf(...) ((void)0)
static void redfin_touch_spi_events_close(void){closes++;redfin_spi_event_open=false;redfin_spi_event_sensing=false;redfin_spi_verified_se=0;redfin_spi_verified_hz=0;}
static int redfin_spi_transfer(struct redfin_spi *s,const uint8_t *p,uint8_t *rx,unsigned n){
 const uint8_t expected[]={0xaa,0,1,0,0,0x62,0x0d,0};
 transfers++;if(s!=&redfin_spi_event_context || rx || n!=8 || memcmp(p,expected,8))bad++;
 return failed;
}
''' + actual + r'''
int run(unsigned issue){
 memset(&redfin_spi_event_context,0,sizeof(redfin_spi_event_context));
 redfin_spi_event_context.se=redfin_spi_verified_se=0x880000;redfin_spi_verified_hz=10000000;
 redfin_spi_event_open=redfin_spi_event_sensing=true;redfin_spi_scan_active=false;
 redfin_spi_event_clears=transfers=closes=bad=0;failed=0;
 switch(issue){case 1:redfin_spi_event_open=false;break;case 2:redfin_spi_event_sensing=false;break;
 case 3:redfin_spi_verified_se=0;break;case 4:redfin_spi_verified_hz=0;break;
 case 5:redfin_spi_event_context.se++;break;case 6:redfin_spi_event_context.dead=true;break;
 case 7:redfin_spi_scan_active=true;break;case 8:failed=EIO;break;case 9:break;default:break;}
 if(issue==9){for(unsigned i=0;i<8;i++)if(redfin_touch_spi_events_clear())return -1;
  if(redfin_touch_spi_events_clear()!=EOVERFLOW || transfers!=8 || redfin_spi_event_clears!=8 || closes || bad)return -2;return 0;}
 int error=redfin_touch_spi_events_clear();
 if(issue>=1 && issue<=7)return error==ENOTSUP&&!transfers&&!closes&&!bad?0:-3;
 if(issue==8){if(error!=EIO || transfers!=1 || closes!=1 || bad)return -4;
  return redfin_touch_spi_events_clear()==ENOTSUP && transfers==1 && closes==1?0:-5;}
 return !error&&transfers==1&&!closes&&!bad?0:-6;
}
'''
        cls.lib = compile_shared(root, text, 'session')
        cls.lib.run.argtypes = [C.c_uint]

    def test_only_sensed_owned_session_clears_and_never_retries_failures_or_exceeds_eight(self):
        for issue in range(10):
            self.assertEqual(self.lib.run(issue), 0, issue)


class TouchOverflowWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = 1
        old_added, old_run = worker_model.added_file, subprocess.run

        def final_added(patch, name):
            actual = patched_source(name)
            if name == 'bsd/dev/redfin_touch_events.c':
                actual = '''#define REDFIN_TOUCH_UFS_EVENTS 2
bool redfin_touch_boot_lease_valid(unsigned mode){return mode==2;}
int redfin_gui_selected(void){return 1;}
int redfin_gui_bind_worker(void){return 1;}
static unsigned test_clears;
static int test_clear_error;
int redfin_touch_spi_events_clear(void){test_clears++;return test_clear_error;}
int redfin_touch_spi_events_sense_init(void){return 0;}
''' + actual
            return actual

        def compile_final(command, *args, **kwargs):
            if isinstance(command, list) and any(str(p).endswith('/worker.c') for p in command):
                source = Path(next(str(p) for p in command if str(p).endswith('/worker.c')))
                text = source.read_text()
                # The scripted model already produces a32-count event at read3.
                # Add clear failure variants and reset helper facts for each run.
                text = text.replace('fault==7 ? 32 : 0', '(fault==7 || fault==20 || fault==21) ? 32 : 0')
                text = text.replace('if(fault==3 || fault==14)return EIO;',
                    'if(fault==3 || fault==14)return EIO; if(fault>=22 && fault<=24)return EILSEQ;')
                text = text.replace('read60++;', 'read60++;if(fault==24 && read60>=5)return EILSEQ;')
                text = text.replace('if(base==1 && offset==0x1004)return 0;', '''if(base==1 && offset==0x1004){
                    if(fault==25)return 1;
                    if(fault==26){
                        if(read60<3)return now<700000000ull;
                        if(read60==3)return now<900000000ull;
                        return read60>=5;
                    }
                    return 0;
                }''')
                text = text.replace('redfin_events_attempted=false;',
                    'redfin_events_attempted=false;test_clears=0;test_clear_error=(fault==20||fault==23)?EIO:fault==21?EBUSY:0;')
                text += '\nunsigned clear_calls(void){return test_clears;}\n'
                source.write_text(text)
            return old_run(command, *args, **kwargs)

        try:
            # Preload sources before replacing subprocess.run: source reconstruction
            # itself uses git apply and must not recursively enter this wrapper.
            actual = {name: final_added('', name) for name in ('bsd/dev/redfin_touch_protocol.h',
                'bsd/dev/redfin_touch_events.h', 'bsd/dev/redfin_touch_events.c')}
            worker_model.added_file = lambda patch, name: actual[name]
            subprocess.run = compile_final
            worker_model.TouchEventWorkerTests.setUpClass.__func__(cls)
        finally:
            worker_model.added_file, subprocess.run = old_added, old_run

    def test_worker_survives_one_overflow_and_finishes_session(self):
        self.assertEqual(self.lib.run(7, 1, 1), 0)
        self.assertEqual(self.lib.stat(10), 0)
        self.assertEqual(self.lib.clear_calls(), 1)
        self.assertEqual(self.lib.stat(9), 0)
        self.assertEqual(self.lib.stat(7), 1)
        self.assertGreaterEqual(self.lib.stat(4), 5)

    def test_clear_failure_is_final_and_never_reopens_spi(self):
        for issue, error in ((20, errno.EIO), (21, errno.EBUSY)):
            self.assertEqual(self.lib.run(issue, 1, 1), 0)
            self.assertEqual(self.lib.stat(10), error)
            self.assertEqual(self.lib.clear_calls(), 1)
            self.assertEqual(self.lib.stat(6), 1)
            self.assertEqual(self.lib.stat(7), 1)
            self.assertEqual(self.lib.stat(9), 0)

    def test_bad_reply_releases_held_contact_and_resynchronizes_without_replaying_it(self):
        self.assertEqual(self.lib.run(22, 1, 1), 0)
        self.assertEqual(self.lib.stat(10), 0)
        self.assertEqual(self.lib.clear_calls(), 1)
        self.assertEqual(self.lib.stat(6), 1)
        self.assertEqual(self.lib.stat(7), 1)
        self.assertEqual(self.lib.stat(8), 2)  # One DOWN, one UP before queue clear.
        self.assertEqual(self.lib.stat(9), 0)

    def test_bad_reply_during_resynchronization_or_clear_failure_is_final(self):
        for issue, error in ((23, errno.EIO), (24, errno.EILSEQ)):
            self.assertEqual(self.lib.run(issue, 1, 1), 0)
            self.assertEqual(self.lib.stat(10), error)
            self.assertEqual(self.lib.clear_calls(), 1)
            self.assertEqual(self.lib.stat(6), 1)
            self.assertEqual(self.lib.stat(7), 1)
            self.assertEqual(self.lib.stat(9), 0)

    def test_idle_high_irq_never_consumes_events_and_low_irq_drains_finger_updates(self):
        self.assertEqual(self.lib.run(25, 1, 1), 0)
        self.assertEqual(self.lib.stat(4), 2)  # Initial synchronization only.
        self.assertEqual(self.lib.stat(8), 0)
        self.assertEqual(self.lib.clear_calls(), 0)
        self.assertEqual(self.lib.run(26, 1, 1), 0)
        self.assertEqual(self.lib.stat(4), 5)  # Initial2 + DOWN/MOVE/UP, no idle reads.
        self.assertEqual(self.lib.stat(8), 3)
        self.assertEqual(self.lib.stat(10), 0)


if __name__ == '__main__':
    unittest.main()
