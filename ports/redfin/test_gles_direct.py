"""Actual queue/BO/frame code preserves ownership and completion on direct draws."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin.compositor_evidence import analyze

HERE=Path(__file__).resolve().parent


class GLESDirectTests(unittest.TestCase):
    def run_source(self,source,cpp=False):
        with tempfile.TemporaryDirectory(prefix='redfin-gles-direct-') as directory:
            folder=Path(directory);path=folder/('contract.cpp' if cpp else 'contract.c');path.write_text(source)
            result=subprocess.run(['c++' if cpp else 'cc','-std=c++17' if cpp else '-std=c11',
                '-O2','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-Wno-misleading-indentation',
                '-I'+str(HERE),str(path),'-o',str(folder/'contract')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            run=subprocess.run([str(folder/'contract')],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_native_producer_changes_only_seed_after_admission_and_never_completes_DMA(self):
        self.run_source(r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include "include/redfin_gpu_queue.h"
#include "include/redfin_gpu_surface.h"
using SInt32=int32_t;using IOReturn=int;
enum {kIOReturnSuccess=0,kIOReturnBadArgument=2,kIOReturnNotReady=3,kIOReturnUnsupported=4};
struct State {uint8_t bytes[64];unsigned length=64;bool missing=false;
 unsigned getLength(){return length;}void *getBytesNoCopy(){return missing?nullptr:bytes;}};
struct SweetSurface {uint32_t id=19;State *state;};
struct gpu_buffer {SweetSurface *surface;uint32_t fence=7,pending=1,producerFence=0;};
static unsigned atomic_updates;
static SInt32 OSIncrementAtomic(volatile SInt32 *p){++atomic_updates;SInt32 old=*p;*p=(SInt32)((uint32_t)old+1);return old;}
static void IOLog(const char *,...){}
#include "gpu-surface-producer.inc"
int main(){
 for(unsigned fault=0;fault<18;++fault){
  State state;memset(state.bytes,0xa7,sizeof(state.bytes));uint32_t seed=41;memcpy(state.bytes+12,&seed,4);
  SweetSurface surface={19,&state};gpu_buffer b={&surface,7,1,0};
  rf_gq_client q={7,6,6,0,1,0,false};rf_gu_surface_producer r={3,19,7,0};
  switch(fault){
   case 1:r.handle=0;break;case 2:r.surface=0;break;case 3:r.fence=0;break;
   case 4:r.reserved=1;break;case 5:surface.id=20;break;case 6:b.fence=0;break;
   case 7:b.fence=8;break;case 8:r.fence=8;break;case 9:b.producerFence=8;break;
   case 10:q.closing=true;break;case 11:q.failed=6;break;case 12:surface.state=nullptr;break;
   case 13:state.length=15;break;case 14:state.missing=true;break;case 15:b.surface=nullptr;break;
   case 16:b.fence=6;break;case 17:b.producerFence=7;break;
  }
  rf_gq_client before=q;unsigned pending=b.pending;uint8_t bytes[64];memcpy(bytes,state.bytes,64);atomic_updates=0;
  int result=gpuSurfaceAnnounce(&b,&q,&r);bool accepted=fault==0||fault==16||fault==17;
  assert((result==0)==accepted);assert(!memcmp(&before,&q,sizeof(q))&&b.pending==pending);
  bool bumped=accepted&&fault!=17;assert(atomic_updates==bumped);
  uint32_t after=0;memcpy(&after,state.bytes+12,4);assert(after==(bumped?42u:41u));
  memcpy(state.bytes+12,bytes+12,4);assert(!memcmp(state.bytes,bytes,64));
  if(accepted){
   assert(rf_gq_status(&q,7)==EAGAIN); /* Announcement is never CPU/GPU completion. */
   assert(!gpuSurfaceAnnounce(&b,&q,&r)&&atomic_updates==bumped);
   assert(!rf_gq_retire(&q,7,0)&&rf_gq_status(&q,7)==0);
  }
 }
 return 0;
}
''',True)

    def test_bound_resource_admission_rejects_aliases_and_keeps_native_handle_lifetime(self):
        self.run_source(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define __APPLE__ 1
#include "surface-padding.h"
enum {PIPE_TEXTURE_2D=2,PIPE_FORMAT_B8G8R8A8_UNORM=7};
struct fd_device {int fd;};
struct fd_bo {struct fd_device *dev;uint32_t size,handle,redfin_surface;bool redfin_padding_ready;struct rf_gp_import redfin_padding;};
struct pipe_resource {unsigned target,last_level,array_size,depth0,nr_samples,format,width0,height0;};
struct fd_resource {struct pipe_resource base;struct fd_bo *bo;struct {unsigned pitch0;struct {unsigned offset,size0;} slices[1];}layout;};
static struct fd_resource *fd_resource(struct pipe_resource *p){return (struct fd_resource *)p;}
static uint32_t fd_bo_size(struct fd_bo *b){return b->size;}
static unsigned calls;static bool capable;
uint32_t redwood_drm_surface_producer(int fd,uint32_t handle){assert(fd==-1&&handle==23);++calls;return capable?handle:0;}
#include "gles-resource-producer.inc"
int main(void){
 for(unsigned fault=0;fault<17;++fault){
  struct fd_device dev={11};struct fd_bo bo={&dev,32768,23,19,true,{{80,61,320,0,RF_GP_BGRA,0,4,1,1},20480}};
  struct fd_resource r={.base={2,0,1,1,1,7,80,61},.bo=&bo,.layout={320,{{0,20480}}}};
  capable=true;calls=0;unsigned surface=19;
  switch(fault){case 1:r.base.target=1;break;case 2:r.base.last_level=1;break;
   case 3:r.base.array_size=2;break;case 4:r.base.depth0=2;break;case 5:r.base.nr_samples=4;break;
   case 6:r.base.format=8;break;case 7:r.base.width0=79;break;case 8:r.base.height0=60;break;
   case 9:r.layout.slices[0].offset=64;break;case 10:r.layout.slices[0].size0--;break;
   case 11:bo.redfin_surface=20;break;case 12:bo.redfin_padding_ready=false;break;
   case 13:bo.redfin_padding.extent=0;break;case 14:r.bo=NULL;break;
   case 15:capable=false;break;case 16:surface=0;break;}
  uint32_t handle=redfin_freedreno_surface_producer(&r.base,surface);
  assert(handle==(fault==0?23u:0u));assert(calls==(fault==0||fault==15));
 }
 assert(!redfin_freedreno_surface_producer(NULL,19));return 0;
}
''')

    def test_metadata_uses_materialized_final_fence_and_stops_on_any_failed_target(self):
        self.run_source(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define __APPLE__ 1
#include "include/redfin_gpu_surface.h"
struct fd_device {int fd;};struct fd_pipe {struct fd_device *dev;};
struct native_fence {struct fd_pipe *pipe;unsigned kfence;};
struct pipe_fence_handle {struct pipe_fence_handle *last_fence;struct native_fence *fence;};
static unsigned published,announced;static int failure;
static int redfin_freedreno_fence_publish(struct pipe_fence_handle *f){assert(f);++published;return failure==1?-1:0;}
static int redwood_drm_surface_announce(int fd,const struct rf_gu_target *t,unsigned fence){
 assert(published==1&&fd==-1&&fence==37&&t->handle&&t->surface);++announced;return failure==2?-1:0;
}
#include "gles-fence-surfaces.inc"
int main(void){
 struct fd_device d={13};struct fd_pipe p={&d};struct native_fence native={&p,37};
 struct pipe_fence_handle last={NULL,&native},first={&last,NULL};
 struct rf_gu_target targets[]={{3,19},{5,23}};
 for(failure=0;failure<3;++failure){
  published=announced=0;assert((redfin_freedreno_publish_surfaces(&first,targets,2)==0)==!failure);
  assert(published==1&&announced==(failure==1?0:failure==2?1:2));
 }
 published=announced=0;assert(redfin_freedreno_publish_surfaces(&first,targets,0));
 assert(redfin_freedreno_publish_surfaces(&first,NULL,1));
 assert(redfin_freedreno_publish_surfaces(&first,targets,257));assert(!published&&!announced);
 native.kfence=0;failure=0;assert(redfin_freedreno_publish_surfaces(&first,targets,2)&&!announced);
 return 0;
}
''')

    def test_actual_frame_stages_copies_before_publication_and_retains_CPU_and_Finish_fallback(self):
        self.run_source(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "include/redfin_gpu_surface.h"
typedef unsigned IOSurfaceRef;
struct image {bool target,drawn,shared;unsigned mirror,producer;IOSurfaceRef surface;};
struct eagl {struct image images[4];unsigned image_count,frames;bool producer_transfer,in_frame;};
static unsigned copied,seed_locks,finishes,flushes,published,phase,direct_count,mirror_count;
static bool failed,wait_for_frames;static unsigned shown_texture;
static unsigned IOSurfaceGetID(IOSurfaceRef s){return s;}
static int IOSurfaceLock(IOSurfaceRef s,unsigned flags,void *seed){assert(s&&!flags&&!seed);++seed_locks;return 0;}
static void IOSurfaceUnlock(IOSurfaceRef s,unsigned flags,void *seed){assert(s&&!flags&&!seed);}
static void glFlush(void){++flushes;phase=2;}
static void glFinish(void){++finishes;phase=4;}
static uint64_t now_us(void){return phase;}
static void show_texture(struct eagl *e,struct image *i){(void)e;(void)i;}
static void target_to_surface(struct eagl *e,struct image *i){
 assert(i->drawn);i->drawn=false;
 if(i->shared||i->mirror){assert(e->producer_transfer&&phase<2);phase=1;}
 else {assert(!e->producer_transfer&&phase>=2);++copied;}
}
static int redfin_eagl_publish_surfaces(const struct rf_gu_target *t,unsigned n){
 assert(n==2&&t[0].handle==3&&t[0].surface==19&&t[1].handle==5&&t[1].surface==23);
 assert(phase==2);++published;phase=3;return !failed;
}
static void redfin_eagl_direct_frame(unsigned f,unsigned d,unsigned m,int notified){
 assert(f==2&&d==1&&m==1);direct_count=d;mirror_count=m;(void)notified;
}
#include "eagl-direct-frame.inc"
int main(void){
 for(unsigned failure=0;failure<2;++failure)for(unsigned finish=0;finish<2;++finish)
  for(unsigned blocking=0;blocking<2;++blocking)for(unsigned foreign=0;foreign<2;++foreign){
   struct eagl e={.images={{true,true,true,0,3,19},{true,true,false,8,5,23},{true,true,false,0,0,27}},.image_count=3,.frames=1,.in_frame=true};
   if(foreign)e.images[0].producer=0;
   copied=seed_locks=finishes=flushes=published=phase=direct_count=mirror_count=0;
   failed=failure;wait_for_frames=blocking;uint64_t waited=0;unsigned in_place=0;
   assert(redfin_eagl_produce_frame(&e,finish,&waited,&in_place)==1);
   assert(in_place==2&&copied==1&&flushes==1&&published==!foreign);
   assert(finishes==(finish||blocking||failure||foreign));assert(seed_locks==((failure||foreign)?2u:0u));
   assert(!e.producer_transfer&&direct_count==1&&mirror_count==1);
  }
 return 0;
}
''')

    def test_direct_evidence_requires_real_current_native_frames_and_announcements(self):
        boot='0123456789abcdef'
        requested=f'REDFIN COMPOSITOR: boot={boot} process=backboardd requested=gles'
        hardware=f'REDFIN EAGL ABI: boot={boot} renderer=FD620'
        frame=f'REDFIN EAGL FRAME: boot={boot} pid=61 frame=120 draws=32 triangles=60 shared=1 copied=0 errors=0'
        direct=f'REDFIN EAGL DIRECT FRAME: boot={boot} pid=61 frame=120 direct=1 mirrored=0 producer-notified=1'
        self.assertTrue(analyze([requested,hardware,frame,direct],boot)['direct_surface_GPU_composition'])
        for bad in (direct.replace('producer-notified=1','producer-notified=0'),direct.replace('mirrored=0','mirrored=1'),
                    direct.replace(boot,'fedcba9876543210'),direct.replace('direct=1','direct=0')):
            self.assertFalse(analyze([requested,hardware,frame,bad],boot)['direct_surface_GPU_composition'])
        self.assertFalse(analyze([requested,hardware,direct],boot)['direct_surface_GPU_composition'])


if __name__=='__main__':unittest.main()
