/* SPDX-License-Identifier: MIT */
/* One complete mode5 run. Every allocation, vote and partially started engine
 * is held until the already armed platform reset; no unsafe rollback/retry. */
#include "redfin_gpu_mapping.h"
#include "redfin_gpu_power.h"
static const uint64_t gx_ranges[]={0x03d00000,0x40000,0x18220000,0x10000};
static struct {
    struct gm_context *context;
    uint8_t sqe[RF_A6_SQE_BYTES],mdt[RF_A6_MDT_BYTES],zap[RF_A6_ZAP_BYTES],hash[3][32];
    struct rf_a6_zap zap_plan;
    struct rf_gm_memory data[3],pool,secure;
    struct rf_gm_pt_plan tables;
    struct rf_a6_mapping mapping;
    struct rf_a6_perf performance;
    struct rf_a6_bw bandwidth;
    struct rf_a6_bcm bcm[9]; /* SH0,MC0,ACV,CN0,CE0,SN6,SN0,SH4,SN10. */
    struct rf_cmddb_resource gfx;
    vm_offset_t gpu,rsc,scratch;
    struct rf_gp_slot inherited[8];
    uint32_t rsc_id,rsc_config,rsc_irq,commands,proxy[9],proxy_held,cfg_held;
    uint32_t rptr,wptr,status,fault,interrupt,protect,values[4],wanted[4];
    uint64_t started,allocated;
    unsigned allocations,stage,registers,submissions,pas_phase,pas_completed;
    bool bound,entered,poisoned,sqe_started;
} gx;

static bool gx_contract(struct gm_context *c)
{
    if(!gm_property(c,"/redfin-gpu-command","reg",gx_ranges,sizeof(gx_ranges)) ||
        !gm_property(c,"/redfin-gpu-command","policy",rf_a6_policy,sizeof(rf_a6_policy)))return false;
    static const char *const names[]={"sqe","zap-mdt","zap-segment"};
    static const char *const hashes[]={"sqe-sha256","zap-mdt-sha256","zap-segment-sha256"};
    const unsigned sizes[]={sizeof(gx.sqe),sizeof(gx.mdt),sizeof(gx.zap)};
    uint8_t *copies[]={gx.sqe,gx.mdt,gx.zap};
    DTEntry entry;const void *files[3];
    if(SecureDTLookupEntry(NULL,"/redfin-gpu-command",&entry)!=kSuccess || (c && gx.bound))return false;
    for(unsigned i=0;i<3;++i) {
        const void *digest;unsigned bytes=0,hash_bytes=0;uint8_t actual[32];
        if(SecureDTGetProperty(entry,names[i],&files[i],&bytes)!=kSuccess || !files[i] || bytes!=sizes[i] ||
            SecureDTGetProperty(entry,hashes[i],&digest,&hash_bytes)!=kSuccess || !digest || hash_bytes!=32 ||
            redfin_mpss_kernel_sha256(NULL,files[i],bytes,actual) || memcmp(actual,digest,32))return false;
        if(c) {
            memcpy(copies[i],files[i],bytes);memcpy(gx.hash[i],digest,32);
            if(!gm_property(c,"/redfin-gpu-command",names[i],copies[i],bytes) ||
                !gm_property(c,"/redfin-gpu-command",hashes[i],gx.hash[i],32))return false;
        }
    }
    struct rf_a6_zap plan;
    if(rf_a6_zap_plan(files[1],sizes[1],sizes[2],&plan))return false;
    if(c){gx.zap_plan=plan;gx.context=c;gx.bound=true;}
    return true;
}

