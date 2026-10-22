/* SPDX-License-Identifier: MIT
 * Redfin native Wi-Fi prerequisite observation. No writable mappings, TCSR,
 * IPCC, RSC, PAS, firmware loading, UFS access or background worker.
 * Source topology is checked by wifi_platform.py before emitting this ADT
 * leaf; the kernel independently enforces the exact ABI and md0/UP/return
 * gates. This leaf grants observation only, never a hardware-write lease.
 */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <sys/errno.h>
#include "redfin_wifi_native_probe.h"
#include "../../../bsd/dev/redfin_wifi_aop.h"
#include "../../../bsd/dev/redfin_rpmh.h"
#include "../../bsddev/redfin_wifi_smem.h"

extern "C" int redfin_spmi_return_ready(void);

struct wf_map {
    IOMemoryDescriptor *memory;
    IOMemoryMap *mapping;
};
struct wf_context { uintptr_t base; bool active; };

static bool wf_property(DTEntry entry, const char *key, void *out, unsigned bytes)
{
    const void *raw = NULL;
    unsigned length = 0;
    if (SecureDTGetProperty(entry, key, &raw, &length) != kSuccess || !raw || length != bytes)
        return false;
    memcpy(out, raw, bytes);
    return true;
}

static bool wf_identity(void)
{
    DTEntry root;
    const char *raw = NULL;
    unsigned bytes = 0;
    bool redfin = false, lito = false;
    if (SecureDTLookupEntry(NULL, "/", &root) != kSuccess ||
        SecureDTGetProperty(root, "compatible", (const void **)&raw, &bytes) != kSuccess ||
        !raw || !bytes || bytes > 256 || raw[bytes - 1]) return false;
    for (unsigned at = 0; at < bytes;) {
        unsigned end = at;
        while (end < bytes && raw[end]) ++end;
        if (end == bytes || at == end) return false;
        if (end - at == 13 && !memcmp(raw + at, "google,redfin", 13)) redfin = true;
        if (end - at == 11 && !memcmp(raw + at, "qcom,sm7250", 11)) lito = true;
        at = end + 1;
    }
    return redfin && lito;
}

static bool wf_zero_arg(const char *key, bool required)
{
    int value = -1;
    bool present = PE_parse_boot_argn(key, &value, sizeof(value));
    return present ? value == 0 : !required;
}

static bool wf_platform(uint64_t ranges[6])
{
    const uint64_t expected[6] = {RF_WIFI_AOP_PHYSICAL, RF_WIFI_AOP_BYTES,
        REDFIN_SMEM_PHYSICAL, REDFIN_SMEM_BYTES, UINT64_C(0x80860000), RF_CMDDB_BYTES};
    const uint32_t witness[12] = {1, 4, 384, 384, 3, 435, 428, 1, 0, 0x00020002, 1, 3};
    uint32_t proof = 0, source[12] = {};
    uint64_t ram_base = 0, ram_bytes = 0, boot_id = 0;
    int cpus = 0, spmi = 0, returned = 0, wifi_mode = 0;
    char root[16] = {};
    DTEntry entry, chosen;
    if (!wf_identity() ||
        !PE_parse_boot_argn("cpus", &cpus, sizeof(cpus)) || cpus != 1 ||
        !PE_parse_boot_argn("redfinwifi", &wifi_mode, sizeof(wifi_mode)) || wifi_mode != 2 ||
        !PE_parse_boot_argn("rd", root, sizeof(root)) || root[sizeof(root) - 1] || strcmp(root, "md0") ||
        !PE_parse_boot_argn("redfinspmi", &spmi, sizeof(spmi)) || spmi != 1 ||
        !PE_parse_boot_argn("redfinreturn", &returned, sizeof(returned)) || returned != 1 ||
        !PE_parse_boot_argn("redfinbootid", &boot_id, sizeof(boot_id)) || !boot_id ||
        !redfin_spmi_return_ready() || !wf_zero_arg("modem", true) ||
        !wf_zero_arg("wifi", true) || !wf_zero_arg("gpu", true) ||
        !wf_zero_arg("sweetusb", true) || !wf_zero_arg("redfingui", false) ||
        !wf_zero_arg("redfinsmp", false) ||
        SecureDTLookupEntry(NULL, "/redfin-wifi-native", &entry) != kSuccess ||
        !wf_property(entry, "reg", ranges, sizeof(expected)) || memcmp(ranges, expected, sizeof(expected)) ||
        !wf_property(entry, "live-fdt-verified", &proof, sizeof(proof)) || proof != 1 ||
        !wf_property(entry, "source-contract", source, sizeof(source)) || memcmp(source, witness, sizeof(source)) ||
        SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        !wf_property(chosen, "dram-base", &ram_base, sizeof(ram_base)) ||
        !wf_property(chosen, "dram-size", &ram_bytes, sizeof(ram_bytes)) ||
        !ram_base || !ram_bytes || ((ram_base | ram_bytes) & 0x3fffULL) ||
        ram_base > (1ULL << 36) || ram_bytes > (1ULL << 36) - ram_base)
        return false;
    for (unsigned i = 0; i < 6; i += 2)
        if (ranges[i] < ram_base + ram_bytes && ram_base < ranges[i] + ranges[i + 1]) return false;
    return true;
}

