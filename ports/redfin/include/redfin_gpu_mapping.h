/* SPDX-License-Identifier: MIT */
/* Owned A620 CB0, with native SID0/mask401 expressed as two disjoint
 * SID0/1 mask400 routes. CB1/GMU and secure SID2/mask400 are preserved. */
#ifndef REDFIN_GPU_MAPPING_H
#define REDFIN_GPU_MAPPING_H
#include "redfin_gpu_command.h"

static inline int rf_a6_pt_build(const struct rf_gs_snapshot *global,
    const struct rf_gm_memory data[3],const struct rf_gm_memory *pool,
    const struct rf_gm_memory_owner *owner,struct rf_gm_pt_plan *out)
{
    if(!global || !data || !pool || !owner || !owner->valid || !owner->owns || !out ||
        !rf_gm_snapshot_format(global) || !rf_gm_memory_valid(pool) || pool->gmu_address ||
        !owner->valid(owner->context) || !owner->owns(owner->context,pool,RF_GM_PT_TABLE_POOL))return EINVAL;
    struct rf_gm_pt_plan p={0};
    p.tables=*pool;p.root_physical=pool->physical;p.granule=4096;p.virtual_bits=39;
    p.physical_bits=36;p.mair0=0xf404ff44;p.extent_count=3;p.table_count=1;
    p.nodes[0]=(struct rf_gm_pt_node){1,0,UINT32_MAX,0};
    const uint32_t addresses[]={RF_A6_RING,RF_A6_SQE,RF_A6_SCRATCH};
    const uint32_t lengths[]={0x8000,0x8000,0x1000};
    for(unsigned i=0;i<3;++i) {
        if(!rf_gm_memory_valid(&data[i]) || data[i].gmu_address!=addresses[i] ||
            data[i].owned_bytes<lengths[i] || rf_gm_memory_alias(pool,&data[i]) ||
            rf_gm_host_alias(pool,out,sizeof(*out)) || rf_gm_host_alias(&data[i],out,sizeof(*out)) ||
            !owner->valid(owner->context) || !owner->owns(owner->context,&data[i],RF_GM_PT_DATA))return EACCES;
        for(unsigned j=0;j<i;++j)if(rf_gm_memory_alias(&data[j],&data[i]))return EINVAL;
        p.extents[i].memory=data[i];p.extents[i].mapped_bytes=lengths[i];
        p.extents[i].permissions=i==1?1u:3u;
        for(unsigned j=0;j<lengths[i];j+=4096) {
            uint32_t address=addresses[i]+j,l2,l3;
            int error=rf_gm_pt_node_index(&p,2,address>>30,0,(address>>30)&511u,&l2);
            if(!error)error=rf_gm_pt_node_index(&p,3,address>>21,l2,(address>>21)&511u,&l3);
            if(error)return error;++p.mapped_pages;
        }
        p.mapped_bytes+=lengths[i];
    }
    p.table_bytes=(uint64_t)p.table_count*4096;
    if(p.table_bytes>pool->owned_bytes || rf_gm_host_alias(pool,data,3*sizeof(*data)) ||
        rf_gm_host_alias(pool,pool,sizeof(*pool)) || rf_gm_host_alias(pool,global,sizeof(*global)) ||
        rf_gm_host_alias(pool,owner,sizeof(*owner)))return EINVAL;
    if(!owner->valid(owner->context))return ECANCELED;
    memset(pool->host,0,(size_t)p.table_bytes);
    for(unsigned i=1;i<p.table_count;++i) {
        const struct rf_gm_pt_node *n=&p.nodes[i];
        if(!owner->valid(owner->context))return ECANCELED;
        rf_gm_write_le64((uint8_t *)pool->host+4096*n->parent+8*n->slot,
            (pool->physical+4096*i)|3u);
    }
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<lengths[i];j+=4096) {
        uint32_t address=addresses[i]+j,node;
        for(node=0;node<p.table_count;++node)
            if(p.nodes[node].level==3 && p.nodes[node].prefix==(address>>21))break;
        if(node==p.table_count)return EINVAL;
        if(!owner->valid(owner->context))return ECANCELED;
        /* Normal-NC, OSH, AF, nG, unprivileged. SQE is read-only. */
        rf_gm_write_le64((uint8_t *)pool->host+4096*node+8*((address>>12)&511u),
            (data[i].physical+j)|(i==1?0xec3u:0xe43u));
    }
    if(!owner->valid(owner->context))return ECANCELED;
    *out=p;return 0;
}

