/* SPDX-License-Identifier: MIT */
/* The actual Mesa append/intent/merge functions are injected by the host
 * contract. Only allocation tables and the native IOKit edge are fixtures. */
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "redfin_gpu_access.h"
#define unlikely(x) (x)
#define READ_ONCE(x) (x)
struct fd_bo {uint32_t idx;unsigned refs;uint64_t size,iova;fd_bo *parent;};
static bool suballoc_bo(fd_bo *b){return b->parent!=nullptr;}
static fd_bo *fd_bo_heap_block(fd_bo *b){assert(b->parent);return b->parent;}
static uint64_t fd_bo_get_iova(fd_bo *b){return b->iova;}
static fd_bo *fd_bo_ref(fd_bo *b){++b->refs;return b;}
struct hash_entry {void *key,*data;};
struct hash_table {hash_entry entry[64]={};unsigned count=0;};
static uint32_t _mesa_hash_pointer(void *p){return (uint32_t)(uintptr_t)p;}
static hash_entry *_mesa_hash_table_search_pre_hashed(hash_table *t,uint32_t,void *p){
 for(unsigned i=0;i<t->count;++i)if(t->entry[i].key==p)return &t->entry[i];return nullptr;
}
static void _mesa_hash_table_insert_pre_hashed(hash_table *t,uint32_t,void *p,void *data){
 assert(t->count<64);t->entry[t->count++]={p,data};
}
struct fd_submit_sp;
struct fd_submit {fd_submit_sp *owner;};
struct fd_submit_sp {
 fd_submit base{this};fd_bo *bos[64]={},*suballoc_bos[64]={};unsigned nr_bos=0,nr_suballoc_bos=0;
 uint64_t redfin_direct_bos[RF_GW_MAX_BOS/64]={};
 uint8_t redfin_bo_access[RF_GW_MAX_BOS]={},redfin_view_access[RF_GW_MAX_RANGES]={};
 hash_table native_table,view_table;hash_table *bo_table=&native_table,*suballoc_bo_table=&view_table;
};
static fd_submit_sp *to_fd_submit_sp(fd_submit *s){return s->owner;}
#define APPEND(s,field,value) ([&]{assert((s)->nr_##field<64);unsigned n=(s)->nr_##field++;(s)->field[n]=(value);return n;}())
static bool fd_submit_redfin_direct(const fd_submit_sp *s,unsigned i){
 return i>=RF_GW_MAX_BOS||(s->redfin_direct_bos[i/64]&(UINT64_C(1)<<(i%64)));
}
struct fd_device {int fd;};struct fd_pipe {fd_device *dev;};
struct drm_msm_gem_submit {
 uint32_t flags,fence,nr_bos,nr_cmds;uint64_t bos,cmds;int32_t fd;uint32_t queue;
 uint64_t in_sync,out_sync;uint32_t nr_in,nr_out,stride,pad;
};
static rf_gw_submit_range captured[RF_GW_MAX_RANGES];static unsigned captured_count,calls;
static int redwood_drm_submit_access(int fd,void *request,size_t bytes,const rf_gw_submit_range *ranges,uint32_t n){
 assert(fd==9&&bytes==72&&n<=RF_GW_MAX_RANGES);++calls;captured_count=n;
 memcpy(captured,ranges,n*sizeof(*ranges));((drm_msm_gem_submit *)request)->fence=77;return 0;
}
/* ACTUAL_APPEND_AND_RESOURCE_INTENT */
#include "mesa-access-submit.inc"
static void release(fd_submit_sp *s){
 for(unsigned i=0;i<s->nr_bos;++i)assert(--s->bos[i]->refs>=1);
 for(unsigned i=0;i<s->nr_suballoc_bos;++i)assert(--s->suballoc_bos[i]->refs>=1);
}
extern "C" int intent_contract(unsigned which){
 fd_bo native={UINT32_MAX,1,65536,0x10000,nullptr};
 fd_bo a={UINT32_MAX,1,64,0x10000,&native},b={UINT32_MAX,1,64,0x10040,&native};
 fd_submit_sp target,source;fd_device device={9};fd_pipe pipe={&device};drm_msm_gem_submit request={};
 if(which==0) {
  fd_submit_redfin_resource_use(&target.base,&a,RF_GA_READ);
  fd_submit_redfin_resource_use(&target.base,&b,RF_GA_WRITE);
  request.nr_bos=target.nr_bos;assert(!redfin_msm_submit_scoped(&target,&pipe,&request));
  assert(captured_count==2&&captured[0].reserved==1&&captured[1].reserved==2);
  assert(captured[0].offset==0&&captured[1].offset==64&&captured[0].bytes==64);
 }
 if(which==1) {
  fd_submit_redfin_resource_use(&target.base,&a,RF_GA_READ);
  fd_submit_redfin_resource_use(&source.base,&a,RF_GA_WRITE);
  redfin_msm_merge_scoped(&target,&source);release(&source);source.nr_bos=source.nr_suballoc_bos=0;
  request.nr_bos=target.nr_bos;assert(!redfin_msm_submit_scoped(&target,&pipe,&request));
  assert(captured_count==1&&captured[0].reserved==RF_GA_RW);
 }
 if(which==2||which==3) {
  if(which==2) {
   fd_submit_redfin_resource_use(&target.base,&a,RF_GA_READ);fd_submit_append_bo(&source,&a);
  } else {
   fd_submit_append_bo(&target,&a);fd_submit_redfin_resource_use(&source.base,&a,RF_GA_READ);
  }
  redfin_msm_merge_scoped(&target,&source);release(&source);source.nr_bos=source.nr_suballoc_bos=0;
  request.nr_bos=target.nr_bos;assert(!redfin_msm_submit_scoped(&target,&pipe,&request));
  assert(captured_count==1&&!captured[0].reserved);
 }
 if(which==4||which==5) {
  fd_submit_redfin_resource_use(&target.base,&native,RF_GA_READ);
  if(which==4)fd_submit_redfin_resource_use(&target.base,&a,RF_GA_WRITE);
  else fd_submit_append_bo(&target,&a);
  request.nr_bos=target.nr_bos;assert(!redfin_msm_submit_scoped(&target,&pipe,&request));
  assert(captured_count==1&&!captured[0].offset&&captured[0].bytes==native.size);
  assert(captured[0].reserved==(which==4?RF_GA_RW:0));
 }
 if(which==6) {
  fd_submit_append_bo(&target,&native);fd_submit_redfin_resource_use(&target.base,&a,RF_GA_READ);
  request.nr_bos=target.nr_bos;assert(!redfin_msm_submit_scoped(&target,&pipe,&request));
  assert(captured_count==1&&!captured[0].reserved&&captured[0].bytes==native.size);
 }
 if(which==7) {
  fd_submit_redfin_resource_use(&target.base,&a,RF_GA_READ);
  fd_submit_redfin_resource_use(&source.base,&b,RF_GA_WRITE);
  redfin_msm_merge_scoped(&target,&source);release(&source);source.nr_bos=source.nr_suballoc_bos=0;
  request.nr_bos=target.nr_bos;unsigned previous=calls;a.iova=native.iova-1;
  assert(redfin_msm_submit_scoped(&target,&pipe,&request)==-1&&errno==EINVAL&&calls==previous);
 }
 release(&target);assert(native.refs==1&&a.refs==1&&b.refs==1);return 0;
}
