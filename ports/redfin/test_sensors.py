"""Exercise actual bounded SSC codecs, registry admission and sample lifecycle."""
import ctypes as C
from fractions import Fraction
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest

from sensor_assets import field, varint, registry_requests

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include "ssc-client.h"
static struct rf_ssc_client session;
static struct rf_sensor_assets assets;
static struct rf_ssc_ops operations;
static uint8_t fragment[936],sent[2048];
static unsigned sent_bytes,published,withdrawn,live;
static uint64_t clock_ns;
static int32_t x;
static int check(void *p){return p==&session&&live?0:-1;}
static int send(void *p,const uint8_t *data,uint32_t n){if(check(p)||n>sizeof(sent))return -1;memcpy(sent,data,n);sent_bytes=n;return 0;}
static uint64_t now(void *p){(void)p;return clock_ns;}
static void sample(void *p,unsigned kind,const struct rf_ssc_sensor *s){(void)p;(void)kind;++published;x=s->fixed[0];}
static void withdraw(void *p,unsigned kind){(void)p;(void)kind;++withdrawn;}
static void event(void *p,const char *why,unsigned a,unsigned b){(void)p;(void)why;(void)a;(void)b;}
void reset(const uint8_t *data,unsigned n){memset(&session,0,sizeof(session));memset(&assets,0,sizeof(assets));
 sent_bytes=published=withdrawn=0;live=1;x=0;clock_ns=UINT64_C(100000000000);
 memcpy(fragment,data,n);strcpy(assets.file[0].name,"reg/000");assets.file[0].data=fragment;assets.file[0].bytes=n;assets.count=1;
 operations=(struct rf_ssc_ops){&session,check,send,now,sample,withdraw,event};}
