/* SPDX-License-Identifier: MIT */
#include "redfin_mesa_submit_merge.h"
/* Called under submit_lock, before appending the next native submission.
 * Pending primaries are finalized; the candidate still has its current IB.
 * Reserve one extra BO per primary IB, even when already present. This
 * upper bound cannot undercount the final merged BO/range inventories. */
static bool redfin_msm_merge_account(struct redfin_msm_merge_budget *budget,
    struct fd_submit *submit,bool pending)
{
    struct fd_submit_sp *native=to_fd_submit_sp(submit);
    uint64_t commands=pending?to_fd_ringbuffer_sp(submit->primary)->u.nr_cmds:
        fd_ringbuffer_cmd_count(submit->primary);
    return redfin_msm_merge_add(budget,commands,(uint64_t)native->nr_bos+commands,
        native->nr_suballoc_bos);
}
static bool redfin_msm_merge_fits(struct fd_device *dev,struct fd_submit *candidate)
{
    struct redfin_msm_merge_budget budget={0};
    foreach_submit(submit,&dev->deferred_submits)
        if(!redfin_msm_merge_account(&budget,submit,true))return false;
    return !candidate || redfin_msm_merge_account(&budget,candidate,false);
}
