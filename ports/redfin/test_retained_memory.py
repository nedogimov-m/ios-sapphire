"""Native residency policy, real Mesa BO lifetime and conservative legacy fallback."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from test_smp_gui import patched_source

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=ROOT/'research/redfin-gpu/frontend-prepare-base-v1'


def execute(source,cpp=False):
    with tempfile.TemporaryDirectory(prefix='redfin-retention-') as directory:
        root=Path(directory);path=root/('contract.cpp' if cpp else 'contract.c');path.write_text(source)
        build=subprocess.run(['c++' if cpp else 'cc','-std=c++17' if cpp else '-std=c11',
            '-O2','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-function',
            '-I'+str(HERE),str(path),'-o',str(root/'contract')],capture_output=True,text=True)
        if build.returncode:raise AssertionError(build.stderr)
        result=subprocess.run([str(root/'contract')],capture_output=True,text=True)
        if result.returncode:raise AssertionError(result.stderr)
        return result.stdout


class RetainedMemoryTests(unittest.TestCase):
    def test_actual_kernel_publishes_explicit_policy_but_raw_invalid_handles_still_fail(self):
        cpp=patched_source('iokit/Kernel/arm/RedfinGPU.cpp')
        self.assertEqual(patched_source('iokit/Kernel/arm/RedfinGPUMemoryPolicy.h'),
                         (HERE/'retained-memory.h').read_text())
        parameter=function(cpp,'static bool parameter(')
        external=function(cpp,'IOReturn RedwoodGPUUserClient::externalMethod(')
        get=external[external.rindex('case GetParam:'):external.rindex('case SetParam:')]
        madvise=external[external.rindex('case Madvise:'):external.rindex('case QueueNew:')]
        source=r'''
#include <assert.h>
#include "retained-memory.h"
#include "include/redfin_gpu_queue.h"
#include "include/redfin_gpu_scope.h"
#include "include/redfin_gpu_access.h"
static unsigned clocks,power;
static uint64_t mach_absolute_time(){++clocks;return 1;}
static uint64_t redfin_gpu_max_frequency(){++power;return 625000000;}
enum {GetParam=0x40,Madvise=0x48,kIOReturnBadArgument=2};
struct msm_param {uint32_t pipe,param;uint64_t value;uint32_t len,pad;};
struct msm_madvise {uint32_t handle,madv,retained;};
static bool alive=true;static int memory;
static void *buffer(uint32_t handle){return alive&&handle==7?&memory:nullptr;}
''' + parameter + '''
static int query(msm_param &request) {
 struct {msm_param param;} r={request};int result=0;
 switch(GetParam) {'''+get+'''}
 request=r.param;return result;
}
static int advise(msm_madvise &request) {
 struct {msm_madvise madvise;} r={request};int result=0;
 switch(Madvise) {'''+madvise+'''}
 request=r.madvise;return result;
}
int main() {
 static_assert(sizeof(msm_param)==24,"existing parameter ABI");
 for(unsigned fault=0;fault<4;++fault) {
  msm_param request={0x10,RF_GM_PARAM,999,0,0};
  if(fault==1)request.len=1;if(fault==2)request.pad=1;if(fault==3)request.pipe=0;
  assert(query(request)==(fault?kIOReturnBadArgument:0));
  if(!fault)assert(request.value==RF_GM_ABI);
 }
 assert(!clocks&&!power); /* policy discovery performs no GPU register work */
 for(unsigned need=0;need<2;++need) {
  msm_madvise request={7,need,999};assert(!advise(request)&&request.retained==1);
  request={8,need,999};assert(advise(request)==kIOReturnBadArgument&&request.retained==999);
  alive=false;request={7,need,999};assert(advise(request)==kIOReturnBadArgument&&request.retained==999);alive=true;
 }
 return 0;
}
'''
        execute(source,True)

    def test_actual_mesa_device_queries_once_and_retained_bos_skip_only_madvise(self):
        targets=['src/freedreno/drm/msm/'+name for name in ('msm_device.c','msm_bo.c')]
        if not all((BASE/t).is_file() for t in targets):
            self.skipTest('exact reviewed Mesa preimage fixture absent')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for t in targets:
                p=root/t;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((BASE/t).read_bytes())
            for t in targets:
                subprocess.run(['git','apply','--include='+t,str(HERE/'mesa-retained-memory.patch')],
                    cwd=root,check=True,capture_output=True)
            device=(root/targets[0]).read_text();bo=(root/targets[1]).read_text()
        methods='\n'.join((function(device,'static void\nmsm_redfin_retention_init('),
            function(device,'struct fd_device *\nmsm_device_new('),
            function(device,'int\nfd_device_retained_statistics('),
            function(bo,'static int\nmsm_bo_madvise(')))
        source=r'''
#define __APPLE__ 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
#include <pthread.h>
#include "retained-memory.h"
#define STATIC_ASSERT(c) _Static_assert(c,#c)
enum {FD_BO_PREP_READ=1,MSM_PREP_READ=1,FD_BO_PREP_WRITE=2,MSM_PREP_WRITE=2,
 FD_BO_PREP_NOSYNC=4,MSM_PREP_NOSYNC=4,FD_VERSION_MADVISE=1,FD_VERSION_CACHED_COHERENT=8,
 MSM_BO_CACHED_COHERENT=1,MSM_MADV_WILLNEED=0,MSM_MADV_DONTNEED=1,
 DRM_MSM_GET_PARAM=0,DRM_MSM_GEM_NEW=2,DRM_MSM_GEM_MADVISE=8,DRM_IOCTL_GEM_CLOSE=9};
struct fd_device_funcs {int marker;};static const struct fd_device_funcs funcs={1};
struct fd_device {const struct fd_device_funcs *funcs;int version,fd;bool has_cached_coherent;size_t bo_size;};
struct msm_device {struct fd_device base;bool redfin_retained;
 uint64_t redfin_retention_queries,redfin_retention_fast,redfin_retention_fallback;};
static struct msm_device *to_msm_device(struct fd_device *d){return (struct msm_device *)d;}
struct fd_bo {struct fd_device *dev;uint32_t handle;};
struct msm_bo {struct fd_bo base;uint64_t offset;};
struct drm_msm_param {uint32_t pipe,param;uint64_t value;uint32_t len,pad;};
struct drm_msm_gem_new {uint64_t size;uint32_t flags,handle;};
struct drm_gem_close {uint32_t handle;};
struct drm_msm_gem_madvise {uint32_t handle,madv,retained;};
typedef struct {int version_minor;} drmVersion,*drmVersionPtr;
static const unsigned os_page_size=16384;
static unsigned mode,queries,legacy;static int old_retained=1,old_error;
static int drmCommandWriteRead(int fd,unsigned number,void *data,size_t bytes) {
 assert(fd==4);
 if(number==DRM_MSM_GET_PARAM) {
  ++queries;assert(bytes==24);struct drm_msm_param *r=data;
  assert(r->pipe==0x10&&r->param==RF_GM_PARAM&&!r->value&&!r->len&&!r->pad);
  r->value=mode==1?0:mode==2?2:RF_GM_ABI;
  if(mode==3)r->pipe=0;if(mode==4)r->param++;if(mode==5)r->len=1;if(mode==6)r->pad=1;
  return mode==7?-EIO:0;
 }
 if(number==DRM_MSM_GEM_MADVISE) {
  ++legacy;assert(bytes==sizeof(struct drm_msm_gem_madvise));struct drm_msm_gem_madvise *r=data;
  assert(r->handle==7&&(r->madv==MSM_MADV_WILLNEED||r->madv==MSM_MADV_DONTNEED));
  r->retained=old_retained;return old_error;
 }
 assert(number==DRM_MSM_GEM_NEW);return -ENOTSUP;
}
static int drmIoctl(int fd,unsigned request,void *data){(void)fd;(void)request;(void)data;assert(0);return -1;}
''' + methods + r'''
static void *reuse(void *p) {
 struct fd_bo *bo=p;
 for(unsigned i=0;i<1000;++i)assert(msm_bo_madvise(bo,i&1)==1);
 return NULL;
}
int main(void) {
 drmVersion version={7};
 for(mode=0;mode<8;++mode) {
  queries=legacy=0;old_retained=1;old_error=0;
  struct fd_device *d=msm_device_new(4,&version);assert(d&&queries==1);d->fd=4;
  struct fd_bo bo={d,7};uint64_t counts[RF_GM_WORDS]={0};
  if(!mode) {
   assert(msm_bo_madvise(&bo,0)==1&&msm_bo_madvise(&bo,1)==1);
   pthread_t threads[4];for(unsigned i=0;i<4;++i)assert(!pthread_create(&threads[i],NULL,reuse,&bo));
   for(unsigned i=0;i<4;++i)assert(!pthread_join(threads[i],NULL));
   assert(!fd_device_retained_statistics(d,counts));
   assert(counts[RF_GM_CAPABILITY]==1&&counts[RF_GM_FAST]==4002&&!counts[RF_GM_FALLBACK]&&!legacy);
   struct fd_bo invalid={d,0};assert(msm_bo_madvise(&invalid,1)==-EINVAL);
   assert(msm_bo_madvise(NULL,1)==-EINVAL);
  } else {
   assert(msm_bo_madvise(&bo,0)==1&&legacy==1);
   old_retained=0;assert(msm_bo_madvise(&bo,1)==0&&legacy==2);
   old_error=-EIO;assert(msm_bo_madvise(&bo,1)==-EIO&&legacy==3);
   assert(!fd_device_retained_statistics(d,counts));
   assert(!counts[RF_GM_CAPABILITY]&&!counts[RF_GM_FAST]&&counts[RF_GM_FALLBACK]==3);
  }
  assert(queries==1&&counts[RF_GM_QUERIES]==1);
  assert(fd_device_retained_statistics(d,NULL)==-1);free(d);
 }
 mode=0;queries=legacy=0;version.version_minor=0;
 struct fd_device *d=msm_device_new(4,&version);assert(d&&!queries);d->fd=4;struct fd_bo bo={d,7};
 assert(msm_bo_madvise(&bo,0)==0&&msm_bo_madvise(&bo,1)==1&&!legacy);free(d);
 return 0;
}
'''
        execute(source)


if __name__=='__main__':unittest.main()
