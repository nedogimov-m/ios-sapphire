/* SPDX-License-Identifier: MIT
 * Native implementation from the wire/ordering contracts reviewed at Google
 * kernel/msm 500b3a2059c1eec0fec08ec56add06320ea901a8: smem.c, smp2p.c,
 * subsys-pil-tz.c, qcom_ipcc.c, qcom_hwspinlock.c; Lito DT
 * afc98e2bb0716a57bf4f8d2b6191378dd7123ce4. The stable HackiOS kernel
 * 8e61187098f2c26c5daee8f9f72b6416aa64b9ab redwood_wifi.c was reviewed for
 * SMP2P interface/serialization; its WPSS IDs/addresses are not reused.
 */
#include "wifi_smp2p.h"

#define SMP_MAGIC 0x504d5324u
#define SMP_VALID_VERSION 0x101u
#define SMP_FATAL 1u
#define SMP_READY 2u
#define SMP_HANDOVER 4u
#define SMP_STOP_ACK 8u
#define SMP_MASTER_VALUE 36u
#define SMP_IPA_VALUE 56u

struct smp_heap {
    uint32_t partition, bytes, cacheline, free_u, free_c;
    uint32_t version, toc_count, toc_entry;
    uint32_t out, out_bytes, in, in_bytes;
    uint32_t out_cached, in_cached, glink;
};
static uint32_t remote_pid(const struct rf_wifi_smp2p_session *s)
{return s->remote_pid?s->remote_pid:1u;}
static uint32_t input_item(const struct rf_wifi_smp2p_session *s)
{return remote_pid(s)==2?443u:RF_WIFI_SMP2P_IN;}
static uint32_t output_item(const struct rf_wifi_smp2p_session *s)
{return remote_pid(s)==2?429u:RF_WIFI_SMP2P_OUT;}

static int valid_ops(const struct rf_wifi_smp2p_ops *o)
{
    return o && o->smem && o->smem_bytes == REDFIN_SMEM_BYTES && o->check &&
        o->pas_reset && o->pas_started && o->lock && o->unlock && o->write32 &&
        o->barrier && o->kick && o->now_ms && o->pause_us;
}
static int gate(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    if(remote_pid(s)>2 || (s->attempted && s->bound_pid!=remote_pid(s)))return RF_WIFI_SMP2P_STATE;
    int error = o->check(o->context);
    if (error) s->platform_error = error;
    return error ? RF_WIFI_SMP2P_PLATFORM : RF_WIFI_SMP2P_OK;
}
static int poison(struct rf_wifi_smp2p_session *s, int error)
{
    s->poisoned = 1; s->error = error; s->stage = RF_WIFI_SMP2P_QUARANTINED;
    return error;
}
static uint32_t word(const struct rf_wifi_smp2p_ops *o, uint32_t offset)
{ return redfin_smem_u32(o->smem + offset); }
static int observe_item(const struct rf_wifi_smp2p_session *s, struct smp_heap *h, uint32_t item, uint32_t data, uint32_t bytes, int cached)
{
    if (item == output_item(s)) {
        if (h->out) return RF_WIFI_SMP2P_SMEM;
        h->out = data; h->out_bytes = bytes; h->out_cached = cached != 0;
    }
    if (item == input_item(s)) {
        if (h->in) return RF_WIFI_SMP2P_SMEM;
        h->in = data; h->in_bytes = bytes; h->in_cached = cached != 0;
    }
    if ((item == output_item(s) || item == input_item(s)) && (data % 4u || bytes != RF_WIFI_SMP2P_BYTES))
        return RF_WIFI_SMP2P_SMEM;
    return RF_WIFI_SMP2P_OK;
}

/* Source-backed host selection: the already-observed APPS/MODEM private heap,
 * never another host or a global fallback. Metadata/FIFO geometry is first
 * validated by the existing native SMEM parser; both uncached and cached item
 * lists are then searched with a combined 4096-item bound. */
