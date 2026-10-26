/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GPU_ACCESS_H
#define REDFIN_GPU_ACCESS_H
#include <stdbool.h>
#ifndef REDFIN_GPU_SCOPE_H
#include "redfin_gpu_scope.h"
#endif

/* Keep scoped ABI1 intact. Only this separately negotiated selector gives
 * the old range.reserved word its READ/WRITE meaning; zero means unknown. */
#define RF_GA_ABI 1u
#define RF_GA_PARAM 0x52465133u
#define RF_GA_SUBMIT 0x52465333u
#define RF_GA_READ 1u
#define RF_GA_WRITE 2u
#define RF_GA_RW (RF_GA_READ|RF_GA_WRITE)
#define RF_GA_LINE_BYTES 64u
#define RF_GA_LINES (RF_GW_PAGE_BYTES/RF_GA_LINE_BYTES)
#define RF_GA_FINE_PAGES 8192u

/* Full-page operations stay O(pages). Only partially accessed pages consume
 * a fine slot. Exhausting this fixed pool keeps the conservative page wait.
 * The same physical aliases share both read/write histories and fine slots. */
struct rf_ga_fine {
    uint64_t base_use,base_write;
    uint64_t use[RF_GA_LINES],write[RF_GA_LINES];
};
struct rf_ga_history {
    uint64_t *use,*write;
    uint32_t *fine_index;
    struct rf_ga_fine *fine;
    uint32_t capacity,allocated;
    uint64_t partial_marks,fine_queries,fallbacks;
};
static inline bool rf_ga_valid(const struct rf_ga_history *h)
{
    return h&&h->use&&h->write&&h->fine_index&&h->capacity<=RF_GA_FINE_PAGES&&
        h->allocated<=h->capacity&&(!h->capacity||h->fine);
}
static inline int rf_ga_validate(const struct rf_ga_history *h,const uint32_t *pages,
    uint32_t count,uint64_t offset,uint64_t bytes,uint64_t size,uint32_t *first,uint32_t *needed)
{
    if(!rf_ga_valid(h)||!pages||rf_gw_span(offset,bytes,size,first,needed)||
       *first>count||*needed>count-*first)return EINVAL;
    for(uint32_t i=*first;i<*first+*needed;++i)
        if(pages[i]>=RF_GW_PAGES||h->fine_index[pages[i]]>h->allocated)return EINVAL;
    return 0;
}
static inline void rf_ga_max(uint64_t *value,uint64_t sequence)
{if(*value<sequence)*value=sequence;}
static inline void rf_ga_mark_page(struct rf_ga_history *h,uint32_t page,
    unsigned begin,unsigned end,uint64_t sequence,unsigned access)
{
    uint32_t slot=h->fine_index[page];
    bool partial=begin||end!=RF_GW_PAGE_BYTES;
    if(partial&&!slot&&h->allocated<h->capacity) {
        slot=++h->allocated;h->fine_index[page]=slot;
        /* The pre-zeroed slot has never been used. Earlier coarse history
         * becomes a baseline; never reinterpret it as a narrower access. */
        h->fine[slot-1].base_use=h->use[page];
        h->fine[slot-1].base_write=h->write[page];
    }
    rf_ga_max(&h->use[page],sequence);
    if(access&RF_GA_WRITE)rf_ga_max(&h->write[page],sequence);
    if(!partial) {
        if(slot) {
            rf_ga_max(&h->fine[slot-1].base_use,sequence);
            if(access&RF_GA_WRITE)rf_ga_max(&h->fine[slot-1].base_write,sequence);
        }
        return;
    }
    ++h->partial_marks;
    if(!slot){++h->fallbacks;return;}
    struct rf_ga_fine *fine=&h->fine[slot-1];
    unsigned first=begin/RF_GA_LINE_BYTES,last=(end-1)/RF_GA_LINE_BYTES;
    for(unsigned i=first;i<=last;++i) {
        rf_ga_max(&fine->use[i],sequence);
        if(access&RF_GA_WRITE)rf_ga_max(&fine->write[i],sequence);
    }
}
static inline int rf_ga_mark_span(struct rf_ga_history *h,const uint32_t *pages,uint32_t count,
    uint64_t offset,uint64_t bytes,uint64_t size,uint64_t sequence,unsigned access)
{
    uint32_t first=0,needed=0;
    if(!sequence||!access||(access&~RF_GA_RW)||
       rf_ga_validate(h,pages,count,offset,bytes,size,&first,&needed))return EINVAL;
    uint64_t end=offset+bytes;
    for(uint32_t i=first;i<first+needed;++i) {
        uint64_t base=(uint64_t)i*RF_GW_PAGE_BYTES;
        unsigned begin=offset>base?(unsigned)(offset-base):0;
        unsigned limit=end-base<RF_GW_PAGE_BYTES?(unsigned)(end-base):RF_GW_PAGE_BYTES;
        rf_ga_mark_page(h,pages[i],begin,limit,sequence,access);
    }
    return 0;
}
static inline int rf_ga_mark_pages(struct rf_ga_history *h,const uint32_t *pages,
    uint32_t count,uint64_t sequence,unsigned access)
{
    if(!rf_ga_valid(h)||!pages||!count||!sequence||!access||(access&~RF_GA_RW))return EINVAL;
    for(uint32_t i=0;i<count;++i)
        if(pages[i]>=RF_GW_PAGES||h->fine_index[pages[i]]>h->allocated)return EINVAL;
    for(uint32_t i=0;i<count;++i)rf_ga_mark_page(h,pages[i],0,RF_GW_PAGE_BYTES,sequence,access);
    return 0;
}
static inline int rf_ga_target(struct rf_ga_history *h,const uint32_t *pages,uint32_t count,
    uint64_t offset,uint64_t bytes,uint64_t size,unsigned op,uint64_t *target)
{
    uint32_t first=0,needed=0;
    if(!target||(op&~7u)||rf_ga_validate(h,pages,count,offset,bytes,size,&first,&needed))return EINVAL;
    bool read_only=(op&RF_GA_RW)==RF_GA_READ;
    uint64_t last=0,end=offset+bytes;
    for(uint32_t i=first;i<first+needed;++i) {
        uint32_t page=pages[i],slot=h->fine_index[page];
        uint64_t base=(uint64_t)i*RF_GW_PAGE_BYTES;
        unsigned begin=offset>base?(unsigned)(offset-base):0;
        unsigned limit=end-base<RF_GW_PAGE_BYTES?(unsigned)(end-base):RF_GW_PAGE_BYTES;
        if(!slot||(!begin&&limit==RF_GW_PAGE_BYTES)) {
            rf_ga_max(&last,read_only?h->write[page]:h->use[page]);continue;
        }
        ++h->fine_queries;
        const struct rf_ga_fine *fine=&h->fine[slot-1];
        rf_ga_max(&last,read_only?fine->base_write:fine->base_use);
        unsigned lo=begin/RF_GA_LINE_BYTES,hi=(limit-1)/RF_GA_LINE_BYTES;
        for(unsigned n=lo;n<=hi;++n)rf_ga_max(&last,read_only?fine->write[n]:fine->use[n]);
    }
    *target=last;return 0;
}
static inline unsigned rf_ga_access(unsigned bo_flags,unsigned range_flags,bool typed)
{
    unsigned access=typed&&range_flags?range_flags:bo_flags&RF_GA_RW;
    return access?access:RF_GA_RW;
}
#endif
