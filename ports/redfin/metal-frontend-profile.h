/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_FRONTEND_PROFILE_H
#define REDFIN_METAL_FRONTEND_PROFILE_H
#include <stddef.h>
#include <stdint.h>

/* Serialized frontend observations only. These never enter shader keys or
 * resource descriptors. Times are monotonic nanoseconds; counters accumulate
 * per device. CONSTANT_MAX_BYTES is an absolute maximum, not a delta. */
enum redfin_metal_frontend_field {
   RF_MFP_STAGE_CALLS, RF_MFP_STAGE_NS,
   RF_MFP_DRAW_CALLS, RF_MFP_DRAW_NS,
   RF_MFP_FRAMEBUFFER_NS, RF_MFP_DRAW_EMIT_NS,
   RF_MFP_CONSTANT_DIRECT, RF_MFP_CONSTANT_UPLOADS,
   RF_MFP_CONSTANT_BYTES, RF_MFP_CONSTANT_MAX_BYTES,
   RF_MFP_CONSTANT_UNKNOWN, RF_MFP_CONSTANT_UNKNOWN_BYTES,
   RF_MFP_CONSTANT_PREPARE_NS, RF_MFP_CONSTANT_UPLOAD_NS,
   RF_MFP_SUBMIT_CALLS, RF_MFP_SUBMIT_NS,
   RF_MFP_SUBMIT_CLEAR_NS, RF_MFP_SUBMIT_RESOLVE_NS,
   RF_MFP_CONSTANT_PROVEN, RF_MFP_CONSTANT_AVOIDED_BYTES, RF_MFP_CONSTANT_FALLBACK,
   RF_MFP_CONSTANT_GPU, RF_MFP_CONSTANT_GPU_BYTES, RF_MFP_CONSTANT_GPU_CHUNKS,
   REDFIN_METAL_FRONTEND_WORDS
};

struct rwa_device;
int rwa_redfin_frontend_statistics(struct rwa_device *,uint64_t *,size_t);
#ifdef __OBJC__
int redfin_metal_frontend_statistics(id,uint64_t *,size_t);
#endif
#endif
