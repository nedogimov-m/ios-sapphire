/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GPU_DISPLAY_SERVICE_H
#define REDFIN_GPU_DISPLAY_SERVICE_H
#include <stdbool.h>
#include <stdint.h>
class SweetSurface;
struct redfin_display_geometry;
/* 1: real completed presentation; 0: unsupported/pre-submit CPU fallback;
 * -1: panel DMA completion is unknown, so CPU writes must stay stopped. */
int RedfinGPUPresent(SweetSurface *, const struct redfin_display_geometry *, const uint8_t *);
bool RedfinGPUDisplayWritable(void);
#endif
