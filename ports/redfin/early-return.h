/* Shared, freestanding Redfin bootloader-return leaf.
 * Google kernel/msm 500b3a2059c1eec0fec08ec56add06320ea901a8:
 * spmi-pmic-arb.c v5 offset/fmt_cmd/read/write; qpnp-power-on.c gen2
 * SOFT_RB_SPARE; msm-poweroff.c bootloader command. No reset is issued.
 *
 * Caller owns one-shot use, CPU0/UP policy, local interrupt exclusion and
 * validated Device mappings: core0xc440000+0x1100, observer0xe600000+0x100000,
 * config0xc40a000+0x26000, selected write0xc600000+APID*0x10000+0x20,
 * IMEM0x146ab65c+4. Find first, map that one write channel, then arm.
 * Shim uses those physical bases; the protected kernel uses ml_io_map VAs.
 * On any error STOP: an observer/write may still complete after timeout.
 * No retry, allocation, diagnostics, IRQ ack, channel setup or reset here.
 */
#ifndef REDFIN_EARLY_RETURN_H
#define REDFIN_EARLY_RETURN_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

enum redfin_er_error {
 REDFIN_ER_OK, REDFIN_ER_INVALID, REDFIN_ER_UNSUPPORTED, REDFIN_ER_NO_TARGET,
 REDFIN_ER_IO, REDFIN_ER_TIMEOUT, REDFIN_ER_CLOCK, REDFIN_ER_CHANGED
};
enum redfin_er_stage {
 REDFIN_ER_PREFLIGHT, REDFIN_ER_SUBTYPE, REDFIN_ER_SPARE, REDFIN_ER_WRITE,
 REDFIN_ER_VERIFY, REDFIN_ER_IMEM, REDFIN_ER_DONE
};
struct redfin_er_target { uint32_t version,mapping; unsigned apid,owner; };
struct redfin_er_io { uintptr_t core,observer,config,channel,imem; };
struct redfin_er_report {
 unsigned stage;
 uint8_t subtype,before,intended,after;
 uint32_t imem;
 bool pon_issued,imem_issued;
};

/* REDFIN_EARLY_RETURN_HW_BEGIN */
static inline uint32_t redfin_er_rd(uintptr_t base,unsigned offset)
{
 uint32_t value=*(volatile uint32_t *)(base+offset);
 __asm__ volatile("dmb oshld" ::: "memory");
 return value;
}
static inline void redfin_er_wr(uintptr_t base,unsigned offset,uint32_t value)
{ *(volatile uint32_t *)(base+offset)=value; }
static inline void redfin_er_read_start(void)
{ __asm__ volatile("dmb oshst" ::: "memory"); }
static inline void redfin_er_data_done(void)
{ __asm__ volatile("dsb oshst" ::: "memory"); }
static inline void redfin_er_command_done(void)
{ __asm__ volatile("dsb osh" ::: "memory"); }
static inline void redfin_er_imem_done(void)
{ __asm__ volatile("dsb sy" ::: "memory"); }
static inline uint64_t redfin_er_counter(void)
{ uint64_t n; __asm__ volatile("mrs %0, cntpct_el0" : "=r"(n) :: "memory"); return n; }
static inline uint64_t redfin_er_frequency(void)
{ uint64_t n; __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(n) :: "memory"); return n; }
static inline void redfin_er_relax(void)
{ __asm__ volatile("yield" ::: "memory"); }
/* REDFIN_EARLY_RETURN_HW_END */

static inline bool redfin_er_base(uintptr_t base,size_t bytes)
{ return base && !(base&3) && bytes<=UINTPTR_MAX-base; }
static inline bool redfin_er_target_valid(const struct redfin_er_target *t)
{
 return t && t->version>=0x50000000u && t->version<0x70000000u &&
  t->apid<512 && t->owner==0 && t->mapping && ((t->mapping>>8)&0xfff)==0x008;
}
/* Discovery is read-only and preserves the existing Linux EE0 preference. */
static inline int
redfin_er_find(uintptr_t core,uintptr_t config,struct redfin_er_target *out)
{
 if(!out || !redfin_er_base(core,0x1100) || !redfin_er_base(config,0x26000)) return REDFIN_ER_INVALID;
 uint32_t version=redfin_er_rd(core,0);
 if(version<0x50000000u || version>=0x70000000u) return REDFIN_ER_UNSUPPORTED;
 struct redfin_er_target found={version,0,512,0xff};
 for(unsigned i=0;i<512;i++) {
  uint32_t mapping=redfin_er_rd(core,0x900+4*i);
  if(!mapping || ((mapping>>8)&0xfff)!=0x008) continue;
  unsigned owner=redfin_er_rd(config,0x700+4*i)&7;
  if(found.apid==512 || owner==0) { found.apid=i; found.owner=owner; found.mapping=mapping; }
 }
 if(!redfin_er_target_valid(&found)) return REDFIN_ER_NO_TARGET;
 *out=found;
 return REDFIN_ER_OK;
}
static inline bool
redfin_er_matches(const struct redfin_er_io *io,const struct redfin_er_target *t)
{
 return redfin_er_rd(io->core,0)==t->version &&
  redfin_er_rd(io->core,0x900+4*t->apid)==t->mapping &&
  (redfin_er_rd(io->config,0x700+4*t->apid)&7)==0;
}
/* ceil(19.2 ticks/us), with a second finite bound if the counter stalls.
 * Each transaction has at most1000 status polls and at most4097 counter
 * samples per wait, including the initial sample. Subtraction tolerates wrap. */
