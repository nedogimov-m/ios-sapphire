/* SPDX-License-Identifier: MIT */
/*
 * Redfin A620v2 GMU firmware planning and the KGSL HFI v2 wire layout.
 * Hardware protocol references are pinned in ../GMU.md. This header performs
 * no MMIO, allocation, SMMU programming, power voting, or firmware start.
 */
#ifndef REDFIN_GMU_FIRMWARE_H
#define REDFIN_GMU_FIRMWARE_H

#include <stdint.h>
#include <stddef.h>
#include <sys/errno.h>

#define REDFIN_GMU_CHIP_ID 0x06020001u
#define REDFIN_GMU_PHYS 0x03d6a000u
#define REDFIN_GMU_REG_BYTES 0x30000u
#define REDFIN_GMU_ITCM_ADDR 0u
#define REDFIN_GMU_DTCM_ADDR 0x10004000u
#define REDFIN_GMU_TCM_BYTES 0x4000u
#define REDFIN_GMU_ITCM_MMIO 0x3000u
#define REDFIN_GMU_DTCM_MMIO 0x7000u
#define REDFIN_GMU_PAGE_BYTES 0x1000u
#define REDFIN_GMU_MAX_FILE_BYTES 0x40000u
#define REDFIN_GMU_MAX_DMA_BYTES 0x100000u
#define REDFIN_GMU_MAX_RECORDS 64u
#define REDFIN_GMU_MAX_REGIONS 20u
#define REDFIN_GMU_MAX_PAYLOADS 32u

/* These permission bits describe the plan, not an ARM SMMU descriptor. */
#define REDFIN_GMU_READ 1u
#define REDFIN_GMU_WRITE 2u
#define REDFIN_GMU_PRIV 4u

#define REDFIN_GMU_HFI_QUEUE_COUNT 4u
#define REDFIN_GMU_HFI_QUEUE_WORDS 1024u
#define REDFIN_GMU_HFI_TABLE_BYTES 216u
#define REDFIN_GMU_HFI_QUEUE_OFFSET 224u
#define REDFIN_GMU_HFI_REQUEST_BYTES 0x40e8u
#define REDFIN_GMU_HFI_MAPPED_BYTES 0x5000u
#define REDFIN_GMU_LOG_BYTES 0x1000u

enum redfin_gmu_memory_kind {
    REDFIN_GMU_ITCM = 0,
    REDFIN_GMU_DTCM,
    REDFIN_GMU_CACHE,
    REDFIN_GMU_KERNEL,
    REDFIN_GMU_HFI,
    REDFIN_GMU_LOG
};

struct redfin_gmu_region {
    uint32_t address;
    uint32_t requested_bytes;
    uint32_t mapped_bytes;
    uint32_t kind;
    uint32_t permissions;
    uint32_t persistent;
};

struct redfin_gmu_payload {
    uint32_t file_offset;
    uint32_t address;
    uint32_t bytes;
    uint32_t region;
};

struct redfin_gmu_fw_plan {
    uint32_t file_bytes;
    uint32_t record_count;
    uint32_t metadata_count;
    uint32_t region_count;
    uint32_t payload_count;
    uint32_t initialized_bytes;
    uint32_t dma_bytes;
    /* core, core_dev, power, power_dev, HFI; DTCM byte offset 0x3fe0. */
    uint32_t versions[5];
    uint32_t hfi_address;
    uint32_t log_address;
    struct redfin_gmu_region regions[REDFIN_GMU_MAX_REGIONS];
    struct redfin_gmu_payload payloads[REDFIN_GMU_MAX_PAYLOADS];
};

static inline uint32_t
redfin_gmu_read_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
        (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static inline void
redfin_gmu_write_le32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16);
    p[3] = (uint8_t)(value >> 24);
}

static inline int
redfin_gmu_contains(uint32_t base, uint32_t size,
    uint32_t address, uint32_t bytes)
{
    return bytes != 0 && address >= base && address - base < size &&
        bytes <= size - (address - base);
}

