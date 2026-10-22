/* SPDX-License-Identifier: MIT */
/*
 * A620 GPU-SMMUv2 read-only global snapshot. Native Google msm and preferred
 * HackiOS references are pinned in ../GPU-SMMU.md. No context-bank registers,
 * TCU/TBU registers, fault acknowledgements, TLB operations or writes exist
 * in this interface. A stable snapshot is not an ownership grant.
 */
#ifndef REDFIN_GPU_SMMU_H
#define REDFIN_GPU_SMMU_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <sys/errno.h>

#define RF_GS_CHIP 0x06020001u
#define RF_GS_PHYS 0x03da0000u
#define RF_GS_BYTES 0x10000u
#define RF_GS_MAX_STREAMS 128u
#define RF_GS_MAX_CONTEXTS 8u

struct rf_gs_ops {
    void *context;
    /* Held CX/clocks, reset-held GMU/GX, exact mode and IRQ/return lifetime. */
    bool (*valid)(void *);
    /* Ordered, explicit scalar LDR; positive errno, no implicit mappings. */
    int (*read)(void *, uint32_t, uint32_t *);
};

struct rf_gs_snapshot {
    uint32_t stage, error, reads, changed_offset;
    uint32_t id0, id1, id2, id7, control, fault, syndrome[3];
    uint32_t page_bytes, global_bytes, streams, contexts, stage2_contexts;
    uint32_t sid_bits, input_bits, output_bits, virtual_bits;
    uint32_t smr[RF_GS_MAX_STREAMS], s2cr[RF_GS_MAX_STREAMS];
    uint32_t cbar[RF_GS_MAX_CONTEXTS], cba2r[RF_GS_MAX_CONTEXTS];
    uint32_t references[RF_GS_MAX_CONTEXTS], active_references[RF_GS_MAX_CONTEXTS];
    uint32_t gmu_matches[2], gmu_slot[2], unreferenced_mask;
    uint32_t malformed_routes;
    bool stable, map_format_supported;
};

static inline uint32_t
rf_gs_address_bits(uint32_t code)
{
    static const uint32_t bits[] = {32, 36, 40, 42, 44, 48};
    return code < sizeof(bits) / sizeof(bits[0]) ? bits[code] : 0;
}

static inline bool
rf_gs_read_allowed(uint32_t at, const struct rf_gs_snapshot *s)
{
    switch (at) {
    case 0: case 0x20: case 0x24: case 0x28: case 0x3c:
    case 0x48: case 0x50: case 0x54: case 0x58:
        return true;
    default: break;
    }
    if (!s || (at & 3) || s->streams > RF_GS_MAX_STREAMS ||
        s->contexts > RF_GS_MAX_CONTEXTS || s->page_bytes != 0x1000 ||
        s->global_bytes != 0x8000)
        return false;
    if ((at >= 0x800 && at - 0x800 < s->streams * 4) ||
        (at >= 0xc00 && at - 0xc00 < s->streams * 4))
        return true;
    /* GR1 metadata only; the first context's own page starts at +0x8000. */
    return (at >= 0x1000 && at - 0x1000 < s->contexts * 4) ||
        (at >= 0x1800 && at - 0x1800 < s->contexts * 4);
}

static inline int
rf_gs_read(const struct rf_gs_ops *ops, struct rf_gs_snapshot *s,
    uint32_t at, uint32_t *value)
{
    if (!rf_gs_read_allowed(at, s))
        return EINVAL;
    if (!ops->valid(ops->context))
        return ECANCELED;
    s->reads++;
    return ops->read(ops->context, at, value);
}

static inline bool
rf_gs_stream_matches(uint32_t smr, uint32_t stream)
{
    uint32_t mask = (smr >> 16) & 0x7fffu;
    return (smr & 0x80000000u) && !((stream ^ (smr & 0x7fffu)) & ~mask & 0x7fffu);
}

static inline int
rf_gs_compare(const struct rf_gs_ops *ops, struct rf_gs_snapshot *s,
    uint32_t at, uint32_t previous)
{
    uint32_t now;
    int error = rf_gs_read(ops, s, at, &now);
    if (error)
        return error;
    if (now != previous) {
        s->changed_offset = at;
        return EAGAIN;
    }
    return 0;
}

