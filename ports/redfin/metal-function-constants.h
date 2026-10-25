/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_FUNCTION_CONSTANTS_H
#define REDFIN_METAL_FUNCTION_CONSTANTS_H
#include <stdint.h>
#include <stddef.h>
#define REDFIN_METAL_CONSTANTS_MAX 512u
/* Little-endian scalar/vector payload, without C vector padding. A Metal
 * function owns an immutable snapshot; the compiler consumes it synchronously. */
struct redfin_metal_constant {uint32_t index,bytes;uint64_t words[4];};
struct redfin_metal_constants {const struct redfin_metal_constant *values;uint32_t count,reserved;};
struct rwa_device;struct rwa_compute;struct rwa_compute_info;struct rwa_render;
struct rwa_render_shape;struct rwa_render_info;struct rwa_argbuf_layout;struct rwa_texture_decl;
struct rwa_compute *rwa_redfin_compute_create(struct rwa_device *,const void *,size_t,const char *,struct rwa_compute_info *,const struct redfin_metal_constants *,char *,size_t);
struct rwa_render *rwa_redfin_render_create(struct rwa_device *,const void *,size_t,const char *,const void *,size_t,const char *,const struct rwa_render_shape *,struct rwa_render_info *,const struct redfin_metal_constants *,const struct redfin_metal_constants *,char *,size_t);
int rwa_redfin_module_argbufs(struct rwa_device *,const void *,size_t,const char *,struct rwa_argbuf_layout *,unsigned,unsigned *,const struct redfin_metal_constants *,char *,size_t);
#endif
