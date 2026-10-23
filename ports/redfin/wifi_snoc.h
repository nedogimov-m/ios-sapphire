/* SPDX-License-Identifier: MIT
 * Redfin APPS SMMU evidence for the WCN3990-class SNOC transport.
 * Native msm 500b3a2059c1eec0fec08ec56add06320ea901a8 arm-smmu{,-regs.h}.
 * Read-only, fixed-layout snapshots. Neither an invalid SMR nor a blank CB
 * grants ownership; no route, context, TLB, fault or CE write API exists here.
 */
#ifndef REDFIN_WIFI_SNOC_H
#define REDFIN_WIFI_SNOC_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/errno.h>

#define RF_SNOC_SMMU_BASE UINT64_C(0x15000000)
#define RF_SNOC_SMMU_BYTES 0x100000u
#define RF_SNOC_GLOBAL_BYTES 0x4000u
#define RF_SNOC_CONTEXT_OFFSET 0x80000u
#define RF_SNOC_CONTEXT_BYTES 0x40000u
#define RF_SNOC_STREAMS 81u
#define RF_SNOC_CONTEXTS 62u
#define RF_SNOC_WLAN_SID 0xc0u

struct rf_snoc_ops {
    void *context;
    int (*check)(void *);
    /* block0 = GR0/GR1, block1 = CB pages; offsets are block relative. */
    int (*read)(void *, unsigned, uint32_t, uint32_t *);
};
struct rf_snoc_bank { uint32_t sctlr, cbar, cba2r, fault; };
struct rf_snoc_snapshot {
    uint32_t stage, error, reads, changed_block, changed_offset;
    uint32_t id[3], control, fault, syndrome[3];
    uint32_t smr[RF_SNOC_STREAMS], s2cr[RF_SNOC_STREAMS];
    struct rf_snoc_bank bank[RF_SNOC_CONTEXTS];
    uint32_t references[RF_SNOC_CONTEXTS], active_references[RF_SNOC_CONTEXTS];
    uint32_t wlan_matches[2], wlan_slot[2], ipa_matches, malformed_routes;
    uint32_t blank_unreferenced;
    bool stable;
};

static inline bool rf_snoc_read_allowed(unsigned block, uint32_t at)
{
    if (at & 3u) return false;
    if (block == 1) return at < RF_SNOC_CONTEXTS * 0x1000u &&
        ((at & 0xfffu) == 0 || (at & 0xfffu) == 0x58u);
    if (block) return false;
    if (at == 0 || at == 0x20 || at == 0x24 || at == 0x28 || at == 0x48 ||
        at == 0x50 || at == 0x54 || at == 0x58) return true;
    return (at >= 0x800 && at - 0x800 < RF_SNOC_STREAMS * 4u) ||
        (at >= 0xc00 && at - 0xc00 < RF_SNOC_STREAMS * 4u) ||
        (at >= 0x1000 && at - 0x1000 < RF_SNOC_CONTEXTS * 4u) ||
        (at >= 0x1800 && at - 0x1800 < RF_SNOC_CONTEXTS * 4u);
}
static inline bool rf_snoc_stream_matches(uint32_t smr, uint32_t sid)
{
    return (smr & 0x80000000u) && !((sid ^ smr) & ~((smr >> 16) & 0x7fffu) & 0x7fffu);
}
static inline int rf_snoc_sample(const struct rf_snoc_ops *ops, struct rf_snoc_snapshot *s,
    unsigned block, uint32_t at, uint32_t *saved, bool compare)
{
    uint32_t value = 0;
    if (!saved || !rf_snoc_read_allowed(block, at)) return EINVAL;
    int error = ops->check(ops->context);
    if (error) return error;
    ++s->reads;
    error = ops->read(ops->context, block, at, &value);
    if (error) return error;
    if (value == UINT32_MAX) return EIO;
    if (compare && *saved != value) {
        s->changed_block = block; s->changed_offset = at;
        return EAGAIN;
    }
    *saved = value;
    return 0;
}

