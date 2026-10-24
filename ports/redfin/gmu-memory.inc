/* SPDX-License-Identifier: MIT */
/* Reset-held A620 firmware, owned RAM and GMU kernel-stream translation.
 * All allocations and installed state are retained until platform reset.
 */
extern int redfin_mpss_kernel_sha256(void *, const uint8_t *, size_t, uint8_t[32]);
/* The BSD pmap view omits this machine-private declaration. */
extern pmap_paddr_t kvtophys(vm_offset_t);
static const uint32_t gm_memory_policy[] = {
    2, 1, 5, 0x400, 39, 36, 0x100000, 0x28000, RF_GMM_TCR, RF_GMM_TCR2, RF_GMM_SCTLR
};
static struct {
    struct gm_context *context;
    struct redfin_gmu_fw_plan firmware;
    struct rf_gm_pt_plan tables;
    struct rf_gmm_lease lease;
    struct rf_gm_memory data[RF_GM_PT_MAX_EXTENTS], pool;
    unsigned count, allocations, translations, loaded, verified;
    uint64_t allocated;
    uint32_t bytes;
    uint8_t digest[32], image[REDFIN_GMU_MAX_FILE_BYTES];
    bool bound, retained;
} gm_memory;

static bool gm_memory_contract(struct gm_context *context)
{
    DTEntry entry;
    const void *image, *digest;
    unsigned bytes, hash_bytes;
    uint8_t actual[32];
    struct redfin_gmu_fw_plan plan;
    if (SecureDTLookupEntry(NULL, "/redfin-gmu", &entry) != kSuccess ||
        SecureDTGetProperty(entry, "firmware", &image, &bytes) != kSuccess ||
        SecureDTGetProperty(entry, "firmware-sha256", &digest, &hash_bytes) != kSuccess || hash_bytes != 32 ||
        bytes < 16 || bytes > REDFIN_GMU_MAX_FILE_BYTES ||
        !gm_property(context, "/redfin-gmu", "memory-policy", gm_memory_policy, sizeof(gm_memory_policy)) ||
        redfin_mpss_kernel_sha256(NULL, image, bytes, actual) || memcmp(actual, digest, 32) ||
        redfin_gmu_fw_plan_make(gm_chip, image, bytes, &plan)) return false;
    if (!context) return true;
    if (gm_memory.bound) return false;
    memcpy(gm_memory.image, image, bytes); memcpy(gm_memory.digest, digest, 32);
    gm_memory.bytes = bytes; gm_memory.firmware = plan; gm_memory.context = context;
    gm_memory.bound = true;
    return gm_property(context, "/redfin-gmu", "firmware", gm_memory.image, bytes) &&
        gm_property(context, "/redfin-gmu", "firmware-sha256", gm_memory.digest, 32);
}

