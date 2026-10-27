/* SPDX-License-Identifier: MIT */
/* Preferred HackiOS c84b4634 button ownership/debounce model, adapted to
 * Redfin's PM8150 PON and PM8150L GPIO5 and the existing native HID service.
 * This runs only on the power worker, including between ADC polls. */
#include "RedfinControlsPolicy.h"
extern "C" void sweet_hid_key(int,int);
extern "C" uint64_t redfin_hid_buttons_epoch(void);
extern "C" int redfin_gui_selected(void);

static const uint32_t keys_contract[]={1,0x0c440000,0x0c40a000,0x0e600000,0,0x008,0x4c4,0x0810,0xc410,15};
static power_target keys_targets[2]={{0x008,512,0,0,0},{0x4c4,512,0,0,0}};
static bool keys_attempted;
static unsigned keys_usable,keys_samples,keys_errors,keys_last_report,keys_presses[3],keys_releases[3],keys_cancels;
static uint64_t keys_next;
static struct rf_keys_state keys_state;
static unsigned keys_armed,keys_consumer;
SYSCTL_NODE(_kern,OID_AUTO,redfin_controls,CTLFLAG_RD|CTLFLAG_LOCKED,0,"Native Redfin physical controls");
SYSCTL_UINT(_kern_redfin_controls,OID_AUTO,keys_usable,CTLFLAG_RD|CTLFLAG_LOCKED,&keys_usable,0,"Source-verified physical input mask");
SYSCTL_UINT(_kern_redfin_controls,OID_AUTO,keys_samples,CTLFLAG_RD|CTLFLAG_LOCKED,&keys_samples,0,"Actual input samples");
SYSCTL_UINT(_kern_redfin_controls,OID_AUTO,keys_errors,CTLFLAG_RD|CTLFLAG_LOCKED,&keys_errors,0,"Actual input read errors");
SYSCTL_UINT(_kern_redfin_controls,OID_AUTO,keys_armed,CTLFLAG_RD|CTLFLAG_LOCKED,&keys_armed,0,"Released and debounced physical keys");
SYSCTL_UINT(_kern_redfin_controls,OID_AUTO,keys_consumer,CTLFLAG_RD|CTLFLAG_LOCKED,&keys_consumer,0,"Native HID consumer present");

static int keys_byte(unsigned which,unsigned address,uint8_t *out)
{
    if(which>=2||!out)return EINVAL;
    const power_target *target=&keys_targets[which];
    if((address>>8)!=(target->ppid&255)||!power_match(target))return ENXIO;
    /* READ_LONG observer framing only. No writer channel, interrupt ack,
     * PON/reset configuration or GPIO mux/pull/direction write exists. */
    unsigned channel=target->apid*0x80;
    power_wr(power_observer,channel,(1u<<27)|((address&255)<<4));
    int error=power_poll(power_observer,channel+8);if(error)return error;
    uint8_t value=(uint8_t)power_rd(power_observer,channel+0x18);
    if(!power_match(target)){power_spmi_ok=false;return EAGAIN;}
    *out=value;return 0;
}

static void keys_emit(void *context __unused,unsigned key,bool down,bool physical)
{
    if(key>=3)return;
    if(physical){if(down)++keys_presses[key];else ++keys_releases[key];}else ++keys_cancels;
    sweet_hid_key((int)key,down?1:0);
    IOLog("REDFIN KEYS EVENT: key=%u down=%u consumer-epoch=%llu physical-edge=%u\n",
        key,down,keys_state.epoch,physical);
}