static inline int
rf_gs_snapshot_run(const struct rf_gs_ops *ops, uint32_t chip,
    struct rf_gs_snapshot *s)
{
    unsigned i, which;
    uint32_t reference_mask = 0;
    int error = EINVAL;
    if (!s)
        return EINVAL;
    *s = (struct rf_gs_snapshot){0};
    if (chip != RF_GS_CHIP || !ops || !ops->valid || !ops->read)
        goto done;
#define RF_GS_TRY(action) do { error = (action); if (error) goto done; } while (0)
    s->stage = 1;
    RF_GS_TRY(rf_gs_read(ops, s, 0x20, &s->id0));
    RF_GS_TRY(rf_gs_read(ops, s, 0x24, &s->id1));
    RF_GS_TRY(rf_gs_read(ops, s, 0x28, &s->id2));
    RF_GS_TRY(rf_gs_read(ops, s, 0x3c, &s->id7));
    s->page_bytes = (s->id1 & 0x80000000u) ? 0x10000u : 0x1000u;
    s->global_bytes = s->page_bytes << (((s->id1 >> 28) & 7u) + 1);
    s->streams = s->id0 & 0xffu;
    s->contexts = s->id1 & 0xffu;
    s->stage2_contexts = (s->id1 >> 16) & 0xffu;
    s->sid_bits = (s->id0 >> 9) & 15u;
    s->input_bits = rf_gs_address_bits(s->id2 & 15u);
    s->output_bits = rf_gs_address_bits((s->id2 >> 4) & 15u);
    s->virtual_bits = rf_gs_address_bits((s->id2 >> 8) & 15u);
    if (!(s->id0 & (1u << 30)) || !(s->id0 & (1u << 27)) || (s->id0 & (1u << 8)) ||
        s->page_bytes != 0x1000 || s->global_bytes != RF_GS_BYTES / 2 ||
        !s->streams || s->streams > RF_GS_MAX_STREAMS ||
        !s->contexts || s->contexts > RF_GS_MAX_CONTEXTS ||
        s->stage2_contexts > s->contexts || !s->sid_bits)
    { error = ENOTSUP; goto done; }
    s->stage = 2;
    RF_GS_TRY(rf_gs_read(ops, s, 0, &s->control));
    RF_GS_TRY(rf_gs_read(ops, s, 0x48, &s->fault));
    for (i = 0; i < 3; i++)
        RF_GS_TRY(rf_gs_read(ops, s, 0x50 + 4*i, &s->syndrome[i]));
    for (i = 0; i < s->streams; i++) {
        RF_GS_TRY(rf_gs_read(ops, s, 0x800 + 4*i, &s->smr[i]));
        /* Include latent invalid-SMR references; none can imply a free bank. */
        RF_GS_TRY(rf_gs_read(ops, s, 0xc00 + 4*i, &s->s2cr[i]));
    }
    for (i = 0; i < s->contexts; i++) {
        RF_GS_TRY(rf_gs_read(ops, s, 0x1000 + 4*i, &s->cbar[i]));
        RF_GS_TRY(rf_gs_read(ops, s, 0x1800 + 4*i, &s->cba2r[i]));
    }
    s->stage = 3;
    RF_GS_TRY(rf_gs_compare(ops, s, 0x20, s->id0));
    RF_GS_TRY(rf_gs_compare(ops, s, 0x24, s->id1));
    RF_GS_TRY(rf_gs_compare(ops, s, 0x28, s->id2));
    RF_GS_TRY(rf_gs_compare(ops, s, 0x3c, s->id7));
    RF_GS_TRY(rf_gs_compare(ops, s, 0, s->control));
    RF_GS_TRY(rf_gs_compare(ops, s, 0x48, s->fault));
    for (i = 0; i < 3; i++)
        RF_GS_TRY(rf_gs_compare(ops, s, 0x50 + 4*i, s->syndrome[i]));
    for (i = 0; i < s->streams; i++) {
        RF_GS_TRY(rf_gs_compare(ops, s, 0x800 + 4*i, s->smr[i]));
        RF_GS_TRY(rf_gs_compare(ops, s, 0xc00 + 4*i, s->s2cr[i]));
    }
    for (i = 0; i < s->contexts; i++) {
        RF_GS_TRY(rf_gs_compare(ops, s, 0x1000 + 4*i, s->cbar[i]));
        RF_GS_TRY(rf_gs_compare(ops, s, 0x1800 + 4*i, s->cba2r[i]));
    }
    s->gmu_slot[0] = s->gmu_slot[1] = UINT32_MAX;
    for (i = 0; i < s->streams; i++) {
        uint32_t type = (s->s2cr[i] >> 16) & 3u, bank = s->s2cr[i] & 0xffu;
        if (type == 3 || (s->smr[i] & 0x8000u) || (type == 0 && bank >= s->contexts))
            s->malformed_routes++;
        if (type == 0 && bank < s->contexts) {
            s->references[bank]++;
            reference_mask |= 1u << bank;
            if (s->smr[i] & 0x80000000u)
                s->active_references[bank]++;
        }
        for (which = 0; which < 2; which++) {
            if (!rf_gs_stream_matches(s->smr[i], 4u + which))
                continue;
            s->gmu_matches[which]++;
            s->gmu_slot[which] = i;
        }
    }
    for (which = 0; which < 2; which++)
        if (s->gmu_matches[which] != 1)
            s->gmu_slot[which] = UINT32_MAX;
    s->unreferenced_mask = ((1u << s->contexts) - 1u) & ~reference_mask;
    s->map_format_supported = (s->id2 & (1u << 12)) && s->output_bits >= 36 &&
        s->virtual_bits >= 39 && s->sid_bits >= 11 && !s->malformed_routes;
    if (!ops->valid(ops->context)) { error = ECANCELED; goto done; }
    s->stable = true;
    s->stage = 4;
    error = 0;
done:
#undef RF_GS_TRY
    if (error)
        s->map_format_supported = false;
    s->error = (uint32_t)error;
    return error;
}

#endif /* REDFIN_GPU_SMMU_H */
