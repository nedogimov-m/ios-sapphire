/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_MESA_SUBMIT_MERGE_H
#define REDFIN_MESA_SUBMIT_MERGE_H
#include <stdbool.h>
#include <stdint.h>
#include "redfin_gpu_scope.h"

/* Native A620 retained-submit ABI1 accepts at most128 primary IBs. This is
 * deliberately independent of Linux MSM's larger ring-buffer limit. Count
 * duplicate BOs/views conservatively before merging or publishing any fence. */
#define REDFIN_MSM_MERGE_COMMANDS 128u
struct redfin_msm_merge_budget {uint32_t commands,bos,ranges;};
static inline bool redfin_msm_merge_add(struct redfin_msm_merge_budget *budget,
    uint64_t commands,uint64_t bos,uint64_t views)
{
    if(!budget || !commands || commands>REDFIN_MSM_MERGE_COMMANDS ||
       bos>RF_GW_MAX_BOS || views>RF_GW_MAX_RANGES ||
       budget->commands>REDFIN_MSM_MERGE_COMMANDS-commands ||
       budget->bos>RF_GW_MAX_BOS-bos || bos+views>RF_GW_MAX_RANGES ||
       budget->ranges>RF_GW_MAX_RANGES-bos-views)return false;
    budget->commands+=(uint32_t)commands;
    budget->bos+=(uint32_t)bos;
    budget->ranges+=(uint32_t)(bos+views);
    return true;
}
#endif
