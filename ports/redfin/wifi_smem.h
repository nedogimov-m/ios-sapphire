/* Read-only SMEM v12 transport inspection; no allocation, locks, MMIO or writes.
 * Layout: Google kernel/msm 500b3a2059c1eec0fec08ec56add06320ea901a8,
 * drivers/soc/qcom/smem.c and drivers/rpmsg/qcom_glink_smem.c.
 * A valid layout does not prove that remote firmware is currently running.
 */
#ifndef REDFIN_WIFI_SMEM_H
#define REDFIN_WIFI_SMEM_H
#include <stddef.h>
#include <stdint.h>

#define REDFIN_SMEM_BYTES 0x200000u
#define REDFIN_SMEM_PHYSICAL 0x80900000ull
#define REDFIN_SMEM_MAX_PARTITIONS 64u
#define REDFIN_SMEM_MAX_ITEMS 4096u

enum redfin_smem_status {
    REDFIN_SMEM_OK, REDFIN_SMEM_LENGTH, REDFIN_SMEM_UNINITIALIZED,
    REDFIN_SMEM_VERSION, REDFIN_SMEM_TOC, REDFIN_SMEM_PARTITION,
    REDFIN_SMEM_ITEM, REDFIN_SMEM_GLINK, REDFIN_SMEM_CHANGED
};
struct redfin_smem_report {
    uint32_t version, partitions, modem_partition, partition_offset, partition_bytes;
    uint32_t uncached_items, cached_uninspected, descriptor, tx_bytes, rx_bytes;
    uint32_t tx_tail, tx_head, rx_tail, rx_head, tx_pending, rx_pending;
};

