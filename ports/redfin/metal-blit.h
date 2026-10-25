/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_BLIT_H
#define REDFIN_METAL_BLIT_H
#include <stdint.h>
#include <stddef.h>
enum {RF_BLIT_BUFFER=1,RF_BLIT_FILL,RF_BLIT_TEXTURE,RF_BLIT_UPLOAD,
      RF_BLIT_DOWNLOAD,RF_BLIT_MIPMAP,RF_BLIT_SYNC,RF_BLIT_INVALID};
struct redfin_metal_blit {
    uint32_t operation,fill_value;
    uint64_t options,source_offset,destination_offset,row_bytes,image_bytes;
    uint64_t source_origin[3],destination_origin[3],size[3];
    uint64_t source_level,destination_level,source_slice,destination_slice;
};
#if defined(__cplusplus)
static_assert(sizeof(redfin_metal_blit)==152,"paired native Metal blit ABI");
#else
_Static_assert(sizeof(struct redfin_metal_blit)==152,"paired native Metal blit ABI");
#endif
struct rwa_device;struct rwa_buffer;struct rwa_texture;
int rwa_redfin_blit(struct rwa_device *,struct rwa_buffer *,struct rwa_buffer *,
    struct rwa_texture *,struct rwa_texture *,const struct redfin_metal_blit *,char *,size_t);
#endif