static int wf_check(void *opaque)
{
    const wf_context *context = (const wf_context *)opaque;
    return context && context->active && context->base && redfin_spmi_return_ready() ? 0 : ENXIO;
}

static int wf_read32(void *opaque, uint32_t offset, uint32_t *out)
{
    wf_context *context = (wf_context *)opaque;
    if (!out || offset % 4u || offset > RF_WIFI_AOP_BYTES - 4u || wf_check(context)) return EINVAL;
    *out = *(const volatile uint32_t *)(context->base + offset);
#if defined(__aarch64__) || defined(__arm64__)
    __asm__ volatile("dmb oshld" ::: "memory");
#else
    __asm__ volatile("" ::: "memory"); /* Host fake-MMIO harness only. */
#endif
    return 0;
}

static int wf_selector(const rf_cmddb_resource *resource, uint32_t wanted)
{
    int selected = -1;
    bool padding = false;
    if (!resource->level_count || resource->level_count > RF_CMDDB_MAX_LEVELS || resource->levels[0]) return -1;
    for (unsigned i = 1; i < resource->level_count; ++i) {
        uint32_t value = resource->levels[i];
        if (!value) { padding = true; continue; }
        if (padding || value <= resource->levels[i - 1]) return -1;
        if (selected < 0 && value >= wanted) selected = (int)i;
    }
    return selected;
}