static int gx_check(void *argument)
{
    struct gm_context *c=argument;
    if(!c || c!=gx.context || !gx.bound || !gx.entered || gx.poisoned || c->smmu_mode!=5 ||
        !gm_start.report.ack || gm_start.report.error || gm_start.report.stage!=6 ||
        gm_start_guard(c,RF_GB_HFI_LIVE))return ECANCELED;
    if(gm_time_ns(c)-gx.started>UINT64_C(25000000000))return ETIMEDOUT;
    if((gm_scalar_read(c->gic+0x128)|gm_scalar_read(c->gic+0x328))&(1u<<12))return EBUSY;
    if(gm_scalar_read(c->smmu+0x48) || (gm_scalar_read(c->cb+0x58)&RF_GC_FAULT_BITS))return EFAULT;
    if(c->gx_granted && ((gm_scalar_read(c->base[RF_GT_GMU]+0x14340)&0xc0u) ||
        (gm_scalar_read(c->base[RF_GT_GPUCC]+0x100c)&0x80000001u)!=0x80000000u))return EIO;
    return 0;
}
static bool gx_valid(void *argument){return gx_check(argument)==0;}
static int gx_allocate(struct rf_gm_memory *out,uint32_t address,uint32_t bytes,unsigned token,bool secure)
{
    if(gx_check(gx.context))return ECANCELED;
    vm_offset_t host=0;vm_size_t size=(bytes+PAGE_MASK)&~PAGE_MASK;
    if(!size || gx.allocated+size>0x180000)return EFBIG;
    vm_size_t alignment=secure?RF_A6_ZAP_ALLOC-1u:PAGE_MASK;
    /* XNU's fourth argument aligns the virtual mapping. Physical page
     * alignment is independent and belongs in the ppnum mask. */
    ppnum_t physical_alignment=secure?(ppnum_t)(alignment>>PAGE_SHIFT):0;
    if(kmem_alloc_contig(kernel_map,&host,size,alignment,
        (ppnum_t)((RF_GM_PT_RAM_BASE+RF_GM_PT_RAM_BYTES-1)>>PAGE_SHIFT),physical_alignment,
        KMA_KOBJECT|KMA_ZERO|KMA_DATA,VM_KERN_MEMORY_IOKIT)!=KERN_SUCCESS)return ENOMEM;
    ++gx.allocations;gx.allocated+=size;
    *out=(struct rf_gm_memory){(void *)host,kvtophys(host),size,token,address};
    printf("REDFIN GPU ALLOCATION: token=%u bytes=%llu PA=%#llx physical-mask=%#llx secure=%u\n",
        token,(unsigned long long)size,(unsigned long long)out->physical,
        (unsigned long long)physical_alignment,secure);
    if(!rf_gm_memory_valid(out) || (secure && (out->physical&(RF_A6_ZAP_ALLOC-1u))))return ERANGE;
    return 0;
}
static bool gx_owns(void *argument,const struct rf_gm_memory *m,unsigned use)
{
    if(gx_check(argument) || !m || !rf_gm_memory_valid(m))return false;
    bool owned=use==RF_GM_PT_TABLE_POOL && gm_memory_same(m,&gx.pool);
    if(use==RF_GM_PT_DATA)for(unsigned i=0;i<3;++i)if(gm_memory_same(m,&gx.data[i]))owned=true;
    if(!owned)return false;
    for(uint64_t i=0;i<m->owned_bytes;i+=4096)
        if(kvtophys((vm_offset_t)m->host+i)!=m->physical+i)return false;
    return true;
}
static int gx_global(void *argument,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || !rf_gs_read_allowed(at,&gm_memory.lease.expected) || gx_check(c))return EPERM;
    *value=gm_scalar_read(c->smmu+at);return 0;
}
static int gx_bank(void *argument,unsigned bank,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || !rf_gc_allowed(bank,at) || gx_check(c))return EPERM;
    *value=gm_scalar_read(c->cb+0x1000*bank+at);return 0;
}
static int gx_sample(void *argument,struct rf_gs_snapshot *global,struct rf_gc_snapshot *banks)
{
    if(!gm_payloads_valid(argument))return EAGAIN;
    const struct rf_gs_ops go={argument,gx_valid,gx_global};
    const struct rf_gc_ops bo={argument,gx_valid,gx_bank};
    int error=rf_gs_snapshot_run(&go,gm_chip,global);
    if(!error)error=rf_gc_snapshot_run(&bo,global,banks);
    return error?error:gm_payloads_valid(argument)?0:EAGAIN;
}
static int gx_map_read(void *argument,unsigned block,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || block>1 || gx_check(c))return ECANCELED;
    if(!block)return gx_global(c,at,value);
    if(!rf_gc_allowed(0,at) && at!=0x28 && at!=0x2c && at!=0x7f4)return EPERM;
    *value=gm_scalar_read(c->cb+at);return 0;
}
static int gx_map_write(void *argument,unsigned block,uint32_t at,uint32_t value)
{
    struct gm_context *c=argument;unsigned wanted_block;uint32_t wanted_at,wanted;
    if(gx_check(c) || rf_a6_map_step(&gx.mapping,&gx.tables,gx.mapping.step,
        &wanted_block,&wanted_at,&wanted) || block!=wanted_block || at!=wanted_at || value!=wanted)return EPERM;
    printf("REDFIN GPU MAP WRITE: step=%u block=%u offset=%#x value=%#x\n",
        gx.mapping.step,block,at,value);
    gm_memory_store((block?c->cb:c->smmu)+at,value);return 0;
}
static int gx_publish(void *argument,const struct rf_gm_pt_plan *p)
{
    if(p!=&gx.tables || !gx_owns(argument,&gx.pool,RF_GM_PT_TABLE_POOL))return EPERM;
    for(unsigned i=0;i<3;++i) {
        if(!gx_owns(argument,&gx.data[i],RF_GM_PT_DATA))return EPERM;
        gm_memory_clean(&gx.data[i]);
    }
    gm_memory_clean(&gx.pool);return gx_check(argument);
}
static int gx_delay(void *argument,unsigned us)
{
    int error=gx_check(argument);if(error)return error;
    if(us!=1 && us!=100)return EINVAL;delay(us);return 0;
}
static const struct rf_gmm_ops gx_mapping_ops={NULL,gx_check,gx_sample,gx_map_read,
    gx_map_write,gx_publish,gx_delay};
