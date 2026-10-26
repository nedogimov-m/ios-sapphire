"""Actual physical line hazards and the retained native cache-maintenance path."""
import ctypes as C
from pathlib import Path
import tempfile
import unittest

from test_gpu_scope import compile_host
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class ResourceAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.library=compile_host(Path(cls.temp.name),'access',r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "redfin_gpu_access.h"
_Static_assert(2*sizeof(uint64_t)*RF_GW_PAGES+sizeof(uint32_t)*RF_GW_PAGES+
 sizeof(struct rf_ga_fine)*RF_GA_FINE_PAGES<20u*1024u*1024u,"bounded metadata footprint");
int run(unsigned which) {
 struct rf_ga_history h={0};h.use=calloc(RF_GW_PAGES,8);h.write=calloc(RF_GW_PAGES,8);
 h.fine_index=calloc(RF_GW_PAGES,4);h.capacity=2;h.fine=calloc(h.capacity,sizeof(*h.fine));
 assert(rf_ga_valid(&h));uint32_t pages[]={2,0,9},alias[]={0,2};uint64_t out=999;
 if(which==0) {
  assert(!rf_ga_mark_span(&h,pages,3,0,64,12288,1,RF_GA_READ));
  assert(!rf_ga_target(&h,pages,3,0,64,12288,RF_GA_READ,&out)&&!out);
  assert(!rf_ga_target(&h,pages,3,0,64,12288,RF_GA_WRITE,&out)&&out==1);
  assert(!rf_ga_target(&h,pages,3,64,64,12288,RF_GA_RW,&out)&&!out);
  assert(!rf_ga_mark_span(&h,pages,3,64,64,12288,2,RF_GA_WRITE));
  assert(!rf_ga_target(&h,pages,3,0,64,12288,RF_GA_READ,&out)&&!out);
  assert(!rf_ga_target(&h,pages,3,64,64,12288,RF_GA_READ,&out)&&out==2);
  assert(!rf_ga_target(&h,alias,2,4096+64,64,8192,RF_GA_READ,&out)&&out==2);
 }
 if(which==1) {
  assert(!rf_ga_mark_span(&h,pages,3,63,2,12288,7,RF_GA_WRITE));
  assert(!rf_ga_target(&h,pages,3,0,1,12288,RF_GA_READ,&out)&&out==7);
  assert(!rf_ga_target(&h,pages,3,127,1,12288,RF_GA_READ,&out)&&out==7);
  assert(!rf_ga_target(&h,pages,3,128,1,12288,RF_GA_READ,&out)&&!out);
 }
 if(which==2) {
  assert(!rf_ga_mark_span(&h,pages,3,4095,2,12288,8,RF_GA_WRITE));
  assert(!rf_ga_target(&h,alias,2,0,1,8192,RF_GA_READ,&out)&&out==8);
  assert(!rf_ga_target(&h,pages,3,4032,64,12288,RF_GA_READ,&out)&&out==8);
  assert(!rf_ga_target(&h,pages,3,3968,64,12288,RF_GA_READ,&out)&&!out);
 }
 if(which==3) {
  assert(!rf_ga_mark_pages(&h,pages,3,4,RF_GA_WRITE));
  assert(!rf_ga_mark_span(&h,pages,3,0,1,12288,5,RF_GA_READ));
  assert(!rf_ga_target(&h,pages,3,256,1,12288,RF_GA_READ,&out)&&out==4);
  assert(!rf_ga_mark_pages(&h,pages,3,6,RF_GA_READ));
  assert(!rf_ga_target(&h,pages,3,256,1,12288,RF_GA_READ,&out)&&out==4);
  assert(!rf_ga_target(&h,pages,3,256,1,12288,RF_GA_WRITE,&out)&&out==6);
  assert(!rf_ga_mark_pages(&h,pages,3,7,RF_GA_WRITE));
  assert(!rf_ga_target(&h,pages,3,256,1,12288,RF_GA_READ,&out)&&out==7);
 }
 if(which==4) {
  h.capacity=0;
  assert(!rf_ga_mark_span(&h,pages,3,0,1,12288,3,RF_GA_WRITE));
  assert(!h.allocated&&h.fallbacks==1);
  assert(!rf_ga_target(&h,pages,3,128,1,12288,RF_GA_READ,&out)&&out==3);
  h.capacity=1;
  assert(!rf_ga_mark_span(&h,pages,3,4096,1,12288,4,RF_GA_READ));
  assert(!rf_ga_mark_span(&h,pages,3,8192,1,12288,5,RF_GA_WRITE));
  assert(h.allocated==1&&h.fallbacks==2);
  assert(!rf_ga_target(&h,pages,3,8192+128,1,12288,RF_GA_READ,&out)&&out==5);
 }
 if(which==5) {
  uint32_t bad[]={2,(uint32_t)RF_GW_PAGES};
  assert(rf_ga_mark_pages(&h,bad,2,99,RF_GA_RW)==EINVAL&&!h.use[2]);
  assert(rf_ga_mark_span(&h,pages,3,UINT64_MAX,1,12288,99,RF_GA_RW)==EINVAL);
  assert(rf_ga_mark_span(&h,pages,3,12287,2,12288,99,RF_GA_RW)==EINVAL);
  assert(rf_ga_mark_span(&h,pages,3,0,1,12288,99,4)==EINVAL&&!h.use[2]);
  assert(rf_ga_target(&h,pages,3,0,1,12288,8,&out)==EINVAL);
  h.fine_index[2]=1;assert(rf_ga_mark_span(&h,pages,3,0,1,12288,99,RF_GA_RW)==EINVAL);
 }
 if(which==6) {
  assert(!rf_ga_mark_span(&h,pages,3,0,64,12288,9,RF_GA_WRITE));
  assert(!rf_ga_mark_span(&h,pages,3,0,64,12288,2,RF_GA_WRITE));
  assert(!rf_ga_target(&h,pages,3,0,64,12288,RF_GA_READ,&out)&&out==9);
  assert(!rf_ga_target(&h,pages,3,0,4096,12288,RF_GA_READ,&out)&&out==9);
  assert(!rf_ga_target(&h,pages,3,64,64,12288,0,&out)&&!out);
  assert(rf_ga_access(0,0,false)==RF_GA_RW&&rf_ga_access(3,0,true)==RF_GA_RW);
  assert(rf_ga_access(3,RF_GA_READ,true)==RF_GA_READ&&rf_ga_access(3,RF_GA_READ,false)==RF_GA_RW);
 }
 free(h.use);free(h.write);free(h.fine_index);free(h.fine);return 0;
}
''')
        cls.library.run.argtypes=[C.c_uint]

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_read_read_overlap_and_adjacent_cache_lines(self):self.assertEqual(self.library.run(0),0)
    def test_unaligned_cache_line_boundaries(self):self.assertEqual(self.library.run(1),0)
    def test_cross_page_physical_aliases(self):self.assertEqual(self.library.run(2),0)
    def test_whole_page_baselines_preserve_prior_writes(self):self.assertEqual(self.library.run(3),0)
    def test_exhausted_fine_pool_keeps_conservative_hazards(self):self.assertEqual(self.library.run(4),0)
    def test_overflow_and_corruption_reject_before_mutation(self):self.assertEqual(self.library.run(5),0)
    def test_monotonic_sequences_and_legacy_access(self):self.assertEqual(self.library.run(6),0)

    def test_actual_scoped_surface_cache_maintenance_preserves_adjacent_lines(self):
        actual=function((HERE/'gpu-throughput-queue.inc').read_text(),'static bool gpuQueuedSurfaceCache(')
        with tempfile.TemporaryDirectory() as directory:
            lib=compile_host(Path(directory),'cache',r'''
#include <assert.h>
#include <stdint.h>
#include <vector>
#include "redfin_gpu_access.h"
struct gpu_buffer {void *kernel;uint64_t size;};
struct gpu_queued_bo {gpu_buffer *buffer;uint32_t handle,flags,access;};
struct gpu_queued_job {gpu_queued_bo *bos;rf_gw_submit_range *ranges;uint32_t nr_ranges;bool typed;};
static struct {uint64_t cleaned,invalidated;} gTiming;
struct span {uintptr_t address;uint64_t bytes;};static std::vector<span> clean,invalid;
static void redfin_gpu_sync(void *p,uint64_t bytes,bool invalidate){assert(invalidate);clean.push_back({(uintptr_t)p,bytes});}
static void redfin_gpu_invalidate(void *p,uint64_t bytes){invalid.push_back({(uintptr_t)p,bytes});}
static bool poisoned=false;static void redfin_gpu_poison(const char *){poisoned=true;}
'''+actual+r'''
extern "C" int run(void){
 gpu_buffer buffer={(void *)0x100000,4096};gpu_queued_bo bo={&buffer,1,3,3};
 rf_gw_submit_range ranges[]={{0,1,0,64},{0,2,95,1}};
 gpu_queued_job job={&bo,ranges,2,true};
 assert(gpuQueuedSurfaceCache(&job,0,false)&&clean.size()==2);
 assert(clean[0].address==0x100000&&clean[0].bytes==64);
 assert(clean[1].address==0x100040&&clean[1].bytes==64);
 assert(gpuQueuedSurfaceCache(&job,0,true)&&invalid.size()==1);
 assert(invalid[0].address==0x100040&&invalid[0].bytes==64&&gTiming.invalidated==64);
 job.typed=false;assert(gpuQueuedSurfaceCache(&job,0,true)&&invalid.size()==3);
 job.nr_ranges=0;assert(gpuQueuedSurfaceCache(&job,0,true)&&invalid.back().bytes==4096);
 job.nr_ranges=2;ranges[1].offset=4095;ranges[1].bytes=2;
 assert(!gpuQueuedSurfaceCache(&job,0,true)&&poisoned);return 0;
}
''',True)
            self.assertEqual(lib.run(),0)


if __name__=='__main__':unittest.main()
