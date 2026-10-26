"""Actual allocator/CPU handoff/FIFO receivers for owned WC IOSurfaces."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from test_smp_gui import patched_source
from ports.redfin.test_usb_owned_route import added_file

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NATIVE = ROOT / 'research/redfin-gpu/surface-cache-native-v1'

TYPES = r'''
#include <cstdint>
#include <cstddef>
#include <cassert>
enum {kIOMapDefaultCache=0,kIOMapWriteCombineCache=4};
struct IOMemoryDescriptor {
 uint64_t length=1228800;virtual ~IOMemoryDescriptor(){}uint64_t getLength(){return length;}
};
struct IOBufferMemoryDescriptor:public IOMemoryDescriptor {};
#define OSDynamicCast(type,value) dynamic_cast<type *>(value)
struct SweetSurface {
 IOMemoryDescriptor *memory=nullptr;uint64_t redfinRenderExtent=1217792,scanoutPhys=0;
 uint32_t allocSize=1228800,cacheMode=0,mapCache=kIOMapWriteCombineCache,wrapDelta=0,parentID=0;
 int scanoutSlot=-1;bool wrapped=false,redfinWriteCombined=true;
 unsigned releases=0;void release(){++releases;}
};
#include "surface-cache.h"
'''


class SurfaceCacheTests(unittest.TestCase):
    def compile_run(self, source):
        with tempfile.TemporaryDirectory(prefix='redfin-surface-cache-') as directory:
            directory = Path(directory)
            path = directory / 'receiver.cpp'
            path.write_text(source)
            built = subprocess.run(['c++', '-std=c++17', '-O2', '-Wall', '-Wextra',
                '-Werror', '-Wno-misleading-indentation', '-Wno-missing-field-initializers',
                '-I'+str(HERE), '-I'+str(HERE/'include'), str(path), '-o', str(directory/'receiver')],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(directory/'receiver')], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            return run.stdout

    def native(self, target):
        path = NATIVE / target
        if not path.is_file():
            self.skipTest('exact current full native preimage fixture unavailable')
        return path.read_text()

    def test_actual_owned_mapping_proof_rejects_each_cached_or_foreign_alias(self):
        self.compile_run(TYPES+r'''
int main(){
 for(unsigned fault=0;fault<20;++fault){
  IOBufferMemoryDescriptor memory,other;IOMemoryDescriptor foreign;
  SweetSurface surface;surface.memory=&memory;IOMemoryDescriptor *request=&memory;
  uint64_t bytes=surface.allocSize;SweetSurface *owner=&surface;
  switch(fault){
   case 0:break;case 1:surface.redfinWriteCombined=false;break;
   case 2:surface.memory=&other;break;case 3:surface.allocSize-=16384;break;
   case 4:memory.length-=16384;break;case 5:surface.mapCache=kIOMapDefaultCache;break;
   case 6:surface.cacheMode=1;break;case 7:surface.redfinRenderExtent=0;break;
   case 8:surface.wrapped=true;break;case 9:surface.wrapDelta=64;break;
   case 10:surface.parentID=1;break;case 11:surface.scanoutPhys=4096;break;
   case 12:surface.scanoutSlot=0;break;case 13:surface.memory=request=&foreign;break;
   case 14:request=nullptr;break;case 15:owner=nullptr;break;case 16:bytes=0;break;
   case 17:bytes-=16384;break;case 18:request=&other;break;case 19:bytes=UINT64_MAX;break;
  }
  assert(redfin_surface_write_combined(owner,request,bytes)==(fault==0));
 }
 redfin_surface_cache_barrier();return 0;
}
''')

    def test_actual_allocator_selects_attributes_before_mapping_and_balances_every_failure(self):
        self.compile_run(r'''
#include <cstdint>
#include <cstddef>
#include <cassert>
using SInt64=int64_t;using IOOptionBits=uint64_t;
enum {kIODirectionInOut=1,kIOMemoryKernelUserShared=2,kIOMapWriteCombineCache=4};
static int kernel_task;static uint64_t page_size=16384;
static uint64_t sweet_surface_wired;
static constexpr uint64_t SWEET_SURFACE_WIRED_MAX=128*1024*1024;
static unsigned calls,releases,mode;static uint64_t seen_options,seen_bytes,seen_alignment;
static SInt64 OSAddAtomic64(SInt64 change,volatile SInt64 *value){SInt64 old=*value;*value=old+change;return old;}
struct IOBufferMemoryDescriptor {
 uint64_t length;uint64_t getLength(){return length;}
 void release(){++releases;}
 static IOBufferMemoryDescriptor *inTaskWithOptions(int task,IOOptionBits options,uint64_t bytes,uint64_t alignment){
  assert(task==kernel_task);++calls;seen_options=options;seen_bytes=bytes;seen_alignment=alignment;
  static IOBufferMemoryDescriptor memory;memory.length=bytes+(mode==2?16384:0);
  return mode==1?nullptr:&memory;
 }
};
#define OSSafeReleaseNULL(value) do{(value)->release();(value)=nullptr;}while(0)
#include "surface-cache-allocator.inc"
int main(){
 for(unsigned wc=0;wc<2;++wc)for(mode=0;mode<4;++mode){
  calls=releases=0;sweet_surface_wired=32768;bool exhausted=mode==3;
  uint32_t bytes=exhausted?SWEET_SURFACE_WIRED_MAX:1228800;
  IOBufferMemoryDescriptor *memory=sweet_redfin_owned_memory(bytes,wc);
  bool success=mode==0;assert((memory!=nullptr)==success);
  assert(sweet_surface_wired==32768+(success?bytes:0));
  assert(calls==(exhausted?0:1));assert(releases==(mode==2?1:0));
  if(calls){assert(seen_bytes==bytes&&seen_alignment==page_size);
   assert(seen_options==(kIODirectionInOut|kIOMemoryKernelUserShared|(wc?kIOMapWriteCombineCache:0)));}
 }
 return 0;
}
''')

    def test_actual_surface_lock_keeps_gpu_wait_and_unlock_orders_cpu_publication(self):
        native = self.native('iokit/Kernel/arm/SweetSurface.cpp')
        lock = function(native, 'IOReturn\nIOSurfaceRootUserClient::trapLock(')
        unlock = function(native, 'IOReturn\nIOSurfaceRootUserClient::trapUnlock(')
        self.compile_run(TYPES+r'''
using IOReturn=int;
enum {kIOReturnSuccess=0,kIOReturnNotFound=1,kIOReturnNotReady=2,kIOSurfaceLockReadOnly=1};
#ifndef __unused
#define __unused __attribute__((unused))
#endif
static SweetSurface *held;static bool gpu_done;static unsigned waits,barriers,seeds,ordinal,barrier_at,seed_at;
static SweetSurface *sweet_surface_held(void *,void *,uint32_t){return held;}
static int redfin_gpu_queue_memory_barrier(void *memory){assert(held&&memory==held->memory);++waits;return gpu_done?0:kIOReturnNotReady;}
static void receiver_cache_barrier(){++barriers;barrier_at=++ordinal;}
#define redfin_surface_cache_barrier receiver_cache_barrier
static IOReturn sweet_surface_seed_out(SweetSurface *,void *,bool){++seeds;seed_at=++ordinal;return 0;}
struct IOSurfaceRootUserClient {
 void *fLock=nullptr,*fRefs=nullptr;
 IOReturn trapLock(void *,void *,void *,void *,void *,void *);
 IOReturn trapUnlock(void *,void *,void *,void *,void *,void *);
};
'''+lock+'\n'+unlock+r'''
int main(){
 IOBufferMemoryDescriptor memory;SweetSurface surface;surface.memory=&memory;held=&surface;
 IOSurfaceRootUserClient client;
 gpu_done=false;
 assert(client.trapLock(nullptr,nullptr,nullptr,nullptr,nullptr,nullptr)==kIOReturnNotReady);
 assert(waits==1&&!barriers&&!seeds&&surface.releases==1);
 gpu_done=true;
 assert(!client.trapLock(nullptr,nullptr,nullptr,nullptr,nullptr,nullptr));
 assert(waits==2&&barriers==1&&seeds==1&&barrier_at<seed_at);
 assert(!client.trapUnlock(nullptr,nullptr,nullptr,nullptr,nullptr,nullptr));
 assert(barriers==2&&seeds==2&&barrier_at<seed_at);
 surface.redfinWriteCombined=false;
 assert(!client.trapLock(nullptr,nullptr,nullptr,nullptr,nullptr,nullptr));
 assert(!client.trapUnlock(nullptr,nullptr,nullptr,nullptr,nullptr,nullptr));
 assert(waits==3&&barriers==2&&seeds==4&&surface.releases==5);
 held=nullptr;assert(client.trapLock(nullptr,nullptr,nullptr,nullptr,nullptr,nullptr)==kIOReturnNotFound);
 return 0;
}
''')

    def test_actual_wc_worker_keeps_real_completion_while_cached_aliases_still_quiesce(self):
        native = self.native('iokit/Kernel/arm/RedfinGPUQueue.inc')
        first = native.index('IOReturn RedwoodGPUUserClient::executeQueued(')
        last = native.index('\nvoid RedwoodGPUUserClient::retireQueued(', first)
        receiver = (HERE/'gpu-physical-worker-host.cpp').read_text()
        fields = r'''
enum {kIOMapWriteCombineCache=4};
struct IOMemoryDescriptor {uint64_t length=16384;virtual ~IOMemoryDescriptor(){}uint64_t getLength(){return length;}};
struct IOBufferMemoryDescriptor:public IOMemoryDescriptor {};
#define OSDynamicCast(type,value) dynamic_cast<type *>(value)
struct fake_surface {
 fake_state *state;IOMemoryDescriptor *memory=nullptr;uint32_t allocSize=16384,mapCache=4,cacheMode=0,wrapDelta=0,parentID=0;
 uint64_t redfinRenderExtent=16384,scanoutPhys=0;int scanoutSlot=-1;bool redfinWriteCombined=false,wrapped=false;
};
using SweetSurface=fake_surface;
#include "surface-cache.h"
'''
        receiver = receiver.replace('struct fake_surface {fake_state *state;};', fields)
        receiver = receiver.replace('struct gpu_buffer {fake_surface *surface=nullptr;',
            'struct gpu_buffer {IOMemoryDescriptor *memory=nullptr;uint64_t size=16384;fake_surface *surface=nullptr;')
        receiver = receiver.replace('uint64_t cleaning=0,submitting=0,invalidating=0;',
            'uint64_t cleaning=0,submitting=0,invalidating=0,wc_clean=0,wc_invalidate=0,wc_clean_bytes=0,wc_invalidate_bytes=0;')
        receiver = receiver.replace('#include "actual-physical-methods.inc"', native[first:last])
        scenario = r'''
    reset(2);IOBufferMemoryDescriptor wc_memory;fake_state wc_state;fake_surface wc_surface{&wc_state};gpu_buffer wc_buffer;
    wc_surface.memory=&wc_memory;wc_surface.redfinWriteCombined=true;
    wc_buffer.memory=&wc_memory;wc_buffer.surface=&wc_surface;wc_buffer.clientMapped=true;wc_buffer.pending=2;
    a=make_job(1,&client);b=make_job(2,&client);a.nr_bos=b.nr_bos=1;
    a.bos[0]=b.bos[0]={&wc_buffer,RF_GA_WRITE};enqueue(&a);enqueue(&b);run();
    REQUIRE(overlap==1&&pending_max==2&&done==2&&!wc_buffer.pending);
    REQUIRE(!clean_calls&&!invalidations&&!quiesces&&gTiming.wc_clean==2&&gTiming.wc_invalidate==2);
    REQUIRE(gTiming.wc_clean_bytes==32768&&gTiming.wc_invalidate_bytes==32768);
'''
        receiver = receiver.replace('    puts("actual physical worker:', scenario+'\n    puts("actual physical worker:')
        self.assertIn('cache/error/stop/retirement PASS', self.compile_run(receiver))

    def test_complete_overlay_matches_owned_files_and_exact_current_source(self):
        patch = (HERE/'native-surface-cache.patch').read_text()
        for owned, target in (
            ('surface-cache.h', 'iokit/Kernel/arm/RedfinSurfaceCache.h'),
            ('surface-cache-allocator.inc', 'iokit/Kernel/arm/RedfinSurfaceCacheAllocator.inc'),
        ):
            self.assertEqual(added_file(patch, target), (HERE/owned).read_text())
            self.assertEqual(patched_source(target), (HERE/owned).read_text())
        base = ROOT/'research/redfin-gpu/surface-cache-base-v1'
        if not base.is_dir():
            self.skipTest('exact actual native preimages unavailable')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            shutil.copytree(base, directory, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))
            check = subprocess.run(['git', 'apply', '--check', str(HERE/'native-surface-cache.patch')],
                cwd=directory, capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)
            subprocess.run(['git', 'apply', str(HERE/'native-surface-cache.patch')],
                cwd=directory, check=True, capture_output=True)
            for path in NATIVE.rglob('*'):
                if path.is_file() and path.name != 'source-proof.json':
                    self.assertEqual((directory/path.relative_to(NATIVE)).read_bytes(), path.read_bytes())

    def test_surface_cache_records_fit_the_native_logger(self):
        files = ('iokit/Kernel/arm/RedfinGPU.cpp', 'iokit/Kernel/arm/RedfinGPUDisplay.inc',
                 'iokit/Kernel/arm/SweetSurface.cpp')
        formats = []
        for target in files:
            formats += re.findall(r'IOLog\("(REDFIN (?:SURFACE CACHE|GPU SURFACE CACHE|GPU OUTPUT CACHE):[^"\n]+)"', self.native(target))
        self.assertEqual(len(formats), 3)
        for value in formats:
            value = value.replace('%llu', str(2**64-1)).replace('%u', str(2**32-1))
            self.assertNotIn('%', value)
            self.assertLessEqual(len(value.replace(r'\n', '\n').encode()), 255)


if __name__ == '__main__':
    unittest.main()
