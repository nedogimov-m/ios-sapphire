/* SPDX-License-Identifier: MIT */
/* Native CoreBrightness and display power requests use the source-bound
 * Redfin DSI FIFO owner. Pixel/GPU objects and their fences are untouched. */
#include "RedfinPanelControls.h"

struct redfin_display_controls {
    IOLock *state_lock,*io_lock;
    thread_call_t work;
    struct redfin_panel_maps maps;
    AppleARMBacklight *backlight;
    uint64_t requested_seq,processed_seq,nits,applied_nits;
    uint32_t desired_level,applied_level;
    bool desired_on,applied_on,level_known,uncertain,queued;
    unsigned commands,errors;
};

static void redfin_control_queue(redfin_display_controls *control)
{
    IOLockLock(control->state_lock);
    bool queue=!control->queued&&!control->uncertain;
    if(queue)control->queued=true;
    IOLockUnlock(control->state_lock);
    if(queue)thread_call_enter(control->work);
}

bool AppleCLCD::startRedfinControls(IOService *provider)
{
    const uint32_t expected[]={1,0x0af00000,0x0ae94000,1080,2340,4,1023,8,500};
    uint32_t actual[sizeof(expected)/sizeof(expected[0])]={};
    if(!fRedfinCopyOnly||!redfin_gui_selected()||fRedfinControls||
        !redfin_fb_data(provider,"redfin,panel-controls",actual,sizeof(actual))||
        memcmp(actual,expected,sizeof(actual)))return false;
    redfin_display_controls *control=(redfin_display_controls *)IOMallocZeroData(sizeof(*control));
    if(!control)return false;
    control->maps.base[RP_CC]=ml_io_map(expected[1],0x4000);
    const uint32_t clocks[]={0x2080,0x2028,0x2038,0x200c};
    bool ready=control->maps.base[RP_CC]!=0;
    for(unsigned i=0;ready&&i<4;++i)
        ready=redfin_panel_clock_on(redfin_panel_read(&control->maps,RP_CC,clocks[i]));
    if(ready) {
        control->maps.base[RP_DSI]=ml_io_map(expected[2],0x4000);
        ready=control->maps.base[RP_DSI]!=0;
    }
    if(ready) {
        uint32_t version=redfin_panel_read(&control->maps,RP_DSI,0);
        uint32_t state=redfin_panel_read(&control->maps,RP_DSI,4);
        ready=(version&0xffff0000u)==0x20040000u&&(state&1)&&!(state&2)&&
            (redfin_panel_read(&control->maps,RP_DSI,0x84)&7)==4&&
            !redfin_panel_read(&control->maps,RP_DSI,0x15c);
    }
    if(ready) {
        control->state_lock=IOLockAlloc();control->io_lock=IOLockAlloc();
        control->work=thread_call_allocate(&AppleCLCD::redfinControlsWork,this);
        ready=control->state_lock&&control->io_lock&&control->work;
    }
    AppleARMBacklight *backlight=ready?OSTypeAlloc(AppleARMBacklight):NULL;
    if(backlight) {
        ready=backlight->init();
        if(ready) {
            backlight->fFB=this;
            backlight->setProperty("backlight-control",true);
            backlight->setProperty("brightness-nits",200ULL,32);
            backlight->setProperty("max-nits",(unsigned long long)RF_PANEL_NORMAL_NITS,32);
            backlight->setProperty("min-nits",2ULL,32);
            backlight->setProperty("RedfinDisplayControlABI",1ULL,32);
            ready=backlight->attach(this);
        }
    } else ready=false;
    if(!ready) {
        OSSafeReleaseNULL(backlight);
        if(control->work)thread_call_free(control->work);
        if(control->state_lock)IOLockFree(control->state_lock);
        if(control->io_lock)IOLockFree(control->io_lock);
        IOFreeData(control,sizeof(*control));
        IOLog("REDFIN DISPLAY CONTROL: source/hardware/resources refused; no packet submitted\n");
        return false;
    }
    control->backlight=backlight;
    control->desired_on=control->applied_on=true;control->nits=UINT64_C(200)<<16;
    (void)rf_panel_nits_to_dbv(control->nits,&control->desired_level);control->requested_seq=1;
    fRedfinControls=control;
    /* This built-in platform service and its existing presenter threads live
     * until reset. Keep the callback's exact owner alive for that lifetime. */
    retain();
    setProperty("RedfinDisplayControlABI",1ULL,32);
    setProperty("IOMFBBrightnessLevel",control->nits,32);
    backlight->registerService();redfin_control_queue(control);
    IOLog("REDFIN DISPLAY CONTROL: AppleARMBacklight registered normal-max-nits=500 DBV=4..1023 DSI2.4 FIFO=1 DMA-memory=0 asynchronous=1\n");
    return true;
}

