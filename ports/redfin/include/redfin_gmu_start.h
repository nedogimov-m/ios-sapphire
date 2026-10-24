/* SPDX-License-Identifier: MIT */
/* A620 cold GMU/PDC/RSC start and a fresh HFI v2 version exchange.
 * Native msm500b3a2059c1eec0fec08ec56add06320ea901a8; preferred upstream
 * redwood_adreno.c steps15/16. No GX request, performance tables or GPU CP.
 */
#ifndef REDFIN_GMU_START_H
#define REDFIN_GMU_START_H
#include <stdbool.h>
#include <string.h>
#include "redfin_gmu_firmware.h"

enum { RF_GB_GMU, RF_GB_RSC, RF_GB_PDC, RF_GB_SEQ, RF_GB_GBIF, RF_GB_UNITS };
enum { RF_GB_HELD, RF_GB_FW_WAIT, RF_GB_FW_LIVE, RF_GB_HFI_WAIT, RF_GB_HFI_LIVE };
#define RF_GB_MAX_STORES 96u
#define RF_GB_WAIT_NS UINT64_C(500000000)

struct rf_gb_config {
    uint32_t chip, core_version, hfi_version, hfi_address, log_address;
    uint32_t xo, cx, mx, vrm, rpmh;
};
struct rf_gb_store { uint32_t unit, at, value, mask; };
struct rf_gb_report {
    unsigned attempted, stage, phase, stores, polls, released, firmware, hfi, ack;
    uint32_t last_unit, last_offset, wanted, observed, init, hfi_status, version;
    uint32_t rsc_status, rsc_busy, tcs[4];
    struct rf_gb_store program[RF_GB_MAX_STORES];
    unsigned program_count;
    int error;
};
struct rf_gb_ops {
    void *context;
    int (*guard)(void *, unsigned phase);
    int (*read)(void *, unsigned unit, uint32_t at, uint32_t *);
    int (*write)(void *, unsigned unit, uint32_t at, uint32_t value);
    int (*audit)(void *, unsigned phase);
    int (*exchange)(void *, uint32_t *version);
    int (*delay)(void *, unsigned us);
    uint64_t (*time_ns)(void *);
};

static inline bool rf_gb_config_valid(const struct rf_gb_config *c)
{
    return c && c->chip == 0x06020001u && c->core_version &&
        (c->hfi_version >> 28) == 2 && c->hfi_address == 0x60001000u &&
        c->log_address == 0x60006000u && c->xo && c->cx && c->mx &&
        !((c->xo | c->cx | c->mx | c->vrm) & 3u) &&
        (c->xo >> 16) == 3 && (c->cx >> 16) == 3 && (c->mx >> 16) == 3 &&
        c->xo != c->cx && c->xo != c->mx && c->cx != c->mx &&
        (!c->vrm || ((c->vrm >> 16) == 4 && c->vrm <= UINT32_MAX - 4));
}

static inline int rf_gb_add(struct rf_gb_report *r, unsigned unit, uint32_t at,
    uint32_t value, uint32_t mask)
{
    if (r->program_count == RF_GB_MAX_STORES) return ENOSPC;
    r->program[r->program_count++] = (struct rf_gb_store){unit, at, value, mask};
    return 0;
}

