/* SPDX-License-Identifier: MIT
 * WCN3990-class WLAN_CFG -> acknowledged mission mode, no CE/DMA operations.
 * Wire: native Google msm500b3a2 wlan_firmware_service_v01.{c,h}; layout:
 * Linux v6.12 adc21867 ath10k/snoc.c, also used by inherited TopazModem.cpp.
 * Include after wifi_bdf.h and wifi_snoc.h.
 */
#ifndef REDFIN_WIFI_MISSION_H
#define REDFIN_WIFI_MISSION_H
#define RF_MISSION_CFG_BYTES 559u
#define RF_MISSION_FIRST_TRANSACTION 6u
enum { RF_MISSION_IDLE, RF_MISSION_CONFIG, RF_MISSION_MODE, RF_MISSION_COMPLETE, RF_MISSION_FAILED };
static const uint32_t rf_mission_target[12][5] = {
    {0, 2, 32, 2048, 0}, {1, 1, 32, 2048, 0}, {2, 1, 64, 2048, 0}, {3, 2, 32, 2048, 0},
    {4, 2, 256, 256, 8}, {5, 2, 1024, 64, 8}, {6, 3, 32, 16384, 0}, {7, 4, 0, 0, 8},
    {8, 1, 32, 2048, 0}, {9, 1, 32, 2048, 0}, {10, 1, 32, 2048, 0}, {11, 1, 32, 2048, 0}};
static const uint32_t rf_mission_service[21][3] = {
    {0x104, 2, 3}, {0x104, 1, 2}, {0x102, 2, 3}, {0x102, 1, 2}, {0x101, 2, 3}, {0x101, 1, 2},
    {0x103, 2, 3}, {0x103, 1, 2}, {0x100, 2, 3}, {0x100, 1, 2}, {1, 2, 0}, {1, 1, 2},
    {0xfe00, 2, 0}, {0xfe00, 1, 2}, {0x300, 2, 4}, {0x300, 1, 1}, {0xfe00, 2, 5},
    {0x301, 1, 9}, {0x302, 1, 10}, {0x600, 1, 11}, {0, 0, 0}};
static const uint16_t rf_mission_shadow[12][2] = {
    {0, 0x3c}, {3, 0x3c}, {4, 0x3c}, {5, 0x3c}, {7, 0x3c}, {1, 0x40},
    {2, 0x40}, {7, 0x40}, {8, 0x40}, {9, 0x40}, {10, 0x40}, {11, 0x40}};
