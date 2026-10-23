"""CPU-only ACK/receipt engine and host wire protocol; no devices or startup."""
import ctypes as C
import errno
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('redfin_usb_log_ready_test', HERE / 'usb-log-ready.py')
ready = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ready
SPEC.loader.exec_module(ready)
BOOT, NONCE, COOKIE = '0123456789abcdef', 0x0123456789abcdef, 0x8877665544332211
LEASE = 30_000_000_000

WRAPPER = r'''
#include "usb-log-ready.h"
#include <string.h>
static struct rf_ulr_session session;
void reset(void){memset(&session,0,sizeof(session));}
int begin(uint64_t nonce,uint64_t cookie,unsigned interface,uint64_t now,uint64_t end,uint8_t *out){
 return rf_ulr_begin(&session,nonce,cookie,interface,now,end,out);
}
int tx(const uint8_t *p,size_t n,unsigned frame_bytes,int error,uint64_t now){
 return rf_ulr_tx_completed(&session,p,n,frame_bytes,error,now);
}
int ack(const uint8_t *p,size_t n,uint64_t now,unsigned interface,uint32_t ip,unsigned source,unsigned target){
 return rf_ulr_ack(&session,interface,ip,(uint16_t)source,(uint16_t)target,p,n,now);
}
int marker(uint64_t address,unsigned operation,unsigned value,uint64_t now,uint8_t *out){
 return rf_ulr_marker(&session,address,operation,value,now,out);
}
int take(uint64_t address,unsigned operation,unsigned value,uint64_t now){return rf_ulr_take_marker(&session,address,operation,value,now);}
int poll(uint64_t now){return rf_ulr_poll(&session,now);}
bool listener(uint64_t now){return rf_ulr_listener_ready(&session,now);}
void abort_session(int error){rf_ulr_abort(&session,error);}
uint64_t stat(unsigned field){
 const uint64_t values[]={session.phase,session.error,session.markers,session.rejected,
  session.last_time,session.request_end,session.lease_end,session.pending.sequence};
 return field<sizeof(values)/sizeof(values[0])?values[field]:0;
}
int codec(const uint8_t *p,size_t n,uint8_t *out,size_t capacity){
 struct rf_ulr_message m;int error=rf_ulr_decode(p,n,&m);return error?error:rf_ulr_encode(&m,out,capacity);
}
'''

SANITIZER = r'''
#include "usb-log-ready.h"
#include <assert.h>
#include <string.h>
#include <sys/errno.h>
int main(void){
 struct rf_ulr_message hello={RF_ULR_HELLO,1,0x123456789abcdefULL,0x8877665544332211ULL,0,0,0};
 uint8_t source[64],output[64],pending[48],ack[48];
 assert(!rf_ulr_encode(&hello,source,sizeof(source)));
 for(unsigned i=0;i<4096;i++){
  uint8_t input[64];memcpy(input,source,48);memset(input+48,0,16);
  input[(i/8)%64]^=(uint8_t)(1u<<(i%8));
  struct rf_ulr_message message;
  memset(output,0xa5,sizeof(output));
  if(!rf_ulr_decode(input,i%65,&message)){
   assert(!rf_ulr_encode(&message,output,48));assert(!memcmp(input,output,48));
  }
  for(unsigned at=48;at<64;at++)assert(output[at]==0xa5);
 }
 struct rf_ulr_session session={0};uint64_t now=0;
 assert(!rf_ulr_begin(&session,hello.boot_nonce,hello.cookie,7,now,30000000000ULL,pending));
 assert(!rf_ulr_tx_completed(&session,pending,48,90,0,++now));
 hello.kind=RF_ULR_HELLO_ACK;assert(!rf_ulr_encode(&hello,ack,48));
 assert(!rf_ulr_ack(&session,7,RF_ULR_HOST_IPV4,5141,5141,ack,48,++now));
 for(unsigned i=0;i<16;i++){
  uint64_t address=0x3d7e000+4*i;
  assert(!rf_ulr_marker(&session,address,RF_ULR_READ32,0,++now,pending));
  assert(!rf_ulr_tx_completed(&session,pending,48,90,0,++now));
  struct rf_ulr_message message;assert(!rf_ulr_decode(pending,48,&message));
  message.kind++;assert(!rf_ulr_encode(&message,ack,48));
  assert(!rf_ulr_ack(&session,7,RF_ULR_HOST_IPV4,5141,5141,ack,48,++now));
  assert(!rf_ulr_take_marker(&session,address,RF_ULR_READ32,0,++now));
  assert(rf_ulr_take_marker(&session,address,RF_ULR_READ32,0,++now)==EAGAIN);
 }
 assert(rf_ulr_marker(&session,0x3d7e000,RF_ULR_READ32,0,++now,pending)==E2BIG);
 return 0;
}
'''


