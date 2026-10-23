/* SPDX-License-Identifier: MIT
 * Redfin PIL bandwidth: native Google msm 500b3a2059c1eec0fec08ec56add06320ea901a8,
 * msm_bus_{arb,fabric}_rpmh.c and the live Lito bus graph. No hardware writes.
 * Include after the existing bounded redfin_rpmh.h CMD-DB parser.
 */
#ifndef REDFIN_WIFI_BW_H
#define REDFIN_WIFI_BW_H
#ifdef __cplusplus
#define RF_WIFI_BW_ZERO {}
#else
#define RF_WIFI_BW_ZERO {0}
#endif
#define RF_WIFI_BW_COUNT 6u
struct rf_wifi_bcm {
    uint32_t address, priority[2], unit;
    uint16_t width, version;
    uint8_t vcd, reserved;
    uint16_t padding;
};
static const uint8_t rf_wifi_bcm_names[RF_WIFI_BW_COUNT][8] = {
    "CE0", "SN6", "SN0", "SH0", "MC0", "ACV"};

static inline int rf_wifi_bcm_lookup(const volatile uint8_t *db, unsigned index,
    struct rf_wifi_bcm *out)
{
    if (!db || !out || index >= RF_WIFI_BW_COUNT) return -1;
    struct rf_cmddb_resource resource = RF_WIFI_BW_ZERO;
    if (rf_cmddb_lookup(db, RF_CMDDB_BYTES, rf_wifi_bcm_names[index], RF_CMDDB_BCM,
        &resource) != RF_CMDDB_OK || !resource.address || resource.address % 4u ||
        resource.aux_bytes != 8u) return -1;
    unsigned matches = 0;
    struct rf_wifi_bcm value = RF_WIFI_BW_ZERO;
    for (unsigned i = 0; i < 8; ++i) {
        const volatile uint8_t *h = db + 8u + i * 16u;
        unsigned type = rf_cmddb_u16(h), count = rf_cmddb_u16(h + 6u);
        if (!type) break;
        uint32_t entries = RF_CMDDB_HEADER + rf_cmddb_u16(h + 2u);
        uint32_t aux = RF_CMDDB_HEADER + rf_cmddb_u16(h + 4u);
        if (count > RF_CMDDB_MAX_ENTRIES ||
            !rf_cmddb_range(entries, count * RF_CMDDB_ENTRY, RF_CMDDB_BYTES)) return -1;
        for (unsigned j = 0; j < count; ++j) {
            const volatile uint8_t *entry = db + entries + j * RF_CMDDB_ENTRY;
            unsigned same = 1;
            for (unsigned k = 0; k < 8; ++k) same &= entry[k] == rf_wifi_bcm_names[index][k];
            if (!same) continue;
            if (++matches != 1 || rf_cmddb_u32(entry + 16u) != resource.address ||
                rf_cmddb_u16(entry + 20u) != 8u) return -1;
            uint32_t at = aux + rf_cmddb_u16(entry + 22u);
            if (!rf_cmddb_range(at, 8, RF_CMDDB_BYTES)) return -1;
            value.address = resource.address;
            value.priority[0] = resource.priority[0]; value.priority[1] = resource.priority[1];
            value.version = resource.aux_version;
            value.unit = rf_cmddb_u32(db + at); value.width = rf_cmddb_u16(db + at + 4u);
            value.vcd = db[at + 6u]; value.reserved = db[at + 7u];
        }
    }
    if (matches != 1 || !value.unit || !value.width || value.vcd >= 16 || value.reserved) return -1;
    *out = value;
    return 0;
}

static inline uint64_t rf_wifi_bw_div(uint64_t value, uint64_t divisor)
{ return value / divisor + (value % divisor != 0); }

static inline uint32_t rf_wifi_bcm_vote(const struct rf_wifi_bcm *bcm, unsigned index)
{
    /* Native SCM crypto client: AB=393.6 MB/s, IB=3936 MB/s. Native modem
     * LLCC->EBI request: AB=0, IB=8,171,520 KB/s. Shared MC0 uses both clients.
     * Widths and aggregation ports are checked against the live bus graph.
     */
    static const uint8_t width[RF_WIFI_BW_COUNT] = {8, 16, 16, 16, 4, 4};
    static const uint8_t ports[RF_WIFI_BW_COUNT] = {1, 1, 1, 2, 2, 2};
    if (!bcm || index >= RF_WIFI_BW_COUNT || !bcm->unit || !bcm->width) return 0;
    if (index == 5) return 0x60000008u; /* Native APPS ACV bit; preserve other bits below. */
    uint64_t ib = index == 4 ? UINT64_C(8171520000) : UINT64_C(3936000000);
    uint64_t x = rf_wifi_bw_div(UINT64_C(393600000) * bcm->width,
        (uint64_t)width[index] * ports[index]);
    uint64_t y = rf_wifi_bw_div(ib * bcm->width, width[index]);
    x = rf_wifi_bw_div(x, bcm->unit); y = rf_wifi_bw_div(y, bcm->unit);
    if (x > 0x3fff) x = 0x3fff;
    if (y > 0x3fff) y = 0x3fff;
    return 0x60000000u | (uint32_t)(x << 14) | (uint32_t)y;
}

static inline int rf_wifi_bcm_floor(unsigned index, uint32_t desired, uint32_t inherited,
    uint32_t *out)
{
    if (!out || index >= RF_WIFI_BW_COUNT || (inherited & ~0x6fffffffu) ||
        ((inherited & 0x0fffffffu) && !(inherited & 0x20000000u)) ||
        (desired & 0x60000000u) != 0x60000000u) return -1;
    uint32_t x = (desired >> 14) & 0x3fff, y = desired & 0x3fff;
    uint32_t old_x = (inherited >> 14) & 0x3fff, old_y = inherited & 0x3fff;
    if (index == 5) {
        if (x || old_x) return -1;
        y |= old_y;
    } else {
        if (x < old_x) x = old_x;
        if (y < old_y) y = old_y;
    }
    *out = 0x60000000u | (x << 14) | y;
    return 0;
}
#endif
