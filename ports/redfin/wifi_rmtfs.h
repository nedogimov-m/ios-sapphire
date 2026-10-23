/* SPDX-License-Identifier: MIT
 * Native RMTFS QMI framing, with private snapshots and volatile RAM shadows.
 * Wire reference: linux-msm/rmtfs b30a3eb38f9af283f18dbd3c7755653efc52c094.
 * This implementation has no filesystem, block-device or arbitrary DMA API.
 */
#ifndef REDFIN_WIFI_RMTFS_H
#define REDFIN_WIFI_RMTFS_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define RF_RM_SHARED 0x280000u
struct rf_rm_file {
    const uint8_t *initial;
    uint8_t *shadow;
    uint32_t bytes, open, node, port, allocated;
};
struct rf_rmtfs {
    struct rf_rm_file file[4];
    const uint8_t *image;
    size_t image_bytes;
    volatile uint8_t *shared;
    uint64_t physical;
    uint32_t ready, poisoned, requests, opens, allocations, reads, writes, failures, last_message;
};
struct rf_rm_ops {
    void *context;
    int (*check)(void *);
    int (*barrier)(void *);
    int (*send)(void *, uint32_t node, uint32_t port, const uint8_t *, uint32_t);
    void (*event)(void *, unsigned message, unsigned caller, unsigned bytes, unsigned error);
};
static const char *const rf_rm_names[4] = {
    "/boot/modem_fs1", "/boot/modem_fs2", "/boot/modem_fsg", "/boot/modem_fsc"};
static inline uint32_t rf_rm_u32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static inline uint64_t rf_rm_u64(const uint8_t *p)
{ return rf_rm_u32(p) | (uint64_t)rf_rm_u32(p + 4) << 32; }
static inline void rf_rm_put(uint8_t *p, uint64_t value, unsigned bytes)
{ for (unsigned i = 0; i < bytes; ++i) p[i] = (uint8_t)(value >> (8u * i)); }
static inline int rf_rm_overlap(const void *a, size_t n, const void *b, size_t m)
{
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x > UINTPTR_MAX - n || y > UINTPTR_MAX - m || (x < y + m && y < x + n);
}
/* Include after wifi_firmware.h for the existing SHA-256 callback ABI. */
static inline int rf_rm_image_open(struct rf_rmtfs *s, const uint8_t *data, size_t bytes,
    const uint8_t expected[32], redfin_mpss_sha256_fn sha, void *opaque)
{
    if (!s || s->image || s->ready || !data || !expected || !sha || bytes < 576 || bytes > 12u * 1024u * 1024u ||
        rf_rm_overlap(s, sizeof(*s), data, bytes)) return -1;
    uint8_t digest[32];
    if (memcmp(data, "RFRMS01\0", 8) || rf_rm_u32(data + 8) != 1 || rf_rm_u32(data + 12) != 4 ||
        rf_rm_u64(data + 16) != bytes || rf_rm_u64(data + 24) != 128 || sha(opaque, data, bytes, digest) ||
        memcmp(digest, expected, 32)) return -1;
    for (unsigned i = 32; i < 64; ++i) if (data[i]) return -1;
    size_t cursor = 576;
    for (unsigned i = 0; i < 4; ++i) {
        const uint8_t *entry = data + 64u + i * 128u;
        size_t length = strlen(rf_rm_names[i]);
        if (memcmp(entry, rf_rm_names[i], length)) return -1;
        for (size_t j = length; j < 64; ++j) if (entry[j]) return -1;
        for (unsigned j = 112; j < 128; ++j) if (entry[j]) return -1;
        uint64_t offset = rf_rm_u64(entry + 64), count = rf_rm_u64(entry + 72);
        if (offset != cursor || !count || count > 4u * 1024u * 1024u || count % 4096u ||
            offset > bytes || count > bytes - offset || sha(opaque, data + cursor, (size_t)count, digest) ||
            memcmp(digest, entry + 80, 32)) return -1;
        cursor += (size_t)count;
    }
    if (cursor != bytes) return -1;
    for (unsigned i = 0; i < 4; ++i) {
        const uint8_t *entry = data + 64u + i * 128u;
        s->file[i].initial = data + rf_rm_u64(entry + 64);
        s->file[i].bytes = (uint32_t)rf_rm_u64(entry + 72);
    }
    s->image = data; s->image_bytes = bytes;
    return 0;
}
static inline size_t rf_rm_shadow_bytes(const struct rf_rmtfs *s)
{
    size_t bytes = 0;
    if (s && s->image && !s->poisoned) for (unsigned i = 0; i < 4; ++i) bytes += s->file[i].bytes;
    return bytes;
}
static inline int rf_rm_shadow_open(struct rf_rmtfs *s, uint8_t *data, size_t bytes)
{
    if (!s || !s->image || s->ready || s->poisoned || s->file[0].shadow || !data ||
        bytes != rf_rm_shadow_bytes(s) || rf_rm_overlap(s, sizeof(*s), data, bytes) ||
        rf_rm_overlap(s->image, s->image_bytes, data, bytes)) return -1;
    size_t cursor = 0;
    for (unsigned i = 0; i < 4; ++i) {
        s->file[i].shadow = data + cursor;
        memcpy(data + cursor, s->file[i].initial, s->file[i].bytes); cursor += s->file[i].bytes;
    }
    return 0;
}
/* Called only after the platform owns, zeroes and successfully shares this
 * exact buffer with HLOS3/MSS15, read-write, retaining it until full reset. */