static inline uint16_t redfin_smem_u16(const volatile uint8_t *p)
{ return (uint16_t)((uint16_t)p[0] | (uint16_t)p[1] << 8); }
static inline uint32_t redfin_smem_u32(const volatile uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static inline int redfin_smem_magic(const volatile uint8_t *p, const char *s)
{ return p[0] == (uint8_t)s[0] && p[1] == (uint8_t)s[1] && p[2] == (uint8_t)s[2] && p[3] == (uint8_t)s[3]; }

static inline enum redfin_smem_status
redfin_smem_inspect(const volatile uint8_t *data, size_t length,
                    struct redfin_smem_report *report)
{
    const uint32_t toc = REDFIN_SMEM_BYTES - 0x1000u;
    uint32_t offsets[REDFIN_SMEM_MAX_PARTITIONS], sizes[REDFIN_SMEM_MAX_PARTITIONS];
    uint32_t item_offsets[3] = {0, 0, 0}, item_sizes[3] = {0, 0, 0};
#ifdef __cplusplus
    struct redfin_smem_report out = {};
#else
    struct redfin_smem_report out = {0};
#endif
    uint32_t part_hosts = 0, free_u, free_c;
    if (!report) return REDFIN_SMEM_LENGTH;
    *report = out;
    if (!data || length != REDFIN_SMEM_BYTES) return REDFIN_SMEM_LENGTH;
    out.version = redfin_smem_u32(data + 0x40u + 7u * 4u);
    *report = out;
    if (redfin_smem_u32(data + 0xc0u) != 1 || redfin_smem_u32(data + 0xccu))
        return REDFIN_SMEM_UNINITIALIZED;
    if ((out.version >> 16) != 12) return REDFIN_SMEM_VERSION;
    if (!redfin_smem_magic(data + toc, "$TOC") || redfin_smem_u32(data + toc + 4) != 1)
        return REDFIN_SMEM_TOC;
    out.partitions = redfin_smem_u32(data + toc + 8);
    if (!out.partitions || out.partitions > REDFIN_SMEM_MAX_PARTITIONS)
        return REDFIN_SMEM_TOC;
    for (uint32_t i = 0; i < out.partitions; ++i) {
        const volatile uint8_t *entry = data + toc + 32u + i * 48u;
        uint32_t offset = redfin_smem_u32(entry), size = redfin_smem_u32(entry + 4);
        uint32_t hosts = redfin_smem_u32(entry + 12);
        offsets[i] = offset; sizes[i] = size;
        if (!offset && !size) continue;
        if (offset < 0x1000u || size < 32u || offset > toc || size > toc - offset)
            return REDFIN_SMEM_PARTITION;
        for (uint32_t j = 0; j < i; ++j) {
            if (sizes[j] && offset < offsets[j] + sizes[j] && offsets[j] < offset + size)
                return REDFIN_SMEM_PARTITION;
        }
        if (hosts == 0x00010000u || hosts == 0x00000001u) {
            if (out.modem_partition) return REDFIN_SMEM_PARTITION;
            out.modem_partition = 1; out.partition_offset = offset; out.partition_bytes = size;
            part_hosts = hosts;
        }
    }
    if (!out.modem_partition) { *report = out; return REDFIN_SMEM_OK; }
    const volatile uint8_t *part = data + out.partition_offset;
    if (!redfin_smem_magic(part, "$PRT") || redfin_smem_u32(part + 4) != part_hosts ||
        redfin_smem_u32(part + 8) != out.partition_bytes) return REDFIN_SMEM_PARTITION;
    free_u = redfin_smem_u32(part + 12); free_c = redfin_smem_u32(part + 16);
    if (free_u < 32 || free_u > free_c || free_c > out.partition_bytes)
        return REDFIN_SMEM_PARTITION;
    out.cached_uninspected = free_c != out.partition_bytes;
    uint32_t cursor = 32;
    while (cursor < free_u) {
        if (++out.uncached_items > REDFIN_SMEM_MAX_ITEMS || free_u - cursor < 16)
            return REDFIN_SMEM_ITEM;
        const volatile uint8_t *entry = part + cursor;
        uint32_t size = redfin_smem_u32(entry + 4);
        uint32_t padding = redfin_smem_u16(entry + 8), header_pad = redfin_smem_u16(entry + 10);
        uint32_t item = redfin_smem_u16(entry + 2), remaining = free_u - cursor - 16;
        if (redfin_smem_u16(entry) != 0xa5a5u || !size || padding >= size ||
            header_pad > remaining || size > remaining - header_pad) return REDFIN_SMEM_ITEM;
        if (item >= 478 && item <= 480) {
            unsigned slot = item - 478;
            if (item_offsets[slot]) return REDFIN_SMEM_ITEM;
            item_offsets[slot] = out.partition_offset + cursor + 16 + header_pad;
            item_sizes[slot] = size - padding;
        }
        cursor += 16 + header_pad + size;
    }
    out.descriptor = item_sizes[0] != 0; out.tx_bytes = item_sizes[1]; out.rx_bytes = item_sizes[2];
    if ((out.descriptor && item_sizes[0] != 32) ||
        (out.tx_bytes && (out.tx_bytes < 16 || out.tx_bytes > 0x10000 || (out.tx_bytes & 7))) ||
        (out.rx_bytes && (out.rx_bytes < 16 || out.rx_bytes > 0x10000 || (out.rx_bytes & 7))))
        return REDFIN_SMEM_GLINK;
    if (out.descriptor) {
        const volatile uint8_t *desc = data + item_offsets[0];
        out.tx_tail = redfin_smem_u32(desc); out.tx_head = redfin_smem_u32(desc + 4);
        out.rx_tail = redfin_smem_u32(desc + 8); out.rx_head = redfin_smem_u32(desc + 12);
        if ((out.tx_tail | out.tx_head | out.rx_tail | out.rx_head) & 7) return REDFIN_SMEM_GLINK;
        if ((out.tx_bytes && (out.tx_tail >= out.tx_bytes || out.tx_head >= out.tx_bytes)) ||
            (out.rx_bytes && (out.rx_tail >= out.rx_bytes || out.rx_head >= out.rx_bytes)))
            return REDFIN_SMEM_GLINK;
        if (out.tx_bytes) out.tx_pending = (out.tx_head + out.tx_bytes - out.tx_tail) % out.tx_bytes;
        if (out.rx_bytes) out.rx_pending = (out.rx_head + out.rx_bytes - out.rx_tail) % out.rx_bytes;
    }
    /* No shared lock is taken: reject observed allocator-header changes. Stable
     * or nonzero ring indices still do not establish liveness or QMI readiness. */
    if (redfin_smem_u32(part + 12) != free_u || redfin_smem_u32(part + 16) != free_c ||
        redfin_smem_u32(data + toc + 8) != out.partitions ||
        redfin_smem_u32(data + 0x40u + 7u * 4u) != out.version ||
        redfin_smem_u32(data + 0xc0u) != 1) return REDFIN_SMEM_CHANGED;
    *report = out;
    return REDFIN_SMEM_OK;
}
#endif
