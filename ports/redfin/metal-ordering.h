/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_ORDERING_H
#define REDFIN_METAL_ORDERING_H
#include <stdint.h>
#include <stddef.h>
#define REDFIN_METAL_ORDERING_WORDS 6u
struct rwa_device;
/* Queued ops, successful real finishes, CPU drains, deferred ops,
 * alias resolves and GPU memory transitions. No getter submits or waits. */
__attribute__((visibility("default"))) int rwa_redfin_ordering_statistics(struct rwa_device *,uint64_t *,size_t);
#endif
