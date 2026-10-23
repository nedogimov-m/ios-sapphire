"""Real SEC response/session code: reject bad bytes and resync only idle events."""
import ctypes as C
import errno
from pathlib import Path
import tempfile
import unittest

from test_smp_gui import compile_shared, patched_source
from test_touch_events import function


class TouchResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        (root / 'protocol.h').write_text(patched_source('bsd/dev/redfin_touch_protocol.h'))
        source = patched_source('bsd/dev/redfin_touch_spi.c')
        read = function(source, 'static int\nredfin_spi_read(')
        event = function(source, 'int\nredfin_touch_spi_event_read(')
        stub = r'''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include "protocol.h"
#define printf(...) ((void)0)
#define RF_SPI_STATUS_EVENTS ((1u<<0)|(1u<<7)|(1u<<26)|(1u<<27)|(1u<<30))
struct redfin_spi{uintptr_t se;unsigned tx_depth,rx_depth;bool dead,command_owned;};
static struct redfin_spi redfin_spi_event_context;
static bool redfin_spi_event_open,redfin_spi_event_sensing;
static unsigned fault,commands,failed,closed,requested,requested_count,settled;
static void delay(unsigned us){settled+=us;}
static uint32_t redfin_spi_rd(struct redfin_spi *s,unsigned at){
 (void)s;if(fault==9 && at==0x40)return 1;
 if(fault==10 && at==0x800)return 1;
 if(fault==11 && at==0x804)return 1;
 if(fault==12 && at==0x610)return 8;
 return at==0x610?0x80:0;
}
static int redfin_spi_failed(struct redfin_spi *s,int error){failed++;s->dead=true;return error;}
static void redfin_touch_spi_events_close(void){closed++;redfin_spi_event_open=false;redfin_spi_event_context.dead=true;}
static int redfin_spi_transfer(struct redfin_spi *s,const uint8_t *tx,uint8_t *rx,unsigned n){
 (void)s;commands++;
 if(fault==4)return ETIMEDOUT;
 if(tx){requested=tx[5];requested_count=((unsigned)tx[3]<<8)|tx[4];return 0;}
 memset(rx,0,n);rx[0]=0xaa;rx[5]=(uint8_t)requested;
 for(unsigned i=0;i<requested_count;i++)rx[7+i]=(uint8_t)(i+1);
 for(unsigned i=0;i<7+requested_count;i++)rx[7+requested_count]+=rx[i];
 if(fault==2)rx[5]^=1;else if(fault==3)rx[0]=0;
 else if(fault!=0)rx[7+requested_count]^=1;
 return 0;
}
'''
        wrapper = r'''
static uint8_t output[248];
int run(unsigned issue,unsigned reg,unsigned count){
 fault=issue;commands=failed=closed=settled=0;memset(output,0x5a,sizeof(output));
 redfin_spi_event_context=(struct redfin_spi){1,16,16,false,false};
 redfin_spi_event_open=redfin_spi_event_sensing=true;
 if(issue==5)redfin_spi_event_sensing=false;
 if(issue==6)redfin_spi_event_context.command_owned=true;
 if(issue==7)redfin_spi_event_context.dead=true;
 return redfin_touch_spi_event_read(reg,count,output);
}
unsigned stat(unsigned n){const unsigned v[]={commands,failed,closed,redfin_spi_event_open,redfin_spi_event_context.dead,output[0],settled};return n<7?v[n]:0;}
'''
        cls.lib = compile_shared(root, stub + read + event + wrapper, 'response')
        cls.lib.run.argtypes = [C.c_uint] * 3

    def test_malformed_completed_event_frames_never_reach_output_or_close_idle_session(self):
        for fault in (1, 2, 3):
            for reg, count in ((0x60, 8), (0x61, 248)):
                self.assertEqual(self.lib.run(fault, reg, count), errno.EILSEQ)
                self.assertEqual([self.lib.stat(i) for i in range(6)], [2, 0, 0, 1, 0, 0x5a])

    def test_transport_errors_non_event_reads_and_unproved_host_state_stay_fatal(self):
        self.assertEqual(self.lib.run(4, 0x60, 8), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(0), 1)
        self.assertEqual(self.lib.stat(2), 1)
        self.assertEqual(self.lib.run(1, 0x55, 1), errno.EIO)
        for fault in (5, 6, 7, 9, 10, 11, 12):
            self.assertEqual(self.lib.run(fault, 0x60, 8), errno.EIO, fault)
            self.assertEqual(self.lib.stat(1), 1, fault)
            self.assertEqual(self.lib.stat(2), 1, fault)
            self.assertEqual(self.lib.stat(5), 0x5a, fault)

    def test_valid_response_is_delivered_once(self):
        self.assertEqual(self.lib.run(0, 0x60, 8), 0)
        self.assertEqual([self.lib.stat(i) for i in range(6)], [2, 0, 0, 1, 0, 1])
        self.assertEqual(self.lib.stat(6), 500)
        self.assertEqual(self.lib.run(0, 0x55, 1), 0)
        self.assertEqual(self.lib.stat(6), 100)


if __name__ == '__main__':
    unittest.main()