static inline int redfin_er_wait_us(void)
{
 uint64_t start=redfin_er_counter();
 for(unsigned i=0;i<4096;i++) {
  if(redfin_er_counter()-start>=20) return REDFIN_ER_OK;
  redfin_er_relax();
 }
 return REDFIN_ER_CLOCK;
}
static inline int redfin_er_poll(uintptr_t base,unsigned offset)
{
 for(unsigned i=0;i<1000;i++) {
  uint32_t status=redfin_er_rd(base,offset);
  if(status&1) return (status&0x0e)?REDFIN_ER_IO:REDFIN_ER_OK;
  int error=redfin_er_wait_us();
  if(error) return error;
 }
 return REDFIN_ER_TIMEOUT;
}
/* Cannot encode another SID, peripheral, register or byte count. */
static inline int
redfin_er_observe(const struct redfin_er_io *io,const struct redfin_er_target *t,
 unsigned address,uint8_t *out)
{
 if(!out || !redfin_er_target_valid(t) || (address!=0x0805 && address!=0x088f)) return REDFIN_ER_INVALID;
 unsigned offset=t->apid*0x80;
 redfin_er_read_start();
 redfin_er_wr(io->observer,offset,(1u<<27)|((address&255u)<<4));
 redfin_er_command_done();
 int error=redfin_er_poll(io->observer,offset+8);
 if(error) return error;
 *out=(uint8_t)redfin_er_rd(io->observer,offset+0x18);
 return REDFIN_ER_OK;
}
static inline int
redfin_er_arm(const struct redfin_er_io *io,const struct redfin_er_target *t,
 struct redfin_er_report *report)
{
 if(!report) return REDFIN_ER_INVALID;
 report->stage=REDFIN_ER_PREFLIGHT;
 report->subtype=report->before=report->intended=report->after=0;
 report->imem=0; report->pon_issued=report->imem_issued=false;
 if(!io || !redfin_er_target_valid(t) || !redfin_er_base(io->core,0x1100) ||
    !redfin_er_base(io->config,0x26000) || !redfin_er_base(io->observer,0x100000) ||
    !redfin_er_base(io->channel,0x20) || !redfin_er_base(io->imem,4)) return REDFIN_ER_INVALID;
 if(redfin_er_frequency()!=19200000u || redfin_er_wait_us()) return REDFIN_ER_CLOCK;
 if(!redfin_er_matches(io,t)) return REDFIN_ER_CHANGED;
 report->stage=REDFIN_ER_SUBTYPE;
 int error=redfin_er_observe(io,t,0x0805,&report->subtype);
 if(error) return error;
 if(report->subtype!=4) return REDFIN_ER_UNSUPPORTED;
 report->stage=REDFIN_ER_SPARE;
 error=redfin_er_observe(io,t,0x088f,&report->before);
 if(error) return error;
 report->intended=(report->before&1u)|4u;
 if(!redfin_er_matches(io,t)) return REDFIN_ER_CHANGED;
 report->stage=REDFIN_ER_WRITE;
 redfin_er_wr(io->channel,0x10,report->intended);
 redfin_er_data_done();
 redfin_er_wr(io->channel,0,0x8f0);
 report->pon_issued=true;
 redfin_er_command_done();
 error=redfin_er_poll(io->channel,8);
 if(error) return error;
 report->stage=REDFIN_ER_VERIFY;
 error=redfin_er_observe(io,t,0x088f,&report->after);
 if(error) return error;
 if(report->after!=report->intended) return REDFIN_ER_IO;
 if(!redfin_er_matches(io,t)) return REDFIN_ER_CHANGED;
 report->stage=REDFIN_ER_IMEM;
 redfin_er_wr(io->imem,0,0x77665500u);
 report->imem_issued=true;
 redfin_er_imem_done();
 report->imem=redfin_er_rd(io->imem,0);
 if(report->imem!=0x77665500u) return REDFIN_ER_IO;
 report->stage=REDFIN_ER_DONE;
 return REDFIN_ER_OK;
}
#endif /* REDFIN_EARLY_RETURN_H */
