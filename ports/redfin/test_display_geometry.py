"""Exercise the real scaler and patched presentation/HID methods; no device I/O."""
import ctypes as C
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FB = 'iokit/Kernel/arm/SweetFramebuffer.cpp'
HID = 'iokit/Kernel/arm/hid/SweetHID.cpp'
HEADER = 'iokit/Kernel/arm/RedfinDisplayGeometry.h'
WIDTH, HEIGHT, STRIDE = 1080, 2340, 4320
BYTES = HEIGHT * STRIDE
RECT = C.c_int32 * 4


class Geometry(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ('mode', 'panel_w', 'panel_h', 'logical_w', 'logical_h', 'x', 'y', 'w', 'h')]


class Surface(C.Structure):
    _fields_ = [('pixels', C.c_void_p), ('length', C.c_uint64), ('offset', C.c_uint64),
                ('width', C.c_uint32), ('height', C.c_uint32), ('stride', C.c_uint32),
                ('format', C.c_uint32)]


def production_sources(directory):
    """Replay real source patches, including this overlay, without a prepared tree."""
    patches = sorted((ROOT / 'xnu/patches').glob('*.patch'))
    board = re.findall(r"['\"]([^'\"]+\.patch)['\"]", (HERE / 'prepare-xnu.py').read_text())
    patches += [HERE / Path(name).name for name in board]
    patches += [HERE / 'display-fit.patch']
    seen = set()
    for patch in patches:
        if patch in seen or not patch.is_file():
            continue
        seen.add(patch)
        source = patch.read_bytes()
        if not any(('+++ b/' + name + '\n').encode() in source for name in (FB, HID, HEADER)):
            continue
        result = subprocess.run(['git', 'apply', '--include=' + FB, '--include=' + HID,
                                 '--include=' + HEADER, str(patch)], cwd=directory,
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'{patch.name}: {result.stderr}')
    return {name: (directory / name).read_text() for name in (FB, HID, HEADER)}


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


