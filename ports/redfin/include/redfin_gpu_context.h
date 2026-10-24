/* SPDX-License-Identifier: MIT */
/*
 * Read-only context 0/1 observation after a fresh GPU-SMMU global snapshot.
 * No context ownership, table dereference, store, fault ack or TLB operation.
 * Native Lito protects CB5 and above; only these two low banks are addressed.
 */
#ifndef REDFIN_GPU_CONTEXT_H
#define REDFIN_GPU_CONTEXT_H

#include "redfin_gpu_smmu.h"

#define RF_GC_BANKS 2u
#define RF_GC_WORDS 12u
#define RF_GC_MAP_BYTES 0x4000u /* XNU's mapping granule; access only CB0/1. */
#define RF_GC_FAULT_BITS 0xc00001feu /* FSR.FORMAT[10:9] is status, not a fault. */

static const uint32_t rf_gc_offsets[RF_GC_WORDS] = {
    0, 0x10, 0x20, 0x24, 0x30, 0x34, 0x38, 0x3c, 0x58, 0x60, 0x64, 0x68
};

struct rf_gc_ops {
    void *context;
    bool (*valid)(void *);
    int (*read)(void *, unsigned bank, uint32_t offset, uint32_t *);
};

struct rf_gc_snapshot {
    uint32_t stage, reads, changed_bank, changed_offset, disabled_mask, fault_mask;
    uint32_t words[RF_GC_BANKS][RF_GC_WORDS];
    int error;
    bool stable;
};

static inline bool
rf_gc_allowed(unsigned bank, uint32_t at)
{
    if (bank >= RF_GC_BANKS)
        return false;
    for (unsigned i = 0; i < RF_GC_WORDS; i++)
        if (at == rf_gc_offsets[i])
            return true;
    return false;
}

static inline int
rf_gc_snapshot_run(const struct rf_gc_ops *ops, const struct rf_gs_snapshot *global,
    struct rf_gc_snapshot *out)
{
    int error = EINVAL;
    if (!out)
        return error;
    *out = (struct rf_gc_snapshot){0};
    if (!ops || !ops->valid || !ops->read || !global)
        goto done;
    if (!global->stable || global->error || global->stage != 4 ||
        !global->map_format_supported || global->page_bytes != 0x1000 ||
        global->global_bytes != 0x8000 || global->contexts < RF_GC_BANKS ||
        global->contexts > RF_GS_MAX_CONTEXTS || global->stage2_contexts)
    { error = ENOTSUP; goto done; }
    for (unsigned pass = 0; pass < 2; pass++) {
        out->stage = pass + 1;
        for (unsigned bank = 0; bank < RF_GC_BANKS; bank++) {
            for (unsigned i = 0; i < RF_GC_WORDS; i++) {
                uint32_t value;
                if (!ops->valid(ops->context))
                { error = ECANCELED; goto done; }
                out->reads++;
                error = ops->read(ops->context, bank, rf_gc_offsets[i], &value);
                if (error)
                    goto done;
                if (!pass) {
                    out->words[bank][i] = value;
                } else if (out->words[bank][i] != value) {
                    out->changed_bank = bank;
                    out->changed_offset = rf_gc_offsets[i];
                    error = EAGAIN;
                    goto done;
                }
            }
        }
    }
    if (!ops->valid(ops->context))
    { error = ECANCELED; goto done; }
    for (unsigned bank = 0; bank < RF_GC_BANKS; bank++) {
        if (!(out->words[bank][0] & 1))
            out->disabled_mask |= 1u << bank;
        if (out->words[bank][8] & RF_GC_FAULT_BITS)
            out->fault_mask |= 1u << bank;
    }
    out->stage = 3;
    out->stable = true;
    error = 0;
done:
    out->error = error;
    return error;
}

#endif /* REDFIN_GPU_CONTEXT_H */
