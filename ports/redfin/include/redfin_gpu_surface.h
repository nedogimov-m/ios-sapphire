/* SPDX-License-Identifier: MIT */
/* Announce a modification by an already admitted GPU producer. This only
 * advances the IOSurface seed; it never retires a fence or grants CPU access. */
#ifndef REDFIN_GPU_SURFACE_H
#define REDFIN_GPU_SURFACE_H
#include <stdint.h>
#define RF_GU_ABI 1u
#define RF_GU_PARAM UINT32_C(0x52465531)
#define RF_GU_ANNOUNCE UINT32_C(0x52465532)
#define RF_GU_MAX_TARGETS 256u
#define RF_GU_SEED_OFFSET 12u /* Actual Redfin SweetSurface state ABI. */
struct rf_gu_target {uint32_t handle,surface;};
struct rf_gu_surface_producer {uint32_t handle,surface,fence,reserved;};
#ifdef __cplusplus
static_assert(sizeof(rf_gu_target)==8 && sizeof(rf_gu_surface_producer)==16,"GPU producer ABI1");
#else
_Static_assert(sizeof(struct rf_gu_target)==8 && sizeof(struct rf_gu_surface_producer)==16,"GPU producer ABI1");
#endif
#endif
