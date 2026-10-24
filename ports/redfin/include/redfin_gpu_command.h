/* SPDX-License-Identifier: MIT */
/* A620 command backend protocol. Register/packet facts: native Google msm
 * 500b3a2059c1eec0fec08ec56add06320ea901a8 and preferred HackiOS
 * 8e61187098f2c26c5daee8f9f72b6416aa64b9ab. Include after redfin_rpmh.h.
 * No firmware bytes, secure carve-out addresses or iOS capability stubs.
 */
#ifndef REDFIN_GPU_COMMAND_H
#define REDFIN_GPU_COMMAND_H
#include "redfin_gmu_mapping.h"
#include "redfin_scm_query.h"

#define RF_A6_RING 0x01000000u
#define RF_A6_SQE 0x01100000u
#define RF_A6_SCRATCH 0x01200000u
#define RF_A6_RING_BYTES 0x8000u
#define RF_A6_SQE_BYTES 31632u
#define RF_A6_MDT_BYTES 6860u
#define RF_A6_ZAP_BYTES 1676u
#define RF_A6_ZAP_ALLOC 0x100000u
#define RF_A6_ZAP_SPAN 0x1000u
#define RF_A6_GMU_SLOT 1u
#define RF_A6_WAIT_NS UINT64_C(500000000)

/* Byte offsets, matching the Redfin ADT contract. The low OPP is common to
 * every live speed bin; its native DDR use case is 5 (2188000 KB/s). */
static const uint32_t rf_a6_policy[] = {
    3,0x06020001,275000000,64,5,14,32,3,0,0x401,UINT32_MAX,0,13,
    RF_A6_ZAP_ALLOC,RF_A6_ZAP_SPAN,RF_A6_RING,RF_A6_RING_BYTES,
    RF_A6_SQE,RF_A6_SCRATCH,500,0,RF_A6_GMU_SLOT /* GPU ASID0, GMU ASID1/slot1. */
};
static const uint32_t rf_a6_ddr_kbps[] = {
    0,400000,800000,1200000,1804800,2188000,2724000,3072000,
    4068000,5412000,6220000,7216000,8371200
};

struct rf_a6_bcm { uint32_t address,unit; uint16_t width; uint8_t vcd,reserved; };

static inline int rf_a6_bcm_lookup(const volatile uint8_t *db,const uint8_t key[8],
    struct rf_a6_bcm *out)
{
    struct rf_cmddb_resource resource;
    if(!db || !key || !out || rf_cmddb_lookup(db,RF_CMDDB_BYTES,key,RF_CMDDB_BCM,&resource)!=RF_CMDDB_OK ||
        !resource.address || (resource.address&3u) || resource.aux_bytes!=8)return EINVAL;
    struct rf_a6_bcm found={0};unsigned matches=0;
    for(unsigned i=0;i<8;++i) {
        const volatile uint8_t *h=db+8+16*i;
        unsigned type=rf_cmddb_u16(h),count=rf_cmddb_u16(h+6);
        if(!type)break;
        uint32_t entries=RF_CMDDB_HEADER+rf_cmddb_u16(h+2),aux=RF_CMDDB_HEADER+rf_cmddb_u16(h+4);
        if(count>RF_CMDDB_MAX_ENTRIES || !rf_cmddb_range(entries,count*RF_CMDDB_ENTRY,RF_CMDDB_BYTES))return EINVAL;
        for(unsigned j=0;j<count;++j) {
            const volatile uint8_t *entry=db+entries+j*RF_CMDDB_ENTRY;
            unsigned same=1;for(unsigned k=0;k<8;++k)same&=entry[k]==key[k];
            if(!same)continue;
            uint32_t at=aux+rf_cmddb_u16(entry+22);
            if(++matches!=1 || rf_cmddb_u32(entry+16)!=resource.address ||
                rf_cmddb_u16(entry+20)!=8 || !rf_cmddb_range(at,8,RF_CMDDB_BYTES))return EINVAL;
            found=(struct rf_a6_bcm){resource.address,rf_cmddb_u32(db+at),
                rf_cmddb_u16(db+at+4),db[at+6],db[at+7]};
        }
    }
    if(matches!=1 || found.vcd>=16 || found.reserved)return EINVAL;
    *out=found;return 0;
}