static int heap(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o, struct smp_heap *h)
{
    struct redfin_smem_report report;
    int error = gate(s, o);
    if (error) return error;
    enum redfin_smem_status status = redfin_smem_inspect_host(o->smem, o->smem_bytes, remote_pid(s), &report);
    if (status == REDFIN_SMEM_CHANGED) return RF_WIFI_SMP2P_UNSTABLE;
    if (status != REDFIN_SMEM_OK || !report.modem_partition) return RF_WIFI_SMP2P_SMEM;
    h->partition = report.partition_offset; h->bytes = report.partition_bytes;
    h->cacheline = report.entry_cacheline; h->free_u = report.free_uncached; h->free_c = report.free_cached;
    h->version = report.version; h->toc_count = report.partitions;
    h->toc_entry = REDFIN_SMEM_BYTES - 4096u + 32u + 48u * report.entry_index;
    h->out = h->out_bytes = h->in = h->in_bytes = h->out_cached = h->in_cached = 0;
    h->glink = report.descriptor || report.tx_bytes || report.rx_bytes;
    uint32_t cursor = 32, count = 0;
    while (cursor < h->free_u) {
        if (++count > REDFIN_SMEM_MAX_ITEMS || h->free_u - cursor < 16) return RF_WIFI_SMP2P_SMEM;
        const volatile uint8_t *entry = o->smem + h->partition + cursor;
        uint32_t size = redfin_smem_u32(entry + 4), padding = redfin_smem_u16(entry + 8);
        uint32_t header = redfin_smem_u16(entry + 10), remaining = h->free_u - cursor - 16u;
        if (redfin_smem_u16(entry) != 0xa5a5u || !size || padding >= size ||
            header > remaining || size > remaining - header) return RF_WIFI_SMP2P_SMEM;
        error = observe_item(s, h, redfin_smem_u16(entry + 2), h->partition + cursor + 16u + header, size - padding, 0);
        if (error) return error;
        cursor += 16u + header + size;
    }
    if (h->free_c < h->bytes) {
        uint32_t line = h->cacheline;
        if (line < 16 || line > 4096 || (line & (line - 1u)) || line > h->bytes - h->free_c)
            return RF_WIFI_SMP2P_SMEM;
        cursor = h->bytes - line;
        for (;;) {
            if (++count > REDFIN_SMEM_MAX_ITEMS || cursor < h->free_c || h->bytes - cursor < 16)
                return RF_WIFI_SMP2P_SMEM;
            const volatile uint8_t *entry = o->smem + h->partition + cursor;
            uint32_t size = redfin_smem_u32(entry + 4), padding = redfin_smem_u16(entry + 8);
            if (redfin_smem_u16(entry) != 0xa5a5u || !size || padding >= size || size > cursor - h->free_c)
                return RF_WIFI_SMP2P_SMEM;
            uint32_t data = cursor - size;
            error = observe_item(s, h, redfin_smem_u16(entry + 2), h->partition + data, size - padding, 1);
            if (error) return error;
            if (data == h->free_c) break;
            if (data <= h->free_c + line) return RF_WIFI_SMP2P_SMEM;
            cursor = data - line;
        }
    }
    if (word(o, h->partition + 12u) != h->free_u || word(o, h->partition + 16u) != h->free_c)
        return RF_WIFI_SMP2P_UNSTABLE;
    return gate(s, o);
}

