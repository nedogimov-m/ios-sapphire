/* SPDX-License-Identifier: MIT
 * Native wire implementation; source/ordering reviewed at:
 * Google kernel/msm 500b3a2059c1eec0fec08ec56add06320ea901a8
 * drivers/mailbox/msm_qmp.c, drivers/soc/qcom/{qcom_ipcc,peripheral-loader}.c;
 * Lito DT afc98e2bb0716a57bf4f8d2b6191378dd7123ce4 qcom/lito.dtsi;
 * preferred HackiOS kernel 8e61187098f2c26c5daee8f9f72b6416aa64b9ab
 * redwood_wifi.c mailbox opening/sending (interface reference only).
 *
 * Redfin maps the full 4 KiB msgram from its own live DT. The remote-owned
 * descriptor/queue is never written. An ACK timeout leaves the sent length
 * intact and quarantines ownership; no speculative clear or channel reset.
 */
#include "wifi_aop.h"

#define AOP_MAGIC 0x4d41494cu
#define AOP_THEIR_LINK 0x0cu
#define AOP_THEIR_LINK_ACK 0x10u
#define AOP_THEIR_CHANNEL 0x14u
#define AOP_THEIR_CHANNEL_ACK 0x18u
#define AOP_THEIR_SIZE 0x1cu
#define AOP_THEIR_BOX 0x20u
#define AOP_OUR_LINK 0x24u
#define AOP_OUR_LINK_ACK 0x28u
#define AOP_OUR_CHANNEL 0x2cu
#define AOP_OUR_CHANNEL_ACK 0x30u
#define AOP_OUR_SIZE 0x34u
#define AOP_OUR_BOX 0x38u

static int valid_ops(const struct rf_wifi_aop_ops *ops, int writes)
{
    return ops && ops->check && ops->read32 &&
        (!writes || (ops->write32 && ops->notify_aop && ops->pause_us));
}

static int rd(const struct rf_wifi_aop_ops *ops, uint32_t offset, uint32_t *value)
{
    if (offset % 4u || offset > RF_WIFI_AOP_BYTES - 4u) return RF_WIFI_AOP_DESCRIPTOR;
    if (ops->check(ops->context) || ops->read32(ops->context, offset, value))
        return RF_WIFI_AOP_PLATFORM;
    return RF_WIFI_AOP_OK;
}

static int geometry(const struct rf_wifi_aop_snapshot *s)
{
    static const uint8_t state_index[] = {3, 4, 5, 6, 9, 10, 11, 12};
    if (s->word[0] != AOP_MAGIC || s->word[1] != 1 || s->word[2] || s->word[15])
        return RF_WIFI_AOP_DESCRIPTOR;
    for (unsigned i = 0; i < sizeof(state_index); ++i) {
        uint32_t value = s->word[state_index[i]];
        if (value != RF_WIFI_AOP_UP && value != RF_WIFI_AOP_DOWN)
            return RF_WIFI_AOP_DESCRIPTOR;
    }
    uint32_t rx = s->word[AOP_THEIR_BOX / 4u], rn = s->word[AOP_THEIR_SIZE / 4u];
    uint32_t tx = s->word[AOP_OUR_BOX / 4u], tn = s->word[AOP_OUR_SIZE / 4u];
    if (rx < 64 || tx < 64 || rx % 4u || tx % 4u || rn % 4u || tn % 4u ||
        rn < RF_WIFI_AOP_MESSAGE_BYTES + 4u || tn < RF_WIFI_AOP_MESSAGE_BYTES + 4u ||
        rx > RF_WIFI_AOP_BYTES || rn > RF_WIFI_AOP_BYTES - rx ||
        tx > RF_WIFI_AOP_BYTES || tn > RF_WIFI_AOP_BYTES - tx ||
        (rx < tx + tn && tx < rx + rn) || s->rx_length > rn - 4u || s->tx_length > tn - 4u)
        return RF_WIFI_AOP_DESCRIPTOR;
    return RF_WIFI_AOP_OK;
}