static inline uint64_t rf_a6_div(uint64_t n,uint64_t d)
{ return n/d+(n%d!=0); }
static inline int rf_a6_bcm_data(const struct rf_a6_bcm *b,unsigned node_width,
    unsigned ports,uint64_t ab,uint64_t ib,bool acv,uint32_t *out)
{
    if(!b || !out || !node_width || !ports || b->reserved || b->vcd>=16)return EINVAL;
    if(acv){*out=(ab||ib)?0x20000008u:0;return 0;}
    if(!b->unit || !b->width || ab>UINT64_MAX/b->width || ib>UINT64_MAX/b->width)return EINVAL;
    uint64_t x=rf_a6_div(rf_a6_div(ab*b->width,(uint64_t)node_width*ports),b->unit);
    uint64_t y=rf_a6_div(rf_a6_div(ib*b->width,node_width),b->unit);
    if(x>0x3fff)x=0x3fff;if(y>0x3fff)y=0x3fff;
    *out=(x||y?0x20000000u:0)|(uint32_t)(x<<14)|(uint32_t)y;
    return 0;
}
static inline int rf_a6_bcm_floor(uint32_t wanted,uint32_t old,bool acv,uint32_t *out)
{
    if(!out || (old&~0x6fffffffu) || ((old&0x0fffffffu) && !(old&0x20000000u)))return EINVAL;
    uint32_t x=(wanted>>14)&0x3fff,y=wanted&0x3fff,ox=(old>>14)&0x3fff,oy=old&0x3fff;
    if(acv){if(x||ox)return EINVAL;y|=oy;}
    else {if(x<ox)x=ox;if(y<oy)y=oy;}
    *out=0x40000000u|(x||y?0x20000000u:0)|(x<<14)|y;return 0;
}
static inline int rf_a6_arc_vote(const struct rf_cmddb_resource *rail,
    const struct rf_cmddb_resource *mx,uint16_t level,uint32_t *out)
{
    if(!rail || !mx || !out || rail->type!=RF_CMDDB_ARC || mx->type!=RF_CMDDB_ARC ||
        rail->aux_version!=0x1000 || mx->aux_version!=0x1000 ||
        !rail->level_count || rail->level_count>16 || !mx->level_count || mx->level_count>16)return EINVAL;
    unsigned count[2]={0,0};const struct rf_cmddb_resource *r[2]={rail,mx};
    for(unsigned which=0;which<2;++which) {
        if(r[which]->levels[0])return EINVAL;
        count[which]=1;
        for(unsigned i=1;i<r[which]->level_count;++i) {
            if(!r[which]->levels[i]) {
                for(unsigned j=i;j<r[which]->level_count;++j)if(r[which]->levels[j])return EINVAL;
                break;
            }
            if(r[which]->levels[i]<=r[which]->levels[i-1])return EINVAL;
            ++count[which];
        }
    }
    unsigned primary=0,secondary=0;
    while(primary<count[0] && rail->levels[primary]<level)++primary;
    if(primary==count[0])return ERANGE;
    while(secondary+1<count[1] && mx->levels[secondary]<rail->levels[primary])++secondary;
    *out=((uint32_t)rail->levels[primary]<<16)|(secondary<<8)|primary;return 0;
}

struct rf_a6_perf {
    uint32_t header,gpu_levels,gmu_levels;
    struct {uint32_t vote,acd,khz;} gpu[16];
    struct {uint32_t vote,khz;} gmu[4];
};
struct rf_a6_bw {
    uint32_t header,levels,cnoc_commands,ddr_commands,cnoc_wait,ddr_wait;
    uint32_t cnoc_address[6],cnoc_data[2][6],ddr_address[8],ddr_data[16][8];
};
static inline int rf_a6_perf_make(const struct rf_cmddb_resource *gfx,
    const struct rf_cmddb_resource *cx,const struct rf_cmddb_resource *mx,struct rf_a6_perf *out)
{
    if(!out)return EINVAL;
    struct rf_a6_perf p={0};p.gpu_levels=2;p.gmu_levels=2;
    p.gpu[0].acd=p.gpu[1].acd=UINT32_MAX;p.gpu[1].khz=275000;p.gmu[1].khz=200000;
    int error=rf_a6_arc_vote(gfx,mx,0,&p.gpu[0].vote);
    if(!error)error=rf_a6_arc_vote(gfx,mx,64,&p.gpu[1].vote);
    if(!error)error=rf_a6_arc_vote(cx,mx,0,&p.gmu[0].vote);
    if(!error)error=rf_a6_arc_vote(cx,mx,48,&p.gmu[1].vote);
    if(!error)*out=p;return error;
}

