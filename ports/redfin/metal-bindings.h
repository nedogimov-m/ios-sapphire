/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_BINDINGS_H
#define REDFIN_METAL_BINDINGS_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#define REDFIN_METAL_BINDING_WORDS 12u
struct rwa_device;
/* Requests, descriptor calls/skips, constant refreshes, cleared stale slots,
 * stage cleanups, graphics calls/skips, vertex calls/skips, live stage slots,
 * live vertex references. Readonly; never submits or waits. */
__attribute__((visibility("default"))) int rwa_redfin_binding_statistics(struct rwa_device *,uint64_t *,size_t);
#ifdef REDFIN_METAL_BINDINGS_RUNTIME
/* Private native state, bounded by Gallium slots and cleared at every scope
 * exit. Resources/views own references; sampler CSOs are forgotten before
 * their owning pipeline or sampler can delete them. */
struct redfin_metal_stage_bindings {
   struct pipe_shader_buffer buffers[PIPE_MAX_SHADER_BUFFERS];
   struct pipe_sampler_view *views[16];
   struct pipe_image_view images[16];
   void *samplers[16];
   unsigned constants,writable,num_buffers,num_views,num_images,num_samplers;
};
enum redfin_metal_cso {RF_BIND_BLEND,RF_BIND_DSA,RF_BIND_RASTER,RF_BIND_VS,RF_BIND_FS,RF_BIND_VELEM,RF_BIND_CSO_COUNT};
struct redfin_metal_graphics_bindings {
   void *cso[RF_BIND_CSO_COUNT];
   unsigned valid;
   struct pipe_vertex_buffer vertices[PIPE_MAX_ATTRIBS];
   unsigned num_vertices;
   bool vertices_valid,vertices_required;
   struct pipe_viewport_state viewport;
   struct pipe_scissor_state scissor;
   struct pipe_blend_color blend;
   struct pipe_stencil_ref stencil;
   unsigned dynamic_valid;
};
#endif
#endif
