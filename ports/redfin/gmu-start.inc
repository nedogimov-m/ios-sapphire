/* SPDX-License-Identifier: MIT */
/* Explicit mode4 only. Reset-held preparation and ownership must pass first.
 * Local GMU interrupts are masked; response queues are polled. No IRQ enable,
 * foreign route, GX request, PAS call, GPU submission or power release.
 */
static const uint64_t gm_start_ranges[] = {
    0x03de0000,0x1000,0x0b290000,0x10000,0x0b490000,0x10000,
    0x03d0f000,0x1000,0x80860000,0x20000
};
static const uint32_t gm_start_policy[] = {1,2,0,0x06020100,500,1,0,0};
static struct {
    struct gm_context *context;
    struct rf_gb_config config;
    struct rf_gb_report report;
    vm_offset_t base[RF_GB_UNITS], db, hfi, log;
    struct rf_gm_memory *hfi_memory, *log_memory;
    struct rf_cmddb_resource resources[4];
    unsigned phase, audited, messages, sent, received;
    bool bound, entered;
} gm_start;

static bool gm_start_contract(struct gm_context *context)
{
    if (!gm_property(context,"/redfin-gmu","start-ranges",gm_start_ranges,sizeof(gm_start_ranges)) ||
        !gm_property(context,"/redfin-gmu","start-policy",gm_start_policy,sizeof(gm_start_policy))) return false;
    if (context) { if(gm_start.bound)return false;gm_start.context=context;gm_start.bound=true; }
    return true;
}

/* Keep every original bound args/ADT/parent/CPU/CX/GIC constraint. The
 * separate lifecycle gate changes only the reset/INIT/HFI expectations. */
static bool gm_start_base_valid(void *argument)
{
    struct gm_context *c=argument;
    if(!c || c!=gm_start.context || !gm_start.bound || !gm_memory.ready ||
        !gm_memory.retained || c->smmu_mode!=4 || !c->smmu_ready ||
        !gm_memory.lease.active || gm_memory.lease.poisoned || !gm_valid(c))return false;
    if((gm_scalar_read(c->base[RF_GT_GPUCC]+0x1098)&0x80000001u)!=1 ||
        (gm_scalar_read(c->base[RF_GT_GPUCC]+0x100c)&0x80000001u)!=1 ||
        (gm_scalar_read(c->base[RF_GT_GPUCC]+0x1064)&0x80000001u)!=0x80000000u)return false;
    return true;
}
static int gm_start_guard(void *argument,unsigned phase)
{
    struct gm_context *c=argument;
    if(phase>RF_GB_HFI_LIVE || !gm_start_base_valid(c))return ECANCELED;
    gm_start.phase=phase;
    uint32_t reset=gm_scalar_read(c->base[RF_GT_GMU]+0x14000);
    uint32_t init=gm_scalar_read(c->base[RF_GT_GMU]+0x14070);
    uint32_t hfi=gm_scalar_read(c->base[RF_GT_GMU]+0x14600);
    if(reset!=(phase==RF_GB_HELD?1u:0u))return EAGAIN;
    if(phase==RF_GB_HELD && (init || hfi))return EAGAIN;
    if(phase!=RF_GB_HELD && gm_start.config.core_version>0x20010004u && (init&0xe00u))return EIO;
    if(phase>=RF_GB_FW_LIVE && !redfin_gmu_started(gm_start.config.core_version,init))return EIO;
    if(phase<RF_GB_HFI_WAIT && (hfi&1u))return EAGAIN;
    if(phase==RF_GB_HFI_LIVE && !(hfi&1u))return EIO;
    if(phase!=RF_GB_HELD) {
        if(gm_scalar_read(c->base[RF_GT_GMU]+0x24c14)&0x29u)return EIO;
        if((gm_scalar_read(c->base[RF_GT_GMU]+0x1464c)&7u)!=7u ||
            (gm_scalar_read(c->base[RF_GT_GMU]+0x24c18)&0x29u)!=0x29u)return EAGAIN;
        if(gm_scalar_read(c->cb+0x1058)&RF_GC_FAULT_BITS)return EFAULT;
    }
    return 0;
}

