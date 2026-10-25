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
#define REDFIN_SMEM_INDEX_NONE 0xffffffffu

enum redfin_smem_status {
    REDFIN_SMEM_OK, REDFIN_SMEM_LENGTH, REDFIN_SMEM_UNINITIALIZED,
    REDFIN_SMEM_VERSION, REDFIN_SMEM_TOC, REDFIN_SMEM_PARTITION,
    REDFIN_SMEM_ITEM, REDFIN_SMEM_GLINK, REDFIN_SMEM_CHANGED
};
/* Partition rejection detail; zero means no partition-specific rejection. */
enum redfin_smem_detail {
    REDFIN_SMEM_DETAIL_NONE, REDFIN_SMEM_ENTRY_ONE_ZERO,
    REDFIN_SMEM_ENTRY_BOUNDS, REDFIN_SMEM_ENTRY_OVERLAP,
    REDFIN_SMEM_MODEM_DUPLICATE, REDFIN_SMEM_HEADER_MAGIC,
    REDFIN_SMEM_HEADER_HOSTS, REDFIN_SMEM_HEADER_SIZE,
    REDFIN_SMEM_HEADER_FREE
};
struct redfin_smem_report {
    uint32_t version, partitions, modem_partition, partition_offset, partition_bytes;
    uint32_t uncached_items, cached_uninspected, descriptor, tx_bytes, rx_bytes;
    uint32_t tx_tail, tx_head, rx_tail, rx_head, tx_pending, rx_pending;
    uint32_t failure_detail, toc_version, entry_index, entry_offset, entry_bytes;
    uint32_t entry_host0, entry_host1, entry_cacheline, other_index, other_offset, other_bytes;
    uint32_t header_present, header_magic, header_host0, header_host1, header_bytes;
    uint32_t free_uncached, free_cached;
};