static bool gm_memory_valid(void *argument)
{
    return gm_memory.bound && argument == gm_memory.context && gm_smmu_valid(argument);
}
static bool gm_memory_same(const struct rf_gm_memory *a, const struct rf_gm_memory *b)
{
    return a->host == b->host && a->physical == b->physical && a->owned_bytes == b->owned_bytes &&
        a->token == b->token && a->gmu_address == b->gmu_address;
}
static bool gm_memory_owns(void *argument, const struct rf_gm_memory *memory, unsigned use)
{
    if (!gm_memory_valid(argument) || !rf_gm_memory_valid(memory)) return false;
    bool own = use == RF_GM_PT_TABLE_POOL && gm_memory_same(memory, &gm_memory.pool);
    if (use == RF_GM_PT_DATA) for (unsigned i = 0; i < gm_memory.count; ++i)
        if (gm_memory_same(memory, &gm_memory.data[i])) own = true;
    if (!own) return false;
    for (uint64_t i = 0; i < memory->owned_bytes; i += 4096)
        if (kvtophys((vm_offset_t)memory->host + i) != memory->physical + i) return false;
    return true;
}
static int gm_memory_allocate(struct rf_gm_memory *out, uint32_t address, uint32_t bytes, uint64_t token)
{
    vm_offset_t host = 0;
    vm_size_t size = (bytes + PAGE_MASK) & ~PAGE_MASK;
    if (!size || size > gm_memory_policy[6] ||
        gm_memory.allocated + size > gm_memory_policy[6]) return EFBIG;
    if (kmem_alloc_contig(kernel_map, &host, size, PAGE_MASK,
            (ppnum_t)((RF_GM_PT_RAM_BASE + RF_GM_PT_RAM_BYTES - 1) >> PAGE_SHIFT), 0,
            KMA_KOBJECT | KMA_ZERO | KMA_DATA, VM_KERN_MEMORY_IOKIT) != KERN_SUCCESS) return ENOMEM;
    ++gm_memory.allocations; gm_memory.allocated += size;
    *out = (struct rf_gm_memory){(void *)host, kvtophys(host), size, token, address};
    return rf_gm_memory_valid(out) ? 0 : ERANGE;
}
static void gm_memory_clean(const struct rf_gm_memory *memory)
{
    for (uintptr_t at = (uintptr_t)memory->host; at < (uintptr_t)memory->host + memory->owned_bytes; at += 64)
        __asm__ volatile("dc cvac, %0" :: "r"(at) : "memory");
    __asm__ volatile("dsb osh" ::: "memory");
}
static int gm_memory_check(void *argument) { return gm_memory_valid(argument) ? 0 : ECANCELED; }
static int gm_memory_sample(void *argument, struct rf_gs_snapshot *global, struct rf_gc_snapshot *banks)
{
    const struct rf_gs_ops gs = {argument, gm_smmu_valid, gm_smmu_read};
    const struct rf_gc_ops gc = {argument, gm_smmu_valid, gm_cb_read};
    int error = rf_gs_snapshot_run(&gs, gm_chip, global);
    return error ? error : rf_gc_snapshot_run(&gc, global, banks);
}
static bool gm_memory_cb_offset(uint32_t at)
{
    return rf_gc_allowed(1, at) || at == 0x28 || at == 0x2c || at == 0x7f4 ||
        at == 0x50 || at == 0x54 || at == 0x8f0;
}
static int gm_memory_read(void *argument, unsigned block, uint32_t at, uint32_t *out)
{
    struct gm_context *context = argument;
    if (!out || block > 1 || !gm_memory_valid(argument)) return ECANCELED;
    if (block) {
        if (!gm_memory_cb_offset(at)) return EINVAL;
        *out = gm_scalar_read(context->cb + 0x1000 + at);
        return 0;
    }
    return gm_smmu_read(argument, at, out);
}
static void gm_memory_store(vm_offset_t address, uint32_t value)
{
    __asm__ volatile("dmb oshst; mov w9, %w0; str w9, [%1]; dsb osh" ::
        "r"(value), "r"(address) : "x9", "memory");
}
static int gm_memory_write(void *argument, unsigned block, uint32_t at, uint32_t value)
{
    struct gm_context *context = argument;
    unsigned expected_block; uint32_t expected_at, expected_value;
    if (!gm_memory.lease.stores || !gm_memory_valid(argument) ||
        rf_gmm_step(&gm_memory.lease, &gm_memory.tables, gm_memory.lease.stores - 1,
                    &expected_block, &expected_at, &expected_value) ||
        block != expected_block || at != expected_at || value != expected_value) return EPERM;
    gm_memory_store((block ? context->cb + 0x1000 : context->smmu) + at, value);
    return 0;
}
static int gm_memory_publish(void *argument, const struct rf_gm_pt_plan *plan)
{
    if (plan != &gm_memory.tables || !gm_memory_owns(argument, &plan->tables, RF_GM_PT_TABLE_POOL)) return EPERM;
    for (unsigned i = 0; i < gm_memory.count; ++i) {
        if (!gm_memory_owns(argument, &gm_memory.data[i], RF_GM_PT_DATA)) return EPERM;
        gm_memory_clean(&gm_memory.data[i]);
    }
    gm_memory_clean(&gm_memory.pool);
    return gm_memory_check(argument);
}
static int gm_memory_delay(void *argument, unsigned microseconds)
{
    if (!gm_memory_valid(argument) || microseconds != 1) return ECANCELED;
    delay(1); return 0;
}

