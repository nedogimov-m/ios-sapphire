/* SPDX-License-Identifier: MIT
 * Sole native WLAN worker, after real readiness. APPS SMMU is independently
 * observable in the bounded USB profile; no WLAN/CE/TCU/TBU register is read.
 * This adapter retains read-only local mappings until the platform reset.
 */
static int fw_start_snoc_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (context != &fw_start || fw_start_check(context) || !context->snoc_mode ||
        !context->authenticated || context->reset || context->locked ||
        !context->wlan_observed || !context->dynamic_received ||
        context->wlfw_setup.stage != RF_WLFW_COMPLETE ||
        !(context->wlfw_setup.fw_ready || context->bdf.fw_ready) ||
        (context->bdf.attempted && (context->bdf.stage != RF_BDF_COMPLETE || !context->bdf.cal_reported)))
        return EPERM;
    for (unsigned i = 0; i < 2; ++i) {
        const fw_start_map *entry = &context->snoc_maps[i];
        if (!entry->memory && !entry->map && !entry->base) continue;
        if (!entry->memory || !entry->map || !entry->base ||
            entry->map->getVirtualAddress() != entry->base ||
            entry->map->getLength() != (i ? RF_SNOC_CONTEXT_BYTES : RF_SNOC_GLOBAL_BYTES)) return EPERM;
    }
    return 0;
}
static int fw_start_snoc_read(void *opaque, unsigned block, uint32_t at, uint32_t *out)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (!out || !rf_snoc_read_allowed(block, at) || fw_start_snoc_check(context) ||
        !context->snoc_maps[block].base) return EPERM;
    uintptr_t address = context->snoc_maps[block].base + at;
    uint32_t value;
    __asm__ volatile("ldr %w0, [%1]\n\tdmb oshld" : "=r"(value) : "r"(address) : "memory");
    *out = value;
    return 0;
}
static int fw_start_snoc_observe(fw_start_context *context)
{
    if (fw_start_snoc_check(context) || context->snoc_attempted || redfin_wifi_power_audit()) return EPERM;
    context->snoc_attempted = true;
    for (unsigned i = 0; i < 2; ++i) {
        if (fw_start_snoc_check(context)) return EPERM;
        fw_start_map *entry = &context->snoc_maps[i];
        uint64_t physical = RF_SNOC_SMMU_BASE + (i ? RF_SNOC_CONTEXT_OFFSET : 0);
        uint64_t bytes = i ? RF_SNOC_CONTEXT_BYTES : RF_SNOC_GLOBAL_BYTES;
        entry->memory = IOMemoryDescriptor::withPhysicalAddress(physical, bytes, kIODirectionIn);
        entry->map = entry->memory ? entry->memory->map(kIOMapReadOnly | kIOMapInhibitCache) : NULL;
        if (!entry->map || !entry->map->getVirtualAddress() || entry->map->getLength() != bytes) return ENOMEM;
        entry->base = (uintptr_t)entry->map->getVirtualAddress();
    }
    const rf_snoc_ops ops = {context, fw_start_snoc_check, fw_start_snoc_read};
    int error = rf_snoc_observe(&ops, &context->snoc);
    const rf_snoc_snapshot *s = &context->snoc;
    IOLog("REDFIN WIFI SNOC: observer=%d stage=%u reads=%u changed=%u/%#x stable=%u; no CE access or ownership grant\n",
        error, s->stage, s->reads, s->changed_block, s->changed_offset, s->stable);
    if (error) return error;
    if (fw_start_snoc_check(context) || redfin_wifi_power_audit()) return EPERM;
    IOLog("REDFIN WIFI SNOC: SMMU ID=%#x/%#x/%#x CR0=%#x GFSR=%#x syndrome=%#x/%#x/%#x WLAN=%u/%u slots=%u/%u IPA521=%u malformed=%u blank-unreferenced=%u ownership=0\n",
        s->id[0], s->id[1], s->id[2], s->control, s->fault, s->syndrome[0], s->syndrome[1], s->syndrome[2],
        s->wlan_matches[0], s->wlan_matches[1], s->wlan_slot[0], s->wlan_slot[1], s->ipa_matches,
        s->malformed_routes, s->blank_unreferenced);
    for (unsigned i = 0; i < RF_SNOC_STREAMS; ++i) {
        if (!(s->smr[i] & 0x80000000u)) continue;
        IOLog("REDFIN WIFI SNOC: slot=%u SMR=%#x S2CR=%#x type=%u bank=%u wlan=%u/%u\n", i,
            s->smr[i], s->s2cr[i], (s->s2cr[i] >> 16) & 3u, s->s2cr[i] & 255u,
            rf_snoc_stream_matches(s->smr[i], 0xc0), rf_snoc_stream_matches(s->smr[i], 0xc1));
    }
    for (unsigned i = 0; i < RF_SNOC_CONTEXTS; ++i) {
        const rf_snoc_bank *b = &s->bank[i];
        IOLog("REDFIN WIFI SNOC: bank=%u refs=%u/%u SCTLR=%#x CBAR=%#x CBA2R=%#x FSR=%#x ownership=0\n",
            i, s->references[i], s->active_references[i], b->sctlr, b->cbar, b->cba2r, b->fault);
    }
    return 0;
}
