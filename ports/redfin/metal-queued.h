/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_QUEUED_H
#define REDFIN_METAL_QUEUED_H
#include <stddef.h>
#include <stdint.h>
struct rwa_device;
struct rwa_redfin_completion;
#define REDFIN_METAL_QUEUED_ABI 1u
/* Submit/retire/destroy require the frontend gate. Wait deliberately does not.
 * Even a partially encoded command returns an owned ticket when it has work
 * to drain. Admission alone never completes resources or callbacks. */
__attribute__((visibility("default"))) int rwa_redfin_commands_submit(struct rwa_device *,struct rwa_redfin_completion **,char *,size_t);
__attribute__((visibility("default"))) int rwa_redfin_completion_wait(struct rwa_redfin_completion *,char *,size_t);
__attribute__((visibility("default"))) int rwa_redfin_completion_retire(struct rwa_redfin_completion *,char *,size_t);
__attribute__((visibility("default"))) void rwa_redfin_completion_destroy(struct rwa_redfin_completion *);
#endif
