/* SPDX-License-Identifier: MIT */
/* Actual20H392 IOMobileFramebuffer afd11f8e008f3276bd72c0e0d96cffa6 ABI. */
#ifndef REDFIN_DISPLAY_MODE_H
#define REDFIN_DISPLAY_MODE_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

struct redfin_display_refresh_parameters {
    uint32_t minimum_interval_32_32,step_mach_ticks;
};
static inline bool redfin_display_refresh_parameters(uint32_t hz,uint64_t clock_hz,
    struct redfin_display_refresh_parameters *out)
{
    if(!out||(hz!=60&&hz!=90)||clock_hz<1000000||clock_hz>1000000000)return false;
    uint64_t interval=((UINT64_C(1)<<32)+hz/2)/hz,step=(clock_hz+hz/2)/hz;
    /* Both20H392 dictionary fields are read through signed CA_CFIntValue.
     * Minimum interval is32.32 seconds; the step is in real Mach ticks. */
    if(!interval||interval>INT32_MAX||!step||step>INT32_MAX)return false;
    struct redfin_display_refresh_parameters value={(uint32_t)interval,(uint32_t)step};
    *out=value;return true;
}

static inline void redfin_display_notification(uint64_t now,uint64_t count,uint64_t values[6])
{
    /* Native VsyncNotifyFunc decodes time, presentation-time, counter in this
     * order. A frame counter in the first pair is not an absolute timestamp. */
    values[0]=(uint32_t)now;values[1]=(uint32_t)(now>>32);
    values[2]=(uint32_t)now;values[3]=(uint32_t)(now>>32);
    values[4]=(uint32_t)count;values[5]=(uint32_t)(count>>32);
}
static inline bool redfin_display_current_mode(uint64_t block,uint64_t offset,
    void *output,size_t capacity)
{
    if (block!=0x40 || !output || !capacity || capacity>4096 || offset>40 || capacity>40-offset) return false;
    uint32_t native[10]={0,1,1,0,0,0,0,0,0,0}; /* current color/timing IDs */
    memcpy(output,(const uint8_t *)native+(size_t)offset,capacity);
    return true;
}
#endif
