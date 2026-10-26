"""Actual Mesa publication and adapted GLES handoff preserve GPU ownership."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from ports.redfin.eagl_userland import adapt_source
from ports.redfin.compositor_evidence import analyze

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class GLESPublicationTests(unittest.TestCase):
    def run_c(self,source):
        with tempfile.TemporaryDirectory(prefix='redfin-gles-publication-') as directory:
            folder=Path(directory);path=folder/'test.c';path.write_text(source)
            built=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(path),'-o',str(folder/'test')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            run=subprocess.run([str(folder/'test')],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_mesa_drains_cpu_thread_and_materializes_kernel_fence_without_waiting_for_GPU(self):
        self.run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#define __APPLE__ 1
#define GLAPI
#define GLAPIENTRY
struct pipe_fence_handle {unsigned kfence;};
struct pipe_context;
struct pipe_screen {
 const char *(*get_name)(struct pipe_screen *);
 void (*fence_reference)(struct pipe_screen *,struct pipe_fence_handle **,struct pipe_fence_handle *);
};
struct pipe_context {struct pipe_screen *screen;void (*flush)(struct pipe_context *,struct pipe_fence_handle **,unsigned);};
struct st_context {struct pipe_context *pipe;};
struct osmesa_context {struct st_context *st;};
typedef struct osmesa_context *OSMesaContext;
static OSMesaContext current;
static unsigned phase,flushes,releases,publication_error,no_fence;
static const char *renderer;
static struct pipe_fence_handle native;
static OSMesaContext OSMesaGetCurrentContext(void){return current;}
static const char *name(struct pipe_screen *screen){assert(screen);return renderer;}
static void flush(struct pipe_context *pipe,struct pipe_fence_handle **fence,unsigned flags){
 assert(pipe&&flags==0&&phase==0);++flushes;phase=1;
 *fence=no_fence?NULL:&native;
}
int redfin_freedreno_fence_publish(struct pipe_fence_handle *fence){
 assert(phase==1&&fence==&native);phase=2;
 if(publication_error)return -1;
 fence->kfence=19;return 0; /* real admission, GPU still has not run */
}
static void reference(struct pipe_screen *screen,struct pipe_fence_handle **fence,struct pipe_fence_handle *next){
 assert(screen&&!next&&(phase==2||no_fence));++releases;*fence=next;
}
#include "gles-publication.inc"
int main(void){
 struct pipe_screen screen={name,reference};struct pipe_context pipe={&screen,flush};
 struct st_context st={&pipe};struct osmesa_context context={&st};
 assert(redfin_gl_frame_publish()==-1&&!flushes);
 current=&context;
 const char *names[]={NULL,"softpipe","llvmpipe","FD610","FD620"};
 for(unsigned n=0;n<5;++n)for(unsigned failure=0;failure<3;++failure){
  renderer=names[n];publication_error=failure==1;no_fence=failure==2;
  phase=flushes=releases=native.kfence=0;
  int result=redfin_gl_frame_publish();
  assert(result==((n==4&&!failure)?0:-1));
  assert(flushes==(n==4)&&releases==(n==4));
  assert(native.kfence==((n==4&&!failure)?19:0));
 }
 current->st=NULL;assert(redfin_gl_frame_publish()==-1);
 context.st=&st;st.pipe=NULL;assert(redfin_gl_frame_publish()==-1);
 return 0;
}
''')

    def test_upstream_handoff_publishes_before_display_and_preserves_finish_and_failure_fallback(self):
        source=ROOT/'research/hackios-upstream/userland/userland/src/eagl.c'
        if not source.is_file():self.skipTest('pinned upstream EAGL fixture absent')
        adapted=adapt_source(source.read_text(),{})
        start=adapted.index('\tif (in_place != 0 && !finished && wait_for_frames)')
        end=adapted.index('\twaited = now_us();',start)
        branch=adapted[start:end]
        publisher=function((HERE/'eagl-guard.c').read_text(),'int redfin_eagl_publish_frame(')
        self.run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#define REDFIN_GLES_PUBLICATION 1
static unsigned published_frames,publication_fallbacks,finishes,flushes;
static unsigned long long boot_nonce=1;
static int result;
static int getpid(void){return 61;}
static int dprintf(int fd,const char *format,...){(void)fd;(void)format;return 0;}
static void glFinish(void){++finishes;}
static int redfin_gl_frame_publish(void){++flushes;return result;}
'''+publisher+'''
static void frame(unsigned in_place,bool finished,bool wait_for_frames,bool sync_frames){
'''+branch+r'''
}
int main(void){
 for(unsigned place=0;place<2;++place)for(unsigned finished=0;finished<2;++finished)
  for(unsigned blocking=0;blocking<2;++blocking)for(unsigned sync=0;sync<2;++sync)
   for(unsigned failed=0;failed<2;++failed){
    result=failed?-1:0;published_frames=publication_fallbacks=finishes=flushes=0;
    frame(place,finished,blocking,sync);
    bool active=place&&!finished;
    bool publish=active&&!blocking&&sync;
    assert(flushes==publish&&published_frames==(publish&&!failed));
    assert(publication_fallbacks==(publish&&failed));
    assert(finishes==(active&&(blocking||(sync&&failed))));
   }
 return 0;
}
''')

    def test_actual_display_admission_requires_current_Redfin_FIFO_versions(self):
        guard=function((HERE/'eagl-guard.c').read_text(),'int redfin_eagl_display_waits(')
        self.run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define REDFIN_GLES_PUBLICATION 1
typedef unsigned io_service_t;
static unsigned fault,queries,releases;
static unsigned long long boot_nonce;
static int dprintf(int fd,const char *format,...){(void)fd;(void)format;return 0;}
static const char *IOServiceMatching(const char *name){assert(!strcmp(name,"RedwoodGPU"));return name;}
static io_service_t IOServiceGetMatchingService(unsigned port,const char *name){assert(!port&&name);++queries;return fault==1?0:17;}
static void IOObjectRelease(io_service_t service){assert(service==17);++releases;}
static bool display_number(io_service_t service,const char *name,int expected){
 const char *names[]={"RedfinPresentationStatisticsABI","chip-id","RedfinRuntimeABI","RedfinQueuedSubmissionABI","RedfinScopedWaitABI"};
 for(unsigned i=0;i<5;++i)if(!strcmp(name,names[i])){
  assert(service==(i?17:9));assert(expected==(i==0?2:i==1?0x06020001:1));
  return fault!=i+2;
 }
 assert(0);return false;
}
'''+guard+r'''
int main(void){
 boot_nonce=0;assert(!redfin_eagl_display_waits(9)&&!queries);
 boot_nonce=1;assert(!redfin_eagl_display_waits(0)&&!queries);
 for(fault=0;fault<7;++fault){
  queries=releases=0;assert(redfin_eagl_display_waits(9)==(fault==0));
  assert(queries==(fault!=2)&&releases==(fault!=1&&fault!=2));
 }
 return 0;
}
''')

    def test_activity_evidence_cannot_confuse_requested_policy_with_real_publication(self):
        boot='0123456789abcdef'
        driver=f'REDFIN EAGL PRESENT: boot={boot} driver-waits=1'
        row=f'REDFIN EAGL PUBLISH: boot={boot} pid=61 published=120 fallbacks=0 result=0 GPU-wait=0'
        self.assertFalse(analyze([driver],boot)['asynchronous_GLES_handoff'])
        self.assertTrue(analyze([driver,row],boot)['asynchronous_GLES_handoff'])
        for bad in (row.replace('fallbacks=0','fallbacks=1'),row.replace('result=0','result=-1'),
                    row.replace('GPU-wait=0','GPU-wait=1'),row.replace(boot,'fedcba9876543210')):
            self.assertFalse(analyze([driver,bad],boot)['asynchronous_GLES_handoff'])


if __name__=='__main__':unittest.main()