static int gx_audit(struct gm_context *c)
{
    int error=gx_check(c);if(error)return error;
    /* Power GX before binding its user stream, as preferred steps17/18.
     * Before CB0 installation starts the complete GMU lease still owns
     * every SMMU word, including the untouched disabled GPU context. */
    if(!gx.mapping.state.attempted)return gm_start_audit(c,RF_GB_HFI_LIVE);
    struct rf_gt_report clock={0};const struct rf_gt_ops source={.context=c,.valid=gm_valid,.read=gm_read};
    error=rf_gt_source_live_power(&source,&clock,true,c->gx_requested);if(error)return error;
    for(unsigned i=0;i<sizeof(gm_smmu_clocks)/sizeof(gm_smmu_clocks[0]);++i) {
        const uint32_t *w=gm_smmu_clocks[i];
        if((gm_scalar_read(c->base[w[0]]+w[1])&w[2])!=w[3])return EAGAIN;
    }
    struct rf_gmm_ops o=gx_mapping_ops;o.context=c;
    error=rf_a6_map_verify(&gx.mapping,&o);
    if(!error)for(unsigned bank=0;bank<2;++bank)
        if(gm_scalar_read(c->cb+bank*4096+0x28) || gm_scalar_read(c->cb+bank*4096+0x2c))error=EAGAIN;
    if(error)gx.poisoned=true;return error;
}

/* The parent already owns and has returned DRV2 ACTIVE0 to idle. Preserve
 * every other TCS and its inherited floors, exactly as the native PIL owner.
 * Transactions change only ACTIVE0 and its own completion W1C bit. */
static int gx_rsc_snapshot(struct gm_context *c,bool initial,bool inflight)
{
    int error=gx_check(c);if(error)return error;
    uint32_t en=gm_scalar_read(c->gic+0x104),active=gm_scalar_read(c->gic+0x304);
    if((en|active)&(1u<<5))return EBUSY;
    if(gm_scalar_read(gx.rsc)!=gx.rsc_id || gm_scalar_read(gx.rsc+0xc)!=gx.rsc_config ||
        gm_scalar_read(gx.rsc+0xd00)!=gx.rsc_irq)return EAGAIN;
    uint32_t irq=gm_scalar_read(gx.rsc+0xd04);
    if(irq==UINT32_MAX || (irq&~1u) || (!inflight && irq))return EBUSY;
    for(unsigned t=0;t<8;++t) {
        uint32_t base=RF_GP_TCS(t);struct rf_gp_slot now={0};
        now.idle=gm_scalar_read(gx.rsc+base+0x18);now.control=gm_scalar_read(gx.rsc+base+0x14);
        now.enabled=gm_scalar_read(gx.rsc+base+0x1c);now.wait=gm_scalar_read(gx.rsc+base+0x10);
        if((t || !inflight) && (!now.idle || now.idle==UINT32_MAX ||
            ((now.enabled|now.wait)&~((1u<<gx.commands)-1u)) ||
            (t<2 && (now.control || now.enabled || now.wait))))return EBUSY;
        for(unsigned i=0;i<gx.commands;++i)if(now.enabled&(1u<<i)) {
            uint32_t at=base+0x30+20*i;
            now.command[i].message=gm_scalar_read(gx.rsc+at);
            now.command[i].address=gm_scalar_read(gx.rsc+at+4);
            now.command[i].data=gm_scalar_read(gx.rsc+at+8);
        }
        if(t || !inflight) {
            if(initial)gx.inherited[t]=now;
            else if(memcmp(&now,&gx.inherited[t],sizeof(now)))return EAGAIN;
        }
    }
    return gx_check(c);
}
static int gx_rsc_store(struct gm_context *c,uint32_t at,uint32_t value,bool readback)
{
    int error=gx_check(c);if(error)return error;
    switch(at) {
    case 0xd30:case 0xd34:case 0xd38:case 0xd10:case 0xd1c:case 0xd14:case 0xd08:break;
    default:return EPERM;
    }
    gm_memory_store(gx.rsc+at,value);
    if(readback && gm_scalar_read(gx.rsc+at)!=value)return EIO;return 0;
}
static int gx_proxy_vote(struct gm_context *c,unsigned index)
{
    const unsigned ids[]={4,5,6,0,1,2,7,8,3};
    if(index>=9)return EINVAL;
    int error=gx_rsc_snapshot(c,false,false);if(error)return error;
    uint32_t data=gx.proxy[index],address=gx.bcm[ids[index]].address;
    const uint32_t at[]={0xd30,0xd34,0xd38,0xd10,0xd1c,0xd14,0xd14};
    const uint32_t values[]={0x10108,address,data,1,1,0,1u<<16};
    for(unsigned i=0;i<7;++i) {
        error=gx_rsc_snapshot(c,false,true);if(error)return error;
        error=gx_rsc_store(c,at[i],values[i],true);if(error)return error;
    }
    error=gx_rsc_store(c,0xd14,0x1010000,false);if(error)return error;
    uint64_t first=gm_time_ns(c);bool complete=false;
    for(unsigned i=0;i<1000 && gm_time_ns(c)-first<UINT64_C(100000000);++i) {
        error=gx_rsc_snapshot(c,false,true);if(error)return error;
        uint32_t irq=gm_scalar_read(gx.rsc+0xd04),idle=gm_scalar_read(gx.rsc+0xd18);
        uint32_t status=gm_scalar_read(gx.rsc+0xd3c);
        if((irq&1u) && idle && (status&0x10100u)==0x10100u){complete=true;break;}
        delay(100);
    }
    if(!complete)return ETIMEDOUT;
    if(index<6)gx.proxy_held|=1u<<index;else gx.cfg_held|=1u<<(index-6);
    const uint32_t off[]={0xd14,0xd14,0xd1c,0xd10,0xd08},val[]={0x10000,0,0,0,1};
    for(unsigned i=0;i<5;++i) {
        error=gx_rsc_snapshot(c,false,true);if(error)return error;
        error=gx_rsc_store(c,off[i],val[i],i!=4);if(error)return error;
    }
    printf("REDFIN GPU PROXY: index=%u address=%#x data=%#x accepted=1 retained=1\n",index,address,data);
    return gx_rsc_snapshot(c,false,false);
}
static int gx_resources(struct gm_context *c)
{
    static const uint8_t names[9][8]={"SH0","MC0","ACV","CN0","CE0","SN6","SN0","SH4","SN10"};
    const volatile uint8_t *db=(const volatile uint8_t *)gm_start.db;
    const uint8_t gfx[8]="gfx.lvl";
    if(gx_check(c) || rf_cmddb_lookup(db,RF_CMDDB_BYTES,gfx,RF_CMDDB_ARC,&gx.gfx)!=RF_CMDDB_OK)return ENXIO;
    for(unsigned i=0;i<9;++i) {
        int error=rf_a6_bcm_lookup(db,names[i],&gx.bcm[i]);if(error)return error;
        printf("REDFIN GPU BCM: name=%.8s address=%#x unit=%u width=%u VCD=%u\n",
            names[i],gx.bcm[i].address,gx.bcm[i].unit,gx.bcm[i].width,gx.bcm[i].vcd);
    }
    int error=rf_a6_perf_make(&gx.gfx,&gm_start.resources[1],&gm_start.resources[2],&gx.performance);
    if(!error)error=rf_a6_bw_make(gx.bcm,&gx.bcm[8],&gx.bandwidth);if(error)return error;
    gx.rsc=ml_io_map(0x18220000,0x10000);if(!gx.rsc)return ENOMEM;
    gx.rsc_id=gm_scalar_read(gx.rsc);gx.rsc_config=gm_scalar_read(gx.rsc+0xc);
    gx.rsc_irq=gm_scalar_read(gx.rsc+0xd00);gx.commands=(gx.rsc_config>>27)&31u;
    unsigned major=(gx.rsc_id>>16)&255u;
    if((major!=1 && major!=2) || gx.rsc_config==UINT32_MAX || !gx.commands || gx.commands>16 ||
        ((gx.rsc_config>>12)&63u)<8 || !(gx.rsc_irq&1u) || gx.rsc_irq==UINT32_MAX)return ENOTSUP;
    error=gx_rsc_snapshot(c,true,false);if(error)return error;
    const unsigned ids[]={4,5,6,0,1,2,7,8,3},width[]={8,16,16,16,4,4,16,8,8},ports[]={1,1,1,2,2,2,1,1,1};
    for(unsigned i=0;i<9;++i) {
        /* Native SCM crypto client125 -> EBI512, AB393.6MB/s IB3936MB/s.
         * No modem bandwidth or modem power is requested by this owner. */
        uint64_t ab=i<6?UINT64_C(393600000):0;
        uint64_t ib=i<6?UINT64_C(3936000000):(uint64_t)RF_A6_CFG_KBPS*1000;
        error=rf_a6_bcm_data(&gx.bcm[ids[i]],width[i],ports[i],ab,ib,
            i==5,&gx.proxy[i]);if(error)return error;
        gx.proxy[i]|=0x40000000;
        for(unsigned t=1;t<8;++t)for(unsigned j=0;j<gx.commands;++j) {
            const struct rf_gp_slot *s=&gx.inherited[t];
            if(!(s->enabled&(1u<<j)) || s->command[j].address!=gx.bcm[ids[i]].address)continue;
            if(!(s->command[j].message&(1u<<16)))return EINVAL;
            error=rf_a6_bcm_floor(gx.proxy[i],s->command[j].data,i==5,&gx.proxy[i]);
            if(error)return error;
        }
    }
    return 0;
}

