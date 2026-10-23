/* SPDX-License-Identifier: MIT
 * Bounded Redfin CNSS DMON board-data exchange. Include after wifi_wlfw.h.
 * Wire: Google msm500b3a2 wlan_firmware_service_v01.{c,h}. Redfin daemon
 * reference9d38f1d7: DMON registration, MSA ready, CAP, BIN BDF, CAL_REPORT.
 * This zero-cache profile subscribes only to FW/MSA ready, as ath10k does;
 * it promises no calibration download/update or persistent calibration store.
 * No MMIO, MSA assignment, mission mode, DMA or storage operation is here.
 */
#ifndef REDFIN_WIFI_BDF_H
#define REDFIN_WIFI_BDF_H
#define RF_BDF_CLIENT UINT32_C(0x444d4f4e)
#define RF_BDF_PORT 0x4005u
#define RF_BDF_BYTES 26328u
#define RF_BDF_CHUNK 2048u
#define RF_BDF_PACKET (RF_BDF_CHUNK + 64u)
#define RF_BDF_SEGMENTS ((RF_BDF_BYTES + RF_BDF_CHUNK - 1u) / RF_BDF_CHUNK)
#define RF_BDF_NAME "image/bdwlan-u-redfin.bin"
enum { RF_BDF_IDLE, RF_BDF_REGISTER, RF_BDF_WAIT_MSA, RF_BDF_CAP,
       RF_BDF_DOWNLOAD, RF_BDF_CAL_REPORT, RF_BDF_COMPLETE, RF_BDF_FAILED };