static inline int
redfin_gmu_domain(uint32_t address, uint32_t bytes)
{
    if (redfin_gmu_contains(REDFIN_GMU_ITCM_ADDR,
            REDFIN_GMU_TCM_BYTES, address, bytes))
        return REDFIN_GMU_ITCM;
    if (redfin_gmu_contains(REDFIN_GMU_DTCM_ADDR,
            REDFIN_GMU_TCM_BYTES, address, bytes))
        return REDFIN_GMU_DTCM;
    if (redfin_gmu_contains(0x4000u, 0xffc000u, address, bytes))
        return REDFIN_GMU_CACHE;
    if (redfin_gmu_contains(0x60000000u, 0x20000000u, address, bytes))
        return REDFIN_GMU_KERNEL;
    /* A620's current kernel firmware does not request a user-context map. */
    return -1;
}

static inline int
redfin_gmu_add_region(struct redfin_gmu_fw_plan *plan,
    uint32_t address, uint32_t requested, uint32_t kind, uint32_t persistent)
{
    uint64_t rounded = ((uint64_t)requested + 0xfffu) & ~UINT64_C(0xfff);
    uint64_t end = (uint64_t)address + rounded;
    uint32_t i;
    struct redfin_gmu_region *region;

    if (!requested || (address & 0xfffu) || rounded > REDFIN_GMU_MAX_DMA_BYTES ||
        end > UINT64_C(0x80000000) ||
        redfin_gmu_domain(address, (uint32_t)rounded) !=
        (kind == REDFIN_GMU_HFI || kind == REDFIN_GMU_LOG ?
            REDFIN_GMU_KERNEL : (int)kind))
        return EINVAL;
    if (plan->region_count == REDFIN_GMU_MAX_REGIONS)
        return ENOSPC;
    if (rounded > REDFIN_GMU_MAX_DMA_BYTES - plan->dma_bytes)
        return EFBIG;
    for (i = 0; i < plan->region_count; i++) {
        const struct redfin_gmu_region *previous = &plan->regions[i];
        if ((uint64_t)address < (uint64_t)previous->address +
                previous->mapped_bytes && previous->address < end)
            return EINVAL;
    }
    region = &plan->regions[plan->region_count++];
    region->address = address;
    region->requested_bytes = requested;
    region->mapped_bytes = (uint32_t)rounded;
    region->kind = kind;
    region->permissions = REDFIN_GMU_READ | REDFIN_GMU_WRITE |
        (kind == REDFIN_GMU_HFI ? 0u : REDFIN_GMU_PRIV);
    region->persistent = persistent;
    plan->dma_bytes += (uint32_t)rounded;
    return 0;
}

/*
 * Validate the entire immutable blob before returning any usable write plan.
 * Native preallocations in TCM refer to the two existing full TCM windows;
 * they are not DMA allocations, and their requests may overlap. Non-TCM
 * preallocations must be distinct. Data header type/value are opaque: the
 * actual A650 image uses 0xefbeadde in both fields, and KGSL ignores them.
 * No output is modified on error. A valid plan does not authenticate firmware.
 */
static inline int
redfin_gmu_fw_plan_make(uint32_t chip, const void *image, size_t bytes,
    struct redfin_gmu_fw_plan *output)
{
    const uint8_t *fw = (const uint8_t *)image;
    struct redfin_gmu_fw_plan plan = {0};
    uint32_t offset = 0, data_seen = 0, i, j, next_kernel = 0x60000000u;
    int error;