/* b[0..2] are SH0/MC0/ACV, b[3] CN0. Native VCD order determines command
 * ordering, commits and waits, including the DDR-off entry. */
static inline int rf_a6_bw_make(const struct rf_a6_bcm b[4],struct rf_a6_bw *out)
{
    if(!b || !out)return EINVAL;
    struct rf_a6_bw p={0};unsigned order[3]={0,1,2};
    for(unsigned i=0;i<4;++i) {
        if(!b[i].address || (b[i].address&3u) || b[i].vcd>=16 || b[i].reserved ||
            (i!=2 && (!b[i].unit || !b[i].width)))return EINVAL;
        for(unsigned j=0;j<i;++j)if(b[j].address==b[i].address)return EINVAL;
    }
    for(unsigned i=0;i<3;++i)for(unsigned j=i+1;j<3;++j)
        if(b[order[j]].vcd<b[order[i]].vcd){unsigned t=order[i];order[i]=order[j];order[j]=t;}
    p.levels=13;p.cnoc_commands=1;p.ddr_commands=3;p.cnoc_wait=1;
    p.cnoc_address[0]=b[3].address;p.cnoc_data[0][0]=0x40000000;
    int error=rf_a6_bcm_data(&b[3],8,1,0,100000,false,&p.cnoc_data[1][0]);
    if(error)return error;p.cnoc_data[1][0]|=0x40000000;
    for(unsigned j=0;j<3;++j) {
        unsigned resource=order[j];bool commit=j==2 || b[resource].vcd!=b[order[j+1]].vcd;
        p.ddr_address[j]=b[resource].address;if(commit)p.ddr_wait|=1u<<j;
        for(unsigned i=0;i<13;++i) {
            error=rf_a6_bcm_data(&b[resource],resource?4:16,2,0,
                (uint64_t)rf_a6_ddr_kbps[i]*1000,resource==2,&p.ddr_data[i][j]);
            if(error)return error;if(commit)p.ddr_data[i][j]|=0x40000000;
        }
    }
    *out=p;return 0;
}

/* Actual signed ELF32 split image: exactly one relocatable PT_LOAD. Native
 * PIL rounds its address span to 4KiB and its allocation to p_align (1MiB).
 * Metadata/hash program headers are not copied as executable segments. */
struct rf_a6_zap {uint32_t segment,file_bytes,memory_bytes,span,allocation,base;};
static inline int rf_a6_zap_plan(const uint8_t *mdt,size_t bytes,size_t segment_bytes,
    struct rf_a6_zap *out)
{
    if(!mdt || !out || bytes!=RF_A6_MDT_BYTES || segment_bytes!=RF_A6_ZAP_BYTES ||
        mdt[0]!=0x7f || mdt[1]!='E' || mdt[2]!='L' || mdt[3]!='F' || mdt[4]!=1 ||
        mdt[5]!=1 || mdt[6]!=1 || redfin_gmu_read_le32(mdt+28)!=52 ||
        rf_cmddb_u16(mdt+40)!=52 || rf_cmddb_u16(mdt+42)!=32 || rf_cmddb_u16(mdt+44)!=3)return EINVAL;
    unsigned loads=0;struct rf_a6_zap p={0};
    for(unsigned i=0;i<3;++i) {
        const uint8_t *h=mdt+52+32*i;
        uint32_t type=redfin_gmu_read_le32(h),flags=redfin_gmu_read_le32(h+24);
        if(type!=1 || (flags&0x07000000u)==0x02000000u || !redfin_gmu_read_le32(h+20))continue;
        p=(struct rf_a6_zap){i,redfin_gmu_read_le32(h+16),redfin_gmu_read_le32(h+20),
            0,redfin_gmu_read_le32(h+28),redfin_gmu_read_le32(h+12)};
        if(++loads!=1 || flags!=0x08000007u || redfin_gmu_read_le32(h+4)!=0x3000 ||
            redfin_gmu_read_le32(h+8)!=0x5000 || p.segment!=2 || p.file_bytes!=segment_bytes ||
            p.memory_bytes!=p.file_bytes || p.base!=0x5000 || p.allocation!=RF_A6_ZAP_ALLOC)return EINVAL;
        p.span=((p.base+p.memory_bytes+4095u)&~4095u)-p.base;
    }
    if(loads!=1 || p.span!=RF_A6_ZAP_SPAN)return EINVAL;
    *out=p;return 0;
}

