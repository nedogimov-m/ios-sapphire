/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_BUFFER_IMPORT_H
#define REDFIN_METAL_BUFFER_IMPORT_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
struct rwa_device;struct rwa_buffer;struct rwa_texture;struct rwa_texture_shape;
struct rwa_buffer *rwa_redfin_buffer_from_surface(struct rwa_device *,unsigned,size_t,void *,char *,size_t);
int rwa_redfin_texture_buffer_link(struct rwa_texture *,struct rwa_buffer *,uint64_t,uint64_t,char *,size_t);
struct rwa_texture *rwa_redfin_texture_from_buffer(struct rwa_device *,struct rwa_buffer *,const struct rwa_texture_shape *,uint64_t,uint64_t,char *,size_t);
/* R32 IBO descriptors must include the real final dword for byte/halfword
 * stores. This padding is allocated; Metal's public length stays unchanged. */
static inline bool redfin_buffer_extent(size_t logical,uint32_t *allocated)
{
    if(!allocated||!logical||logical>UINT32_MAX-3)return false;
    *allocated=(uint32_t)((logical+3)&~(size_t)3);return true;
}
#endif
