/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GPU_SCOPE_H
#define REDFIN_GPU_SCOPE_H
#include <stdint.h>
#include <stddef.h>
#include <sys/errno.h>

/* Same owned physical window as redfin_gmu_pagetables.h. GPU aliases have
 * distinct handles/VAs but share this physical retirement history. Entries
 * are never cleared on close: retained jobs prevent premature page reuse. */
#define RF_GW_RAM_BASE UINT64_C(0x180000000)
#define RF_GW_RAM_BYTES UINT64_C(0x80000000)
#define RF_GW_PAGE_BYTES 4096u
#define RF_GW_PAGES (RF_GW_RAM_BYTES/RF_GW_PAGE_BYTES)
#define RF_GW_ABI 1u
#define RF_GW_PARAM 0x52465132u
#define RF_GW_CPU_RANGE 0x52464350u
#define RF_GW_SUBMIT 0x52465352u
#define RF_GW_MAX_BOS 1024u
#define RF_GW_MAX_RANGES 8192u
struct rf_gw_submit_range {uint32_t bo,reserved;uint64_t offset,bytes;};
struct rf_gw_submit_extension {uint64_t ranges;uint32_t count,reserved;};
struct rf_gw_cpu_range {
    uint32_t handle,op;
    uint64_t offset,bytes;
    int64_t seconds,nanoseconds;
};
#ifdef __cplusplus
static_assert(sizeof(struct rf_gw_cpu_range)==40,"scoped CPU preparation ABI");
#else
_Static_assert(sizeof(struct rf_gw_cpu_range)==40,"scoped CPU preparation ABI");
#endif
static inline int rf_gw_index(uint64_t physical,uint32_t *index)
{
    if(!index || (physical&(RF_GW_PAGE_BYTES-1)) || physical<RF_GW_RAM_BASE ||
       physical-RF_GW_RAM_BASE>=RF_GW_RAM_BYTES)return EINVAL;
    *index=(uint32_t)((physical-RF_GW_RAM_BASE)/RF_GW_PAGE_BYTES);return 0;
}
static inline int rf_gw_span(uint64_t offset,uint64_t bytes,uint64_t size,
    uint32_t *first,uint32_t *count)
{
    if(!first||!count||!bytes||offset>size||bytes>size-offset||
       size>RF_GW_RAM_BYTES)return EINVAL;
    *first=(uint32_t)(offset/RF_GW_PAGE_BYTES);
    *count=(uint32_t)((offset+bytes-1)/RF_GW_PAGE_BYTES)-*first+1;return 0;
}
/* The existing queue lock serializes these CPU-only bounded arrays. Validate
 * before modifying anything, including a private-metadata corruption case. */
static inline int rf_gw_mark(uint64_t *history,const uint32_t *pages,uint32_t count,uint64_t sequence)
{
    if(!history||!pages||!count||!sequence)return EINVAL;
    for(uint32_t i=0;i<count;++i)if(pages[i]>=RF_GW_PAGES)return EINVAL;
    for(uint32_t i=0;i<count;++i)if(history[pages[i]]<sequence)history[pages[i]]=sequence;
    return 0;
}
static inline int rf_gw_target(const uint64_t *history,const uint32_t *pages,uint32_t count,
    uint64_t offset,uint64_t bytes,uint64_t size,uint64_t *target)
{
    uint32_t first=0,needed=0;
    if(!history||!pages||!target||rf_gw_span(offset,bytes,size,&first,&needed)||
       first>count||needed>count-first)return EINVAL;
    uint64_t last=0;
    for(uint32_t i=first;i<first+needed;++i) {
        if(pages[i]>=RF_GW_PAGES)return EINVAL;
        if(history[pages[i]]>last)last=history[pages[i]];
    }
    *target=last;return 0;
}
static inline int rf_gw_mark_span(uint64_t *history,const uint32_t *pages,uint32_t count,
    uint64_t offset,uint64_t bytes,uint64_t size,uint64_t sequence)
{
    uint32_t first=0,needed=0;
    if(!pages||rf_gw_span(offset,bytes,size,&first,&needed)||first>count||needed>count-first)
        return EINVAL;
    return rf_gw_mark(history,pages+first,needed,sequence);
}
#endif
