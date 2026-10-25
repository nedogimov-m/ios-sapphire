/* SPDX-License-Identifier: MIT */
#include "RedfinPanelMode.h"

struct redfin_panel_maps { vm_offset_t base[4]; };
static uint32_t redfin_panel_read(void *context,unsigned bank,uint32_t offset)
{
    struct redfin_panel_maps *maps=(struct redfin_panel_maps *)context;
    uint32_t value=*(volatile uint32_t *)(maps->base[bank]+offset);
    __asm__ volatile("dmb oshld" ::: "memory"); return value;
}
static void redfin_panel_write(void *context,unsigned bank,uint32_t offset,uint32_t value)
{
    struct redfin_panel_maps *maps=(struct redfin_panel_maps *)context;
    *(volatile uint32_t *)(maps->base[bank]+offset)=value;
    __asm__ volatile("dsb oshst" ::: "memory");
}
static uint64_t redfin_panel_time(void *context __unused)
{uint64_t n;absolutetime_to_nanoseconds(mach_absolute_time(),&n);return n;}
static void redfin_panel_delay(void *context __unused,unsigned us)
{if (us>=1000) IOSleep((us+999)/1000);else IODelay(us);}
static void redfin_panel_log_sample(const char *name,const struct redfin_panel_sample *s)
{
    IOLog("REDFIN PANEL TE: %s edges=%u intervals=%u min-us=%u max-us=%u mean-us=%u elapsed-us=%u intf-frames=%u GPIO10-input=1\n",
        name,s->edges,s->intervals,s->minimum_us,s->maximum_us,s->mean_us,s->elapsed_us,s->frames);
}
static uint32_t redfin_panel_mode(IOService *provider,uint32_t requested)
{
    if (requested!=90) return requested;
    /* This property is built only from the captured live FDT and verified
     * two-mode commands. Pointer fields are never accepted from userspace. */
    const uint32_t expected[]={1,1080,2340,554000000,0x0af00000,0x0ae94000,
        0x0ae6b800,0x0f50a000,10,0x80152853,0x80153853};
    uint32_t actual[sizeof(expected)/sizeof(expected[0])]={};
    if (!redfin_gui_selected() || !redfin_fb_data(provider,"redfin,panel-mode",actual,sizeof(actual)) ||
        memcmp(actual,expected,sizeof(actual))) {
        IOLog("REDFIN PANEL:90Hz refused: live hardware contract missing\n");return 60;
    }
    struct redfin_panel_maps maps={};
    /* Check the independent clock controller before touching gated DSI/DPU. */
    maps.base[RP_CC]=ml_io_map(expected[4],0x4000);
    if (!maps.base[RP_CC]) return 60;
    const uint32_t clock_offsets[]={0x2080,0x2028,0x2038,0x200c};
    for (unsigned i=0;i<4;++i) {
        uint32_t clock=redfin_panel_read(&maps,RP_CC,clock_offsets[i]);
        IOLog("REDFIN PANEL CLOCK: offset=%#x value=%#x\n",clock_offsets[i],clock);
        if (!redfin_panel_clock_on(clock)) return 60;
    }
    maps.base[RP_DSI]=ml_io_map(expected[5]&~0x3fffu,0x4000)+(expected[5]&0x3fff);
    maps.base[RP_INTF]=ml_io_map(expected[6]&~0x3fffu,0x4000)+(expected[6]&0x3fff);
    maps.base[RP_GPIO]=ml_io_map(expected[7]&~0x3fffu,0x4000)+(expected[7]&0x3fff);
    if (maps.base[RP_DSI]<(expected[5]&0x3fff)+1 ||
        maps.base[RP_INTF]<(expected[6]&0x3fff)+1 ||
        maps.base[RP_GPIO]<(expected[7]&0x3fff)+1) return 60;
    struct redfin_panel_io io={&maps,redfin_panel_read,redfin_panel_write,redfin_panel_delay,redfin_panel_time};
    struct redfin_panel_result result={};bool switched=redfin_panel_switch_90(&io,&result);
    IOLog("REDFIN PANEL MODE: request=90 actual=%u verified=%u stage=%u version=%#x ctrl=%#x status=%#x tear=%#x auto=%#x gpio=%#x command=%u rollback=%u uncertain=%u FIFO=1 DMA-memory=0\n",
        result.actual_hz,switched,result.stage,result.version,result.control,result.status,result.tear,
        result.autorefresh,result.gpio,result.command_done,result.rollback_done,result.uncertain);
    redfin_panel_log_sample("before",&result.before);redfin_panel_log_sample("after",&result.after);
    if (result.rollback_done) redfin_panel_log_sample("rollback",&result.rollback);
    provider->setProperty("redfin-panel-hz-verified",(unsigned long long)result.actual_hz,32);
    return switched ? 90 : 60;
}