static bool gm_start_read_allowed(unsigned unit,uint32_t at)
{
    if(unit>=RF_GB_UNITS || (at&3u))return false;
    for(unsigned i=0;i<gm_start.report.program_count;++i) {
        const struct rf_gb_store *w=&gm_start.report.program[i];
        if(unit==w->unit && at==w->at)return true;
    }
    if(unit==RF_GB_RSC)return at==0x10 || at==0x404 || at==0xd18 || at==0xfb8 || at==0xd14 || at==0xfb4;
    if(unit==RF_GB_GBIF)return at==0x114 || at==0x118;
    if(unit!=RF_GB_GMU)return false;
    switch(at) {
    case 0x14000:case 0x14070:case 0x14600:case 0x14604:case 0x14648:case 0x24c14:
    case 0x143a0:case 0x24c1c:case 0x24c20:case 0x24c4c:case 0x14404:case 0xafdc:
        return true;
    default:return at>=0xafe0 && at<=0xaff0;
    }
}
static int gm_start_read(void *argument,unsigned unit,uint32_t at,uint32_t *value)
{
    if(!value || !gm_start_base_valid(argument) || !gm_start_read_allowed(unit,at) ||
        !gm_start.base[unit])return EPERM;
    *value=gm_scalar_read(gm_start.base[unit]+at);return 0;
}
static int gm_start_write(void *argument,unsigned unit,uint32_t at,uint32_t value)
{
    if(!gm_start_base_valid(argument) || unit>=RF_GB_UNITS || !gm_start.base[unit])return ECANCELED;
    const struct rf_gb_report *s=&gm_start.report;
    bool allowed=s->last_unit==unit && s->last_offset==at && s->wanted==value;
    if(!allowed)return EPERM;
    allowed=false;
    for(unsigned i=0;i<s->program_count;++i) {
        const struct rf_gb_store *w=&s->program[i];
        if(w->unit==unit && w->at==at && w->value==value)allowed=true;
    }
    if(unit==RF_GB_GMU) {
        if(at==0x14000 && value==0 && s->released && s->phase==RF_GB_FW_WAIT)allowed=true;
        if(at==0x14618 && value==1 && s->firmware && s->phase==RF_GB_HFI_WAIT)allowed=true;
        if(at==0x24c1c && (value==0 || value==2) && s->phase==RF_GB_HELD)allowed=true;
    }
    if(!allowed)return EPERM;
    if(unit!=RF_GB_GMU || (at!=0x14000 && at!=0x14618))
        if(gm_start_guard(argument,s->phase))return ECANCELED;
    printf("REDFIN GMU START WRITE: step=%u unit=%u offset=%#x value=%#x\n",s->stores,unit,at,value);
    if(!gm_start_base_valid(argument))return ECANCELED;
    gm_memory_store(gm_start.base[unit]+at,value);return 0;
}

/* Read-only complete SMMU audit without recursively taking the reset-held
 * source proof at every word. It still guards each MMIO access. */
static bool gm_start_sample_valid(void *argument)
{ return gm_start_guard(argument,gm_start.phase)==0; }
static int gm_start_global(void *argument,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || !rf_gs_read_allowed(at,&gm_memory.lease.expected) || !gm_start_sample_valid(c))return EPERM;
    *value=gm_scalar_read(c->smmu+at);return 0;
}
static int gm_start_bank(void *argument,unsigned bank,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || !rf_gc_allowed(bank,at) || !gm_start_sample_valid(c))return EPERM;
    *value=gm_scalar_read(c->cb+0x1000*bank+at);return 0;
}
static int gm_start_audit(void *argument,unsigned phase)
{
    struct gm_context *c=argument;
    int error=gm_start_guard(c,phase);
    if(error)return error;
    struct rf_gt_report clock={0};
    const struct rf_gt_ops source={.context=c,.valid=gm_valid,.read=gm_read};
    error=rf_gt_source_live(&source,&clock,true);if(error)return error;
    for(unsigned i=0;i<sizeof(gm_smmu_clocks)/sizeof(gm_smmu_clocks[0]);++i) {
        const uint32_t *w=gm_smmu_clocks[i];
        if((gm_scalar_read(c->base[w[0]]+w[1])&w[2])!=w[3])return EAGAIN;
    }
    const struct rf_gs_ops go={c,gm_start_sample_valid,gm_start_global};
    const struct rf_gc_ops bo={c,gm_start_sample_valid,gm_start_bank};
    error=rf_gs_snapshot_run(&go,gm_chip,&gm_memory.lease.fresh);
    if(!error)error=rf_gc_snapshot_run(&bo,&gm_memory.lease.fresh,&gm_memory.lease.fresh_banks);
    if(!error && !rf_gmm_equal(&gm_memory.lease))error=EAGAIN;
    if(!error && (gm_scalar_read(c->cb+0x1028) || gm_scalar_read(c->cb+0x102c)))error=EAGAIN;
    if(error){gm_memory.lease.poisoned=1;gm_memory.lease.active=0;return error;}
    ++gm_start.audited;
    printf("REDFIN GMU START AUDIT: phase=%u complete=%u FSR=%#x\n",phase,gm_start.audited,
        gm_memory.lease.fresh_banks.words[1][8]);
    return gm_start_guard(c,phase);
}
static int gm_start_delay(void *argument,unsigned us)
{
    if(us!=100 || !gm_start_base_valid(argument))return ECANCELED;
    delay(100);return 0;
}

