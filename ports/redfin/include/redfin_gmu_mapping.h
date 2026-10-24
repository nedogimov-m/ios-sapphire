/* SPDX-License-Identifier: MIT */
/* Native A620 GMU kernel-stream context, while CM3/GX remain reset-held.
 * Sources: preferred redwood_adreno.c space_on(); native arm-smmu.c and
 * io-pgtable-arm.c at the pins in GPU-SMMU.md. No global reset/fault ack,
 * foreign route update, context release or firmware execution is provided.
 */
#ifndef REDFIN_GMU_MAPPING_H
#define REDFIN_GMU_MAPPING_H
#include <string.h>
#include "redfin_gpu_context.h"
#include "redfin_gmu_pagetables.h"

#define RF_GMM_BANK 1u
#define RF_GMM_STEPS 17u
#define RF_GMM_TCR 0x00802019u /* 39-bit/4KiB, NC walks, outer-shareable, EPD1. */
#define RF_GMM_TCR2 0x00038011u /* 36-bit PA, ASID16, upstream SEP. */
#define RF_GMM_SCTLR 0x1027u /* M/TRE/AFE/CFRE/ASIDPNE; no stall or IRQ. */

struct rf_gmm_ops {
    void *context;
    int (*check)(void *);
    int (*sample)(void *, struct rf_gs_snapshot *, struct rf_gc_snapshot *);
    int (*read)(void *, unsigned block, uint32_t, uint32_t *);
    int (*write)(void *, unsigned block, uint32_t, uint32_t);
    int (*publish)(void *, const struct rf_gm_pt_plan *);
    int (*delay)(void *, unsigned);
};

struct rf_gmm_lease {
    unsigned attempted, owned, active, poisoned, slot, stores, polls;
    unsigned ttbr1_valid;
    unsigned step, block;
    uint32_t offset, requested, observed;
    struct rf_gs_snapshot expected, fresh;
    struct rf_gc_snapshot banks, fresh_banks;
};

static inline bool rf_gmm_equal(const struct rf_gmm_lease *s)
{
    const struct rf_gs_snapshot *a = &s->expected, *b = &s->fresh;
    return b->stable && b->stage == 4 && !b->error &&
        a->id0 == b->id0 && a->id1 == b->id1 && a->id2 == b->id2 && a->id7 == b->id7 &&
        a->control == b->control && a->fault == b->fault &&
        !memcmp(a->syndrome, b->syndrome, sizeof(a->syndrome)) &&
        !memcmp(a->smr, b->smr, sizeof(a->smr)) && !memcmp(a->s2cr, b->s2cr, sizeof(a->s2cr)) &&
        !memcmp(a->cbar, b->cbar, sizeof(a->cbar)) && !memcmp(a->cba2r, b->cba2r, sizeof(a->cba2r)) &&
        s->fresh_banks.stable && s->fresh_banks.stage == 3 && !s->fresh_banks.error &&
        !memcmp(s->banks.words, s->fresh_banks.words, sizeof(s->banks.words));
}

static inline int rf_gmm_verify(struct rf_gmm_lease *s, const struct rf_gmm_ops *o)
{
    if (!s || !o || !o->check || !o->sample || !o->read || !o->write ||
        !o->publish || !o->delay || s->poisoned) return EINVAL;
    int error = o->check(o->context);
    if (!error) error = o->sample(o->context, &s->fresh, &s->fresh_banks);
    if (!error && !rf_gmm_equal(s)) error = EAGAIN;
    for (unsigned i = 0; !error && i < 2; ++i) if (s->ttbr1_valid & (1u << i)) {
        uint32_t value;
        error = o->read(o->context, 1, 0x28 + 4u*i, &value);
        if (!error && value) error = EAGAIN;
    }
    if (!error) error = o->check(o->context);
    if (error) { s->poisoned = 1; s->active = 0; }
    return error;
}

static inline int rf_gmm_step(const struct rf_gmm_lease *s, const struct rf_gm_pt_plan *p,
    unsigned step, unsigned *block, uint32_t *at, uint32_t *value)
{
    if (!s || !s->owned || !p || step >= RF_GMM_STEPS || !block || !at || !value) return EINVAL;
    *block = 1; *at = 0; *value = 0;
    switch (step) {
    case 0: break;
    case 1: *block = 0; *at = 0x1804; *value = 1; break;
    case 2: *block = 0; *at = 0x1004; *value = 0x1f300; break;
    case 3: *at = 0x10; *value = RF_GMM_TCR2; break;
    case 4: *at = 0x30; *value = RF_GMM_TCR; break;
    case 5: *at = 0x20; *value = (uint32_t)p->root_physical; break;
    case 6: *at = 0x24; *value = (uint32_t)(p->root_physical >> 32) | 0x10000; break;
    case 7: *at = 0x28; break;
    case 8: *at = 0x2c; break;
    case 9: *at = 0x34; break;
    case 10: *at = 0x38; *value = p->mair0; break;
    case 11: *at = 0x3c; break;
    case 12: *at = 0x610; *value = RF_GMM_BANK; break;
    case 13: *at = 0x7f0; *value = 1; break;
    case 14: *value = RF_GMM_SCTLR; break;
    case 15: *block = 0; *at = 0xc00 + 4u*s->slot; *value = RF_GMM_BANK; break;
    default: *block = 0; *at = 0x800 + 4u*s->slot; *value = 0x84000005; break;
    }
    return 0;
}