static int gx_hfi(struct gm_context *c,unsigned id,uint32_t *words,unsigned count)
{
    int error=gx_check(c);if(error)return error;
    uint32_t reply[255];unsigned received=0;
    error=gm_start_command(c,id,words,count,reply,&received);
    if(!error)printf("REDFIN GPU HFI ACK: id=%u sequence=%u count=%u result=%#x\n",
        id,gm_start.sent,received,reply[2]);
    return error;
}
static int gx_power(struct gm_context *c)
{
    /* Native adreno_start raises APPS1 -> GPU_CFG598 to its HIGH case before
     * waking GX. This is separate from the GPU's outgoing CNOC/DDR votes. */
    int error;
    for(unsigned i=6;i<9;++i){error=gx_proxy_vote(c,i);if(error)return error;}
    error=gx_hfi(c,4,(uint32_t *)&gx.performance,sizeof(gx.performance)/4);if(error)return error;
    error=gx_hfi(c,3,(uint32_t *)&gx.bandwidth,sizeof(gx.bandwidth)/4);if(error)return error;
    uint32_t core[]={0,0},vote[]={0,1,1,5},start[]={0};
    error=gx_audit(c);if(error)return error;
    /* CORE_FW_START may already bring GX out of collapse. Only this explicit
     * mode5 power phase permits that transition; access still needs OOB. */
    c->gx_requested=true;
    error=gx_hfi(c,14,core,2);if(error)return error;
    error=gx_hfi(c,30,vote,4);if(error)return error;
    error=gx_audit(c);if(error)return error;
    if(gm_scalar_read(c->base[RF_GT_GMU]+0x14648)&0x80000000u)return EBUSY;
    if(gx_check(c))return ECANCELED;
    gm_memory_store(c->base[RF_GT_GMU]+0x14650,1u<<30);
    uint64_t first=gm_time_ns(c);bool granted=false;
    for(unsigned i=0;i<5000 && gm_time_ns(c)-first<RF_A6_WAIT_NS;++i) {
        error=gx_check(c);if(error)return error;
        uint32_t grant=gm_scalar_read(c->base[RF_GT_GMU]+0x14648);
        if((grant&0x80000000u) && !(gm_scalar_read(c->base[RF_GT_GMU]+0x14340)&0xc0u) &&
            (gm_scalar_read(c->base[RF_GT_GPUCC]+0x100c)&0x80000001u)==0x80000000u) {
            granted=true;break;
        }
        delay(100);
    }
    if(!granted)return ETIMEDOUT;
    gm_memory_store(c->base[RF_GT_GMU]+0x14644,1u<<31);c->gx_granted=true;
    error=gx_audit(c);if(error)return error;
    error=gx_hfi(c,10,start,1);if(error)return error;
    printf("REDFIN GPU POWERED: OOB=fresh low-khz=275000 bw-index=5 GX=%#x SPTPRAC=%#x RPMH=%#x\n",
        gm_scalar_read(c->base[RF_GT_GPUCC]+0x100c),gm_scalar_read(c->base[RF_GT_GMU]+0x14340),
        gm_scalar_read(c->base[RF_GT_GMU]+0x143b0));
    return gx_check(c);
}