struct rf_bdf_ops {
    void *context;
    int (*check)(void *);
    int (*send)(void *, const uint8_t *, uint32_t);
};
struct rf_bdf_session {
    const uint8_t *data;
    uint32_t bytes, stage, attempted, poisoned, registered, msa_ready, fw_ready, skipped_ready;
    uint32_t offset, segment, chunk, requests, responses, bdf_acks, cal_reported, ignored, indications;
    uint16_t transaction, waiting, result, error, last_indication;
    uint64_t fw_status;
    struct rf_wlfw_cap expected, cap;
    uint8_t packet[RF_BDF_PACKET];
};
static inline int rf_bdf_gate(struct rf_bdf_session *s, const struct rf_bdf_ops *o)
{
    if (!s || !o || !o->check || !o->send || s->poisoned) return -1;
    if (o->check(o->context)) { s->poisoned = 1; s->stage = RF_BDF_FAILED; return -1; }
    return 0;
}
static inline int rf_bdf_identity(const struct rf_wlfw_cap *cap)
{
    return cap && !cap->result && !cap->error && (cap->valid & 13u) == 13u &&
        cap->chip == 0x4320 && cap->family == 0x4001 && cap->soc == 0x400b0000 &&
        cap->firmware == 0x33197fff && (!(cap->valid & 2u) || cap->board == 0xff);
}
static inline void rf_bdf_number(struct rf_bdf_session *s, uint32_t *used, unsigned kind, uint64_t value, unsigned bytes)
{
    s->packet[(*used)++] = (uint8_t)kind;
    rf_wlfw_put(s->packet + *used, bytes, 2); *used += 2;
    rf_wlfw_put(s->packet + *used, value, bytes); *used += bytes;
}
static inline int rf_bdf_send(struct rf_bdf_session *s, const struct rf_bdf_ops *o, unsigned stage)
{
    if (rf_bdf_gate(s, o) || !s->attempted || !s->data || s->bytes != RF_BDF_BYTES || s->waiting ||
        s->transaction >= RF_BDF_SEGMENTS + 3u) return -1;
    uint16_t message = stage == RF_BDF_REGISTER ? 0x20 : stage == RF_BDF_CAP ? 0x24 :
        stage == RF_BDF_DOWNLOAD ? 0x25 : stage == RF_BDF_CAL_REPORT ? 0x26 : 0;
    if (!message ||
        (stage == RF_BDF_REGISTER && (s->stage != RF_BDF_IDLE || s->transaction)) ||
        (stage == RF_BDF_CAP && (s->stage != RF_BDF_WAIT_MSA || !s->registered || !s->msa_ready || s->transaction != 1)) ||
        (stage == RF_BDF_DOWNLOAD && (!rf_bdf_identity(&s->cap) || s->chunk || s->segment >= RF_BDF_SEGMENTS ||
            s->offset != s->segment * RF_BDF_CHUNK || s->offset >= s->bytes ||
            !((s->stage == RF_BDF_CAP && s->transaction == 2 && !s->offset) ||
              (s->stage == RF_BDF_DOWNLOAD && s->transaction == 2u + s->segment)))) ||
        (stage == RF_BDF_CAL_REPORT && (s->stage != RF_BDF_DOWNLOAD || s->chunk || s->offset != s->bytes ||
            s->segment != RF_BDF_SEGMENTS || s->transaction != 2u + RF_BDF_SEGMENTS))) return -1;
    uint32_t used = 7;
    memset(s->packet, 0, sizeof(s->packet));
    rf_wlfw_put(s->packet + 1, ++s->transaction, 2); rf_wlfw_put(s->packet + 3, message, 2);
    if (stage == RF_BDF_REGISTER) {
        rf_bdf_number(s, &used, 0x10, 1, 1); /* FW_READY. */
        rf_bdf_number(s, &used, 0x13, 1, 1); /* MSA_READY, no permission change. */
        rf_bdf_number(s, &used, 0x15, RF_BDF_CLIENT, 4);
    } else if (stage == RF_BDF_DOWNLOAD) {
        s->chunk = s->bytes - s->offset < RF_BDF_CHUNK ? s->bytes - s->offset : RF_BDF_CHUNK;
        rf_bdf_number(s, &used, 1, 1, 1);
        rf_bdf_number(s, &used, 0x10, 0, 4); /* Native BIN file_id0. */
        rf_bdf_number(s, &used, 0x11, s->bytes, 4); /* Full total, not remaining. */
        rf_bdf_number(s, &used, 0x12, s->segment, 4);
        s->packet[used++] = 0x13; rf_wlfw_put(s->packet + used, s->chunk + 2u, 2); used += 2;
        rf_wlfw_put(s->packet + used, s->chunk, 2); used += 2;
        memcpy(s->packet + used, s->data + s->offset, s->chunk); used += s->chunk;
        rf_bdf_number(s, &used, 0x14, s->offset + s->chunk == s->bytes, 1);
        rf_bdf_number(s, &used, 0x15, 0, 1); /* Native BIN type0. */
    } else if (stage == RF_BDF_CAL_REPORT) {
        rf_bdf_number(s, &used, 1, 0, 1); /* No cached calibration IDs. */
        rf_bdf_number(s, &used, 0x11, 0, 1); /* Native cal_remove_supported0. */
    }
    if (used > sizeof(s->packet)) return -1;
    rf_wlfw_put(s->packet + 5, used - 7u, 2);
    s->stage = stage; s->waiting = message; ++s->requests;
    if (o->send(o->context, s->packet, used) || rf_bdf_gate(s, o)) {
        s->poisoned = 1; s->stage = RF_BDF_FAILED; return -1;
    }
    return 0;
}
static inline int rf_bdf_begin(struct rf_bdf_session *s, const struct rf_bdf_ops *o,
    const uint8_t *data, uint32_t bytes, const struct rf_wlfw_cap *cap)
{
    if (rf_bdf_gate(s, o) || s->attempted || s->stage != RF_BDF_IDLE || !data ||
        bytes != RF_BDF_BYTES || !rf_bdf_identity(cap)) return -1;
    s->attempted = 1; s->data = data; s->bytes = bytes; s->expected = *cap;
    return rf_bdf_send(s, o, RF_BDF_REGISTER);
}
/* Every accepted reply advances at most one pending request. Nonzero QMI
 * results, including a final BDF CRC rejection, remain failures; no retry or
 * upstream CRC-error exception is adopted. FW_READY is an independent fact. */
