"""Run actual event state, SPI session API and HID geometry/readiness helpers."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch import added_file


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + "\n"


class Geometry(C.Structure):
    _fields_ = [(key, C.c_int) for key in
                ("panel_w", "panel_h", "logical_w", "logical_h", "off_x", "off_y")]


class TouchEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cxx = shutil.which("c++")
        if not cxx:
            raise unittest.SkipTest("host C++ compiler unavailable")
        base = Path(__file__).parent
        patch = (base / "touch-events.patch").read_text()
        protocol = added_file((base / "touch.patch").read_text(), "bsd/dev/redfin_touch_protocol.h")
        events = added_file(patch, "bsd/dev/redfin_touch_events.h")
        geometry = added_file(patch, "iokit/Kernel/arm/hid/RedfinTouchGeometry.h")
        hid_chunk = patch.split("diff --git a/iokit/Kernel/arm/hid/SweetHID.cpp ", 1)[1]
        additions = "\n".join(line[1:] for line in hid_chunk.splitlines()
                              if line.startswith(("+", " ")) and not line.startswith("+++"))
        profile = additions.split("/* REDFIN_HID_PROFILE_BEGIN */", 1)[1].split(
            "/* REDFIN_HID_PROFILE_END */", 1)[0]
        ready = function(additions, "bool\nSweetHIDTouch::redfinConsumerReady(void)")
        ready += function(additions, 'extern "C" bool\nsweet_hid_redfin_touch_ready(void)')
        touch = function(additions, "void\nSweetHIDTouch::touch(")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        (directory / "bsd/dev").mkdir(parents=True)
        old_spi = added_file((base / "touch-spi.patch").read_text(), "bsd/dev/redfin_touch_spi.c")
        (directory / "bsd/dev/redfin_touch_spi.c").write_text(old_spi)
        subprocess.run(["git", "apply", "--include=bsd/dev/redfin_touch_spi.c", str(base.resolve() / "touch-events.patch")],
                       cwd=directory, check=True)
        spi = (directory / "bsd/dev/redfin_touch_spi.c").read_text()
        apis = "\n".join(function(spi, signature) for signature in (
            "int\nredfin_touch_spi_probe(", "bool\nredfin_touch_spi_identity_ready(",
            "void\nredfin_touch_spi_events_close(", "int\nredfin_touch_spi_events_begin(",
            "int\nredfin_touch_spi_event_read("))
        stub = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#define kSuccess 0
#define printf fake_printf
static int fake_printf(const char *f,...) {(void)f;return 0;}
typedef void *DTEntry;
typedef uintptr_t vm_offset_t;
static unsigned boot_mode=2,event_enable=1,fb_enable=1,property_fault,api_fault;
static unsigned prepare_calls,read_calls,close_writes,last_reg,last_count;
static const uint32_t one=1,pw=1080,ph=2340,cw=1125,ch=2436,wrong=2400,size[]={1080,2340};
static int PE_parse_boot_argn(const char *name,void *out,int bytes){
    (void)bytes;*(uint32_t *)out=!strcmp(name,"redfintouch") ? boot_mode :
        !strcmp(name,"redfintouchevents") ? event_enable : fb_enable;return 1;
}
static int SecureDTLookupEntry(void *root,const char *name,DTEntry *out){
    (void)root;*out=(void *)(uintptr_t)(!strcmp(name,"/arm-io/disp0") ? 1 : 2);return property_fault==1 ? -1 : 0;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *n){
    (void)node;*n=4;
    if(!strcmp(name,"compatible")){*out="redfin,sec-touch";*n=sizeof("redfin,sec-touch");}
    else if(!strcmp(name,"redfin,abl-copy-only"))*out=&one;
    else if(!strcmp(name,"width"))*out=&pw;
    else if(!strcmp(name,"height"))*out=&ph;
    else if(!strcmp(name,"canvas-width"))*out=&cw;
    else if(!strcmp(name,"canvas-height"))*out=&ch;
    else if(!strcmp(name,"touch-size")){*out=size;*n=8;}
    else return -1;
    if(property_fault==2 && !strcmp(name,"compatible"))*out=NULL;
    if(property_fault==3 && !strcmp(name,"height"))*out=&wrong;
    if(property_fault==4 && !strcmp(name,"touch-size"))(*n)--;
    if(property_fault==5 && !strcmp(name,"canvas-height"))*out=&wrong;
    return 0;
}
struct redfin_spi {vm_offset_t se;unsigned tx_depth,rx_depth;bool dead,command_owned;};
static bool redfin_spi_attempted,redfin_spi_event_open;
static vm_offset_t redfin_spi_verified_se;
static unsigned redfin_spi_verified_hz;
static struct redfin_spi redfin_spi_event_context;
bool redfin_touch_spi_identity_ready(void);
void redfin_touch_spi_events_close(void);
static int redfin_spi_prepare(struct redfin_spi *s){(void)s;prepare_calls++;return api_fault==3 ? EBUSY : 0;}
static int redfin_spi_read(struct redfin_spi *s,unsigned reg,unsigned count,uint8_t *out){
    (void)s;read_calls++;last_reg=reg;last_count=count;
    if(api_fault==2)return EIO;
    if(!out)return EINVAL;
    memset(out,0,count);
    if(reg==0x22){const uint8_t id[]={0x53,0x45,0x37,0x91,0};memcpy(out,id,5);if(api_fault==1)out[0]^=1;}
    if(reg==0x55)out[0]=0x20;
    return 0;
}
static void redfin_spi_wr(struct redfin_spi *s,unsigned offset,uint32_t value){(void)s;(void)offset;(void)value;close_writes++;}
static int redfin_spi_failed(struct redfin_spi *s,int error){s->dead=true;return error;}
class IOHIDEventServiceClient {public:void *action;};
class FakeClients {public:unsigned n;IOHIDEventServiceClient clients[3];unsigned getCount(){return n;}
    void *getObject(unsigned i){return &clients[i];}};
static unsigned held_locks;
static void IOLockLock(void *){held_locks++;}
static void IOLockUnlock(void *){held_locks--;}
typedef int32_t IOFixed;
typedef uint32_t UInt32;
#define SWEET_TOUCH_FINGERS 10
#define SWEET_TOUCH_EDGE_PX 48
#define TRUE 1
enum {kIOHIDDigitizerTransducerTypeHand,kIOHIDDigitizerTransducerTypeFinger};
enum {kIOHIDEventFieldDigitizerCollection,kIOHIDEventFieldDigitizerIndex,
 kIOHIDEventFieldDigitizerIdentity,kIOHIDEventFieldDigitizerTouch,
 kIOHIDEventFieldDigitizerEventMask,kIOHIDEventFieldDigitizerX,
 kIOHIDEventFieldDigitizerY,kIOHIDEventFieldDigitizerRange,kIOHIDEventFieldDigitizerButtonMask};
enum {kIOHIDDigitizerEventFromEdgeTip=1,kIOHIDDigitizerEventTouch=2,
 kIOHIDDigitizerEventRange=4,kIOHIDDigitizerEventPosition=8,kIOHIDDigitizerEventIdentity=16};
static unsigned allocation_fault,dispatches,dispatch_down,dispatch_up;
static uint64_t mach_absolute_time(){return 0;}
static void IOLog(const char *,...){}
class IOHIDEvent {public:
 unsigned finger,mask,children_down,children_up;bool down;
 static IOHIDEvent *digitizerEvent(uint64_t,UInt32,unsigned,bool,int,IOFixed,IOFixed);
 void setIntegerValue(unsigned key,unsigned value){
   if(key==kIOHIDEventFieldDigitizerIndex)finger=value;
   if(key==kIOHIDEventFieldDigitizerTouch)down=value!=0;
   if(key==kIOHIDEventFieldDigitizerEventMask)mask=value;
 }
 void setFixedValue(unsigned,IOFixed){}
 void appendChild(IOHIDEvent *child){
   if(child->down)children_down|=1u<<child->finger;
   else if(child->mask&kIOHIDDigitizerEventTouch)children_up|=1u<<child->finger;
 }
 void release(){}
};
IOHIDEvent *IOHIDEvent::digitizerEvent(uint64_t,UInt32 index,unsigned type,bool down,int,IOFixed,IOFixed){
 if((allocation_fault==1 && type==kIOHIDDigitizerTransducerTypeHand) ||
    (allocation_fault==2 && type==kIOHIDDigitizerTransducerTypeFinger))return NULL;
 static IOHIDEvent events[12];IOHIDEvent *event=&events[index];*event={};event->down=down;return event;
}
class SweetHIDTouch {public:
 bool fRedfinGeometry;void *_clientLock;FakeClients *_clients;
 void *fLock;int fLogicalW,fLogicalH,fOffX,fOffY,fPanelW,fPanelH;
 bool fDown[10],fEdge[10];IOFixed fX[10],fY[10];
 bool redfinConsumerReady(void);void touch(int,bool,int,int);
 void dispatchEvent(IOHIDEvent *event){dispatches++;dispatch_down=event->children_down;dispatch_up=event->children_up;}
};
static SweetHIDTouch *gSweetTouch;
static bool gSweetRedfinTouchPublished;
'''
        harness = r'''
static struct redfin_events_state state;
static uint8_t queued[64*8];static unsigned queued_count,cursor,read60,read61,read_fault;
static unsigned emits,emitted[128][4];
static int event_read(void *,unsigned reg,unsigned count,uint8_t *out){
    if(reg==0x60)read60++;else if(reg==0x61)read61++;else return EINVAL;
    if(read_fault==reg)return EIO;
    if(reg==0x60 && cursor==queued_count){memset(out,0,count);return 0;}
    if(count%8 || cursor+count/8>queued_count)return EIO;
    memcpy(out,queued+cursor*8,count);cursor+=count/8;return 0;
}
static void emit(void *,unsigned finger,int down,unsigned x,unsigned y){
    if(emits<128){emitted[emits][0]=finger;emitted[emits][1]=(unsigned)down;emitted[emits][2]=x;emitted[emits][3]=y;}
    emits++;
}
extern "C" {
void reset_state(){memset(&state,0,sizeof(state));state.startup_reset=true;emits=read60=read61=0;}
void queue_events(const uint8_t *events,unsigned count,unsigned fault){
    memset(queued,0,sizeof(queued));if(events && count<=64)memcpy(queued,events,count*8);
    queued_count=count;cursor=0;read_fault=fault;
}
int batch(bool deliver){const struct redfin_events_ops ops={event_read,emit,NULL};return redfin_events_batch(&state,&ops,deliver);}
void release_all(){redfin_events_release_all(&state,emit,NULL);}
unsigned stat(unsigned n){const unsigned values[]={state.down,state.suppressed,state.synchronized,emits,read60,read61,state.contacts,state.releases};return n<8 ? values[n] : 0;}
unsigned emitted_value(unsigned n,unsigned field){return n<emits && n<128 && field<4 ? emitted[n][field] : 0;}
bool geometry_make(unsigned a,unsigned b,unsigned c,unsigned d,struct redfin_touch_geometry *o){return redfin_touch_geometry_make(a,b,c,d,o);}
int axis(int v,int off,int logical,int dimension){return redfin_touch_axis_normalize(redfin_touch_axis_clamp(v,dimension),off,logical);}
bool edge(int x,int y){return redfin_touch_edge(x,y,1080,2340,48);}
bool profile(unsigned fault,unsigned enabled,struct redfin_touch_geometry *o){property_fault=fault;fb_enable=enabled;return redfin_hid_profile(o);}
bool ready(bool published,bool geometry,unsigned clients,unsigned callback_mask){
    FakeClients list={};list.n=clients;
    for(unsigned i=0;i<clients && i<3;i++)list.clients[i].action=(callback_mask&(1u<<i)) ? (void *)1 : NULL;
    SweetHIDTouch service={};service.fRedfinGeometry=geometry;service._clientLock=(void *)1;
    service._clients=&list;gSweetTouch=&service;
    __atomic_store_n(&gSweetRedfinTouchPublished,published,__ATOMIC_RELEASE);
    bool result=sweet_hid_redfin_touch_ready();gSweetTouch=NULL;return result && held_locks==0;
}
int identify(unsigned fault){
    api_fault=fault;boot_mode=2;event_enable=1;redfin_spi_attempted=redfin_spi_event_open=false;
    redfin_spi_verified_se=redfin_spi_verified_hz=0;prepare_calls=read_calls=close_writes=0;
    return redfin_touch_spi_probe(1,960000,true);
}
int begin(bool mask,unsigned enabled){event_enable=enabled;return redfin_touch_spi_events_begin(mask);}
int event_api(unsigned reg,unsigned count,unsigned fault){uint8_t out[256]={0};api_fault=fault;return redfin_touch_spi_event_read(reg,count,out);}
void close_api(){redfin_touch_spi_events_close();}
bool identity_ready(){return redfin_touch_spi_identity_ready();}
unsigned api_stat(unsigned n){const unsigned values[]={prepare_calls,read_calls,close_writes,last_reg,last_count};return n<5 ? values[n] : 0;}
unsigned hid_release_test(unsigned fault){
    SweetHIDTouch service={};service.fLock=(void *)1;service.fLogicalW=1125;service.fLogicalH=2436;
    service.fOffX=20;service.fOffY=48;service.fPanelW=1080;service.fPanelH=2340;
    allocation_fault=0;dispatches=dispatch_down=dispatch_up=0;
    for(unsigned i=0;i<10;i++)service.touch(i,true,100,200);
    if(dispatch_down!=1023)return 1;
    allocation_fault=fault;
    for(unsigned i=0;i<10;i++)service.touch(i,false,100,200);
    for(unsigned i=0;i<10;i++)if(service.fDown[i])return 2;
    if(held_locks)return 3;
    if(!fault && (dispatch_down || dispatch_up!=(1u<<9)))return 4;
    allocation_fault=0;service.touch(0,true,100,200);
    if(dispatch_down!=1)return 5; /* Failed UP must not reappear in a later frame. */
    return 0;
}
}
'''
        for name, data in (("redfin_touch_protocol.h", protocol), ("redfin_touch_events.h", events),
                           ("RedfinTouchGeometry.h", geometry)):
            (directory / name).write_text(data)
        translation = stub + '#include "redfin_touch_events.h"\n#include "RedfinTouchGeometry.h"\n'
        (directory / "events.cpp").write_text(translation + profile + ready + touch + apis + harness)
        library = directory / "events.so"
        subprocess.run([cxx, "-std=c++17", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(directory / "events.cpp"), "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.queue_events.argtypes = [C.POINTER(C.c_uint8), C.c_uint, C.c_uint]
        cls.lib.batch.argtypes = [C.c_bool]
        cls.lib.geometry_make.argtypes = [C.c_uint] * 4 + [C.POINTER(Geometry)]
        cls.lib.geometry_make.restype = C.c_bool
        cls.lib.profile.argtypes = [C.c_uint, C.c_uint, C.POINTER(Geometry)]
        cls.lib.profile.restype = C.c_bool
        cls.lib.ready.argtypes = [C.c_bool, C.c_bool, C.c_uint, C.c_uint]
        cls.lib.ready.restype = C.c_bool
        cls.lib.edge.argtypes = [C.c_int] * 2
        cls.lib.edge.restype = C.c_bool
        cls.lib.begin.argtypes = [C.c_bool, C.c_uint]
        cls.lib.identity_ready.restype = C.c_bool

    def setUp(self):
        self.lib.reset_state()

    @staticmethod
    def contact(finger=0, action=1, x=100, y=200, kind=0, remaining=0):
        return bytes([(action << 6) | ((finger + 1) << 2), x >> 4, y >> 4,
                      ((x & 15) << 4) | (y & 15), 8, 6, (kind >> 2) << 6, ((kind & 3) << 6) | remaining])

    def batch(self, packets=(), deliver=True, fault=0):
        data = b"".join(packets)
        self.lib.queue_events((C.c_uint8 * len(data)).from_buffer_copy(data), len(packets), fault)
        return self.lib.batch(deliver)

    def synchronize(self):
        self.assertEqual(self.batch(deliver=False), 0)
        self.assertEqual(self.lib.stat(2), 1)

    def output(self):
        return [tuple(self.lib.emitted_value(i, field) for field in range(4))
                for i in range(self.lib.stat(3))]

    def test_startup_discards_old_contacts_until_release_then_new_gesture(self):
        boot = bytes([9, 0, 0x10, 0, 0, 0, 0, 1])
        self.assertEqual(self.batch([boot, self.contact()], deliver=False), 0)
        self.synchronize()
        self.assertEqual(self.batch([self.contact(action=2)]), 0)
        self.assertEqual(self.output(), [])
        self.assertEqual(self.batch([self.contact(action=3)]), 0)
        for action in (1, 2, 3):
            self.assertEqual(self.batch([self.contact(action=action, y=500-action*40)]), 0)
        self.assertEqual([entry[1] for entry in self.output()], [1, 1, 0])
        self.assertEqual(self.lib.stat(0), 0)

    def test_ten_contacts_batch_uses_60_then_61_and_explicit_releases(self):
        self.synchronize()
        self.assertEqual(self.batch([self.contact(i, remaining=9-i) for i in range(10)]), 0)
        self.assertEqual(self.lib.stat(0), 1023)
        self.assertEqual(self.lib.stat(5), 1)
        self.assertEqual(self.batch([self.contact(i, action=3, remaining=9-i) for i in range(10)]), 0)
        self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual(len(self.output()), 20)

    def test_bad_trailing_event_or_read_error_never_emits_partial_down(self):
        self.synchronize()
        invalid = self.contact(x=1080)
        self.assertEqual(self.batch([self.contact(remaining=1), invalid]), errno.EINVAL)
        self.assertEqual(self.output(), [])
        self.assertEqual(self.batch([self.contact(remaining=1), self.contact(1)], fault=0x61), errno.EIO)
        self.assertEqual(self.output(), [])
        self.assertEqual(self.batch([self.contact(remaining=32)]), errno.EOVERFLOW)
        self.assertEqual(self.output(), [])
        self.assertEqual(self.batch([self.contact(remaining=1), bytes(8)]), errno.EINVAL)
        self.assertEqual(self.output(), [])

    def test_palm_grip_suppressed_until_up_unknown_move_does_not_start(self):
        self.synchronize()
        self.assertEqual(self.batch([self.contact(action=2)]), 0)
        self.assertEqual(self.output(), [])
        for kind in (5, 10, 1, 4):
            self.assertEqual(self.batch([self.contact(kind=kind)]), 0)
            self.assertEqual(self.batch([self.contact(action=2)]), 0)
            self.assertEqual(self.output(), [])
            self.assertEqual(self.batch([self.contact(action=3)]), 0)
        self.assertEqual(self.batch([self.contact()]), 0)
        self.assertEqual(self.batch([self.contact(action=2, kind=5)]), 0)
        self.assertEqual([entry[1] for entry in self.output()], [1, 0])

    def test_reset_or_error_status_fails_and_all_active_contacts_release(self):
        self.synchronize()
        self.assertEqual(self.batch([self.contact(0, remaining=1), self.contact(9)]), 0)
        for status in (bytes([5, 1, 0, 0, 0, 0, 0, 0]), bytes([9, 0, 0x10, 0, 0, 0, 0, 0])):
            self.assertEqual(self.batch([status]), errno.EIO)
        self.lib.release_all()
        self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual([entry[0] for entry in self.output()[-2:]], [0, 9])
        self.assertEqual([entry[1] for entry in self.output()[-2:]], [0, 0])

    def test_geometry_and_client_registration_contract(self):
        value = Geometry()
        self.assertTrue(self.lib.geometry_make(1080, 2340, 1125, 2436, C.byref(value)))
        self.assertEqual(tuple(getattr(value, key) for key, _ in value._fields_), (1080, 2340, 1125, 2436, 20, 48))
        self.assertFalse(self.lib.geometry_make(1080, 2400, 1125, 2436, C.byref(value)))
        self.assertTrue(self.lib.profile(0, 1, C.byref(value)))
        for fault in range(1, 6):
            self.assertFalse(self.lib.profile(fault, 1, C.byref(value)))
        self.assertFalse(self.lib.profile(0, 0, C.byref(value)))
        self.assertEqual(self.lib.axis(-1, 20, 1125, 1080), 1165)
        self.assertEqual(self.lib.axis(9999, 48, 2436, 2340), 64217)
        self.assertTrue(self.lib.edge(540, 2339))
        self.assertTrue(self.lib.edge(540, 2292))
        self.assertFalse(self.lib.edge(540, 1200))
        for args in ((False, True, 1, 1), (True, False, 1, 1), (True, True, 0, 0), (True, True, 2, 0)):
            self.assertFalse(self.lib.ready(*args))
        self.assertTrue(self.lib.ready(True, True, 2, 2))

    def test_hid_release_clears_all_ten_contacts_when_event_allocation_fails(self):
        for fault in (0, 1, 2):
            with self.subTest(allocation=fault):
                self.assertEqual(self.lib.hid_release_test(fault), 0)

    def test_session_requires_this_boot_successful_id_and_gic_proof(self):
        for fault in (1, 2):
            self.assertNotEqual(self.lib.identify(fault), 0)
            self.assertFalse(self.lib.identity_ready())
            self.assertEqual(self.lib.begin(True, 1), errno.ENOTSUP)
        self.assertEqual(self.lib.identify(0), 0)
        self.assertTrue(self.lib.identity_ready())
        self.assertEqual(self.lib.begin(False, 1), errno.ENOTSUP)
        self.assertEqual(self.lib.begin(True, 0), errno.ENOTSUP)
        self.assertEqual(self.lib.begin(True, 1), 0)
        for reg, count in ((0x55, 1), (0x60, 8), (0x61, 248)):
            self.assertEqual(self.lib.event_api(reg, count, 0), 0)
            self.assertEqual((self.lib.api_stat(3), self.lib.api_stat(4)), (reg, count))
        self.assertEqual(self.lib.event_api(0x10, 0, 0), errno.EINVAL)
        self.assertEqual(self.lib.event_api(0x60, 8, 0), errno.ENXIO)
        self.assertFalse(self.lib.identity_ready())
        self.assertEqual(self.lib.begin(True, 1), errno.ENOTSUP)

    def test_transport_error_closes_session_and_invalidates_identity(self):
        self.assertEqual(self.lib.identify(0), 0)
        self.assertEqual(self.lib.begin(True, 1), 0)
        self.assertEqual(self.lib.event_api(0x60, 8, 2), errno.EIO)
        self.assertFalse(self.lib.identity_ready())
        self.assertEqual(self.lib.event_api(0x60, 8, 0), errno.ENXIO)


if __name__ == "__main__":
    unittest.main()