static bool gx_scm_valid(void *argument)
{
    return !gx_check(argument) && gm_payloads_valid(argument) && gx.proxy_held==63 && gx.secure.host &&
        gx.secure.owned_bytes==RF_A6_ZAP_ALLOC && gx.pas_phase>=1 && gx.pas_phase<=3;
}
static void gx_scm_delay(void *argument,unsigned us)
{if(gx_scm_valid(argument) && us==30000)delay(30000);}
static int gx_scm_invoke(void *argument,struct rf_sq_regs *r)
{
    unsigned command=gx.pas_phase==1?1:gx.pas_phase==2?2:5;
    uint64_t fn=UINT64_C(0x42000200)|command;
    if(!r || !gx_scm_valid(argument) || (r->x[0]!=fn && r->x[0]!=1))return EPERM;
    if(r->x[0]==fn && (r->x[1]!=(command==1?0x82u:command==2?3u:1u) || r->x[2]!=13 ||
        r->x[3]!=(command==5?0:gx.secure.physical) || r->x[4]!=(command==2?RF_A6_ZAP_SPAN:0) ||
        r->x[5] || r->x[6]))return EPERM;
    register uint64_t x0 __asm__("x0")=r->x[0],x1 __asm__("x1")=r->x[1],
        x2 __asm__("x2")=r->x[2],x3 __asm__("x3")=r->x[3],x4 __asm__("x4")=r->x[4],
        x5 __asm__("x5")=r->x[5],x6 __asm__("x6")=r->x[6],x7 __asm__("x7")=0;
    __asm__ volatile("dsb sy\n\tsmc #0\n\tdsb sy"
        : "+r"(x0),"+r"(x1),"+r"(x2),"+r"(x3),"+r"(x4),"+r"(x5),"+r"(x6),"+r"(x7)
        : : "x8","x9","x10","x11","x12","x13","x14","x15","x16","x17","cc","memory");
    r->x[0]=x0;r->x[1]=x1;r->x[2]=x2;r->x[3]=x3;r->x[4]=x4;r->x[5]=x5;r->x[6]=x6;r->x[7]=x7;
    return gx_check(argument);
}
static int gx_zap_load(struct gm_context *c)
{
    const struct rf_sq_ops o={c,gx_scm_valid,gx_scm_invoke,gx_scm_delay,gm_time_ns};
    struct rf_sq_report report;
    if(gx_check(c) || gx.pas_phase || gx.pas_completed || !gx.secure.host)return EPERM;
    for(unsigned i=0;i<6;++i){int error=gx_proxy_vote(c,i);if(error)return error;}
    /* As native PIL, metadata initially occupies the region itself. INIT
     * takes the signed header before MEM_SETUP makes its load page writable. */
    memcpy(gx.secure.host,gx.mdt,sizeof(gx.mdt));
    gm_memory_clean(&gx.secure);
    if(memcmp(gx.secure.host,gx.mdt,sizeof(gx.mdt)))return EIO;
    gx.pas_phase=1;
    int error=rf_a6_pas_run(&o,1,gx.secure.physical,&report);
    printf("REDFIN GPU PAS13: command=1 result=%d status=%lld value=%#llx calls=%u resumes=%u\n",
        error,(long long)report.status,(unsigned long long)report.value[0],report.calls,report.resumes);
    if(error)return error;gx.pas_completed=1;gx.pas_phase=2;
    error=rf_a6_pas_run(&o,2,gx.secure.physical,&report);
    printf("REDFIN GPU PAS13: command=2 result=%d status=%lld value=%#llx calls=%u resumes=%u\n",
        error,(long long)report.status,(unsigned long long)report.value[0],report.calls,report.resumes);
    if(error)return error;gx.pas_completed=2;
    /* Only now copy the relocatable segment. Never map/touch 0x8bc15400. */
    if(gx_check(c))return ECANCELED;
    memset(gx.secure.host,0,RF_A6_ZAP_SPAN);memcpy(gx.secure.host,gx.zap,sizeof(gx.zap));
    if(memcmp(gx.secure.host,gx.zap,sizeof(gx.zap)))return EIO;
    for(uintptr_t at=(uintptr_t)gx.secure.host;at<(uintptr_t)gx.secure.host+RF_A6_ZAP_SPAN;at+=64)
        __asm__ volatile("dc cvac, %0"::"r"(at):"memory");
    __asm__ volatile("dsb sy":::"memory");
    gx.pas_phase=3;error=rf_a6_pas_run(&o,5,gx.secure.physical,&report);
    printf("REDFIN GPU PAS13: command=5 result=%d status=%lld value=%#llx calls=%u resumes=%u\n",
        error,(long long)report.status,(unsigned long long)report.value[0],report.calls,report.resumes);
    if(!error)gx.pas_completed=3;
    return error;
}