static inline int rf_gb_program(const struct rf_gb_config *c, struct rf_gb_report *r)
{
    static const uint32_t rsc_code[] = {0xeaaae5a0,0xe1a1ebab,0xa2e0a581,0xecac82e2,0x0020edad};
    static const uint32_t pdc_code[] = {0xfebea1e1,0xa5a4a3a2,0x8382a6e0,0xbce3e284,0x002081fc};
    int error;
    if (!r || !rf_gb_config_valid(c)) return EINVAL;
    r->program_count = 0;
#define RF_GB_ADD(u,a,v,m) do { error=rf_gb_add(r,u,a,v,m); if(error)return error; } while(0)
    RF_GB_ADD(RF_GB_GMU,0x24c18,UINT32_MAX,0x29); /* Native GMU_AO_INT_MASK. */
    RF_GB_ADD(RF_GB_GMU,0x1464c,UINT32_MAX,7); /* Native HFI_IRQ_MASK. */
    RF_GB_ADD(RF_GB_GMU,0x24c10,UINT32_MAX,0); /* Owned local interrupt W1C. */
    RF_GB_ADD(RF_GB_GMU,0x14644,UINT32_MAX,0);
    RF_GB_ADD(RF_GB_RSC,0x10,1u<<24,0); /* Disable SDE gating, status/command. */
    RF_GB_ADD(RF_GB_RSC,0x2c,1,0xff);
    for (unsigned i=0;i<3;++i) {
        RF_GB_ADD(RF_GB_RSC,0x38+8*i,i==2?0x80000000u:0,UINT32_MAX);
        /* Native writes zero, but these hidden destinations are hard-wired
         * on Redfin (e.g. CMD0 reads 0x82204514). Do not require zero. */
        RF_GB_ADD(RF_GB_RSC,0x34+8*i,0,0);
    }
    RF_GB_ADD(RF_GB_RSC,0x400,0,0xffff);
    RF_GB_ADD(RF_GB_RSC,0x20,0x4520,0xffff);
    RF_GB_ADD(RF_GB_RSC,0x24,0x4510,0xffff);
    RF_GB_ADD(RF_GB_RSC,0x28,0x4514,0xffff);
    for (unsigned i=0;i<5;++i) RF_GB_ADD(RF_GB_RSC,0x600+4*i,rsc_code[i],UINT32_MAX);
    for (unsigned i=0;i<5;++i) RF_GB_ADD(RF_GB_SEQ,4*i,pdc_code[i],UINT32_MAX);
    for (unsigned group=0;group<2;++group) {
        uint32_t base=4u*(group?0x15d6:0x1572);
        RF_GB_ADD(RF_GB_PDC,base+4,7,0xffff);
        RF_GB_ADD(RF_GB_PDC,base+8,0,0xffff);
        RF_GB_ADD(RF_GB_PDC,base,0,0x1010000);
        uint32_t addresses[4]={c->mx,c->cx,c->xo,c->vrm?c->vrm+4:0};
        uint32_t values[4]={group?2u:1u,group?2u:0u,group?3u:0u,group?1u:0u};
        for (unsigned cmd=0;cmd<(c->vrm?4u:3u);++cmd) {
            RF_GB_ADD(RF_GB_PDC,base+12+16*cmd,0x10108,0x3ffff);
            RF_GB_ADD(RF_GB_PDC,base+16+16*cmd,addresses[cmd],UINT32_MAX);
            RF_GB_ADD(RF_GB_PDC,base+20+16*cmd,values[cmd],UINT32_MAX);
        }
    }
    RF_GB_ADD(RF_GB_PDC,0x4520,0,0xffff);
    RF_GB_ADD(RF_GB_PDC,0x4500,0x80000001,0x80000001);
    /* A620 vetoes FAL10; the A642L-only FALNEXT register is not used. */
    RF_GB_ADD(RF_GB_GMU,0x143c0,1,1);
    RF_GB_ADD(RF_GB_GMU,0x14070,0,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x14004,2,3);
    RF_GB_ADD(RF_GB_GMU,0x14614,c->hfi_address,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x14610,1,1);
    RF_GB_ADD(RF_GB_GMU,0x24c44,0x80a008a0,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x140b4,0x4052,0xffff);
    RF_GB_ADD(RF_GB_GBIF,0x114,0,7);
    RF_GB_ADD(RF_GB_GMU,0x14404,0,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x14608,0x06020100,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x14400,c->log_address,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x1303c,1,1);
    RF_GB_ADD(RF_GB_GMU,0x13000,1,1);
    RF_GB_ADD(RF_GB_GMU,0x13004,1,1);
    RF_GB_ADD(RF_GB_GMU,0x14300,0x09c40400,UINT32_MAX);
    RF_GB_ADD(RF_GB_GMU,0x143a0,c->rpmh|0xf11u,0xf11);
#undef RF_GB_ADD
    return 0;
}