IOReturn AppleCLCD::redfinSetBrightness(uint64_t nits)
{
    redfin_display_controls *control=fRedfinControls;uint32_t level=0;
    if(!control)return kIOReturnUnsupported;
    if(!rf_panel_nits_to_dbv(nits,&level))return kIOReturnBadArgument;
    IOLockLock(control->state_lock);
    if(control->uncertain){IOLockUnlock(control->state_lock);return kIOReturnNotReady;}
    bool changed=control->nits!=nits||control->desired_level!=level;
    control->nits=nits;control->desired_level=level;
    if(changed)++control->requested_seq;
    IOLockUnlock(control->state_lock);
    setProperty("IOMFBBrightnessLevel",nits,32);
    if(changed)redfin_control_queue(control);
    return kIOReturnSuccess;
}

IOReturn AppleCLCD::redfinBacklightProperties(OSObject *properties)
{
    OSDictionary *values=OSDynamicCast(OSDictionary,properties);
    if(!values)return kIOReturnBadArgument;
    OSNumber *number=OSDynamicCast(OSNumber,values->getObject("brightness-nits"));
    if(!number)return kIOReturnSuccess; /* unchanged native ancillary-key policy */
    uint64_t nits=number->unsigned64BitValue();
    if(nits<0x10000)nits<<=16; /* native plain-nit and16.16 callers */
    IOReturn result=redfinSetBrightness(nits);
    if(result==kIOReturnSuccess)fRedfinControls->backlight->setProperty("brightness-nits",number);
    return result;
}

IOReturn AppleCLCD::redfinSetDisplayPower(bool on)
{
    redfin_display_controls *control=fRedfinControls;if(!control)return kIOReturnUnsupported;
    IOLockLock(control->state_lock);
    if(control->uncertain){IOLockUnlock(control->state_lock);return kIOReturnNotReady;}
    bool changed=control->desired_on!=on;control->desired_on=on;
    if(changed)++control->requested_seq;
    IOLockUnlock(control->state_lock);
    if(changed)redfin_control_queue(control);
    return kIOReturnSuccess;
}

void AppleCLCD::redfinControlsWork(thread_call_param_t parameter,thread_call_param_t unused __unused)
{
    AppleCLCD *fb=(AppleCLCD *)parameter;redfin_display_controls *control=fb->fRedfinControls;
    if(!control)return;
    /* Requests only take state_lock. One running worker and at most one
     * coalesced successor serialize every complete FIFO transaction here. */
    IOLockLock(control->io_lock);IOLockLock(control->state_lock);
    control->queued=false;
    bool on=control->desired_on,was_on=control->applied_on,uncertain=control->uncertain;
    bool power_changed=on!=was_on;
    uint32_t level=control->desired_level,was_level=control->applied_level;
    bool level_known=control->level_known;uint64_t sequence=control->requested_seq,nits=control->nits;
    IOLockUnlock(control->state_lock);
    struct redfin_panel_io io={&control->maps,redfin_panel_read,redfin_panel_write,
        redfin_panel_delay,redfin_panel_time};
    bool ok=!uncertain;struct rf_panel_control_result transaction={};
    if(ok&&power_changed) {
        ok=rf_panel_control(&io,false,on?1:0,&transaction);
        if(ok){was_on=on;++control->commands;}
        uncertain|=transaction.uncertain;
    }
    if(ok&&on&&(!level_known||level!=was_level||power_changed)) {
        transaction={};ok=rf_panel_control(&io,true,level,&transaction);
        if(ok){was_level=level;level_known=true;++control->commands;}
        uncertain|=transaction.uncertain;
    }
    IOLockLock(control->state_lock);
    control->applied_on=was_on;control->applied_level=was_level;control->level_known=level_known;
    control->uncertain|=uncertain;
    if(ok&&on)control->applied_nits=nits;
    if(ok)control->processed_seq=sequence;else ++control->errors;
    uint64_t processed=control->processed_seq,applied_nits=control->applied_nits;
    IOLockUnlock(control->state_lock);
    fb->setProperty("RedfinDisplayOn",was_on);
    fb->setProperty("RedfinControlUncertain",uncertain);
    if(level_known)fb->setProperty("RedfinAppliedDBV",(unsigned long long)was_level,32);
    fb->setProperty("RedfinAppliedNits",applied_nits,64);
    /* Publish the completed sequence last, after its actual level/state. */
    fb->setProperty("RedfinControlSequence",processed,64);
    if(sequence<=8||!ok||power_changed)
        IOLog("REDFIN DISPLAY CONTROL DONE: sequence=%llu processed=%llu requested-on=%u applied-on=%u requested-DBV=%u applied-DBV=%u known=%u success=%u uncertain=%u commands=%u errors=%u\n",
            sequence,processed,on,was_on,level,was_level,level_known,ok,uncertain,control->commands,control->errors);
    IOLockUnlock(control->io_lock);
}
