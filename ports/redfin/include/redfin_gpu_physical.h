/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GPU_PHYSICAL_H
#define REDFIN_GPU_PHYSICAL_H
#include <stdbool.h>
#include <stdint.h>
#include <sys/errno.h>
#include "redfin_gpu_runtime.h"

/* Two retained publications, four generation-owned timestamp slots. All
 * slots are within the actual owned4KiB native scratch page, after startup
 * proof words and the existing common cache-flush fence/timestamp fields. */
#define RF_GI_DEPTH 2u
#define RF_GI_SLOTS 4u
#define RF_GI_TIME_BASE 0x300u
#define RF_GI_TIME_STEP 32u
#define RF_GI_SCRATCH_BYTES 0x1000u

struct rf_gi_publication {uint32_t fence,ibs;uint64_t published_ns;};

static inline uint32_t rf_gi_time_offset(uint32_t fence)
{return RF_GI_TIME_BASE+(fence%RF_GI_SLOTS)*RF_GI_TIME_STEP;}

static inline bool rf_gi_ring_room(uint32_t read,uint32_t write,uint32_t capacity,uint32_t need)
{
    if(capacity<2||capacity>UINT32_MAX/2||read>=capacity||write>=capacity||!need||need>=capacity)return false;
    return (read+capacity-write-1)%capacity>=need;
}
static inline int rf_gi_counter(uint32_t issued,uint32_t completed,uint32_t observed,
    uint32_t target,bool *done)
{
    if(!done||completed>issued||target>issued||observed>issued||observed<completed)return EPROTO;
    *done=observed>=target;return 0;
}
static inline bool rf_gi_can_publish(uint32_t issued,uint32_t completed)
{return issued>=completed&&issued!=UINT32_MAX&&issued-completed<RF_GI_DEPTH;}

/* Reuse the exact validated native packet builder, changing only the two
 * private timestamp destinations. The common CACHE_FLUSH_TS fence stays
 * unchanged. Generation ownership prevents a later publication overwriting
 * a timestamp pair that has not actually been read after its GPU fence. */
static inline unsigned rf_gi_submit_words(const struct rf_gr_arena *arena,
    const uint64_t *addresses,const uint32_t *words,unsigned count,uint32_t fence,
    uint32_t *out,unsigned room)
{
    unsigned n=rf_gr_submit_words(arena,addresses,words,count,fence,out,room);
    if(!n||n!=4*count+18||out[2]!=0x01200000u+RF_GR_TIME_AT||
       out[n-7]!=0x01200000u+RF_GR_TIME_AT+8)return 0;
    uint32_t offset=rf_gi_time_offset(fence);
    if(offset<RF_GR_TIME_AT+16||offset>RF_GI_SCRATCH_BYTES-16)return 0;
    out[2]=0x01200000u+offset;out[n-7]=0x01200000u+offset+8;
    return n;
}
#endif