int begin(void){return rf_ssc_begin(&session,&operations,&assets);}
int poll(void){return rf_ssc_poll(&session);}
void advance(unsigned seconds){clock_ns+=(uint64_t)seconds*1000000000u;}
unsigned sent_byte(unsigned i){return i<sent_bytes?sent[i]:0;}
int receive(const uint8_t *data,unsigned n){return rf_ssc_receive(&session,data,n);}
unsigned metric(unsigned i){unsigned v[]={session.pending,session.failed,published,withdrawn,session.registry_verified,session.phase,sent_bytes,session.sensor[0].configured};return i<8?v[i]:0;}
int32_t value(void){return x;}
int convert(uint32_t bits,uint32_t num,uint32_t den,int32_t *out){return rf_sns_float_fixed(bits,num,den,out);}
int contains(const uint8_t *a,unsigned an,const uint8_t *e,unsigned en){return rf_sns_registry_contains((struct rf_sns_slice){a,an},(struct rf_sns_slice){e,en});}
'''


def uid(low, high=3):
    return b'\x09' + struct.pack('<Q', low) + b'\x11' + struct.pack('<Q', high)


WELL = uid(0xabababababababab, 0xabababababababab)
REG = uid(101)
ACCEL = uid(102)


def indication(source, message, body, ticks=1920000000):
    event = b'\x0d' + struct.pack('<I', message) + b'\x11' + struct.pack('<Q', ticks) + field(3, body)
    payload = field(1, source) + field(2, event)
    tlv = b'\x01\x08\x00' + struct.pack('<Q', 11)
    tlv += b'\x02' + struct.pack('<HH', len(payload) + 2, len(payload)) + payload
    return b'\x04\x00\x00\x22\x00' + struct.pack('<H', len(tlv)) + tlv


def group(name='native.config', value=7, version=1):
    item = field(1, b'actual') + b'\x15' + struct.pack('<I', version) + b'\x69' + struct.pack('<q', value)
    return field(1, name.encode()) + field(2, field(3, item))


class SensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('native host C compiler required')
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        p = Path(cls.temp.name); (p / 'model.c').write_text(HARNESS)
        built = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), str(p / 'model.c'), str(HERE / 'ssc-client.c'), str(HERE / 'ssc-protocol.c'),
            '-o', str(p / 'model.so')], capture_output=True, text=True)
        if built.returncode:
            raise RuntimeError(built.stderr)
        cls.lib = C.CDLL(str(p / 'model.so'))
        cls.lib.receive.argtypes = [C.c_void_p, C.c_uint]
        cls.lib.reset.argtypes = [C.c_void_p, C.c_uint]
        cls.lib.value.restype = C.c_int32
        cls.lib.convert.argtypes = [C.c_uint32, C.c_uint32, C.c_uint32, C.POINTER(C.c_int32)]

    def setUp(self):
        body = group(); self.lib.reset(body, len(body))

    def receive(self, data, ok=True):
        result = self.lib.receive(data, len(data))
        self.assertEqual(result == 0, ok)

    def ack(self):
        transaction = self.lib.metric(0); self.assertTrue(transaction)
        self.receive(b'\x02' + struct.pack('<HHH', transaction, 0x20, 7) + b'\x02\x04\x00\x00\x00\x00\x00')

    def seed(self, actual=None):
        self.assertEqual(self.lib.begin(), 0); self.ack()
        self.receive(indication(WELL, 768, field(1, b'registry') + field(2, REG)))
        self.assertEqual(self.lib.poll(), 0); self.ack()
        self.assertEqual(self.lib.poll(), 0); self.ack()
        self.receive(indication(REG, 514, actual or group()), ok=actual is None)
        if actual is None:
            self.assertEqual(self.lib.poll(), 0)
            self.assertEqual(self.lib.metric(4), 1)

    def configured(self):
        self.seed()
        types = ['accel','gyro','mag','ambient_light','proximity','pressure','sensor_temperature','gravity',
                 'linear_accel','rotation_vector','game_rv','geomag_rv']
        for index, name in enumerate(types):
            self.assertEqual(self.lib.poll(), 0); self.ack()
            self.receive(indication(WELL, 768, field(1, name.encode()) + (field(2, ACCEL) if index == 0 else b'')))
        self.assertEqual(self.lib.poll(), 0); self.ack()
        def attribute(number, data):
            return field(1, b'\x08' + varint(number) + field(2, field(1, data)))
        attributes = attribute(0, field(2, b'actual accelerometer')) + attribute(1, field(2, b'actual vendor'))
        attributes += attribute(2, field(2, b'accel')) + attribute(3, b'\x28\x01')
        attributes += attribute(16, b'\x21' + struct.pack('<q', 0)) + attribute(6, b'\x1d' + struct.pack('<f', 50))
        self.receive(indication(ACCEL, 128, attributes))
        self.assertEqual(self.lib.poll(), 0); self.ack()
        self.assertEqual(self.lib.metric(7), 1)
        self.assertEqual(self.lib.metric(2), 0, 'configuration does not fabricate a sample')

    def test_real_protocol_path_requires_registry_readback_and_attributes_before_sample(self):
        self.configured()
        body = field(1, struct.pack('<3f', 9.80665, 0, -9.80665)) + b'\x10\x03'
        self.receive(indication(ACCEL, 1025, body))
        self.assertEqual((self.lib.metric(2), self.lib.value()), (1, 65536))
        self.receive(indication(ACCEL, 1025, body), ok=False)
        self.assertEqual(self.lib.metric(3), 1, 'repeated timestamp revokes the published source')

    def test_native_calibration_mismatch_stops_before_sensor_publication(self):
        self.seed(group(value=8)); self.assertEqual(self.lib.metric(1), 1)
        self.assertEqual(self.lib.metric(2), 0)

    def test_native_qmi_failure_is_not_a_grant_or_a_sample(self):
        self.assertEqual(self.lib.begin(), 0); transaction = self.lib.metric(0)
        self.receive(b'\x02' + struct.pack('<HHH', transaction, 0x20, 7) + b'\x02\x04\x00\x01\x00\x03\x00', ok=False)
        self.assertEqual((self.lib.metric(1), self.lib.metric(2)), (1, 0))

    def test_empty_native_registry_update_preserves_subscription_and_later_discovery(self):
        self.assertEqual(self.lib.begin(), 0)
        sent=bytes(self.lib.sent_byte(i) for i in range(self.lib.metric(6)))
        self.assertIn(field(1,b'registry')+b'\x10\x01\x18\x00',sent)
        self.receive(indication(WELL,768,field(1,b'registry')))
        self.ack();self.lib.advance(12)
        self.assertEqual(self.lib.poll(),0)
        self.assertEqual((self.lib.metric(0),self.lib.metric(1),self.lib.metric(2)),(0,0,0))
        self.receive(indication(WELL,768,field(1,b'registry')+field(2,REG)))
        self.assertEqual(self.lib.poll(),0)
        self.assertTrue(self.lib.metric(0),'only the real later SUID permits registry writes')

    def test_empty_registry_updates_cannot_extend_the_bounded_startup_deadline(self):
        self.assertEqual(self.lib.begin(),0);self.ack()
        for _ in range(3):
            self.lib.advance(10)
            self.receive(indication(WELL,768,field(1,b'registry')))
            self.assertEqual(self.lib.poll(),0)
        self.lib.advance(1)
        self.assertNotEqual(self.lib.poll(),0)
        self.assertEqual((self.lib.metric(1),self.lib.metric(2)),(1,0))

    def test_registry_subset_accepts_order_extras_and_newer_version_but_not_changed_value(self):
        e = group(); a = group(version=2)
        self.assertEqual(self.lib.contains(a, len(a), e, len(e)), 0)
        for a in [group(value=8), group(name='other'), group(version=0), group()[:-1]]:
            self.assertNotEqual(self.lib.contains(a, len(a), e, len(e)), 0)

    def test_truncated_or_oversized_reports_never_publish(self):
        packet = indication(WELL, 768, field(1, b'registry') + field(2, REG))
        for length in range(len(packet)):
            self.setUp(); self.lib.begin(); self.receive(packet[:length], ok=False)
            self.assertEqual(self.lib.metric(2), 0)

    def test_integer_only_float_conversion_matches_exact_rational_units(self):
        values = [0.0, -0.0, 9.80665, -9.80665, 123.125, -32768.0, 1e-35]
        rng = random.Random(17); values += [rng.uniform(-200, 200) for _ in range(500)]
        for value in values:
            encoded = struct.pack('<f', value); bits, = struct.unpack('<I', encoded)
            native, = struct.unpack('<f', encoded)
            for num, den in [(1,1),(100000,980665),(1,10),(1,65536)]:
                out = C.c_int32(); error = self.lib.convert(bits, num, den, C.byref(out))
                exact = Fraction(native) * 65536 * num / den
                magnitude = abs(exact); rounded = (magnitude.numerator * 2 + magnitude.denominator) // (2 * magnitude.denominator)
                wanted = -rounded if exact < 0 else rounded
                if -(1 << 31) <= wanted < 1 << 31:
                    self.assertEqual((error, out.value), (0, wanted))
                else:
                    self.assertNotEqual(error, 0)
        for bits in [0x7f800000,0xff800000,0x7fc00001,0x7f7fffff]:
            self.assertNotEqual(self.lib.convert(bits,1,1,C.byref(C.c_int32())),0)

    def test_actual_registry_links_types_versions_and_fragmentation_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'registry').mkdir();(p/'factory_data').mkdir()
            def item(kind,data,version='2'):return dict(type=kind,data=data,version=version)
            parent={'owner':'sns','child':item('grp',''),'value':item('int','7')}
            child={'owner':'sns',**{'item'+str(i):item('str','actual'*20) for i in range(15)}}
            (p/'registry'/'root').write_text(json.dumps({'root':parent}))
            (p/'registry'/'root.child').write_text(json.dumps({'root.child':child}))
            (p/'factory_data'/'root').write_text(json.dumps({'root':{'owner':'sns','value':item('int','1')}}))
            requests, groups = registry_requests(p)
            self.assertEqual(groups,2);self.assertGreater(len(requests),2)
            self.assertTrue(all(len(data)<=936 for data in requests))
            # Every real leaf occurs in the parent tree and direct child group.
            for i in range(15):self.assertEqual(sum(field(1,('item'+str(i)).encode()) in data for data in requests),2)
            (p/'registry'/'root.child').unlink()
            with self.assertRaises(ValueError):registry_requests(p)