struct rf_mission_ops {
    void *context;
    int (*check)(void *);
    int (*send)(void *, const uint8_t *, uint32_t);
};
struct rf_mission {
    uint32_t attempted, stage, poisoned, requests, responses, ignored;
    uint16_t transaction, waiting, result, error;
    uint8_t packet[RF_MISSION_CFG_BYTES];
};
static inline int rf_mission_gate(struct rf_mission *s, const struct rf_mission_ops *o)
{
    if (!s || !o || !o->check || !o->send || s->poisoned) return -1;
    if (o->check(o->context)) { s->poisoned = 1; s->stage = RF_MISSION_FAILED; return -1; }
    return 0;
}
static inline int rf_mission_send(struct rf_mission *s, const struct rf_mission_ops *o, unsigned stage)
{
    if (rf_mission_gate(s, o) || !s->attempted || s->waiting ||
        !((stage == RF_MISSION_CONFIG && s->stage == RF_MISSION_IDLE && !s->transaction) ||
          (stage == RF_MISSION_MODE && s->stage == RF_MISSION_CONFIG && s->transaction == RF_MISSION_FIRST_TRANSACTION))) return -1;
    memset(s->packet, 0, sizeof(s->packet));
    uint32_t used = 7;
    s->transaction = (uint16_t)(stage == RF_MISSION_CONFIG ? RF_MISSION_FIRST_TRANSACTION : RF_MISSION_FIRST_TRANSACTION + 1u);
    s->waiting = (uint16_t)(stage == RF_MISSION_CONFIG ? 0x23 : 0x22);
    rf_wlfw_put(s->packet + 1, s->transaction, 2); rf_wlfw_put(s->packet + 3, s->waiting, 2);
    if (stage == RF_MISSION_CONFIG) {
        /* Native arrays have a single-byte count; reserved host struct fields
         * are not on the wire. host_version and v2 shadow/MSI stay absent. */
        for (unsigned which = 0; which < 3; ++which) {
            unsigned count = which == 1 ? 21u : 12u, columns = which == 0 ? 5u : which == 1 ? 3u : 2u;
            unsigned width = which == 2 ? 2u : 4u;
            s->packet[used++] = (uint8_t)(0x11u + which);
            rf_wlfw_put(s->packet + used, 1u + count * columns * width, 2); used += 2;
            s->packet[used++] = (uint8_t)count;
            for (unsigned i = 0; i < count; ++i) for (unsigned j = 0; j < columns; ++j) {
                uint32_t value = which == 0 ? rf_mission_target[i][j] : which == 1 ?
                    rf_mission_service[i][j] : rf_mission_shadow[i][j];
                rf_wlfw_put(s->packet + used, value, width); used += width;
            }
        }
        if (used != RF_MISSION_CFG_BYTES) return -1;
    } else {
        /* Mission0, hw_debug_valid1/hw_debug0, exactly as native ICNSS. */
        s->packet[used++] = 1; rf_wlfw_put(s->packet + used, 4, 2); used += 6;
        s->packet[used++] = 0x10; rf_wlfw_put(s->packet + used, 1, 2); used += 3;
    }
    rf_wlfw_put(s->packet + 5, used - 7u, 2); s->stage = stage; ++s->requests;
    if (o->send(o->context, s->packet, used) || rf_mission_gate(s, o)) {
        s->poisoned = 1; s->stage = RF_MISSION_FAILED; return -1;
    }
    return 0;
}
static inline int rf_mission_begin(struct rf_mission *s, const struct rf_mission_ops *o,
    const struct rf_wlfw_cap *cap, const struct rf_snoc_snapshot *snapshot)
{
    if (rf_mission_gate(s, o) || s->attempted || s->stage != RF_MISSION_IDLE || !rf_bdf_identity(cap) ||
        !snapshot || !snapshot->stable || snapshot->stage != 4 || snapshot->error ||
        snapshot->fault || snapshot->malformed_routes || snapshot->wlan_matches[0] || snapshot->wlan_matches[1]) return -1;
    /* This entry deliberately leaves WLAN unmatched in a faulting SMMU:
     * firmware can enter mission, but no inherited host route is granted. */
    if ((snapshot->control & 9u) || !(snapshot->control & 0x400u)) return -1;
    s->attempted = 1;
    return rf_mission_send(s, o, RF_MISSION_CONFIG);
}
static inline int rf_mission_receive(struct rf_mission *s, const struct rf_mission_ops *o,
    const uint8_t *data, uint32_t bytes)
{
    if (rf_mission_gate(s, o) || !s->attempted || !data || bytes < 7 || bytes > 4096 ||
        data[0] != 2 || rf_qmi_u16(data + 5) != bytes - 7u) return -1;
    if (s->stage == RF_MISSION_FAILED || !s->waiting || rf_qmi_u16(data + 1) != s->transaction ||
        rf_qmi_u16(data + 3) != s->waiting) { ++s->ignored; return 1; }
    unsigned seen = 0; uint16_t result = 0, error = 0;
    for (uint32_t at = 7; at < bytes;) {
        if (bytes - at < 3) return -1;
        unsigned kind = data[at], length = rf_qmi_u16(data + at + 1);
        if (length > bytes - at - 3u) return -1;
        if (kind == 2) {
            if (seen || length != 4) return -1;
            seen = 1; result = rf_qmi_u16(data + at + 3); error = rf_qmi_u16(data + at + 5);
            if (result > 1 || (!result && error)) return -1;
        } else if (kind < 16) return -1;
        at += 3u + length;
    }
    if (!seen) return -1;
    s->result = result; s->error = error; s->waiting = 0; ++s->responses;
    if (result) { s->stage = RF_MISSION_FAILED; return 0; }
    if (s->stage == RF_MISSION_CONFIG) return rf_mission_send(s, o, RF_MISSION_MODE);
    if (s->stage == RF_MISSION_MODE) { s->stage = RF_MISSION_COMPLETE; return 0; }
    return -1;
}
#endif
