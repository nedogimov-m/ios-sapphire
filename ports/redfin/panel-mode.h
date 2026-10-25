/* SPDX-License-Identifier: MIT */
/* Bounded S6E3HC2 mode transaction. Register and packet facts are from
 * Google's Redfin500b3a20 DTS/clock/pinctrl and display-drivers ca74909c.
 * No DMA address, DPU source, DSC, PLL, SMMU or GPIO configuration writes.
 * The caller validates the live hardware/ADT and serializes this owner. */
#ifndef REDFIN_PANEL_MODE_H
#define REDFIN_PANEL_MODE_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

enum redfin_panel_bank { RP_DSI,RP_INTF,RP_GPIO,RP_CC };
struct redfin_panel_io {
    void *context;
    uint32_t (*read)(void *,unsigned,uint32_t);
    void (*write)(void *,unsigned,uint32_t,uint32_t);
    void (*delay)(void *,unsigned);
    uint64_t (*now_ns)(void *);
};
struct redfin_panel_sample {
    uint32_t edges,intervals,minimum_us,maximum_us,mean_us;
    uint32_t frames,elapsed_us;
};
struct redfin_panel_result {
    uint32_t stage,actual_hz,version,control,status,tear,autorefresh,gpio;
    bool command_done,rollback_done,uncertain;
    struct redfin_panel_sample before,after,rollback;
};
static inline uint32_t rp_read(const struct redfin_panel_io *io,unsigned bank,uint32_t reg)
{return io->read(io->context,bank,reg);}
static inline void rp_write(const struct redfin_panel_io *io,unsigned bank,uint32_t reg,uint32_t value)
{io->write(io->context,bank,reg,value);}

static inline bool redfin_panel_clock_on(uint32_t cbcr)
{return cbcr!=UINT32_MAX && (cbcr&1) && !(cbcr&(1u<<31));}

static inline void redfin_panel_measure(const struct redfin_panel_io *io,
    struct redfin_panel_sample *out)
{
    *out=(struct redfin_panel_sample){0};
    uint64_t began=io->now_ns(io->context),last=0,total=0;
    uint32_t old=rp_read(io,RP_GPIO,4)&1,frames=rp_read(io,RP_INTF,0xac);
    out->minimum_us=UINT32_MAX;
    /* Also bounded by iterations if a clock stalls. GPIO10 is sampled only;
     * neither its mux nor interrupt status is modified. */
    for (unsigned i=0;i<100000;++i) {
        uint64_t now=io->now_ns(io->context);
        if (now<began || now-began>=350000000) break;
        uint32_t level=rp_read(io,RP_GPIO,4)&1;
        if (level && !old) {
            ++out->edges;
            if (last && now>last) {
                uint64_t us=(now-last)/1000;
                if (us>UINT32_MAX) break;
                if (us<out->minimum_us) out->minimum_us=(uint32_t)us;
                if (us>out->maximum_us) out->maximum_us=(uint32_t)us;
                total+=us; ++out->intervals;
            }
            last=now;
        }
        old=level; io->delay(io->context,3);
    }
    uint64_t end=io->now_ns(io->context);
    if (end>=began && (end-began)/1000<=UINT32_MAX) out->elapsed_us=(uint32_t)((end-began)/1000);
    out->frames=rp_read(io,RP_INTF,0xac)-frames;
    if (out->intervals) out->mean_us=(uint32_t)(total/out->intervals);
    else out->minimum_us=0;
}
static inline bool redfin_panel_sample_is(const struct redfin_panel_sample *s,unsigned hz)
{
    if (!s || s->intervals<15 || s->elapsed_us<250000 || s->elapsed_us>500000) return false;
    uint32_t target=1000000/hz,slop=target/16;
    return s->mean_us>=target-slop && s->mean_us<=target+slop &&
        s->minimum_us>=target-target/5 && s->maximum_us<=target+target/5;
}
static inline bool redfin_panel_idle(const struct redfin_panel_io *io)
{
    for (unsigned i=0;i<4000;++i) {
        if (!(rp_read(io,RP_DSI,8)&6u)) return true;
        io->delay(io->context,5);
    }
    return false;
}
/* Only the two source-verified timing commands are expressible here. A fresh
 * DMA-done edge is mandatory; old status is acknowledged before the trigger.
 * On uncertain completion leave the FIFO/engine alone until the next reset. */