static inline int rf_snoc_observe(const struct rf_snoc_ops *ops, struct rf_snoc_snapshot *s)
{
    int error = EINVAL;
    if (!s) return EINVAL;
#ifdef __cplusplus
    *s = rf_snoc_snapshot{};
#else
    *s = (struct rf_snoc_snapshot){0};
#endif
    s->wlan_slot[0] = s->wlan_slot[1] = UINT32_MAX;
    if (!ops || !ops->check || !ops->read) goto done;
#define RF_SNOC_SAMPLE(block, at, field, compare) do { \
    error = rf_snoc_sample(ops, s, block, at, &(field), compare); if (error) goto done; \
} while (0)
    for (unsigned pass = 0; pass < 2; ++pass) {
        bool compare = pass != 0;
        s->stage = pass ? 3 : 1;
        for (unsigned i = 0; i < 3; ++i) RF_SNOC_SAMPLE(0, 0x20 + 4u*i, s->id[i], compare);
        /* Exact IDs were observed by the isolated native USB context probe.
         * Refuse different layouts before ever reaching context pages. */
        if (s->id[0] != 0x4c017e51u || s->id[1] != 0x6000003eu || s->id[2] != 0x5111u)
        { error = ENOTSUP; goto done; }
        RF_SNOC_SAMPLE(0, 0, s->control, compare);
        if ((s->control & 9u) || !(s->control & 0x400u)) { error = ENOTSUP; goto done; }
        RF_SNOC_SAMPLE(0, 0x48, s->fault, compare);
        for (unsigned i = 0; i < 3; ++i) RF_SNOC_SAMPLE(0, 0x50 + 4u*i, s->syndrome[i], compare);
        if (!pass) s->stage = 2;
        for (unsigned i = 0; i < RF_SNOC_STREAMS; ++i) {
            RF_SNOC_SAMPLE(0, 0x800 + 4u*i, s->smr[i], compare);
            RF_SNOC_SAMPLE(0, 0xc00 + 4u*i, s->s2cr[i], compare);
        }
        for (unsigned i = 0; i < RF_SNOC_CONTEXTS; ++i) {
            RF_SNOC_SAMPLE(0, 0x1000 + 4u*i, s->bank[i].cbar, compare);
            RF_SNOC_SAMPLE(0, 0x1800 + 4u*i, s->bank[i].cba2r, compare);
            RF_SNOC_SAMPLE(1, 0x1000u*i, s->bank[i].sctlr, compare);
            RF_SNOC_SAMPLE(1, 0x1000u*i + 0x58, s->bank[i].fault, compare);
        }
    }
    for (unsigned i = 0; i < RF_SNOC_STREAMS; ++i) {
        uint32_t type = (s->s2cr[i] >> 16) & 3u, bank = s->s2cr[i] & 255u;
        if (type == 3 || (s->smr[i] & 0x8000u) || (!type && bank >= RF_SNOC_CONTEXTS))
            ++s->malformed_routes;
        /* Retain references even from invalid SMRs: never call a latent CB free. */
        if (!type && bank < RF_SNOC_CONTEXTS) {
            ++s->references[bank];
            if (s->smr[i] & 0x80000000u) ++s->active_references[bank];
        }
        for (unsigned which = 0; which < 2; ++which) if (rf_snoc_stream_matches(s->smr[i], RF_SNOC_WLAN_SID + which)) {
            ++s->wlan_matches[which]; s->wlan_slot[which] = i;
        }
        if (rf_snoc_stream_matches(s->smr[i], 0x521)) ++s->ipa_matches;
    }
    for (unsigned which = 0; which < 2; ++which)
        if (s->wlan_matches[which] != 1) s->wlan_slot[which] = UINT32_MAX;
    for (unsigned i = 0; i < RF_SNOC_CONTEXTS; ++i) {
        const struct rf_snoc_bank *b = &s->bank[i];
        if (!s->malformed_routes && !s->references[i] && !b->sctlr && !b->cbar && !b->cba2r && !b->fault)
            ++s->blank_unreferenced;
    }
    error = ops->check(ops->context);
    if (error) goto done;
    s->stage = 4; s->stable = true;
done:
#undef RF_SNOC_SAMPLE
    s->error = (uint32_t)error;
    return error;
}
#endif