static inline int rf_gb_read(struct rf_gb_report *s,const struct rf_gb_ops *o,
    unsigned unit,uint32_t at,uint32_t *value)
{
    int error=o->guard(o->context,s->phase);
    if(!error)error=o->read(o->context,unit,at,value);
    return error;
}
static inline int rf_gb_write(struct rf_gb_report *s,const struct rf_gb_ops *o,
    unsigned unit,uint32_t at,uint32_t value,uint32_t mask)
{
    int error=o->guard(o->context,s->phase);
    if(error)return error;
    s->last_unit=unit;s->last_offset=at;s->wanted=value;s->observed=0;
    ++s->stores;
    error=o->write(o->context,unit,at,value);
    if(error || !mask)return error;
    error=rf_gb_read(s,o,unit,at,&s->observed);
    if(!error && ((s->observed^value)&mask))error=EIO;
    return error;
}
static inline int rf_gb_poll(struct rf_gb_report *s,const struct rf_gb_ops *o,
    unsigned unit,uint32_t at,uint32_t wanted,uint32_t mask,uint32_t *out)
{
    uint64_t first=o->time_ns(o->context);
    for(unsigned i=0;i<5000;++i) {
        int error=rf_gb_read(s,o,unit,at,out);if(error)return error;
        ++s->polls;
        if((*out&mask)==wanted)return 0;
        if(o->time_ns(o->context)-first>=RF_GB_WAIT_NS)return ETIMEDOUT;
        error=o->delay(o->context,100);if(error)return error;
    }
    return ETIMEDOUT;
}

