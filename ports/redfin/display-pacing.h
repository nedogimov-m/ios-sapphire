/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_PACING_H
#define REDFIN_DISPLAY_PACING_H
#include <stdint.h>

/* Advance the previous absolute phase, skipping elapsed periods without
 * accumulating the time spent presenting into the next notification delay. */
static inline uint64_t
redfin_display_next_tick(uint64_t previous, uint64_t now, uint64_t period,
    uint64_t *skipped)
{
    if (skipped) *skipped = 0;
    if (!period) return 0;
    if (!previous) return now > UINT64_MAX - period ? 0 : now + period;
    if (previous > now) return previous;
    uint64_t count = (now - previous) / period;
    if (count == UINT64_MAX || ++count > (UINT64_MAX - previous) / period) return 0;
    if (skipped) *skipped = count - 1;
    return previous + count * period;
}
#endif
