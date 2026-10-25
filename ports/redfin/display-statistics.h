/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_STATISTICS_H
#define REDFIN_DISPLAY_STATISTICS_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/* A read-only private presentation query. Include the common GUI profile first.
 * Presents are incremented only after the actual panel copy/GPU fence.
 * Notification ticks and CADisplayLink callbacks are never counted here. */
#define REDFIN_DISPLAY_STATISTICS_SELECTOR 0x52465053u
#define REDFIN_DISPLAY_STATISTICS_SELECTOR_V2 0x52465054u
struct redfin_display_statistics {
    uint32_t version,bytes;
    uint64_t ticks,presents,gpu_presents;
    uint32_t panel_hz,reserved;
};
/* Preserve v1 for earlier observers. v2 also reports the hardware counter
 * frequency, so frame rates do not silently trust a guessed timebase. */
struct redfin_display_statistics_v2 {
    uint32_t version,bytes;
    uint64_t ticks,presents,gpu_presents;
    uint32_t panel_hz,reserved;
    uint64_t counter_hz;
};
/* One existing serialized presenter publishes only after real completion.
 * Readers never depend on the optional image-capture lock or wait for DMA.
 * An even sequence brackets one consistent CPU/GPU pair. All shared accesses
 * are atomic, including a read that overlaps the writer. */
struct redfin_display_statistics_state {
    uint64_t sequence,presents,gpu_presents;
};
static inline void redfin_display_statistics_record(struct redfin_display_statistics_state *s,bool gpu)
{
    __atomic_fetch_add(&s->sequence,1,__ATOMIC_ACQ_REL);
    __atomic_fetch_add(&s->presents,1,__ATOMIC_RELAXED);
    if(gpu)__atomic_fetch_add(&s->gpu_presents,1,__ATOMIC_RELAXED);
    __atomic_fetch_add(&s->sequence,1,__ATOMIC_RELEASE);
}
static inline bool redfin_display_statistics_read(const struct redfin_display_statistics_state *s,
    uint64_t *presents,uint64_t *gpu)
{
    if(!s||!presents||!gpu)return false;
    for(unsigned attempt=0;attempt<4;++attempt) {
        uint64_t before=__atomic_load_n(&s->sequence,__ATOMIC_ACQUIRE);
        if(before&1u)continue;
        uint64_t completed=__atomic_load_n(&s->presents,__ATOMIC_RELAXED);
        uint64_t accelerated=__atomic_load_n(&s->gpu_presents,__ATOMIC_RELAXED);
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if(before==__atomic_load_n(&s->sequence,__ATOMIC_RELAXED)) {
            *presents=completed;*gpu=accelerated;return true;
        }
    }
    return false;
}
#ifdef __cplusplus
static_assert(sizeof(struct redfin_display_statistics)==40,"native capture statistics ABI");
static_assert(sizeof(struct redfin_display_statistics_v2)==48,"physical counter statistics ABI");
#else
_Static_assert(sizeof(struct redfin_display_statistics)==40,"native capture statistics ABI");
_Static_assert(sizeof(struct redfin_display_statistics_v2)==48,"physical counter statistics ABI");
#endif

static inline bool redfin_display_statistics_admit(const char *args,unsigned bytes,uint64_t requested)
{
    uint64_t nonce=0;
    if (!requested || !redfin_gpu_gui_profile(args,bytes,&nonce) || nonce!=requested) return false;
    /* Reading counters never starts a capture or submits a frame. Ordinary
     * nonce-bound GUI3 boots need this observer without heavy image reads. */
    return true;
}
static inline bool redfin_display_statistics_valid(const struct redfin_display_statistics *s)
{
    return s && s->version==1 && s->bytes==sizeof(*s) && s->ticks &&
        s->gpu_presents<=s->presents && !s->reserved && (s->panel_hz==60 || s->panel_hz==90);
}
static inline bool redfin_display_statistics_valid_v2(const struct redfin_display_statistics_v2 *s)
{
    if(!s||s->version!=2||s->bytes!=sizeof(*s)||s->counter_hz<1000000||s->counter_hz>1000000000)return false;
    struct redfin_display_statistics base={1,sizeof(base),s->ticks,s->presents,s->gpu_presents,s->panel_hz,s->reserved};
    return redfin_display_statistics_valid(&base);
}
#endif
