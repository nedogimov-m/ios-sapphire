/* SPDX-License-Identifier: MIT
 * Immutable bounded WLAN assets, for the host-owned RAM-only TFTP service.
 * Include after the existing native wifi_firmware.h planner/SHA ABI.
 */
#ifndef REDFIN_WIFI_ASSETS_H
#define REDFIN_WIFI_ASSETS_H
#include <string.h>
struct rf_wlan_asset { char name[64]; const uint8_t *data; uint32_t bytes; };
struct rf_wlan_assets { uint32_t count; struct rf_wlan_asset file[16]; };
static inline int rf_wlan_assets_open(struct rf_wlan_assets *out, const uint8_t *data, size_t bytes,
    const uint8_t expected[32], redfin_mpss_sha256_fn sha, void *context)
{
    if (!out) return -1;
    out->count = 0;
    if (!data || !expected || !sha || bytes < 64 || bytes > 16u * 1024u * 1024u) return -1;
    uint8_t digest[32];
    if (sha(context, data, bytes, digest) || !redfin_mpss_equal(digest, expected, 32) ||
        !redfin_mpss_equal(data, (const uint8_t *)"RFWAS01\0", 8) || redfin_mpss_u32(data + 8) != 1 ||
        redfin_mpss_u64(data + 16) != bytes || redfin_mpss_u64(data + 24) != 128) return -1;
    for (unsigned i = 32; i < 64; ++i) if (data[i]) return -1;
    uint32_t count = redfin_mpss_u32(data + 12);
    if (!count || count > 16 || 64u + count * 128u > bytes) return -1;
    size_t cursor = 64u + count * 128u;
    for (unsigned i = 0; i < count; ++i) {
        const uint8_t *record = data + 64u + i * 128u;
        size_t name = 0;
        while (name < 64 && record[name]) {
            unsigned c = record[name];
            if (!(c == '/' || c == '-' || c == '_' || c == '.' || (c >= 'a' && c <= 'z') ||
                (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'))) return -1;
            ++name;
        }
        if (name < 7 || name >= 64 || memcmp(record, "image/", 6)) return -1;
        for (size_t j = name; j < 64; ++j) if (record[j]) return -1;
        for (size_t j = 0; j + 1 < name; ++j) if (record[j] == '.' && record[j + 1] == '.') return -1;
        uint64_t offset = redfin_mpss_u64(record + 64), length = redfin_mpss_u64(record + 72);
        if (offset != cursor || !length || length > 8u * 1024u * 1024u || offset > bytes || length > bytes - offset)
            return -1;
        for (unsigned j = 112; j < 128; ++j) if (record[j]) return -1;
        if (sha(context, data + cursor, (size_t)length, digest) || !redfin_mpss_equal(digest, record + 80, 32)) return -1;
        for (unsigned j = 0; j < i; ++j) if (!memcmp(out->file[j].name, record, 64)) return -1;
        memcpy(out->file[i].name, record, 64); out->file[i].data = data + cursor; out->file[i].bytes = (uint32_t)length;
        cursor = (size_t)((offset + length + 15u) & ~UINT64_C(15));
        if (cursor > bytes) return -1;
        for (uint64_t j = offset + length; j < cursor; ++j) if (data[(size_t)j]) return -1;
    }
    if (cursor != bytes) return -1;
    out->count = count;
    return 0;
}
static inline int rf_wlan_asset_find(const struct rf_wlan_assets *assets, const char *name,
    const uint8_t **data, uint32_t *bytes)
{
    if (!assets || !name || !data || !bytes || assets->count > 16) return -1;
    for (unsigned i = 0; i < assets->count; ++i) if (!strcmp(assets->file[i].name, name)) {
        *data = assets->file[i].data; *bytes = assets->file[i].bytes; return 0;
    }
    return -1;
}
#endif
