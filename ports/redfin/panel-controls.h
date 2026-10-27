/* SPDX-License-Identifier: MIT */
/* S6E3HC2 display visibility/brightness on Redfin's already proved DSI2.4
 * embedded FIFO route. No physical DMA buffer, scanout, PLL or GPIO writes. */
#ifndef REDFIN_PANEL_CONTROLS_H
#define REDFIN_PANEL_CONTROLS_H
#include "RedfinPanelMode.h"
#include "RedfinControlsPolicy.h"

struct rf_panel_control_result {
    bool submitted,completed,restored,uncertain;
    uint32_t status;
};

/* Only native DCS0x51 and visibility0x28/0x29 are expressible. The exact
 * source-identified display/mode contract is checked by the kernel owner.
 * A timed-out transaction owns the FIFO until reset; never reset/retry it. */
static inline bool rf_panel_control(const struct redfin_panel_io *io,bool brightness,
    uint32_t value,struct rf_panel_control_result *result)
{
    if(!result)return false;
    *result=(struct rf_panel_control_result){0};
    if(!io||!io->read||!io->write||!io->delay||!io->now_ns||
        (brightness?value>RF_PANEL_DBV_MAX:value>1))return false;
    const uint32_t clocks[]={0x2080,0x2028,0x2038,0x200c};
    for(unsigned i=0;i<4;++i)
        if(!redfin_panel_clock_on(rp_read(io,RP_CC,clocks[i])))return false;
    if((rp_read(io,RP_DSI,0)&0xffff0000u)!=0x20040000u||!redfin_panel_idle(io))return false;
    uint32_t control=rp_read(io,RP_DSI,4),trigger=rp_read(io,RP_DSI,0x84);
    uint32_t dma=rp_read(io,RP_DSI,0x3c),pattern=rp_read(io,RP_DSI,0x15c);
    uint32_t length=rp_read(io,RP_DSI,0x4c),interrupts=rp_read(io,RP_DSI,0x110);
    if(!(control&1)||(control&2)||pattern||(trigger&7)!=4||(interrupts&(1u<<24)))return false;
    const uint32_t masks=(1u<<1)|(1u<<9)|(1u<<11)|(1u<<13)|(1u<<15)|
        (1u<<17)|(1u<<21)|(1u<<25)|(1u<<29)|(1u<<31);
    uint32_t saved_masks=interrupts&masks;
    rp_write(io,RP_DSI,0x110,saved_masks|1);
    if(rp_read(io,RP_DSI,0x110)&1)return false;
    rp_write(io,RP_DSI,4,control|4);
    rp_write(io,RP_DSI,0x15c,0x30006);
    uint32_t words[2],bytes;
    if(brightness) {
        words[0]=0xc0390003u; /* long DCS packet: three payload bytes */
        words[1]=0xff000051u|((value>>8)<<8)|((value&255u)<<16);bytes=8;
    } else {
        /* Header bytes are command, parameter0, DCS datatype05, last80. */
        words[0]=0x80050000u|(value?0x29u:0x28u);words[1]=0;bytes=4;
    }
    rp_write(io,RP_DSI,0x17c,words[0]);rp_write(io,RP_DSI,0x17c,words[1]);
    uint32_t selected=(dma&~((3u<<30)|(1u<<29)|(1u<<24)))|(1u<<28)|(1u<<26);
    rp_write(io,RP_DSI,0x3c,selected);rp_write(io,RP_DSI,0x4c,bytes);
    if(rp_read(io,RP_DSI,0x3c)!=selected||rp_read(io,RP_DSI,0x4c)!=bytes) {
        rp_write(io,RP_DSI,0x15c,pattern);rp_write(io,RP_DSI,0x3c,dma);
        rp_write(io,RP_DSI,0x4c,length);rp_write(io,RP_DSI,4,control);return false;
    }
    rp_write(io,RP_DSI,0x90,1);result->submitted=true;
    for(unsigned poll=0;poll<4000;++poll) {
        result->status=rp_read(io,RP_DSI,0x110);
        if(result->status&(1u<<24))break;
        if(result->status&1){result->completed=true;break;}
        io->delay(io->context,5);
    }
    if(!result->completed||!redfin_panel_idle(io)){result->uncertain=true;return false;}
    rp_write(io,RP_DSI,0x110,saved_masks|1);
    rp_write(io,RP_DSI,0x15c,pattern);
    rp_write(io,RP_DSI,0x1ec,1);io->delay(io->context,1);rp_write(io,RP_DSI,0x1ec,0);
    rp_write(io,RP_DSI,0x3c,dma);rp_write(io,RP_DSI,0x4c,length);rp_write(io,RP_DSI,4,control);
    result->restored=rp_read(io,RP_DSI,4)==control&&rp_read(io,RP_DSI,0x3c)==dma&&
        rp_read(io,RP_DSI,0x4c)==length&&rp_read(io,RP_DSI,0x15c)==pattern;
    result->uncertain=!result->restored;
    return result->restored;
}
#endif