static int gx_register_write(struct gm_context *c,uint32_t at,uint32_t value,uint32_t mask)
{
    if(gx_check(c) || !c->gx_granted || gx.cfg_held!=7 || !gx.gpu || at&3u || at>=0x40000)return EPERM;
    /* Native cold start writes SQE_CNTL=1 once, after all owned mapping and
     * core configuration. The non-native halt3 request stalls this A620. */
    if(at==4*0x808 && (value!=1 || !gx.mapping.state.active || gx.sqe_started ||
        gx.submissions || gx.pas_completed))return EPERM;
    printf("REDFIN GPU REGISTER BEGIN: step=%u offset=%#x value=%#x\n",gx.registers+1,at,value);
    gm_memory_store(gx.gpu+at,value);++gx.registers;
    if(at==4*0x808)gx.sqe_started=true;
    if(gx.registers<=3)printf("REDFIN GPU REGISTER STORED: step=%u offset=%#x\n",gx.registers,at);
    if(mask) {
        uint32_t observed=gm_scalar_read(gx.gpu+at);
        printf("REDFIN GPU REGISTER READBACK: step=%u offset=%#x observed=%#x mask=%#x\n",
            gx.registers,at,observed,mask);
        if((observed^value)&mask)return EIO;
    }
    return 0;
}
static int gx_ring_submit(struct gm_context *c,const uint32_t *words,unsigned count)
{
    int error=gx_audit(c);if(error)return error;
    if(!words || !count || count>32 || gx.submissions>=8 || gx.wptr+count>=RF_A6_RING_BYTES/4 ||
        gm_scalar_read(gx.gpu+4*0x806)!=gx.wptr)return EBUSY;
    uint32_t *ring=gx.data[0].host;
    for(unsigned i=0;i<count;++i)ring[gx.wptr+i]=words[i];
    gm_memory_clean(&gx.data[0]);gx.wptr+=count;
    error=gx_register_write(c,4*0x807,gx.wptr,0);if(error)return error;++gx.submissions;
    uint64_t first=gm_time_ns(c);
    for(unsigned i=0;i<5000 && gm_time_ns(c)-first<RF_A6_WAIT_NS;++i) {
        error=gx_check(c);if(error)return error;
        gx.rptr=gm_scalar_read(gx.gpu+4*0x806);gx.status=gm_scalar_read(gx.gpu+4*0x210);
        gx.fault=gm_scalar_read(gx.gpu+4*0x821);gx.interrupt=gm_scalar_read(gx.gpu+4*0x823);
        if(gx.fault || (gx.interrupt&0xf7u))return EIO;
        if(gx.rptr==gx.wptr && !(gx.status&~1u)) {
            printf("REDFIN GPU SUBMIT: batch=%u words=%u rptr=%u wptr=%u status=%#x\n",
                gx.submissions,count,gx.rptr,gx.wptr,gx.status);
            return gx_audit(c);
        }
        delay(100);
    }
    return ETIMEDOUT;
}
static int gx_core(struct gm_context *c)
{
    int error=gx_audit(c);if(error)return error;
    if(!gx.gpu)gx.gpu=ml_io_map(0x03d00000,0x40000);if(!gx.gpu)return ENOMEM;
    printf("REDFIN GPU CORE: first powered access status=%#x ring=%#x fault=%#x\n",
        gm_scalar_read(gx.gpu+4*0x210),gm_scalar_read(gx.gpu+4*0x806),gm_scalar_read(gx.gpu+4*0x821));
    /* Fresh GX collapse/reset and the sole OOB request establish cold CP
     * ownership. Follow native initialization before the one SQE release. */
    for(unsigned i=0;i<sizeof(rf_a6_registers)/sizeof(rf_a6_registers[0]);++i) {
        const struct rf_a6_register *w=&rf_a6_registers[i];
        error=gx_register_write(c,w->at,w->value,w->mask);
        if(error){printf("REDFIN GPU REGISTER: index=%u offset=%#x wanted=%#x mask=%#x\n",
            i,w->at,w->value,w->mask);return error;}
    }
    if(gm_scalar_read(gx.gpu+4*0x806) || gm_scalar_read(gx.gpu+4*0x807))return EBUSY;
    error=gx_audit(c);if(error)return error;
    error=gx_register_write(c,4*0x808,1,0);if(error)return error;
    uint32_t words[12];unsigned count=rf_a6_me_init(words);
    error=gx_ring_submit(c,words,count);if(error)return error;
    error=gx_zap_load(c);if(error)return error;
    count=rf_a6_unsecure(words);error=gx_ring_submit(c,words,count);if(error)return error;
    /* Two submissions with different boot-bound values prevent an inherited
     * word or a CPU-side initialization from being treated as GPU output. */
    const char *nonce_word=strnstr(c->args,"redfinbootid=0x",c->args_bytes);uint64_t nonce=0;
    if(!nonce_word)return EINVAL;
    for(unsigned i=15;i<31;++i) {
        unsigned digit=(unsigned)(nonce_word[i]-'0');
        if(digit>9)digit=(unsigned)(nonce_word[i]-'a'+10);
        nonce=(nonce<<4)|digit;
    }
    gx.wanted[0]=((uint32_t)nonce&0x00ffffffu)|0x60000000u;
    gx.wanted[1]=~gx.wanted[0];
    gx.wanted[2]=((uint32_t)(nonce>>32)&0x00ffffffu)|0x51000000u;gx.wanted[3]=~gx.wanted[2];
    for(unsigned pass=0;pass<2;++pass) {
        unsigned n=0;
        for(unsigned slot=0;slot<2;++slot) {
            unsigned at=pass*2+slot;
            if(gm_scalar_read(gx.scratch+0x100+4*at))return EAGAIN;
            n+=rf_a6_mem_write(words+n,at,gx.wanted[at]);
        }
        error=gx_ring_submit(c,words,n);if(error)return error;
        for(unsigned slot=0;slot<2;++slot) {
            unsigned at=pass*2+slot;gx.values[at]=gm_scalar_read(gx.scratch+0x100+4*at);
            printf("REDFIN GPU MEMORY RESULT: slot=%u wanted=%#x observed=%#x\n",at,gx.wanted[at],gx.values[at]);
            if(gx.values[at]!=gx.wanted[at])return EIO;
        }
    }
    return gx_audit(c);
}

