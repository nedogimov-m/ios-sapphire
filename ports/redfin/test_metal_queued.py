"""Actual ticket/epoch code and native queue admission/retirement contracts."""
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

from ports.redfin.test_usb_owned_route import added_file

HERE=Path(__file__).resolve().parent


class MetalQueuedTests(unittest.TestCase):
    def run_c(self,source,headers=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,content in (headers or {}).items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
            (root/'test.c').write_text(source)
            built=subprocess.run(['cc','-std=c11','-O2','-pthread','-Wall','-Wextra','-Werror',
                '-I'+str(root),'-I'+str(HERE),str(root/'test.c'),'-o',str(root/'test')],capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr.decode(errors='replace'))
            ran=subprocess.run([str(root/'test')],capture_output=True,timeout=15)
            self.assertEqual(ran.returncode,0,ran.stderr.decode(errors='replace'))

    def test_native_budget_deadlines_and_failed_predecessor_dont_release_later_jobs(self):
        self.run_c(r'''
#include <assert.h>
#include "include/redfin_gpu_queue.h"
int main(void) {
 struct rf_gq_budget budget={0};
 for(unsigned i=0;i<RF_GQ_MAX_JOBS;++i)assert(!rf_gq_reserve(&budget,4096));
 assert(rf_gq_reserve(&budget,1)==EAGAIN);
 for(unsigned i=0;i<RF_GQ_MAX_JOBS;++i)assert(!rf_gq_unreserve(&budget,4096));
 assert(!budget.jobs&&!budget.bytes&&rf_gq_unreserve(&budget,1)==EINVAL);
 assert(!rf_gq_reserve(&budget,RF_GQ_MAX_BYTES)&&rf_gq_reserve(&budget,1)==EAGAIN);
 assert(!rf_gq_unreserve(&budget,RF_GQ_MAX_BYTES));
 assert(rf_gq_reserve(&budget,RF_GQ_MAX_BYTES+1)==EINVAL);
 struct rf_gq_client q={0};uint32_t a=0,b=0,c=0;
 assert(!rf_gq_accept(&q,&a)&&a==1&&!rf_gq_accept(&q,&b)&&b==2);
 assert(rf_gq_status(&q,a)==EAGAIN&&rf_gq_status(&q,b)==EAGAIN);
 assert(rf_gq_retire(&q,b,0)==EPROTO&&q.pending==2);
 assert(!rf_gq_retire(&q,a,EIO)&&rf_gq_status(&q,a)==EIO);
 assert(rf_gq_status(&q,b)==EAGAIN&&q.pending==1); /* still owns backing pages */
 assert(rf_gq_accept(&q,&c)==ECANCELED);
 assert(!rf_gq_retire(&q,b,ECANCELED)&&rf_gq_status(&q,b)==EIO&&!q.pending);
 q=(struct rf_gq_client){0};assert(!rf_gq_accept(&q,&a));q.closing=true;
 assert(rf_gq_accept(&q,&b)==ECANCELED&&rf_gq_status(&q,a)==EAGAIN);
 assert(!rf_gq_retire(&q,a,0)&&!rf_gq_status(&q,a));
 uint64_t end=0;
 assert(!rf_gq_deadline(0,0,100,&end)&&end==0);
 assert(!rf_gq_deadline(INT64_MAX,999999999,100,&end)&&end==100+RF_GQ_WAIT_NS);
 assert(!rf_gq_deadline(0,101,100,&end)&&end==101);
 assert(rf_gq_deadline(-1,0,100,&end)==EINVAL&&rf_gq_deadline(1,1000000000,100,&end)==EINVAL);
 return 0;
}
''')

    def test_exact_owned_kernel_queue_sources_are_compiled_by_the_overlay(self):
        patch=(HERE/'native-queued-submission.patch').read_text()
        for owned,native in [('include/redfin_gpu_queue.h','RedfinGPUQueue.h'),
                             ('gpu-queued-submission.inc','RedfinGPUQueue.inc')]:
            self.assertEqual((HERE/owned).read_text(),added_file(patch,'iokit/Kernel/arm/'+native))

    def test_published_fence_wait_never_touches_the_mutable_encoder_flush_path(self):
        name='src/freedreno/drm/freedreno_pipe.c'
        baseline=HERE.parents[1]/'research/redfin-metal-bindings-v1/mesa-25.0.7'/name
        if not baseline.is_file():self.skipTest('private reviewed Mesa baseline is absent')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/name;target.parent.mkdir(parents=True);shutil.copy2(baseline,target)
            applied=subprocess.run(['git','apply','--include='+name,str(HERE/'metal-queued-submission.patch')],
                                   cwd=directory,capture_output=True)
            self.assertEqual(applied.returncode,0,applied.stderr.decode(errors='replace'))
            source=target.read_text();first=source.index('void\nfd_fence_flush(');last=source.index('\n}\n',first)+3
            function=source[first:last]
        self.run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
struct fd_pipe {unsigned mutable_encoder_state;};
struct util_queue_fence {bool ready;};
struct fd_fence {struct fd_pipe *pipe;uint32_t ufence;struct util_queue_fence ready;uint32_t kfence;};
static unsigned flushes,waits;static struct fd_fence *admitted;
static bool util_queue_fence_is_signalled(struct util_queue_fence *f){return f->ready;}
static void util_queue_fence_wait(struct util_queue_fence *f){++waits;assert(f->ready);}
static void fd_pipe_flush(struct fd_pipe *p,uint32_t f){assert(p&&f);++p->mutable_encoder_state;++flushes;admitted->ready.ready=true;admitted->kfence=8;}
#define MESA_TRACE_FUNC() ((void)0)
'''+function+r'''
int main(void) {
 struct fd_pipe pipe={0};struct fd_fence f={&pipe,1,{true},7};admitted=&f;
 fd_fence_flush(&f);assert(!flushes&&!waits&&!pipe.mutable_encoder_state);
 /* Actual Mesa constructor: ready starts signalled, kfence is still zero.
  * Private BO submits may remain deferred until this explicit publication. */
 f.kfence=0;fd_fence_flush(&f);assert(flushes==1&&waits==1&&pipe.mutable_encoder_state==1&&f.kfence==8);
 fd_fence_flush(&f);assert(flushes==1&&waits==1&&pipe.mutable_encoder_state==1);
 f.ready.ready=false;fd_fence_flush(&f);assert(flushes==2&&waits==2&&pipe.mutable_encoder_state==2);
 return 0;
}
''')

    def test_real_ticket_wait_once_epochs_cpu_visibility_error_and_close(self):
        self.run_c(r'''
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "metal-queued.h"
#include "metal-ordering.h"
#include "metal-command-scope.h"
#define MAX2(a,b) ((a)>(b)?(a):(b))
#define RWA_FENCE_TIMEOUT_NS 2000000000ull
#define PIPE_BARRIER_SHADER_BUFFER 1
#define PIPE_BARRIER_CONSTANT_BUFFER 2
#define PIPE_BARRIER_VERTEX_BUFFER 4
#define PIPE_BARRIER_INDEX_BUFFER 8
#define PIPE_BARRIER_TEXTURE 16
#define PIPE_BARRIER_IMAGE 32
#define PIPE_BARRIER_UPDATE_BUFFER 64
#define PIPE_BARRIER_UPDATE_TEXTURE 128
struct pipe_fence_handle {pthread_mutex_t mutex;pthread_cond_t condition;bool signaled,fail;unsigned waits;};
struct pipe_constant_buffer {void *buffer;unsigned buffer_offset,buffer_size;};
struct pipe_framebuffer_state {unsigned dummy;};
struct pipe_context {
 void (*flush)(struct pipe_context *,struct pipe_fence_handle **,unsigned);
 void (*set_framebuffer_state)(struct pipe_context *,const struct pipe_framebuffer_state *);
 void (*memory_barrier)(struct pipe_context *,unsigned);
 void *const_uploader;
};
struct pipe_screen {
 bool (*fence_finish)(struct pipe_screen *,void *,struct pipe_fence_handle *,uint64_t);
 void (*fence_reference)(struct pipe_screen *,struct pipe_fence_handle **,struct pipe_fence_handle *);
};
struct pipe_resource;
struct rwa_buffer {struct rwa_device *device;struct rwa_buffer *all_next;bool gpu_pending,gpu_visible;uint64_t gpu_write_epoch;};
struct rwa_texture {struct rwa_texture *buffer_next;bool buffer_pending;uint64_t buffer_write_epoch;};
struct rwa_device {
 struct pipe_context *pipe;struct pipe_screen *screen;struct redfin_metal_command_scope command_scope;
 struct rwa_buffer *all_buffers;struct rwa_texture *buffer_textures;
 uint64_t ordering[REDFIN_METAL_ORDERING_WORDS],issued_epoch,encoding_epoch,completed_epoch,gpu_memory_epoch;
 bool gpu_memory_pending,queued_closing,queued_failed;unsigned queued_owners,ubo_offset_align;
 struct rwa_redfin_completion *queued_tickets;
};
static unsigned destroyed,drains,resolve_error,allocation_failure;
static struct pipe_fence_handle *next_fence;
static void say(char *why,size_t n,const char *text){if(why&&n)snprintf(why,n,"%s",text);}
static int command_scope_finish(void *context,char *why,size_t n){(void)context;(void)why;(void)n;++drains;return 0;}
static bool rwa_redfin_buffers_share(const struct rwa_buffer *a,const struct rwa_buffer *b){return a==b;}
static int rwa_redfin_queued_drain(struct rwa_device *,char *,size_t);
static void rwa_redfin_device_destroy(struct rwa_device *d){assert(!d->queued_owners);++destroyed;}
static void rwa_redfin_bindings_clear(struct rwa_device *d){(void)d;}
static int rwa_redfin_linear_resolve_all(struct rwa_device *d,char *w,size_t n){(void)d;(void)w;(void)n;return resolve_error?-1:0;}
static void rwa_redfin_trace_end(struct rwa_device *d){(void)d;}
static bool rwa_redfin_trace_selected(void){return false;}
static int rwa_redfin_fence_publish(struct rwa_device *d,struct pipe_fence_handle *f){(void)d;(void)f;return 0;}
static void u_upload_data(void *u,unsigned a,unsigned b,unsigned c,const void *data,unsigned *off,struct pipe_resource **r)
 {(void)u;(void)a;(void)b;(void)c;(void)data;*off=0;*r=NULL;}
static void u_upload_unmap(void *u){(void)u;}
/* Helpers unrelated to tickets remain compiled, but are not a CPU/GPU model. */
#pragma clang diagnostic ignored "-Wunused-function"
#include "metal-ordering.inc"
static int rwa_commands_end(struct rwa_device *d,char *why,size_t n) {
 int error=rwa_redfin_cpu_drain(d,why,n);d->command_scope.active=false;d->encoding_epoch=0;return error;
}
static void *ticket_calloc(size_t n,size_t s){if(allocation_failure){allocation_failure=0;return NULL;}return calloc(n,s);}
#define calloc ticket_calloc
#include "metal-queued.inc"
#undef calloc
static void flush(struct pipe_context *p,struct pipe_fence_handle **out,unsigned flags){(void)p;(void)flags;if(out)*out=next_fence;}
static void framebuffer(struct pipe_context *p,const struct pipe_framebuffer_state *s){(void)p;(void)s;}
static bool fence_finish(struct pipe_screen *s,void *ctx,struct pipe_fence_handle *f,uint64_t timeout) {
 (void)s;(void)ctx;(void)timeout;pthread_mutex_lock(&f->mutex);++f->waits;
 pthread_cond_broadcast(&f->condition);
 while(!f->signaled)pthread_cond_wait(&f->condition,&f->mutex);
 bool result=!f->fail;pthread_mutex_unlock(&f->mutex);return result;
}
static void fence_ref(struct pipe_screen *s,struct pipe_fence_handle **p,struct pipe_fence_handle *f){(void)s;*p=f;}
static void signal_fence(struct pipe_fence_handle *f){pthread_mutex_lock(&f->mutex);f->signaled=true;pthread_cond_broadcast(&f->condition);pthread_mutex_unlock(&f->mutex);}
static void wait_entered(struct pipe_fence_handle *f){pthread_mutex_lock(&f->mutex);while(!f->waits)pthread_cond_wait(&f->condition,&f->mutex);pthread_mutex_unlock(&f->mutex);}
static void *waiter(void *t){char why[128]={0};return (void *)(intptr_t)rwa_redfin_completion_wait(t,why,sizeof(why));}
static void *consumer(void *d){char why[128]={0};return (void *)(intptr_t)rwa_redfin_cpu_drain(d,why,sizeof(why));}
static void scope(struct rwa_device *d,uint64_t epoch){assert(!redfin_metal_scope_begin(&d->command_scope));d->issued_epoch=d->encoding_epoch=epoch;d->command_scope.pending=true;}
int main(void) {
 struct pipe_context pipe={.flush=flush,.set_framebuffer_state=framebuffer};struct pipe_screen screen={fence_finish,fence_ref};
 struct rwa_device d={.pipe=&pipe,.screen=&screen};struct rwa_buffer b={.device=&d};struct rwa_texture t={0};
 rwa_redfin_buffer_register(&b);d.buffer_textures=&t;
 struct pipe_fence_handle first={PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,false,false,0};
 struct pipe_fence_handle second={PTHREAD_MUTEX_INITIALIZER,PTHREAD_COND_INITIALIZER,false,false,0};
 char why[128]={0};struct rwa_redfin_completion *one=NULL,*two=NULL;
 next_fence=&first;scope(&d,1);b.gpu_pending=true;b.gpu_write_epoch=1;
 assert(!rwa_redfin_commands_submit(&d,&one,why,sizeof(why))&&one&&!d.command_scope.active);
 pthread_t a,c;assert(!pthread_create(&a,NULL,waiter,one));wait_entered(&first);
 assert(!pthread_create(&c,NULL,waiter,one));
 next_fence=&second;scope(&d,2);b.gpu_pending=true;b.gpu_visible=false;b.gpu_write_epoch=2;
 t.buffer_pending=true;t.buffer_write_epoch=2;d.gpu_memory_pending=true;d.gpu_memory_epoch=2;
 assert(!rwa_redfin_commands_submit(&d,&two,why,sizeof(why))&&two&&d.queued_owners==2);
 signal_fence(&first);void *result=NULL;
 assert(!pthread_join(a,&result)&&!result&&!pthread_join(c,&result)&&!result&&first.waits==1);
 assert(!rwa_redfin_completion_retire(one,why,sizeof(why)));
 assert(b.gpu_pending&&!b.gpu_visible&&t.buffer_pending&&d.gpu_memory_pending&&d.completed_epoch==1);
 pthread_t cpu;assert(!pthread_create(&cpu,NULL,consumer,&d));wait_entered(&second);
 assert(b.gpu_pending&&t.buffer_pending);signal_fence(&second);
 assert(!pthread_join(cpu,&result)&&!result&&!b.gpu_pending&&b.gpu_visible&&!t.buffer_pending&&!d.gpu_memory_pending);
 assert(d.ordering[1]==2&&d.ordering[2]==1&&!d.queued_tickets&&!drains);
 rwa_redfin_buffer_unregister(&b);
 rwa_device_close(&d);assert(!destroyed&&d.queued_closing);
 rwa_redfin_completion_destroy(one);assert(!destroyed&&d.queued_owners==1);
 rwa_redfin_completion_destroy(two);assert(destroyed==1&&!d.queued_owners);
 /* Generic encoding refusal still retains a real ticket and actual fence. */
 struct rwa_device partial={.pipe=&pipe,.screen=&screen};next_fence=&first;resolve_error=1;scope(&partial,1);
 assert(rwa_redfin_commands_submit(&partial,&one,why,sizeof(why))<0&&one);
 assert(!rwa_redfin_completion_wait(one,why,sizeof(why)));rwa_redfin_completion_destroy(one);resolve_error=0;
 /* A native failure is memoized and permanently rejects later encoding. */
 struct rwa_device failed={.pipe=&pipe,.screen=&screen};second.fail=true;next_fence=&second;scope(&failed,1);
 unsigned waits=second.waits;assert(!rwa_redfin_commands_submit(&failed,&one,why,sizeof(why)));
 assert(rwa_redfin_completion_wait(one,why,sizeof(why))<0&&rwa_redfin_completion_wait(one,why,sizeof(why))<0);
 assert(second.waits==waits+1&&rwa_redfin_gpu_prepare(&failed,why,sizeof(why))<0);
 assert(rwa_redfin_completion_retire(one,why,sizeof(why))<0);rwa_redfin_completion_destroy(one);
 struct rwa_device missing={.pipe=&pipe,.screen=&screen};next_fence=NULL;scope(&missing,1);
 assert(rwa_redfin_commands_submit(&missing,&one,why,sizeof(why))<0&&one&&missing.queued_failed);
 assert(rwa_redfin_completion_wait(one,why,sizeof(why))<0);rwa_redfin_completion_destroy(one);
 /* No ticket on allocation failure: emitted work must take the fallback drain. */
 struct rwa_device oom={.pipe=&pipe,.screen=&screen};scope(&oom,1);allocation_failure=1;
 assert(rwa_redfin_commands_submit(&oom,&one,why,sizeof(why))<0&&!one&&!oom.command_scope.active&&drains==1);
 return 0;
}
''',{'util/u_upload_mgr.h':''})

    def test_native_deadline_uses_the_same_mach_uptime_domain_as_kernel(self):
        name='src/freedreno/drm/msm/msm_priv.h'
        baseline=HERE.parents[1]/'research/redfin-metal-bindings-v1/mesa-25.0.7'/name
        if not baseline.is_file():self.skipTest('private reviewed Mesa baseline is absent')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/name;target.parent.mkdir(parents=True);shutil.copy2(baseline,target)
            applied=subprocess.run(['git','apply','--include='+name,str(HERE/'metal-queued-submission.patch')],
                                   cwd=directory,capture_output=True)
            self.assertEqual(applied.returncode,0,applied.stderr.decode(errors='replace'))
            source=target.read_text();first=source.index('static inline void\nget_abs_timeout(');last=source.index('\n}',first)+2
            function=source[first:last]
        self.run_c(r'''
#include <assert.h>
#include <stdint.h>
#include <time.h>
#include <mach/mach_time.h>
#undef NSEC_PER_SEC
#define NSEC_PER_SEC 1000000000l
#define OS_TIMEOUT_INFINITE UINT64_MAX
struct drm_msm_timespec {int64_t tv_sec,tv_nsec;};
static int bad_scale;
static int clock_scale_fixture(mach_timebase_info_t s){s->numer=125;s->denom=6;return bad_scale;}
static uint64_t clock_ticks_fixture(void){return 60000123;}
#define mach_timebase_info clock_scale_fixture
#define mach_absolute_time clock_ticks_fixture
'''+function+r'''
int main(void) {
 struct drm_msm_timespec tv={0};const uint64_t uptime=(60000123ull*125)/6;
 get_abs_timeout(&tv,0);assert((uint64_t)tv.tv_sec*NSEC_PER_SEC+tv.tv_nsec==uptime);
 get_abs_timeout(&tv,2000000000ull);assert((uint64_t)tv.tv_sec*NSEC_PER_SEC+tv.tv_nsec==uptime+2000000000ull);
 get_abs_timeout(&tv,987654321);assert((uint64_t)tv.tv_sec*NSEC_PER_SEC+tv.tv_nsec==uptime+987654321&&tv.tv_nsec<1000000000);
 get_abs_timeout(&tv,OS_TIMEOUT_INFINITE);assert((uint64_t)tv.tv_sec*NSEC_PER_SEC+tv.tv_nsec==uptime+3600ull*NSEC_PER_SEC);
 bad_scale=1;get_abs_timeout(&tv,1);assert(tv.tv_sec<0&&tv.tv_nsec<0);
 return 0;
}
''')

    def test_cpu_prepare_uses_the_real_heap_block_for_suballocated_textures(self):
        name='src/freedreno/drm/freedreno_bo.c'
        baseline=HERE.parents[1]/'research/redfin-metal-bindings-v1/mesa-25.0.7'/name
        if not baseline.is_file():self.skipTest('private reviewed Mesa baseline is absent')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/name;target.parent.mkdir(parents=True);shutil.copy2(baseline,target)
            applied=subprocess.run(['git','apply','--include='+name,str(HERE/'metal-queued-submission.patch')],
                                   cwd=directory,capture_output=True)
            self.assertEqual(applied.returncode,0,applied.stderr.decode(errors='replace'))
            source=target.read_text();first=source.index('int\nfd_bo_cpu_prep(');last=source.index('\n}',first)+2
            function=source[first:last]
        self.run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#define FD_BO_PREP_FLUSH 8u
struct fd_pipe {unsigned unused;};struct fd_bo;
struct fd_bo_funcs {int (*cpu_prep)(struct fd_bo *,struct fd_pipe *,uint32_t);};
struct fd_bo {const struct fd_bo_funcs *funcs;struct fd_bo *parent;unsigned handle,flushes;};
static unsigned calls;static int refused;static struct fd_bo *wanted;static struct fd_pipe *wanted_pipe;
static bool suballoc_bo(struct fd_bo *b){return b->parent!=0;}
static struct fd_bo *fd_bo_heap_block(struct fd_bo *b){assert(b->parent);return b->parent;}
static void bo_flush(struct fd_bo *b){++b->flushes;}
static int native_prepare(struct fd_bo *b,struct fd_pipe *p,uint32_t op){assert(b==wanted&&p==wanted_pipe&&op==3&&b->handle==7);++calls;return refused;}
'''+function+r'''
int main(void) {
 const struct fd_bo_funcs kernel={native_prepare},suballocation={0};struct fd_pipe pipe={0};wanted_pipe=&pipe;
 struct fd_bo parent={&kernel,0,7,0},small={&suballocation,&parent,0,0};wanted=&parent;
 assert(!fd_bo_cpu_prep(&parent,&pipe,3)&&calls==1&&parent.flushes==1);
 assert(!fd_bo_cpu_prep(&small,&pipe,3|FD_BO_PREP_FLUSH)&&calls==2&&small.flushes==1);
 assert(!fd_bo_cpu_prep(&small,&pipe,FD_BO_PREP_FLUSH)&&calls==2&&small.flushes==2);
 refused=-ETIMEDOUT;assert(fd_bo_cpu_prep(&small,&pipe,3)==-ETIMEDOUT&&calls==3);
 parent.funcs=&suballocation;assert(fd_bo_cpu_prep(&small,&pipe,3)==-ENOTSUP&&calls==3);
 return 0;
}
''')


if __name__=='__main__':unittest.main()
