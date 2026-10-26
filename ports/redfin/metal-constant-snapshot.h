/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_CONSTANT_SNAPSHOT_H
#define REDFIN_METAL_CONSTANT_SNAPSHOT_H
#include <stdbool.h>
#include <stdint.h>

struct pipe_resource;
/* Append-only GPU storage. A slice is never overwritten or returned to the
 * arena. Gallium batches retain old chunks through their real GPU retirement. */
struct redfin_metal_constant_arena {
   struct pipe_resource *resource;
   uint32_t offset;
   uint64_t grid_x;
   bool queried,supported;
};
#define REDFIN_METAL_GPU_SNAPSHOT_MIN (16u * 1024u)
#define REDFIN_METAL_GPU_SNAPSHOT_CHUNK (1024u * 1024u)
#endif