    if (!fw || !output || chip != REDFIN_GMU_CHIP_ID || bytes < 16 ||
        bytes > REDFIN_GMU_MAX_FILE_BYTES || (bytes & 3u))
        return EINVAL;
    plan.file_bytes = (uint32_t)bytes;
    plan.region_count = 2;
    plan.regions[0].kind = REDFIN_GMU_ITCM;
    plan.regions[0].address = REDFIN_GMU_ITCM_ADDR;
    plan.regions[1].kind = REDFIN_GMU_DTCM;
    plan.regions[1].address = REDFIN_GMU_DTCM_ADDR;
    for (i = 0; i < 2; i++) {
        plan.regions[i].requested_bytes = REDFIN_GMU_TCM_BYTES;
        plan.regions[i].mapped_bytes = REDFIN_GMU_TCM_BYTES;
        plan.regions[i].permissions = REDFIN_GMU_READ | REDFIN_GMU_WRITE;
    }
    while (offset < bytes) {
        uint32_t address, size, type, value;
        int kind;
        if (bytes - offset < 16 || ++plan.record_count > REDFIN_GMU_MAX_RECORDS)
            return EINVAL;
        address = redfin_gmu_read_le32(fw + offset);
        size = redfin_gmu_read_le32(fw + offset + 4);
        type = redfin_gmu_read_le32(fw + offset + 8);
        value = redfin_gmu_read_le32(fw + offset + 12);
        offset += 16;
        if (size == 0) {
            if (data_seen)
                return EINVAL;
            plan.metadata_count++;
            if (type >= 2 && type <= 6)
                continue; /* Known optional metadata; versions come from DTCM. */
            if (type != 1 && type != 7)
                return ENOTSUP;
            if ((address & 3u) || (value & 3u))
                return EINVAL;
            kind = redfin_gmu_domain(address, value);
            if (kind < 0)
                return EINVAL;
            if (kind == REDFIN_GMU_ITCM || kind == REDFIN_GMU_DTCM)
                continue;
            error = redfin_gmu_add_region(&plan, address, value,
                (uint32_t)kind, type == 7);
            if (error)
                return error;
            if (kind == REDFIN_GMU_KERNEL && address +
                    plan.regions[plan.region_count - 1].mapped_bytes > next_kernel)
                next_kernel = address + plan.regions[plan.region_count - 1].mapped_bytes;
            continue;
        }
        data_seen = 1;
        if (size > bytes - offset || ((address | size) & 3u) ||
            redfin_gmu_domain(address, size) < 0)
            return EINVAL;
        if (plan.payload_count == REDFIN_GMU_MAX_PAYLOADS)
            return ENOSPC;
        for (i = 0; i < plan.region_count; i++)
            if (redfin_gmu_contains(plan.regions[i].address,
                    plan.regions[i].requested_bytes, address, size))
                break;
        if (i == plan.region_count)
            return EINVAL;
        for (j = 0; j < plan.payload_count; j++) {
            const struct redfin_gmu_payload *previous = &plan.payloads[j];
            if ((uint64_t)address < (uint64_t)previous->address +
                    previous->bytes && previous->address < (uint64_t)address + size)
                return EINVAL;
        }
        plan.payloads[plan.payload_count].file_offset = offset;
        plan.payloads[plan.payload_count].address = address;
        plan.payloads[plan.payload_count].bytes = size;
        plan.payloads[plan.payload_count++].region = i;
        plan.initialized_bytes += size;
        offset += size;
    }
    if (!plan.payload_count || !plan.metadata_count)
        return EINVAL;
    /* A partial/missing version tuple cannot determine the start/HFI ABI. */
    for (i = 0; i < 5; i++) {
        uint32_t address = REDFIN_GMU_DTCM_ADDR + 0x3fe0u + i * 4;
        for (j = 0; j < plan.payload_count; j++) {
            const struct redfin_gmu_payload *payload = &plan.payloads[j];
            if (redfin_gmu_contains(payload->address, payload->bytes, address, 4)) {
                plan.versions[i] = redfin_gmu_read_le32(fw + payload->file_offset +
                    address - payload->address);
                break;
            }
        }
        if (j == plan.payload_count)
            return EINVAL;
    }
    if ((plan.versions[4] >> 16) != 0x2000u)
        return ENOTSUP;
    plan.hfi_address = next_kernel;
    error = redfin_gmu_add_region(&plan, next_kernel,
        REDFIN_GMU_HFI_REQUEST_BYTES, REDFIN_GMU_HFI, 0);
    if (error)
        return error;
    next_kernel += REDFIN_GMU_HFI_MAPPED_BYTES;
    plan.log_address = next_kernel;
    error = redfin_gmu_add_region(&plan, next_kernel,
        REDFIN_GMU_LOG_BYTES, REDFIN_GMU_LOG, 0);
    if (error)
        return error;
    *output = plan;
    return 0;
}

