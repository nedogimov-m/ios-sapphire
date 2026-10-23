/* SPDX-License-Identifier: MIT
 * Legacy Redfin ICNSS: indication registration -> MSA_INFO -> MSA_READY -> CAP.
 * Wire reference: Google msm 500b3a2059c1eec0fec08ec56add06320ea901a8,
 * icnss_qmi.c and wlan_firmware_service_v01.{c,h}. Include after wifi_qmi.h.
 * This fixed-permission profile performs QMI only: no MSA CPU mapping,
 * memory assignment, WLAN registers, supplies, mission mode or data DMA.
 */
#ifndef REDFIN_WIFI_WLFW_H
#define REDFIN_WIFI_WLFW_H
#define RF_WLFW_MSA_BASE UINT64_C(0x8ba00000)
#define RF_WLFW_MSA_BYTES 0x200000u
enum { RF_WLFW_IDLE, RF_WLFW_REGISTER, RF_WLFW_MSA_INFO, RF_WLFW_MSA_READY,
       RF_WLFW_CAP, RF_WLFW_COMPLETE, RF_WLFW_FAILED };
struct rf_wlfw_region { uint64_t base; uint32_t bytes, secure; };
struct rf_wlfw_setup {
    uint32_t stage, attempted, poisoned, registered, regions, msa_accepted, ready_indications, pin_indications;
    uint32_t fw_ready, msa_ready_ind, responses, ignored, already_registered;
    uint16_t transaction, waiting, result, error;
    uint64_t fw_status;
    struct rf_wlfw_region region[2];
    struct rf_wlfw_cap cap;
};
struct rf_wlfw_ops {
    void *context;
    int (*check)(void *);
    int (*send)(void *, const uint8_t *, uint32_t);
};
static inline uint64_t rf_wlfw_u64(const uint8_t *p)
{ return rf_qmi_u32(p) | (uint64_t)rf_qmi_u32(p + 4) << 32; }
static inline void rf_wlfw_put(uint8_t *p, uint64_t value, unsigned bytes)
{ for (unsigned i = 0; i < bytes; ++i) p[i] = (uint8_t)(value >> (8u * i)); }
static inline int rf_wlfw_gate(struct rf_wlfw_setup *s, const struct rf_wlfw_ops *o)
{
    if (!s || !o || !o->check || !o->send || s->poisoned) return -1;
    if (o->check(o->context)) { s->poisoned = 1; s->stage = RF_WLFW_FAILED; return -1; }
    return 0;
}
static inline int rf_wlfw_send(struct rf_wlfw_setup *s, const struct rf_wlfw_ops *o, unsigned stage)
{
    if (rf_wlfw_gate(s, o) || !s->attempted) return -1;
    if ((stage == RF_WLFW_REGISTER && (s->stage != RF_WLFW_IDLE || s->transaction)) ||
        (stage == RF_WLFW_MSA_INFO && (s->stage != RF_WLFW_REGISTER || !s->registered || s->transaction != 1)) ||
        (stage == RF_WLFW_MSA_READY && (s->stage != RF_WLFW_MSA_INFO || s->transaction != 2 || s->responses != 2)) ||
        (stage == RF_WLFW_CAP && (s->stage != RF_WLFW_MSA_READY || !s->msa_accepted || s->transaction != 3))) return -1;
    uint8_t data[48] = {0}; uint32_t used = 7;
    uint16_t message = stage == RF_WLFW_REGISTER ? 0x20 : stage == RF_WLFW_MSA_INFO ? 0x2d :
        stage == RF_WLFW_MSA_READY ? 0x2e : stage == RF_WLFW_CAP ? 0x24 : 0;
    if (!message || s->transaction >= 4) return -1;
    rf_wlfw_put(data + 1, ++s->transaction, 2); rf_wlfw_put(data + 3, message, 2);
    if (stage == RF_WLFW_REGISTER) {
        const uint8_t enables[] = {0x10, 0x13, 0x14};
        for (unsigned i = 0; i < 3; ++i) {
            data[used++] = enables[i]; data[used++] = 1; data[used++] = 0; data[used++] = 1;
        }
        data[used++] = 0x15; data[used++] = 4; data[used++] = 0;
        rf_wlfw_put(data + used, UINT32_C(0x4b4e454c), 4); used += 4;
    } else if (stage == RF_WLFW_MSA_INFO) {
        data[used++] = 1; data[used++] = 8; data[used++] = 0;
        rf_wlfw_put(data + used, RF_WLFW_MSA_BASE, 8); used += 8;
        data[used++] = 2; data[used++] = 4; data[used++] = 0;
        rf_wlfw_put(data + used, RF_WLFW_MSA_BYTES, 4); used += 4;
    }
    rf_wlfw_put(data + 5, used - 7u, 2);
    s->stage = stage; s->waiting = message;
    if (o->send(o->context, data, used) || rf_wlfw_gate(s, o)) {
        s->poisoned = 1; s->stage = RF_WLFW_FAILED; return -1;
    }
    return 0;
}
static inline int rf_wlfw_begin(struct rf_wlfw_setup *s, const struct rf_wlfw_ops *o)
{
    if (rf_wlfw_gate(s, o) || s->attempted || s->stage != RF_WLFW_IDLE) return -1;
    s->attempted = 1;
    return rf_wlfw_send(s, o, RF_WLFW_REGISTER);
}
/* 0 accepted, 1 unrelated/late response, -1 malformed or platform failure.
 * A valid QMI error is recorded as FAILED without pretending it was success. */