extern "C" void redfin_wifi_native_observe(void)
{
    int enabled = 0;
    if (!PE_parse_boot_argn("redfinwifinative", &enabled, sizeof(enabled)) || enabled != 1) return;
    static uint32_t attempted;
    if (__atomic_exchange_n(&attempted, 1, __ATOMIC_RELAXED)) return;
    uint64_t ranges[6] = {};
    if (!wf_platform(ranges)) {
        IOLog("REDFIN WIFI NATIVE: refused md0/UP/identity/return/live-FDT contract\n");
        return;
    }
    wf_map maps[3] = {};
    bool mapped = true;
    for (unsigned i = 0; i < 3; ++i) {
        maps[i].memory = IOMemoryDescriptor::withPhysicalAddress(ranges[2 * i], ranges[2 * i + 1], kIODirectionIn);
        IOOptionBits options = kIOMapReadOnly | (i == 0 ? kIOMapInhibitCache : kIOMapWriteCombineCache);
        maps[i].mapping = maps[i].memory ? maps[i].memory->map(options) : NULL;
        if (!maps[i].mapping || !maps[i].mapping->getVirtualAddress() ||
            maps[i].mapping->getLength() != ranges[2 * i + 1]) { mapped = false; break; }
    }
    if (!mapped || !redfin_spmi_return_ready()) {
        IOLog("REDFIN WIFI NATIVE: read-only mapping/return check failed\n");
    } else {
        wf_context context = {(uintptr_t)maps[0].mapping->getVirtualAddress(), true};
        const rf_wifi_aop_ops operations = {&context, wf_check, wf_read32, NULL, NULL, NULL};
        uint32_t raw[16] = {};
        int captured = 0;
        for (unsigned i = 0; i < 16; ++i) {
            captured = wf_read32(&context, i * 4u, &raw[i]);
            if (captured) break;
        }
        IOLog("REDFIN WIFI NATIVE: AOP raw status=%d magic=%#x version=%u features=%#x reserved=%#x\n",
            captured, raw[0], raw[1], raw[2], raw[15]);
        IOLog("REDFIN WIFI NATIVE: AOP ucore link=%#x ack=%#x channel=%#x ack=%#x box=%#x bytes=%u\n",
            raw[3], raw[4], raw[5], raw[6], raw[8], raw[7]);
        IOLog("REDFIN WIFI NATIVE: AOP mcore link=%#x ack=%#x channel=%#x ack=%#x box=%#x bytes=%u\n",
            raw[9], raw[10], raw[11], raw[12], raw[14], raw[13]);
        rf_wifi_aop_snapshot snapshot = {};
        int observed = captured ? RF_WIFI_AOP_PLATFORM : rf_wifi_aop_observe(&operations, &snapshot);
        IOLog("REDFIN WIFI NATIVE: AOP observation status=%d pending_tx=%u pending_rx=%u (no channel open/message/kick)\n",
            observed, snapshot.tx_length, snapshot.rx_length);
        if (observed != RF_WIFI_AOP_PLATFORM && redfin_spmi_return_ready()) {
            redfin_smem_report smem = {};
            enum redfin_smem_status smem_status = redfin_smem_inspect(
                (const volatile uint8_t *)maps[1].mapping->getVirtualAddress(), REDFIN_SMEM_BYTES, &smem);
            IOLog("REDFIN WIFI NATIVE: SMEM status=%u partitions=%u modem=%u offset=%#x bytes=%#x items=%u cached_uninspected=%u GLINK=%u tx=%u rx=%u\n",
                (unsigned)smem_status, smem.partitions, smem.modem_partition, smem.partition_offset,
                smem.partition_bytes, smem.uncached_items, smem.cached_uninspected, smem.descriptor,
                smem.tx_pending, smem.rx_pending);
            if (redfin_spmi_return_ready()) {
                static const uint8_t names[3][8] = {"xo.lvl", "cx.lvl", "mss.lvl"};
                for (unsigned i = 0; i < 3; ++i) {
                    if (!redfin_spmi_return_ready()) break;
                    rf_cmddb_resource resource = {};
                    enum rf_cmddb_status status = rf_cmddb_lookup(
                        (const volatile uint8_t *)maps[2].mapping->getVirtualAddress(), RF_CMDDB_BYTES,
                        names[i], RF_CMDDB_ARC, &resource);
                    IOLog("REDFIN WIFI NATIVE: resource %.8s status=%u type=%u address=%#x aux_version=%#x aux_bytes=%u levels=%u TURBO_selector=%d\n",
                        (const char *)names[i], (unsigned)status, resource.type, resource.address,
                        resource.aux_version, resource.aux_bytes, resource.level_count,
                        status == RF_CMDDB_OK && i ? wf_selector(&resource, 384) : -1);
                    char values[128] = {};
                    unsigned used = 0;
                    for (unsigned level = 0; level < resource.level_count && level < RF_CMDDB_MAX_LEVELS; ++level) {
                        int written = snprintf(values + used, sizeof(values) - used, "%s%u",
                            level ? "," : "", resource.levels[level]);
                        if (written < 0 || (unsigned)written >= sizeof(values) - used) break;
                        used += (unsigned)written;
                    }
                    IOLog("REDFIN WIFI NATIVE: %.8s raw_AUX=[%s] (consumer levels; no physical power proof or vote)\n",
                        (const char *)names[i], values);
                }
            }
        }
        context.active = false;
        IOLog("REDFIN WIFI NATIVE: read-only observation finished; no PAS/power/SMEM writes or notifications\n");
    }
    for (unsigned i = 0; i < 3; ++i) {
        OSSafeReleaseNULL(maps[i].mapping);
        OSSafeReleaseNULL(maps[i].memory);
    }
}
#endif