static int own(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    int error = gate(s, o);
    if (error) return error;
    const uint32_t toc = REDFIN_SMEM_BYTES - 4096u;
    if (s->partition < 4096u || s->partition > toc || s->partition_bytes < 32u ||
        s->partition_bytes > toc - s->partition || !s->data ||
        s->entry != s->data - 16u || s->data < s->partition + 48u ||
        s->partition_bytes < RF_WIFI_SMP2P_PADDED ||
        s->data > s->partition + s->partition_bytes - RF_WIFI_SMP2P_PADDED ||
        s->toc_entry < toc + 32u || s->toc_entry > toc + 32u + 63u * 48u)
        return RF_WIFI_SMP2P_CHANGED;
    uint32_t free_u = word(o, s->partition + 12u), free_c = word(o, s->partition + 16u);
    if (!s->data || s->data < s->partition + 48u ||
        s->data > s->partition + s->partition_bytes - RF_WIFI_SMP2P_PADDED ||
        word(o, s->entry) != (output_item(s) << 16 | 0xa5a5u) ||
        word(o, s->entry + 4u) != RF_WIFI_SMP2P_PADDED || word(o, s->entry + 8u) != 4u ||
        word(o, s->entry + 12u) || word(o, s->partition) != 0x54525024u ||
        word(o, s->partition + 4u) != s->hosts ||
        word(o, s->partition + 8u) != s->partition_bytes ||
        free_u < s->data + RF_WIFI_SMP2P_PADDED - s->partition || free_u > free_c || free_c > s->partition_bytes ||
        word(o, 0x5cu) != s->version || word(o, 0xc0u) != 1u ||
        word(o, REDFIN_SMEM_BYTES - 4096u) != 0x434f5424u ||
        word(o, REDFIN_SMEM_BYTES - 4092u) != 1u ||
        word(o, REDFIN_SMEM_BYTES - 4088u) != s->toc_count)
        return RF_WIFI_SMP2P_CHANGED;
    for (unsigned i = 0; i < 12; ++i)
        if (word(o, s->toc_entry + 4u * i) != s->toc[i]) return RF_WIFI_SMP2P_CHANGED;
    for (unsigned i = 0; i < RF_WIFI_SMP2P_WORDS; ++i)
        if (word(o, s->data + 4u * i) != s->own[i]) return RF_WIFI_SMP2P_CHANGED;
    return gate(s, o);
}
static int barrier(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    int error = gate(s, o);
    if (error) return error;
    error = o->barrier(o->context);
    if (error) s->platform_error = error;
    return error ? RF_WIFI_SMP2P_PLATFORM : RF_WIFI_SMP2P_OK;
}
static int kick(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    int error = own(s, o);
    if (!error) error = barrier(s, o);
    if (error) return error;
    ++s->kicks;
    error = o->kick(o->context);
    if (error) s->platform_error = error;
    return error ? RF_WIFI_SMP2P_PLATFORM : RF_WIFI_SMP2P_OK;
}
static int put_initial(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o,
    uint32_t offset, uint32_t value)
{
    int error = gate(s, o);
    if (error) return error;
    if (!s->allocator_locked || s->stage != RF_WIFI_SMP2P_PREPARING || offset % 4u ||
        (offset != s->partition + 12u && (offset < s->entry ||
         offset >= s->data + RF_WIFI_SMP2P_PADDED))) return RF_WIFI_SMP2P_STATE;
    ++s->stores;
    error = o->write32(o->context, offset, value);
    if (error) { s->platform_error = error; return RF_WIFI_SMP2P_PLATFORM; }
    return word(o, offset) == value ? RF_WIFI_SMP2P_OK : RF_WIFI_SMP2P_CHANGED;
}
static int update(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o,
    uint32_t relative, uint32_t value)
{
    int error = own(s, o);
    if (error) return error;
    if ((relative != 4u || (value != 1u && value != SMP_VALID_VERSION)) &&
        (relative != 16u || (value != 0u && value != 2u)) &&
        (relative != SMP_MASTER_VALUE || (value != 0u && value != 1u)) &&
        (relative != SMP_IPA_VALUE || value != 1u || s->stage != RF_WIFI_SMP2P_READY))
        return RF_WIFI_SMP2P_ARGUMENT;
    if (s->own[relative / 4u] == value) return RF_WIFI_SMP2P_OK;
    ++s->stores;
    error = o->write32(o->context, s->data + relative, value);
    if (error) { s->platform_error = error; return RF_WIFI_SMP2P_PLATFORM; }
    if (word(o, s->data + relative) != value) return RF_WIFI_SMP2P_CHANGED;
    s->own[relative / 4u] = value;
    return barrier(s, o);
}
static uint32_t text_word(const char *text, unsigned size, unsigned at)
{
    uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) if (at + i < size) value |= (uint32_t)(uint8_t)text[at + i] << (8u * i);
    return value;
}