static uint32_t gm_start_hfi_word(uint32_t at)
{ return gm_scalar_read(gm_start.hfi+at); }
static void gm_start_hfi_store(uint32_t at,uint32_t value)
{ gm_memory_store(gm_start.hfi+at,value); }
static int gm_start_hfi_shape(void *argument)
{
    int error=gm_start_guard(argument,RF_GB_HFI_LIVE);if(error)return error;
    static const uint32_t header[]={0,54,6,12,4,4};
    static const uint32_t priority[]={10,10,40,20};
    for(unsigned i=1;i<6;++i)if(gm_start_hfi_word(4*i)!=header[i])return EPROTO;
    for(unsigned q=0;q<4;++q) {
        uint32_t at=24+48*q;
        if(gm_start_hfi_word(at)!=(q==3?0u:1u) ||
            gm_start_hfi_word(at+4)!=gm_start.config.hfi_address+0xe0+4096*q ||
            gm_start_hfi_word(at+8)!=(q|(priority[q]<<8)) ||
            gm_start_hfi_word(at+12)!=1024 || gm_start_hfi_word(at+16))return EPROTO;
        uint32_t read=gm_start_hfi_word(at+40),write=gm_start_hfi_word(at+44);
        if(read>=1024 || write>=1024 || ((read|write)&3u))return EPROTO;
    }
    return gm_start_guard(argument,RF_GB_HFI_LIVE);
}
static int gm_start_receive(void *argument,unsigned q,uint32_t request,uint32_t *version)
{
    if(q!=1 && q!=2)return EINVAL;
    int error=gm_start_hfi_shape(argument);if(error)return error;
    uint32_t base=24+48*q,read=gm_start_hfi_word(base+40),write=gm_start_hfi_word(base+44);
    if(read==write)return ENOENT;
    uint32_t at=0xe0+4096*q;
    uint32_t first=gm_start_hfi_word(at+4*read),count=(first>>8)&255u;
    uint32_t available=(write+1024-read)%1024,padded=(count+3u)&~3u;
    if(!count || padded>available || padded>=1024 || gm_start.messages>=16)return EPROTO;
    uint32_t words[255];
    for(unsigned i=0;i<count;++i)words[i]=gm_start_hfi_word(at+4*((read+i)%1024));
    ++gm_start.messages;
    printf("REDFIN GMU HFI RECEIVE: queue=%u count=%u header=%#x word1=%#x word2=%#x word3=%#x\n",
        q,count,words[0],count>1?words[1]:0,count>2?words[2]:0,count>3?words[3]:0);
    if((words[0]&255u)==100u)return EIO;
    error=gm_start_guard(argument,RF_GB_HFI_LIVE);if(error)return error;
    gm_start_hfi_store(base+40,(read+padded)%1024);
    if(q==1 && ((words[0]>>16)&15u)==1) {
        error=rf_gb_version_ack(words,count,request,0x20000000,version);
        if(!error)++gm_start.received;
        return error;
    }
    return ENOMSG;
}
static int gm_start_exchange(void *argument,uint32_t *version)
{
    int error=gm_start_hfi_shape(argument);if(error)return error;
    if(gm_start.sent || gm_start_hfi_word(64) || gm_start_hfi_word(68))return EBUSY;
    for(unsigned i=0;i<16;++i) {
        bool pending=false;
        for(unsigned q=1;q<=2;++q) {
            uint32_t unused=0;
            error=gm_start_receive(argument,q,UINT32_MAX,&unused);
            if(error==ENOMSG){pending=true;continue;}
            if(error!=ENOENT)return error;
        }
        if(!pending)break;
        if(i==15)return EPROTO;
    }
    uint32_t request;
    error=redfin_gmu_hfi_command_header(1,2,1,&request);if(error)return error;
    uint32_t command[]={request,0x20000000,0xfafafafa,0xfafafafa};
    for(unsigned i=0;i<4;++i) {
        error=gm_start_guard(argument,RF_GB_HFI_LIVE);if(error)return error;
        gm_start_hfi_store(0xe0+4*i,command[i]);
    }
    error=gm_start_guard(argument,RF_GB_HFI_LIVE);if(error)return error;
    gm_start_hfi_store(68,4);
    ++gm_start.sent;
    error=gm_start_guard(argument,RF_GB_HFI_LIVE);if(error)return error;
    gm_memory_store(gm_start.base[RF_GB_GMU]+0x14650,1);
    printf("REDFIN GMU HFI SENT: request=%#x supported=0x20000000 sequence=1\n",request);
    uint64_t first=gm_time_ns(argument);
    for(unsigned i=0;i<5000 && gm_time_ns(argument)-first<RF_GB_WAIT_NS;++i) {
        error=gm_start_receive(argument,1,request,version);
        if(!error) {
            if(gm_start_hfi_word(64)!=4)return EPROTO;
            error=gm_start_guard(argument,RF_GB_HFI_LIVE);if(error)return error;
            gm_memory_store(gm_start.base[RF_GB_GMU]+0x14644,1);
            return 0;
        }
        if(error!=ENOENT && error!=ENOMSG)return error;
        error=gm_start_receive(argument,2,request,version);
        if(error!=ENOENT && error!=ENOMSG)return error;
        error=gm_start_delay(argument,100);if(error)return error;
    }
    return ETIMEDOUT;
}