static inline uint16_t redfin_smem_u16(const volatile uint8_t *p)
{ return (uint16_t)((uint16_t)p[0] | (uint16_t)p[1] << 8); }
static inline uint32_t redfin_smem_u32(const volatile uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static inline int redfin_smem_magic(const volatile uint8_t *p, const char *s)
{ return p[0] == (uint8_t)s[0] && p[1] == (uint8_t)s[1] && p[2] == (uint8_t)s[2] && p[3] == (uint8_t)s[3]; }

static inline void
redfin_smem_entry_metadata(const volatile uint8_t *entry, uint32_t index,
                          struct redfin_smem_report *out)
{
    out->entry_index = index;
    out->entry_offset = redfin_smem_u32(entry);
    out->entry_bytes = redfin_smem_u32(entry + 4);
    out->entry_host0 = redfin_smem_u16(entry + 12);
    out->entry_host1 = redfin_smem_u16(entry + 14);
    out->entry_cacheline = redfin_smem_u32(entry + 16);
    out->header_present = 0;
    out->header_magic = out->header_host0 = out->header_host1 = out->header_bytes = 0;
    out->free_uncached = out->free_cached = 0;
}

/* Called only after the entry's complete 32-byte header is proved in range. */
static inline void
redfin_smem_header_metadata(const volatile uint8_t *part, struct redfin_smem_report *out)
{
    out->header_magic = redfin_smem_u32(part);
    out->header_host0 = redfin_smem_u16(part + 4);
    out->header_host1 = redfin_smem_u16(part + 6);
    out->header_bytes = redfin_smem_u32(part + 8);
    out->free_uncached = redfin_smem_u32(part + 12);
    out->free_cached = redfin_smem_u32(part + 16);
    out->header_present = 1;
}

static inline enum redfin_smem_status
redfin_smem_result(struct redfin_smem_report *report, struct redfin_smem_report *out,
                   enum redfin_smem_status status, enum redfin_smem_detail detail)
{
    out->failure_detail = (uint32_t)detail;
    *report = *out;
    return status;
}

static inline enum redfin_smem_status
redfin_smem_inspect_host(const volatile uint8_t *data, size_t length,
                    uint32_t remote_host, struct redfin_smem_report *report)
{
    const uint32_t toc = REDFIN_SMEM_BYTES - 0x1000u;
    uint32_t offsets[REDFIN_SMEM_MAX_PARTITIONS], sizes[REDFIN_SMEM_MAX_PARTITIONS];
    uint32_t item_offsets[3] = {0, 0, 0}, item_sizes[3] = {0, 0, 0};
#ifdef __cplusplus
    struct redfin_smem_report out = {};
#else
    struct redfin_smem_report out = {0};
#endif
    uint32_t part_hosts = 0, modem_index = REDFIN_SMEM_INDEX_NONE, free_u, free_c;
    if (!report) return REDFIN_SMEM_LENGTH;
    out.entry_index = out.other_index = REDFIN_SMEM_INDEX_NONE;
    *report = out;
    if (!data || length != REDFIN_SMEM_BYTES || (remote_host!=1 && remote_host!=2)) return REDFIN_SMEM_LENGTH;
    out.version = redfin_smem_u32(data + 0x40u + 7u * 4u);
    if (redfin_smem_u32(data + 0xc0u) != 1 || redfin_smem_u32(data + 0xccu))
        return redfin_smem_result(report, &out, REDFIN_SMEM_UNINITIALIZED, REDFIN_SMEM_DETAIL_NONE);
    if ((out.version >> 16) != 12)
        return redfin_smem_result(report, &out, REDFIN_SMEM_VERSION, REDFIN_SMEM_DETAIL_NONE);
    out.toc_version = redfin_smem_u32(data + toc + 4);
    if (!redfin_smem_magic(data + toc, "$TOC") || out.toc_version != 1)
        return redfin_smem_result(report, &out, REDFIN_SMEM_TOC, REDFIN_SMEM_DETAIL_NONE);
    out.partitions = redfin_smem_u32(data + toc + 8);
    if (!out.partitions || out.partitions > REDFIN_SMEM_MAX_PARTITIONS)
        return redfin_smem_result(report, &out, REDFIN_SMEM_TOC, REDFIN_SMEM_DETAIL_NONE);
    for (uint32_t i = 0; i < out.partitions; ++i) {
        const volatile uint8_t *entry = data + toc + 32u + i * 48u;
        redfin_smem_entry_metadata(entry, i, &out);
        uint32_t offset = out.entry_offset, size = out.entry_bytes;
        uint32_t hosts = redfin_smem_u32(entry + 12);
        offsets[i] = offset; sizes[i] = 0;
        /* smem.c:965 selects APPS before interpreting a private partition.
         * Firmware also lists its TOC reservation as ffff/ffff; that is not
         * an APPS heap. Keep the separately supported global fffe/fffe heap
         * in overlap checks, but never dereference other hosts' entries.
         */
        if (out.entry_host0 != 0 && out.entry_host1 != 0 && hosts != 0xfffefffeu)
            continue;
        if (!offset && !size) continue;
        /* Google skips either-zero entries; retain our stricter rejection and
         * diagnose it before deciding whether a real firmware layout needs it. */
        if (!offset || !size)
            return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_ENTRY_ONE_ZERO);
        if (offset < 0x1000u || size < 32u || offset > toc || size > toc - offset)
            return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_ENTRY_BOUNDS);
        sizes[i] = size;
        redfin_smem_header_metadata(data + offset, &out);
        for (uint32_t j = 0; j < i; ++j) {
            if (sizes[j] && offset < offsets[j] + sizes[j] && offsets[j] < offset + size) {
                out.other_index = j; out.other_offset = offsets[j]; out.other_bytes = sizes[j];
                return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_ENTRY_OVERLAP);
            }
        }
        if (hosts == remote_host<<16 || hosts == remote_host) {
            if (out.modem_partition) {
                out.other_index = modem_index;
                out.other_offset = out.partition_offset; out.other_bytes = out.partition_bytes;
                return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_MODEM_DUPLICATE);
            }
            out.modem_partition = 1; out.partition_offset = offset; out.partition_bytes = size;
            part_hosts = hosts; modem_index = i;
        }
    }
    if (!out.modem_partition)
        return redfin_smem_result(report, &out, REDFIN_SMEM_OK, REDFIN_SMEM_DETAIL_NONE);
    const volatile uint8_t *part = data + out.partition_offset;
    redfin_smem_entry_metadata(data + toc + 32u + modem_index * 48u, modem_index, &out);
    redfin_smem_header_metadata(part, &out);
    if (out.header_magic != 0x54525024u)
        return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_HEADER_MAGIC);
    if ((out.header_host0 | out.header_host1 << 16) != part_hosts)
        return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_HEADER_HOSTS);
    if (out.header_bytes != out.partition_bytes)
        return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_HEADER_SIZE);
    free_u = out.free_uncached; free_c = out.free_cached;
    if (free_u < 32 || free_u > free_c || free_c > out.partition_bytes)
        return redfin_smem_result(report, &out, REDFIN_SMEM_PARTITION, REDFIN_SMEM_HEADER_FREE);
    out.cached_uninspected = free_c != out.partition_bytes;
    uint32_t cursor = 32;
    while (cursor < free_u) {
        if (++out.uncached_items > REDFIN_SMEM_MAX_ITEMS || free_u - cursor < 16)
            return redfin_smem_result(report, &out, REDFIN_SMEM_ITEM, REDFIN_SMEM_DETAIL_NONE);
        const volatile uint8_t *entry = part + cursor;
        uint32_t size = redfin_smem_u32(entry + 4);
        uint32_t padding = redfin_smem_u16(entry + 8), header_pad = redfin_smem_u16(entry + 10);
        uint32_t item = redfin_smem_u16(entry + 2), remaining = free_u - cursor - 16;
        if (redfin_smem_u16(entry) != 0xa5a5u || !size || padding >= size ||
            header_pad > remaining || size > remaining - header_pad)
            return redfin_smem_result(report, &out, REDFIN_SMEM_ITEM, REDFIN_SMEM_DETAIL_NONE);
        if (item >= 478 && item <= 480) {
            unsigned slot = item - 478;
            if (item_offsets[slot])
                return redfin_smem_result(report, &out, REDFIN_SMEM_ITEM, REDFIN_SMEM_DETAIL_NONE);
            item_offsets[slot] = out.partition_offset + cursor + 16 + header_pad;
            item_sizes[slot] = size - padding;
        }
        cursor += 16 + header_pad + size;
    }
    out.descriptor = item_sizes[0] != 0; out.tx_bytes = item_sizes[1]; out.rx_bytes = item_sizes[2];
    if ((out.descriptor && item_sizes[0] != 32) ||
        (out.tx_bytes && (out.tx_bytes < 16 || out.tx_bytes > 0x10000 || (out.tx_bytes & 7))) ||
        (out.rx_bytes && (out.rx_bytes < 16 || out.rx_bytes > 0x10000 || (out.rx_bytes & 7))))
        return redfin_smem_result(report, &out, REDFIN_SMEM_GLINK, REDFIN_SMEM_DETAIL_NONE);
    if (out.descriptor) {
        const volatile uint8_t *desc = data + item_offsets[0];
        out.tx_tail = redfin_smem_u32(desc); out.tx_head = redfin_smem_u32(desc + 4);
        out.rx_tail = redfin_smem_u32(desc + 8); out.rx_head = redfin_smem_u32(desc + 12);
        if ((out.tx_tail | out.tx_head | out.rx_tail | out.rx_head) & 7)
            return redfin_smem_result(report, &out, REDFIN_SMEM_GLINK, REDFIN_SMEM_DETAIL_NONE);
        if ((out.tx_bytes && (out.tx_tail >= out.tx_bytes || out.tx_head >= out.tx_bytes)) ||
            (out.rx_bytes && (out.rx_tail >= out.rx_bytes || out.rx_head >= out.rx_bytes)))
            return redfin_smem_result(report, &out, REDFIN_SMEM_GLINK, REDFIN_SMEM_DETAIL_NONE);
        if (out.tx_bytes) out.tx_pending = (out.tx_head + out.tx_bytes - out.tx_tail) % out.tx_bytes;
        if (out.rx_bytes) out.rx_pending = (out.rx_head + out.rx_bytes - out.rx_tail) % out.rx_bytes;
    }
    /* No shared lock is taken: reject observed allocator-header changes. Stable
     * or nonzero ring indices still do not establish liveness or QMI readiness. */
    if (redfin_smem_u32(part + 12) != free_u || redfin_smem_u32(part + 16) != free_c ||
        redfin_smem_u32(data + toc + 8) != out.partitions ||
        redfin_smem_u32(data + 0x40u + 7u * 4u) != out.version ||
        redfin_smem_u32(data + 0xc0u) != 1)
        return redfin_smem_result(report, &out, REDFIN_SMEM_CHANGED, REDFIN_SMEM_DETAIL_NONE);
    return redfin_smem_result(report, &out, REDFIN_SMEM_OK, REDFIN_SMEM_DETAIL_NONE);
}
/* Keep the established APPS/MPSS interface and report layout unchanged. The
 * legacy modem_partition field means the selected private heap for host2. */
static inline enum redfin_smem_status
redfin_smem_inspect(const volatile uint8_t *data,size_t bytes,struct redfin_smem_report *report)
{return redfin_smem_inspect_host(data,bytes,1,report);}
#endif
