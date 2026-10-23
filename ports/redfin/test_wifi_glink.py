"""Run the actual bounded GLINK allocator/rings against firmware-like frames."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_wifi_smem import fixture, PART, PART_SIZE

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include "wifi_glink.h"
static uint8_t smem[REDFIN_SMEM_BYTES],received[65536],scratch[8256];
static struct rf_glink session;
static unsigned live,locked,locks,unlocks,writes,fail_write,kicks,received_bytes,unsafe,bulk_failure;
static int check(void *p){return p==&session && live ? 0 : -1;}
static int lock(void *p){if(check(p)||locked)return -1;locked=1;++locks;return 0;}
static int unlock(void *p){if(p!=&session||!locked)return -1;locked=0;++unlocks;return 0;}
static int write32(void *p,uint32_t at,uint32_t value){
 if(check(p)||at%4||at>REDFIN_SMEM_BYTES-4){++unsafe;return -1;}
 if(++writes==fail_write)return -1;
 for(unsigned i=0;i<4;++i)smem[at+i]=(uint8_t)(value>>(i*8));return 0;
}
static int barrier(void *p){return check(p);}
static int kick(void *p){++kicks;return check(p);}
static void packet(void *p,const uint8_t *data,uint32_t bytes){
 if(check(p)||bytes>sizeof(received)){++unsafe;return;}memcpy(received,data,bytes);received_bytes=bytes;
}
static int payload(void *p,uint32_t at,const uint8_t *data,uint32_t bytes){
 if(check(p)||at<session.tx||bytes>16384||at-session.tx>16384-bytes){++unsafe;return -1;}
 memcpy(smem+at,data,bulk_failure ? bytes/2 : bytes);return bulk_failure ? -1 : 0;
}
static struct rf_glink_ops ops={&session,smem,check,lock,unlock,write32,barrier,kick,packet,NULL};
uint8_t *memory(void){return smem;}
void reset(void){memset(&session,0,sizeof(session));memset(smem,0,sizeof(smem));live=1;locked=locks=unlocks=writes=fail_write=kicks=received_bytes=unsafe=bulk_failure=0;ops.payload=NULL;}
void option(unsigned which,unsigned value){if(which==0)live=value;if(which==1)fail_write=value;if(which==2)ops.payload=payload;if(which==3)bulk_failure=value;}
int initialize(void){return rf_gl_init(&session,&ops);}
int pump(void){int e=rf_gl_pump(&session,&ops);if(e && e!=RF_GL_AGAIN)session.poisoned=1;return e;}
int say(void){return rf_gl_say(&session,&ops,0,1,1,NULL,0);}
int send_packet(const uint8_t *data,unsigned bytes){return rf_gl_send_packet(&session,&ops,data,bytes,scratch,sizeof(scratch));}
uint8_t *packet_data(void){return received;}
uint32_t metric(unsigned which){
 const uint32_t values[]={session.descriptor,session.tx,session.head,session.tail,session.version,session.channel,
 session.open,session.heard,session.sent,session.packets,writes,locks,unlocks,kicks,received_bytes,unsafe,session.poisoned};
 return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
'''


class NativeGlinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'model.c').write_text(HARNESS)
        result = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                                 '-I', str(HERE), str(directory / 'model.c'), '-o', str(directory / 'model.so')],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.library = C.CDLL(str(directory / 'model.so'))
        cls.library.memory.restype = C.c_void_p
        cls.library.packet_data.restype = C.c_void_p
        cls.library.send_packet.argtypes = [C.c_void_p, C.c_uint]

    def setUp(self):
        self.library.reset()
        self.memory = (C.c_uint8 * 0x200000).from_address(self.library.memory())
        C.memmove(self.library.memory(), bytes(fixture(False)), len(self.memory))
        self.rx = 0

    def remote_item(self, item, data):
        free = struct.unpack_from('<I', self.memory, PART + 12)[0]
        at = PART + free
        struct.pack_into('<HHIHHI', self.memory, at, 0xa5a5, item, len(data), 0, 0, 0)
        self.memory[at + 16:at + 16 + len(data)] = data
        struct.pack_into('<I', self.memory, PART + 12, free + 16 + len(data))
        return at + 16

    def remote(self, frames):
        if not self.rx:
            self.rx = self.remote_item(480, bytes(16384))
        descriptor = self.library.metric(0)
        head = struct.unpack_from('<I', self.memory, descriptor + 12)[0]
        for byte in frames:
            self.memory[self.rx + head] = byte
            head = (head + 1) % 16384
        struct.pack_into('<I', self.memory, descriptor + 12, head)

    @staticmethod
    def frame(command, first=0, second=0, data=b''):
        value = struct.pack('<HHI', command, first, second) + data
        return value.ljust((len(value) + 7) & ~7, b'\0')

    def handshake(self):
        self.assertEqual(self.library.initialize(), 0)
        self.assertEqual(self.library.say(), 0)
        self.remote(self.frame(0, 1, 1) + self.frame(1, 1, 1) + self.frame(2, 7, 7, b'IPCRTR\0') +
                    self.frame(4, 1) + self.frame(5, 7, 1, struct.pack('<II', 8192, 41)))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual((self.library.metric(4), self.library.metric(5), self.library.metric(6)), (1, 7, 1))

    def test_new_host_allocations_are_bounded_and_publish_only_their_own_words(self):
        self.assertEqual(self.library.initialize(), 0)
        self.assertEqual((self.library.metric(11), self.library.metric(12)), (1, 1))
        self.assertEqual(self.library.metric(15), 0)
        descriptor, fifo = self.library.metric(0), self.library.metric(1)
        self.assertEqual(bytes(self.memory[descriptor:descriptor + 32]), bytes(32))
        self.assertGreater(fifo, descriptor)
        free = struct.unpack_from('<I', self.memory, PART + 12)[0]
        self.assertLessEqual(free, PART_SIZE)

    def test_version_negotiates_the_intersection_with_new_peer_capabilities(self):
        self.assertEqual(self.library.initialize(), 0)
        self.assertEqual(self.library.say(), 0)
        self.remote(self.frame(0, 1, 0x83) + self.frame(1, 1, 1) +
                    self.frame(2, 7, 7, b'IPCRTR\0') + self.frame(4, 1))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(self.library.metric(6), 1)

    def test_version_ipcrtr_intents_rx_and_tx_use_real_ring_frames(self):
        self.handshake()
        payload = b'QRTR test payload'
        self.remote(self.frame(9, 7, 1, struct.pack('<II', len(payload), 0) + payload))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(C.string_at(self.library.packet_data(), self.library.metric(14)), payload)
        self.assertEqual(self.library.send_packet(payload, len(payload)), 0)
        self.assertEqual(self.library.send_packet(payload, len(payload)), 6)
        self.remote(self.frame(14, 7, 41))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(self.library.send_packet(payload, len(payload)), 0)

    def test_remote_owned_descriptor_and_fifo_bytes_are_unchanged_by_consumption(self):
        self.handshake()
        descriptor = self.library.metric(0)
        before = bytes(self.memory[self.rx:self.rx + 16384])
        remote_words = bytes(self.memory[descriptor:descriptor + 4]), bytes(self.memory[descriptor + 12:descriptor + 16])
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(bytes(self.memory[self.rx:self.rx + 16384]), before)
        self.assertEqual((bytes(self.memory[descriptor:descriptor + 4]), bytes(self.memory[descriptor + 12:descriptor + 16])), remote_words)

    def test_zero_remote_intent_handle_and_large_capacity_do_not_expand_local_packets(self):
        self.assertEqual(self.library.initialize(), 0)
        self.assertEqual(self.library.say(), 0)
        self.remote(self.frame(0, 1, 1) + self.frame(1, 1, 1) + self.frame(2, 7, 7, b'IPCRTR\0') +
                    self.frame(4, 1) + self.frame(5, 7, 1, struct.pack('<II', 0x100000, 0)))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(self.library.send_packet(b'bounded', 7), 0)
        self.remote(self.frame(14, 7, 0))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(self.library.send_packet(b'bounded', 7), 0)
        self.assertNotEqual(self.library.send_packet(bytes(8193), 8193), 0)

    def test_other_channels_cannot_publish_intents_or_payloads_into_ipcrtr(self):
        self.handshake()
        self.remote(self.frame(2, 12, 10, b'glink_ssr\0') +
                    self.frame(5, 12, 1, struct.pack('<II', 8192, 900)) +
                    self.frame(9, 12, 1, struct.pack('<II', 8, 0) + b'foreign!'))
        self.assertEqual(self.library.pump(), 0)
        self.assertEqual(self.library.metric(9), 0)
        self.assertEqual(self.library.metric(6), 1)
        self.assertEqual(self.library.send_packet(b'ours', 4), 0)
        self.assertEqual(self.library.send_packet(b'ours', 4), 6)

    def test_bulk_fifo_copy_reads_back_before_head_publication_and_partial_failure_is_terminal(self):
        self.handshake()
        self.library.option(2, 1)
        data = bytes((i * 7) % 256 for i in range(4096))
        head = self.library.metric(2)
        self.assertEqual(self.library.send_packet(data, len(data)), 0)
        at = self.library.metric(1) + head
        self.assertEqual(bytes(self.memory[at + 16:at + 16 + len(data)]), data)
        self.remote(self.frame(14, 7, 41))
        self.assertEqual(self.library.pump(), 0)
        head = self.library.metric(2)
        self.library.option(3, 1)
        self.assertNotEqual(self.library.send_packet(data, len(data)), 0)
        self.assertEqual(self.library.metric(2), head)
        self.assertEqual(self.library.metric(16), 1)
        self.assertNotEqual(self.library.say(), 0)

    def test_foreign_owner_indices_and_malformed_packets_fail_without_reset_or_advance(self):
        for bad in ('owner', 'length', 'intent'):
            with self.subTest(bad=bad):
                self.setUp()
                self.handshake()
                tail = self.library.metric(3)
                if bad == 'owner':
                    struct.pack_into('<I', self.memory, self.library.metric(0) + 4, 8)
                else:
                    count = 65537 if bad == 'length' else 8
                    self.remote(self.frame(9, 7, 2 if bad == 'intent' else 1, struct.pack('<II', count, 0) + b'12345678'))
                self.assertNotEqual(self.library.pump(), 0)
                self.assertEqual(self.library.metric(3), tail)
                self.assertEqual(self.library.metric(16), 1)

    def test_failed_allocation_writes_release_only_the_owned_lock_and_cannot_retry(self):
        self.assertEqual(self.library.initialize(), 0)
        count = self.library.metric(10)
        for failure in range(1, count + 1):
            self.setUp()
            self.library.option(1, failure)
            self.assertNotEqual(self.library.initialize(), 0)
            self.assertEqual((self.library.metric(11), self.library.metric(12)), (1, 1))
            self.assertNotEqual(self.library.initialize(), 0)

    def test_lost_live_parent_refuses_queue_writes(self):
        self.handshake()
        writes = self.library.metric(10)
        self.library.option(0, 0)
        self.assertNotEqual(self.library.say(), 0)
        self.assertEqual(self.library.metric(10), writes)


if __name__ == '__main__':
    unittest.main()
