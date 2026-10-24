/* SPDX-License-Identifier: MIT
 * Native Redfin hardware owner for the complete ath10k-compatible packet and
 * station engine. One bound worker owns routes, MMIO and fresh DMA32 memory.
 * The retained RMTFS allocation is never used by the packet engine.
 */
static uint64_t fw_start_packet_phys(const fw_start_context *context, unsigned i)
{
    const uint64_t physical[4] = {RF_SNOC_SMMU_BASE, RF_SNOC_SMMU_BASE + RF_SNOC_CONTEXT_OFFSET,
        RF_CE_BASE, UINT64_C(0x18830000)};
    return i < 4 ? physical[i] : context->packet_pool[0];
}
static uint64_t fw_start_packet_bytes(const fw_start_context *context, unsigned i)
{
    const uint64_t bytes[4] = {RF_SNOC_GLOBAL_BYTES, RF_SNOC_CONTEXT_BYTES, RF_CE_MAP_BYTES, 16384};
    return i < 4 ? bytes[i] : context->packet_pool[1];
}
static int fw_start_packet_owner(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (context != &fw_start || !context->packets_mode || fw_start_glink_check(context) ||
        fw_start_snoc_check(context) || context->mission.stage != RF_MISSION_COMPLETE || !context->ce.stable)
        return EPERM;
    for (unsigned i = 0; i < 5; ++i) {
        const fw_start_map *m = &context->packet_maps[i];
        if (!m->memory && !m->map && !m->base) continue;
        if (!m->memory || !m->map || !m->base || m->map->getVirtualAddress() != m->base ||
            m->map->getLength() != fw_start_packet_bytes(context, i)) return EPERM;
    }
    return 0;
}
static int fw_start_packet_sample(void *opaque, rf_snoc_snapshot *out)
{
    if (!out || fw_start_packet_owner(opaque)) return EPERM;
    const rf_snoc_ops ops = {opaque, fw_start_snoc_check, fw_start_snoc_read};
    return rf_snoc_observe(&ops, out);
}
static __attribute__((noinline)) void fw_start_packet_store(uintptr_t address, uint32_t value)
{
    /* Force a GPR even for zero: the reviewed Qualcomm global-register trap
     * cannot decode stores using architectural register31. */
    __asm__ volatile("dmb oshst\n\tstr %w0, [%1]\n\tdsb osh" : : "r"(value), "r"(address) : "memory");
}
static int fw_start_packet_route_write(void *opaque, unsigned block, uint32_t at, uint32_t value)
{
    fw_start_context *context = (fw_start_context *)opaque;
    unsigned expected_block = 0; uint32_t expected_at = 0, expected_value = 0;
    if (fw_start_packet_owner(context) || !context->packet_lease.stores || block > 1 ||
        rf_snoc_lease_step(&context->packet_lease, context->packet_lease.stores - 1u,
            &expected_block, &expected_at, &expected_value) ||
        block != expected_block || at != expected_at || value != expected_value || !context->packet_maps[block].base)
        return EPERM;
    ++context->packet_stores;
    fw_start_packet_store(context->packet_maps[block].base + at, value);
    return 0;
}
static int fw_start_packet_route_delay(void *opaque, unsigned us)
{ return us == 1 ? fw_start_pause(opaque, 1) : EINVAL; }
static int fw_start_packet_bus_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_packet_owner(context) || !context->packet_lease.active || context->packet_lease.poisoned) return EPERM;
    const rf_snoc_lease *lease = &context->packet_lease;
    uint32_t value = 0;
    const unsigned block[5] = {0, 0, 1, 0, 0};
    const uint32_t at[5] = {0x800 + 4u*lease->slot, 0xc00 + 4u*lease->slot, 0x1000u*lease->bank,
        0x1800 + 4u*lease->bank, 0x1000 + 4u*lease->bank};
    const uint32_t expected[5] = {0x800100c0, 0x300u | lease->bank, 0, 1, 0x10000};
    for (unsigned i = 0; i < 5; ++i)
        if (fw_start_snoc_read(context, block[i], at[i], &value) || value != expected[i]) return EPERM;
    return 0;
}
static void *fw_start_packet_allocate(void *opaque, uint64_t bytes, uint64_t *physical)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (!physical || !bytes || bytes > 0x1000000 || fw_start_packet_bus_check(context) ||
        !context->packet_maps[4].base) return NULL;
    bytes = (bytes + 4095u) & ~UINT64_C(4095);
    if (context->packet_used > context->packet_buffer[1] || bytes > context->packet_buffer[1] - context->packet_used) return NULL;
    *physical = context->packet_buffer[0] + context->packet_used;
    uintptr_t base = context->packet_maps[4].base + 16384u + context->packet_used;
    context->packet_used += bytes;
    bzero((void *)base, (size_t)bytes);
    __asm__ volatile("dsb sy" ::: "memory");
    return (void *)base;
}
static int fw_start_packet_ce_read(void *opaque, uint32_t at, uint32_t *out)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (!out || !rf_ce_read_allowed(at) || fw_start_packet_bus_check(context) || !context->ce_map.base) return EPERM;
    uintptr_t address = context->ce_map.base + at; uint32_t value;
    __asm__ volatile("ldr %w0, [%1]\n\tdmb oshld" : "=r"(value) : "r"(address) : "memory");
    *out = value;
    return value == UINT32_MAX ? EIO : 0;
}
static const uint32_t fw_packet_source_entries[12] = {16, 0, 0, 32, 2048, 0, 0, 2, 0, 0, 0, 0};
static const uint32_t fw_packet_dest_entries[12] = {0, 512, 64, 0, 0, 512, 0, 2, 128, 512, 512, 512};
static bool fw_start_packet_address(const fw_start_context *context, uint32_t value)
{
    return value >= context->packet_buffer[0] && value < context->packet_buffer[0] + context->packet_used && !(value & 15u);
}
static int fw_start_packet_ce_write(void *opaque, uint32_t at, uint32_t value)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_packet_bus_check(context) || !context->packet_maps[2].base || (at & 3u)) return EPERM;
    unsigned ce = at / 0x1000u, offset = at & 0xfffu, index = RF_CE_OBSERVED_REGS;
    bool allowed = false;
    if (ce == 12) {
        allowed = (offset == 4 && fw_start_packet_address(context, value)) || (offset == 8 && !value);
    } else if (ce < 12) {
        for (unsigned i = 0; i < RF_CE_OBSERVED_REGS; ++i) if (rf_ce_observed_offsets[i] == offset) index = i;
        if (offset == 0 && fw_packet_source_entries[ce]) allowed = fw_start_packet_address(context, value);
        else if (offset == 4 && fw_packet_source_entries[ce]) allowed = !value;
        else if (offset == 8 && fw_packet_source_entries[ce]) allowed = value == fw_packet_source_entries[ce];
        else if (offset == 0x0c && fw_packet_dest_entries[ce]) allowed = fw_start_packet_address(context, value);
        else if (offset == 0x10 && fw_packet_dest_entries[ce]) allowed = !((value ^ context->packet_expected[ce][4]) & ~0x1fu) && !(value & 0x1fu);
        else if (offset == 0x14 && fw_packet_dest_entries[ce]) allowed = value == fw_packet_dest_entries[ce];
        else if (offset == 0x18) {
            uint32_t live = 0;
            uint32_t owned = rf_ce_host_config_mask(offset, fw_packet_source_entries[ce], fw_packet_dest_entries[ce]);
            if (fw_start_packet_ce_read(context, at, &live)) return EPERM;
            allowed = !((value ^ live) & ~owned);
        }
        else if (offset == 0x4c && fw_packet_source_entries[ce]) allowed = value == fw_packet_source_entries[ce];
        else if (offset == 0x50 && fw_packet_dest_entries[ce]) allowed = value == fw_packet_dest_entries[ce];
        else if (offset == 0x40 && fw_packet_dest_entries[ce] && ce != 7) allowed = value < fw_packet_dest_entries[ce];
    }
    if (!allowed) return EPERM;
    ++context->packet_stores;
    fw_start_packet_store(context->packet_maps[2].base + at, value);
    if (ce < 12 && index < RF_CE_OBSERVED_REGS) context->packet_expected[ce][index] = value;
    if (ce == 12) context->packet_rri[offset == 4 ? 0 : 1] = value;
    return 0;
}
static int fw_start_packet_shadow(void *opaque, unsigned ce, uint32_t value)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if ((ce != 0 && ce != 3 && ce != 4) || value >= fw_packet_source_entries[ce] ||
        fw_start_packet_bus_check(context) || !context->packet_maps[3].base) return EPERM;
    ++context->packet_stores;
    fw_start_packet_store(context->packet_maps[3].base + 0x2000 + 4u*ce, value);
    return 0;
}
static int fw_start_packet_guards(fw_start_context *context, bool initial)
{
    if (fw_start_packet_owner(context) || !context->packet_maps[4].base) return EPERM;
    const volatile uint64_t *pool = (const volatile uint64_t *)context->packet_maps[4].base;
    for (uint64_t i = 0; i < context->packet_pool[1] / 8u; ++i) {
        bool guard = i < 2048u || i >= (16384u + context->packet_buffer[1]) / 8u;
        if (guard) { if (pool[(size_t)i] != UINT64_C(0xd3d3d3d3d3d3d3d3)) return EIO; }
        else if (initial) { if (pool[(size_t)i]) return EBUSY; }
        else i = (16384u + context->packet_buffer[1]) / 8u - 1u;
    }
    return 0;
}
static int fw_start_packets_start(fw_start_context *context)
{
    if (fw_start_packet_owner(context) || context->packets_started || context->packet_lease.attempted ||
        fw_start_mission_check(context) || redfin_wifi_power_audit()) return EPERM;
    for (unsigned i = 0; i < 5; ++i) {
        if (fw_start_packet_owner(context)) return EPERM;
        fw_start_map *m = &context->packet_maps[i];
        if (m->memory || m->map || m->base) return EBUSY;
        uint64_t bytes = fw_start_packet_bytes(context, i);
        m->memory = IOMemoryDescriptor::withPhysicalAddress(fw_start_packet_phys(context, i), bytes, kIODirectionInOut);
        m->map = m->memory ? m->memory->map(i == 4 ? kIOMapWriteCombineCache : kIOMapInhibitCache) : NULL;
        if (!m->map || !m->map->getVirtualAddress() || m->map->getLength() != bytes) return ENOMEM;
        m->base = (uintptr_t)m->map->getVirtualAddress();
    }
    int error = fw_start_packet_guards(context, true);
    if (error) return error;
    context->packet_lease_ops = {context, fw_start_packet_owner, fw_start_packet_sample, fw_start_snoc_read,
        fw_start_packet_route_write, fw_start_packet_route_delay};
    error = rf_snoc_lease_claim(&context->packet_lease, &context->packet_lease_ops, &context->snoc);
    IOLog("REDFIN WIFI PACKETS: context lease=%d bank=%u slot=%u stores=%u retained=1\n", error,
        context->packet_lease.bank, context->packet_lease.slot, context->packet_lease.stores);
    if (error) {
        unsigned block = 0; uint32_t at = 0, expected = 0, observed = 0;
        bool changed = rf_snoc_lease_difference(&context->packet_lease, &block, &at, &expected, &observed);
        const rf_snoc_snapshot *fresh = &context->packet_lease.fresh;
        IOLog("REDFIN WIFI PACKETS: lease refusal sample=%u/%u stable=%u changed=%u block=%u at=%#x expected=%#x observed=%#x unstable=%u/%#x\n",
            fresh->stage, fresh->error, fresh->stable, changed, block, at, expected, observed,
            fresh->changed_block, fresh->changed_offset);
        return error;
    }
    memcpy(context->packet_expected, context->ce.ce, sizeof(context->packet_expected));
    const redfin_wifi_radio_ops ops = {context, fw_start_packet_bus_check, fw_start_packet_allocate,
        fw_start_packet_ce_read, fw_start_packet_ce_write, fw_start_packet_shadow};
    error = redfin_wifi_radio_start(&ops);
    if (error) return error;
    context->packets_started = true;
    context->packet_epoch = fw_start_ns(context); context->packet_audit = context->packet_epoch + UINT64_C(1000000000);
    IOLog("REDFIN WIFI PACKETS: native CE/HTC/WMI/HTT engine started, DMA bytes=%llu; station and iOS networking follow readiness\n",
        (unsigned long long)context->packet_used);
    return 0;
}
static int fw_start_packets_poll(fw_start_context *context, uint64_t now)
{
    if (fw_start_packet_bus_check(context)) return EPERM;
    int error = redfin_wifi_radio_poll((uint32_t)((now - context->packet_epoch) / 1000000u));
    if (error) return error;
    if (now >= context->packet_audit) {
        error = rf_snoc_lease_verify(&context->packet_lease, &context->packet_lease_ops);
        if (error) {
            unsigned block = 0; uint32_t at = 0, expected = 0, observed = 0;
            bool changed = rf_snoc_lease_difference(&context->packet_lease, &block, &at, &expected, &observed);
            IOLog("REDFIN WIFI PACKETS: SMMU audit=%d changed=%u block=%u at=%#x expected=%#x observed=%#x sample=%u/%u\n",
                error, changed, block, at, expected, observed, context->packet_lease.fresh.stage, context->packet_lease.fresh.error);
        }
        if (!error) error = fw_start_packet_guards(context, false);
        if (!error) error = redfin_wifi_power_audit();
        for (unsigned ce = 0; !error && ce < RF_CE_COUNT; ++ce) {
            for (unsigned i = 0; i < 7; ++i) {
                uint32_t at = rf_ce_observed_offsets[i];
                uint32_t mask = rf_ce_host_config_mask(at, fw_packet_source_entries[ce], fw_packet_dest_entries[ce]);
                if (!mask) continue;
                uint32_t value = 0;
                error = fw_start_packet_ce_read(context, 0x1000u*ce + at, &value);
                if (!error && ((value ^ context->packet_expected[ce][i]) & mask)) {
                    IOLog("REDFIN WIFI PACKETS: host CE audit CE=%u at=%#x mask=%#x expected=%#x observed=%#x\n",
                        ce, at, mask, context->packet_expected[ce][i], value);
                    error = EAGAIN;
                }
                if (error) break;
            }
        }
        for (unsigned i = 0; !error && i < 2; ++i) {
            uint32_t value = 0, mask = i ? 0x1fu : UINT32_MAX;
            error = fw_start_packet_ce_read(context, 0xc004 + 4u*i, &value);
            if (!error && ((value ^ context->packet_rri[i]) & mask)) {
                IOLog("REDFIN WIFI PACKETS: RRI audit at=%#x expected=%#x observed=%#x\n",
                    0xc004 + 4u*i, context->packet_rri[i], value);
                error = EAGAIN;
            }
        }
        if (error) return error;
        struct redfin_wifi_radio_state state = {};
        redfin_wifi_radio_state(&state);
        IOLog("REDFIN WIFI PACKETS: HTC=%u WMI=%u interface=%u scan=%u station=%u error=%u RX=%u TX=%u DMA=%llu stores=%u\n",
            state.htc, state.wmi, state.ready, state.scanning, state.phase, state.last_error,
            state.received, state.transmitted, (unsigned long long)context->packet_used, context->packet_stores);
        context->packet_audit = now + UINT64_C(1000000000);
    }
    return 0;
}