static int snapshot(const struct rf_wifi_aop_ops *ops, struct rf_wifi_aop_snapshot *s)
{
    for (unsigned i = 0; i < 16; ++i) {
        int error = rd(ops, 4u * i, &s->word[i]);
        if (error) return error;
    }
    /* Check geometry before the first indirect read. Queue values are filled
     * only after these offsets have been proved inside the 4 KiB mapping. */
    s->tx_length = s->rx_length = 0;
    int error = geometry(s);
    if (error) return error;
    error = rd(ops, s->word[AOP_OUR_BOX / 4u], &s->tx_length);
    if (!error) error = rd(ops, s->word[AOP_THEIR_BOX / 4u], &s->rx_length);
    return error ? error : geometry(s);
}

int rf_wifi_aop_observe(const struct rf_wifi_aop_ops *ops, struct rf_wifi_aop_snapshot *out)
{
    struct rf_wifi_aop_snapshot first, second;
    if (!out || !valid_ops(ops, 0)) return RF_WIFI_AOP_ARGUMENT;
    int error = snapshot(ops, &first);
    if (!error) error = snapshot(ops, &second);
    if (error) return error;
    for (unsigned i = 0; i < 16; ++i)
        if (first.word[i] != second.word[i]) return RF_WIFI_AOP_CHANGED;
    if (first.tx_length != second.tx_length || first.rx_length != second.rx_length)
        return RF_WIFI_AOP_CHANGED;
    *out = first;
    return RF_WIFI_AOP_OK;
}

static int poison(struct rf_wifi_aop_session *s, int error)
{
    s->poisoned = 1;
    s->error = error;
    return error;
}

/* Revalidate immutable geometry and all four APPS-owned descriptor words
 * before every store/notification/poll. Remote-owned ACKs may progress, but
 * AOP's link must remain up throughout the lease. No write trusts a cached
 * pointer alone, and no remote-owned descriptor field is ever a target. */
static int guard(struct rf_wifi_aop_session *s, const struct rf_wifi_aop_ops *ops)
{
    static const uint8_t stable[] = {0, 1, 2, 4, 6, 7, 8, 9, 11, 13, 14, 15};
    uint32_t value;
    for (unsigned i = 0; i < sizeof(stable); ++i) {
        int error = rd(ops, (uint32_t)stable[i] * 4u, &value);
        if (error) return error;
        if (value != s->baseline.word[stable[i]]) return RF_WIFI_AOP_CHANGED;
    }
    int error = rd(ops, AOP_THEIR_LINK, &value);
    if (error) return error;
    return value == RF_WIFI_AOP_UP ? RF_WIFI_AOP_OK : RF_WIFI_AOP_CHANGED;
}

static int connected(struct rf_wifi_aop_session *s, const struct rf_wifi_aop_ops *ops)
{
    static const uint8_t ready[] = {3, 4, 5, 6, 9, 10, 11, 12};
    uint32_t value;
    int error = guard(s, ops);
    if (error) return error;
    for (unsigned i = 0; i < sizeof(ready); ++i) {
        error = rd(ops, (uint32_t)ready[i] * 4u, &value);
        if (error) return error;
        if (value != RF_WIFI_AOP_UP) return RF_WIFI_AOP_CHANGED;
    }
    return RF_WIFI_AOP_OK;
}

