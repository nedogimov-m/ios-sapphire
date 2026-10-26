/* SPDX-License-Identifier: MIT
 * Actual native runtime include with guarded MMIO/clock/fence receivers.
 * This checks publication, timestamps and ownership, not A620 pixel execution.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "include/redfin_gpu_physical.h"
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"physical runtime: %s at %u\n",#x,__LINE__);abort();}}while(0)
#define RF_A6_RING_BYTES 0x8000u
#define RF_A6_WAIT_NS UINT64_C(500000000)
static struct {
   struct rf_gr_arena arena;uint32_t fence,completed;
   struct rf_gi_publication physical[RF_GI_SLOTS];
   uint64_t physical_overlap,audit_ns,wait_ns,publish_ns,gpu_ticks,polls;
   uint32_t physical_max_pending;
} gr;
static uint32_t ring[RF_A6_RING_BYTES/4],scratch[0x1000/4];
static struct {
   void *context;uintptr_t gpu,scratch;uint32_t wptr;
   struct {void *host;} data[1];
} gx={.context=(void *)1,.gpu=0x100000,.scratch=0x200000,.data={{ring}}};
static uint32_t gpu_rptr,status,hw_done,hw_issued[32],hw_count;
static uint64_t clock_ns;static unsigned audits,mapped,diagnostics,poisons,dvfs;
static bool ready=true,advance=true,need_vote,dirty_map;
static int fail_audit;
static uint64_t gm_time_ns(void *p){(void)p;return ++clock_ns;}
static int gr_live(void){return ready?0:ENXIO;}
static int gr_audit(bool force){(void)force;++audits;return fail_audit?EIO:gr_live();}
static uint32_t gm_scalar_read(uintptr_t address)
{
   if(address>=gx.scratch&&address<gx.scratch+sizeof(scratch))return scratch[(address-gx.scratch)/4];
   if(address==gx.gpu+4*0x806)return gpu_rptr;
   if(address==gx.gpu+4*0x210)return status;
   if(address==gx.gpu+4*0x821||address==gx.gpu+4*0x823)return 0;
   REQUIRE(false);return 0;
}
static void gm_memory_store(uintptr_t address,uint32_t value)
{REQUIRE(address==gx.gpu+4*0x807&&value==gx.wptr);REQUIRE(hw_count<32);hw_issued[hw_count++]=gr.fence;status=2;}
static void redfin_gpu_sync(void *p,uint64_t bytes,bool invalidate)
{(void)p;(void)bytes;REQUIRE(!invalidate);}
static void redfin_gpu_poison(const char *reason){(void)reason;ready=false;++poisons;}
static void gx_diagnostic(void *p){(void)p;++diagnostics;}
static int redfin_gpu_quiesce(void);
static int redfin_gpu_mapped(void){++mapped;if(dirty_map){int r=redfin_gpu_quiesce();if(r)return r;dirty_map=false;}return gr_live();}
static int gr_dvfs(bool activity)
{REQUIRE(activity);++dvfs;if(need_vote&&gpu_rptr!=gx.wptr)return EBUSY;need_vote=false;return 0;}
struct gr_wait_sample {uint32_t wanted,done,rptr,status;bool idle;};
static int gr_wait_sample(void *argument,bool *complete)
{
   struct gr_wait_sample *s=argument;int error=gr_live();if(error)return error;
   s->done=gm_scalar_read(gx.scratch+RF_GR_FENCE_AT);s->rptr=gpu_rptr;s->status=status;
   error=rf_gi_counter(gr.fence,gr.completed,s->done,s->wanted,complete);
   if(!error&&s->idle)*complete=*complete&&s->rptr==gx.wptr&&!(s->status&~1u);return error;
}
static void complete_one(void)
{
   if(hw_done>=hw_count)return;
   uint32_t fence=hw_issued[hw_done++],offset=rf_gi_time_offset(fence);
   scratch[offset/4]=fence*100;scratch[offset/4+1]=0;scratch[offset/4+2]=fence*100+25;scratch[offset/4+3]=0;
   scratch[RF_GR_FENCE_AT/4]=fence;
   if(hw_done==hw_count){gpu_rptr=gx.wptr;status=0;}
}
static void gr_wait_pause(void *p,unsigned microseconds)
{(void)p;clock_ns+=(uint64_t)microseconds*1000;if(advance)complete_one();}
#include "gpu-physical-runtime.inc"

static void reset(void)
{
   memset(&gr,0,sizeof(gr));memset(ring,0,sizeof(ring));memset(scratch,0,sizeof(scratch));
   gx.wptr=gpu_rptr=status=hw_done=hw_count=0;clock_ns=0;audits=mapped=diagnostics=poisons=dvfs=0;
   ready=advance=true;need_vote=dirty_map=false;fail_audit=0;
}
int main(void)
{
   reset();uint64_t address=rf_gr_allocate(&gr.arena,0x4000);uint32_t words=4,a=0,b=0;
   REQUIRE(!redfin_gpu_publish(&address,&words,1,&a)&&a==1&&gr.completed==0&&hw_done==0);
   REQUIRE(!redfin_gpu_publish(&address,&words,1,&b)&&b==2&&gr.completed==0&&hw_done==0&&gr.physical_overlap==1&&gr.physical_max_pending==2);
   REQUIRE(redfin_gpu_poll(a)==EAGAIN&&gr.completed==0);
   REQUIRE(!redfin_gpu_wait(a)&&gr.completed==1&&hw_done==1&&status==2);
   REQUIRE(!gr.physical[a%RF_GI_SLOTS].fence&&gr.physical[b%RF_GI_SLOTS].fence==2);
   REQUIRE(!redfin_gpu_quiesce()&&gr.completed==2&&gpu_rptr==gx.wptr&&gr.gpu_ticks==50&&audits>=4);
   /* Exact wrapped ring words and timestamp generation reuse. */
   gx.wptr=gpu_rptr=RF_A6_RING_BYTES/4-8;
   REQUIRE(!redfin_gpu_submit(&address,&words,1,&a)&&a==3&&gr.completed==3&&gx.wptr==14);
   REQUIRE(ring[RF_A6_RING_BYTES/4-6]==0x01200000+rf_gi_time_offset(3));
   REQUIRE(!redfin_gpu_publish(&address,&words,1,&a)&&a==4);
   need_vote=true;REQUIRE(!redfin_gpu_publish(&address,&words,1,&b)&&b==5&&gr.completed==4&&hw_done==4);
   REQUIRE(!redfin_gpu_quiesce()&&gr.completed==5&&gr.gpu_ticks==125);
   /* New page-table publication drains actual physical work first. */
   REQUIRE(!redfin_gpu_publish(&address,&words,1,&a));dirty_map=true;
   REQUIRE(!redfin_gpu_publish(&address,&words,1,&b)&&gr.completed==a&&!dirty_map);
   REQUIRE(!redfin_gpu_quiesce());
   unsigned issued=hw_count;uint32_t untouched=42;
   REQUIRE(redfin_gpu_publish(&address,&words,0,&untouched)==EINVAL&&untouched==0&&issued==hw_count);
   /* Real missed deadline and a forged forward/backward fence poison; no
    * completed metadata or slot becomes available on any such failure. */
   REQUIRE(!redfin_gpu_publish(&address,&words,1,&a));advance=false;
   uint32_t prior=gr.completed;clock_ns+=RF_A6_WAIT_NS;
   REQUIRE(redfin_gpu_poll(a)==ETIMEDOUT&&!ready&&gr.completed==prior&&gr.physical[a%RF_GI_SLOTS].fence==a);
   reset();address=rf_gr_allocate(&gr.arena,0x4000);REQUIRE(!redfin_gpu_publish(&address,&words,1,&a));
   scratch[RF_GR_FENCE_AT/4]=a+1;REQUIRE(redfin_gpu_wait(a)==EPROTO&&!ready&&!gr.completed);
   reset();address=rf_gr_allocate(&gr.arena,0x4000);REQUIRE(!redfin_gpu_publish(&address,&words,1,&a));
   complete_one();fail_audit=1;REQUIRE(redfin_gpu_wait(a)==EIO&&!ready&&!gr.completed);
   puts("actual physical runtime publication/counter/timestamp/wrap/quiescence/failure PASS");return 0;
}