STUBS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
#include "display-geometry.h"
static void IOLog(const char *,...) {}
static int PE_parse_boot_argn(const char *,void *,unsigned) {return 0;}
static unsigned locks,barriers,releases;
static void IOLockLock(void *) {locks++;}
static void IOLockUnlock(void *) {assert(locks);locks--;}
static void fake_barrier() {barriers++;}
#define OSSafeReleaseNULL(p) do {if(p){(p)->release();(p)=NULL;}} while(0)
#define SWEET_FB_LAYERS 4
static unsigned sweet_fb_swaps_logged;
static int sweet_console_muted;
static uint32_t get32(const uint8_t *p,unsigned n){uint32_t v;memcpy(&v,p+n,4);return v;}
static void put32(uint8_t *p,unsigned n,uint32_t v){memcpy(p+n,&v,4);}
struct Memory {uint64_t bytes;uint64_t getLength(){return bytes;}};
struct SweetSurface {
 uint32_t width,height,pixelFormat,bytesPerRow,bytesPerElement,elementWidth,elementHeight;
 uint64_t offset;const uint8_t *pixels;Memory *memory;
 uintptr_t kernelAddress(){return (uintptr_t)pixels;}
 void release(){releases++;}
};
static SweetSurface *current_surface;
static SweetSurface *sweet_surface_copy(uint32_t id){return id==1 ? current_surface : NULL;}
class AppleCLCD {public:
 bool fConsShown=false,fConsolePaused=false,fRedfinCopyOnly=true;
 uint8_t *fFlip[2]={};void *fVig0=NULL,*fLock=(void *)1,*fRedfinCaptureLock=NULL;
 uint32_t fScanPhys=0,fBootSrc=0,fBootStride=4320;
 uint32_t fWidth=1080,fHeight=2340,fRowBytes=4320,fLogicalW=1125,fLogicalH=2436;
 int fOffX=20,fOffY=48;uintptr_t fPixels=0;const uint8_t *fLastVA=NULL;
 SweetSurface *fSurface=NULL;uint64_t fRedfinFrames=0;
 struct redfin_display_geometry fRedfinFit={};
 struct redfin_display_workspace fRedfinFitWorkspace;
 bool directPresent(const uint8_t *){return false;}
 uint8_t *backBuffer(){assert(0);return NULL;}
 void scanFrom(uint32_t,uint32_t){assert(0);}
 void flipBack(){assert(0);}
 void captureRedfin(uint32_t,uint64_t){assert(0);}
 void present(const uint8_t *);
};
static uint32_t redfin_capture_early(AppleCLCD *){return 0;}

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
static uint64_t mach_absolute_time(){return 0;}
static unsigned dispatches,allocation_fault,last_down,last_up;
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
static int redfin_touch_axis_clamp(int value,int dimension){return value<0 ? 0 : value>=dimension ? dimension-1 : value;}
static int32_t redfin_touch_axis_normalize(int value,int offset,int logical){return (int32_t)(((int64_t)(value+offset)<<16)/logical);}
static bool redfin_touch_edge(int x,int y,int w,int h,int b){return x<b || x>w-1-b || y<b || y>h-1-b;}
class SweetHIDTouch {public:
 void *fLock=(void *)1;int fLogicalW=1125,fLogicalH=2436,fOffX=20,fOffY=48,fPanelW=1080,fPanelH=2340;
 bool fDown[10]={},fEdge[10]={};IOFixed fX[10]={},fY[10]={};
 struct redfin_display_geometry fRedfinFit={};bool fRedfinIgnored[10]={};
 void touch(int,bool,int,int);
 void dispatchEvent(IOHIDEvent *event){dispatches++;last_down=event->children_down;last_up=event->children_up;}
};
'''

WRAPPERS = r'''
static struct redfin_display_workspace workspace;
static SweetHIDTouch hid;
extern "C" {
bool geometry(unsigned mode,unsigned w,unsigned h,unsigned cw,unsigned ch,struct redfin_display_geometry *g){
 return redfin_display_geometry_make(mode,w,h,cw,ch,g);
}
bool clear(const struct redfin_display_geometry *g,uint8_t *p,uint64_t n,unsigned stride){
 return redfin_display_clear_margins(g,p,n,stride);
}
bool draw(const struct redfin_display_geometry *g,uint8_t *p,uint64_t n,unsigned stride,
 const struct redfin_display_surface *s,const int32_t *a,const int32_t *b,uint64_t *copied){
 return redfin_display_draw(g,&workspace,p,n,stride,s,a,b,copied);
}
unsigned present(unsigned mode,uint8_t *pixels,const struct redfin_display_surface *input,
 const int32_t *a,const int32_t *b,unsigned fault){
 AppleCLCD *fb=new AppleCLCD();
 if(mode)assert(redfin_display_geometry_make(mode,1080,2340,1125,2436,&fb->fRedfinFit));
 Memory memory={input->length};
 SweetSurface surface={input->width,input->height,input->format,input->stride,4,1,1,
  input->offset,input->pixels,&memory};
 if(fault==1)surface.bytesPerElement=2;
 if(fault==2)surface.elementWidth=2;
 if(fault==3)surface.elementHeight=2;
 if(fault==4)surface.memory=NULL;
 if(fault==5)surface.bytesPerElement=0;
 current_surface=&surface;fb->fPixels=(uintptr_t)pixels;
 if(fault==6)fb->fSurface=&surface;
 if(fault==7)current_surface=NULL;
 uint8_t record[0x46c]={};put32(record,0x104,1);put32(record,0x54,1);
 for(unsigned i=0;i<4;i++){put32(record,0x64+i*4,(uint32_t)a[i]);put32(record,0xc4+i*4,(uint32_t)b[i]);}
 releases=locks=barriers=0;fb->present(record);
 unsigned result=releases|(locks<<8)|(barriers<<16);delete fb;current_surface=NULL;return result;
}
void fill(uint32_t *p,unsigned width,unsigned height,unsigned stride){
 for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++)p[y*stride/4+x]=0xff000000u|((x&255)<<16)|((y&255)<<8)|((x+y)&255);
}
void hid_reset(unsigned mode){
 hid=SweetHIDTouch();if(mode)assert(redfin_display_geometry_make(mode,1080,2340,1125,2436,&hid.fRedfinFit));
 dispatches=last_down=last_up=allocation_fault=locks=0;
}
void touch(int finger,bool down,int x,int y,unsigned fault){allocation_fault=fault;hid.touch(finger,down,x,y);assert(!locks);}
unsigned hid_value(unsigned key,unsigned finger){
 if(key==0)return dispatches;if(key==1)return last_down;if(key==2)return last_up;
 if(finger>=10)return 0;
 if(key==3)return hid.fDown[finger];if(key==4)return (unsigned)hid.fX[finger];
 if(key==5)return (unsigned)hid.fY[finger];if(key==6)return hid.fEdge[finger];
 if(key==7)return hid.fRedfinIgnored[finger];return 0;
}
bool touch_map(const struct redfin_display_geometry *g,bool down,bool was,bool *ignored,int x,int y,
 int32_t *nx,int32_t *ny,bool *edge){return redfin_display_touch_map(g,down,was,ignored,x,y,nx,ny,edge);}
}
'''

SANITIZER = r'''
#include <assert.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "display-geometry.h"
#ifndef MAP_ANON
#define MAP_ANON MAP_ANONYMOUS
#endif
struct guarded {uint8_t *region,*pixels;size_t span,total,bytes,page;};
static struct guarded allocate_guarded(size_t bytes){
 struct guarded b={0};b.page=(size_t)sysconf(_SC_PAGESIZE);b.bytes=bytes;
 b.span=(bytes+b.page-1)/b.page*b.page;b.total=b.span+2*b.page;
 b.region=mmap(NULL,b.total,PROT_NONE,MAP_PRIVATE|MAP_ANON,-1,0);assert(b.region!=MAP_FAILED);
 assert(mprotect(b.region+b.page,b.span,PROT_READ|PROT_WRITE)==0);
 b.pixels=b.region+b.page+b.span-bytes;assert(!((uintptr_t)b.pixels&3));return b;
}
static void destroy_guarded(struct guarded *b){assert(munmap(b->region,b->total)==0);}
static uint32_t next_random(uint32_t *state){
 *state^=*state<<13;*state^=*state>>17;*state^=*state<<5;return *state;
}
int main(void){
 struct redfin_display_workspace *work=calloc(1,sizeof(*work));assert(work);
 struct guarded target=allocate_guarded(4320u*2340u);
 uint32_t random=0xd1534a77;
 for(unsigned mode=1;mode<=2;mode++){
  struct redfin_display_geometry g;assert(redfin_display_geometry_make(mode,1080,2340,1125,2436,&g));
  for(unsigned iteration=0;iteration<100;iteration++){
   uint32_t w=1+next_random(&random)%63,h=1+next_random(&random)%37;
   uint32_t stride=w*4+next_random(&random)%8*4,offset=next_random(&random)%8*4;
   size_t bytes=offset+(h-1)*stride+w*4;struct guarded source=allocate_guarded(bytes);
   memset(source.pixels,0xa5,bytes);
   struct redfin_display_surface s={source.pixels,bytes,offset,w,h,stride,REDFIN_DISPLAY_BGRA};
   assert(mprotect(source.region+source.page,source.span,PROT_READ)==0);
   int32_t a[4]={0,0,(int32_t)w,(int32_t)h};
   int32_t b[4]={(int32_t)(next_random(&random)%1280)-100,
    (int32_t)(next_random(&random)%2620)-100,
    (int32_t)(1+next_random(&random)%80),(int32_t)(1+next_random(&random)%80)};
   if(iteration==0){b[0]=b[1]=0;b[2]=1125;b[3]=2436;}
   if(iteration==1){b[0]=b[1]=-100;b[2]=b[3]=INT_MAX;}
   if(iteration==2){b[0]=b[1]=INT_MIN;b[2]=b[3]=INT_MAX;}
   uint64_t copied=99;assert(redfin_display_clear_margins(&g,target.pixels,target.bytes,4320));
   (void)redfin_display_draw(&g,work,target.pixels,target.bytes,4320,&s,a,b,&copied);
   assert(copied<=(uint64_t)g.w*g.h*4);
   struct redfin_display_surface bad=s;bad.length--;
   assert(!redfin_display_draw(&g,work,target.pixels,target.bytes,4320,&bad,a,b,&copied) && !copied);
   bad=s;bad.offset=UINT64_MAX-3;
   assert(!redfin_display_draw(&g,work,target.pixels,target.bytes,4320,&bad,a,b,&copied));
   a[0]=INT_MAX;a[2]=INT_MAX;
   assert(!redfin_display_draw(&g,work,target.pixels,target.bytes,4320,&s,a,b,&copied));
   bool ignored=false,edge=false;int32_t nx,ny;
   assert(redfin_display_touch_map(&g,true,true,&ignored,INT_MIN,INT_MIN,&nx,&ny,&edge));
   assert(nx==0 && ny==0);
   assert(redfin_display_touch_map(&g,true,true,&ignored,INT_MAX,INT_MAX,&nx,&ny,&edge));
   assert(nx>=0 && nx<65536 && ny>=0 && ny<65536);
   destroy_guarded(&source);
  }
 }
 destroy_guarded(&target);free(work);return 0;
}
'''


class DisplayGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('host C++ compiler required')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        actual = production_sources(directory)
        cls.actual = actual
        if actual[HEADER] != (HERE / 'display-geometry.h').read_text():
            raise RuntimeError('kernel overlay header differs from the host-tested header')
        (directory / 'display-geometry.h').write_text(actual[HEADER])
        present = function(actual[FB], 'void\nAppleCLCD::present(')
        present = present.replace('__asm__ volatile("dsb sy" ::: "memory");', 'fake_barrier();')
        touch = function(actual[HID], 'void\nSweetHIDTouch::touch(')
        source = directory / 'display.cpp'
        source.write_text(STUBS + present + touch + WRAPPERS)
        library = directory / 'display.so'
        result = subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-misleading-indentation',
                                 '-shared', '-fPIC', str(source), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library))
        cls.lib.geometry.argtypes = [C.c_uint] * 5 + [C.POINTER(Geometry)]
        cls.lib.geometry.restype = C.c_bool
        cls.lib.clear.argtypes = [C.POINTER(Geometry), C.c_void_p, C.c_uint64, C.c_uint]
        cls.lib.clear.restype = C.c_bool
        cls.lib.draw.argtypes = cls.lib.clear.argtypes + [C.POINTER(Surface), C.POINTER(C.c_int32),
                                                         C.POINTER(C.c_int32), C.POINTER(C.c_uint64)]
        cls.lib.draw.restype = C.c_bool
        cls.lib.present.argtypes = [C.c_uint, C.c_void_p, C.POINTER(Surface), C.POINTER(C.c_int32),
                                    C.POINTER(C.c_int32), C.c_uint]
        cls.lib.fill.argtypes = [C.c_void_p, C.c_uint, C.c_uint, C.c_uint]
        cls.lib.touch.argtypes = [C.c_int, C.c_bool, C.c_int, C.c_int, C.c_uint]
        cls.lib.hid_value.argtypes = [C.c_uint, C.c_uint]
        cls.lib.hid_value.restype = C.c_uint
        cls.lib.touch_map.argtypes = [C.POINTER(Geometry), C.c_bool, C.c_bool, C.POINTER(C.c_bool),
                                     C.c_int, C.c_int, C.POINTER(C.c_int32), C.POINTER(C.c_int32), C.POINTER(C.c_bool)]
        cls.lib.touch_map.restype = C.c_bool
        cls.directory = directory

    def geometry(self, mode=2):
        geometry = Geometry()
        self.assertTrue(self.lib.geometry(mode, 1080, 2340, 1125, 2436, C.byref(geometry)))
        return geometry

    def buffers(self, width=1125, height=2436, stride=4608, offset=0):
        length = offset + (height - 1) * stride + width * 4
        source = (C.c_uint32 * ((length + 3) // 4))()
        self.lib.fill(C.addressof(source) + offset, width, height, stride)
        output = (C.c_uint32 * (BYTES // 4 + 16))()
        C.memset(output, 0x5a, C.sizeof(output))
        surface = Surface(C.addressof(source), length, offset, width, height, stride, 0x42475241)
        return source, surface, output

    def test_exact_fixed_modes_and_camera_rectangle(self):
        for mode, expected in ((1, (0, 1, 1080, 2338)), (2, (31, 136, 1017, 2204))):
            g = self.geometry(mode)
            self.assertEqual((g.x, g.y, g.w, g.h), expected)
            self.assertLessEqual(abs(g.w * 2436 - g.h * 1125), 2436)
        for mode, pw, ph, cw, ch in ((0,1080,2340,1125,2436), (3,1080,2340,1125,2436),
                                      (2,1080,2400,1125,2436), (2,1080,2340,1080,2340),
                                      (2,0,0,1125,2436), (0xffffffff,1080,2340,1125,2436)):
            self.assertFalse(self.lib.geometry(mode,pw,ph,cw,ch,C.byref(Geometry())))
        self.assertFalse(self.lib.geometry(2,1080,2340,1125,2436,None))
        g = self.geometry(2)
        self.assertGreaterEqual(g.y,136)
        self.assertLessEqual(g.x + g.w,1080)
        self.assertEqual(g.y + g.h,2340)

    def test_real_full_canvas_present_is_bilinear_and_source_immutable(self):
        source, surface, output = self.buffers(offset=64)
        original = hashlib.sha256(source).digest()
        rect = RECT(0,0,1125,2436)
        for mode in (1,2):
            g = self.geometry(mode)
            self.assertEqual(self.lib.present(mode,output,C.byref(surface),rect,rect,0), 1 | (1 << 16))
            for x,y in ((0,0),(g.w-1,0),(0,g.h-1),(g.w-1,g.h-1),(g.w//2,g.h//2),(4,130),(400,900)):
                self.assertEqual(output[(g.y+y)*WIDTH+g.x+x],
                                 self.reference(source,surface,(0,0,1125,2436),g.w,g.h,x,y))
            self.assertEqual(hashlib.sha256(source).digest(),original)
            for x,y in ((0,0),(1079,0),(0,135),(1079,135)):
                if not (g.x <= x < g.x+g.w and g.y <= y < g.y+g.h):
                    self.assertEqual(output[y*WIDTH+x],0xff000000)
            self.assertEqual(output[-16:],[0x5a5a5a5a]*16)

    @staticmethod
    def reference(source, surface, rect, dw, dh, x, y):
        sx,sy,sw,sh = rect
        ax = max(0,min((sw-1)*256,((2*x+1)*sw-dw)*128//dw))
        ay = max(0,min((sh-1)*256,((2*y+1)*sh-dh)*128//dh))
        ix,iy,wx,wy = ax//256,ay//256,ax%256,ay%256
        def pixel(dx,dy):
            return source[(surface.offset+(sy+dy)*surface.stride)//4+sx+dx]
        def blend(a,b,w):
            return sum((((a>>shift)&255)*(256-w)+((b>>shift)&255)*w)//256 << shift for shift in (0,8,16,24))
        a,b = pixel(ix,iy),pixel(min(ix+1,sw-1),iy)
        if wy:
            a = blend(a,pixel(ix,min(iy+1,sh-1)),wy)
            b = blend(b,pixel(min(ix+1,sw-1),min(iy+1,sh-1)),wy)
        return blend(a,b,wx)

    def test_source_subrect_destination_clipping_and_adjacent_layer_grid(self):
        source,surface,output = self.buffers(29,23,128,32)
        g = self.geometry(2)
        src = RECT(3,4,11,13)
        for dst in (RECT(100,200,20,30),RECT(-10,200,20,30),RECT(100,-10,20,30),
                    RECT(1115,2426,20,30),RECT(-2147483648,0,2147483647,20),
                    RECT(2147483647,2147483647,2147483647,2147483647)):
            C.memset(output,0x5a,C.sizeof(output))
            copied=C.c_uint64(123)
            result=self.lib.draw(C.byref(g),output,BYTES,STRIDE,C.byref(surface),src,dst,C.byref(copied))
            px0=g.x+dst[0]*g.w//1125; py0=g.y+dst[1]*g.h//2436
            px1=g.x+(dst[0]+dst[2])*g.w//1125; py1=g.y+(dst[1]+dst[3])*g.h//2436
            x0,y0=max(g.x,px0),max(g.y,py0)
            x1,y1=min(g.x+g.w,px1),min(g.y+g.h,py1)
            visible=x1>x0 and y1>y0
            self.assertEqual(result,visible)
            self.assertEqual(copied.value,max(0,x1-x0)*max(0,y1-y0)*4)
            if visible:
                for x,y in ((x0,y0),(x1-1,y1-1)):
                    self.assertEqual(output[y*WIDTH+x],self.reference(source,surface,src,px1-px0,py1-py0,x-px0,y-py0))
                if x0:self.assertEqual(output[y0*WIDTH+x0-1],0x5a5a5a5a)
            self.assertEqual(output[-16:],[0x5a5a5a5a]*16)
        # Adjacent logical halves share the exact projected boundary.
        first,second=RECT(0,0,562,2436),RECT(562,0,563,2436)
        self.assertTrue(self.lib.draw(C.byref(g),output,BYTES,STRIDE,C.byref(surface),src,first,C.byref(C.c_uint64())))
        self.assertTrue(self.lib.draw(C.byref(g),output,BYTES,STRIDE,C.byref(surface),src,second,C.byref(C.c_uint64())))
        self.assertNotEqual(output[g.y*WIDTH+g.x+562*g.w//1125-1],0x5a5a5a5a)
        self.assertNotEqual(output[g.y*WIDTH+g.x+562*g.w//1125],0x5a5a5a5a)

    def test_checked_memory_format_and_rectangle_failures_write_nothing(self):
        source,surface,output = self.buffers(11,13,48,16)
        g=self.geometry(2);src=RECT(0,0,11,13);dst=RECT(0,0,1125,2436)
        source_before=hashlib.sha256(source).digest()
        invalid=[]
        for key,value in (('length',surface.length-1),('length',0),('offset',surface.length+4),
                          ('offset',0xfffffffffffffffc),('offset',1),('stride',40),('stride',47),
                          ('format',0x52474241),('width',16385),('height',0),('pixels',None)):
            bad=Surface.from_buffer_copy(surface);setattr(bad,key,value);invalid.append(bad)
        before=hashlib.sha256(output).digest()
        for bad in invalid:
            copied=C.c_uint64(777)
            self.assertFalse(self.lib.draw(C.byref(g),output,BYTES,STRIDE,C.byref(bad),src,dst,C.byref(copied)))
            self.assertEqual(copied.value,0)
            self.assertEqual(hashlib.sha256(output).digest(),before)
        for bad_src in (RECT(-1,0,2,2),RECT(0,-1,2,2),RECT(10,0,2,2),RECT(0,12,2,2),
                        RECT(2147483647,0,2147483647,2)):
            self.assertFalse(self.lib.draw(C.byref(g),output,BYTES,STRIDE,C.byref(surface),bad_src,dst,C.byref(C.c_uint64())))
            self.assertEqual(hashlib.sha256(output).digest(),before)
        for length,stride in ((BYTES-1,STRIDE),(BYTES,STRIDE-4),(0,STRIDE)):
            self.assertFalse(self.lib.clear(C.byref(g),output,length,stride))
        bad_g=Geometry.from_buffer_copy(g);bad_g.w+=1
        self.assertFalse(self.lib.clear(C.byref(bad_g),output,BYTES,STRIDE))
        self.assertEqual(hashlib.sha256(output).digest(),before)
        # The actual wrapper also rejects metadata that cannot describe BGRA.
        for fault in (1,2,3,4,5,6,7):
            self.lib.present(2,output,C.byref(surface),src,dst,fault)
            self.assertEqual(output[g.y*WIDTH+g.x],0x5a5a5a5a)
        self.assertEqual(hashlib.sha256(source).digest(),source_before)

    def test_default_rectangle_policy_single_pixel_and_legacy_crop(self):
        source,surface,output=self.buffers(1,1,4)
        source[0]=0x80402010
        g=self.geometry(2);copied=C.c_uint64()
        self.assertTrue(self.lib.draw(C.byref(g),output,BYTES,STRIDE,C.byref(surface),RECT(9,9,0,0),RECT(9,9,0,0),C.byref(copied)))
        self.assertEqual(copied.value,g.w*g.h*4)
        self.assertEqual(output[g.y*WIDTH+g.x],source[0])
        self.assertEqual(output[(g.y+g.h-1)*WIDTH+g.x+g.w-1],source[0])
        source,surface,output=self.buffers()
        rect=RECT(0,0,1125,2436)
        self.lib.present(0,output,C.byref(surface),rect,rect,0)
        self.assertEqual(output[0],source[48*4608//4+20])
        self.assertEqual(output[BYTES//4-1],source[(48+2339)*4608//4+20+1079])

    def test_inverse_touch_matches_fit_and_preserves_release_across_margins(self):
        g=self.geometry(2);self.lib.hid_reset(2)
        value=lambda key,finger=0:self.lib.hid_value(key,finger)
        self.lib.touch(0,True,0,0,0)
        self.assertEqual((value(0),value(3),value(7)),(0,0,1))
        self.lib.touch(0,True,500,500,0)
        self.assertEqual(value(0),0)
        self.lib.touch(0,False,500,500,0)
        self.assertEqual((value(0),value(7)),(0,0))
        self.lib.touch(0,True,500,500,0)
        self.assertEqual((value(0),value(3)),(1,1))
        self.assertEqual((value(4),value(5)),((500-g.x)*65536//g.w,(500-g.y)*65536//g.h))
        self.lib.touch(0,True,0,0,0)
        self.assertEqual((value(4),value(5),value(3)),(0,0,1))
        self.lib.touch(0,False,0,0,0)
        self.assertEqual((value(3),value(2)),(0,1))
        for mode in (1,2):
            g=self.geometry(mode);self.lib.hid_reset(mode)
            for finger,x,y in ((0,g.x,g.y),(1,g.x+g.w-1,g.y+g.h-1),(2,g.x+g.w//2,g.y+g.h//2)):
                self.lib.touch(finger,True,x,y,0)
                self.assertEqual(value(4,finger),(x-g.x)*65536//g.w)
                self.assertEqual(value(5,finger),(y-g.y)*65536//g.h)
                self.assertEqual(value(6,finger),int(finger!=2))
            self.lib.touch(1,False,1079,2339,1)
            self.assertEqual(value(3,1),0)  # release survives allocation failure
        self.lib.hid_reset(0);self.lib.touch(0,True,0,0,0)
        self.assertEqual((value(4),value(5)),(20*65536//1125,48*65536//2436))

    def test_touch_integer_extremes_are_bounded_and_contacts_are_independent(self):
        g=self.geometry(2)
        for x,y in ((-2147483648,-2147483648),(2147483647,2147483647),(0,135),(1079,2339)):
            ignored=C.c_bool();nx=C.c_int32();ny=C.c_int32();edge=C.c_bool()
            self.assertTrue(self.lib.touch_map(C.byref(g),True,True,C.byref(ignored),x,y,C.byref(nx),C.byref(ny),C.byref(edge)))
            self.assertTrue(0<=nx.value<65536 and 0<=ny.value<65536)
        self.lib.hid_reset(2)
        self.lib.touch(0,True,0,0,0);self.lib.touch(1,True,500,500,0)
        self.assertEqual((self.lib.hid_value(3,0),self.lib.hid_value(3,1)),(0,1))
        self.lib.touch(0,False,0,0,0)
        self.assertEqual((self.lib.hid_value(7,0),self.lib.hid_value(3,1)),(0,1))

    def test_c11_address_and_undefined_sanitizers_with_readonly_guarded_sources(self):
        source=self.directory/'sanitizer.c'
        executable=self.directory/'sanitizer'
        source.write_text(SANITIZER)
        result=subprocess.run([shutil.which('cc') or 'cc','-std=c11','-D_DEFAULT_SOURCE','-O1','-g',
                               '-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                               '-fno-sanitize-recover=undefined','-fno-omit-frame-pointer',
                               str(source),'-o',str(executable)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([str(executable)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
