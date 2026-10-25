/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_LINEAR_IMPORT_H
#define REDFIN_METAL_LINEAR_IMPORT_H
#include <stdbool.h>
#include <stdint.h>
struct pipe_screen;
struct pipe_resource;
struct pipe_context;
struct pipe_blit_info;
struct pipe_resource *redfin_freedreno_import_buffer(struct pipe_screen *,unsigned);
struct pipe_resource *redfin_freedreno_buffer_alias(struct pipe_screen *,struct pipe_resource *,unsigned *,unsigned *);
struct pipe_resource *redfin_freedreno_texture_alias(struct pipe_screen *,struct pipe_resource *,const struct pipe_resource *,unsigned,unsigned);
int redfin_freedreno_alias_written(struct pipe_context *,struct pipe_resource *);
int redfin_freedreno_gpu_blit(struct pipe_context *,const struct pipe_blit_info *);
int redfin_freedreno_gpu_fill(struct pipe_context *,struct pipe_resource *,unsigned,unsigned,uint8_t);

/* Bounds for the actual native layout, not a claim about sampler support.
 * V18 hardware rounds 480/4512-byte source rows to 512/4544. GPU buffer
 * copies convert them to/from a genuinely aligned native texture. */
static inline bool redfin_linear_layout_fits(uint32_t width,uint32_t height,
    uint32_t cpp,uint32_t pitch,uint64_t offset,uint64_t bytes)
{
    if(!width||!height||!cpp||cpp>16||(cpp&(cpp-1))||!pitch||
       pitch%cpp||(pitch&3)||(offset&3)||width>pitch/cpp||offset>bytes)return false;
    uint64_t rows=(uint64_t)pitch*height;
    return rows<=UINT32_MAX&&rows<=bytes-offset;
}
struct redfin_linear_copy_plan {
    uint32_t words,rows,source_pitch,destination_pitch,source_offset,destination_offset;
};
#if defined(__cplusplus)
static_assert(sizeof(redfin_linear_copy_plan)==24,"native GPU copy constants");
#else
_Static_assert(sizeof(struct redfin_linear_copy_plan)==24,"native GPU copy constants");
#endif
static inline bool redfin_linear_copy_plan_make(struct redfin_linear_copy_plan *plan,
    uint32_t pixel_bytes,uint32_t rows,uint32_t source_pitch,uint32_t destination_pitch,
    uint64_t source_offset,uint64_t destination_offset,uint64_t source_bytes,uint64_t destination_bytes)
{
    if(!plan||!pixel_bytes||pixel_bytes>UINT32_MAX-3||!rows||
       (source_pitch&3)||(destination_pitch&3)||(source_offset&3)||(destination_offset&3)||
       source_offset>UINT32_MAX||destination_offset>UINT32_MAX)return false;
    uint32_t words=(pixel_bytes+3)/4;
    if(words>source_pitch/4||words>destination_pitch/4||
       source_offset>source_bytes||destination_offset>destination_bytes)return false;
    uint64_t source_end=(uint64_t)(rows-1)*source_pitch+(uint64_t)words*4;
    uint64_t destination_end=(uint64_t)(rows-1)*destination_pitch+(uint64_t)words*4;
    if(source_end>UINT32_MAX-source_offset||destination_end>UINT32_MAX-destination_offset||
       source_end>source_bytes-source_offset||destination_end>destination_bytes-destination_offset)return false;
    *plan=(struct redfin_linear_copy_plan){words,rows,source_pitch,destination_pitch,
        (uint32_t)source_offset,(uint32_t)destination_offset};
    return true;
}
#endif
