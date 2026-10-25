/* SPDX-License-Identifier: MIT */
/* Actual20H392 IOMobileFramebuffer afd11f8e008f3276bd72c0e0d96cffa6 ABI. */
#ifndef REDFIN_DISPLAY_MODE_H
#define REDFIN_DISPLAY_MODE_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

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
