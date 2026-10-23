"""Native ath10k WLAN_CFG/mission wire and ACK ordering, with no DMA APIs."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_wifi_wlfw import response, tlv

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include "wifi_qmi.h"
#include "wifi_wlfw.h"
#include "wifi_bdf.h"
#include "wifi_snoc.h"
#include "wifi_mission.h"
static struct rf_mission session;
static struct rf_snoc_snapshot snapshot;
static struct rf_wlfw_cap cap;
static uint8_t sent[2][600];static uint32_t lengths[2];
static unsigned checks,sends,fail_check,fail_send,violations;
static int check(void *ctx){++checks;return ctx!=&session || (fail_check && checks>=fail_check) ? -1 : 0;}
static int send_packet(void *ctx,const uint8_t *data,uint32_t bytes){
 ++sends;if(ctx!=&session || sends>2 || bytes>600){violations++;return -1;}
 memcpy(sent[sends-1],data,bytes);lengths[sends-1]=bytes;
 return fail_send && sends>=fail_send ? -1 : 0;
}
static const struct rf_mission_ops ops={&session,check,send_packet};
void reset(unsigned issue){
 memset(&session,0,sizeof(session));memset(&snapshot,0,sizeof(snapshot));memset(&cap,0,sizeof(cap));
 memset(sent,0,sizeof(sent));memset(lengths,0,sizeof(lengths));checks=sends=fail_check=fail_send=violations=0;
 snapshot.stage=4;snapshot.stable=true;snapshot.control=0x400;
 cap.valid=13;cap.chip=0x4320;cap.family=0x4001;cap.soc=0x400b0000;cap.firmware=0x33197fff;
 if(issue==1)cap.chip^=1;
 if(issue==2)cap.valid=5;
 if(issue==3)snapshot.stable=false;
 if(issue==4)snapshot.stage=3;
 if(issue==5)snapshot.error=1;
 if(issue==6)snapshot.fault=1;
 if(issue==7)snapshot.malformed_routes=1;
 if(issue==8)snapshot.wlan_matches[0]=1;
 if(issue==9)snapshot.wlan_matches[1]=1;
 if(issue==10)snapshot.control=0x401;
 if(issue==11)snapshot.control=0;
}
void failure(unsigned which,unsigned at){if(which==0)fail_check=at;else fail_send=at;}
int begin(void){return rf_mission_begin(&session,&ops,&cap,&snapshot);}
int receive(const uint8_t *data,uint32_t bytes){return rf_mission_receive(&session,&ops,data,bytes);}
uint32_t metric(unsigned which){
 uint32_t values[]={checks,sends,violations,session.stage,session.poisoned,session.waiting,
 session.transaction,session.requests,session.responses,session.ignored,session.result,session.error};
 return which<12 ? values[which] : 0;
}
uint32_t packet(unsigned index,uint8_t *out){if(index>=sends || index>=2)return 0;memcpy(out,sent[index],lengths[index]);return lengths[index];}
'''


def elements(data):
    result = {}
    at = 7
    while at < len(data):
        kind, length = struct.unpack_from('<BH', data, at); at += 3
        assert kind not in result and length <= len(data) - at
        result[kind] = data[at:at + length]; at += length
    assert at == len(data)
    return result


class MissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'): raise unittest.SkipTest('host C compiler unavailable')
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name); source = directory / 'mission.c'; library = directory / 'mission.so'
        source.write_text(HARNESS)
        result = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), str(source), '-o', str(library)], capture_output=True, text=True)
        if result.returncode: raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library)); cls.lib.receive.argtypes = [C.c_void_p, C.c_uint32]
        cls.lib.metric.restype = cls.lib.packet.restype = C.c_uint32
        cls.lib.packet.argtypes = [C.c_uint, C.c_void_p]

    def setUp(self): self.lib.reset(0)

    def packet(self, index):
        out = C.create_string_buffer(600); size = self.lib.packet(index, out)
        return out.raw[:size]

    def receive(self, message, transaction, result=0, error=0, extra=b''):
        data = response(message, transaction, extra, result=result, error=error)
        return self.lib.receive(data, len(data))

    def test_exact_native_arrays_and_mission_follow_only_successful_config_ack(self):
        self.assertEqual(self.lib.begin(), 0)
        cfg = self.packet(0)
        self.assertEqual(struct.unpack('<BHHH', cfg[:7]), (0, 6, 0x23, 552))
        e = elements(cfg); self.assertEqual(set(e), {0x11, 0x12, 0x13})
        self.assertEqual([e[k][0] for k in (0x11, 0x12, 0x13)], [12, 21, 12])
        target = list(struct.iter_unpack('<5I', e[0x11][1:])); service = list(struct.iter_unpack('<3I', e[0x12][1:]))
        shadow = list(struct.iter_unpack('<2H', e[0x13][1:]))
        self.assertEqual([x[0] for x in target], list(range(12)))
        self.assertEqual(target[0], (0, 2, 32, 2048, 0)); self.assertEqual(target[4], (4, 2, 256, 256, 8))
        self.assertEqual(target[6], (6, 3, 32, 16384, 0)); self.assertEqual(target[7], (7, 4, 0, 0, 8))
        self.assertEqual(service[10:12], [(1, 2, 0), (1, 1, 2)])
        self.assertEqual(service[14:16], [(0x300, 2, 4), (0x300, 1, 1)])
        self.assertEqual(service[-1], (0, 0, 0))
        self.assertEqual(shadow, [(0, 0x3c), (3, 0x3c), (4, 0x3c), (5, 0x3c), (7, 0x3c), (1, 0x40),
            (2, 0x40), (7, 0x40), (8, 0x40), (9, 0x40), (10, 0x40), (11, 0x40)])
        self.assertEqual(self.lib.metric(1), 1); self.assertEqual(self.lib.metric(3), 1)
        self.assertEqual(self.receive(0x23, 6), 0)
        mode = self.packet(1)
        self.assertEqual(struct.unpack('<BHHH', mode[:7]), (0, 7, 0x22, 11))
        self.assertEqual(elements(mode), {1: bytes(4), 0x10: b'\0'})
        self.assertEqual(self.lib.metric(3), 2)
        self.assertEqual(self.receive(0x22, 7), 0)
        self.assertEqual([self.lib.metric(i) for i in (1, 2, 3, 5, 7, 8)], [2, 0, 3, 0, 2, 2])

    def test_incomplete_snapshot_foreign_wlan_routes_or_wrong_hardware_never_send_config(self):
        for issue in range(1, 12):
            self.lib.reset(issue); self.assertNotEqual(self.lib.begin(), 0)
            self.assertEqual(self.lib.metric(1), 0)

    def test_one_attempt_and_foreign_duplicate_or_late_replies_cannot_advance(self):
        self.assertEqual(self.lib.begin(), 0); self.assertNotEqual(self.lib.begin(), 0)
        for message, transaction in ((0x23, 5), (0x22, 6), (0x24, 6)):
            self.assertEqual(self.receive(message, transaction), 1)
            self.assertEqual(self.lib.metric(1), 1)
        self.assertEqual(self.receive(0x23, 6), 0)
        self.assertEqual(self.receive(0x23, 6), 1); self.assertEqual(self.lib.metric(1), 2)
        self.assertEqual(self.receive(0x22, 7), 0)
        self.assertEqual(self.receive(0x22, 7), 1); self.assertEqual(self.lib.metric(1), 2)

    def test_qmi_rejection_at_either_stage_does_not_claim_mission_or_retry(self):
        for which in (0, 1):
            self.lib.reset(0); self.assertEqual(self.lib.begin(), 0)
            if which: self.assertEqual(self.receive(0x23, 6), 0)
            self.assertEqual(self.receive(0x22 if which else 0x23, 7 if which else 6, result=1, error=42), 0)
            self.assertEqual([self.lib.metric(i) for i in (3, 10, 11)], [4, 1, 42])
            self.assertEqual(self.lib.metric(1), 2 if which else 1)

    def test_every_owner_check_and_send_uncertainty_stops_without_retry(self):
        self.lib.begin(); self.receive(0x23, 6); self.receive(0x22, 7)
        checks = self.lib.metric(0)
        for which, count in ((0, checks), (1, 2)):
            for at in range(1, count + 1):
                self.lib.reset(0); self.lib.failure(which, at)
                self.lib.begin(); self.receive(0x23, 6); self.receive(0x22, 7)
                self.assertEqual(self.lib.metric(3), 4)
                self.assertEqual(self.lib.metric(4), 1)
                self.assertLessEqual(self.lib.metric(1), 2 if which == 0 else at)

    def test_truncated_duplicate_missing_or_inconsistent_result_is_never_an_ack(self):
        good = response(0x23, 6)
        cases = [good[:n] for n in range(len(good))]
        cases += [response(0x23, 6, tlv(2, bytes(4))), response(0x23, 6, result=0, error=1),
                  response(0x23, 6, result=2), b'\2\6\0\x23\0\0\0']
        for data in cases:
            self.lib.reset(0); self.lib.begin()
            self.assertNotEqual(self.lib.receive(data, len(data)), 0)
            self.assertEqual(self.lib.metric(1), 1); self.assertNotEqual(self.lib.metric(3), 3)


if __name__ == '__main__': unittest.main()
