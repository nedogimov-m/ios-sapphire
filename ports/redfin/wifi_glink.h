/* SPDX-License-Identifier: MIT
 * Bounded native APPS/MPSS GLINK transport. Google msm
 * 500b3a2059c1eec0fec08ec56add06320ea901a8 qcom_glink_{smem,native}.c;
 * preferred HackiOS kernel8e611870 redwood_wifi.c framing/QRTR was reviewed.
 * The caller must establish this boot's PAS4/SMP2P ready and own lock3.
 */
#ifndef REDFIN_WIFI_GLINK_H
#define REDFIN_WIFI_GLINK_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "wifi_smem.h"
#ifdef __cplusplus
#define RF_GL_ZERO {}
#else
#define RF_GL_ZERO {0}
#endif
enum { RF_GL_OK, RF_GL_ARGUMENT, RF_GL_PLATFORM, RF_GL_CHANGED, RF_GL_LAYOUT,
    RF_GL_SPACE, RF_GL_AGAIN, RF_GL_PROTOCOL, RF_GL_CLOSED };
struct rf_glink_ops {
    void *context;
    const volatile uint8_t *smem;
    int (*check)(void *); /* Same authenticated PAS4/SMP2P session, worker/CPU/maps. */
    int (*lock)(void *);
    int (*unlock)(void *);
    int (*write32)(void *, uint32_t offset, uint32_t value);
    int (*barrier)(void *);
    int (*kick)(void *); /* Native MPSS client2 / GLINK signal0 only. */
    void (*packet)(void *, const uint8_t *, uint32_t bytes);
    /* Optional bounded copy to the APPS-owned FIFO only. The producer checks
     * actual readback and publishes head only after barriers/ownership checks. */
    int (*payload)(void *, uint32_t offset, const uint8_t *, uint32_t bytes);
};
struct rf_glink_intent { uint32_t id, bytes, busy, present; };
struct rf_glink {
    uint32_t remote_host,bound_host; /* zero keeps established MPSS host1; ADSP is2 */
    uint32_t attempted, poisoned, partition, bytes, descriptor, tx, rx, rx_bytes;
    uint32_t head, tail, features, version, asked, acknowledged, channel, open, offered;
    uint32_t fill, remaining, heard, sent, packets, stores;
    uint32_t last_command, last_p1, last_p2, last_waiting;
    uint32_t last_intent_bytes, last_intent_id;
    uint32_t changed_reason, changed_offset, changed_expected, changed_observed;
    struct rf_glink_intent intent[32];
    uint8_t packet[65536];
    uint8_t frame[16384];
};
static inline uint32_t rf_gl_word(const struct rf_glink_ops *o, uint32_t at)
{ return redfin_smem_u32(o->smem + at); }
static inline int rf_gl_changed(struct rf_glink *s, uint32_t reason, uint32_t at,
    uint32_t expected, uint32_t observed)
{
    s->changed_reason = reason; s->changed_offset = at;
    s->changed_expected = expected; s->changed_observed = observed;
    s->poisoned = 1;
    return RF_GL_CHANGED;
}
static inline int rf_gl_gate(struct rf_glink *s, const struct rf_glink_ops *o)
{
    if (!s || !o || !o->smem || !o->check || !o->lock || !o->unlock || !o->write32 ||
        !o->barrier || !o->kick || !o->packet) return RF_GL_ARGUMENT;
    uint32_t remote=s->remote_host?s->remote_host:1;
    if(remote>2 || (s->attempted && s->bound_host!=remote))return RF_GL_ARGUMENT;
    if (s->poisoned) return RF_GL_CHANGED;
    if (o->check(o->context)) { s->poisoned = 1; return RF_GL_PLATFORM; }
    return 0;
}
static inline int rf_gl_put(struct rf_glink *s, const struct rf_glink_ops *o, uint32_t at, uint32_t value)
{
    if (at % 4u || at > REDFIN_SMEM_BYTES - 4u || rf_gl_gate(s, o)) return RF_GL_PLATFORM;
    ++s->stores;
    if (o->write32(o->context, at, value) || rf_gl_word(o, at) != value) {
        s->poisoned = 1; return RF_GL_PLATFORM;
    }
    return 0;
}
static inline int rf_gl_find(struct rf_glink *s, const struct rf_glink_ops *o,
    uint32_t location[3], uint32_t lengths[3], struct redfin_smem_report *report)
{
    if (rf_gl_gate(s, o)) return RF_GL_PLATFORM;
    if (redfin_smem_inspect_host(o->smem, REDFIN_SMEM_BYTES, s->remote_host?s->remote_host:1, report) != REDFIN_SMEM_OK ||
        !report->modem_partition) return RF_GL_LAYOUT;
    if (s->partition && (s->partition != report->partition_offset || s->bytes != report->partition_bytes))
        return rf_gl_changed(s, 1, report->partition_offset, s->bytes, report->partition_bytes);
    for (unsigned i = 0; i < 3; ++i) location[i] = lengths[i] = 0;
    uint32_t at = 32, count = 0;
    while (at < report->free_uncached) {
        if (++count > REDFIN_SMEM_MAX_ITEMS || report->free_uncached - at < 16u) return RF_GL_LAYOUT;
        uint32_t entry = report->partition_offset + at;
        uint32_t stored = rf_gl_word(o, entry + 4u), padding = redfin_smem_u16(o->smem + entry + 8u);
        uint32_t header = redfin_smem_u16(o->smem + entry + 10u), item = redfin_smem_u16(o->smem + entry + 2u);
        if (redfin_smem_u16(o->smem + entry) != 0xa5a5u || !stored || padding >= stored ||
            header > report->free_uncached - at - 16u || stored > report->free_uncached - at - 16u - header)
            return RF_GL_LAYOUT;
        if (item >= 478 && item <= 480) {
            unsigned slot = item - 478;
            if (location[slot]) return RF_GL_LAYOUT;
            location[slot] = entry + 16u + header; lengths[slot] = stored - padding;
        }
        at += 16u + header + stored;
    }
    if (rf_gl_word(o, report->partition_offset + 12u) != report->free_uncached ||
        rf_gl_word(o, report->partition_offset + 16u) != report->free_cached) return RF_GL_AGAIN;
    return rf_gl_gate(s, o);
}
static inline int rf_gl_allocate(struct rf_glink *s, const struct rf_glink_ops *o,
    struct redfin_smem_report *r, uint32_t item, uint32_t bytes, uint32_t *data)
{
    if ((item != 478 || bytes != 32) && (item != 479 || bytes != 16384)) return RF_GL_ARGUMENT;
    if (r->free_uncached % 8u || bytes > r->free_cached - r->free_uncached ||
        16u > r->free_cached - r->free_uncached - bytes) return RF_GL_SPACE;
    uint32_t at = r->partition_offset + r->free_uncached;
    *data = at + 16u;
    /* Only new unpublished descriptor words are initialized. TX bytes are
     * written before publishing head; no stale/unwritten data is advertised. */
    if (item == 478) for (unsigned i = 0; i < 32; i += 4)
        if (rf_gl_put(s, o, *data + i, 0)) return RF_GL_PLATFORM;
    const uint32_t header[4] = {item << 16 | 0xa5a5u, bytes, 0, 0};
    for (unsigned i = 0; i < 4; ++i) if (rf_gl_put(s, o, at + i * 4u, header[i])) return RF_GL_PLATFORM;
    if (o->barrier(o->context) || rf_gl_gate(s, o)) return RF_GL_PLATFORM;
    if (rf_gl_put(s, o, r->partition_offset + 12u, r->free_uncached + 16u + bytes)) return RF_GL_PLATFORM;
    r->free_uncached += 16u + bytes;
    return o->barrier(o->context) ? RF_GL_PLATFORM : 0;
}
static inline int rf_gl_init(struct rf_glink *s, const struct rf_glink_ops *o)
{
    if (rf_gl_gate(s, o) || s->attempted) return RF_GL_ARGUMENT;
    s->bound_host=s->remote_host?s->remote_host:1;
    s->attempted = 1;
    if (o->lock(o->context)) return RF_GL_PLATFORM;
    uint32_t at[3], sizes[3]; struct redfin_smem_report r = RF_GL_ZERO;
    int error = rf_gl_find(s, o, at, sizes, &r);
    if (!error) { s->partition = r.partition_offset; s->bytes = r.partition_bytes; }
    if (!error && !at[0]) { error = rf_gl_allocate(s, o, &r, 478, 32, &at[0]); sizes[0] = 32; }
    if (!error && !at[1]) { error = rf_gl_allocate(s, o, &r, 479, 16384, &at[1]); sizes[1] = 16384; }
    if (!error && (sizes[0] != 32 || sizes[1] != 16384 || (at[0] | at[1]) % 4u ||
        rf_gl_word(o, at[0] + 4u) || rf_gl_word(o, at[0] + 8u))) error = RF_GL_LAYOUT;
    if (!error) { s->descriptor = at[0]; s->tx = at[1]; s->features = 1; }
    int unlocked = o->unlock(o->context);
    if (unlocked) error = RF_GL_PLATFORM;
    if (error) s->poisoned = 1;
    return error;
}
static inline int rf_gl_indices(struct rf_glink *s, const struct rf_glink_ops *o,
    uint32_t *remote_tail, uint32_t *remote_head)
{
    int error = rf_gl_gate(s, o);
    if (error) return error;
    if (!s->descriptor || !s->tx) return rf_gl_changed(s, 2, 0, 1, 0);
    uint32_t local_head = rf_gl_word(o, s->descriptor + 4u), local_tail = rf_gl_word(o, s->descriptor + 8u);
    if (local_head != s->head) return rf_gl_changed(s, 3, s->descriptor + 4u, s->head, local_head);
    if (local_tail != s->tail) return rf_gl_changed(s, 4, s->descriptor + 8u, s->tail, local_tail);
    *remote_tail = rf_gl_word(o, s->descriptor);
    *remote_head = rf_gl_word(o, s->descriptor + 12u);
    if ((*remote_tail | *remote_head) % 8u || *remote_tail >= 16384u ||
        (s->rx_bytes && *remote_head >= s->rx_bytes)) return RF_GL_LAYOUT;
    return o->barrier(o->context) ? RF_GL_PLATFORM : 0;
}
static inline int rf_gl_say(struct rf_glink *s, const struct rf_glink_ops *o,
    uint16_t command, uint16_t p1, uint32_t p2, const uint8_t *data, uint32_t bytes)
{
    if (bytes > 16352 || (bytes && !data)) return RF_GL_ARGUMENT;
    uint32_t tail, head, length = (8u + bytes + 7u) & ~7u;
    int error = rf_gl_indices(s, o, &tail, &head);
    if (error) return error;
    uint32_t free = (tail + 16384u - s->head) % 16384u;
    if (!free) free = 16384;
    if (length + 16u > free) return RF_GL_AGAIN;
    for (uint32_t i = 0; i < length; i += 4u) {
        uint32_t value = i == 0 ? (uint32_t)command | (uint32_t)p1 << 16 : i == 4 ? p2 : 0;
        if (i >= 8) for (unsigned j = 0; j < 4; ++j)
            if (i - 8u + j < bytes) value |= (uint32_t)data[i - 8u + j] << (8u * j);
        for (unsigned j = 0; j < 4; ++j) s->frame[i + j] = (uint8_t)(value >> (j * 8u));
    }
    if (o->payload) {
        for (uint32_t sent = 0; sent < length;) {
            uint32_t at = (s->head + sent) % 16384u, take = length - sent;
            if (take > 16384u - at) take = 16384u - at;
            if (rf_gl_gate(s, o) || o->payload(o->context, s->tx + at, s->frame + sent, take)) {
                s->poisoned = 1; return RF_GL_PLATFORM;
            }
            if (o->barrier(o->context) || rf_gl_gate(s, o)) { s->poisoned = 1; return RF_GL_PLATFORM; }
            for (uint32_t i = 0; i < take; ++i)
                if (o->smem[s->tx + at + i] != s->frame[sent + i])
                    return rf_gl_changed(s, 5, s->tx + at + i, s->frame[sent + i], o->smem[s->tx + at + i]);
            s->stores += take / 4u; sent += take;
        }
    } else for (uint32_t i = 0; i < length; i += 4u) {
        uint32_t value = (uint32_t)s->frame[i] | (uint32_t)s->frame[i + 1u] << 8 |
            (uint32_t)s->frame[i + 2u] << 16 | (uint32_t)s->frame[i + 3u] << 24;
        if (rf_gl_put(s, o, s->tx + (s->head + i) % 16384u, value)) return RF_GL_PLATFORM;
    }
    if (o->barrier(o->context) || rf_gl_gate(s, o)) return RF_GL_PLATFORM;
    uint32_t next = (s->head + length) % 16384u;
    if (rf_gl_put(s, o, s->descriptor + 4u, next)) return RF_GL_PLATFORM;
    s->head = next; ++s->sent;
    return o->barrier(o->context) || o->kick(o->context) ? RF_GL_PLATFORM : 0;
}
static inline void rf_gl_peek(const struct rf_glink *s, const struct rf_glink_ops *o,
    uint32_t offset, uint8_t *out, uint32_t bytes)
{
    for (uint32_t i = 0; i < bytes; ++i) out[i] = o->smem[s->rx + (s->tail + offset + i) % s->rx_bytes];
}
static inline uint32_t rf_gl_u32(const uint8_t *bytes)
{ return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 | (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24; }
static inline void rf_gl_encode(uint8_t *bytes, uint32_t value)
{ for (unsigned i = 0; i < 4; ++i) bytes[i] = (uint8_t)(value >> (8u * i)); }
static inline int rf_gl_send_packet(struct rf_glink *s, const struct rf_glink_ops *o,
    const uint8_t *data, uint32_t bytes, uint8_t *scratch, uint32_t capacity)
{
    if (!s->open || !data || !bytes || bytes > 8192 || !scratch || capacity < bytes + 8u) return RF_GL_ARGUMENT;
    int slot = -1;
    for (unsigned i = 0; i < 32; ++i)
        if (s->intent[i].present && !s->intent[i].busy && s->intent[i].bytes >= bytes) { slot = (int)i; break; }
    if (slot < 0) return RF_GL_AGAIN;
    rf_gl_encode(scratch, bytes); rf_gl_encode(scratch + 4u, 0); memcpy(scratch + 8u, data, bytes);
    int error = rf_gl_say(s, o, 9, 1, s->intent[slot].id, scratch, bytes + 8u);
    if (!error) s->intent[slot].busy = 1;
    return error;
}
static inline int rf_gl_pump(struct rf_glink *s, const struct rf_glink_ops *o)
{
    if (!s->rx) {
        uint32_t at[3], sizes[3]; struct redfin_smem_report r = RF_GL_ZERO;
        int error = rf_gl_find(s, o, at, sizes, &r);
        if (error) return error;
        if (at[0] != s->descriptor || at[1] != s->tx || sizes[0] != 32 || sizes[1] != 16384)
            return rf_gl_changed(s, 6, at[0], s->tx, at[1]);
        if (!at[2]) return RF_GL_AGAIN;
        if (sizes[2] < 64 || sizes[2] > 65536 || sizes[2] % 8u) return RF_GL_LAYOUT;
        s->rx = at[2]; s->rx_bytes = sizes[2];
    }
    for (unsigned budget = 0; budget < 128; ++budget) {
        uint32_t peer_tail, peer_head;
        int error = rf_gl_indices(s, o, &peer_tail, &peer_head);
        if (error) return error;
        uint32_t waiting = (peer_head + s->rx_bytes - s->tail) % s->rx_bytes;
        if (waiting < 8) return 0;
        uint32_t room = (peer_tail + 16384u - s->head) % 16384u;
        if (room && room < 144u) return RF_GL_AGAIN; /* Reserve all control replies before consuming. */
        uint8_t header[16] = RF_GL_ZERO;
        rf_gl_peek(s, o, 0, header, 8);
        uint32_t first = rf_gl_u32(header), command = first & 0xffffu, p1 = first >> 16, p2 = rf_gl_u32(header + 4);
        s->last_command = command; s->last_p1 = p1; s->last_p2 = p2; s->last_waiting = waiting;
        uint32_t bytes = 8, chunk = 0, left = 0;
        if (command == 2) { if (!p2 || p2 > 32) return RF_GL_PROTOCOL; bytes += p2; }
        else if (command == 5) { if (!p2 || p2 > 32) return RF_GL_PROTOCOL; bytes += p2 * 8u; }
        else if (command == 9 || command == 12) {
            if (waiting < 16) return 0;
            rf_gl_peek(s, o, 8, header + 8, 8);
            chunk = rf_gl_u32(header + 8); left = rf_gl_u32(header + 12);
            if (!chunk || chunk > 65536 || left > 65536 - chunk) return RF_GL_PROTOCOL;
            bytes = 16u + chunk;
        }
        bytes = (bytes + 7u) & ~7u;
        if (bytes > s->rx_bytes - 8u) return RF_GL_PROTOCOL;
        if (waiting < bytes) return 0;
        uint8_t response[40] = RF_GL_ZERO;
        unsigned response_bytes = 0, response_command = 0xffffu, response_p1 = 0, response_p2 = 0;
        bool packet = false;
        bool foreign = ((command == 5 || command == 6 || command == 14 || command == 7 ||
            command == 9 || command == 12 || command == 3) && p1 != s->channel) ||
            (command == 4 && p1 != 1);
        if (foreign) {
            /* Other remote channels can advertise before our IPCRTR opens.
             * Consume their bounded frames without adopting buffers or data. */
        } else if (command == 0 || command == 1) {
            if (p1 != 1 || (command == 1 && (p2 & ~s->features))) return RF_GL_PROTOCOL;
            s->features &= p2;
            if (command == 0) { response_command = 1; response_p1 = 1; response_p2 = s->features; }
            else s->version = 1;
        } else if (command == 2) {
            rf_gl_peek(s, o, 8, response, p2);
            if (response[p2 - 1u]) return RF_GL_PROTOCOL;
            if (p2 == 7 && !memcmp(response, "IPCRTR", 7)) {
                if (!p1 || (s->channel && s->channel != p1)) return RF_GL_PROTOCOL;
                s->channel = p1; response_command = 4; response_p1 = p1;
            }
        } else if (command == 4) {
            if (p1 != 1) return RF_GL_PROTOCOL;
            s->acknowledged = 1;
        } else if (command == 5) {
            if (p1 != s->channel) return RF_GL_PROTOCOL;
            for (unsigned i = 0; i < p2; ++i) {
                uint8_t raw[8]; rf_gl_peek(s, o, 8u + i * 8u, raw, 8);
                uint32_t size = rf_gl_u32(raw), id = rf_gl_u32(raw + 4u);
                s->last_intent_bytes = size; s->last_intent_id = id;
                /* An opaque remote handle may be zero. Its capacity does not
                 * allocate or authorize local memory; sends remain <=8192. */
                if (!size) return RF_GL_PROTOCOL;
                int selected = -1;
                for (unsigned j = 0; j < 32; ++j) {
                    if (s->intent[j].present && s->intent[j].id == id) {
                        if (s->intent[j].busy) return RF_GL_PROTOCOL; selected = (int)j; break;
                    }
                    if (!s->intent[j].present && selected < 0) selected = (int)j;
                }
                if (selected < 0) return RF_GL_SPACE;
                s->intent[selected].id = id; s->intent[selected].bytes = size;
                s->intent[selected].present = 1;
            }
        } else if (command == 6 || command == 14) {
            if (p1 != s->channel) return RF_GL_PROTOCOL;
            for (unsigned i = 0; i < 32; ++i) if (s->intent[i].present && s->intent[i].id == p2) {
                if (!s->intent[i].busy) return RF_GL_PROTOCOL;
                s->intent[i].busy = 0; if (command == 6) s->intent[i].present = 0;
                break;
            }
        } else if (command == 9 || command == 12) {
            if (p1 != s->channel || p2 != 1 || !s->offered || chunk > sizeof(s->packet) - s->fill ||
                (command == 9 && s->fill) || (command == 12 && (!s->fill || chunk + left != s->remaining)))
                return RF_GL_PROTOCOL;
            rf_gl_peek(s, o, 16, s->packet + s->fill, chunk);
            s->fill += chunk; s->remaining = left;
            if (!left) { packet = true; response_command = s->features & 1u ? 14 : 6; response_p1 = 1; response_p2 = 1; }
        } else if (command == 7) {
            response_command = 8; response_p1 = 1; response_p2 = 0; /* One reusable local intent; no unbounded allocations. */
        } else if (command == 3) return RF_GL_CLOSED;
        else if (command != 8 && command != 11 && command != 13 && command != 15) return RF_GL_PROTOCOL;
        uint32_t next = (s->tail + bytes) % s->rx_bytes;
        if (rf_gl_put(s, o, s->descriptor + 8u, next)) return RF_GL_PLATFORM;
        s->tail = next; ++s->heard;
        if (o->barrier(o->context) || o->kick(o->context)) return RF_GL_PLATFORM;
        if (response_command != 0xffffu) {
            error = rf_gl_say(s, o, (uint16_t)response_command, (uint16_t)response_p1, response_p2,
                response_bytes ? response : NULL, response_bytes);
            if (error) return error;
        }
        if (packet) {
            ++s->packets; o->packet(o->context, s->packet, s->fill); s->fill = s->remaining = 0;
            if (!(s->features & 1u)) s->offered = 0;
        }
        if (s->channel && !s->asked) {
            static const uint8_t channel[7] = "IPCRTR";
            error = rf_gl_say(s, o, 2, 1, sizeof(channel), channel, sizeof(channel));
            if (error) return error;
            s->asked = 1;
        }
        if (s->version && s->channel && s->acknowledged && !s->offered) {
            uint8_t intent[8]; rf_gl_encode(intent, sizeof(s->packet)); rf_gl_encode(intent + 4u, 1);
            error = rf_gl_say(s, o, 5, 1, 1, intent, sizeof(intent));
            if (error) return error;
            s->offered = s->open = 1;
        }
    }
    return RF_GL_AGAIN;
}
#undef RF_GL_ZERO
#endif