static int store(struct rf_wifi_aop_session *s, const struct rf_wifi_aop_ops *ops,
    uint32_t offset, uint32_t value, int control)
{
    int error = guard(s, ops);
    if (error) return error;
    uint32_t box = s->baseline.word[AOP_OUR_BOX / 4u];
    if (control) {
        if ((offset != AOP_THEIR_LINK_ACK && offset != AOP_THEIR_CHANNEL_ACK &&
             offset != AOP_OUR_LINK && offset != AOP_OUR_CHANNEL) || value != RF_WIFI_AOP_UP)
            return RF_WIFI_AOP_ARGUMENT;
        if (s->baseline.word[offset / 4u] == value) return RF_WIFI_AOP_OK;
    } else if (!s->open || (offset != box &&
        (offset < box + 4u || offset >= box + 4u + RF_WIFI_AOP_MESSAGE_BYTES)) ||
        offset % 4u || (offset == box && value != RF_WIFI_AOP_MESSAGE_BYTES)) {
        return RF_WIFI_AOP_ARGUMENT;
    }
    if (ops->check(ops->context)) return RF_WIFI_AOP_PLATFORM;
    ++s->stores; /* An uncertain store must also prohibit retry. */
    if (ops->write32(ops->context, offset, value)) return RF_WIFI_AOP_PLATFORM;
    if (control || offset != box) {
        uint32_t readback;
        error = rd(ops, offset, &readback);
        if (error) return error;
        if (readback != value) return RF_WIFI_AOP_CHANGED;
        if (control) s->baseline.word[offset / 4u] = value;
    }
    return RF_WIFI_AOP_OK;
}

static int notify(struct rf_wifi_aop_session *s, const struct rf_wifi_aop_ops *ops)
{
    int error = guard(s, ops);
    if (error) return error;
    if (ops->check(ops->context)) return RF_WIFI_AOP_PLATFORM;
    ++s->notifications;
    return ops->notify_aop(ops->context) ? RF_WIFI_AOP_PLATFORM : RF_WIFI_AOP_OK;
}

static int poll_word(struct rf_wifi_aop_session *s, const struct rf_wifi_aop_ops *ops,
    uint32_t offset, uint32_t desired, uint32_t milliseconds)
{
    for (uint32_t elapsed = 0; elapsed <= milliseconds; ++elapsed) {
        uint32_t value;
        int error = guard(s, ops);
        if (!error) error = rd(ops, offset, &value);
        if (error) return error;
        if (value == desired) return RF_WIFI_AOP_OK;
        if (elapsed == milliseconds) break;
        if (ops->check(ops->context) || ops->pause_us(ops->context, 1000u))
            return RF_WIFI_AOP_PLATFORM;
    }
    return RF_WIFI_AOP_TIMEOUT;
}

int rf_wifi_aop_open(struct rf_wifi_aop_session *s, const struct rf_wifi_aop_ops *ops)
{
    if (!s || !valid_ops(ops, 1)) return RF_WIFI_AOP_ARGUMENT;
    if (s->attempted || s->poisoned || s->open) return RF_WIFI_AOP_STATE;
    s->attempted = 1;
    int error = rf_wifi_aop_observe(ops, &s->baseline);
    if (error) return poison(s, error);
    if (s->baseline.tx_length || s->baseline.rx_length) return poison(s, RF_WIFI_AOP_BUSY);
    if (s->baseline.word[AOP_THEIR_LINK / 4u] != RF_WIFI_AOP_UP)
        return poison(s, RF_WIFI_AOP_STATE);
    error = connected(s, ops);
    if (!error) { s->open = 1; return RF_WIFI_AOP_OK; }
    /* A fully closed APPS edge is the one supported negotiation starting
     * point. A partial handoff is observed/refused, never reset by this code. */
    static const uint8_t closed[] = {5, 6, 9, 10, 11, 12};
    for (unsigned i = 0; i < sizeof(closed); ++i)
        if (s->baseline.word[closed[i]] != RF_WIFI_AOP_DOWN)
            return poison(s, RF_WIFI_AOP_STATE);
    if (error != RF_WIFI_AOP_CHANGED) return poison(s, error);
#define AOP_STEP(operation) do { error = (operation); if (error) return poison(s, error); } while (0)
    AOP_STEP(store(s, ops, AOP_THEIR_LINK_ACK, RF_WIFI_AOP_UP, 1));
    AOP_STEP(store(s, ops, AOP_OUR_LINK, RF_WIFI_AOP_UP, 1));
    AOP_STEP(notify(s, ops));
    AOP_STEP(poll_word(s, ops, AOP_OUR_LINK_ACK, RF_WIFI_AOP_UP, RF_WIFI_AOP_HANDSHAKE_MS));
    AOP_STEP(store(s, ops, AOP_OUR_CHANNEL, RF_WIFI_AOP_UP, 1));
    AOP_STEP(notify(s, ops));
    AOP_STEP(poll_word(s, ops, AOP_THEIR_CHANNEL, RF_WIFI_AOP_UP, RF_WIFI_AOP_HANDSHAKE_MS));
    AOP_STEP(store(s, ops, AOP_THEIR_CHANNEL_ACK, RF_WIFI_AOP_UP, 1));
    AOP_STEP(notify(s, ops));
    AOP_STEP(poll_word(s, ops, AOP_OUR_CHANNEL_ACK, RF_WIFI_AOP_UP, RF_WIFI_AOP_HANDSHAKE_MS));
    AOP_STEP(connected(s, ops));
    s->open = 1;
#undef AOP_STEP
    return RF_WIFI_AOP_OK;
}

