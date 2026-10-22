/* SPDX-License-Identifier: MIT */
/*
 * CPU-only A620 GMU 4KiB/LPAE table construction. No SMMU, route, TTBR, TLB,
 * cache-publication or firmware-start operation is provided. Every memory
 * object must already be exclusively allocated and unreachable by DMA.
 * The ownership callbacks prove the host/physical pair and complete lifetime;
 * a routing snapshot alone cannot do so. References: ../GPU-SMMU.md.
 */
#ifndef REDFIN_GMU_PAGETABLES_H
#define REDFIN_GMU_PAGETABLES_H

#include "redfin_gmu_firmware.h"
#include "redfin_gpu_smmu.h"

#define RF_GM_PT_MAX_TABLES 40u
#define RF_GM_PT_MAX_EXTENTS (REDFIN_GMU_MAX_REGIONS - 2u)
#define RF_GM_PT_RAM_BASE UINT64_C(0x180000000)
#define RF_GM_PT_RAM_BYTES UINT64_C(0x80000000)

struct rf_gm_memory {
    void *host;
    uint64_t physical, owned_bytes, token;
    uint32_t gmu_address;
};

enum { RF_GM_PT_DATA = 1, RF_GM_PT_TABLE_POOL = 2 };
struct rf_gm_memory_owner {
    void *context;
    bool (*valid)(void *);
    bool (*owns)(void *, const struct rf_gm_memory *, unsigned);
};

struct rf_gm_pt_node {
    uint32_t level, prefix, parent, slot;
};

struct rf_gm_pt_extent {
    struct rf_gm_memory memory;
    uint32_t mapped_bytes, permissions;
};

struct rf_gm_pt_plan {
    uint32_t table_count, extent_count, mapped_pages, mapped_bytes;
    uint32_t granule, virtual_bits, physical_bits, mair0;
    uint64_t root_physical, table_bytes;
    struct rf_gm_memory tables;
    struct rf_gm_pt_node nodes[RF_GM_PT_MAX_TABLES];
    struct rf_gm_pt_extent extents[RF_GM_PT_MAX_EXTENTS];
};

static inline bool
rf_gm_memory_valid(const struct rf_gm_memory *memory)
{
    if (!memory)
        return false;
    uint64_t host = (uint64_t)(uintptr_t)memory->host;
    return host && memory->token && !(memory->physical & 0xfffu) &&
        memory->owned_bytes && !(memory->owned_bytes & 0xfffu) &&
        memory->owned_bytes <= 0x200000u &&
        memory->physical >= RF_GM_PT_RAM_BASE &&
        memory->physical - RF_GM_PT_RAM_BASE < RF_GM_PT_RAM_BYTES &&
        memory->owned_bytes <= RF_GM_PT_RAM_BYTES -
            (memory->physical - RF_GM_PT_RAM_BASE) &&
        memory->owned_bytes <= UINTPTR_MAX &&
        host <= UINTPTR_MAX - memory->owned_bytes;
}

static inline bool
rf_gm_overlaps(uint64_t first, uint64_t first_bytes,
    uint64_t second, uint64_t second_bytes)
{
    if (!first_bytes || !second_bytes)
        return false;
    return first <= second ? second - first < first_bytes : first - second < second_bytes;
}

static inline bool
rf_gm_host_alias(const struct rf_gm_memory *memory, const void *p, size_t bytes)
{
    return rf_gm_overlaps((uint64_t)(uintptr_t)memory->host, memory->owned_bytes,
        (uint64_t)(uintptr_t)p, bytes);
}

static inline bool
rf_gm_memory_alias(const struct rf_gm_memory *a, const struct rf_gm_memory *b)
{
    return a->token == b->token ||
        rf_gm_overlaps(a->physical, a->owned_bytes, b->physical, b->owned_bytes) ||
        rf_gm_overlaps((uint64_t)(uintptr_t)a->host, a->owned_bytes,
            (uint64_t)(uintptr_t)b->host, b->owned_bytes);
}