static inline int rf_gb_run(struct rf_gb_report *s,struct rf_gb_config *c,const struct rf_gb_ops *o)
{
    int error=EINVAL;
    if(!s || !c || !o || !o->guard || !o->read || !o->write || !o->audit ||
        !o->exchange || !o->delay || !o->time_ns)return error;
    if(s->attempted)return EBUSY;
    s->attempted=1;s->phase=RF_GB_HELD;s->stage=1;
    if(!rf_gb_config_valid(c))goto done;
#define RF_GB_TRY(x) do {error=(x);if(error)goto done;} while(0)
    RF_GB_TRY(o->guard(o->context,s->phase));
    RF_GB_TRY(o->audit(o->context,s->phase));
    RF_GB_TRY(rf_gb_read(s,o,RF_GB_RSC,0x10,&s->rsc_status));
    RF_GB_TRY(rf_gb_read(s,o,RF_GB_RSC,0x404,&s->rsc_busy));
    if(s->rsc_busy){error=EBUSY;goto done;}
    /* A620's separate RSC resource is 4KiB: TCS0/1 only. The generic
     * native helper also names TCS2/3 beyond this resource; do not follow. */
    for(unsigned i=0;i<2;++i) {
        RF_GB_TRY(rf_gb_read(s,o,RF_GB_RSC,4u*(0x346+0xa8*i),&s->tcs[i]));
        uint32_t control;
        RF_GB_TRY(rf_gb_read(s,o,RF_GB_RSC,4u*(0x346+0xa8*i)-4,&control));
        if(control&(1u<<16)){error=EBUSY;goto done;}
    }
    RF_GB_TRY(rf_gb_read(s,o,RF_GB_GMU,0x143a0,&c->rpmh));
    RF_GB_TRY(rf_gb_program(c,s));
    /* Apply masking before a possible inherited RSC wake; no GIC enables. */
    for(unsigned i=0;i<4;++i) {
        struct rf_gb_store *w=&s->program[i];
        RF_GB_TRY(rf_gb_write(s,o,w->unit,w->at,w->value,w->mask));
    }
    if(s->rsc_status&(1u<<16)) {
        uint32_t ack;
        RF_GB_TRY(rf_gb_write(s,o,RF_GB_GMU,0x24c1c,2,3));
        RF_GB_TRY(rf_gb_poll(s,o,RF_GB_GMU,0x24c20,2,2,&ack));
        RF_GB_TRY(rf_gb_poll(s,o,RF_GB_RSC,0x404,0,UINT32_MAX,&s->rsc_busy));
        RF_GB_TRY(rf_gb_write(s,o,RF_GB_GMU,0x24c1c,0,3));
    }
    s->stage=2;
    for(unsigned i=4;i<s->program_count;++i) {
        struct rf_gb_store *w=&s->program[i];
        RF_GB_TRY(rf_gb_write(s,o,w->unit,w->at,w->value,w->mask));
    }
    RF_GB_TRY(o->audit(o->context,s->phase));
    /* Fresh zero is verified immediately before the sole reset release. */
    RF_GB_TRY(rf_gb_read(s,o,RF_GB_GMU,0x14070,&s->init));
    if(s->init){error=EAGAIN;goto done;}
    s->stage=3;
    RF_GB_TRY(o->guard(o->context,RF_GB_HELD));
    s->phase=RF_GB_FW_WAIT;
    s->last_unit=RF_GB_GMU;s->last_offset=0x14000;s->wanted=0;s->observed=0;
    ++s->stores;s->released=1;
    RF_GB_TRY(o->write(o->context,RF_GB_GMU,0x14000,0));
    uint64_t first=o->time_ns(o->context);
    error=ETIMEDOUT;
    for(unsigned i=0;i<5000;++i) {
        RF_GB_TRY(rf_gb_read(s,o,RF_GB_GMU,0x14070,&s->init));
        ++s->polls;
        if(c->core_version>0x20010004u && (s->init&0xe00u)){error=EIO;goto done;}
        if(redfin_gmu_started(c->core_version,s->init)){error=0;break;}
        if(o->time_ns(o->context)-first>=RF_GB_WAIT_NS){error=ETIMEDOUT;goto done;}
        RF_GB_TRY(o->delay(o->context,100));
        error=ETIMEDOUT;
    }
    if(error)goto done;
    s->firmware=1;s->phase=RF_GB_FW_LIVE;s->stage=4;
    RF_GB_TRY(o->audit(o->context,s->phase));
    s->phase=RF_GB_HFI_WAIT;
    RF_GB_TRY(rf_gb_write(s,o,RF_GB_GMU,0x14618,1,1));
    RF_GB_TRY(rf_gb_poll(s,o,RF_GB_GMU,0x14600,1,1,&s->hfi_status));
    s->hfi=1;s->phase=RF_GB_HFI_LIVE;s->stage=5;
    RF_GB_TRY(o->exchange(o->context,&s->version));
    if((s->version>>28)!=2u){error=EPROTO;goto done;}
    s->ack=1;
    RF_GB_TRY(o->audit(o->context,s->phase));
    s->stage=6;error=0;
done:
    s->error=error;
#undef RF_GB_TRY
    return error;
}

/* HFI v2 ACK: reply type1, original full request header, status, version.
 * ID126 is a v1 convention and is not required for a v2 response. */
static inline int rf_gb_version_ack(const uint32_t *words,unsigned count,uint32_t request,
    uint32_t expected,uint32_t *version)
{
    if(!words || !version || count<4 || count>255 || ((words[0]>>8)&255u)!=count ||
        ((words[0]>>16)&15u)!=1 || words[1]!=request)return EPROTO;
    if(words[2])return EIO;
    if((words[3]>>28)!=(expected>>28) ||
        ((words[3]>>16)&0xfffu)<((expected>>16)&0xfffu))return EPROTONOSUPPORT;
    *version=words[3];return 0;
}
#endif
