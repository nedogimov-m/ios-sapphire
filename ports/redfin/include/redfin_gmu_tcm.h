/* SPDX-License-Identifier: MIT */
/*
 * Lito-only, reset-held GMU clock/counter/TCM experiment. References: GMU.md.
 * This does not start CM3, configure SMMU/GX/PDC/RSC, or load firmware.
 * The caller must own a bounded single-CPU md0 session, fresh CX power and
 * its held ARC floor, exclusive GCC/GPUCC/GMU clock access and reset return.
 * Added votes/clocks stay held until that platform reset. Only the two DTCM
 * words and the RCG's initial force-enable bit are restored here.
 */
#ifndef REDFIN_GMU_TCM_H
#define REDFIN_GMU_TCM_H

#include <stdbool.h>
#include <stdint.h>
#include <sys/errno.h>

enum { RF_GT_GCC, RF_GT_GPUCC, RF_GT_GMU };
enum {
    RF_GT_PREFLIGHT = 1, RF_GT_BUS_CLOCKS, RF_GT_RESET, RF_GT_SOURCE,
    RF_GT_CORE_CLOCK, RF_GT_COUNTER, RF_GT_SAVE, RF_GT_PATTERN,
    RF_GT_RESTORE, RF_GT_DONE
};

struct rf_gt_ops {
    void *context;
    /* Recheck the exact A620/UP/md0/power/clock/return lifetime each time. */
    bool (*valid)(void *);
    /* Ordered 32-bit Device MMIO; return positive errno on failure. */
    int (*read)(void *, unsigned, uint32_t, uint32_t *);
    int (*write)(void *, unsigned, uint32_t, uint32_t);
    /* Bounded busy wait in microseconds; no thread sleep or rescheduling. */
    void (*delay)(void *, unsigned);
};

struct rf_gt_report {
    uint32_t stage, error, reads, writes, polls;
    uint32_t pll_mode, pll_l, pll_user, pll_alpha;
    uint32_t pll_vote_before, feed_before, misc, cx, cx_hw, gx;
    uint32_t rcg_before, source_before, gmu_clock_before;
    uint32_t reset_before, result_before, hfi_before;
    uint32_t reset_after, source_after, gmu_clock_after;
    uint32_t counter_before, counter_after, counter_delta;
    uint32_t saved[2], pattern_read[2], restored[2];
    bool reset_held, source_200m, counter_live, dtcm_dirty, dtcm_restored;
};

/* Narrow callback allowlist; the adapter must enforce its own bound lease. */
static inline bool
rf_gt_allowed(unsigned unit, uint32_t at, bool writing)
{
    if (unit == RF_GT_GCC) {
        switch (at) {
        case 0x52010: case 0x52000: case 0x71154: case 0x7100c: case 0x71018:
            return true;
        case 0: case 4: case 0xc: case 0x40: case 0x71004: case 0x71028:
            return !writing;
        default: return false;
        }
    }
    if (unit == RF_GT_GPUCC) {
        switch (at) {
        case 0x1078: case 0x109c: case 0x5000: case 0x1120: case 0x1124: case 0x1098:
            return true;
        case 0x106c: case 0x1540: case 0x100c: case 0x1064:
            return !writing;
        default: return false;
        }
    }
    if (unit == RF_GT_GMU) {
        switch (at) {
        case 0x14000: case 0x7000: case 0x7004:
            return true;
        case 0x14070: case 0x14600: case 0x14220:
            return !writing;
        default: return false;
        }
    }
    return false;
}

static inline int
rf_gt_rd(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    unsigned unit, uint32_t at, uint32_t *value)
{
    if (!rf_gt_allowed(unit, at, false))
        return EINVAL;
    if (!ops->valid(ops->context))
        return ECANCELED;
    r->reads++;
    return ops->read(ops->context, unit, at, value);
}

static inline int
rf_gt_wr(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    unsigned unit, uint32_t at, uint32_t value)
{
    if (!rf_gt_allowed(unit, at, true) ||
        (unit == RF_GT_GMU && at == 0x14000 && value != 1))
        return EINVAL;
    if (!ops->valid(ops->context))
        return ECANCELED;
    r->writes++;
    return ops->write(ops->context, unit, at, value);
}