static inline bool
rf_gm_snapshot_format(const struct rf_gs_snapshot *s)
{
    return s && s->stable && s->error == 0 && s->stage == 4 && s->map_format_supported &&
        s->page_bytes == 0x1000 && s->global_bytes == 0x8000 &&
        s->streams && s->streams <= RF_GS_MAX_STREAMS &&
        s->contexts && s->contexts <= RF_GS_MAX_CONTEXTS &&
        s->streams == (s->id0 & 255u) && s->contexts == (s->id1 & 255u) &&
        (s->id1 & 0xf0000000u) == 0x20000000u &&
        s->stage2_contexts == ((s->id1 >> 16) & 255u) &&
        s->stage2_contexts <= s->contexts &&
        s->sid_bits == ((s->id0 >> 9) & 15u) &&
        s->input_bits == rf_gs_address_bits(s->id2 & 15u) && s->input_bits &&
        s->output_bits == rf_gs_address_bits((s->id2 >> 4) & 15u) &&
        s->virtual_bits == rf_gs_address_bits((s->id2 >> 8) & 15u) &&
        (s->id0 & (1u << 30)) && (s->id0 & (1u << 27)) && !(s->id0 & (1u << 8)) &&
        (s->id2 & (1u << 12)) && rf_gs_address_bits((s->id2 >> 4) & 15u) >= 36 &&
        rf_gs_address_bits((s->id2 >> 8) & 15u) >= 39 &&
        ((s->id0 >> 9) & 15u) >= 11 && !s->malformed_routes;
}

static inline int
rf_gm_pt_node_index(struct rf_gm_pt_plan *plan, uint32_t level,
    uint32_t prefix, uint32_t parent, uint32_t slot, uint32_t *index)
{
    uint32_t i;
    for (i = 0; i < plan->table_count; i++) {
        if (plan->nodes[i].level == level && plan->nodes[i].prefix == prefix) {
            if (plan->nodes[i].parent != parent || plan->nodes[i].slot != slot)
                return EINVAL;
            *index = i;
            return 0;
        }
    }
    if (plan->table_count == RF_GM_PT_MAX_TABLES)
        return ENOSPC;
    plan->nodes[i].level = level;
    plan->nodes[i].prefix = prefix;
    plan->nodes[i].parent = parent;
    plan->nodes[i].slot = slot;
    plan->table_count++;
    *index = i;
    return 0;
}

static inline void
rf_gm_write_le64(uint8_t *destination, uint64_t value)
{
    for (unsigned i = 0; i < 8; i++)
        destination[i] = (uint8_t)(value >> (8*i));
}

/*
 * All malformed/denied inputs fail before touching the table pool. On a later
 * lifetime revocation, stop writing immediately at the next bounded operation
 * and leave output unchanged. The pool may then contain incomplete CPU-only
 * tables: no success means no caller may publish/install them. The immutable
 * firmware blob, memory metadata and callback state must not change during
 * this call. Callback state must remain disjoint from the writable pool.
 */