static inline int rf_wlfw_receive(struct rf_wlfw_setup *s, const struct rf_wlfw_ops *o,
    const uint8_t *data, uint32_t bytes)
{
    if (rf_wlfw_gate(s, o) || !s->attempted || !data || bytes < 7 || bytes > 4096 ||
        rf_qmi_u16(data + 5) != bytes - 7u) return -1;
    uint16_t transaction = rf_qmi_u16(data + 1), message = rf_qmi_u16(data + 3);
    if (data[0] != 2 && data[0] != 4) return -1;
    if (data[0] == 2 && (s->stage == RF_WLFW_COMPLETE || s->stage == RF_WLFW_FAILED ||
        transaction != s->transaction || message != s->waiting)) { ++s->ignored; return 1; }
    if (data[0] == 4 && message != 0x21 && message != 0x2b && message != 0x2c) { ++s->ignored; return 1; }
    if (data[0] == 2 && s->stage == RF_WLFW_CAP) {
        struct rf_wlfw_cap cap;
        if (rf_wlfw_cap_parse(&cap, data, bytes, s->transaction)) return -1;
        s->cap = cap; s->result = cap.result; s->error = cap.error; ++s->responses;
        s->stage = cap.result ? RF_WLFW_FAILED : RF_WLFW_COMPLETE;
        return 0;
    }
    uint32_t seen = 0, count = 0, offset = 0, length = 0;
    uint16_t result = 0, error = 0;
    uint64_t status = 0;
    struct rf_wlfw_region regions[2] = {{0, 0, 0}, {0, 0, 0}};
    if (data[0] == 4 && message == 0x21) {
        if (bytes != 7) return -1;
        s->fw_ready = 1; ++s->ready_indications; return 0;
    }
    for (uint32_t at = 7; at < bytes;) {
        if (bytes - at < 3) return -1;
        uint32_t size = rf_qmi_u16(data + at + 1), kind = data[at], bit = 0;
        const uint8_t *value = data + at + 3u;
        if (size > bytes - at - 3u) return -1;
        if (data[0] == 2 && kind == 2) {
            bit = 1; if (size != 4) return -1;
            result = rf_qmi_u16(value); error = rf_qmi_u16(value + 2);
            if (result > 1 || (!result && error)) return -1;
        } else if (data[0] == 2 && s->stage == RF_WLFW_REGISTER && kind == 0x10) {
            bit = 2; if (size != 8) return -1; status = rf_wlfw_u64(value);
        } else if (data[0] == 2 && s->stage == RF_WLFW_MSA_INFO && kind == 3) {
            bit = 2;
            if (!size || value[0] > 2 || size != 1u + 13u * value[0]) return -1;
            count = value[0];
            for (unsigned i = 0; i < count; ++i) {
                const uint8_t *entry = value + 1u + 13u * i;
                regions[i].base = rf_wlfw_u64(entry); regions[i].bytes = rf_qmi_u32(entry + 8); regions[i].secure = entry[12];
                if (regions[i].base < RF_WLFW_MSA_BASE || regions[i].base >= RF_WLFW_MSA_BASE + RF_WLFW_MSA_BYTES ||
                    regions[i].bytes > RF_WLFW_MSA_BASE + RF_WLFW_MSA_BYTES - regions[i].base || regions[i].secure > 1)
                    return -1;
                for (unsigned j = 0; j < i; ++j) if (regions[i].bytes && regions[j].bytes &&
                    regions[i].base < regions[j].base + regions[j].bytes &&
                    regions[j].base < regions[i].base + regions[i].bytes) return -1;
            }
        } else if (data[0] == 4 && message == 0x2b && kind == 0x10) {
            bit = 1; if (size != 4) return -1; offset = rf_qmi_u32(value);
        } else if (data[0] == 4 && message == 0x2b && kind == 0x11) {
            bit = 2; if (size != 2) return -1; length = rf_qmi_u16(value);
        } else if (data[0] == 4 && message == 0x2c && kind >= 0x10 && kind <= 0x12) {
            bit = 1u << (kind - 0x10u); if (size != 4) return -1;
        } else if (kind < 16) return -1;
        if (bit && (seen & bit)) return -1;
        seen |= bit; at += 3u + size;
    }
    if (data[0] == 4) {
        if (message == 0x2b) {
            if (offset > RF_WLFW_MSA_BYTES || length > RF_WLFW_MSA_BYTES - offset) return -1;
            s->msa_ready_ind = 1;
        } else ++s->pin_indications;
        return 0;
    }
    if (!(seen & 1u) || (!result && s->stage == RF_WLFW_MSA_INFO && !(seen & 2u))) return -1;
    s->result = result; s->error = error; ++s->responses;
    if (result) { s->stage = RF_WLFW_FAILED; return 0; }
    if (s->stage == RF_WLFW_REGISTER) {
        s->registered = 1; s->fw_status = status;
        if (status & 1u) { s->stage = RF_WLFW_FAILED; s->already_registered = 1; return 0; }
        if (status & 2u) s->fw_ready = 1;
        if (status & 4u) s->msa_ready_ind = 1;
        return rf_wlfw_send(s, o, RF_WLFW_MSA_INFO);
    }
    if (s->stage == RF_WLFW_MSA_INFO) {
        s->regions = count; memcpy(s->region, regions, sizeof(regions));
        return rf_wlfw_send(s, o, RF_WLFW_MSA_READY);
    }
    if (s->stage == RF_WLFW_MSA_READY) {
        s->msa_accepted = 1;
        return rf_wlfw_send(s, o, RF_WLFW_CAP);
    }
    return -1;
}
#endif