int rf_wifi_smp2p_cold(struct rf_wifi_smp2p_session *s,const struct rf_wifi_smp2p_ops *o)
{
    if(!s||!valid_ops(o))return RF_WIFI_SMP2P_ARGUMENT;
    if(s->attempted||s->stage!=RF_WIFI_SMP2P_IDLE||s->poisoned)return RF_WIFI_SMP2P_STATE;
    struct smp_heap h;int error=heap(s,o,&h);
    if(error)return error;
    return h.out||h.in||h.glink||h.free_c!=h.bytes?RF_WIFI_SMP2P_BUSY:gate(s,o);
}

int rf_wifi_smp2p_prepare(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    if (!s || !valid_ops(o)) return RF_WIFI_SMP2P_ARGUMENT;
    if (s->attempted || s->stage != RF_WIFI_SMP2P_IDLE) return RF_WIFI_SMP2P_STATE;
    s->bound_pid=remote_pid(s);
    s->attempted = 1; s->stage = RF_WIFI_SMP2P_PREPARING;
    int error = gate(s, o);
    if (!error && o->pas_reset(o->context)) error = RF_WIFI_SMP2P_STATE;
    if (error) return poison(s, error);
    error = o->lock(o->context, 1000u);
    if (error) { s->platform_error = error; return poison(s, RF_WIFI_SMP2P_PLATFORM); }
    s->allocator_locked = 1;
    struct smp_heap h;
    error = heap(s, o, &h);
    if (!error && (h.out || h.in || h.glink || h.free_c != h.bytes)) error = RF_WIFI_SMP2P_BUSY;
    if (!error && ((h.partition | h.free_u) & 7u)) error = RF_WIFI_SMP2P_SMEM;
    if (!error && h.free_c - h.free_u < 16u + RF_WIFI_SMP2P_PADDED) error = RF_WIFI_SMP2P_SPACE;
    if (!error) {
        s->partition = h.partition; s->partition_bytes = h.bytes; s->cacheline = h.cacheline;
        s->hosts = word(o, h.partition + 4u); s->version = h.version;
        s->toc_count = h.toc_count; s->toc_entry = h.toc_entry;
        for (unsigned i = 0; i < 12; ++i) s->toc[i] = word(o, h.toc_entry + 4u * i);
        s->entry = h.partition + h.free_u; s->data = s->entry + 16u;
        for (unsigned i = 0; i < RF_WIFI_SMP2P_WORDS; ++i) s->own[i] = 0;
        s->own[0] = SMP_MAGIC; s->own[1] = 0x100u; s->own[2] = remote_pid(s) << 16;
        s->own[3] = 16u | (remote_pid(s)==2?1u:2u) << 16;
        for (unsigned i = 0; i < 4; ++i) {
            s->own[5u + i] = text_word("master-kernel", 13, 4u * i);
            if(remote_pid(s)==1)s->own[10u + i] = text_word("ipa", 3, 4u * i);
        }
        /* Data has invalid version until allocation metadata is published. */
        for (unsigned i = 0; i < RF_WIFI_SMP2P_WORDS && !error; ++i)
            error = put_initial(s, o, s->data + 4u * i, s->own[i]);
        const uint32_t header[4] = {output_item(s) << 16 | 0xa5a5u, RF_WIFI_SMP2P_PADDED, 4, 0};
        for (unsigned i = 0; i < 4 && !error; ++i) error = put_initial(s, o, s->entry + 4u * i, header[i]);
        if (!error) error = barrier(s, o);
        if (!error && o->pas_reset(o->context)) error = RF_WIFI_SMP2P_STATE;
        if (!error) error = put_initial(s, o, s->partition + 12u, h.free_u + 16u + RF_WIFI_SMP2P_PADDED);
        if (!error) error = barrier(s, o);
        if (!error) error = put_initial(s, o, s->data + 4u, SMP_VALID_VERSION);
        if (!error) { s->own[1] = SMP_VALID_VERSION; error = barrier(s, o); }
    }
    int unlocked = o->unlock(o->context);
    s->allocator_locked = 0;
    if (unlocked) { s->platform_error = unlocked; error = RF_WIFI_SMP2P_PLATFORM; }
    if (error) return poison(s, error);
    s->stage = RF_WIFI_SMP2P_PREPARED;
    error = kick(s, o);
    return error ? poison(s, error) : RF_WIFI_SMP2P_OK;
}