static inline int
rf_gm_pt_build(const struct rf_gs_snapshot *snapshot, uint32_t chip,
    const void *image, size_t image_bytes, const struct rf_gm_memory *backing,
    unsigned backing_count, const struct rf_gm_memory *table_pool,
    const struct rf_gm_memory_owner *owner, struct rf_gm_pt_plan *output)
{
    struct redfin_gmu_fw_plan firmware;
    struct rf_gm_pt_plan plan = {0};
    struct rf_gm_memory pool;
    uint64_t image_start = (uint64_t)(uintptr_t)image;
    uint32_t i, j, l2, l3;
    int error;
    if (!output || !backing || !table_pool || !owner || !owner->valid || !owner->owns ||
        backing_count > RF_GM_PT_MAX_EXTENTS || !image ||
        image_bytes > UINTPTR_MAX || image_start > UINTPTR_MAX - image_bytes ||
        (uintptr_t)output > UINTPTR_MAX - sizeof(*output))
        return EINVAL;
    if (!rf_gm_snapshot_format(snapshot))
        return ENOTSUP;
    error = redfin_gmu_fw_plan_make(chip, image, image_bytes, &firmware);
    if (error)
        return error;
    if (backing_count != firmware.region_count - 2u)
        return EINVAL;
    pool = *table_pool;
    if (pool.gmu_address != 0 || !rf_gm_memory_valid(&pool) ||
        rf_gm_host_alias(&pool, image, image_bytes) ||
        rf_gm_host_alias(&pool, snapshot, sizeof(*snapshot)) ||
        rf_gm_host_alias(&pool, backing, backing_count * sizeof(*backing)) ||
        rf_gm_host_alias(&pool, table_pool, sizeof(*table_pool)) ||
        rf_gm_host_alias(&pool, owner, sizeof(*owner)) ||
        rf_gm_host_alias(&pool, output, sizeof(*output)) ||
        rf_gm_overlaps((uintptr_t)output, sizeof(*output), image_start, image_bytes) ||
        rf_gm_overlaps((uintptr_t)output, sizeof(*output),
            (uintptr_t)snapshot, sizeof(*snapshot)) ||
        rf_gm_overlaps((uintptr_t)output, sizeof(*output),
            (uintptr_t)backing, backing_count * sizeof(*backing)) ||
        rf_gm_overlaps((uintptr_t)output, sizeof(*output),
            (uintptr_t)table_pool, sizeof(*table_pool)) ||
        rf_gm_overlaps((uintptr_t)output, sizeof(*output),
            (uintptr_t)owner, sizeof(*owner)))
        return EINVAL;
    plan.extent_count = backing_count;
    plan.granule = 0x1000;
    plan.virtual_bits = 39;
    plan.physical_bits = 36;
    plan.mair0 = 0xf404ff44u;
    plan.root_physical = pool.physical;
    plan.tables = pool;
    plan.table_count = 1;
    plan.nodes[0].level = 1;
    plan.nodes[0].parent = UINT32_MAX;

    for (i = 0; i < backing_count; i++) {
        const struct redfin_gmu_region *region = &firmware.regions[i + 2];
        struct rf_gm_pt_extent *extent = &plan.extents[i];
        for (j = 0; j < backing_count; j++)
            if (backing[j].gmu_address == region->address)
                break;
        if (j == backing_count)
            return EINVAL;
        extent->memory = backing[j];
        extent->mapped_bytes = region->mapped_bytes;
        extent->permissions = region->permissions;
        if (!rf_gm_memory_valid(&extent->memory) ||
            extent->memory.owned_bytes < region->mapped_bytes ||
            rf_gm_memory_alias(&pool, &extent->memory) ||
            rf_gm_host_alias(&extent->memory, image, image_bytes) ||
            rf_gm_host_alias(&extent->memory, output, sizeof(*output)))
            return EINVAL;
        for (j = 0; j < i; j++)
            if (rf_gm_memory_alias(&plan.extents[j].memory, &extent->memory))
                return EINVAL;
        for (j = 0; j < region->mapped_bytes; j += 0x1000) {
            uint32_t va = region->address + j;
            error = rf_gm_pt_node_index(&plan, 2, va >> 30, 0, (va >> 30) & 511u, &l2);
            if (error)
                return error;
            error = rf_gm_pt_node_index(&plan, 3, va >> 21, l2, (va >> 21) & 511u, &l3);
            if (error)
                return error;
            plan.mapped_pages++;
        }
        plan.mapped_bytes += region->mapped_bytes;
    }
    plan.table_bytes = (uint64_t)plan.table_count * 0x1000;
    if (plan.table_bytes > pool.owned_bytes)
        return ENOSPC;
    if (!owner->valid(owner->context))
        return ECANCELED;
    if (!owner->owns(owner->context, &pool, RF_GM_PT_TABLE_POOL))
        return EACCES;
    for (i = 0; i < plan.extent_count; i++) {
        if (!owner->valid(owner->context))
            return ECANCELED;
        if (!owner->owns(owner->context, &plan.extents[i].memory, RF_GM_PT_DATA))
            return EACCES;
    }
    /* All metadata is copied; revalidate the lifetime before the first write. */
    if (!owner->valid(owner->context))
        return ECANCELED;
    for (i = 0; i < plan.table_count; i++) {
        if (!owner->valid(owner->context))
            return ECANCELED;
        uint8_t *table = (uint8_t *)pool.host + i * 0x1000;
        for (j = 0; j < 0x1000; j++)
            table[j] = 0;
    }
    for (i = 1; i < plan.table_count; i++) {
        const struct rf_gm_pt_node *node = &plan.nodes[i];
        uint64_t descriptor = (pool.physical + (uint64_t)i * 0x1000) | 3u;
        if (!owner->valid(owner->context))
            return ECANCELED;
        rf_gm_write_le64((uint8_t *)pool.host + node->parent * 0x1000 + node->slot * 8, descriptor);
    }
    for (i = 0; i < plan.extent_count; i++) {
        const struct rf_gm_pt_extent *extent = &plan.extents[i];
        for (j = 0; j < extent->mapped_bytes; j += 0x1000) {
            uint32_t va = extent->memory.gmu_address + j;
            uint64_t descriptor = extent->memory.physical + j;
            /* Native RW/no-CACHE map: normal-NC, outer-shareable, AF, nG. */
            descriptor |= (extent->permissions & REDFIN_GMU_PRIV) ? 0xe03u : 0xe43u;
            for (l3 = 0; l3 < plan.table_count; l3++)
                if (plan.nodes[l3].level == 3 && plan.nodes[l3].prefix == va >> 21)
                    break;
            if (l3 == plan.table_count)
                return EINVAL;
            if (!owner->valid(owner->context))
                return ECANCELED;
            rf_gm_write_le64((uint8_t *)pool.host + l3 * 0x1000 + ((va >> 12) & 511u) * 8, descriptor);
        }
    }
    if (!owner->valid(owner->context))
        return ECANCELED;
    *output = plan;
    return 0;
}

#endif /* REDFIN_GMU_PAGETABLES_H */