static inline bool redfin_panel_command(const struct redfin_panel_io *io,unsigned hz,bool *uncertain)
{
    if (!uncertain || (hz!=60 && hz!=90) || !redfin_panel_idle(io)) return false;
    uint32_t control=rp_read(io,RP_DSI,4),trigger=rp_read(io,RP_DSI,0x84);
    uint32_t dma=rp_read(io,RP_DSI,0x3c),tpg=rp_read(io,RP_DSI,0x15c);
    uint32_t length=rp_read(io,RP_DSI,0x4c),interrupts=rp_read(io,RP_DSI,0x110);
    if (!(control&1) || (control&2) || tpg || (trigger&7)!=4 || (interrupts&(1u<<24))) return false;
    const uint32_t masks=(1u<<1)|(1u<<9)|(1u<<11)|(1u<<13)|(1u<<15)|
        (1u<<17)|(1u<<21)|(1u<<25)|(1u<<29)|(1u<<31);
    uint32_t saved_masks=interrupts&masks;
    rp_write(io,RP_DSI,0x110,saved_masks|1);
    if (rp_read(io,RP_DSI,0x110)&1) return false;
    rp_write(io,RP_DSI,4,control|4);
    rp_write(io,RP_DSI,0x15c,0x30006); /* custom embedded FIFO, no memory fetch */
    rp_write(io,RP_DSI,0x17c,hz==90 ? 0x80153853 : 0x80152853);
    rp_write(io,RP_DSI,0x17c,0); /* hardware requires an even count of DWORDs */
    uint32_t selected=(dma&~((3u<<30)|(1u<<29)|(1u<<24)))|(1u<<28)|(1u<<26);
    rp_write(io,RP_DSI,0x3c,selected);
    rp_write(io,RP_DSI,0x4c,4);
    if (rp_read(io,RP_DSI,0x3c)!=selected || rp_read(io,RP_DSI,0x4c)!=4) {
        rp_write(io,RP_DSI,0x15c,tpg);rp_write(io,RP_DSI,0x3c,dma);
        rp_write(io,RP_DSI,0x4c,length);rp_write(io,RP_DSI,4,control);return false;
    }
    rp_write(io,RP_DSI,0x90,1);
    bool done=false;
    for (unsigned i=0;i<4000;++i) {
        uint32_t status=rp_read(io,RP_DSI,0x110);
        if (status&(1u<<24)) break;
        if (status&1) {done=true;break;}
        io->delay(io->context,5);
    }
    if (!done || !redfin_panel_idle(io)) {*uncertain=true;return false;}
    rp_write(io,RP_DSI,0x110,saved_masks|1);
    rp_write(io,RP_DSI,0x15c,tpg);
    rp_write(io,RP_DSI,0x1ec,1);io->delay(io->context,1);rp_write(io,RP_DSI,0x1ec,0);
    rp_write(io,RP_DSI,0x3c,dma);rp_write(io,RP_DSI,0x4c,length);rp_write(io,RP_DSI,4,control);
    bool restored=rp_read(io,RP_DSI,4)==control && rp_read(io,RP_DSI,0x3c)==dma &&
        rp_read(io,RP_DSI,0x4c)==length && rp_read(io,RP_DSI,0x15c)==tpg;
    if (!restored) *uncertain=true;
    return restored;
}

static inline bool redfin_panel_switch_90(const struct redfin_panel_io *io,
    struct redfin_panel_result *out)
{
    if (!io || !out || !io->read || !io->write || !io->delay || !io->now_ns) return false;
    *out=(struct redfin_panel_result){0};out->stage=1;
    if (!redfin_panel_clock_on(rp_read(io,RP_CC,0x2080)) ||
        !redfin_panel_clock_on(rp_read(io,RP_CC,0x2028)) ||
        !redfin_panel_clock_on(rp_read(io,RP_CC,0x2038)) ||
        !redfin_panel_clock_on(rp_read(io,RP_CC,0x200c))) return false;
    out->stage=2;out->version=rp_read(io,RP_DSI,0);
    out->control=rp_read(io,RP_DSI,4);out->status=rp_read(io,RP_DSI,8);
    out->tear=rp_read(io,RP_INTF,0x288);out->autorefresh=rp_read(io,RP_INTF,0x2b4);
    out->gpio=rp_read(io,RP_GPIO,0);
    /* Source-identified DSI2.4/TE0 command-mode handoff only. */
    if ((out->version&0xffff0000u)!=0x20040000u || !(out->control&1) ||
        (out->control&2) || rp_read(io,RP_DSI,0x2cc) || (out->gpio&0x3c)!=4 ||
        (out->gpio&(1u<<9))) return false;
    out->stage=3;redfin_panel_measure(io,&out->before);
    if (redfin_panel_sample_is(&out->before,90)) {out->actual_hz=90;out->stage=8;return true;}
    if (!redfin_panel_sample_is(&out->before,60)) return false;
    out->actual_hz=60;out->stage=4;
    /* Keep the inherited external-TE autorefresh path and its source. Never
     * synthesize a faster frame counter as evidence of panel refresh. */
    if (!(rp_read(io,RP_INTF,0x284)&1) || !(out->tear&(1u<<20)) ||
        !(out->autorefresh&(1u<<31)) || (out->autorefresh&0xffff)!=1 ||
        !(out->tear&0xffff)) return false;
    out->stage=5;
    out->command_done=redfin_panel_command(io,90,&out->uncertain);
    if (!out->command_done) {if(out->uncertain) out->actual_hz=0;return false;}
    uint32_t updated=(out->tear&0xffff0000u)|((out->tear&0xffff)*2/3);
    rp_write(io,RP_INTF,0x288,updated);
    io->delay(io->context,40000);
    out->stage=6;redfin_panel_measure(io,&out->after);
    if (rp_read(io,RP_INTF,0x288)==updated && redfin_panel_sample_is(&out->after,90)) {
        out->actual_hz=90;out->stage=8;return true;
    }
    out->actual_hz=0;out->stage=7;
    if (!out->uncertain) out->rollback_done=redfin_panel_command(io,60,&out->uncertain);
    if (out->rollback_done) {
        rp_write(io,RP_INTF,0x288,out->tear);io->delay(io->context,40000);
        redfin_panel_measure(io,&out->rollback);
        if (redfin_panel_sample_is(&out->rollback,60)) out->actual_hz=60;
    }
    return false;
}
#endif