int rf_wifi_aop_load_state(struct rf_wifi_aop_session *s,
    const struct rf_wifi_aop_ops *ops, int on)
{
    static const char on_text[RF_WIFI_AOP_MESSAGE_BYTES] =
        "{class: image, res: load_state, name: modem, val: on}";
    static const char off_text[RF_WIFI_AOP_MESSAGE_BYTES] =
        "{class: image, res: load_state, name: modem, val: off}";
    if (!s || !valid_ops(ops, 1) || (on != 0 && on != 1)) return RF_WIFI_AOP_ARGUMENT;
    if (!s->open || s->poisoned || s->load_state != (on ? 0u : 1u)) return RF_WIFI_AOP_STATE;
    uint32_t box = s->baseline.word[AOP_OUR_BOX / 4u], value;
    const char *text = on ? on_text : off_text;
    int error = connected(s, ops);
    if (!error) error = rd(ops, box, &value);
    if (!error && value) error = RF_WIFI_AOP_BUSY;
    if (!error) error = rd(ops, s->baseline.word[AOP_THEIR_BOX / 4u], &value);
    if (!error && value) error = RF_WIFI_AOP_BUSY;
    if (error) return poison(s, error);
#define AOP_STEP(operation) do { error = (operation); if (error) return poison(s, error); } while (0)
    for (uint32_t i = 0; i < RF_WIFI_AOP_MESSAGE_BYTES; i += 4u) {
        uint32_t word = (uint8_t)text[i] | (uint32_t)(uint8_t)text[i + 1u] << 8 |
            (uint32_t)(uint8_t)text[i + 2u] << 16 | (uint32_t)(uint8_t)text[i + 3u] << 24;
        AOP_STEP(store(s, ops, box + 4u + i, word, 0));
    }
    /* Refuse another writer's message even if it appeared after the initial
     * empty check. The lease/descriptor checks still precede publication. */
    AOP_STEP(rd(ops, box, &value));
    if (value) return poison(s, RF_WIFI_AOP_BUSY);
    AOP_STEP(store(s, ops, box, RF_WIFI_AOP_MESSAGE_BYTES, 0));
    AOP_STEP(rd(ops, box, &value)); /* Visibility readback; a fast ACK may be zero. */
    if (value != 0 && value != RF_WIFI_AOP_MESSAGE_BYTES) return poison(s, RF_WIFI_AOP_CHANGED);
    AOP_STEP(notify(s, ops));
    AOP_STEP(poll_word(s, ops, box, 0, RF_WIFI_AOP_TX_MS));
    AOP_STEP(connected(s, ops));
    s->load_state = on ? 1u : 2u;
#undef AOP_STEP
    return RF_WIFI_AOP_OK;
}