/* Convert only a TCM payload into an offset inside the Redfin GMU aperture. */
static inline int
redfin_gmu_tcm_mmio(const struct redfin_gmu_region *region,
    uint32_t offset, uint32_t bytes, uint32_t *aperture_offset)
{
    uint32_t base, address;
    if (!region || !aperture_offset || ((offset | bytes) & 3u))
        return EINVAL;
    if (region->kind == REDFIN_GMU_ITCM) {
        base = REDFIN_GMU_ITCM_MMIO;
        address = REDFIN_GMU_ITCM_ADDR;
    } else if (region->kind == REDFIN_GMU_DTCM) {
        base = REDFIN_GMU_DTCM_MMIO;
        address = REDFIN_GMU_DTCM_ADDR;
    } else {
        return EINVAL;
    }
    if (region->address != address || region->mapped_bytes != REDFIN_GMU_TCM_BYTES ||
        !redfin_gmu_contains(0, REDFIN_GMU_TCM_BYTES, offset, bytes))
        return EINVAL;
    *aperture_offset = base + offset;
    return 0;
}

/* Native KGSL selects the completion mask from the version loaded in DTCM. */
static inline int
redfin_gmu_started(uint32_t core_version, uint32_t result)
{
    return core_version <= 0x20010004u ? result == 0xbabefaceu :
        (result & 0x1ffu) == 0x100u;
}

/*
 * Host-memory construction only. Caller owns a zeroable, contiguous 20KiB
 * view at this GMU IOVA; mapping, cache publication and reset ownership must
 * be established separately. Counts reproduce the pinned native driver,
 * including num_active_q=4 with the dispatch descriptor disabled.
 */
static inline int
redfin_gmu_hfi_init(void *buffer, size_t bytes, uint32_t address, uint32_t version)
{
    uint8_t *p = (uint8_t *)buffer;
    uint32_t i;
    static const uint32_t priorities[4] = {10, 10, 40, 20};
    if (!p || bytes != REDFIN_GMU_HFI_MAPPED_BYTES || (address & 0xfffu) ||
        (version >> 16) != 0x2000u ||
        !redfin_gmu_contains(0x60000000u, 0x20000000u, address, (uint32_t)bytes))
        return EINVAL;
    for (i = 0; i < bytes; i++)
        p[i] = 0;
    redfin_gmu_write_le32(p + 4, REDFIN_GMU_HFI_TABLE_BYTES / 4);
    redfin_gmu_write_le32(p + 8, 6);
    redfin_gmu_write_le32(p + 12, 12);
    redfin_gmu_write_le32(p + 16, REDFIN_GMU_HFI_QUEUE_COUNT);
    redfin_gmu_write_le32(p + 20, REDFIN_GMU_HFI_QUEUE_COUNT);
    for (i = 0; i < REDFIN_GMU_HFI_QUEUE_COUNT; i++) {
        uint8_t *q = p + 24 + 48 * i;
        redfin_gmu_write_le32(q, i == 3 ? 0 : 1);
        redfin_gmu_write_le32(q + 4, address + REDFIN_GMU_HFI_QUEUE_OFFSET + 4096 * i);
        redfin_gmu_write_le32(q + 8, i | priorities[i] << 8);
        redfin_gmu_write_le32(q + 12, REDFIN_GMU_HFI_QUEUE_WORDS);
    }
    return 0;
}

/* Pure v2 ring arithmetic; a caller publishes only after writing and fencing. */
struct redfin_gmu_hfi_write {
    uint32_t first_word;
    uint32_t first_words;
    uint32_t second_words;
    uint32_t padding_words;
    uint32_t next_write;
};