static int gm_memory_transfer(struct gm_context *context, bool tcm)
{
    for (unsigned p = 0; p < gm_memory.firmware.payload_count; ++p) {
        const struct redfin_gmu_payload *payload = &gm_memory.firmware.payloads[p];
        const struct redfin_gmu_region *region = &gm_memory.firmware.regions[payload->region];
        const uint8_t *source = gm_memory.image + payload->file_offset;
        uint32_t offset = payload->address - region->address;
        if ((payload->region < 2) != tcm) continue;
        if (!gm_memory_valid(context)) return ECANCELED;
        printf("REDFIN GMU LOAD: payload=%u address=%#x bytes=%u tcm=%u\n",
            p, payload->address, payload->bytes, tcm);
        if (payload->region < 2) {
            uint32_t mmio;
            if (redfin_gmu_tcm_mmio(region, offset, payload->bytes, &mmio)) return EINVAL;
            for (unsigned j = 0; j < payload->bytes; j += 4) {
                if (!gm_memory_valid(context)) return ECANCELED;
                gm_memory_store(context->base[RF_GT_GMU] + mmio + j, redfin_gmu_read_le32(source + j));
            }
            ++gm_memory.loaded;
            unsigned mismatches = 0;
            for (unsigned j = 0; j < payload->bytes; j += 4) {
                if (!gm_memory_valid(context)) return ECANCELED;
                uint32_t expected = redfin_gmu_read_le32(source + j);
                uint32_t actual = gm_scalar_read(context->base[RF_GT_GMU] + mmio + j);
                if (actual != expected) {
                    if (mismatches < 4)
                        printf("REDFIN GMU TCM MISMATCH: payload=%u address=%#x mmio=%#x expected=%#x actual=%#x\n",
                            p, payload->address + j, mmio + j, expected, actual);
                    ++mismatches;
                }
            }
            printf("REDFIN GMU TCM VERIFIED: payload=%u words=%u mismatches=%u\n",
                p, payload->bytes / 4, mismatches);
            if (mismatches) return EIO;
        } else {
            struct rf_gm_memory *target = &gm_memory.data[payload->region - 2];
            if (!gm_memory_owns(context, target, RF_GM_PT_DATA) || offset > target->owned_bytes ||
                payload->bytes > target->owned_bytes - offset) return EPERM;
            memcpy((uint8_t *)target->host + offset, source, payload->bytes);
            ++gm_memory.loaded;
            if (memcmp((uint8_t *)target->host + offset, source, payload->bytes)) return EIO;
        }
        ++gm_memory.verified;
    }
    if (tcm) return 0;
    for (unsigned i = 0; i < gm_memory.count; ++i)
        if (gm_memory.data[i].gmu_address == gm_memory.firmware.hfi_address)
            return redfin_gmu_hfi_init(gm_memory.data[i].host, REDFIN_GMU_HFI_MAPPED_BYTES,
                gm_memory.firmware.hfi_address, gm_memory.firmware.versions[4]);
    return ENOENT;
}

static int gm_memory_translate(struct gm_context *context, const struct rf_gmm_ops *ops,
    uint32_t address, uint64_t physical)
{
    int error = rf_gmm_verify(&gm_memory.lease, ops);
    if (error) return error;
    uint64_t request = address;
    vm_offset_t ats = context->cb + 0x1000 + 0x800;
    __asm__ volatile("dmb oshst; mov x9, %0; str x9, [%1]; dsb osh" :: "r"(request), "r"(ats) : "x9", "memory");
    uint32_t status = 1, low, high;
    for (unsigned us = 0; us < 1000; ++us) {
        error = gm_memory_read(context, 1, 0x8f0, &status); if (error) return error;
        if (!(status & 1)) break;
        error = gm_memory_delay(context, 1); if (error) return error;
    }
    if (status & 1) return ETIMEDOUT;
    error = gm_memory_read(context, 1, 0x50, &low); if (error) return error;
    error = gm_memory_read(context, 1, 0x54, &high); if (error) return error;
    uint64_t translated = ((uint64_t)high << 32) | low;
    printf("REDFIN GMU ATS: address=%#x PAR=%#llx expected=%#llx\n", address,
        (unsigned long long)translated, (unsigned long long)physical);
    if ((translated & 1) || (translated & 0x0000000ffffff000ULL) != physical) return EFAULT;
    ++gm_memory.translations;
    return rf_gmm_verify(&gm_memory.lease, ops);
}

