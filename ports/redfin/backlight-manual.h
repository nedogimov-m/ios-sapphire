/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_BACKLIGHT_MANUAL_H
#define REDFIN_BACKLIGHT_MANUAL_H
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
/* UIKit/BKS logical input maps to the published normal DBV range. This does
 * not supply a measured luminance curve, HBM, ALS, HDR or electrical limits. */
static inline bool redfin_manual_backlight_level(float value,uint32_t *dbv)
{
    if(!dbv||!isfinite(value)||value<0||value>1)return false;
    *dbv=(uint32_t)lround((double)value*(1023-4))+4;
    return true;
}
#endif
