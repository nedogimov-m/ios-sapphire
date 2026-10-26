/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_UBO_EXTENTS_H
#define REDFIN_METAL_UBO_EXTENTS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum { REDFIN_METAL_UBO_SLOTS=32 };
struct redfin_metal_ubo_extents {
   uint32_t bytes[REDFIN_METAL_UBO_SLOTS];
   bool unbounded[REDFIN_METAL_UBO_SLOTS];
};

/* An absent/unsupported proof never shortens a copy. Interface type size is
 * not an upper bound on a dynamically indexed Metal constant pointer. */
static inline size_t
redfin_metal_ubo_snapshot_bytes(const struct redfin_metal_ubo_extents *extents,
   unsigned slot,size_t remaining,bool *proven)
{
   if(proven)*proven=false;
   if(!extents||slot>=REDFIN_METAL_UBO_SLOTS||extents->unbounded[slot]||
      !extents->bytes[slot]||extents->bytes[slot]>remaining)return remaining;
   if(proven)*proven=true;
   return extents->bytes[slot];
}
#endif
