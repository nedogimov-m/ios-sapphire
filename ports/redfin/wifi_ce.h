/* SPDX-License-Identifier: MIT
 * Read-only WCN3990-class CE state. Linux v6.12 adc21867 ath10k/hw.c.
 * Offsets are relative to WLAN+240000. Include after wifi_snoc.h.
 */
#ifndef REDFIN_WIFI_CE_H
#define REDFIN_WIFI_CE_H
#define RF_CE_BASE UINT64_C(0x18a40000)
#define RF_CE_MAP_BYTES 0x10000u
#define RF_CE_COUNT 12u
#define RF_CE_OBSERVED_REGS 17u
static const uint32_t rf_ce_observed_offsets[RF_CE_OBSERVED_REGS] = {
    0, 4, 8, 0x0c, 0x10, 0x14, 0x18, 0x2c, 0x30, 0x34, 0x38,
    0x3c, 0x40, 0x44, 0x48, 0x4c, 0x50};
struct rf_ce_snapshot {
    uint32_t stage, reads, error, changed_offset;
    uint32_t wrapper[3], ce[RF_CE_COUNT][RF_CE_OBSERVED_REGS];
    bool stable;
};
struct rf_ce_ops {
    void *context;
    int (*check)(void *);
    int (*read)(void *, uint32_t, uint32_t *);
};
/* Host configuration ownership from native snoc.c host_ce_config_wlan.
 * The opposite side of each CE remains live firmware state after HTT setup.
 * Read/write indices and status are deliberately absent from this mask. */
static inline uint32_t rf_ce_host_config_mask(uint32_t at, unsigned source_entries, unsigned dest_entries)
{
    switch (at) {
    case 0: case 8: return source_entries ? UINT32_MAX : 0;
    case 4: return source_entries ? 0x1fu : 0;
    case 0x0c: case 0x14: return dest_entries ? UINT32_MAX : 0;
    case 0x10: return dest_entries ? 0x1fu : 0;
    case 0x18: return (1u << 19) | (source_entries ? 0xffffu | (1u << 17) : 0) |
        (dest_entries ? 1u << 18 : 0);
    default: return 0;
    }
}
static inline bool rf_ce_read_allowed(uint32_t at)
{
    if (at & 3u) return false;
    if (at >= 0xc000) return at == 0xc000 || at == 0xc004 || at == 0xc008;
    for (unsigned i = 0; i < RF_CE_OBSERVED_REGS; ++i)
        if ((at & 0xfffu) == rf_ce_observed_offsets[i]) return true;
    return false;
}
static inline int rf_ce_sample(const struct rf_ce_ops *o, struct rf_ce_snapshot *s,
    uint32_t at, uint32_t *saved, bool compare)
{
    uint32_t value = 0;
    if (!rf_ce_read_allowed(at)) return EINVAL;
    int error = o->check(o->context);
    if (error) return error;
    ++s->reads; error = o->read(o->context, at, &value);
    if (error) return error;
    if (value == UINT32_MAX) return EIO;
    if (compare && value != *saved) { s->changed_offset = at; return EAGAIN; }
    *saved = value; return 0;
}
static inline int rf_ce_observe(const struct rf_ce_ops *o, struct rf_ce_snapshot *s)
{
    int error = EINVAL;
    if (!s) return EINVAL;
#ifdef __cplusplus
    *s = rf_ce_snapshot{};
#else
    *s = (struct rf_ce_snapshot){0};
#endif
    if (!o || !o->check || !o->read) goto done;
    for (unsigned pass = 0; pass < 2; ++pass) {
        s->stage = pass + 1u;
        for (unsigned i = 0; i < 3; ++i) {
            error = rf_ce_sample(o, s, 0xc000 + 4u*i, &s->wrapper[i], pass != 0);
            if (error) goto done;
        }
        for (unsigned ce = 0; ce < RF_CE_COUNT; ++ce) for (unsigned r = 0; r < RF_CE_OBSERVED_REGS; ++r) {
            error = rf_ce_sample(o, s, 0x1000u*ce + rf_ce_observed_offsets[r], &s->ce[ce][r], pass != 0);
            if (error) goto done;
        }
    }
    error = o->check(o->context);
    if (!error) { s->stage = 3; s->stable = true; }
done:
    s->error = (uint32_t)error; return error;
}
#endif