int rf_wifi_smp2p_auth_begin(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    if (!s || !valid_ops(o)) return RF_WIFI_SMP2P_ARGUMENT;
    if (s->stage != RF_WIFI_SMP2P_PREPARED || s->poisoned) return RF_WIFI_SMP2P_STATE;
    struct smp_heap h;
    int error = own(s, o);
    if (!error && o->pas_reset(o->context)) error = RF_WIFI_SMP2P_STATE;
    if (!error) error = heap(s, o, &h);
    if (!error && (h.in || h.out != s->data || h.out_cached)) error = RF_WIFI_SMP2P_BUSY;
    if (error) return poison(s, error);
    s->stage = RF_WIFI_SMP2P_ARMED;
    return RF_WIFI_SMP2P_OK;
}

static int peer(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o, uint32_t *state)
{
    struct smp_heap h;
    int error = heap(s, o, &h);
    if (error) return error;
    error = own(s, o);
    if (error) return error;
    if (h.out != s->data || h.out_cached || h.partition != s->partition || h.bytes != s->partition_bytes ||
        h.cacheline != s->cacheline)
        return RF_WIFI_SMP2P_CHANGED;
    if (!h.in) return RF_WIFI_SMP2P_NOT_FOUND;
    if (s->peer && h.in != s->peer) return RF_WIFI_SMP2P_RESTART;
    uint32_t first[RF_WIFI_SMP2P_BYTES / 4u], second[RF_WIFI_SMP2P_BYTES / 4u];
    for (unsigned i = 0; i < RF_WIFI_SMP2P_BYTES / 4u; ++i) first[i] = word(o, h.in + 4u * i);
    error = gate(s, o);
    if (error) return error;
    for (unsigned i = 0; i < RF_WIFI_SMP2P_BYTES / 4u; ++i) second[i] = word(o, h.in + 4u * i);
    for (unsigned i = 0; i < RF_WIFI_SMP2P_BYTES / 4u; ++i) if (first[i] != second[i]) return RF_WIFI_SMP2P_UNSTABLE;
    if (!(first[1] & 255u)) return s->peer_seen ? RF_WIFI_SMP2P_RESTART : RF_WIFI_SMP2P_UNSTABLE;
    if (first[0] != SMP_MAGIC || (first[1] & 255u) != 1u || first[2] != remote_pid(s) ||
        (first[3] & 65535u) != 16u || first[3] >> 16 > 16u || (first[4] & ~3u))
        return RF_WIFI_SMP2P_BAD_PEER;
    uint32_t features = first[1] >> 8 & 1u, restart = first[4] & 1u, valid = first[3] >> 16;
    if (s->peer_seen && (features != s->peer_features || restart != s->peer_restart || valid < s->peer_valid))
        return RF_WIFI_SMP2P_RESTART;
    uint8_t names[16][16];
    uint32_t slave = 0, found = 0, ipa = 0, ipa_found = 0, wlan = 0, wlan_found = 0;
    for (unsigned i = 0; i < valid; ++i) {
        int terminated = 0;
        for (unsigned j = 0; j < 16; ++j) {
            uint8_t value = (uint8_t)(first[5u + 5u * i + j / 4u] >> (8u * (j % 4u)));
            if (!value) terminated = 1;
            else if (terminated || value < 32u || value > 126u) return RF_WIFI_SMP2P_BAD_PEER;
            names[i][j] = value;
            if (i < s->peer_valid && value != s->names[i][j]) return RF_WIFI_SMP2P_RESTART;
        }
        if (!names[i][0] || !terminated) return RF_WIFI_SMP2P_BAD_PEER;
        for (unsigned previous = 0; previous < i; ++previous) {
            unsigned different = 0;
            for (unsigned j = 0; j < 16; ++j) different |= names[i][j] ^ names[previous][j];
            if (!different) return RF_WIFI_SMP2P_BAD_PEER;
        }
        static const uint8_t slave_name[16] = "slave-kernel";
        unsigned different = 0;
        for (unsigned j = 0; j < 16; ++j) different |= names[i][j] ^ slave_name[j];
        if (!different) { slave = i; found = 1; }
        static const uint8_t ipa_name[16] = "ipa";
        different = 0;
        for (unsigned j = 0; j < 16; ++j) different |= names[i][j] ^ ipa_name[j];
        if (!different) { ipa = i; ipa_found = 1; }
        static const uint8_t wlan_name[16] = "wlan";
        different = 0;
        for (unsigned j = 0; j < 16; ++j) different |= names[i][j] ^ wlan_name[j];
        if (!different) { wlan = i; wlan_found = 1; }
    }
    uint32_t state_value = found ? first[9u + 5u * slave] : 0;
    if (state_value & SMP_FATAL) return RF_WIFI_SMP2P_FATAL;
    if (s->slave_found && (!found || slave != s->slave_index)) return RF_WIFI_SMP2P_RESTART;
    int negotiated = 0;
    if (!s->peer_seen) {
        uint32_t old_stores = s->stores;
        error = update(s, o, 4, features << 8 | 1u);
        if (!error && features) error = update(s, o, 16, restart ? 2u : 0u);
        if (!error && s->stores != old_stores) error = kick(s, o);
        if (error) return error;
        s->peer_seen = 1; s->peer_features = features; s->peer_restart = restart; s->peer = h.in;
        negotiated = s->stores != old_stores;
    }
    s->peer_valid = valid;
    for (unsigned i = 0; i < valid; ++i)
        for (unsigned j = 0; j < 16; ++j) s->names[i][j] = names[i][j];
    s->slave_found = found; s->slave_index = slave; s->last_state = state_value;
    s->handover |= (state_value & SMP_HANDOVER) != 0;
    s->ipa_found = ipa_found; s->ipa_index = ipa;
    s->ipa_state = ipa_found ? first[9u + 5u * ipa] : 0;
    s->wlan_found = wlan_found; s->wlan_index = wlan;
    s->wlan_state = wlan_found ? first[9u + 5u * wlan] : 0;
    *state = state_value;
    error = gate(s, o);
    return error ? error : negotiated ? RF_WIFI_SMP2P_UNSTABLE : RF_WIFI_SMP2P_OK;
}