static inline int rf_gmm_claim(struct rf_gmm_lease *s, const struct rf_gmm_ops *o,
    const struct rf_gs_snapshot *initial, const struct rf_gc_snapshot *banks,
    const struct rf_gm_pt_plan *plan, const struct rf_gm_memory_owner *owner)
{
    int error = EINVAL;
    if (!s || !o || !o->check || !o->sample || !o->read || !o->write || !o->publish ||
        !o->delay || !initial || !banks || !plan || !owner || !owner->valid || !owner->owns) return error;
    if (s->attempted) return EBUSY;
    s->attempted = 1;
    if (!rf_gm_snapshot_format(initial) || initial->id0 != 0x4c017e05u ||
        initial->id1 != 0x20000005u || initial->id2 != 0x5511u || initial->id7 != 0x24u ||
        initial->fault || (initial->control & 9u) || initial->gmu_matches[0] || initial->gmu_matches[1] ||
        initial->references[RF_GMM_BANK] || initial->cbar[RF_GMM_BANK] || initial->cba2r[RF_GMM_BANK] ||
        !banks->stable || banks->stage != 3 || banks->error || banks->fault_mask ||
        banks->disabled_mask != 3 || plan->granule != 0x1000 || plan->virtual_bits != 39 ||
        plan->physical_bits != 36 || plan->mair0 != 0xf404ff44u ||
        !rf_gm_memory_valid(&plan->tables) || plan->root_physical != plan->tables.physical ||
        !plan->table_count || plan->table_count > RF_GM_PT_MAX_TABLES ||
        plan->table_bytes != (uint64_t)plan->table_count * 4096 || plan->table_bytes > plan->tables.owned_bytes ||
        !plan->extent_count || plan->extent_count > RF_GM_PT_MAX_EXTENTS) { error = EPERM; goto failed; }
    s->slot = initial->streams;
    for (unsigned i = 0; i < initial->streams; ++i)
        if (!(initial->smr[i] & 0x80000000u)) { s->slot = i; break; }
    if (s->slot == initial->streams) { error = ENOSPC; goto failed; }
    if (!owner->valid(owner->context) || !owner->owns(owner->context, &plan->tables, RF_GM_PT_TABLE_POOL))
        { error = EACCES; goto failed; }
    for (unsigned i = 0; i < plan->extent_count; ++i)
        if (!owner->valid(owner->context) || !owner->owns(owner->context, &plan->extents[i].memory, RF_GM_PT_DATA))
            { error = EACCES; goto failed; }
    s->expected = *initial; s->banks = *banks;
    error = rf_gmm_verify(s, o); if (error) goto failed;
    error = o->publish(o->context, plan); if (error) goto failed;
    error = rf_gmm_verify(s, o); if (error) goto failed;
    s->owned = 1;
    for (unsigned step = 0; step < RF_GMM_STEPS; ++step) {
        unsigned block; uint32_t at, value, got = 0;
        error = rf_gmm_verify(s, o); if (error) goto failed;
        error = rf_gmm_step(s, plan, step, &block, &at, &value); if (error) goto failed;
        s->step = step; s->block = block; s->offset = at;
        s->requested = value; s->observed = 0;
        ++s->stores;
        error = o->write(o->context, block, at, value); if (error) goto failed;
        if (step == 12) continue; /* command register, no readable stored value */
        if (step == 13) {
            for (unsigned us = 0; us < 1000; ++us) {
                error = o->check(o->context); if (error) goto failed;
                ++s->polls; error = o->read(o->context, 1, 0x7f4, &got); if (error) goto failed;
                s->observed = got;
                if (!(got & 1)) break;
                error = o->delay(o->context, 1); if (error) goto failed;
            }
            if (got & 1) { error = ETIMEDOUT; goto failed; }
            continue;
        }
        error = o->check(o->context); if (error) goto failed;
        error = o->read(o->context, block, at, &got); if (error) goto failed;
        s->observed = got;
        /* The native/upstream contract tests CBAR's type and S2CR's
         * implemented route/privilege fields. Retain the complete observed
         * word afterwards; reserved HYP readback bits are not assumptions. */
        uint32_t mask = step == 2 ? 0x30000u : step == 15 ? 0x030300ffu : UINT32_MAX;
        if ((got & mask) != (value & mask)) { error = EIO; goto failed; }
        if (step == 7 || step == 8) s->ttbr1_valid |= 1u << (step - 7);
        if (!block) {
            if (step == 1) {
                s->expected.cba2r[1] = value;
                s->banks.words[1][8] = (s->banks.words[1][8] & ~0x600u) | 0x400u;
            } else if (step == 2) s->expected.cbar[1] = got;
            else if (step == 15) s->expected.s2cr[s->slot] = got;
            else s->expected.smr[s->slot] = value;
        } else for (unsigned i = 0; i < RF_GC_WORDS; ++i)
            if (rf_gc_offsets[i] == at) s->banks.words[1][i] = value;
    }
    error = rf_gmm_verify(s, o); if (error) goto failed;
    s->active = 1;
    return 0;
failed:
    s->poisoned = 1; s->active = 0;
    return error;
}
#endif