static int gm_memory_run(struct gm_context *context, const struct rf_gs_snapshot *global,
    const struct rf_gc_snapshot *banks)
{
    int error = gm_memory_check(context);
    struct rf_gm_memory_owner owner = {context, gm_memory_valid, gm_memory_owns};
    struct rf_gmm_ops ops = {context, gm_memory_check, gm_memory_sample, gm_memory_read,
        gm_memory_write, gm_memory_publish, gm_memory_delay};
    unsigned stage = 0;
    if (error) goto done;
    stage = 1; gm_memory.count = gm_memory.firmware.region_count - 2;
    printf("REDFIN GMU MEMORY STEP: bound firmware=%u payloads=%u extents=%u; allocate private zeroed RAM\n",
        gm_memory.bytes, gm_memory.firmware.payload_count, gm_memory.count);
    for (unsigned i = 0; i < gm_memory.count; ++i) {
        const struct redfin_gmu_region *r = &gm_memory.firmware.regions[i + 2];
        error = gm_memory_allocate(&gm_memory.data[i], r->address, r->mapped_bytes, i + 1); if (error) goto done;
    }
    error = gm_memory_allocate(&gm_memory.pool, 0, RF_GM_PT_MAX_TABLES * 4096, 0x100); if (error) goto done;
    stage = 2;
    error = rf_gm_pt_build(global, gm_chip, gm_memory.image, gm_memory.bytes,
        gm_memory.data, gm_memory.count, &gm_memory.pool, &owner, &gm_memory.tables); if (error) goto done;
    printf("REDFIN GMU MEMORY STEP: tables=%u pages=%u root=%#llx; initialize owned RAM and HFI\n",
        gm_memory.tables.table_count, gm_memory.tables.mapped_pages,
        (unsigned long long)gm_memory.tables.root_physical);
    stage = 3; error = gm_memory_transfer(context, false); if (error) goto done;
    stage = 4;
    printf("REDFIN GMU MEMORY STEP: owned RAM/HFI initialized; publish CB1 and stream5\n");
    error = rf_gmm_claim(&gm_memory.lease, &ops, global, banks, &gm_memory.tables, &owner); if (error) goto done;
    gm_memory.retained = true; stage = 5;
    for (unsigned i = 0; i < gm_memory.tables.extent_count; ++i) {
        const struct rf_gm_pt_extent *r = &gm_memory.tables.extents[i];
        error = gm_memory_translate(context, &ops, r->memory.gmu_address, r->memory.physical); if (error) goto done;
        error = gm_memory_translate(context, &ops, r->memory.gmu_address + r->mapped_bytes - 4096,
            r->memory.physical + r->mapped_bytes - 4096); if (error) goto done;
    }
    stage = 6;
    /* Native a6xx_gmu_fw_start enables TCM retention before loading TCM.
     * Translation/ATS is independently proved first, as upstream steps13/14.
     * CM3 remains held; no firmware fetch or HFI execution is allowed. */
    error = gm_memory_check(context); if (error) goto done;
    printf("REDFIN GMU TCM RETENTION: before=%#x requested=1\n",
        gm_scalar_read(context->base[RF_GT_GMU] + 0x14730));
    error = gm_memory_check(context); if (error) goto done;
    gm_memory_store(context->base[RF_GT_GMU] + 0x14730, 1);
    error = gm_memory_check(context); if (error) goto done;
    uint32_t retention = gm_scalar_read(context->base[RF_GT_GMU] + 0x14730);
    printf("REDFIN GMU TCM RETENTION: observed=%#x\n", retention);
    if (retention != 1) { error = EIO; goto done; }
    error = gm_memory_transfer(context, true); if (error) goto done;
    error = rf_gmm_verify(&gm_memory.lease, &ops); if (error) goto done;
    stage = 7;
done:
    if (gm_memory.lease.attempted)
        printf("REDFIN GMU MEMORY LEASE: step=%u block=%u offset=%#x requested=%#x observed=%#x poisoned=%u; CB1 SCTLR=%#x TCR2=%#x TTBR=%#x/%#x TCR=%#x FSR=%#x\n",
            gm_memory.lease.step, gm_memory.lease.block, gm_memory.lease.offset,
            gm_memory.lease.requested, gm_memory.lease.observed, gm_memory.lease.poisoned,
            gm_memory.lease.fresh_banks.words[1][0], gm_memory.lease.fresh_banks.words[1][1],
            gm_memory.lease.fresh_banks.words[1][2], gm_memory.lease.fresh_banks.words[1][3],
            gm_memory.lease.fresh_banks.words[1][4], gm_memory.lease.fresh_banks.words[1][8]);
    printf("REDFIN GMU MEMORY: result=%d stage=%u firmware=%u payloads=%u loaded=%u verified=%u allocations=%u bytes=%llu tables=%u pages=%u bank=1 slot=%u stores=%u translations=%u retained=%u; CM3 reset held, no GX/firmware execution\n",
        error, stage, gm_memory.bytes, gm_memory.firmware.payload_count, gm_memory.loaded,
        gm_memory.verified, gm_memory.allocations,
        (unsigned long long)gm_memory.allocated, gm_memory.tables.table_count, gm_memory.tables.mapped_pages,
        gm_memory.lease.slot, gm_memory.lease.stores, gm_memory.translations, gm_memory.allocations != 0);
    return error;
}