def buffer(data=b''):
    return C.create_string_buffer(data, max(len(data),48))


def udp_log(payload):
    wire=ready.WIRE
    udp=struct.pack('!4H',12345,5140,len(payload)+8,0)+payload
    checksum=wire.checksum(wire.PHONE_IP+wire.HOST_IP+struct.pack('!BBH',0,17,len(udp))+udp) or 0xffff
    udp=udp[:6]+struct.pack('!H',checksum)+udp[8:]
    return wire.ethernet(wire.HOST_MAC,wire.PHONE_MAC,0x800,wire.ipv4(wire.PHONE_IP,wire.HOST_IP,17,udp))


def arp_reply():
    wire=ready.WIRE
    payload=struct.pack('!HHBBH',1,0x800,6,4,2)+wire.PHONE_MAC+wire.PHONE_IP+wire.HOST_MAC+wire.HOST_IP
    return wire.ethernet(wire.HOST_MAC,wire.PHONE_MAC,0x806,payload)


def echo_reply():
    wire=ready.WIRE
    return wire.ethernet(wire.HOST_MAC,wire.PHONE_MAC,0x800,
                         wire.ipv4(wire.PHONE_IP,wire.HOST_IP,1,wire.icmp_echo(BOOT,reply=True)))


class USBLogReadyCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which('cc')
        if not compiler:raise unittest.SkipTest('host C compiler required')
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.directory=Path(cls.temp.name);wrapper=cls.directory/'wrapper.c';wrapper.write_text(WRAPPER)
        library=cls.directory/'ready.so'
        result=subprocess.run([compiler,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                               '-I',str(HERE),str(HERE/'usb-log-ready.c'),str(wrapper),'-o',str(library)],
                              capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        cls.lib=C.CDLL(str(library))
        cls.lib.begin.argtypes=[C.c_uint64,C.c_uint64,C.c_uint,C.c_uint64,C.c_uint64,C.c_void_p]
        cls.lib.tx.argtypes=[C.c_void_p,C.c_size_t,C.c_uint,C.c_int,C.c_uint64]
        cls.lib.ack.argtypes=[C.c_void_p,C.c_size_t,C.c_uint64,C.c_uint,C.c_uint32,C.c_uint,C.c_uint]
        cls.lib.marker.argtypes=[C.c_uint64,C.c_uint,C.c_uint,C.c_uint64,C.c_void_p]
        cls.lib.take.argtypes=[C.c_uint64,C.c_uint,C.c_uint,C.c_uint64]
        cls.lib.stat.argtypes=[C.c_uint];cls.lib.stat.restype=C.c_uint64
        cls.lib.poll.argtypes=cls.lib.listener.argtypes=[C.c_uint64]
        cls.lib.listener.restype=C.c_bool
        cls.lib.codec.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t]

    def begin(self,now=0,end=LEASE):
        self.lib.reset();out=buffer()
        self.assertEqual(self.lib.begin(NONCE,COOKIE,7,now,end,out),0)
        return out.raw[:48]

    def tx(self,payload,now=1,frame_bytes=90,error=0):
        return self.lib.tx(buffer(payload),len(payload),frame_bytes,error,now)

    def ack(self,payload,now=2,interface=7,ip=0xc0a80701,source=5141,target=5141):
        return self.lib.ack(buffer(payload),len(payload),now,interface,ip,source,target)

    def listener(self):
        hello=self.begin();self.assertEqual(self.tx(hello),0)
        self.assertEqual(self.ack(ready.acknowledge(ready.decode(hello)).encode()),0)
        self.assertTrue(self.lib.listener(3))

    def test_codec_is_canonical_and_matches_python_for_all_kinds(self):
        for kind in range(1,5):
            message=ready.Message(kind,1 if kind<=2 else 2,NONCE,COOKIE,
                                  0 if kind<=2 else 0x3d7e000,0 if kind<=2 else ready.WRITE32,
                                  0 if kind<=2 else 0xa062f00d)
            payload=message.encode();out=buffer(b'X'*64)
            self.assertEqual(self.lib.codec(buffer(payload),48,out,64),0)
            self.assertEqual(out.raw[:48],payload)
            self.assertEqual(out.raw[48:],b'X'*16)
            self.assertEqual(ready.decode(payload),message)
        payload=ready.Message(ready.HELLO,1,NONCE,COOKIE).encode()
        for bad in (payload[:-1],payload+b'\0',b'X'+payload[1:],bytes(48)):
            self.assertEqual(self.lib.codec(buffer(bad),len(bad),buffer(),48),errno.EBADMSG)
            with self.assertRaises(ValueError):ready.decode(bad)
        out=buffer(b'X'*48)
        self.assertEqual(self.lib.codec(buffer(payload),48,out,47),errno.EINVAL)
        self.assertEqual(out.raw,b'X'*48)

    def test_host_ack_and_queued_tx_do_not_replace_a_completed_dwc3_receipt(self):
        hello=self.begin();ack=ready.acknowledge(ready.decode(hello)).encode()
        self.assertEqual(self.ack(ack,1),errno.EAGAIN)
        self.assertFalse(self.lib.listener(1))
        self.assertEqual(self.lib.marker(0x171004,ready.READ32,0,1,buffer()),errno.EBUSY)
        self.assertEqual(self.tx(hello,2),0)
        self.assertEqual(self.ack(ack,3),0)
        self.assertTrue(self.lib.listener(4))
        self.assertEqual(self.ack(ack,4),errno.EALREADY)
        self.assertEqual(self.lib.begin(NONCE,COOKIE,7,5,LEASE,buffer()),errno.EBUSY)

    def test_tx_failure_short_frame_or_wrong_packet_is_sticky(self):
        for frame_bytes,error in ((89,0),(91,0),(0,0),(90,errno.EIO)):
            hello=self.begin()
            self.assertEqual(self.tx(hello,frame_bytes=frame_bytes,error=error),errno.EIO)
            self.assertFalse(self.lib.listener(2))
        hello=self.begin();wrong=ready.Message(ready.HELLO,1,NONCE+1,COOKIE).encode()
        self.assertEqual(self.tx(wrong),errno.EPROTO)
        self.assertEqual(self.tx(hello,2),errno.EPROTO)

    def test_wrong_peer_nonce_cookie_and_replay_never_confirm(self):
        for kwargs in (dict(interface=8),dict(ip=0xc0a80703),dict(source=1234)):
            hello=self.begin();self.tx(hello)
            self.assertEqual(self.ack(ready.acknowledge(ready.decode(hello)).encode(),**kwargs),errno.EBADMSG)
            self.assertFalse(self.lib.listener(3))
        for nonce,cookie in ((NONCE+1,COOKIE),(NONCE,COOKIE+1)):
            hello=self.begin();self.tx(hello)
            bad=ready.Message(ready.HELLO_ACK,1,nonce,cookie).encode()
            self.assertEqual(self.ack(bad),errno.EBADMSG)
            self.assertFalse(self.lib.listener(3))
        hello=self.begin();self.tx(hello)
        for index in range(16):
            self.assertEqual(self.ack(b'bad',2+index),errno.EBADMSG)
        self.assertEqual(self.lib.stat(0),7)

    def test_unrelated_legacy_udp_does_not_change_state_or_deadlines(self):
        self.begin();before=[self.lib.stat(i) for i in range(8)]
        self.assertEqual(self.ack(b'ordinary log',2**64-1,target=5140),errno.ENOMSG)
        self.assertEqual([self.lib.stat(i) for i in range(8)],before)

    def test_exact_marker_requires_receipt_ack_and_one_consumption(self):
        self.listener();out=buffer()
        self.assertEqual(self.lib.marker(0x3d7e000,ready.WRITE32,1,10,out),0)
        payload=out.raw[:48];ack=ready.acknowledge(ready.decode(payload)).encode()
        self.assertEqual(self.lib.take(0x3d7e000,ready.WRITE32,1,11),errno.EAGAIN)
        self.assertEqual(self.ack(ack,12),errno.EAGAIN)
        self.assertEqual(self.tx(payload,13),0)
        stale=ready.Message(ready.HELLO_ACK,1,NONCE,COOKIE).encode()
        self.assertEqual(self.ack(stale,14),errno.EBADMSG)
        self.assertEqual(self.ack(ack,15),0)
        self.assertEqual(self.lib.take(0x3d7e004,ready.WRITE32,1,16),errno.EINVAL)
        self.assertEqual(self.lib.take(0x3d7e000,ready.WRITE32,1,17),0)
        self.assertEqual(self.lib.take(0x3d7e000,ready.WRITE32,1,18),errno.EAGAIN)

    def test_deadlines_monotonic_time_overflow_and_marker_budget(self):
        self.begin();self.assertEqual(self.lib.poll(10_000_000_000),errno.ETIMEDOUT)
        self.listener();out=buffer()
        self.assertEqual(self.lib.marker(0x171004,ready.READ32,0,10,out),0)
        self.assertEqual(self.lib.stat(5),500_000_010)
        self.assertEqual(self.lib.poll(500_000_010),errno.ETIMEDOUT)
        self.begin(2**64-1000,2**64-1)
        self.assertEqual(self.lib.stat(5),2**64-1)
        self.assertEqual(self.lib.poll(2**64-1),errno.ETIMEDOUT)
        self.listener();self.assertEqual(self.lib.poll(2),errno.EINVAL)
        self.listener()
        for index in range(16):
            at=10+index*4
            self.assertEqual(self.lib.marker(0x171004,ready.READ32,0,at,out),0)
            payload=out.raw[:48];self.assertEqual(self.tx(payload,at+1),0)
            self.assertEqual(self.ack(ready.acknowledge(ready.decode(payload)).encode(),at+2),0)
            self.assertEqual(self.lib.take(0x171004,ready.READ32,0,at+3),0)
        self.assertEqual(self.lib.marker(0x171004,ready.READ32,0,100,out),errno.E2BIG)

    def test_sanitized_codec_and_complete_sixteen_marker_lifecycle(self):
        source=self.directory/'sanitize.c';source.write_text(SANITIZER);executable=self.directory/'sanitize'
        result=subprocess.run([shutil.which('cc') or 'cc','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
                               '-fsanitize=address,undefined','-fno-sanitize-recover=undefined',
                               '-fno-omit-frame-pointer','-I',str(HERE),str(HERE/'usb-log-ready.c'),
                               str(source),'-o',str(executable)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([str(executable)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)


class USBLogReadyHostTests(unittest.TestCase):
    def warm(self,host=None):
        records=[]
        host=host or ready.HostReadyProtocol(BOOT,records.append)
        hello=ready.Message(ready.HELLO,1,NONCE,COOKIE)
        self.assertEqual(host.feed(ready.frame(hello)),[])
        offered=host.feed(arp_reply())
        self.assertEqual(offered,[host.wire.echo_request()])
        host.echo_transmitted(offered[0])
        self.assertEqual(host.feed(echo_reply()),[])
        replies=host.feed(udp_log(b'REDFIN BOOT ID: '+BOOT.encode()+b'\n'))
        self.assertEqual(replies,[ready.frame(ready.acknowledge(hello),reply=True)])
        return host,records

    def test_arp_injected_nonce_ping_and_fresh_log_all_precede_record_and_ack(self):
        host,records=self.warm()
        self.assertEqual(len(records),1)
        self.assertEqual(host.wire.log_freshness,'matched')
        self.assertTrue(host.echo_sent and host.wire.echo_seen and host.wire.arp_seen)
        self.assertEqual(host.feed(udp_log(b'normal log traffic\n')),[])
        self.assertTrue(host.wire.log.endswith(b'normal log traffic\n'))

    def test_queued_or_unsolicited_echo_cannot_make_listener_ready(self):
        records=[];host=ready.HostReadyProtocol(BOOT,records.append)
        hello=ready.Message(ready.HELLO,1,NONCE,COOKIE)
        host.feed(ready.frame(hello));offered=host.feed(arp_reply())
        self.assertEqual(host.feed(echo_reply()),[])
        self.assertEqual(host.feed(udp_log(b'REDFIN BOOT ID: '+BOOT.encode()+b'\n')),[])
        self.assertEqual(records,[])
        host.echo_transmitted(offered[0])
        self.assertEqual(host.feed(echo_reply()),[ready.frame(ready.acknowledge(hello),reply=True)])

    def test_marker_record_precedes_ack_and_duplicate_replies_are_bounded(self):
        host,records=self.warm();marker=ready.Message(ready.MARKER,2,NONCE,COOKIE,0x171004,ready.READ32)
        packet=ready.frame(marker);expected=ready.frame(ready.acknowledge(marker),reply=True)
        self.assertEqual(host.feed(packet),[expected]);self.assertEqual(records[-1],marker)
        self.assertEqual(host.feed(packet),[expected]);self.assertEqual(host.feed(packet),[expected])
        self.assertEqual(host.feed(packet),[]);self.assertEqual(len(records),2)
        stale=ready.Message(ready.MARKER,4,NONCE,COOKIE,0x171004,ready.READ32)
        self.assertEqual(host.feed(ready.frame(stale)),[])
        self.assertEqual(len(records),2)

    def test_wrong_frame_checksum_cookie_nonce_or_recorder_failure_gives_no_ack(self):
        host,records=self.warm();marker=ready.Message(ready.MARKER,2,NONCE,COOKIE,0x171004,ready.READ32)
        packet=ready.frame(marker)
        corrupt=[]
        for offset in (0,6,24,40,48):
            bad=bytearray(packet);bad[offset]^=1;corrupt.append(bytes(bad))
        corrupt.extend((packet[:-1],packet+b'\0',ready.frame(ready.Message(ready.MARKER,2,NONCE+1,COOKIE,0x171004,ready.READ32)),
                        ready.frame(ready.Message(ready.MARKER,2,NONCE,COOKIE+1,0x171004,ready.READ32))))
        for bad in corrupt:self.assertEqual(host.feed(bad),[])
        self.assertEqual(len(records),1)
        def failed_record(message):raise OSError('private output unavailable')
        host.record=failed_record
        with self.assertRaises(OSError):host.feed(packet)
        self.assertTrue(host.failed);self.assertEqual(host.feed(packet),[])

    def test_duplicate_or_wrong_boot_log_revokes_further_acks(self):
        host,records=self.warm()
        self.assertEqual(host.feed(udp_log(b'REDFIN BOOT ID: '+BOOT.encode()+b'\n')),[])
        self.assertTrue(host.failed)
        marker=ready.Message(ready.MARKER,2,NONCE,COOKIE,0x171004,ready.READ32)
        self.assertEqual(host.feed(ready.frame(marker)),[])
        self.assertEqual(len(records),1)


if __name__ == '__main__':
    unittest.main()