static int now(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o, uint64_t *value)
{
    int error = gate(s, o);
    if (!error) error = o->now_ms(o->context, value);
    if (error) { s->platform_error = error; return RF_WIFI_SMP2P_PLATFORM; }
    return RF_WIFI_SMP2P_OK;
}
static int pause_poll(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    int error = gate(s, o);
    if (!error) error = o->pause_us(o->context, 1000u);
    if (error) { s->platform_error = error; return RF_WIFI_SMP2P_PLATFORM; }
    return RF_WIFI_SMP2P_OK;
}
static int wait_state(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o,
    uint32_t mask, uint32_t timeout_ms)
{
    uint64_t start = 0, current = 0;
    int error = now(s, o, &start);
    if (error) return error;
    for (uint32_t poll = 0; poll <= timeout_ms; ++poll) {
        uint32_t state = 0;
        error = gate(s, o);
        if (!error && o->pas_started(o->context)) error = RF_WIFI_SMP2P_STATE;
        if (!error) error = peer(s, o, &state);
        if (!error && (state & mask)) return RF_WIFI_SMP2P_OK;
        if (error && error != RF_WIFI_SMP2P_NOT_FOUND && error != RF_WIFI_SMP2P_UNSTABLE) return error;
        error = now(s, o, &current);
        if (error) return error;
        if (current < start || current - start >= timeout_ms || poll == timeout_ms)
            return RF_WIFI_SMP2P_TIMEOUT;
        error = pause_poll(s, o);
        if (error) return error;
    }
    return RF_WIFI_SMP2P_TIMEOUT;
}