static inline int
rf_gt_delay(const struct rf_gt_ops *ops, unsigned us)
{
    if (!ops->valid(ops->context))
        return ECANCELED;
    ops->delay(ops->context, us);
    return ops->valid(ops->context) ? 0 : ECANCELED;
}

static inline int
rf_gt_poll(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    unsigned unit, uint32_t at, uint32_t mask, uint32_t expected, unsigned limit)
{
    uint32_t value;
    unsigned i;
    int error;
    for (i = 0; i < limit; i++) {
        error = rf_gt_rd(ops, r, unit, at, &value);
        if (error)
            return error;
        r->polls++;
        if ((value & mask) == expected)
            return 0;
        error = rf_gt_delay(ops, 1);
        if (error)
            return error;
    }
    return ETIMEDOUT;
}

static inline int
rf_gt_update(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    unsigned unit, uint32_t at, uint32_t mask, uint32_t value)
{
    uint32_t before, after;
    int error = rf_gt_rd(ops, r, unit, at, &before);
    if (error)
        return error;
    error = rf_gt_wr(ops, r, unit, at, (before & ~mask) | (value & mask));
    if (error)
        return error;
    error = rf_gt_rd(ops, r, unit, at, &after);
    if (error)
        return error;
    return (after & mask) == (value & mask) ? 0 : EIO;
}

static inline bool
rf_gt_pll_identity(uint32_t mode, uint32_t l, uint32_t user, uint32_t alpha)
{
    /* Locked/active FSM, all native outputs on, even postdivision /2. */
    return (mode & 0xc0100000u) == 0xc0100000u && l == 31 &&
        (user & 0xf07u) == 0x107u && alpha == 0x4000;
}

static inline int
rf_gt_source_live(const struct rf_gt_ops *ops, struct rf_gt_report *r, bool running)
{
    uint32_t v[15];
    static const struct { unsigned unit; uint32_t at; } registers[15] = {
        {RF_GT_GCC, 0x71004}, {RF_GT_GPUCC, 0x106c},
        {RF_GT_GCC, 0}, {RF_GT_GCC, 4}, {RF_GT_GCC, 0xc}, {RF_GT_GCC, 0x40},
        {RF_GT_GCC, 0x52010}, {RF_GT_GCC, 0x52000},
        {RF_GT_GPUCC, 0x1124}, {RF_GT_GPUCC, 0x1120},
        {RF_GT_GPUCC, 0x1098}, {RF_GT_GPUCC, 0x109c},
        {RF_GT_GPUCC, 0x100c}, {RF_GT_GPUCC, 0x1064}, {RF_GT_GPUCC, 0x1540}
    };
    unsigned i;
    int error;
    for (i = 0; i < 15; i++) {
        error = rf_gt_rd(ops, r, registers[i].unit, registers[i].at, &v[i]);
        if (error)
            return error;
    }
    if ((v[0] & 0x80000001u) != 1 || (v[1] & 3u) || !(v[14] & 0x80000000u) ||
        !rf_gt_pll_identity(v[2], v[3], v[4], v[5]) ||
        !(v[6] & 1) || !(v[7] & 0x10000u) || (v[11] & 0x80000001u) != 1 ||
        (v[12] & 0x80000001u) != 1 ||
        (v[13] & 0x80000001u) != 0x80000000u)
        return EAGAIN;
    if (!running && (v[10] & 0x80000001u) != 0x80000000u)
        return EBUSY;
    if (running && ((v[8] & 0x10371fu) != 0x602 ||
            (v[9] & 0x80000001u) != 0 || (v[10] & 0x80000001u) != 1))
        return EAGAIN;
    return 0;
}

/* CSR access with fresh power/source proof; data access also verifies reset. */
static inline int
rf_gt_gmu_rd(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    uint32_t at, uint32_t *value, bool running, bool data)
{
    uint32_t reset;
    int error = rf_gt_source_live(ops, r, running);
    if (error)
        return error;
    if (data) {
        error = rf_gt_rd(ops, r, RF_GT_GMU, 0x14000, &reset);
        if (error)
            return error;
        if (reset != 1)
            return EAGAIN;
    }
    return rf_gt_rd(ops, r, RF_GT_GMU, at, value);
}