/* PAS13 only, SCM64 only, dynamically allocated 1MiB-aligned owned RAM.
 * The caller supplies and audits that allocation and strict init/setup/auth
 * phases. A failure never means that an inherited zap can be trusted. */
static inline int rf_a6_pas_run(const struct rf_sq_ops *o,unsigned command,
    uint64_t physical,struct rf_sq_report *report)
{
    if(!o || !report || !o->valid || !o->invoke || !o->time_ns || !o->delay_us ||
        (command!=1 && command!=2 && command!=5) || (physical&(RF_A6_ZAP_ALLOC-1u)) ||
        physical<RF_GM_PT_RAM_BASE || physical>RF_GM_PT_RAM_BASE+RF_GM_PT_RAM_BYTES-RF_A6_ZAP_ALLOC)return EINVAL;
    struct rf_sq_regs request={{0}},live;
    request.x[0]=UINT64_C(0x42000200)|command;
    request.x[1]=command==1?0x82u:command==2?3u:1u;request.x[2]=13;
    request.x[3]=command==5?0:physical;request.x[4]=command==2?RF_A6_ZAP_SPAN:0;
    *report=(struct rf_sq_report){0};report->convention=64;report->kind=command;
    report->function=request.x[0];report->argument=13;
    uint64_t first=o->time_ns(o->context);live=request;
    for(;;) {
        if(!o->valid(o->context))return ECANCELED;
        uint64_t now=o->time_ns(o->context);
        if(now<first || now-first>UINT64_C(2000000000))return ETIMEDOUT;
        if(live.x[0]!=request.x[0] && live.x[0]!=1)return EINVAL;
        live.x[7]=0;int error=o->invoke(o->context,&live);++report->calls;
        if(error)return error;if(!o->valid(o->context))return ECANCELED;
        now=o->time_ns(o->context);if(now<first || now-first>UINT64_C(2000000000))return ETIMEDOUT;
        report->elapsed_ns=now-first;report->status=(int64_t)live.x[0];
        for(unsigned i=0;i<3;++i)report->value[i]=live.x[i+1];
        if(report->status==1){if(++report->resumes>128)return ETIMEDOUT;continue;}
        if(report->status==-12) {
            if(report->busy_retries++>=3)return EBUSY;
            o->delay_us(o->context,30000);live=request;continue;
        }
        report->completed=true;return report->status || report->value[0]?EIO:0;
    }
}

static inline uint32_t rf_a6_parity(uint32_t v)
{return (0x9669u>>((v^(v>>4)^(v>>8)^(v>>12)^(v>>16)^(v>>20)^(v>>24)^(v>>28))&15u))&1u;}
static inline uint32_t rf_a6_packet7(uint32_t opcode,unsigned count)
{return 0x70000000u|count|(rf_a6_parity(count)<<15)|(opcode<<16)|(rf_a6_parity(opcode)<<23);}
static inline unsigned rf_a6_me_init(uint32_t words[12])
{
    /* No preemption/IFPC register-list pointer at zero: omit ordinal8, use
     * native 11-word layout with native optional-ordinal padding. */
    static const uint32_t body[11]={0x6f,3,0x20000000,0,0,0,2,0,0,0,0};
    words[0]=rf_a6_packet7(0x48,11);memcpy(words+1,body,sizeof(body));return 12;
}
static inline unsigned rf_a6_unsecure(uint32_t words[2])
{words[0]=rf_a6_packet7(0x66,1);words[1]=0;return 2;}
static inline unsigned rf_a6_mem_write(uint32_t words[5],unsigned slot,uint32_t value)
{
    if(slot>=16)return 0;
    words[0]=rf_a6_packet7(0x3d,3);words[1]=RF_A6_SCRATCH+0x100+4*slot;
    words[2]=0;words[3]=value;words[4]=rf_a6_packet7(0x26,0);return 5;
}

struct rf_a6_register {uint32_t at,value,mask;};
/* Generated from reviewed native A620 tables; see GPU-COMMANDS.md. */
#include "redfin_gpu_registers.h"
#endif
