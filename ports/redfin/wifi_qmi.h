/* SPDX-License-Identifier: MIT
 * Legacy ICNSS WLFW capability framing, QMI service0x45/v1/message0x24.
 * Pinned native icnss_qmi.c and preferred redwood_wlfw.c were reviewed.
 */
#ifndef REDFIN_WIFI_QMI_H
#define REDFIN_WIFI_QMI_H
#include <stdint.h>
#include <string.h>
struct rf_wlfw_cap {
    uint32_t valid, chip, family, board, soc, firmware;
    uint16_t result, error;
};
static inline uint16_t rf_qmi_u16(const uint8_t *p) { return (uint16_t)p[0] | (uint16_t)p[1] << 8; }
static inline uint32_t rf_qmi_u32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static inline int rf_wlfw_cap_parse(struct rf_wlfw_cap *out, const uint8_t *data, uint32_t bytes, uint16_t transaction)
{
    if (!out || !data || bytes < 7 || bytes > 4096 || data[0] != 2 ||
        rf_qmi_u16(data + 1) != transaction || rf_qmi_u16(data + 3) != 0x24 ||
        rf_qmi_u16(data + 5) != bytes - 7u) return -1;
    struct rf_wlfw_cap parsed;
    memset(&parsed, 0, sizeof(parsed));
    uint32_t seen = 0;
    for (uint32_t at = 7; at < bytes;) {
        if (bytes - at < 3) return -1;
        uint32_t length = rf_qmi_u16(data + at + 1), type = data[at], bit = 0;
        if (length > bytes - at - 3u) return -1;
        const uint8_t *value = data + at + 3u;
        if (type == 2) {
            bit = 1;
            if (length != 4) return -1;
            parsed.result = rf_qmi_u16(value); parsed.error = rf_qmi_u16(value + 2);
        } else if (type == 0x10) {
            bit = 2;
            if (length != 8) return -1;
            parsed.chip = rf_qmi_u32(value); parsed.family = rf_qmi_u32(value + 4); parsed.valid |= 1;
        } else if (type == 0x11 || type == 0x12) {
            bit = type == 0x11 ? 4u : 8u;
            if (length != 4) return -1;
            if (type == 0x11) { parsed.board = rf_qmi_u32(value); parsed.valid |= 2; }
            else { parsed.soc = rf_qmi_u32(value); parsed.valid |= 4; }
        } else if (type == 0x13) {
            bit = 16;
            if (length < 4 || length > 128) return -1;
            parsed.firmware = rf_qmi_u32(value); parsed.valid |= 8;
        }
        if (bit && (seen & bit)) return -1;
        seen |= bit; at += 3u + length;
    }
    if (!(seen & 1u) || parsed.result > 1 || (!parsed.result && parsed.error)) return -1;
    if (parsed.result) parsed.valid = 0;
    *out = parsed;
    return 0;
}
#endif