static inline int rf_bdf_receive(struct rf_bdf_session *s, const struct rf_bdf_ops *o,
    const uint8_t *data, uint32_t bytes)
{
    if (rf_bdf_gate(s, o) || !s->attempted || !data || bytes < 7 || bytes > 4096 ||
        rf_qmi_u16(data + 5) != bytes - 7u || (data[0] != 2 && data[0] != 4)) return -1;
    uint16_t transaction = rf_qmi_u16(data + 1), message = rf_qmi_u16(data + 3);
    if (data[0] == 4 && message == 0x39) {
        s->poisoned = 1; s->stage = RF_BDF_FAILED; return -1;
    }
    if (s->stage == RF_BDF_FAILED) { ++s->ignored; return 1; }
    if (data[0] == 2 && (!s->waiting || s->stage == RF_BDF_COMPLETE ||
        transaction != s->transaction || message != s->waiting)) { ++s->ignored; return 1; }
    uint32_t seen = 0; uint16_t result = 0, error = 0; uint64_t status = 0;
    if (data[0] == 4 && message == 0x21) {
        if (bytes != 7) return -1;
        s->fw_ready = 1; ++s->indications; s->last_indication = message; return 0;
    }
    for (uint32_t at = 7; at < bytes;) {
        if (bytes - at < 3) return -1;
        uint32_t length = rf_qmi_u16(data + at + 1), kind = data[at], bit = 0;
        const uint8_t *value = data + at + 3u;
        if (length > bytes - at - 3u) return -1;
        if (data[0] == 2 && kind == 2) {
            bit = 1; if (length != 4) return -1;
            result = rf_qmi_u16(value); error = rf_qmi_u16(value + 2);
            if (result > 1 || (!result && error)) return -1;
        } else if (data[0] == 2 && kind == 0x10 && message != 0x24) {
            bit = 2; if (length != 8) return -1; status = rf_wlfw_u64(value);
        } else if (data[0] == 2 && kind < 16) return -1;
        else if (data[0] == 4 && message == 0x2b && (kind == 0x10 || kind == 0x11)) {
            bit = kind == 0x10 ? 1u : 2u;
            if (length != (kind == 0x10 ? 4u : 2u)) return -1;
        }
        if (bit && (seen & bit)) return -1;
        seen |= bit; at += 3u + length;
    }
    if (data[0] == 4) {
        ++s->indications; s->last_indication = message;
        if (message != 0x2b) { ++s->ignored; return 1; }
        s->msa_ready = 1;
        return s->stage == RF_BDF_WAIT_MSA ? rf_bdf_send(s, o, RF_BDF_CAP) : 0;
    }
    if (!(seen & 1u)) return -1;
    s->result = result; s->error = error; s->waiting = 0; ++s->responses;
    if (result) { s->stage = RF_BDF_FAILED; return 0; }
    if (s->stage == RF_BDF_REGISTER) {
        s->registered = 1; s->fw_status = status;
        s->fw_ready |= (status & 2u) != 0; s->msa_ready |= (status & 4u) != 0;
        if (s->fw_ready) { s->skipped_ready = 1; s->stage = RF_BDF_COMPLETE; return 0; }
        if (status & 1u) { s->stage = RF_BDF_FAILED; return 0; }
        s->stage = RF_BDF_WAIT_MSA;
        return s->msa_ready ? rf_bdf_send(s, o, RF_BDF_CAP) : 0;
    }
    if (s->stage == RF_BDF_CAP) {
        if (rf_wlfw_cap_parse(&s->cap, data, bytes, s->transaction) || !rf_bdf_identity(&s->cap) ||
            s->cap.chip != s->expected.chip || s->cap.family != s->expected.family ||
            s->cap.soc != s->expected.soc || s->cap.firmware != s->expected.firmware) return -1;
        return rf_bdf_send(s, o, RF_BDF_DOWNLOAD);
    }
    if (s->stage == RF_BDF_DOWNLOAD) {
        if (!s->chunk || s->offset > s->bytes || s->chunk > s->bytes - s->offset) return -1;
        s->offset += s->chunk; s->chunk = 0; ++s->segment; ++s->bdf_acks;
        return rf_bdf_send(s, o, s->offset == s->bytes ? RF_BDF_CAL_REPORT : RF_BDF_DOWNLOAD);
    }
    if (s->stage == RF_BDF_CAL_REPORT) { s->cal_reported = 1; s->stage = RF_BDF_COMPLETE; return 0; }
    return -1;
}
#endif
