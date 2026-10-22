/* Redfin CX-only power experiment. Google msm500b3a2059c1eec0fec08ec56add06320ea901a8:
 * rpmh-regulator.c ARC selector map; rpmh-rsc.c ACTIVE transaction;
 * gdsc-regulator.c LOW_SVS parent before SW_COLLAPSE,500us status poll.
 * The exact eight-entry table is mandatory: its highest legal selector7
 * cannot lower an inherited legal request. Hold until reset; never unvote.
 * No GX, GPU/GMU/SMMU register access or firmware/DMA in this stage. */
#ifndef REDFIN_GPU_POWER_H
#define REDFIN_GPU_POWER_H
#include <stdbool.h>
#include <stdint.h>
#include "redfin_rpmh.h"
enum { RF_GP_GCC,RF_GP_GPUCC,RF_GP_RSC,RF_GP_GIC };
enum { RF_GP_OK,RF_GP_POLICY,RF_GP_TABLE,RF_GP_CLOCK,RF_GP_HANDOFF,
 RF_GP_WRITE,RF_GP_COMPLETION,RF_GP_CHANGED,RF_GP_DOMAIN };
struct rf_gp_ops {
 void *context;
 bool (*valid)(void *);
 uint32_t (*read)(void *,unsigned,unsigned);
 void (*write)(void *,unsigned,unsigned,uint32_t);
 void (*delay)(void *,unsigned);
 bool (*table)(void *);
};
struct rf_gp_slot {
 uint32_t idle,control,enabled,wait;
 struct {uint32_t message,address,data;} command[16];
};
struct rf_gp_report {
 unsigned stage,polls,commands,selector,corner;
 uint32_t id,config,irq_enable,irq,status,cx_before,cx_after,cx_hw;
 bool parent_held,cx_on,write_issued;
 struct rf_gp_slot inherited[8];
};
#define RF_GP_TCS(t) (0xd00u+0x2a0u*(t))
static inline bool rf_gp_table(const struct rf_cmddb_resource *r)
{
 const uint16_t values[]={0,16,64,128,192,256,384,416,0,0,0,0,0,0,0,0};
 if(!r || r->address!=0x30000 || r->type!=RF_CMDDB_ARC || r->aux_version!=0x1000 ||
    r->aux_bytes!=32 || r->level_count!=16) return false;
 for(unsigned i=0;i<16;i++) if(r->levels[i]!=values[i]) return false;
 return true;
}
static inline uint32_t rf_gp_rd(const struct rf_gp_ops *o,unsigned unit,unsigned at)
{ return o->read(o->context,unit,at); }
static inline bool rf_gp_irq(const struct rf_gp_ops *o,const struct rf_gp_report *r,bool before)
{
 if(!o->valid(o->context)) return false;
 uint32_t en=rf_gp_rd(o,RF_GP_GIC,0x104),pending=rf_gp_rd(o,RF_GP_GIC,0x204),active=rf_gp_rd(o,RF_GP_GIC,0x304);
 return en!=UINT32_MAX && pending!=UINT32_MAX && active!=UINT32_MAX &&
  !((en|active|(before?pending:0))&(1u<<5)) && rf_gp_rd(o,RF_GP_RSC,0xd00)==r->irq_enable;
}
static inline bool rf_gp_snapshot(const struct rf_gp_ops *o,struct rf_gp_report *r,bool compare)
{
 for(unsigned t=0;t<8;t++) {
  struct rf_gp_slot now;
  unsigned at=RF_GP_TCS(t);
  now.idle=rf_gp_rd(o,RF_GP_RSC,at+0x18);now.control=rf_gp_rd(o,RF_GP_RSC,at+0x14);
  now.enabled=rf_gp_rd(o,RF_GP_RSC,at+0x1c);now.wait=rf_gp_rd(o,RF_GP_RSC,at+0x10);
  if(now.idle==UINT32_MAX || !now.idle || now.control==UINT32_MAX ||
     ((now.enabled|now.wait)&~((1u<<r->commands)-1)) ||
     (t<2 && (now.control || now.enabled || now.wait))) return false;
  struct rf_gp_slot *s=&r->inherited[t];
  if(compare && (s->idle!=now.idle || s->control!=now.control || s->enabled!=now.enabled || s->wait!=now.wait)) return false;
  if(!compare) {s->idle=now.idle;s->control=now.control;s->enabled=now.enabled;s->wait=now.wait;}
  for(unsigned n=0;n<r->commands;n++) {
   if(!(now.enabled&(1u<<n))) continue;
   unsigned cmd=at+0x30+n*0x14;
   uint32_t message=rf_gp_rd(o,RF_GP_RSC,cmd),address=rf_gp_rd(o,RF_GP_RSC,cmd+4),data=rf_gp_rd(o,RF_GP_RSC,cmd+8);
   if((address&~3u)==0x30000 && (address!=0x30000 || !(message&(1u<<16)) || data>7)) return false;
   if(compare && (s->command[n].message!=message || s->command[n].address!=address || s->command[n].data!=data)) return false;
   if(!compare) {s->command[n].message=message;s->command[n].address=address;s->command[n].data=data;}
  }
 }
 return true;
}
static inline bool rf_gp_sync(const struct rf_gp_ops *o,struct rf_gp_report *r,unsigned unit,unsigned at,uint32_t value)
{
 if(!o->valid(o->context)) return false;
 r->write_issued=true;o->write(o->context,unit,at,value);
 for(unsigned i=0;i<1000;i++) {
  if(rf_gp_rd(o,unit,at)==value) return true;
  o->delay(o->context,1);
 }
 return false;
}
static inline int rf_gp_run(const struct rf_gp_ops *o,struct rf_gp_report *r)
{
 if(!o || !r || !o->valid || !o->read || !o->write || !o->delay || !o->table || !o->valid(o->context)) return RF_GP_POLICY;
 r->stage=RF_GP_TABLE;
 if(!o->table(o->context)) return RF_GP_TABLE;
 r->stage=RF_GP_CLOCK;
 if((rf_gp_rd(o,RF_GP_GCC,0x71004)&0x80000001u)!=1) return RF_GP_CLOCK;
 r->cx_before=rf_gp_rd(o,RF_GP_GPUCC,0x106c);
 /* Frozen observed ABL configuration; no HW-controlled or already-on domain. */
 if(r->cx_before!=0x222001) return RF_GP_HANDOFF;
 r->stage=RF_GP_HANDOFF;
 r->id=rf_gp_rd(o,RF_GP_RSC,0);r->config=rf_gp_rd(o,RF_GP_RSC,0xc);
 unsigned major=(r->id>>16)&255,count=(r->config>>12)&63;
 r->commands=(r->config>>27)&31;
 if((major!=1 && major!=2) || r->config==UINT32_MAX || count<8 || count>9 || !r->commands || r->commands>16) return RF_GP_HANDOFF;
 r->irq_enable=rf_gp_rd(o,RF_GP_RSC,0xd00);
 if(!(r->irq_enable&1) || r->irq_enable==UINT32_MAX || rf_gp_rd(o,RF_GP_RSC,0xd04) ||
    !rf_gp_irq(o,r,true) || !rf_gp_snapshot(o,r,false) || !rf_gp_snapshot(o,r,true) ||
    !o->table(o->context) || !rf_gp_snapshot(o,r,true) || rf_gp_rd(o,RF_GP_RSC,0)!=r->id || rf_gp_rd(o,RF_GP_RSC,0xc)!=r->config ||
    rf_gp_rd(o,RF_GP_GPUCC,0x106c)!=r->cx_before || !rf_gp_irq(o,r,true)) return RF_GP_CHANGED;
 r->stage=RF_GP_WRITE;r->selector=7;r->corner=416;
 unsigned at=RF_GP_TCS(0),cmd=at+0x30;
 if(!rf_gp_sync(o,r,RF_GP_RSC,cmd,0x10108) || !rf_gp_sync(o,r,RF_GP_RSC,cmd+4,0x30000) ||
    !rf_gp_sync(o,r,RF_GP_RSC,cmd+8,7) || !rf_gp_sync(o,r,RF_GP_RSC,at+0x10,1) ||
    !rf_gp_sync(o,r,RF_GP_RSC,at+0x1c,1) || !rf_gp_sync(o,r,RF_GP_RSC,at+0x14,0) ||
    !rf_gp_sync(o,r,RF_GP_RSC,at+0x14,1u<<16) || !rf_gp_irq(o,r,true)) return RF_GP_WRITE;
 if(!o->valid(o->context)) return RF_GP_POLICY;
 o->write(o->context,RF_GP_RSC,at+0x14,(1u<<16)|(1u<<24));
 r->stage=RF_GP_COMPLETION;
 bool completed=false;
 for(unsigned us=0;us<100000;us++) {
  if(!rf_gp_irq(o,r,false)) return RF_GP_CHANGED;
  r->irq=rf_gp_rd(o,RF_GP_RSC,0xd04);
  uint32_t idle=rf_gp_rd(o,RF_GP_RSC,at+0x18);
  r->status=rf_gp_rd(o,RF_GP_RSC,cmd+12);r->polls++;
  if(r->irq==UINT32_MAX || (r->irq&~1u) || idle==UINT32_MAX || r->status==UINT32_MAX) return RF_GP_COMPLETION;
  if((r->irq&1) && idle && (r->status&0x10100)==0x10100) {completed=true;break;}
  o->delay(o->context,1);
 }
 if(!completed) return RF_GP_COMPLETION;
 if(!rf_gp_sync(o,r,RF_GP_RSC,at+0x14,1u<<16) || !rf_gp_sync(o,r,RF_GP_RSC,at+0x14,0) ||
    !rf_gp_sync(o,r,RF_GP_RSC,at+0x1c,0) || !rf_gp_sync(o,r,RF_GP_RSC,at+0x10,0) || !o->valid(o->context)) return RF_GP_WRITE;
 o->write(o->context,RF_GP_RSC,0xd08,1);
 if(rf_gp_rd(o,RF_GP_RSC,0xd04) || !rf_gp_irq(o,r,false) || !rf_gp_snapshot(o,r,true) || !o->table(o->context)) return RF_GP_CHANGED;
 r->parent_held=true;
 r->stage=RF_GP_DOMAIN;
 if((rf_gp_rd(o,RF_GP_GCC,0x71004)&0x80000001u)!=1 || rf_gp_rd(o,RF_GP_GPUCC,0x106c)!=r->cx_before) return RF_GP_CHANGED;
 if(!o->valid(o->context)) return RF_GP_POLICY;
 r->write_issued=true;o->write(o->context,RF_GP_GPUCC,0x106c,r->cx_before&~1u);
 o->delay(o->context,1);
 for(unsigned us=0;us<1000;us++) {
  if(!o->valid(o->context)) return RF_GP_POLICY;
  r->cx_hw=rf_gp_rd(o,RF_GP_GPUCC,0x1540);
  r->cx_after=rf_gp_rd(o,RF_GP_GPUCC,0x106c);
  if(r->cx_hw==UINT32_MAX || r->cx_after==UINT32_MAX) return RF_GP_DOMAIN;
  if((r->cx_hw&(1u<<31)) && !(r->cx_after&3u)) {r->cx_on=true;r->stage=RF_GP_OK;return RF_GP_OK;}
  o->delay(o->context,1);
 }
 return RF_GP_DOMAIN;
}
#endif
