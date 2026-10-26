/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_EAGL_GUARD_H
#define REDFIN_EAGL_GUARD_H
#include <stdint.h>
#include "include/redfin_gpu_surface.h"
#ifndef REDFIN_GLES_PUBLICATION
#define REDFIN_GLES_PUBLICATION 0
#endif
int redfin_eagl_validate(void);
int redfin_eagl_hardware(void);
int redfin_eagl_installed(void);
int redfin_eagl_display_waits(unsigned display);
int redfin_eagl_publish_frame(void);
int redfin_eagl_producer_ready(void);
int redfin_eagl_direct_requested(void);
int redfin_eagl_frame_budget_enabled(void);
unsigned redfin_eagl_surface_producer(unsigned surface);
int redfin_eagl_publish_surfaces(const struct rf_gu_target *,unsigned count);
void redfin_eagl_direct_frame(unsigned frame,unsigned direct,unsigned mirrored,int notified);
void redfin_eagl_frame_budget(unsigned frame,unsigned pending,unsigned maximum,
                             unsigned waits,unsigned already,unsigned completed,unsigned fallbacks);
void redfin_eagl_mark_installed(unsigned methods);
void redfin_eagl_frame(unsigned frame,unsigned draws,unsigned triangles,
                       unsigned shared,unsigned copied,unsigned errors);
void redfin_eagl_set_tls(void *native_context);
#endif