struct rf_a6_mapping {
    struct rf_gmm_lease state;
    unsigned slots[2],step,ttbr1_valid;
};
#define RF_A6_MAP_STEPS 18u
static inline int rf_a6_map_step(const struct rf_a6_mapping *s,const struct rf_gm_pt_plan *p,
    unsigned step,unsigned *block,uint32_t *at,uint32_t *value)
{
    if(!s || !p || !block || !at || !value || step>=RF_A6_MAP_STEPS)return EINVAL;
    *block=1;*at=0;*value=0;
    switch(step) {
    case 0:break;
    case 1:*block=0;*at=0x1800;*value=1;break;
    case 2:*block=0;*at=0x1000;*value=0x1f300;break;
    case 3:*at=0x10;*value=RF_GMM_TCR2;break;
    case 4:*at=0x30;*value=RF_GMM_TCR;break;
    case 5:*at=0x20;*value=(uint32_t)p->root_physical;break;
    case 6:*at=0x24;*value=(uint32_t)(p->root_physical>>32);break; /* Preferred CB0/ASID0. */
    case 7:*at=0x28;break;
    case 8:*at=0x2c;break;
    case 9:*at=0x38;*value=p->mair0;break;
    case 10:*at=0x3c;break;
    case 11:*at=0x610;break; /* ASID0, distinct from the owned GMU's ASID1. */
    case 12:*at=0x7f0;*value=1;break;
    case 13:*value=RF_GMM_SCTLR|0x100;break; /* Native HUPCF, no stall/IRQ. */
    case 14:*block=0;*at=0xc00+4*s->slots[0];break;
    case 15:*block=0;*at=0x800+4*s->slots[0];*value=0x84000000;break;
    case 16:*block=0;*at=0xc00+4*s->slots[1];break;
    default:*block=0;*at=0x800+4*s->slots[1];*value=0x84000001;break;
    }
    return 0;
}
static inline int rf_a6_map_verify(struct rf_a6_mapping *m,const struct rf_gmm_ops *o)
{
    struct rf_gmm_lease *s=&m->state;
    int error=o->check(o->context);
    if(!error)error=o->sample(o->context,&s->fresh,&s->fresh_banks);
    if(!error && !rf_gmm_equal(s))error=EAGAIN;
    for(unsigned i=0;!error && i<2;++i)if(m->ttbr1_valid&(1u<<i)) {
        uint32_t value;
        error=o->read(o->context,1,0x28+4*i,&value);
        if(!error && value)error=EAGAIN;
    }
    if(error){s->active=0;s->poisoned=1;}
    return error;
}
static inline int rf_a6_map_claim(struct rf_a6_mapping *m,const struct rf_gmm_ops *o,
    const struct rf_gmm_lease *gmu,const struct rf_gm_pt_plan *p)
{
    if(!m || !o || !o->check || !o->sample || !o->read || !o->write || !o->publish ||
        !o->delay || !gmu || !p || !gmu->active || gmu->poisoned || m->state.attempted)return EINVAL;
    struct rf_gmm_lease *s=&m->state;s->attempted=1;
    const struct rf_gs_snapshot *g=&gmu->expected;
    const struct rf_gc_snapshot *b=&gmu->banks;
    if(!rf_gm_snapshot_format(g) || g->id0!=0x4c017e05 || g->id1!=0x20000005 ||
        g->id2!=0x5511 || g->id7!=0x24 || g->fault || (g->control&9u) ||
        g->references[0] || g->cbar[0] || g->cba2r[0] ||
        !b->stable || b->error || (b->words[0][0]&1u) || b->fault_mask ||
        !(b->words[1][0]&1u) || !rf_gm_memory_valid(&p->tables) ||
        p->root_physical!=p->tables.physical || p->granule!=4096 || p->virtual_bits!=39 ||
        p->physical_bits!=36 || p->mair0!=0xf404ff44 || p->extent_count!=3 ||
        p->table_count!=4 || p->table_bytes!=16384 || p->tables.owned_bytes<p->table_bytes)return EPERM;
    unsigned found=0;
    for(unsigned i=0;i<g->streams;++i) {
        if(rf_gs_stream_matches(g->smr[i],0) || rf_gs_stream_matches(g->smr[i],1) ||
            rf_gs_stream_matches(g->smr[i],0x400) || rf_gs_stream_matches(g->smr[i],0x401))return EBUSY;
        if(!(g->smr[i]&0x80000000u) && found<2)m->slots[found++]=i;
    }
    if(found!=2)return ENOSPC;
    s->expected=*g;s->banks=*b;
    int error=rf_a6_map_verify(m,o);if(error)return error;
    error=o->publish(o->context,p);if(error)return error;
    s->owned=1;
    for(unsigned step=0;step<RF_A6_MAP_STEPS;++step) {
        error=rf_a6_map_verify(m,o);if(error)return error;
        unsigned block;uint32_t at,value,got=0;
        error=rf_a6_map_step(m,p,step,&block,&at,&value);if(error)return error;
        m->step=step;s->step=step;s->block=block;s->offset=at;s->requested=value;++s->stores;
        error=o->write(o->context,block,at,value);if(error)goto failed;
        if(step==11)continue;
        if(step==12) {
            for(unsigned i=0;i<1000;++i) {
                if((error=o->check(o->context)) || (error=o->read(o->context,1,0x7f4,&got)))goto failed;
                ++s->polls;if(!(got&1u))break;
                error=o->delay(o->context,1);if(error)goto failed;
            }
            if(got&1u){error=ETIMEDOUT;goto failed;}
            continue;
        }
        error=o->check(o->context);if(error)goto failed;
        error=o->read(o->context,block,at,&got);if(error)goto failed;s->observed=got;
        uint32_t mask=step==2?0x30000u:step==3?0x38017u:step==4?0x00c0ffbfu:
            step==13?0x001001f1u:(step==14 || step==16)?0x000300ffu:UINT32_MAX;
        /* As preferred space_on(), require translation type and CB index.
         * HYP may retain/force PRIVCFG; our only mapped pages are owned and
         * allow both privilege levels. Keep the whole observed word in every
         * later exact audit, including those implementation-controlled bits. */
        if((got&mask)!=(value&mask)){error=EIO;goto failed;}
        if(step==7 || step==8)m->ttbr1_valid|=1u<<(step-7);
        if(!block) {
            if(step==1){s->expected.cba2r[0]=got;s->banks.words[0][8]=(s->banks.words[0][8]&~0x600u)|0x400u;}
            else if(step==2)s->expected.cbar[0]=got;
            else if(step==14 || step==16)s->expected.s2cr[m->slots[(step-14)/2]]=got;
            else s->expected.smr[m->slots[(step-15)/2]]=got;
        } else for(unsigned i=0;i<RF_GC_WORDS;++i)if(rf_gc_offsets[i]==at)s->banks.words[0][i]=got;
    }
    error=rf_a6_map_verify(m,o);if(error)goto failed;
    s->active=1;return 0;
failed:
    s->active=0;s->poisoned=1;return error;
}
#endif
