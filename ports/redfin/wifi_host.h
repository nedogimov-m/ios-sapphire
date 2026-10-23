/* SPDX-License-Identifier: MIT
 * Bounded QRTR host services for native MPSS: servreg locator and RAM TFTP.
 * Wire references: native servreg-locator QMI and tqftpserv; the legacy
 * Sapphire host-service protocol was reviewed, with all partition tables,
 * UFS/EFS/DMA access and unbounded request parsing omitted here.
 */
#ifndef REDFIN_WIFI_HOST_H
#define REDFIN_WIFI_HOST_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdbool.h>
#define RF_HOST_BLOCK 4096u
#define RF_HOST_PATH 160u
struct rf_host_ops {
    void *context;
    int (*check)(void *);
    int (*lookup)(void *, const char *, const uint8_t **, uint32_t *);
    int (*send)(void *, uint32_t from, uint32_t node, uint32_t to, const uint8_t *, uint32_t);
    void (*event)(void *, unsigned kind, const char *name, uint32_t size);
};
struct rf_host_ram { char name[RF_HOST_PATH]; uint32_t used, bytes; uint8_t data[65536]; };
struct rf_host_tftp {
    uint32_t used, done, complete, write, node, port, local, block, block_bytes, offset, end;
    int ram;
    const uint8_t *data;
    char name[RF_HOST_PATH];
    uint32_t response_bytes;
    uint8_t response[RF_HOST_BLOCK + 256];
};
struct rf_host {
    uint32_t poisoned, serial, requests, pd_requests, reads, writes, missing;
    struct rf_host_ram ram[4];
    struct rf_host_tftp session[8];
    uint8_t qmi[512];
};
static inline uint16_t rf_host_le16(const uint8_t *p) { return (uint16_t)p[0] | (uint16_t)p[1] << 8; }
static inline uint16_t rf_host_be16(const uint8_t *p) { return (uint16_t)p[1] | (uint16_t)p[0] << 8; }
static inline void rf_host_le_put(uint8_t *p, uint32_t value, unsigned bytes)
{ for (unsigned i = 0; i < bytes; ++i) p[i] = (uint8_t)(value >> (i * 8u)); }
static inline void rf_host_be_put(uint8_t *p, uint16_t value) { p[0] = (uint8_t)(value >> 8); p[1] = (uint8_t)value; }
static inline int rf_host_string(const uint8_t *data, uint32_t bytes, uint32_t *cursor,
    char *out, unsigned capacity)
{
    if (!cursor || !out || !capacity || *cursor >= bytes) return -1;
    unsigned used = 0;
    while (*cursor < bytes && data[*cursor]) {
        unsigned c = data[(*cursor)++];
        if (c < 32 || c > 126 || used + 1u >= capacity) return -1;
        out[used++] = (char)c;
    }
    if (*cursor == bytes) return -1;
    ++*cursor; out[used] = 0;
    return 0;
}
static inline int rf_host_decimal(const char *text, uint32_t *value)
{
    if (!text || !text[0] || !value) return -1;
    uint32_t out = 0;
    for (unsigned i = 0; text[i]; ++i) {
        unsigned digit = (unsigned)(text[i] - '0');
        if (i >= 10 || digit > 9 || out > (UINT32_MAX - digit) / 10u) return -1;
        out = out * 10u + digit;
    }
    *value = out; return 0;
}
static inline int rf_host_path(const char *name)
{
    if (!name || !name[0]) return -1;
    for (unsigned i = 0; name[i]; ++i) {
        if (i + 1u >= RF_HOST_PATH || (name[i] == '.' && name[i + 1u] == '.') ||
            (name[i] == '/' && name[i + 1u] == '/')) return -1;
    }
    return 0;
}
static inline int rf_host_gate(struct rf_host *h, const struct rf_host_ops *o)
{
    if (!h || !o || !o->check || !o->lookup || !o->send || !o->event || h->poisoned) return -1;
    if (o->check(o->context)) { h->poisoned = 1; return -1; }
    return 0;
}
static inline int rf_host_emit(struct rf_host *h, const struct rf_host_ops *o, struct rf_host_tftp *s)
{
    if (rf_host_gate(h, o)) return -1;
    if (o->send(o->context, s->local, s->node, s->port, s->response, s->response_bytes)) {
        h->poisoned = 1; return -1;
    }
    return 0;
}
static inline int rf_host_error(struct rf_host *h, const struct rf_host_ops *o,
    struct rf_host_tftp *s, uint16_t code)
{
    rf_host_be_put(s->response, 5); rf_host_be_put(s->response + 2, code);
    memcpy(s->response + 4, "unavailable", 12); s->response_bytes = 16; s->done = s->complete = 1;
    return rf_host_emit(h, o, s);
}
static inline int rf_host_data(struct rf_host *h, const struct rf_host_ops *o, struct rf_host_tftp *s)
{
    if (s->offset > s->end || !s->block || s->block > 65535 || !s->data) return -1;
    uint32_t bytes = s->end - s->offset;
    if (bytes > s->block_bytes) bytes = s->block_bytes;
    rf_host_be_put(s->response, 3); rf_host_be_put(s->response + 2, (uint16_t)s->block);
    memcpy(s->response + 4, s->data + s->offset, bytes); s->response_bytes = bytes + 4u;
    s->done = bytes < s->block_bytes;
    return rf_host_emit(h, o, s);
}
static inline int rf_host_option(uint8_t *out, uint32_t *used, const char *name, uint32_t value)
{
    unsigned name_bytes = (unsigned)strlen(name) + 1u;
    char digits[11]; unsigned count = 0;
    do { digits[count++] = (char)('0' + value % 10u); value /= 10u; } while (value);
    if (*used + name_bytes + count + 1u > RF_HOST_BLOCK + 256u) return -1;
    memcpy(out + *used, name, name_bytes); *used += name_bytes;
    while (count) out[(*used)++] = (uint8_t)digits[--count];
    out[(*used)++] = 0;
    return 0;
}
static inline int rf_host_tftp_request(struct rf_host *h, const struct rf_host_ops *o,
    uint32_t node, uint32_t port, const uint8_t *data, uint32_t bytes)
{
    if (rf_host_gate(h, o) || bytes < 4 || bytes > 1024) return -1;
    uint16_t command = rf_host_be16(data);
    if (command != 1 && command != 2) return -1;
    char name[RF_HOST_PATH], mode[16]; uint32_t cursor = 2;
    if (rf_host_string(data, bytes, &cursor, name, sizeof(name)) || rf_host_path(name) ||
        rf_host_string(data, bytes, &cursor, mode, sizeof(mode)) || strcmp(mode, "octet")) return -1;
    for (unsigned i = 0; i < 8; ++i) if (h->session[i].used && h->session[i].node == node &&
        h->session[i].port == port && !h->session[i].complete && !strcmp(h->session[i].name, name))
        return rf_host_emit(h, o, &h->session[i]);
    int slot = -1;
    for (unsigned i = 0; i < 8; ++i) if (!h->session[i].used || h->session[i].complete) { slot = (int)i; break; }
    if (slot < 0 || h->serial >= 4096) return -1;
    struct rf_host_tftp *s = &h->session[slot];
    memset(s, 0, sizeof(*s)); s->used = 1; s->write = command == 2; s->node = node; s->port = port;
    s->local = 0x4100u + h->serial++; s->block_bytes = 512; s->ram = -1; memcpy(s->name, name, strlen(name) + 1u);
    bool options = cursor < bytes; uint32_t seek = 0, requested = UINT32_MAX, flags = 0, timeout = 1000, transfer_size = 0;
    for (unsigned count = 0; cursor < bytes; ++count) {
        char option[24], text[16]; uint32_t value;
        if (count >= 16 || rf_host_string(data, bytes, &cursor, option, sizeof(option)) ||
            rf_host_string(data, bytes, &cursor, text, sizeof(text)) || rf_host_decimal(text, &value))
            return rf_host_error(h, o, s, 8);
        unsigned bit = !strcmp(option, "blksize") ? 1u : !strcmp(option, "wsize") ? 2u :
            !strcmp(option, "seek") ? 4u : !strcmp(option, "rsize") ? 8u : !strcmp(option, "tsize") ? 16u :
            !strcmp(option, "timeoutms") ? 32u : 0;
        if (bit && (flags & bit)) return rf_host_error(h, o, s, 8);
        flags |= bit;
        if (bit == 1) {
            if (value < 8 || value > 65535) return rf_host_error(h, o, s, 8);
            s->block_bytes = value > RF_HOST_BLOCK ? RF_HOST_BLOCK : value;
        } else if (bit == 2 && !value) return rf_host_error(h, o, s, 8);
        else if (bit == 4) seek = value;
        else if (bit == 8) requested = value ? value : UINT32_MAX;
        else if (bit == 16) transfer_size = value;
        else if (bit == 32) { if (!value || value > 10000) return rf_host_error(h, o, s, 8); timeout = value; }
    }
    bool writable = !strncmp(name, "/readwrite/", 11);
    if (writable) {
        for (unsigned i = 0; i < 4; ++i) if (h->ram[i].used && !strcmp(h->ram[i].name, name)) s->ram = (int)i;
        if (s->ram < 0 && s->write) for (unsigned i = 0; i < 4; ++i) if (!h->ram[i].used) {
            s->ram = (int)i; h->ram[i].used = 1; memcpy(h->ram[i].name, name, strlen(name) + 1u); break;
        }
        if (s->ram < 0) return rf_host_error(h, o, s, 1);
        struct rf_host_ram *ram = &h->ram[s->ram];
        if (s->write && !seek) ram->bytes = 0;
        s->data = ram->data; s->end = ram->bytes;
    } else {
        if (s->write) return rf_host_error(h, o, s, 2);
        const char *path = name;
        if (!strncmp(path, "/readonly/firmware/", 19)) path += 19;
        else if (!strncmp(path, "/vendor/firmware_mnt/", 21)) path += 21;
        uint32_t length = 0;
        if (strncmp(path, "image/", 6) || o->lookup(o->context, path, &s->data, &length)) {
            ++h->missing; o->event(o->context, 3, name, 0); return rf_host_error(h, o, s, 1);
        }
        s->end = length;
    }
    uint32_t logical_size = s->end;
    if (s->write) {
        if (!writable || seek > sizeof(h->ram[0].data)) return rf_host_error(h, o, s, 3);
        if ((flags & 16u) && transfer_size > sizeof(h->ram[0].data) - seek) return rf_host_error(h, o, s, 3);
        logical_size = transfer_size;
    } else {
        if (seek > s->end) return rf_host_error(h, o, s, 0);
        if (requested < s->end - seek) s->end = seek + requested;
    }
    s->offset = seek; ++h->requests; o->event(o->context, s->write ? 2 : 1, name, s->end);
    options = options && flags != 0;
    if (options) {
        rf_host_be_put(s->response, 6); s->response_bytes = 2;
        if ((flags & 1u) && rf_host_option(s->response, &s->response_bytes, "blksize", s->block_bytes)) return -1;
        if ((flags & 2u) && rf_host_option(s->response, &s->response_bytes, "wsize", 1)) return -1;
        if ((flags & 16u) && rf_host_option(s->response, &s->response_bytes, "tsize", logical_size)) return -1;
        if ((flags & 32u) && rf_host_option(s->response, &s->response_bytes, "timeoutms", timeout)) return -1;
        if ((flags & 4u) && seek && rf_host_option(s->response, &s->response_bytes, "seek", seek)) return -1;
        if ((flags & 8u) && requested != UINT32_MAX &&
            rf_host_option(s->response, &s->response_bytes, "rsize", requested)) return -1;
    } else if (s->write) {
        rf_host_be_put(s->response, 4); rf_host_be_put(s->response + 2, 0); s->response_bytes = 4;
    } else { s->block = 1; return rf_host_data(h, o, s); }
    return rf_host_emit(h, o, s);
}
static inline int rf_host_tftp_packet(struct rf_host *h, const struct rf_host_ops *o,
    uint32_t node, uint32_t from, uint32_t to, const uint8_t *data, uint32_t bytes)
{
    if (rf_host_gate(h, o) || bytes < 4 || bytes > RF_HOST_BLOCK + 4u) return -1;
    struct rf_host_tftp *s = NULL;
    for (unsigned i = 0; i < 8; ++i) if (h->session[i].used && h->session[i].local == to &&
        h->session[i].node == node && h->session[i].port == from) { s = &h->session[i]; break; }
    if (!s) return -1;
    uint16_t command = rf_host_be16(data), block = rf_host_be16(data + 2);
    if (command == 5) { s->done = s->complete = 1; return 0; }
    if (s->write) {
        if (command != 3 || s->ram < 0 || bytes - 4u > s->block_bytes) return -1;
        if (block == s->block) return rf_host_emit(h, o, s);
        if (s->done || block != s->block + 1u || bytes - 4u > sizeof(h->ram[0].data) - s->offset)
            return rf_host_error(h, o, s, 3);
        memcpy(h->ram[s->ram].data + s->offset, data + 4u, bytes - 4u);
        s->offset += bytes - 4u; s->block = block;
        if (h->ram[s->ram].bytes < s->offset) h->ram[s->ram].bytes = s->offset;
        s->done = s->complete = bytes - 4u < s->block_bytes; ++h->writes;
        rf_host_be_put(s->response, 4); rf_host_be_put(s->response + 2, block); s->response_bytes = 4;
        return rf_host_emit(h, o, s);
    }
    if (command != 4 || bytes != 4) return -1;
    if (block + 1u == s->block) return rf_host_emit(h, o, s);
    if (block != s->block) return -1;
    if (s->block && s->done) { s->complete = 1; return 0; }
    if (s->block) s->offset += s->response_bytes - 4u;
    if (++s->block > 65535) return -1;
    ++h->reads; return rf_host_data(h, o, s);
}
static inline int rf_host_pd(struct rf_host *h, const struct rf_host_ops *o, uint32_t node,
    uint32_t from, const uint8_t *data, uint32_t bytes)
{
    if (rf_host_gate(h, o) || bytes < 7 || bytes > 512 || data[0] || rf_host_le16(data + 5) != bytes - 7u)
        return -1;
    uint8_t *out = h->qmi; memset(out, 0, 512); out[0] = 2;
    memcpy(out + 1, data + 1, 4);
    uint32_t used = 14; out[7] = 2; rf_host_le_put(out + 8, 4, 2);
    uint16_t message = rf_host_le16(data + 3);
    char name[80] = {0}; bool found = false;
    if (message == 0x21) for (uint32_t at = 7; at < bytes;) {
        if (bytes - at < 3) return -1;
        uint32_t count = rf_host_le16(data + at + 1);
        if (count > bytes - at - 3u) return -1;
        if (data[at] == 1) {
            if (found || !count || count >= sizeof(name)) return -1;
            for (unsigned i = 0; i < count; ++i) if (data[at + 3u + i] < 32 || data[at + 3u + i] > 126) return -1;
            memcpy(name, data + at + 3u, count); found = true;
        }
        at += 3u + count;
    }
    if (message == 0x21 && found) {
        /* Captured modemr.jsn supplies root servreg/GPS; modemuw.jsn supplies
         * WLAN servreg/ELF loader/fw. Absent PDR/dump services stay absent. */
        bool wlan = !strcmp(name, "wlan/fw") || !strcmp(name, "kernel/elf_loader") || !strcmp(name, "tms/servreg");
        bool root = !strcmp(name, "tms/servreg") || !strcmp(name, "gps/gps_service");
        unsigned matched = (unsigned)wlan + (unsigned)root;
        out[used++] = 0x10; rf_host_le_put(out + used, 2, 2); used += 2;
        rf_host_le_put(out + used, matched, 2); used += 2;
        out[used++] = 0x11; rf_host_le_put(out + used, 2, 2); used += 2;
        rf_host_le_put(out + used, 1, 2); used += 2;
        if (matched) {
            static const char *const domain[2] = {"msm/modem/root_pd", "msm/modem/wlan_pd"};
            uint32_t start = used;
            out[used++] = 0x12; used += 2; out[used++] = (uint8_t)matched;
            for (unsigned i = 0; i < 2; ++i) {
                if (i == 0 ? !root : !wlan) continue;
                unsigned length = (unsigned)strlen(domain[i]);
                out[used++] = (uint8_t)length;
                memcpy(out + used, domain[i], length); used += length;
                rf_host_le_put(out + used, 180, 4); used += 4;
                out[used++] = 0; memset(out + used, 0, 4); used += 4;
            }
            rf_host_le_put(out + start + 1u, used - start - 3u, 2);
        }
        ++h->pd_requests; o->event(o->context, 4, name, matched);
    } else if (message != 0x20) {
        rf_host_le_put(out + 10, 1, 2); rf_host_le_put(out + 12, 0x5e, 2);
    }
    rf_host_le_put(out + 5, used - 7u, 2);
    if (o->send(o->context, 0x4001, node, from, out, used)) { h->poisoned = 1; return -1; }
    return 0;
}
#endif
