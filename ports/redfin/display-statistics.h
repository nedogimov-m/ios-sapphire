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
