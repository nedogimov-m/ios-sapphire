/* SPDX-License-Identifier: MIT */
/* A620 runtime protocol, adapted from preferred HackiOS msm-1.7 bridge.
 * All GPU addresses belong to this allocator; the bootstrap region is absent.
 * One 64KiB guard follows each object. Callers serialize the complete operation.
 */
#ifndef REDFIN_GPU_RUNTIME_H
#define REDFIN_GPU_RUNTIME_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define RF_GR_BASE UINT64_C(0x10000000)
#define RF_GR_BYTES UINT64_C(0x20000000)
#define RF_GR_GRANULE UINT64_C(0x10000)
#define RF_GR_TABLE_BYTES 0x100000u
#define RF_GR_TABLES 256u
#define RF_GR_OBJECTS 1024u
#define RF_GR_BUFFER_MAX (128u<<20)
#define RF_GR_MEMORY_MAX (512u<<20)
#define RF_GR_COMMANDS 128u
#define RF_GR_FENCE_AT 0x200u
#define RF_GR_PACKET_WORDS (4u*RF_GR_COMMANDS+16u)
#define RF_GR_HOST_PAGE 16384u
static const uint32_t rf_gr_policy[]={1,0x06020001,512,128,1024,128,500,0x10000,0x100000,1};

struct rf_gr_object {uint64_t address,size,span;};
struct rf_gr_arena {struct rf_gr_object objects[RF_GR_OBJECTS];uint64_t bytes;};
/* allocSize already includes the surface's own offset. A prepared wrapped
 * range additionally starts wrapDelta bytes into its first native page. */
static inline bool rf_gr_surface_layout(uint64_t allocation,uint32_t offset,uint32_t delta,
    uint64_t descriptor,uint64_t *size,uint32_t *pixels)
{
    if(!size || !pixels || !allocation || allocation>RF_GR_BUFFER_MAX || offset>=allocation ||
        delta>=RF_GR_HOST_PAGE)return false;
    uint64_t length=(allocation+delta+RF_GR_HOST_PAGE-1)&~(uint64_t)(RF_GR_HOST_PAGE-1);
    uint64_t start=(uint64_t)offset+delta;
    if(length>RF_GR_BUFFER_MAX || descriptor<length || start>=length || start>UINT32_MAX)return false;
    *size=length;*pixels=(uint32_t)start;return true;
}
/* Preferred RedwoodGPU's seed/4ms fallback. A client-mapped surface must
 * still be pushed on every submission; not every CPU writer bumps a seed. */
struct rf_gr_surface_cache {uint64_t pushed;uint32_t seed;bool initialized;};
static inline bool rf_gr_surface_push(struct rf_gr_surface_cache *cache,uint32_t seed,
    uint64_t now,uint64_t interval,bool client_mapped)
{
    if(!cache || !interval)return true;
    if(cache->initialized && !client_mapped && seed==cache->seed && now>=cache->pushed &&
        now-cache->pushed<interval)return false;
    cache->pushed=now;cache->seed=seed;cache->initialized=true;return true;
}

static inline bool rf_gr_span(uint64_t size,uint64_t *span)
{
    if(!size || size>RF_GR_BUFFER_MAX)return false;
    *span=((size+RF_GR_GRANULE-1)&~(RF_GR_GRANULE-1))+RF_GR_GRANULE;
    return true;
}
/* First fit without an allocatable free-list that could lose a returned hole. */
static inline uint64_t rf_gr_allocate(struct rf_gr_arena *a,uint64_t size)
{
    uint64_t span,at=RF_GR_BASE;unsigned free_slot=RF_GR_OBJECTS;
    if(!a || !rf_gr_span(size,&span) || a->bytes>RF_GR_MEMORY_MAX-size)return 0;
    for(unsigned i=0;i<RF_GR_OBJECTS;i++)if(!a->objects[i].address){free_slot=i;break;}
    if(free_slot==RF_GR_OBJECTS)return 0;
    for(unsigned pass=0;pass<=RF_GR_OBJECTS;pass++) {
        if(at>RF_GR_BASE+RF_GR_BYTES-span)return 0;
        uint64_t next=at;
        for(unsigned i=0;i<RF_GR_OBJECTS;i++) {
            const struct rf_gr_object *o=&a->objects[i];
            if(o->address && at<o->address+o->span && o->address<at+span && next<o->address+o->span)
                next=o->address+o->span;
        }
        if(next==at){a->objects[free_slot]=(struct rf_gr_object){at,size,span};a->bytes+=size;return at;}
        at=next;
    }
    return 0;
}
static inline const struct rf_gr_object *rf_gr_find(const struct rf_gr_arena *a,uint64_t at,uint64_t bytes)
{
    if(!a || !bytes || at>UINT64_MAX-bytes)return NULL;
    for(unsigned i=0;i<RF_GR_OBJECTS;i++) {
        const struct rf_gr_object *o=&a->objects[i];
        if(o->address && at>=o->address && at-o->address<=o->size && bytes<=o->size-(at-o->address))return o;
    }
    return NULL;
}
static inline bool rf_gr_release(struct rf_gr_arena *a,uint64_t at,uint64_t size)
{
    if(!a)return false;
    for(unsigned i=0;i<RF_GR_OBJECTS;i++)if(a->objects[i].address==at && a->objects[i].size==size) {
        a->bytes-=size;a->objects[i]=(struct rf_gr_object){0};return true;
    }
    return false;
}
/* Native TYPE7 parity, CP_INDIRECT_BUFFER followed by a real cache-flush fence. */
static inline uint32_t rf_gr_parity(uint32_t v)
{v^=v>>16;v^=v>>8;v^=v>>4;v^=v>>2;v^=v>>1;return (~v)&1u;}
static inline uint32_t rf_gr_type7(unsigned op,unsigned words)
{return 0x70000000u|(op<<16)|(rf_gr_parity(op)<<23)|words|(rf_gr_parity(words)<<15);}
static inline unsigned rf_gr_submit_words(const struct rf_gr_arena *a,const uint64_t *addresses,
    const uint32_t *words,unsigned count,uint32_t fence,uint32_t *out,unsigned room)
{
    if(!a || !addresses || !words || !count || count>RF_GR_COMMANDS || !fence || !out || room<4*count+10)return 0;
    for(unsigned i=0;i<count;i++)if((addresses[i]&3u) || !words[i] || words[i]>0xfffffu ||
        !rf_gr_find(a,addresses[i],(uint64_t)words[i]*4))return 0;
    unsigned n=0;
    out[n++]=rf_gr_type7(0x46,1);out[n++]=0x18; /* Invalidate depth/color state, native a6xx_submit. */
    out[n++]=rf_gr_type7(0x46,1);out[n++]=0x19;
    for(unsigned i=0;i<count;i++) {
        out[n++]=rf_gr_type7(0x3f,3);out[n++]=(uint32_t)addresses[i];
        out[n++]=(uint32_t)(addresses[i]>>32);out[n++]=words[i];
    }
    out[n++]=rf_gr_type7(0x26,0);
    out[n++]=rf_gr_type7(0x46,4);out[n++]=4;
    out[n++]=0x01200000u+RF_GR_FENCE_AT;out[n++]=0;out[n++]=fence;
    return n;
}
#endif