static int gm_start_resources(struct gm_context *context)
{
    static const uint8_t names[4][8]={"xo.lvl","cx.lvl","mx.lvl","vrm.soc"};
    for(unsigned i=0;i<4;++i) {
        if(!gm_start_base_valid(context))return ECANCELED;
        enum rf_cmddb_status e=rf_cmddb_lookup((volatile const uint8_t *)gm_start.db,
            RF_CMDDB_BYTES,names[i],i==3?RF_CMDDB_VRM:RF_CMDDB_ARC,&gm_start.resources[i]);
        if(i==3 && e==RF_CMDDB_MISSING)continue;
        if(e!=RF_CMDDB_OK)return ENXIO;
    }
    gm_start.config=(struct rf_gb_config){
        .chip=gm_chip,.core_version=gm_memory.firmware.versions[0],
        .hfi_version=gm_memory.firmware.versions[4],.hfi_address=gm_memory.firmware.hfi_address,
        .log_address=gm_memory.firmware.log_address,.xo=gm_start.resources[0].address,
        .cx=gm_start.resources[1].address,.mx=gm_start.resources[2].address,.vrm=gm_start.resources[3].address
    };
    printf("REDFIN GMU START RESOURCES: xo=%#x cx=%#x mx=%#x vrm=%#x core=%#x hfi=%#x\n",
        gm_start.config.xo,gm_start.config.cx,gm_start.config.mx,gm_start.config.vrm,
        gm_start.config.core_version,gm_start.config.hfi_version);
    return rf_gb_config_valid(&gm_start.config)?0:ENOTSUP;
}
static int gm_start_memory(struct gm_context *context)
{
    for(unsigned i=0;i<gm_memory.count;++i) {
        struct rf_gm_memory *memory=&gm_memory.data[i];
        if(memory->gmu_address==gm_start.config.hfi_address)gm_start.hfi_memory=memory;
        if(memory->gmu_address==gm_start.config.log_address)gm_start.log_memory=memory;
    }
    struct rf_gm_memory *objects[]={gm_start.hfi_memory,gm_start.log_memory};
    for(unsigned i=0;i<2;++i) {
        struct rf_gm_memory *m=objects[i];
        if(!m || !gm_memory_owns(context,m,RF_GM_PT_DATA))return EACCES;
        for(uintptr_t at=(uintptr_t)m->host;at<(uintptr_t)m->host+m->owned_bytes;at+=64)
            __asm__ volatile("dc civac, %0"::"r"(at):"memory");
        __asm__ volatile("dsb osh":::"memory");
        vm_offset_t mapped=ml_io_map_wcomb(m->physical,m->owned_bytes);
        if(!mapped)return ENOMEM;
        if(i)gm_start.log=mapped;else gm_start.hfi=mapped;
    }
    /* Only the uncached view is used after CM3 can write. */
    return 0;
}
static void gm_start_diagnostic(struct gm_context *context)
{
    if(!gm_start_base_valid(context))return;
    const uint32_t offsets[]={0x14000,0x14070,0x14600,0x14604,0x14648,0x24c14,0x24c4c,0xafdc,0x14404};
    for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);++i)
        printf("REDFIN GMU START STATE: offset=%#x value=%#x\n",offsets[i],
            gm_scalar_read(gm_start.base[RF_GB_GMU]+offsets[i]));
    printf("REDFIN GMU START FAULT: FSR=%#x FAR=%#x/%#x FSYNR=%#x GFSR=%#x\n",
        gm_scalar_read(context->cb+0x1058),gm_scalar_read(context->cb+0x1060),
        gm_scalar_read(context->cb+0x1064),gm_scalar_read(context->cb+0x1068),
        gm_scalar_read(context->smmu+0x48));
    if(gm_start.hfi)
        for(unsigned q=0;q<4;++q)printf("REDFIN GMU START QUEUE: q=%u status=%#x read=%u write=%u\n",
            q,gm_start_hfi_word(24+48*q),gm_start_hfi_word(64+48*q),gm_start_hfi_word(68+48*q));
    if(gm_start.log)
        for(unsigned i=0;i<16;i+=4)printf("REDFIN GMU START LOG: at=%#x words=%#x/%#x/%#x/%#x\n",4*i,
            gm_scalar_read(gm_start.log+4*i),gm_scalar_read(gm_start.log+4*i+4),
            gm_scalar_read(gm_start.log+4*i+8),gm_scalar_read(gm_start.log+4*i+12));
}
static int gm_start_run(struct gm_context *context)
{
    int error=EPERM;
    if(!gm_start.bound || gm_start.entered || context!=gm_start.context ||
        !gm_memory.ready || gm_memory.loaded!=gm_memory.firmware.payload_count ||
        gm_memory.verified!=gm_memory.firmware.payload_count)return error;
    gm_start.entered=true;gm_start.base[RF_GB_GMU]=context->base[RF_GT_GMU];
    gm_start.base[RF_GB_RSC]=ml_io_map(0x03de0000,0x4000);
    gm_start.base[RF_GB_PDC]=ml_io_map(0x0b290000,0x10000);
    gm_start.base[RF_GB_SEQ]=ml_io_map(0x0b490000,0x10000);
    gm_start.base[RF_GB_GBIF]=ml_io_map(0x03d0f000,0x1000);
    gm_start.db=ml_io_map_wcomb(0x80860000,RF_CMDDB_BYTES);
    if(!gm_start_base_valid(context))return ECANCELED;
    for(unsigned i=0;i<RF_GB_UNITS;++i)if(!gm_start.base[i])return ENOMEM;
    if(!gm_start.db)return ENOMEM;
    uint64_t started=gm_time_ns(context);
    error=gm_start_resources(context);if(error)goto done;
    error=gm_start_memory(context);if(error)goto done;
    const struct rf_gb_ops ops={context,gm_start_guard,gm_start_read,gm_start_write,
        gm_start_audit,gm_start_exchange,gm_start_delay,gm_time_ns};
    printf("REDFIN GMU START: native A620 cold PDC/RSC/CM3/HFI begins; no GX request\n");
    error=rf_gb_run(&gm_start.report,&gm_start.config,&ops);
done:
    gm_start_diagnostic(context);
    printf("REDFIN GMU START RESULT: result=%d stage=%u phase=%u stores=%u polls=%u released=%u firmware=%u hfi=%u sent=%u received=%u ack=%u version=%#x elapsed-ns=%llu\n",
        error,gm_start.report.stage,gm_start.report.phase,gm_start.report.stores,gm_start.report.polls,
        gm_start.report.released,gm_start.report.firmware,gm_start.report.hfi,gm_start.sent,gm_start.received,
        gm_start.report.ack,gm_start.report.version,(unsigned long long)(gm_time_ns(context)-started));
    printf("REDFIN GMU START LAST: unit=%u offset=%#x wanted=%#x observed=%#x audits=%u; allocations retained until reset\n",
        gm_start.report.last_unit,gm_start.report.last_offset,gm_start.report.wanted,
        gm_start.report.observed,gm_start.audited);
    printf("REDFIN GMU START CACHED SMMU: error=%d stable=%u FSR=%#x FAR=%#x/%#x FSYNR=%#x GFSR=%#x poisoned=%u\n",
        gm_memory.lease.fresh_banks.error,gm_memory.lease.fresh_banks.stable,
        gm_memory.lease.fresh_banks.words[1][8],gm_memory.lease.fresh_banks.words[1][9],
        gm_memory.lease.fresh_banks.words[1][10],gm_memory.lease.fresh_banks.words[1][11],
        gm_memory.lease.fresh.fault,gm_memory.lease.poisoned);
    return error;
}
