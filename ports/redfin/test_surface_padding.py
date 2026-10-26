"""Owned native transfer footprints and immutable exact-image import permission."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class Image(C.Structure):
    _fields_=[(key,C.c_uint32) for key in ('width','height','pitch','offset','format','planes',
                                         'bytes_per_element','element_width','element_height')]


class Plan(C.Structure):
    _fields_=[('allocation',C.c_uint64),('extent',C.c_uint64)]


class Owner(C.Structure):
    _fields_=[('image',Image),('extent',C.c_uint64)]


class View(C.Structure):
    _fields_=[(key,C.c_uint32) for key in ('width','height','pitch','offset','cpp','levels','layers','samples')]


def compile_host(root,source,cpp=False):
    path=root/('contract.cpp' if cpp else 'contract.c');path.write_text(source)
    library=root/'contract.so'
    result=subprocess.run(['c++' if cpp else 'cc','-std=c++17' if cpp else '-std=c11',
        '-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
        '-Wno-unused-function','-Wno-missing-field-initializers','-I',str(HERE),
        str(path),'-o',str(library)],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    return C.CDLL(str(library))


class SurfacePaddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.lib=compile_host(Path(cls.temp.name),'''
#include "surface-padding.h"
int plan(const struct rf_gp_image *s,uint64_t n,struct rf_gp_plan *p)
{return rf_gp_storage_plan(s,n,p);}
uint64_t extent(const struct rf_gp_import *o,const struct rf_gp_view *v,uint64_t n)
{return rf_gp_full_image_extent(o,v,n);}
''')
        cls.lib.plan.argtypes=[C.POINTER(Image),C.c_uint64,C.POINTER(Plan)]
        cls.lib.extent.argtypes=[C.POINTER(Owner),C.POINTER(View),C.c_uint64]
        cls.lib.extent.restype=C.c_uint64

    def image(self,w=1065,h=282,pitch=4288):
        return Image(w,h,pitch,0,0x42475241,0,4,1,1)

    def test_native_probe_guards_owned_output_footprints_and_every_readonly_source_byte(self):
        helper=function((HERE/'metal-raster-check.inc').read_text(),
                        'static uint64_t raster_probe_tail_start(')
        source='#include "surface-padding.h"\ntypedef int BOOL;\n'+helper+'''
uint64_t guard(unsigned w,unsigned h,unsigned p,unsigned n,int output,unsigned abi)
{return raster_probe_tail_start(w,h,p,n,output,abi);}
'''
        with tempfile.TemporaryDirectory() as directory:
            lib=compile_host(Path(directory),source);lib.guard.restype=C.c_uint64
            lib.guard.argtypes=[C.c_uint]*4+[C.c_int,C.c_uint]
            for width,height,pitch,allocation in ((1125,9,4544,65536),
                    (1065,282,4288,1228800),(281,609,1152,720896),(64,64,256,32768)):
                visible=pitch*height;extent=pitch*((height+3)&~3)
                self.assertEqual(lib.guard(width,height,pitch,allocation,1,1),extent)
                for output,abi in ((0,1),(0,0),(0,2),(1,0),(1,2)):
                    self.assertEqual(lib.guard(width,height,pitch,allocation,output,abi),visible)
            # Converted output backing and arbitrary allocation slack acquire
            # no permission; the old logical tail remains protected.
            for pitch,allocation in ((4512,65536),(480,16384),(4544,65535),(4544,32768)):
                self.assertEqual(lib.guard(1125 if pitch>500 else 120,9,pitch,allocation,1,1),pitch*9)

    def test_actual_16_by_4_footprint_allocates_every_row_and_preserves_larger_owned_size(self):
        for width in (1,15,16,17,281,640,1065,1080,1125,16384):
            pitch=(width*4+63)&~63
            for height in range(1,1030):
                image=self.image(width,height,pitch)
                visible=pitch*height;allocation=(visible+16383)&~16383
                expected=pitch*((height+3)&~3)
                for capacity in (allocation,allocation+32768):
                    plan=Plan()
                    self.assertEqual(self.lib.plan(C.byref(image),capacity,C.byref(plan)),1)
                    self.assertEqual(plan.extent,expected)
                    self.assertEqual(plan.allocation,max(capacity,(expected+16383)&~16383))
                    self.assertLessEqual(plan.extent,plan.allocation)

    def test_invalid_formats_planes_dimensions_pitch_offsets_and_overflow_grant_nothing(self):
        for key,value in (('width',0),('width',16385),('height',0),('height',16385),
                          ('pitch',4287),('pitch',64),('offset',64),('planes',1),
                          ('format',0),('bytes_per_element',2),('element_width',2),('element_height',2)):
            image=self.image();setattr(image,key,value);plan=Plan(123,456)
            self.assertEqual(self.lib.plan(C.byref(image),1212416,C.byref(plan)),0)
            self.assertEqual((plan.allocation,plan.extent),(123,456))
        for image,allocation in ((self.image(),0),(self.image(),1212415),
                                  (self.image(),16384),(self.image(),2**64-1),
                                  (self.image(16384,16384,65536),128*1024**2)):
            self.assertFalse(self.lib.plan(C.byref(image),allocation,C.byref(Plan())))
        self.assertFalse(self.lib.plan(None,16384,C.byref(Plan())))
        self.assertFalse(self.lib.plan(C.byref(self.image()),1212416,None))

    def test_attestation_is_exact_and_cannot_extend_an_offset_smaller_mip_or_array_view(self):
        for w,h,pitch in ((1065,282,4288),(281,609,1152),(1125,2436,4544)):
            image=self.image(w,h,pitch);plan=Plan();initial=(pitch*h+16383)&~16383
            self.assertTrue(self.lib.plan(C.byref(image),initial,C.byref(plan)))
            owner=Owner(image,plan.extent);view=View(w,h,pitch,0,4,1,1,1)
            self.assertEqual(self.lib.extent(C.byref(owner),C.byref(view),plan.allocation),plan.extent)
            for field,value in (('width',w-1),('height',h-1),('pitch',pitch+64),('offset',64),
                                ('cpp',8),('levels',2),('layers',2),('samples',4)):
                altered=View.from_buffer_copy(view);setattr(altered,field,value)
                self.assertEqual(self.lib.extent(C.byref(owner),C.byref(altered),plan.allocation),0)
            for extent,allocation in ((0,plan.allocation),(plan.extent+1,plan.allocation),
                                      (plan.extent,initial-16384)):
                altered=Owner(image,extent)
                self.assertEqual(self.lib.extent(C.byref(altered),C.byref(view),allocation),0)

    def test_actual_kernel_query_requires_real_owned_descriptor_and_rejects_stale_geometry(self):
        from test_smp_gui import patched_source
        method=function(patched_source('iokit/Kernel/arm/RedfinGPU.cpp'),
                        'IOReturn RedwoodGPUUserClient::info(')
        self.assertEqual(patched_source('iokit/Kernel/arm/RedfinSurfacePadding.h'),
                         (HERE/'surface-padding.h').read_text())
        source=r'''
#include <assert.h>
#include "surface-padding.h"
using IOReturn=int;
enum {kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnUnsupported=2};
struct IOMemoryDescriptor {uint64_t length;virtual ~IOMemoryDescriptor(){} uint64_t getLength(){return length;}};
struct IOBufferMemoryDescriptor:public IOMemoryDescriptor {};
#define OSDynamicCast(type,value) dynamic_cast<type *>(value)
static bool ready=true;static bool redfin_gpu_ready(){return ready;}
struct SweetSurface {
 uint32_t width=1065,height=282,bytesPerRow=4288,offset=0,pixelFormat=RF_GP_BGRA,planeCount=0;
 uint32_t bytesPerElement=4,elementWidth=1,elementHeight=1,allocSize=1228800;
 uint64_t redfinRenderExtent=1217792,scanoutPhys=0;int scanoutSlot=-1;bool wrapped=false;
 uint32_t parentID=0;IOMemoryDescriptor *memory=nullptr;
};
struct gpu_buffer {uint64_t address=123,size=1228800;uint32_t flags=0;SweetSurface *surface=nullptr;IOMemoryDescriptor *memory=nullptr;};
struct msm_gem_info {uint32_t handle,info;uint64_t value;uint32_t len,pad;};
struct RedwoodGPUUserClient {
 gpu_buffer entry;gpu_buffer *buffer(uint32_t n){return n==7?&entry:nullptr;}
 IOReturn info(msm_gem_info *);
};
''' + method + r'''
extern "C" int contract() {
 for(unsigned fault=0;fault<17;++fault) {
  IOBufferMemoryDescriptor memory,other;IOMemoryDescriptor foreign;memory.length=other.length=foreign.length=1228800;
  SweetSurface surface;surface.memory=&memory;RedwoodGPUUserClient client;
  client.entry.memory=&memory;client.entry.surface=&surface;ready=true;
  msm_gem_info request={7,RF_GP_INFO_RENDER_EXTENT,999,0,0};
  switch(fault) {
   case 0:break;case 1:surface.wrapped=true;break;case 2:surface.parentID=1;break;
   case 3:surface.scanoutPhys=4096;break;case 4:surface.scanoutSlot=0;break;
   case 5:surface.memory=&other;break;case 6:surface.allocSize-=16384;break;
   case 7:memory.length-=16384;break;case 8:surface.memory=client.entry.memory=&foreign;break;
   case 9:surface.redfinRenderExtent=0;break;case 10:surface.redfinRenderExtent++;break;
   case 11:surface.height=285;break;case 12:surface.offset=64;break;case 13:ready=false;break;
   case 14:client.entry.surface=nullptr;break;case 15:request.len=1;break;case 16:request.pad=1;break;
  }
  IOReturn result=client.info(&request);
  assert(result==(fault>=15?kIOReturnBadArgument:kIOReturnSuccess));
  assert(request.value==(fault?0:1217792));
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(compile_host(Path(folder),source,True).contract(),0)

    def test_actual_import_cache_queries_once_and_retains_exact_owned_permission(self):
        target='src/freedreno/drm/freedreno_bo.c'
        path=ROOT/'research/redfin-gpu/render-padding-base-v1'/target
        if not path.is_file():self.skipTest('verified native Mesa preimage fixture absent')
        with tempfile.TemporaryDirectory() as folder:
            native=Path(folder)/target;native.parent.mkdir(parents=True);native.write_bytes(path.read_bytes())
            subprocess.run(['git','apply','--include='+target,str(HERE/'mesa-surface-padding.patch')],
                           cwd=folder,check=True,capture_output=True)
            method=function(native.read_text(),'struct fd_bo *\nfd_bo_from_dmabuf_drm(')
        source=r'''
#include <assert.h>
#include <string.h>
#include "surface-padding.h"
#define __APPLE__ 1
#define VG_BO_ALLOC(value) ((void)(value))
struct fd_device;struct fd_bo {uint32_t size,handle;struct rf_gp_import redfin_padding;bool redfin_padding_ready;};
struct fd_funcs {uint32_t (*handle_from_dmabuf)(struct fd_device *,int);};
struct fd_device {int fd;void *handle_table;struct fd_funcs *funcs;};
struct redwood_drm_surface {uint32_t surface,handle;uint64_t size;uint32_t offset,row_bytes,width,height,pixel_format,planes;};
static struct fd_bo zombie,existing;static int table_lock,locked,describes,queries,imports;static bool cached,declined;
static void simple_mtx_lock(int *p){assert(p==&table_lock&&!locked);locked=1;}
static void simple_mtx_unlock(int *p){assert(p==&table_lock&&locked);locked=0;}
static uint32_t handle(struct fd_device *d,int surface){assert(locked&&d->fd==4&&surface==8);return 7;}
static struct fd_bo *lookup_bo(void *t,uint32_t h){(void)t;assert(locked&&h==7);return cached?&existing:NULL;}
static struct fd_bo *import_bo_from_handle(struct fd_device *d,int bytes,uint32_t h){
 (void)d;assert(locked&&bytes==1228800&&h==7);++imports;existing.size=bytes;existing.handle=h;cached=true;return &existing;}
static int redwood_drm_surface(int fd,struct redwood_drm_surface *s){
 assert(locked&&fd==4&&s->surface==8);++describes;
 s->size=1228800;s->width=1065;s->height=282;s->row_bytes=4288;s->pixel_format=RF_GP_BGRA;return 0;}
static uint64_t redwood_drm_render_extent(int fd,uint32_t h){assert(locked&&fd==4&&h==7);++queries;return declined?0:1217792;}
''' + method + r'''
int contract(void) {
 struct fd_funcs funcs={handle};struct fd_device device={4,NULL,&funcs};
 for(unsigned phase=0;phase<2;++phase) {
  memset(&existing,0,sizeof(existing));cached=false;declined=phase;describes=queries=imports=0;
  for(unsigned i=0;i<20;++i) {
   struct fd_bo *bo=fd_bo_from_dmabuf_drm(&device,8);
   assert(bo==&existing&&bo->redfin_padding_ready&&!locked);
   assert(bo->redfin_padding.extent==(phase?0:1217792));
   assert(describes==1&&queries==1&&imports==1);
  }
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(compile_host(Path(folder),source).contract(),0)


if __name__=='__main__':unittest.main()
