"""Run the actual DWC3 TX queue/event handlers against completed DMA TRBs."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_usb_gadget import patched_source
from ports.redfin.test_touch_events import function

HERE = Path(__file__).resolve().parent

STUB = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
typedef uintptr_t vm_offset_t;
typedef void *ifnet_t;
typedef int lck_mtx_t;
typedef struct {size_t length;} *mbuf_t;
struct rf_usb_gadget_guard {bool redfin,enum_only;int error;};
#define ETHER_MAX_LEN 1518
#define ETHER_CRC_LEN 4
static uint8_t memory[16384];
static struct {size_t length;} packets[2];
static unsigned copies,starts,syncs,freed,locks,violations,proof_calls,lose_at,other_events;
static int printf(const char *format,...){(void)format;return 0;}
static void lck_mtx_lock(lck_mtx_t *p){(void)p;if(locks++)violations++;}
static void lck_mtx_unlock(lck_mtx_t *p){(void)p;if(!locks)violations++;else locks--;}
static bool ud_redfin_proof(void){
 if(++proof_calls==lose_at)ud.guard.error=EPERM;
 return !ud.guard.error;
}
static void rf_usb_gadget_fail(struct rf_usb_gadget_guard *g,int error){if(!g->error)g->error=error;}
static void ud_sync(uint32_t offset,uint32_t bytes){
 syncs++;if(!locks || offset!=UD_TRB_TX || bytes!=16)violations++;
}
static size_t mbuf_pkthdr_len(mbuf_t m){return m->length;}
static void mbuf_freem(mbuf_t m){(void)m;freed++;}
static int mbuf_copydata(mbuf_t m,size_t offset,size_t bytes,void *out){
 if(!locks || offset || bytes!=m->length || out!=memory+UD_TX)violations++;
 copies++;memset(out,0xa5,bytes);return 0;
}
static void ud_start_trb(unsigned ep,uint32_t offset,uint32_t buffer,uint32_t bytes,uint32_t ctl){
 if(!locks || ep!=EP_TX || offset!=UD_TRB_TX || buffer!=UD_TX)violations++;
 volatile uint32_t *t=(volatile uint32_t *)(memory+offset);
 uint64_t pa=ud.dma_pa+buffer;t[0]=(uint32_t)pa;t[1]=(uint32_t)(pa>>32);t[2]=bytes;
 t[3]=ctl|TRB_HWO|TRB_LST|TRB_IOC|TRB_ISP_IMI;starts++;
}
static uint32_t dwc_rd(uint32_t offset){(void)offset;other_events++;return 0;}
static void dwc_wr(uint32_t offset,uint32_t value){(void)offset;(void)value;other_events++;}
static int ud_epcmd(unsigned ep,uint32_t cmd,uint32_t a,uint32_t b,uint32_t c){
 (void)ep;(void)cmd;(void)a;(void)b;(void)c;other_events++;return 0;
}
static void ud_rx_done(void){other_events++;}
static void ud_setup(void){other_events++;}
static void ud_start_setup(void){other_events++;}
static void ud_start(unsigned ep,uint32_t offset,uint32_t size,uint32_t control){
 (void)ep;(void)offset;(void)size;(void)control;other_events++;
}
'''

HARNESS = r'''
void reset(unsigned legacy){
 memset(&ud,0,sizeof(ud));memset(memory,0,sizeof(memory));
 copies=starts=syncs=freed=locks=violations=proof_calls=lose_at=other_events=0;
 ud.guard.redfin=!legacy;ud.dma=(uintptr_t)memory;ud.dma_pa=UINT64_C(0x180000000);
 ud.configured=true;ud.lock=(lck_mtx_t *)1;
}
void submit(unsigned first,unsigned second){
 packets[0].length=first;packets[1].length=second;
 ud.txq[0]=(mbuf_t)&packets[0];ud.txq_count=1;
 if(second){ud.txq[1]=(mbuf_t)&packets[1];ud.txq_count++;}
 lck_mtx_lock(ud.lock);ud_tx_kick_locked();lck_mtx_unlock(ud.lock);
}
void hardware_done(void){uint32_t *t=(uint32_t *)(memory+UD_TRB_TX);t[2]=0;t[3]&=~TRB_HWO;}
void trb_word(unsigned index,uint32_t value){if(index<4)((uint32_t *)(memory+UD_TRB_TX))[index]=value;}
void invalidate(unsigned key){
 if(key==0)ud.tx_busy=false;else if(key==1)ud.tx_bytes=0;else if(key==2)ud.configured=false;
 else if(key==3)ud.tx_bytes=UD_FRAME_MAX+1;
}
void lose_proof(unsigned calls){lose_at=proof_calls+calls;}
void event(unsigned ep,unsigned type,unsigned status){ud_event((ep<<1)|(type<<6)|(status<<12));}
uint64_t metric(unsigned key){
 const uint64_t values[]={ud.guard.error,ud.tx_busy,ud.tx_bytes,ud.tx_completed_frames,
  ud.tx_completed_bytes,copies,starts,syncs,freed,locks,violations,ud.txq_count,ud.tx_frames,other_events};
 return key<sizeof(values)/sizeof(values[0])?values[key]:0;
}
'''


class USBTXCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        patched_source(root)
        for name in ('usb-network-worker.patch', 'usb-log-worker-check.patch', 'usb-tx-completion.patch'):
            subprocess.run(['git', 'apply', '--include=bsd/dev/sweet_usb.c', str(HERE / name)],
                           cwd=root, check=True, capture_output=True)
        source = (root / 'bsd/dev/sweet_usb.c').read_text()
        macros = '\n'.join(line for line in source.splitlines() if line.startswith('#define'))
        state = re.search(r'static struct \{.*?\n\} ud;', source, re.S).group()
        actual = '\n'.join(function(source, signature) for signature in (
            'static void\nud_tx_kick_locked(', 'static bool\nud_redfin_tx_complete(',
            'static void\nud_event('))
        # Types precede the real driver state; fake services follow it.
        types, services = STUB.split('static uint8_t memory', 1)
        model = root / 'model.c'
        model.write_text(types + '\n' + macros + '\n' + state + '\nstatic uint8_t memory' +
                         services + '\n' + actual + HARNESS)
        library = root / 'model.so'
        result = subprocess.run([compiler, '-shared', '-fPIC', '-std=c11', '-O2',
                                 '-Wall', '-Wextra', '-Werror', str(model), '-o', str(library)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library))
        cls.lib.metric.restype = C.c_uint64

    def setUp(self):
        self.lib.reset(0)

    def tearDown(self):
        self.assertEqual(self.lib.metric(9), 0, 'lock leaked')
        self.assertEqual(self.lib.metric(10), 0, 'fake DMA/lock contract violated')

    def test_completed_frame_and_padding_use_actual_queued_lengths(self):
        self.lib.submit(90, 512)
        self.lib.hardware_done()
        self.lib.event(3, 1, 12)
        self.assertEqual([self.lib.metric(i) for i in range(7)], [0, 1, 513, 1, 90, 2, 2])
        self.lib.hardware_done()
        self.lib.event(3, 1, 8)
        self.assertEqual([self.lib.metric(i) for i in range(5)], [0, 0, 0, 2, 603])

    def test_successful_event_flags_allow_ioc_and_last_without_error(self):
        for status in (0, 4, 8, 12):
            with self.subTest(status=status):
                self.lib.reset(0);self.lib.submit(90, 0);self.lib.hardware_done()
                self.lib.event(3, 1, status)
                self.assertEqual([self.lib.metric(i) for i in range(5)], [0, 0, 0, 1, 90])

    def test_bus_or_short_error_retains_inflight_buffer_and_queued_packet(self):
        for status in (1, 2, 3, 5, 10, 15):
            with self.subTest(status=status):
                self.lib.reset(0);self.lib.submit(90, 64);self.lib.hardware_done()
                self.lib.event(3, 1, status)
                self.assertEqual([self.lib.metric(i) for i in (0, 1, 3, 5, 6, 11)],
                                 [errno.EIO, 1, 0, 1, 1, 1])

    def test_bad_descriptor_never_reuses_dma_or_counts_delivery(self):
        control = 2 | 16 | 1024 | 2048
        mutations = ((0, 0), (1, 0), (2, 1), (2, 1 << 28), (2, 1 << 24),
                     (3, control | 1), (3, control ^ 16), (3, control ^ 2), (3, control ^ 2048))
        for index, value in mutations:
            with self.subTest(index=index,value=value):
                self.lib.reset(0);self.lib.submit(90, 64);self.lib.hardware_done()
                self.lib.trb_word(index, value);self.lib.event(3, 1, 12)
                self.assertEqual([self.lib.metric(i) for i in (0, 1, 3, 5, 6, 11)],
                                 [errno.EIO, 1, 0, 1, 1, 1])

    def test_missing_submission_or_configuration_stops_before_dma_read(self):
        for key in range(4):
            with self.subTest(key=key):
                self.lib.reset(0);self.lib.submit(90, 64);self.lib.hardware_done();self.lib.invalidate(key)
                self.lib.event(3, 1, 12)
                self.assertEqual(self.lib.metric(0), errno.EIO)
                self.assertEqual([self.lib.metric(i) for i in (3, 5, 6, 7)], [0, 1, 1, 0])

    def test_lease_loss_before_or_after_cache_sync_blocks_reuse(self):
        for calls, syncs in ((1, 0), (2, 1)):
            with self.subTest(calls=calls):
                self.lib.reset(0);self.lib.submit(90, 64);self.lib.hardware_done();self.lib.lose_proof(calls)
                self.lib.event(3, 1, 12)
                self.assertEqual([self.lib.metric(i) for i in (0, 1, 3, 5, 6, 7)],
                                 [errno.EPERM, 1, 0, 1, 1, syncs])

    def test_duplicate_or_other_endpoint_event_cannot_create_a_receipt(self):
        self.lib.submit(90, 0);self.lib.hardware_done()
        for endpoint, kind in ((3, 2), (3, 3), (5, 1), (2, 1)):
            self.lib.event(endpoint, kind, 12)
            self.assertEqual(self.lib.metric(3), 0)
        self.lib.event(3, 1, 12)
        self.lib.event(3, 1, 12)
        self.assertEqual([self.lib.metric(i) for i in (0, 3, 4)], [errno.EIO, 1, 90])

    def test_legacy_handler_keeps_its_existing_behavior(self):
        self.lib.reset(1);self.lib.submit(90, 64)
        self.lib.event(3, 1, 15)
        self.assertEqual([self.lib.metric(i) for i in (0, 1, 3, 5, 6, 7)], [0, 1, 0, 2, 2, 0])


if __name__ == '__main__':
    unittest.main()