static void gx_diagnostic(struct gm_context *c)
{
    if(!gm_valid(c))return;
    const struct rf_gmm_lease *lease=&gx.mapping.state;
    printf("REDFIN GPU MAP LAST: step=%u stores=%u block=%u offset=%#x wanted=%#x observed=%#x poisoned=%u slots=%u/%u\n",
        lease->step,lease->stores,lease->block,lease->offset,lease->requested,lease->observed,
        lease->poisoned,gx.mapping.slots[0],gx.mapping.slots[1]);
    printf("REDFIN GPU MAP CONTEXT: SCTLR=%#x TCR2=%#x TCR=%#x TTBR0=%#x/%#x MAIR0=%#x CBAR=%#x CBA2R=%#x\n",
        gm_scalar_read(c->cb),gm_scalar_read(c->cb+0x10),gm_scalar_read(c->cb+0x30),
        gm_scalar_read(c->cb+0x20),gm_scalar_read(c->cb+0x24),gm_scalar_read(c->cb+0x38),
        gm_scalar_read(c->smmu+0x1000),gm_scalar_read(c->smmu+0x1800));
    printf("REDFIN GPU SMMU STATE: FSR=%#x FAR=%#x/%#x FSYNR=%#x GFSR=%#x\n",
        gm_scalar_read(c->cb+0x58),gm_scalar_read(c->cb+0x60),gm_scalar_read(c->cb+0x64),
        gm_scalar_read(c->cb+0x68),gm_scalar_read(c->smmu+0x48));
    printf("REDFIN GPU POWER STATE: GX=%#x SPTPRAC=%#x OOB=%#x FW=%#x\n",
        gm_scalar_read(c->base[RF_GT_GPUCC]+0x100c),gm_scalar_read(c->base[RF_GT_GMU]+0x14340),
        gm_scalar_read(c->base[RF_GT_GMU]+0x14648),gm_scalar_read(c->base[RF_GT_GMU]+0x14070));
    if(gx.gpu && c->gx_granted && gm_start_base_valid(c) &&
        !(gm_scalar_read(c->base[RF_GT_GMU]+0x14340)&0xc0u) &&
        (gm_scalar_read(c->base[RF_GT_GPUCC]+0x100c)&0x80000001u)==0x80000000u) {
        const uint32_t offsets[]={0x201,0x210,0x806,0x807,0x808,0x821,0x823,0x824,0xf400};
        for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);++i)
            printf("REDFIN GPU CORE STATE: word=%#x value=%#x\n",offsets[i],gm_scalar_read(gx.gpu+4*offsets[i]));
    }
}
static int gx_run(struct gm_context *c)
{
    if(!gx.bound || gx.entered || gx.context!=c || c->smmu_mode!=5)return EPERM;
    gx.entered=true;gx.started=gm_time_ns(c);int error=gx_check(c);
    if(error)goto done;
    gx.stage=1;error=gm_start_audit(c,RF_GB_HFI_LIVE);if(error)goto done;
    error=gx_resources(c);if(error)goto done;
    gx.stage=2;
    const uint32_t address[]={RF_A6_RING,RF_A6_SQE,RF_A6_SCRATCH},bytes[]={0x8000,0x8000,0x1000};
    for(unsigned i=0;i<3;++i) {
        error=gx_allocate(&gx.data[i],address[i],bytes[i],0x200+i,false);if(error)goto done;
    }
    error=gx_allocate(&gx.pool,0,0x4000,0x210,false);if(error)goto done;
    error=gx_allocate(&gx.secure,0,RF_A6_ZAP_ALLOC,0x220,true);if(error)goto done;
    memcpy(gx.data[1].host,gx.sqe+4,sizeof(gx.sqe)-4);
    if(memcmp(gx.data[1].host,gx.sqe+4,sizeof(gx.sqe)-4)){error=EIO;goto done;}
    const struct rf_gm_memory_owner owner={c,gx_valid,gx_owns};
    error=rf_a6_pt_build(&gm_memory.lease.expected,gx.data,&gx.pool,&owner,&gx.tables);if(error)goto done;
    printf("REDFIN GPU MEMORY: owned=%llu allocations=%u tables=%u pages=%u SQE-words=%u\n",
        (unsigned long long)gx.allocated,gx.allocations,gx.tables.table_count,gx.tables.mapped_pages,
        (unsigned)(sizeof(gx.sqe)-4)/4);
    /* Power/OOB precedes the native GPU stream binding. Local IRQs stay
     * masked; the fresh cold CP is started only after mapping/configuration. */
    gx.stage=3;error=gx_power(c);if(error)goto done;
    printf("REDFIN GPU MMIO PREFLIGHT: cfg-held=%#x fence=%#x/%#x clocks=%#x/%#x/%#x\n",
        gx.cfg_held,gm_scalar_read(c->base[RF_GT_GMU]+0x24c40),
        gm_scalar_read(c->base[RF_GT_GMU]+0x24c4c),gm_scalar_read(c->base[RF_GT_GPUCC]+0x1078),
        gm_scalar_read(c->base[RF_GT_GPUCC]+0x1064),gm_scalar_read(c->base[RF_GT_GPUCC]+0x109c));
    /* Native ALLOW mode is safe only after the owned GX/OOB proof. Do not
     * discard a fence error: a nonzero status stops before core access. */
    if(gx_check(c)){error=ECANCELED;goto done;}
    gm_memory_store(c->base[RF_GT_GMU]+0x24c40,0);
    if(gm_scalar_read(c->base[RF_GT_GMU]+0x24c40) || gm_scalar_read(c->base[RF_GT_GMU]+0x24c4c))
        {error=EIO;goto done;}
    printf("REDFIN GPU MMIO MAP: begin\n");
    gx.gpu=ml_io_map(0x03d00000,0x40000);if(!gx.gpu){error=ENOMEM;goto done;}
    printf("REDFIN GPU MMIO MAP: ready; first RBBM_STATUS read begins\n");
    uint32_t first_status=gm_scalar_read(gx.gpu+4*0x210);
    printf("REDFIN GPU MMIO FIRST READ: RBBM_STATUS=%#x\n",first_status);
    error=gx_register_write(c,4*0x38,0,UINT32_MAX);if(error)goto done;
    error=gx_register_write(c,4*0x3a,0,UINT32_MAX);if(error)goto done;
    error=gx_register_write(c,4*0xae,0,0);if(error)goto done; /* No HWCG before CP setup. */
    gx.stage=4;struct rf_gmm_ops o=gx_mapping_ops;o.context=c;
    error=rf_a6_map_claim(&gx.mapping,&o,&gm_memory.lease,&gx.tables);if(error)goto done;
    /* Uncached host view before GPU DMA; never read its cached scratch alias
     * after this point, including in an ownership/publication callback. */
    for(uintptr_t at=(uintptr_t)gx.data[2].host;at<(uintptr_t)gx.data[2].host+gx.data[2].owned_bytes;at+=64)
        __asm__ volatile("dc civac, %0"::"r"(at):"memory");
    __asm__ volatile("dsb osh":::"memory");
    gx.scratch=ml_io_map_wcomb(gx.data[2].physical,gx.data[2].owned_bytes);
    if(!gx.scratch){error=ENOMEM;goto done;}
    gx.stage=5;error=gx_core(c);if(error)goto done;
    gx.stage=6;
done:
    gx_diagnostic(c);
    printf("REDFIN GPU COMMAND RESULT: result=%d stage=%u mapped=%u GX-request=%u GX-grant=%u PAS=%u submissions=%u registers=%u\n",
        error,gx.stage,gx.mapping.state.active,c->gx_requested,c->gx_granted,gx.pas_completed,
        gx.submissions,gx.registers);
    printf("REDFIN GPU COMMAND MEMORY: result=%d verified=%u/%u retained-bytes=%llu elapsed-ns=%llu; held until platform reset\n",
        error,gx.submissions>=3 && gx.values[0]==gx.wanted[0] && gx.values[1]==gx.wanted[1],
        gx.submissions>=4 && gx.values[2]==gx.wanted[2] && gx.values[3]==gx.wanted[3],
        (unsigned long long)gx.allocated,(unsigned long long)(gm_time_ns(c)-gx.started));
    return error;
}
