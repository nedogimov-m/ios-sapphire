/* SPDX-License-Identifier: MIT */
/* Paired Metal/AIR draw state. Explicit dimensions and clipping are part of
 * each recorded draw, including every draw deferred until command commit. */
#ifndef REDFIN_METAL_RASTER_H
#define REDFIN_METAL_RASTER_H
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
struct redfin_metal_raster_state {
    double viewport[6]; /* origin x/y, width/height, near/far */
    uint64_t scissor[4];
    float blend_color[4],depth_bias,slope_scale,bias_clamp;
    uint32_t flags,cull,winding,fill,depth_clip;
};
#if defined(__cplusplus)
static_assert(sizeof(redfin_metal_raster_state)==128,"paired native raster ABI");
#else
_Static_assert(sizeof(struct redfin_metal_raster_state)==128,"paired native raster ABI");
#endif
static inline bool redfin_metal_raster_valid(const struct redfin_metal_raster_state *s)
{
    if(!s)return true;
    if((s->flags&~3u)||s->cull>2||s->winding>1||s->fill>1||s->depth_clip>1)return false;
    for(unsigned i=0;i<4;++i)if(!isfinite(s->blend_color[i]))return false;
    if(!isfinite(s->depth_bias)||!isfinite(s->slope_scale)||!isfinite(s->bias_clamp))return false;
    if(s->flags&1u) {
        for(unsigned i=0;i<6;++i)if(!isfinite(s->viewport[i])||fabs(s->viewport[i])>16777216.0)return false;
        if(s->viewport[2]<0||s->viewport[3]<0||s->viewport[4]<0||s->viewport[4]>1||
           s->viewport[5]<0||s->viewport[5]>1)return false;
    }
    if(s->flags&2u)for(unsigned i=0;i<2;++i)
        if(s->scissor[i]>UINT32_MAX||s->scissor[i+2]>UINT32_MAX-s->scissor[i])return false;
    return true;
}
static inline void redfin_metal_scissor(const struct redfin_metal_raster_state *s,
    uint32_t width,uint32_t height,uint32_t rect[4])
{
    rect[0]=rect[1]=0;rect[2]=width;rect[3]=height;
    if(!s||!(s->flags&2u))return;
    uint64_t right=s->scissor[0]+s->scissor[2],bottom=s->scissor[1]+s->scissor[3];
    rect[0]=s->scissor[0]<width?(uint32_t)s->scissor[0]:width;
    rect[1]=s->scissor[1]<height?(uint32_t)s->scissor[1]:height;
    rect[2]=right<width?(uint32_t)right:width;rect[3]=bottom<height?(uint32_t)bottom:height;
}
#endif
