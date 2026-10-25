/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_STATISTICS_H
#define REDFIN_DISPLAY_STATISTICS_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/* A read-only private capture query. Include the common GUI profile first.
 * Presents are incremented only after the actual panel copy/GPU fence.
 * Notification ticks and CADisplayLink callbacks are never counted here. */
#define REDFIN_DISPLAY_STATISTICS_SELECTOR 0x52465053u
struct redfin_display_statistics {
    uint32_t version,bytes;
    uint64_t ticks,presents,gpu_presents;
    uint32_t panel_hz,reserved;
};
#ifdef __cplusplus
static_assert(sizeof(struct redfin_display_statistics)==40,"native capture statistics ABI");
#else
_Static_assert(sizeof(struct redfin_display_statistics)==40,"native capture statistics ABI");
#endif

static inline bool redfin_display_statistics_admit(const char *args,unsigned bytes,uint64_t requested)
{
    uint64_t nonce=0;
    if (!requested || !redfin_gpu_gui_profile(args,bytes,&nonce) || nonce!=requested) return false;
    for (unsigned at=0;at<bytes && args[at];) {
        if (args[at]==' ') {++at;continue;}
        unsigned first=at;
        while (at<bytes && args[at] && args[at]!=' ') ++at;
        if (redfin_gui_token(args+first,at-first,"redfinscreen=1")) return true;
    }
    return false;
}
static inline bool redfin_display_statistics_valid(const struct redfin_display_statistics *s)
{
    return s && s->version==1 && s->bytes==sizeof(*s) && s->ticks &&
        s->gpu_presents<=s->presents && !s->reserved && (s->panel_hz==60 || s->panel_hz==90);
}
#endif