static inline int rf_rm_bind(struct rf_rmtfs *s, volatile uint8_t *shared, uint64_t physical, size_t bytes)
{
    if (!s || s->ready || s->poisoned || !s->image || !s->file[0].shadow || !shared || bytes != RF_RM_SHARED ||
        physical < UINT64_C(0x80000000) || physical > UINT64_C(0x100000000) - bytes || physical % 16384u ||
        rf_rm_overlap(s->image, s->image_bytes, (const void *)shared, bytes) ||
        rf_rm_overlap(s->file[0].shadow, rf_rm_shadow_bytes(s), (const void *)shared, bytes) ||
        rf_rm_overlap(s, sizeof(*s), (const void *)shared, bytes)) return -1;
    s->shared = shared; s->physical = physical; s->ready = 1;
    return 0;
}
static inline int rf_rm_gate(struct rf_rmtfs *s, const struct rf_rm_ops *o)
{
    if (!s || !o || !o->check || !o->barrier || !o->send || !o->event || !s->ready || s->poisoned) return -1;
    if (o->check(o->context)) { s->poisoned = 1; return -1; }
    return 0;
}
static inline int rf_rm_request(struct rf_rmtfs *s, const struct rf_rm_ops *o, uint32_t node,
    uint32_t port, const uint8_t *data, uint32_t bytes)
{
    if (rf_rm_gate(s, o) || !data || bytes < 7 || bytes > 4096 || data[0] ||
        ((uint32_t)data[5] | (uint32_t)data[6] << 8) != bytes - 7u) return -1;
    uint32_t message = (uint32_t)data[3] | (uint32_t)data[4] << 8, error = 0, seen = 0;
    const uint8_t *value[4] = {NULL, NULL, NULL, NULL}; uint32_t length[4] = {0};
    uint8_t response[25] = {2, 0, 0, 0, 0, 7, 0, 2, 4, 0, 0, 0, 0, 0};
    memcpy(response + 1, data + 1, 4);
    uint32_t used = 14, caller = 0, transferred = 0;
    struct rf_rm_file *file = NULL;
    if (!message || message > 5) error = 0x5e;
    for (uint32_t at = 7; !error && at < bytes;) {
        if (bytes - at < 3) { error = 2; break; }
        uint32_t kind = data[at], count = (uint32_t)data[at + 1] | (uint32_t)data[at + 2] << 8;
        if (count > bytes - at - 3u || !kind || (kind > 4 && kind < 16)) { error = 2; break; }
        if (kind <= 4) {
            unsigned bit = 1u << (kind - 1u);
            if (seen & bit) { error = 2; break; }
            seen |= bit; value[kind - 1] = data + at + 3u; length[kind - 1] = count;
        }
        at += 3u + count;
    }
    uint32_t required = message == 3 ? 15u : message == 4 ? 3u : 1u;
    if (!error && seen != required) error = 2;
    if (!error && message == 1) {
        for (unsigned i = 0; i < 4; ++i) if (length[0] == strlen(rf_rm_names[i]) &&
            !memcmp(value[0], rf_rm_names[i], length[0])) { file = &s->file[i]; caller = i + 1u; break; }
        if (!file || (file->open && file->node != node)) error = 1;
        if (!error) {
            file->open = 1; file->node = node; file->port = port;
            response[14] = 16; rf_rm_put(response + 15, 4, 2); rf_rm_put(response + 17, caller, 4); used += 7;
            ++s->opens;
        }
    } else if (!error) {
        if (length[0] != 4) error = 2;
        else {
            caller = rf_rm_u32(value[0]);
            if (caller >= 1 && caller <= 4) file = &s->file[caller - 1u];
            /* Native handles belong to a QRTR node. MPSS can use another
             * client socket/port for subsequent requests on the same handle. */
            if (!file || !file->open || file->node != node) error = 1;
        }
        if (!error && message == 2) { file->open = 0; file->allocated = 0; }
        else if (!error && message == 4) {
            if (length[1] != 4) error = 2;
            else {
                uint32_t requested = rf_rm_u32(value[1]);
                transferred = requested;
                if (requested > RF_RM_SHARED) error = 1;
                else {
                    /* rmtfs_mem_alloc returns the same fixed buffer even for
                     * size0; it does not carve a per-request suballocation. */
                    file->allocated = RF_RM_SHARED;
                    response[14] = 16; rf_rm_put(response + 15, 8, 2); rf_rm_put(response + 17, s->physical, 8);
                    used += 11; ++s->allocations; transferred = requested;
                }
            }
        } else if (!error && message == 5) {
            response[14] = 16; rf_rm_put(response + 15, 1, 2); response[17] = 0; used += 4;
        } else if (!error && message == 3) {
            uint32_t count = length[2] ? value[2][0] : 0;
            if (length[1] != 1 || value[1][0] > 1 || length[3] != 1 || value[3][0] > 1 ||
                !count || length[2] != 1u + 12u * count || !file->allocated) error = 2;
            /* Prevalidate the complete vector before copying any byte. */
            for (uint32_t i = 0; !error && i < count; ++i) {
                const uint8_t *entry = value[2] + 1u + 12u * i;
                uint64_t sector = rf_rm_u32(entry), physical = rf_rm_u32(entry + 4), sectors = rf_rm_u32(entry + 8);
                uint64_t size = sectors * 512u;
                if (!sectors || sector * 512u > file->bytes || size > file->bytes - sector * 512u ||
                    physical < s->physical || physical - s->physical > file->allocated ||
                    size > file->allocated - (physical - s->physical) || physical % 512u ||
                    size > RF_RM_SHARED - transferred) error = 1;
                else transferred += (uint32_t)size;
            }
            if (!error && o->barrier(o->context)) { s->poisoned = 1; return -1; }
            for (uint32_t i = 0; !error && i < count; ++i) {
                const uint8_t *entry = value[2] + 1u + 12u * i;
                uint32_t offset = rf_rm_u32(entry) * 512u, pool_offset = rf_rm_u32(entry + 4) - (uint32_t)s->physical;
                uint32_t size = rf_rm_u32(entry + 8) * 512u;
                for (uint32_t at = 0; at < size; ++at) {
                    if (!(at % 4096u) && rf_rm_gate(s, o)) return -1;
                    if (value[1][0]) file->shadow[offset + at] = s->shared[pool_offset + at];
                    else s->shared[pool_offset + at] = file->shadow[offset + at];
                }
            }
            if (!error && o->barrier(o->context)) { s->poisoned = 1; return -1; }
            if (!error) { if (value[1][0]) s->writes += transferred / 512u; else s->reads += transferred / 512u; }
        }
    }
    if (error) { used = 14; rf_rm_put(response + 10, 1, 2); rf_rm_put(response + 12, error, 2); ++s->failures; }
    rf_rm_put(response + 5, used - 7u, 2);
    ++s->requests; s->last_message = message;
    o->event(o->context, message, caller, transferred, error);
    if (rf_rm_gate(s, o) || o->send(o->context, node, port, response, used)) { s->poisoned = 1; return -1; }
    return 0;
}
#endif