static inline int
redfin_gmu_hfi_write_plan(uint32_t read, uint32_t write, uint32_t message_words,
    struct redfin_gmu_hfi_write *output)
{
    struct redfin_gmu_hfi_write plan;
    uint32_t padded, occupied, available;
    if (!output || read >= 1024 || write >= 1024 || ((read | write) & 3u) ||
        !message_words || message_words > 255)
        return EINVAL;
    padded = (message_words + 3u) & ~3u;
    occupied = (write + 1024u - read) % 1024u;
    available = 1024u - occupied;
    /* Keep the producer/consumer equality unambiguously empty. */
    if (padded >= available)
        return ENOSPC;
    plan.first_word = write;
    plan.first_words = message_words < 1024u - write ? message_words : 1024u - write;
    plan.second_words = message_words - plan.first_words;
    plan.padding_words = padded - message_words;
    plan.next_write = (write + padded) % 1024u;
    *output = plan;
    return 0;
}

static inline int
redfin_gmu_hfi_command_header(uint32_t id, uint32_t words, uint32_t sequence,
    uint32_t *output)
{
    if (!output || id > 255 || !words || words > 255 || !sequence || sequence > 4095)
        return EINVAL;
    *output = id | words << 8 | sequence << 20;
    return 0;
}

/*
 * A future hardware adapter may use this bounded transfer loop. Preflight and
 * guard are read-only: they must prove current CX/clocks, held CM3 reset,
 * image identity, every owned buffer/translation and exclusive lifetime.
 * Initialize/zero DMA buffers and HFI before enabling their owned context.
 * The immutable blob and callback storage must outlive the whole operation.
 * Each write and verification is preceded by a fresh guard. A callback error
 * stops immediately: no retry, firmware start, power down or unsafe rollback.
 * After an attempted write, caller must keep reset asserted and all backing
 * memory pinned until a proved context shutdown or platform reset.
 */
struct redfin_gmu_load_ops {
    void *context;
    int (*preflight)(void *, const struct redfin_gmu_fw_plan *);
    int (*guard)(void *);
    int (*write)(void *, const struct redfin_gmu_region *, uint32_t,
        const uint8_t *, uint32_t);
    int (*publish)(void *);
    int (*verify)(void *, const struct redfin_gmu_region *, uint32_t,
        const uint8_t *, uint32_t);
};

struct redfin_gmu_load_progress {
    uint32_t attempted;
    uint32_t completed;
    uint32_t verified;
};

static inline int
redfin_gmu_fw_load(uint32_t chip, const void *image, size_t bytes,
    const struct redfin_gmu_load_ops *ops, struct redfin_gmu_load_progress *progress)
{
    struct redfin_gmu_fw_plan plan;
    const uint8_t *fw = (const uint8_t *)image;
    uint32_t i;
    int error;
    if (!progress)
        return EINVAL;
    progress->attempted = progress->completed = progress->verified = 0;
    if (!ops || !ops->preflight || !ops->guard || !ops->write ||
        !ops->publish || !ops->verify)
        return EINVAL;
    error = redfin_gmu_fw_plan_make(chip, image, bytes, &plan);
    if (error)
        return error;
    error = ops->preflight(ops->context, &plan);
    if (error)
        return error;
    for (i = 0; i < plan.payload_count; i++) {
        const struct redfin_gmu_payload *payload = &plan.payloads[i];
        const struct redfin_gmu_region *region = &plan.regions[payload->region];
        error = ops->guard(ops->context);
        if (error)
            return error;
        progress->attempted++;
        error = ops->write(ops->context, region, payload->address - region->address,
            fw + payload->file_offset, payload->bytes);
        if (error)
            return error;
        progress->completed++;
    }
    error = ops->guard(ops->context);
    if (error)
        return error;
    error = ops->publish(ops->context);
    if (error)
        return error;
    for (i = 0; i < plan.payload_count; i++) {
        const struct redfin_gmu_payload *payload = &plan.payloads[i];
        const struct redfin_gmu_region *region = &plan.regions[payload->region];
        error = ops->guard(ops->context);
        if (error)
            return error;
        error = ops->verify(ops->context, region, payload->address - region->address,
            fw + payload->file_offset, payload->bytes);
        if (error)
            return error;
        progress->verified++;
    }
    return 0;
}

#endif /* REDFIN_GMU_FIRMWARE_H */
