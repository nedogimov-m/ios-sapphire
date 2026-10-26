"""Real frame fences bound CPU admission without serializing every new frame."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin.compositor_evidence import analyze,native_budget_check
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class GLESFrameBudgetTests(unittest.TestCase):
    def test_only_explicit_GLES_backboardd_uses_the_frame_window(self):
        body=function((HERE/'eagl-guard.c').read_text(),'int redfin_eagl_frame_budget_enabled(')
        source=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include "compositor-policy.h"
static const char *program,*setting;static bool ready;
static const char *getprogname(void){return program;}
static const char *getenv(const char *name){assert(!strcmp(name,REDFIN_COMPOSITOR_ENV));return setting;}
static int redfin_eagl_producer_ready(void){return ready;}
'''+body+r'''
int main(void){
 const char *programs[]={NULL,"backboardd","SpringBoard","Photos","metal-check"};
 const char *choices[]={NULL,"gles","metal","","software"};
 for(unsigned p=0;p<5;++p)for(unsigned s=0;s<5;++s)for(unsigned r=0;r<2;++r){
  program=programs[p];setting=choices[s];ready=r;
  assert(redfin_eagl_frame_budget_enabled()==(p==1&&s==1&&r));
 }
 return 0;
}
'''
        self.run_c(source)

    def run_c(self,source):
        with tempfile.TemporaryDirectory(prefix='redfin-gles-frame-budget-') as directory:
            folder=Path(directory);path=folder/'test.c';path.write_text(source)
            result=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(path),'-o',str(folder/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(folder/'test')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_actual_two_frame_window_waits_the_oldest_real_completion_and_owns_syncs(self):
        source=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef unsigned GLenum;
struct sync {unsigned owner,serial;bool deleted,done;};
typedef struct sync *GLsync;
static unsigned current,finished,waited,deleted,answer;
static void glDeleteSync(GLsync s){assert(s&&s->owner==current&&!s->deleted);s->deleted=true;++deleted;}
static GLenum glClientWaitSync(GLsync s,unsigned flags,uint64_t timeout){
 assert(s&&s->owner==current&&!s->deleted&&!flags&&timeout==UINT64_C(2000000000));
 waited=s->serial;
 if(answer==0x911a)assert(s->done);
 if(answer==0x911c)s->done=true;
 return answer;
}
static void glFinish(void){++finished;}
#include "gles-frame-budget.h"
int main(void){
 struct rf_gl_frame_budget a={0},b={0};struct sync s[200]={0};current=1;answer=0x911c;
 for(unsigned frame=1;frame<=80;++frame){
  unsigned before=waited;
  assert(rf_gl_frame_begin(&a));
  if(frame<=2)assert(waited==before&&!deleted&&!finished);
  else assert(waited==frame-2&&s[frame-2].done&&s[frame-2].deleted);
  s[frame]=(struct sync){1,frame,false,false};assert(rf_gl_frame_publish(&a,&s[frame]));
  assert(a.count==(frame==1?1u:2u)&&a.maximum<=2&&!a.disabled&&!a.fallbacks);
  /* A second current context must neither wait nor delete the first one's
   * fence, even when both use the same kernel GPU connection. */
  current=2;assert(rf_gl_frame_begin(&b));assert(!b.count);current=1;
 }
 assert(a.waits==78&&a.completed==78&&!a.already&&!finished);
 /* Deleting a sync object is not DMA completion. Destruction releases GL
  * ownership while the driver's retained jobs keep the pending resources. */
 assert(!s[79].done&&!s[80].done);rf_gl_frame_clear(&a);
 assert(s[79].deleted&&s[80].deleted&&!s[79].done&&!s[80].done&&!a.count);
 assert(deleted==80&&!finished);
 for(unsigned fault=0;fault<5;++fault){
  memset(&a,0,sizeof(a));memset(s,0,sizeof(s));finished=waited=deleted=0;
  s[1]=(struct sync){1,1,false,true};s[2]=(struct sync){1,2,false,false};
  assert(rf_gl_frame_publish(&a,&s[1])&&rf_gl_frame_publish(&a,&s[2]));
  answer=fault==0?0x911a:fault==1?0x911c:fault==2?0x911b:0x911d;
  if(fault==4){s[1].deleted=true;a.fences[0]=NULL;}
  bool ok=rf_gl_frame_begin(&a);assert(ok==(fault<2));
  if(ok)assert(a.count==1&&!a.disabled&&!finished&&deleted==1);
  else {
   assert(!a.count&&a.disabled&&a.fallbacks==1&&finished==1);
   assert(!rf_gl_frame_begin(&a)&&finished==1);
  }
  rf_gl_frame_clear(&a);
 }
 /* An unrecordable new fence must get a real full wait before its reference
  * can be dropped; reaching the bound cannot silently evict pending work. */
 for(unsigned missing=0;missing<2;++missing){
  memset(&a,0,sizeof(a));memset(s,0,sizeof(s));finished=deleted=0;
  for(unsigned n=1;n<=3;++n)s[n]=(struct sync){1,n,false,false};
  if(!missing){assert(rf_gl_frame_publish(&a,&s[1]));assert(rf_gl_frame_publish(&a,&s[2]));}
  assert(!rf_gl_frame_publish(&a,missing?NULL:&s[3]));
  assert(finished==1&&a.disabled&&!a.count&&a.fallbacks==1&&deleted==(missing?0u:3u));
 }
 return 0;
}
'''
        self.run_c(source)

    def test_evidence_requires_actual_bounded_current_frames_and_native_pixels(self):
        boot='0123456789abcdef'
        line=f'REDFIN EAGL BUDGET: boot={boot} pid=61 frame=120 bound=2 pending=2 maximum=2 waits=118 already=8 completed=110 fallbacks=0 real-GL-fences=1'
        self.assertTrue(analyze([line],boot)['real_GLES_frame_budget'])
        for bad in (line.replace('bound=2','bound=16'),line.replace('pending=2','pending=3'),
                    line.replace('fallbacks=0','fallbacks=1'),line.replace('waits=118','waits=119'),
                    line.replace('real-GL-fences=1','real-GL-fences=0'),line.replace(boot,'fedcba9876543210')):
            self.assertFalse(analyze([bad],boot)['real_GLES_frame_budget'])
        self.assertFalse(analyze([],boot)['real_GLES_frame_budget'])
        native=f'REDFIN GLES BUDGET CHECK: boot={boot} bound=2 rounds=12 maximum=2 waits=11 pixels=58560 tail-guard-bytes=147456 real-GL-fences=1 CPU-pixels=1 result=0'
        self.assertTrue(native_budget_check([native],boot))
        for bad in (native.replace('result=0','result=1'),native.replace('pixels=58560','pixels=1'),
                    native.replace('CPU-pixels=1','CPU-pixels=0'),native.replace(boot,'fedcba9876543210')):
            self.assertFalse(native_budget_check([bad],boot))
        self.assertFalse(native_budget_check([native,native],boot))


if __name__=='__main__':unittest.main()
