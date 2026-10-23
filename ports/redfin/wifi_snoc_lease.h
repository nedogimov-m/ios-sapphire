/* SPDX-License-Identifier: MIT
 * Sole-worker APPS SMMU lease for WLANc0/mask1, adapted from the native
 * non-static NS allocator and the proven Redfin USB AArch64 bypass context.
 * Include after wifi_snoc.h. No memory allocator or CE/DMA authority here.
 */
#ifndef REDFIN_WIFI_SNOC_LEASE_H
#define REDFIN_WIFI_SNOC_LEASE_H
#include <string.h>
#define RF_SNOC_CONTEXT_FAULT 0xc00001feu
#define RF_SNOC_LEASE_STORES 5u
struct rf_snoc_lease_ops {
    void *context;
    int (*check)(void *);
    int (*sample)(void *, struct rf_snoc_snapshot *);
    int (*read)(void *, unsigned, uint32_t, uint32_t *);
    int (*write)(void *, unsigned, uint32_t, uint32_t);
    int (*delay)(void *, unsigned);
};
struct rf_snoc_lease {
    unsigned attempted, leased, active, poisoned, stores, bank, slot, polls;
    struct rf_snoc_snapshot expected, fresh;
};
static inline bool rf_snoc_raw_equal(const struct rf_snoc_snapshot *a, const struct rf_snoc_snapshot *b)
{
    return a && b && a->stable && b->stable && a->stage == 4 && b->stage == 4 && !a->error && !b->error &&
        a->control == b->control && a->fault == b->fault &&
        !memcmp(a->id, b->id, sizeof(a->id)) && !memcmp(a->syndrome, b->syndrome, sizeof(a->syndrome)) &&
        !memcmp(a->smr, b->smr, sizeof(a->smr)) && !memcmp(a->s2cr, b->s2cr, sizeof(a->s2cr)) &&
        !memcmp(a->bank, b->bank, sizeof(a->bank));
}
static inline int rf_snoc_lease_gate(struct rf_snoc_lease *s, const struct rf_snoc_lease_ops *o)
{
    if (!s) return EINVAL;
    if (!o || !o->check || !o->sample || !o->read || !o->write || !o->delay || s->poisoned) {
        s->poisoned = 1; s->active = 0; return EINVAL;
    }
    int error = o->check(o->context);
    if (error) { s->poisoned = 1; s->active = 0; }
    return error;
}
static inline int rf_snoc_lease_verify(struct rf_snoc_lease *s, const struct rf_snoc_lease_ops *o)
{
    int error = rf_snoc_lease_gate(s, o);
    if (error) return error;
    if (!s->attempted || !s->leased) return EPERM;
    error = o->sample(o->context, &s->fresh);
    if (!error && !rf_snoc_raw_equal(&s->expected, &s->fresh)) error = EAGAIN;
    if (!error) error = rf_snoc_lease_gate(s, o);
    if (error) { s->poisoned = 1; s->active = 0; }
    return error;
}
/* A typed step is the only write address/value the adapter may accept. */
static inline int rf_snoc_lease_step(const struct rf_snoc_lease *s, unsigned step,
    unsigned *block, uint32_t *at, uint32_t *value)
{
    if (!s || !s->leased || !block || !at || !value || step >= RF_SNOC_LEASE_STORES ||
        s->bank >= RF_SNOC_CONTEXTS || s->slot >= RF_SNOC_STREAMS) return EINVAL;
    *block = 0;
    switch (step) {
    case 0: *block = 1; *at = 0x1000u*s->bank; *value = 0; break;
    case 1: *at = 0x1800 + 4u*s->bank; *value = 1; break;
    case 2: *at = 0x1000 + 4u*s->bank; *value = 0x10000; break;
    case 3: *at = 0xc00 + 4u*s->slot; *value = 0x300u | s->bank; break;
    default: *at = 0x800 + 4u*s->slot; *value = 0x800100c0; break;
    }
    return 0;
}
static inline int rf_snoc_lease_claim(struct rf_snoc_lease *s, const struct rf_snoc_lease_ops *o,
    const struct rf_snoc_snapshot *initial)
{
    bool reserved[RF_SNOC_CONTEXTS] = {false};
    int error = rf_snoc_lease_gate(s, o);
    if (error) return error;
    if (s->attempted) return EBUSY;
    s->attempted = 1;
    if (!initial || !initial->stable || initial->stage != 4 || initial->error || initial->fault ||
        initial->malformed_routes || initial->wlan_matches[0] || initial->wlan_matches[1] ||
        initial->id[0] != 0x4c017e51u || initial->id[1] != 0x6000003eu || initial->id[2] != 0x5111u ||
        (initial->control & 9u) || !(initial->control & 0x400u)) { error = EPERM; goto failed; }
    s->expected = *initial; s->bank = RF_SNOC_CONTEXTS; s->slot = RF_SNOC_STREAMS;
    for (unsigned i = 0; i < RF_SNOC_STREAMS; ++i) {
        uint32_t smr = initial->smr[i], type = (initial->s2cr[i] >> 16) & 3u, bank = initial->s2cr[i] & 255u;
        if (type == 3 || (smr & 0x8000u) || (!type && bank >= RF_SNOC_CONTEXTS) ||
            rf_snoc_stream_matches(smr, 0xc0) || rf_snoc_stream_matches(smr, 0xc1)) { error = EPERM; goto failed; }
        if (!type) reserved[bank] = true;
        if (!(smr & 0x80000000u) && s->slot == RF_SNOC_STREAMS) s->slot = i;
    }
    for (unsigned i = 0; i < RF_SNOC_CONTEXTS; ++i) {
        const struct rf_snoc_bank *b = &initial->bank[i];
        if (!reserved[i] && !(b->sctlr & 1u) && !b->cbar && !b->cba2r &&
            !(b->fault & RF_SNOC_CONTEXT_FAULT)) { s->bank = i; break; }
    }
    if (s->bank == RF_SNOC_CONTEXTS || s->slot == RF_SNOC_STREAMS) { error = ENOSPC; goto failed; }
    /* Permanently consumed software lease. Never release or retry, including
     * failed readbacks. Every inherited foreign route/context stays exact. */
    s->leased = 1;
    for (unsigned step = 0; step < RF_SNOC_LEASE_STORES; ++step) {
        unsigned block = 0; uint32_t at = 0, value = 0, observed = 0;
        error = rf_snoc_lease_verify(s, o); if (error) goto failed;
        error = rf_snoc_lease_step(s, step, &block, &at, &value); if (error) goto failed;
        ++s->stores;
        error = o->write(o->context, block, at, value); if (error) goto failed;
        for (unsigned us = 0; us < 1000; ++us) {
            error = rf_snoc_lease_gate(s, o); if (error) goto failed;
            ++s->polls; error = o->read(o->context, block, at, &observed); if (error) goto failed;
            if (observed == value) break;
            error = o->delay(o->context, 1); if (error) goto failed;
        }
        if (observed != value) { error = EIO; goto failed; }
        switch (step) {
        case 0: s->expected.bank[s->bank].sctlr = value; break;
        case 1: s->expected.bank[s->bank].cba2r = value; break;
        case 2: s->expected.bank[s->bank].cbar = value; break;
        case 3: s->expected.s2cr[s->slot] = value; break;
        default: s->expected.smr[s->slot] = value; break;
        }
    }
    error = rf_snoc_lease_verify(s, o); if (error) goto failed;
    s->active = 1;
    return 0;
failed:
    s->poisoned = 1; s->active = 0;
    return error;
}
#endif
