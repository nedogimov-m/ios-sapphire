"""Execute actual Mesa admission/publication with bounded native shared merges."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from test_gpu_scope import compile_host

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class NativeSharedMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        root=Path(cls.temp.name)
        base=ROOT/'research/redfin-metal-throughput-v1/mesa-25.0.7'
        if not base.is_dir():
            cls.temp.cleanup()
            raise unittest.SkipTest('cached native Mesa25.0.7 source is absent')
        names=('src/freedreno/drm/freedreno_ringbuffer_sp.c',
               'src/freedreno/drm/msm/msm_pipe.c',
               'src/freedreno/drm/msm/msm_ringbuffer_sp.c')
        for name in names:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((base/name).read_bytes())
        subprocess.run(['git','apply',str(HERE/'mesa-submit-merge.patch')],
                       cwd=root,check=True,capture_output=True)
        actual=(root/names[0]).read_text()
        methods=''.join(function(actual,signature) for signature in (
            'static bool\nshould_defer(',
            'static struct fd_fence *\nfd_submit_sp_flush(',
            'void\nfd_pipe_sp_flush('))
        for suffix in ('h','inc'):
            (root/('redfin_mesa_submit_merge.'+suffix)).write_bytes(
                (HERE/('mesa-submit-merge.'+suffix)).read_bytes())
        source=r'''
#include <assert.h>
#include <stdint.h>
#include <limits.h>
#include <pthread.h>
#include <vector>
#include "redfin_gpu_runtime.h"
#include "redfin_mesa_submit_merge.h"
static_assert(REDFIN_MSM_MERGE_COMMANDS==RF_GR_COMMANDS,"actual kernel primary-IB bound");
struct fd_submit;
struct list_node {fd_submit *owner;};
struct list_head {std::vector<fd_submit *> values;};
struct fd_fence {unsigned references=1;bool use_fence_fd=false,published=false;};
struct fd_device {list_head deferred_submits;unsigned deferred_cmds=0;fd_fence *deferred_submits_fence=nullptr;int submit_lock=0;std::vector<unsigned> groups;};
struct fd_pipe {fd_device *dev;bool no_implicit_sync=true;uint32_t last_enqueue_fence=0,last_submit_fence=0;};
struct fd_ringbuffer {struct {unsigned nr_cmds=0;} u;};
struct fd_submit {fd_pipe *pipe;fd_ringbuffer *primary;uint32_t fence;list_node node;unsigned refs=1;};
struct fd_submit_sp {fd_submit base;unsigned nr_bos=0,nr_suballoc_bos=0;bool shared=true;};
static fd_submit_sp *to_fd_submit_sp(fd_submit *s){return reinterpret_cast<fd_submit_sp *>(s);}
static fd_ringbuffer *to_fd_ringbuffer_sp(fd_ringbuffer *r){return r;}
static unsigned fd_ringbuffer_cmd_count(fd_ringbuffer *r){return r->u.nr_cmds+1;}
#define foreach_submit(s,h) for(fd_submit *s:(h)->values)
#define MESA_TRACE_FUNC() ((void)0)
#define DEBUG_MSG(...) ((void)0)
static pthread_mutex_t flush_mtx=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t flush_cnd=PTHREAD_COND_INITIALIZER;
static bool list_is_empty(list_head *h){return h->values.empty();}
static fd_submit *last_submit(list_head *h){return h->values.back();}
static fd_submit *fd_submit_ref(fd_submit *s){++s->refs;return s;}
static void list_addtail(list_node *n,list_head *h){h->values.push_back(n->owner);}
static void simple_mtx_lock(int *p){assert(!*p);*p=1;}
static void simple_mtx_unlock(int *p){assert(*p);*p=0;}
static bool fd_fence_before(uint32_t a,uint32_t b){return (int32_t)(a-b)<0;}
static bool fd_fence_after(uint32_t a,uint32_t b){return fd_fence_before(b,a);}
static fd_fence *fd_fence_new(fd_pipe *,bool fd){auto *f=new fd_fence;f->use_fence_fd=fd;return f;}
static fd_fence *fd_fence_ref(fd_fence *f){++f->references;return f;}
static void fd_fence_del(fd_fence *f){assert(f->references);if(!--f->references)delete f;}
static bool fd_submit_sp_flush_prep(fd_submit *s,int,fd_fence *) {
 ++s->primary->u.nr_cmds;return to_fd_submit_sp(s)->shared;
}
static unsigned fd_dev_count_deferred_cmds(fd_device *d) {
 unsigned n=0;foreach_submit(s,&d->deferred_submits)n+=fd_ringbuffer_cmd_count(s->primary);return n;
}
static bool fd_device_threaded_submit(fd_device *){return false;}
/* Only the external backend is stubbed: record publication rather than
 * simulating GPU completion. Native completion remains the kernel contract. */
static void flush_deferred_submits(fd_device *dev) {
 if(list_is_empty(&dev->deferred_submits))return;
 unsigned commands=0;fd_pipe *pipe=last_submit(&dev->deferred_submits)->pipe;
 foreach_submit(s,&dev->deferred_submits) {
  assert(s->pipe==pipe);commands+=s->primary->u.nr_cmds;
  pipe->last_submit_fence=s->fence;assert(s->refs==2);--s->refs;
 }
 assert(commands<=RF_GR_COMMANDS);dev->groups.push_back(commands);
 dev->deferred_submits_fence->published=true;
 fd_fence_del(dev->deferred_submits_fence);dev->deferred_submits_fence=nullptr;
 dev->deferred_submits.values.clear();dev->deferred_cmds=0;
}
#include "redfin_mesa_submit_merge.inc"
/* ACTUAL_MESA_METHODS */
struct group {
 fd_device dev;fd_pipe a{&dev},b{&dev};
 std::vector<fd_submit_sp *> objects;std::vector<fd_fence *> fences;
 fd_fence *append(fd_pipe *pipe,unsigned bos=2,unsigned views=0,unsigned commands=1) {
  auto *s=new fd_submit_sp;auto *r=new fd_ringbuffer;r->u.nr_cmds=commands-1;
  s->base={pipe,r,pipe->last_enqueue_fence+1,{&s->base},1};s->nr_bos=bos;s->nr_suballoc_bos=views;
  objects.push_back(s);auto *f=fd_submit_sp_flush(&s->base,-1,false);fences.push_back(f);return f;
 }
 ~group() {
  assert(list_is_empty(&dev.deferred_submits));
  for(auto *f:fences)fd_fence_del(f);
  for(auto *s:objects){assert(s->base.refs==1);delete s->base.primary;delete s;}
 }
};
extern "C" int contract(unsigned which) {
 if(which==0) {
  group g;for(unsigned i=0;i<7;++i)g.append(&g.a);
  assert(g.dev.groups.empty());for(auto *f:g.fences)assert(f==g.fences[0]&&!f->published);
  fd_pipe_sp_flush(&g.a,7);assert(g.dev.groups==std::vector<unsigned>{7});
  for(auto *f:g.fences)assert(f->published);return 0;
 }
 if(which==1) {
  group g;g.a.no_implicit_sync=false;
  for(unsigned i=0;i<7;++i){auto *f=g.append(&g.a);assert(f->published);}
  assert(g.dev.groups==std::vector<unsigned>(7,1));return 0;
 }
 if(which==2) {
  group g;for(unsigned i=0;i<3;++i)g.append(&g.a);
  g.append(&g.b);assert(g.dev.groups==std::vector<unsigned>{3});
  fd_pipe_sp_flush(&g.b,1);assert((g.dev.groups==std::vector<unsigned>{3,1}));return 0;
 }
 if(which==3) {
  group g;for(unsigned i=0;i<128;++i)g.append(&g.a);
  assert(g.dev.groups.empty());g.append(&g.a);
  assert(g.dev.groups==std::vector<unsigned>{128});
  fd_pipe_sp_flush(&g.a,129);assert((g.dev.groups==std::vector<unsigned>{128,1}));return 0;
 }
 if(which==4 || which==5) {
  group g;unsigned bos=which==4?600:2,views=which==5?5000:0;
  g.append(&g.a,bos,views);g.append(&g.a,bos,views);
  assert(g.dev.groups==std::vector<unsigned>{1});
  fd_pipe_sp_flush(&g.a,2);assert((g.dev.groups==std::vector<unsigned>{1,1}));return 0;
 }
 if(which==6) {
  redfin_msm_merge_budget b{};assert(redfin_msm_merge_add(&b,128,1024,7168));
  auto old=b;assert(!redfin_msm_merge_add(&b,1,0,0));
  assert(b.commands==old.commands&&b.bos==old.bos&&b.ranges==old.ranges);
  for(unsigned i=0;i<3;++i) {
   redfin_msm_merge_budget z{};
   uint64_t values[3]={1,1,0};values[i]=UINT64_MAX;
   assert(!redfin_msm_merge_add(&z,values[0],values[1],values[2]));
   assert(!z.commands&&!z.bos&&!z.ranges);
  }
  assert(!redfin_msm_merge_add(nullptr,1,1,0));return 0;
 }
 if(which==7) {
  group g;g.append(&g.a,10,0,64);g.append(&g.a,10,0,64);
  assert(g.dev.groups.empty());fd_pipe_sp_flush(&g.a,1);
  assert(g.dev.groups==std::vector<unsigned>{128});
  assert(g.a.last_submit_fence==2);fd_pipe_sp_flush(&g.a,2);
  assert(g.dev.groups.size()==1);return 0;
 }
 return -1;
}
'''.replace('/* ACTUAL_MESA_METHODS */',methods)
        cls.library=compile_host(root,'merge',source,True)
        cls.library.contract.argtypes=[C.c_uint]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_shared_passes_publish_as_one_actual_ordered_group(self):
        self.assertEqual(self.library.contract(0),0)

    def test_unopted_shared_buffers_keep_immediate_publication(self):
        self.assertEqual(self.library.contract(1),0)

    def test_queue_priority_boundary_flushes_predecessors(self):
        self.assertEqual(self.library.contract(2),0)

    def test_129th_primary_flushes_before_admission(self):
        self.assertEqual(self.library.contract(3),0)

    def test_aggregate_backing_bo_bound_flushes_before_admission(self):
        self.assertEqual(self.library.contract(4),0)

    def test_aggregate_suballocation_range_bound_flushes_before_admission(self):
        self.assertEqual(self.library.contract(5),0)

    def test_overflow_rejection_does_not_change_budget(self):
        self.assertEqual(self.library.contract(6),0)

    def test_cpu_or_final_fence_flush_publishes_whole_multi_ib_group(self):
        self.assertEqual(self.library.contract(7),0)


if __name__=='__main__':unittest.main()