static void keys_initialize(void)
{
    keys_attempted=true;
    if(!power_spmi_ok||!redfin_gui_selected())return;
    IORegistryEntry *node=IORegistryEntry::fromPath("/redfin-controls",gIODTPlane);
    if(!node)return;
    OSData *data=OSDynamicCast(OSData,node->getProperty("keys-contract"));
    bool exact=data&&data->getLength()==sizeof(keys_contract)&&
        !memcmp(data->getBytesNoCopy(),keys_contract,sizeof(keys_contract));
    node->release();if(!exact)return;
    for(unsigned apid=0;apid<512;++apid) {
        uint32_t mapping=power_rd(power_core,0x900+4*apid);unsigned ppid=(mapping>>8)&0xfff;
        if(!mapping)continue;
        for(unsigned i=0;i<2;++i)if(ppid==keys_targets[i].ppid) {
            unsigned owner=power_rd(power_config,0x700+4*apid)&7;
            if(keys_targets[i].apid==512||owner==0)
                keys_targets[i]=(power_target){ppid,apid,owner,mapping,0};
        }
    }
    uint8_t pon_type=0,pon_subtype=0,gpio_type=0,gpio_subtype=0,mode=0,enable=0,pull=0;
    int pon=keys_byte(0,0x0804,&pon_type);
    if(!pon)pon=keys_byte(0,0x0805,&pon_subtype);
    /* Native qpnp-power-on RT_STS bits0/1 are shared by gen1/gen2 types1..5.
     * POCO's separate gen3 HLOS block/status bits are intentionally refused. */
    if(!pon&&pon_type==1&&pon_subtype>=1&&pon_subtype<=5)keys_usable|=5;
    int gpio=keys_byte(1,0xc404,&gpio_type);
    if(!gpio)gpio=keys_byte(1,0xc405,&gpio_subtype);
    if(!gpio)gpio=keys_byte(1,0xc440,&mode);
    if(!gpio)gpio=keys_byte(1,0xc446,&enable);
    if(!gpio)gpio=keys_byte(1,0xc442,&pull);
    if(!gpio&&gpio_type==0x10&&gpio_subtype>=0x10&&gpio_subtype<=0x13&&
        ((mode&3)==0||(mode&3)==2)&&(enable&0x80)&&(pull&7)<=3)keys_usable|=2;
    IOLog("REDFIN KEYS START: usable=%u PON=%#x/%#x result=%d GPIO5=%#x/%#x mode=%#x enable=%#x pull=%#x result=%d observer-only=1 poll-ms=10 debounce-ms=15\n",
        keys_usable,pon_type,pon_subtype,pon,gpio_type,gpio_subtype,mode,enable,pull,gpio);
}

static void redfin_keys_poll(void)
{
    uint64_t now=power_now();if(now<keys_next)return;keys_next=now+UINT64_C(10000000);
    uint64_t epoch=redfin_hid_buttons_epoch();
    keys_consumer=epoch?1:0;
    /* Hardware startup/rail observers precede the GUI consumer. Do not add
     * button transfers to that phase or arm a key before a real listener. */
    if(!keys_attempted&&epoch)keys_initialize();
    if(!keys_attempted||!keys_usable)return;
    unsigned valid=0,pressed=0;uint8_t pon=0,pin=0;
    if(epoch&&power_spmi_ok) {
        if((keys_usable&5)&&!keys_byte(0,0x0810,&pon)) {
            valid|=keys_usable&5;
            if(pon&1)pressed|=1;if(pon&2)pressed|=4;
        }
        if((keys_usable&2)&&!keys_byte(1,0xc410,&pin)) {
            valid|=2;if(!(pin&1))pressed|=2;
        }
        ++keys_samples;
        if(valid!=keys_usable)++keys_errors;
    }
    (void)rf_keys_sample(&keys_state,now,epoch,pressed,valid,keys_emit,NULL);
    keys_armed=keys_state.armed;
    if(keys_samples!=keys_last_report&&(keys_samples<=4||keys_samples-keys_last_report>=3000)) {
        keys_last_report=keys_samples;
        IOLog("REDFIN KEYS STATE: samples=%u errors=%u consumer=%llu usable=%u armed=%u down=%u presses=%u/%u/%u releases=%u/%u/%u cancels=%u\n",
            keys_samples,keys_errors,keys_state.epoch,keys_usable,keys_state.armed,keys_state.down,
            keys_presses[0],keys_presses[1],keys_presses[2],keys_releases[0],keys_releases[1],keys_releases[2],keys_cancels);
    }
}

static void redfin_keys_pause(unsigned milliseconds)
{
    redfin_keys_poll();
    if(!keys_attempted||!keys_usable){IOSleep(milliseconds);return;}
    while(milliseconds) {
        redfin_keys_poll();unsigned step=milliseconds<10?milliseconds:10;
        IOSleep(step);milliseconds-=step;
    }
}
