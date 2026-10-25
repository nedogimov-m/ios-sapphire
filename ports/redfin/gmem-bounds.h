/* SPDX-License-Identifier: MIT */
/* Mesa25.0.7 fd6_layout.c reserves a 16x4 transfer footprint for the final
 * linear level. Imported IOSurface storage may end before the padded rows.
 * Such an attachment must use real GPU sysmem rendering, even with a debug
 * GMEM request. Never grant DMA access to a guard or another owner's memory. */
#ifndef REDFIN_GMEM_BOUNDS_H
#define REDFIN_GMEM_BOUNDS_H
#include <stdint.h>
#include <stdbool.h>
static inline bool redfin_linear_gmem_fits(uint64_t allocation,uint64_t offset,
    uint64_t pitch,uint32_t rows)
{
    if(!pitch||!rows||offset>allocation)return false;
    uint64_t padded=((uint64_t)rows+3)&~UINT64_C(3);
    return padded<=UINT64_MAX/pitch&&padded*pitch<=allocation-offset;
}
#endif
