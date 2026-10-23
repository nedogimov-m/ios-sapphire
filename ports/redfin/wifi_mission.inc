/* SPDX-License-Identifier: MIT
 * Native worker's acknowledged mission entry and bounded CE register reads.
 * No SMMU/CE writes, interrupt registration, ring memory or RX posting.
 */
static int fw_start_mission_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (context != &fw_start || !context->mission_mode || fw_start_glink_check(context) ||
        fw_start_snoc_check(context) || !context->snoc.stable) return EPERM;
    const rf_snoc_ops ops = {context, fw_start_snoc_check, fw_start_snoc_read};
    int error = rf_snoc_observe(&ops, &context->snoc_fresh);
    if (error) return error;
    const rf_snoc_snapshot *before = &context->snoc, *now = &context->snoc_fresh;
    if (before->control != now->control || before->fault != now->fault ||
        memcmp(before->id, now->id, sizeof(now->id)) ||
        memcmp(before->syndrome, now->syndrome, sizeof(now->syndrome)) ||
        memcmp(before->smr, now->smr, sizeof(now->smr)) ||
        memcmp(before->s2cr, now->s2cr, sizeof(now->s2cr)) ||
        memcmp(before->bank, now->bank, sizeof(now->bank))) return EAGAIN;
    return !now->fault && !now->malformed_routes && !now->wlan_matches[0] && !now->wlan_matches[1] ? 0 : EPERM;
}
static int fw_start_mission_send(void *opaque, const uint8_t *data, uint32_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (!data || bytes < 7 || bytes > RF_MISSION_CFG_BYTES || fw_start_mission_check(context)) return EPERM;
    return fw_start_qrtr_queue(context, 1, 0x4004, context->wlfw_node, context->wlfw_port, data, bytes);
}
static int fw_start_ce_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (context != &fw_start || fw_start_glink_check(context) || fw_start_snoc_check(context) ||
        !context->mission_mode || context->mission.poisoned || context->mission.stage != RF_MISSION_COMPLETE ||
        context->mission.waiting || context->mission.responses != 2 || !context->mission_settle_ns ||
        fw_start_ns(context) < context->mission_settle_ns) return EPERM;
    const fw_start_map *entry = &context->ce_map;
    if (!entry->memory && !entry->map && !entry->base) return 0;
    return entry->memory && entry->map && entry->base && entry->map->getVirtualAddress() == entry->base &&
        entry->map->getLength() == RF_CE_MAP_BYTES ? 0 : EPERM;
}
static int fw_start_ce_read(void *opaque, uint32_t at, uint32_t *out)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (!out || !rf_ce_read_allowed(at) || fw_start_ce_check(context) || !context->ce_map.base) return EPERM;
    uintptr_t address = context->ce_map.base + at;
    uint32_t value;
    __asm__ volatile("ldr %w0, [%1]\n\tdmb oshld" : "=r"(value) : "r"(address) : "memory");
    *out = value; return 0;
}
static int fw_start_ce_observe(fw_start_context *context)
{
    if (fw_start_ce_check(context) || context->ce_map.memory || context->ce_map.map || context->ce_map.base ||
        fw_start_mission_check(context) || redfin_wifi_power_audit()) return EPERM;
    fw_start_map *entry = &context->ce_map;
    entry->memory = IOMemoryDescriptor::withPhysicalAddress(RF_CE_BASE, RF_CE_MAP_BYTES, kIODirectionIn);
    entry->map = entry->memory ? entry->memory->map(kIOMapReadOnly | kIOMapInhibitCache) : NULL;
    if (!entry->map || !entry->map->getVirtualAddress() || entry->map->getLength() != RF_CE_MAP_BYTES) return ENOMEM;
    entry->base = (uintptr_t)entry->map->getVirtualAddress();
    const rf_ce_ops ops = {context, fw_start_ce_check, fw_start_ce_read};
    int error = rf_ce_observe(&ops, &context->ce);
    const rf_ce_snapshot *s = &context->ce;
    IOLog("REDFIN WIFI CE: observer=%d stage=%u stable=%u reads=%u changed=%#x WRAP=%#x RRI=%#x/%#x; no CE writes or DMA\n",
        error, s->stage, s->stable, s->reads, s->changed_offset, s->wrapper[0], s->wrapper[1], s->wrapper[2]);
    if (error) return error;
    for (unsigned i = 0; i < RF_CE_COUNT; ++i) {
        const uint32_t *v = s->ce[i];
        IOLog("REDFIN WIFI CE: engine=%u SRC=%#x/%#x/%u DST=%#x/%#x/%u CTRL=%#x IE=%#x IS=%#x misc=%#x/%#x index=%u/%u/%u/%u WM=%#x/%#x\n",
            i, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10],
            v[11], v[12], v[13], v[14], v[15], v[16]);
    }
    if (fw_start_mission_check(context) || redfin_wifi_power_audit()) return EPERM;
    return 0;
}
