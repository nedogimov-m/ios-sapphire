"""Actual physical dependencies, Mesa view ownership and native FIFO presentation."""
import ctypes as C
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_display_geometry import function

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def compile_host(root,name,source,cpp=False):
    path=root/(name+('.cpp' if cpp else '.c'));path.write_text(source)
    library=root/(name+'.so')
    result=subprocess.run(['c++' if cpp else 'cc','-std=c++17' if cpp else '-std=c11',
        '-O2','-shared','-fPIC','-pthread','-Wall','-Wextra','-Werror',
        '-Wno-unused-function','-Wno-misleading-indentation',
        *(['-Wno-missing-field-initializers'] if cpp else []),'-I',str(HERE),
        '-I',str(HERE/'include'),str(path),'-o',str(library)],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    return C.CDLL(str(library))


class PhysicalScopeTests(unittest.TestCase):
    def test_complete_native_owner_and_output_records_fit_the_actual_logger(self):
        # Real hardware lost the old record's total and units at255 bytes.
        # Bound the production formats at full argument type maxima, including
        # newline; useful prefixes alone must never count as a whole record.
        formats = []
        for name in ('gpu-throughput-queue.inc', 'gpu-display.inc'):
            formats.extend(re.findall(r'IOLog\("(REDFIN GPU (?:OWNER(?: ID)?|OUTPUT):[^"\n]+)"',
                                      (HERE/name).read_text()))
        self.assertEqual(len(formats), 3)
        maxima = {'%llu': str(2**64-1), '%u': str(2**32-1),
                  '%x': 'ffffffff', '%d': str(-2**31), '%c': 'R', '%s': 'x'*19}
        for value in formats:
            for spec, maximum in maxima.items():
                value = value.replace(spec, maximum)
            self.assertNotIn('%', value)
            self.assertTrue(value.endswith(r'\n'))
            self.assertLessEqual(len(value.replace(r'\n','\n').encode()), 255)

    def test_final_owned_native_wait_and_presentation_sources_match_the_compiled_overlay(self):
        from test_smp_gui import patched_source
        for target,owned in (
            ('RedfinGPUWaits.h','include/redfin_gpu_scope.h'),
            ('RedfinGPUAccess.h','include/redfin_gpu_access.h'),
            ('RedfinGPUScopedWaits.inc','gpu-scoped-waits.inc'),
            ('RedfinGPUQueuedPresent.inc','gpu-queued-present.inc'),
            ('RedfinGPUQueue.inc','gpu-throughput-queue.inc')):
            self.assertEqual(patched_source('iokit/Kernel/arm/'+target),(HERE/owned).read_text())

    def test_actual_pages_aliases_subranges_overflow_and_immutable_source_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            library=compile_host(Path(directory),'physical',r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "redfin_gpu_scope.h"
#include "redfin_gpu_runtime.h"
static unsigned calls;static bool valid=true;
static bool verify(void *p){assert(p==&valid);++calls;return valid;}
int run(void) {
 _Static_assert(sizeof(struct rf_gw_cpu_range)==40,"CPU range wire");
 _Static_assert(sizeof(struct rf_gw_submit_range)==24,"submit range wire");
 _Static_assert(sizeof(struct rf_gw_submit_extension)==16,"submit extension wire");
 uint64_t *history=calloc(RF_GW_PAGES,sizeof(*history));assert(history);
 uint32_t pages[]={0,2,3,100},alias[]={2,20},index=999,first=999,count=999;
 assert(!rf_gw_index(RF_GW_RAM_BASE,&index)&&!index);
 assert(!rf_gw_index(RF_GW_RAM_BASE+RF_GW_RAM_BYTES-4096,&index)&&index==RF_GW_PAGES-1);
 for(unsigned i=0;i<3;i++) {
  uint64_t bad[]={RF_GW_RAM_BASE-4096,RF_GW_RAM_BASE+1,RF_GW_RAM_BASE+RF_GW_RAM_BYTES};
  assert(rf_gw_index(bad[i],&index)==EINVAL);
 }
 assert(!rf_gw_span(4095,2,16384,&first,&count)&&first==0&&count==2);
 assert(!rf_gw_mark_span(history,pages,4,4096,1,16384,7));
 uint64_t target=999;
 assert(!rf_gw_target(history,pages,4,0,4096,16384,&target)&&!target);
 assert(!rf_gw_target(history,alias,2,0,1,8192,&target)&&target==7);
 assert(!rf_gw_mark_span(history,pages,4,8192,4096,16384,10));
 assert(!rf_gw_target(history,alias,2,0,4096,8192,&target)&&target==7);
 assert(!rf_gw_target(history,pages,4,0,16384,16384,&target)&&target==10);
 assert(!rf_gw_mark_span(history,pages,4,4096,1,16384,4)&&history[2]==7);
 uint32_t bad_pages[]={0,(uint32_t)RF_GW_PAGES};
 assert(rf_gw_mark(history,bad_pages,2,99)==EINVAL&&!history[0]);
 assert(rf_gw_mark_span(history,pages,4,UINT64_MAX,2,16384,99)==EINVAL);
 assert(rf_gw_target(history,pages,4,16384,1,16384,&target)==EINVAL);
 assert(rf_gw_target(history,pages,1,0,8192,16384,&target)==EINVAL);
 assert(rf_gw_mark_span(history,pages,4,16383,2,16384,99)==EINVAL);
 free(history);
 struct rf_gr_payload_cache cache={0};
 assert(rf_gr_payload_live(&cache,1,false,&valid,verify)&&calls==1);
 assert(rf_gr_payload_live(&cache,2,false,&valid,verify)&&calls==1&&cache.hits==1);
 assert(rf_gr_payload_live(&cache,RF_GR_PAYLOAD_RECHECK_NS,false,&valid,verify)&&calls==1);
 assert(rf_gr_payload_live(&cache,RF_GR_PAYLOAD_RECHECK_NS+1,false,&valid,verify)&&calls==2);
 assert(rf_gr_payload_live(&cache,RF_GR_PAYLOAD_RECHECK_NS+2,true,&valid,verify)&&calls==3);
 valid=false;assert(!rf_gr_payload_live(&cache,RF_GR_PAYLOAD_RECHECK_NS+3,true,&valid,verify)&&calls==4);
 valid=true;assert(!rf_gr_payload_live(&cache,RF_GR_PAYLOAD_RECHECK_NS+4,true,&valid,verify)&&calls==4);
 struct rf_gr_payload_cache backwards={0};
 assert(rf_gr_payload_live(&backwards,100,false,&valid,verify));
 assert(!rf_gr_payload_live(&backwards,99,false,&valid,verify)&&backwards.failed);
 return 0;
}
''')
            self.assertEqual(library.run(),0)

    def test_actual_kernel_fifo_presentation_scoped_cpu_waits_and_source_lifetime(self):
        queue=(HERE/'gpu-throughput-queue.inc').read_text()
        prefix=queue[:queue.index('static void gpuPhysicalRetire(')]
        worker=function(queue,'static void gpuPhysicalRetire(')+'\n'+(HERE/'gpu-physical-worker.inc').read_text()
        methods=''.join(function(queue,s) for s in (
            'IOReturn RedwoodGPUUserClient::submit(',
            'void RedwoodGPUUserClient::retireQueued(',
            'IOReturn RedwoodGPUUserClient::prepareRange(',
            'IOReturn RedwoodGPUUserClient::prepareQueued(',
            'extern "C" int redfin_gpu_queue_memory_barrier('))
        text=(HERE/'gpu-scope-host.cpp').read_text().replace(
            '/* ACTUAL_QUEUE_DECLARATIONS_AND_WAIT */',prefix).replace(
            '/* ACTUAL_QUEUE_WORKER */',worker).replace(
            '/* ACTUAL_CLIENT_RETIREMENT_AND_PREPARATION */',methods)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'RedfinGPUScopedWaits.inc').write_bytes((HERE/'gpu-scoped-waits.inc').read_bytes())
            library=compile_host(root,'native',text,True)
            self.assertEqual(library.queue_contract(),0)
            self.assertEqual(library.read_only_contract(),0)
            self.assertEqual(library.typed_submit_contract(),0)

    def test_actual_mesa_merge_preserves_view_refs_and_explicit_whole_backing_use(self):
        # Execute the same final append functions as the real patched Mesa.
        old=ROOT/'research/redfin-metal-queued-v8/mesa-25.0.7'
        if not old.is_dir():self.skipTest('cached native Mesa25.0.7 preimage is not installed')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);name='src/freedreno/drm/freedreno_ringbuffer_sp.c'
            path=root/name;path.parent.mkdir(parents=True);path.write_bytes((old/name).read_bytes())
            subprocess.run(['git','apply','--include='+name,str(HERE/'metal-scoped-submission.patch')],
                           cwd=root,check=True,capture_output=True)
            actual=path.read_text()
            funcs=''.join(function(actual,s) for s in (
                'static inline bool\ncheck_append_suballoc_bo(',
                'static inline uint32_t\ncheck_append_bo(',
                'uint32_t\nfd_submit_append_bo(',
                'uint32_t fd_submit_append_bo_backing('))
            prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "redfin_gpu_scope.h"
#define __APPLE__ 1
#define unlikely(x) (x)
#define READ_ONCE(x) (x)
struct fd_bo {uint32_t idx;unsigned refs;uint64_t size,iova;fd_bo *parent;};
static bool suballoc_bo(fd_bo *b){return b->parent!=nullptr;}
static fd_bo *fd_bo_heap_block(fd_bo *b){assert(b->parent);return b->parent;}
static uint64_t fd_bo_get_iova(fd_bo *b){return b->iova;}
static fd_bo *fd_bo_ref(fd_bo *b){++b->refs;return b;}
struct hash_entry {void *key,*data;};struct hash_table {hash_entry entry[64];unsigned count;};
static uint32_t _mesa_hash_pointer(void *p){return (uint32_t)(uintptr_t)p;}
static hash_entry *_mesa_hash_table_search_pre_hashed(hash_table *t,uint32_t hash,void *p){
 (void)hash;for(unsigned i=0;i<t->count;++i)if(t->entry[i].key==p)return &t->entry[i];return nullptr;}
static void _mesa_hash_table_insert_pre_hashed(hash_table *t,uint32_t hash,void *p,void *data){
 (void)hash;assert(t->count<64);t->entry[t->count++]={p,data};}
struct fd_submit_sp {
 fd_bo *bos[64]={},*suballoc_bos[64]={};unsigned nr_bos=0,nr_suballoc_bos=0;
 uint64_t redfin_direct_bos[RF_GW_MAX_BOS/64]={};
 hash_table native_table={},view_table={};hash_table *bo_table=&native_table,*suballoc_bo_table=&view_table;
};
#define APPEND(s,field,value) ([&]{assert((s)->nr_##field<64);unsigned n=(s)->nr_##field++;(s)->field[n]=(value);return n;}())
static bool fd_submit_redfin_direct(const fd_submit_sp *s,unsigned i){
 return i>=RF_GW_MAX_BOS||(s->redfin_direct_bos[i/64]&(UINT64_C(1)<<(i%64)));}
struct fd_device {int fd;};struct fd_pipe {fd_device *dev;};
struct drm_msm_gem_submit {
 uint32_t flags,fence,nr_bos,nr_cmds;uint64_t bos,cmds;int32_t fd;uint32_t queue;
 uint64_t in_sync,out_sync;uint32_t nr_in,nr_out,stride,pad;
};
static rf_gw_submit_range captured[RF_GW_MAX_RANGES];static unsigned captured_count,calls;
static int redwood_drm_submit_scoped(int fd,void *request,size_t bytes,const rf_gw_submit_range *ranges,uint32_t n){
 assert(fd==9&&bytes==72&&n<=RF_GW_MAX_RANGES);++calls;captured_count=n;
 memcpy(captured,ranges,n*sizeof(*ranges));((drm_msm_gem_submit *)request)->fence=77;return 0;}
'''
            suffix=r'''
static void release(fd_submit_sp *s){
 for(unsigned i=0;i<s->nr_bos;++i)assert(--s->bos[i]->refs>=1);
 for(unsigned i=0;i<s->nr_suballoc_bos;++i)assert(--s->suballoc_bos[i]->refs>=1);
}
extern "C" int run(void){
 fd_bo native={UINT32_MAX,1,65536,0x10000,nullptr},other={UINT32_MAX,1,8192,0x30000,nullptr};
 fd_bo a={UINT32_MAX,1,2048,0x12000,&native},b={UINT32_MAX,1,1024,0x15000,&native};
 fd_submit_sp target,deferred;fd_device device={9};fd_pipe pipe={&device};
 unsigned index=fd_submit_append_bo(&target,&a);assert(index==0&&!fd_submit_redfin_direct(&target,index));
 fd_submit_append_bo(&deferred,&b);fd_submit_append_bo(&deferred,&other);
 redfin_msm_merge_scoped(&target,&deferred);assert(target.nr_bos==2&&target.nr_suballoc_bos==2);
 assert(!fd_submit_redfin_direct(&target,0)&&fd_submit_redfin_direct(&target,1));
 release(&deferred);assert(b.refs==2&&native.refs==2&&other.refs==2);
 drm_msm_gem_submit request={};request.nr_bos=target.nr_bos;
 assert(!redfin_msm_submit_scoped(&target,&pipe,&request)&&request.fence==77&&captured_count==3);
 assert(captured[0].bo==0&&captured[0].offset==8192&&captured[0].bytes==2048);
 assert(captured[1].bo==0&&captured[1].offset==20480&&captured[1].bytes==1024);
 assert(captured[2].bo==1&&!captured[2].offset&&captured[2].bytes==8192);
 /* Explicit use of the backing allocation must dominate narrower views. */
 fd_submit_append_bo(&target,&native);assert(fd_submit_redfin_direct(&target,0));
 assert(!redfin_msm_submit_scoped(&target,&pipe,&request)&&captured_count==2);
 assert(captured[0].bo==0&&!captured[0].offset&&captured[0].bytes==65536);
 release(&target);assert(native.refs==1&&other.refs==1&&a.refs==1&&b.refs==1);
 fd_submit_sp invalid;b.iova=native.iova-1;fd_submit_append_bo(&invalid,&b);
 request={};request.nr_bos=invalid.nr_bos;unsigned before=calls;
 assert(redfin_msm_submit_scoped(&invalid,&pipe,&request)==-1&&errno==EINVAL&&calls==before&&!request.fence);
 release(&invalid);assert(native.refs==1&&b.refs==1);return 0;
}
'''
            library=compile_host(root,'mesa',prefix+funcs+(HERE/'mesa-scoped-submit.inc').read_text()+suffix,True)
            self.assertEqual(library.run(),0)


if __name__=='__main__':unittest.main()