static inline int
rf_gt_gmu_wr(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    uint32_t at, uint32_t value, bool running, bool data)
{
    uint32_t reset;
    int error = rf_gt_source_live(ops, r, running);
    if (error)
        return error;
    if (data) {
        error = rf_gt_rd(ops, r, RF_GT_GMU, 0x14000, &reset);
        if (error)
            return error;
        if (reset != 1)
            return EAGAIN;
    }
    return rf_gt_wr(ops, r, RF_GT_GMU, at, value);
}

static inline int
rf_gt_branch(const struct rf_gt_ops *ops, struct rf_gt_report *r,
    unsigned unit, uint32_t at, bool halt_delay)
{
    uint32_t before;
    int error = rf_gt_rd(ops, r, unit, at, &before);
    if (error)
        return error;
    error = rf_gt_wr(ops, r, unit, at, before | 1u);
    if (error)
        return error;
    /* Native GPUCC AHB completion is a delay, not a reliable HALT bit. */
    if (halt_delay)
        return rf_gt_delay(ops, 10);
    return rf_gt_poll(ops, r, unit, at, 0x80000001u, 1, 200);
}

static inline int
rf_gt_run(const struct rf_gt_ops *ops, uint32_t chip, struct rf_gt_report *output)
{
    struct rf_gt_report r = {0};
    uint32_t value, gmu_gx, cfg, command, reset;
    static const uint32_t pattern[2] = {0x62a00d01u, 0xa062f00du};
    unsigned i;
    int error = EINVAL, pattern_error = 0;

    if (!output)
        return EINVAL;
    if (chip != 0x06020001u || !ops || !ops->valid || !ops->read ||
        !ops->write || !ops->delay)
        goto done;
    r.stage = RF_GT_PREFLIGHT;
#define RF_GT_TRY(action) do { error = (action); if (error) goto done; } while (0)
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0x71004, &value));
    if ((value & 0x80000001u) != 1) { error = EAGAIN; goto done; }
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x106c, &r.cx));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1540, &r.cx_hw));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x100c, &r.gx));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1064, &gmu_gx));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1098, &r.gmu_clock_before));
    if ((r.cx & 3u) || !(r.cx_hw & 0x80000000u) ||
        (r.gx & 0x80000001u) != 1 ||
        (gmu_gx & 0x80000001u) != 0x80000000u ||
        (r.gmu_clock_before & 0x80000001u) != 0x80000000u) {
        error = EBUSY; goto done;
    }
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0, &r.pll_mode));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 4, &r.pll_l));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0xc, &r.pll_user));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0x40, &r.pll_alpha));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0x71028, &r.misc));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0x52010, &r.pll_vote_before));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GCC, 0x52000, &r.feed_before));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1120, &r.rcg_before));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1124, &r.source_before));
    if (!rf_gt_pll_identity(r.pll_mode, r.pll_l, r.pll_user, r.pll_alpha) ||
        (r.misc & 3u) != 3 || (r.rcg_before & 0xf1u)) {
        error = EAGAIN; goto done;
    }

    r.stage = RF_GT_BUS_CLOCKS;
    RF_GT_TRY(rf_gt_update(ops, &r, RF_GT_GCC, 0x52010, 1, 1));
    RF_GT_TRY(rf_gt_update(ops, &r, RF_GT_GCC, 0x52000, 0x10000, 0x10000));
    RF_GT_TRY(rf_gt_delay(ops, 10)); /* Divided feed uses BRANCH_HALT_DELAY. */
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GCC, 0x71154, false));
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GCC, 0x7100c, false));
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GCC, 0x71018, false));
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GPUCC, 0x109c, false));
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GPUCC, 0x1078, true));
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GPUCC, 0x5000, false));

    /* Do not clock an ambiguous inherited processor before holding reset. */
    r.stage = RF_GT_RESET;
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14000, &r.reset_before, false, false));
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14070, &r.result_before, false, false));
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14600, &r.hfi_before, false, false));
    if (r.reset_before > 1 || r.result_before != 0 || r.hfi_before != 0) {
        error = EBUSY; goto done;
    }
    RF_GT_TRY(rf_gt_gmu_wr(ops, &r, 0x14000, 1, false, false));
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14000, &r.reset_after, false, false));
    if (r.reset_after != 1) { error = EIO; goto done; }
    r.reset_held = true;

    r.stage = RF_GT_SOURCE;
    RF_GT_TRY(rf_gt_update(ops, &r, RF_GT_GPUCC, 0x1120, 2, 2));
    RF_GT_TRY(rf_gt_poll(ops, &r, RF_GT_GPUCC, 0x1120, 0x80000000u, 0, 500));
    RF_GT_TRY(rf_gt_update(ops, &r, RF_GT_GPUCC, 0x1124, 0x10371f, 0x602));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1120, &command));
    RF_GT_TRY(rf_gt_wr(ops, &r, RF_GT_GPUCC, 0x1120, command | 1));
    RF_GT_TRY(rf_gt_poll(ops, &r, RF_GT_GPUCC, 0x1120, 1, 0, 500));
    RF_GT_TRY(rf_gt_update(ops, &r, RF_GT_GPUCC, 0x1120, 2, r.rcg_before & 2u));

    r.stage = RF_GT_CORE_CLOCK;
    RF_GT_TRY(rf_gt_update(ops, &r, RF_GT_GPUCC, 0x1098, 0xff0, 0xff0));
    RF_GT_TRY(rf_gt_branch(ops, &r, RF_GT_GPUCC, 0x1098, false));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1124, &r.source_after));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1098, &r.gmu_clock_after));
    RF_GT_TRY(rf_gt_source_live(ops, &r, true));
    r.source_200m = true;

    r.stage = RF_GT_COUNTER;
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14220, &r.counter_before, true, true));
    RF_GT_TRY(rf_gt_delay(ops, 1000));
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14220, &r.counter_after, true, true));
    r.counter_delta = r.counter_after - r.counter_before;
    if (r.counter_delta < 15360 || r.counter_delta > 23040) {
        error = ETIMEDOUT; goto done;
    }
    r.counter_live = true;

    r.stage = RF_GT_SAVE;
    for (i = 0; i < 2; i++)
        RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x7000 + 4*i, &r.saved[i], true, true));
    r.stage = RF_GT_PATTERN;
    for (i = 0; i < 2; i++) {
        r.dtcm_dirty = true; /* A failed write may have partially completed. */
        RF_GT_TRY(rf_gt_gmu_wr(ops, &r, 0x7000 + 4*i, pattern[i], true, true));
    }
    for (i = 0; i < 2; i++) {
        RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x7000 + 4*i, &r.pattern_read[i], true, true));
        if (r.pattern_read[i] != pattern[i])
            pattern_error = EIO;
    }
    r.stage = RF_GT_RESTORE;
    for (i = 0; i < 2; i++)
        RF_GT_TRY(rf_gt_gmu_wr(ops, &r, 0x7000 + 4*i, r.saved[i], true, true));
    for (i = 0; i < 2; i++) {
        RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x7000 + 4*i, &r.restored[i], true, true));
        if (r.restored[i] != r.saved[i]) { error = EIO; goto done; }
    }
    r.dtcm_dirty = false;
    r.dtcm_restored = true;
    if (pattern_error) { error = pattern_error; goto done; }
    RF_GT_TRY(rf_gt_gmu_rd(ops, &r, 0x14000, &reset, true, false));
    RF_GT_TRY(rf_gt_rd(ops, &r, RF_GT_GPUCC, 0x1124, &cfg));
    if (reset != 1 || (cfg & 0x10371fu) != 0x602) { error = EAGAIN; goto done; }
    r.stage = RF_GT_DONE;
    error = 0;
done:
#undef RF_GT_TRY
    r.error = (uint32_t)error;
    *output = r;
    return error;
}

#endif /* REDFIN_GMU_TCM_H */
