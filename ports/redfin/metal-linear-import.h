/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_LINEAR_IMPORT_H
#define REDFIN_METAL_LINEAR_IMPORT_H
#include <stdbool.h>
#include <stdint.h>

/* Private paired AIR/freedreno import. A6xx samplers carry a byte pitch;
 * RB_MRT_PITCH discards its low six bits. Unaligned imports are read-only
 * shader inputs, never framebuffer or storage-image destinations. */
#define REDFIN_LINEAR_SAMPLER_USAGE (1u << 31)
static inline bool redfin_linear_sampler_fits(uint32_t width,uint32_t height,
    uint32_t cpp,uint32_t pitch,uint64_t offset,uint64_t bytes)
{
    if(!width||!height||!cpp||cpp>16||(cpp&(cpp-1))||!pitch||pitch>0x3fffff||
       pitch%cpp||(offset&31)||width>pitch/cpp||offset>bytes)return false;
    uint64_t rows=(uint64_t)pitch*height;
    return rows<=UINT32_MAX&&rows<=bytes-offset;
}
#endif