int rf_wifi_smp2p_wait_ready(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o, uint32_t timeout_ms)
{
    if (!s || !valid_ops(o) || !timeout_ms || timeout_ms > RF_WIFI_SMP2P_MAX_READY_MS)
        return RF_WIFI_SMP2P_ARGUMENT;
    if (s->stage != RF_WIFI_SMP2P_ARMED || s->poisoned) return RF_WIFI_SMP2P_STATE;
    int error = wait_state(s, o, SMP_READY, timeout_ms);
    if (error == RF_WIFI_SMP2P_TIMEOUT) {
        s->stage = RF_WIFI_SMP2P_WAIT_FAILED; s->error = error; return error;
    }
    if (error) return poison(s, error);
    s->stage = RF_WIFI_SMP2P_READY;
    return RF_WIFI_SMP2P_OK;
}

int rf_wifi_smp2p_alive(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    if (!s || !valid_ops(o)) return RF_WIFI_SMP2P_ARGUMENT;
    if (s->stage != RF_WIFI_SMP2P_READY || s->poisoned) return RF_WIFI_SMP2P_STATE;
    uint32_t state = 0;
    int error = gate(s, o);
    if (!error && o->pas_started(o->context)) error = RF_WIFI_SMP2P_STATE;
    if (!error) error = peer(s, o, &state);
    if (error == RF_WIFI_SMP2P_UNSTABLE) return error;
    if (!error && !(state & SMP_READY)) error = RF_WIFI_SMP2P_STATE;
    return error ? poison(s, error) : RF_WIFI_SMP2P_OK;
}

int rf_wifi_smp2p_ipa_respond(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o)
{
    if (!s || !valid_ops(o)) return RF_WIFI_SMP2P_ARGUMENT;
    if (s->stage != RF_WIFI_SMP2P_READY || s->poisoned) return RF_WIFI_SMP2P_STATE;
    uint32_t state = 0;
    int error = gate(s, o);
    if (!error && o->pas_started(o->context)) error = RF_WIFI_SMP2P_STATE;
    if (!error) error = peer(s, o, &state);
    if (error == RF_WIFI_SMP2P_UNSTABLE) return error;
    if (!error && !(state & SMP_READY)) error = RF_WIFI_SMP2P_STATE;
    if (!error && s->ipa_found && (s->ipa_state & 1u) && !s->ipa_responses) {
        error = update(s, o, SMP_IPA_VALUE, 1);
        if (!error) error = kick(s, o);
        if (!error) ++s->ipa_responses;
    }
    return error ? poison(s, error) : RF_WIFI_SMP2P_OK;
}

int rf_wifi_smp2p_stop(struct rf_wifi_smp2p_session *s, const struct rf_wifi_smp2p_ops *o, uint32_t timeout_ms)
{
    if (!s || !valid_ops(o) || !timeout_ms || timeout_ms > RF_WIFI_SMP2P_MAX_STOP_MS)
        return RF_WIFI_SMP2P_ARGUMENT;
    if ((s->stage != RF_WIFI_SMP2P_READY && s->stage != RF_WIFI_SMP2P_WAIT_FAILED &&
         s->stage != RF_WIFI_SMP2P_ARMED) || s->poisoned) return RF_WIFI_SMP2P_STATE;
    uint32_t state = 0;
    int error = gate(s, o);
    if (!error && o->pas_started(o->context)) error = RF_WIFI_SMP2P_STATE;
    if (!error) error = peer(s, o, &state);
    if (error == RF_WIFI_SMP2P_NOT_FOUND) error = 0;
    if (!error && (state & SMP_STOP_ACK)) error = RF_WIFI_SMP2P_STATE;
    if (error) return poison(s, error);
    s->stage = RF_WIFI_SMP2P_STOPPING;
    error = update(s, o, SMP_MASTER_VALUE, 1u);
    if (!error) error = kick(s, o);
    if (!error) error = wait_state(s, o, SMP_STOP_ACK, timeout_ms);
    if (!error) error = update(s, o, SMP_MASTER_VALUE, 0u);
    if (!error) error = kick(s, o);
    if (error) return poison(s, error);
    s->stage = RF_WIFI_SMP2P_STOPPED;
    return RF_WIFI_SMP2P_OK;
}
