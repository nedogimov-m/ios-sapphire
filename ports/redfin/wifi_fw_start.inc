/* SPDX-License-Identifier: MIT
 * Native Redfin PIL coordinator, included once by RedfinWiFiFWSource.cpp.
 * Google msm 500b3a2059c1eec0fec08ec56add06320ea901a8 peripheral-loader.c
 * passes region_start as the temporary metadata address to init_image().
 * All hardware state is retained until platform reset on an uncertain result.
 */
#include <kern/clock.h>
#include "../../../bsd/dev/redfin_scm_query.h"
#include "../../../bsd/dev/redfin_wifi_smp2p.h"
#include "redfin_wifi_pas.h"
#include "redfin_wifi_glink.h"
#include "redfin_wifi_assets.h"
#include "redfin_wifi_host.h"
#include "redfin_wifi_qmi.h"
#include "redfin_wifi_rmtfs.h"
#include "redfin_wifi_hyp.h"
#include "redfin_wifi_wlfw.h"

extern "C" int redfin_wifi_power_start(void);
extern "C" int redfin_wifi_power_held(void);
extern "C" int redfin_wifi_power_audit(void);
extern "C" int redfin_wifi_wlan_resources_observe(void);
extern "C" int redfin_wifi_wlan_power_start(unsigned, uint32_t, void *, int (*)(void *));
/* Built-in XNU worker exit; declaration is private to Mach compilation in
 * this pinned kernel's kern/thread.h. This is not an external kext KPI. */
extern "C" void thread_terminate_self(void);

enum { FW_START_SOURCE = 1, FW_START_POWER, FW_START_ABI, FW_START_RESET,
    FW_START_SMP2P, FW_START_METADATA, FW_START_INIT, FW_START_SETUP,
    FW_START_COPY, FW_START_AUTH, FW_START_READY, FW_START_GLINK, FW_START_RMTFS };
enum { FW_START_SMEM, FW_START_TCSR, FW_START_IPCC, FW_START_MPSS, FW_START_METADATA_MAP,
    FW_START_ASSETS_MAP, FW_START_RMTFS_SNAPSHOT_MAP, FW_START_RMTFS_SCRATCH_MAP,
    FW_START_RMTFS_POOL_MAP, FW_START_MAPS };
static const uint64_t fw_start_ranges[8] = {
    UINT64_C(0x80900000), 0x200000, 0x1f40000, 0x20000,
    0x408000, 0x1000, 0x8c000000, 0x11800000};
struct fw_start_map { IOMemoryDescriptor *memory; IOMemoryMap *map; uintptr_t base; };
struct fw_start_context {
    fw_start_map mapping[FW_START_MAPS];
    rf_wifi_smp2p_session smp2p;
    rf_wifi_smp2p_ops smp_ops;
    rf_sq_ops scm_ops;
    unsigned phase, convention, stores, copies;
    bool active, power, reset, initialized, setup, auth_attempted, authenticated, locked, poisoned;
    uint64_t function, metadata[2];
    uint8_t readback[REDFIN_MPSS_COPY_CHUNK];
    rf_glink glink;
    rf_glink_ops glink_ops;
    uint8_t transport[8256], qrtr[8256];
    uint32_t qrtr_peer, qrtr_seen, qrtr_hello, qrtr_hello_sent, qrtr_services, wlfw_node, wlfw_port;
    uint8_t pending[32][RF_HOST_BLOCK + 64];
    uint32_t pending_bytes[32];
    unsigned pending_head, pending_tail, pending_count, transport_mode;
    unsigned host_mode, host_announced, cap_sent, cap_received;
    uint64_t assets_reg[2], assets_bytes;
    uint8_t assets_sha256[32];
    rf_wlan_assets assets;
    rf_host host;
    rf_host_ops host_ops;
    rf_wlfw_cap cap;
    bool rmtfs_mode, rmtfs_attempted, rmtfs_shared;
    uint64_t rmtfs_snapshot[2], rmtfs_scratch[2], rmtfs_pool[2], rmtfs_shared_reg[2], rmtfs_bytes;
    uint8_t rmtfs_sha256[32];
    void *rmtfs_shadow;
    rf_rmtfs rmtfs;
    rf_rm_ops rmtfs_ops;
    bool wlfw_mode, wlan_observe_mode, wlan_power_mode, wlan_observed;
    rf_wlfw_setup wlfw_setup;
    rf_wlfw_ops wlfw_ops;
    unsigned dynamic_sent, dynamic_received;
    rf_wlfw_dynamic dynamic;
};
static fw_start_context fw_start;

static bool fw_start_glink_contract(void)
{
    const uint32_t expected[10] = {1, 4, 1, 478, 479, 480, 16384, 0x20000, 3, 1};
    uint32_t witness[10] = {}; char name[7] = {}; DTEntry node;
    bool valid = SecureDTLookupEntry(NULL, "/redfin-wifi-glink", &node) == kSuccess &&
        fw_property(node, "source-contract", witness, sizeof(witness)) && !memcmp(witness, expected, sizeof(witness)) &&
        fw_property(node, "channel", name, sizeof(name)) && !memcmp(name, "IPCRTR", sizeof(name));
    if (valid && fw_start.host_mode) {
        const uint32_t required[16] = {3, 64, 257, 0x4001, 4096, 1, 0x4002, 4, 65536, 8, 4096, 0, 1, 14, 1, 0x4003};
        uint32_t actual[16] = {};
        valid = fw_property(node, "host-services", actual, sizeof(actual)) && !memcmp(actual, required, sizeof(actual));
    }
    return valid;
}

static bool fw_start_assets_contract(fw_start_context *context, bool capture)
{
    DTEntry node, memory;
    const uint32_t required[4] = {1, 16, 128, 16384};
    uint32_t witness[4] = {}; uint64_t reg[2] = {}, mapped[2] = {}, bytes = 0; uint8_t digest[32] = {};
    if (SecureDTLookupEntry(NULL, "/redfin-wifi-assets", &node) != kSuccess ||
        !fw_property(node, "source-contract", witness, sizeof(witness)) || memcmp(witness, required, sizeof(witness)) ||
        !fw_property(node, "reg", reg, sizeof(reg)) || !fw_property(node, "bundle-bytes", &bytes, sizeof(bytes)) ||
        !fw_property(node, "bundle-sha256", digest, sizeof(digest)) ||
        SecureDTLookupEntry(NULL, "/chosen/memory-map", &memory) != kSuccess ||
        !fw_property(memory, "RedfinWiFiAssets", mapped, sizeof(mapped)) || memcmp(reg, mapped, sizeof(reg)) ||
        bytes < 64 || bytes > 16u * 1024u * 1024u || reg[1] != ((bytes + 16383u) & ~UINT64_C(16383)) ||
        reg[0] < UINT64_C(0x180000000) || reg[0] > UINT64_C(0x200000000) - reg[1] || (reg[0] & 16383u) ||
        reg[0] + reg[1] != context->metadata[0]) return false;
    if (capture) {
        memcpy(context->assets_reg, reg, sizeof(reg)); memcpy(context->assets_sha256, digest, sizeof(digest));
        context->assets_bytes = bytes;
    }
    return !memcmp(reg, context->assets_reg, sizeof(reg)) && !memcmp(digest, context->assets_sha256, sizeof(digest)) &&
        bytes == context->assets_bytes;
}

static bool fw_start_metadata_contract(fw_start_context *context, bool capture)
{
    DTEntry source, memory;
    uint64_t reg[2] = {}, mapped[2] = {};
    if (SecureDTLookupEntry(NULL, "/redfin-wifi-fw", &source) != kSuccess ||
        !fw_property(source, "metadata-reg", reg, sizeof(reg)) ||
        SecureDTLookupEntry(NULL, "/chosen/memory-map", &memory) != kSuccess ||
        !fw_property(memory, "RedfinWiFiMetadata", mapped, sizeof(mapped)) || memcmp(reg, mapped, sizeof(reg)) ||
        reg[0] < UINT64_C(0x180000000) || reg[0] > UINT64_C(0x200000000) - RF_WIFI_FW_PAGE ||
        (reg[0] & (RF_WIFI_FW_PAGE - 1u)) || reg[1] != RF_WIFI_FW_PAGE) return false;
    if (capture) memcpy(context->metadata, reg, sizeof(reg));
    return !memcmp(context->metadata, reg, sizeof(reg));
}

static bool fw_start_rmtfs_contract(fw_start_context *context, bool capture)
{
    DTEntry node, memory;
    const uint32_t expected[10] = {1, 14, 1, 0x4003, 512, 4, 0x280000, 3, 15, 6};
    uint32_t actual[10] = {}, owned = 0;
    uint64_t snapshot[2] = {}, scratch[2] = {}, pool[2] = {}, shared[2] = {}, mapped[2] = {}, bytes = 0;
    uint8_t digest[32] = {};
    if (!context->host_mode || SecureDTLookupEntry(NULL, "/redfin-rmtfs", &node) != kSuccess ||
        !fw_property(node, "source-contract", actual, sizeof(actual)) || memcmp(actual, expected, sizeof(actual)) ||
        !fw_property(node, "shim-owned", &owned, sizeof(owned)) || owned != 1 ||
        !fw_property(node, "snapshot-reg", snapshot, sizeof(snapshot)) ||
        !fw_property(node, "scratch-reg", scratch, sizeof(scratch)) ||
        !fw_property(node, "pool-reg", pool, sizeof(pool)) || !fw_property(node, "shared-reg", shared, sizeof(shared)) ||
        !fw_property(node, "bundle-bytes", &bytes, sizeof(bytes)) ||
        !fw_property(node, "bundle-sha256", digest, sizeof(digest)) ||
        bytes < 576 || bytes > 12u * 1024u * 1024u ||
        snapshot[1] != ((bytes + 16383u) & ~UINT64_C(16383)) || snapshot[0] < UINT64_C(0x180000000) ||
        snapshot[0] > UINT64_C(0x200000000) - snapshot[1] - 16384u || (snapshot[0] & 16383u) ||
        scratch[0] != snapshot[0] + snapshot[1] || scratch[1] != 16384u ||
        scratch[0] + scratch[1] != context->assets_reg[0] ||
        pool[0] < UINT64_C(0x80000000) || pool[0] > UINT64_C(0x100000000) - 0x288000u ||
        pool[1] != 0x288000u || (pool[0] & 16383u) || shared[0] != pool[0] + 16384u || shared[1] != RF_RM_SHARED ||
        SecureDTLookupEntry(NULL, "/chosen/memory-map", &memory) != kSuccess ||
        !fw_property(memory, "RedfinRMTFSSnapshot", mapped, sizeof(mapped)) || memcmp(mapped, snapshot, sizeof(mapped)) ||
        !fw_property(memory, "RedfinRMTFSScratch", mapped, sizeof(mapped)) || memcmp(mapped, scratch, sizeof(mapped)) ||
        !fw_property(memory, "RedfinRMTFSPool", mapped, sizeof(mapped)) || memcmp(mapped, pool, sizeof(mapped))) return false;
    if (capture) {
        memcpy(context->rmtfs_snapshot, snapshot, sizeof(snapshot)); memcpy(context->rmtfs_scratch, scratch, sizeof(scratch));
        memcpy(context->rmtfs_pool, pool, sizeof(pool)); memcpy(context->rmtfs_shared_reg, shared, sizeof(shared));
        memcpy(context->rmtfs_sha256, digest, sizeof(digest)); context->rmtfs_bytes = bytes;
    }
    return !memcmp(context->rmtfs_snapshot, snapshot, sizeof(snapshot)) &&
        !memcmp(context->rmtfs_scratch, scratch, sizeof(scratch)) && !memcmp(context->rmtfs_pool, pool, sizeof(pool)) &&
        !memcmp(context->rmtfs_shared_reg, shared, sizeof(shared)) && !memcmp(context->rmtfs_sha256, digest, sizeof(digest)) &&
        context->rmtfs_bytes == bytes;
}

static const uint64_t *fw_start_region(const fw_start_context *context, unsigned index)
{
    return index == FW_START_ASSETS_MAP ? context->assets_reg : index == FW_START_METADATA_MAP ? context->metadata :
        index == FW_START_RMTFS_SNAPSHOT_MAP ? context->rmtfs_snapshot :
        index == FW_START_RMTFS_SCRATCH_MAP ? context->rmtfs_scratch :
        index == FW_START_RMTFS_POOL_MAP ? context->rmtfs_pool : &fw_start_ranges[2u * index];
}

static bool fw_start_wlfw_contract(void)
{
    DTEntry node;
    const uint32_t expected[10] = {1, 0x45, 1, 0, 0x4b4e454c, 0, 2, 4096, 0x2d, 0x2e};
    const uint64_t expected_reg[2] = {RF_WLFW_MSA_BASE, RF_WLFW_MSA_BYTES};
    uint32_t actual[10] = {}, verified = 0; uint64_t reg[2] = {};
    return fw_start.host_mode && fw_start.rmtfs_mode && fw_start.wlfw_mode &&
        SecureDTLookupEntry(NULL, "/redfin-wifi-wlfw", &node) == kSuccess &&
        fw_property(node, "source-contract", actual, sizeof(actual)) && !memcmp(actual, expected, sizeof(actual)) &&
        fw_property(node, "reg", reg, sizeof(reg)) && !memcmp(reg, expected_reg, sizeof(reg)) &&
        fw_property(node, "shim-verified", &verified, sizeof(verified)) && verified == 1;
}

static bool fw_start_wlan_contract(void)
{
    DTEntry node;
    const uint32_t expected[10] = {fw_start.wlan_power_mode ? 2u : 1u, 5, 4, 4, 0, 352, 1800, 1304, 3000, 3000};
    const uint8_t expected_names[5][8] = {"ldoa1", "ldoa14", "ldoc2", "ldoc11", "ldoc10"};
    uint32_t actual[10] = {}, observe = 0; uint8_t names[40] = {};
    bool valid = fw_start.wlfw_mode && fw_start.wlan_observe_mode &&
        SecureDTLookupEntry(NULL, "/redfin-wifi-wlan", &node) == kSuccess &&
        fw_property(node, "source-contract", actual, sizeof(actual)) && !memcmp(actual, expected, sizeof(actual)) &&
        fw_property(node, "resource-names", names, sizeof(names)) && !memcmp(names, expected_names, sizeof(names)) &&
        fw_property(node, "observe-only", &observe, sizeof(observe)) && observe == (fw_start.wlan_power_mode ? 0u : 1u);
    if (valid && fw_start.wlan_power_mode) {
        const uint32_t expected_addresses[5] = {0x40800, 0x42100, 0x41d00, 0x41a00, 0x41900};
        uint32_t actual_addresses[5] = {};
        valid = fw_property(node, "resource-addresses", actual_addresses, sizeof(actual_addresses)) &&
            !memcmp(actual_addresses, expected_addresses, sizeof(actual_addresses));
    }
    return valid;
}

static int fw_start_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    bool valid = context == &fw_start && context->active && !context->poisoned && ml_get_interrupts_enabled() &&
        !fw_probe_check(&fw_probe, fw_probe.nonce) && fw_start_metadata_contract(context, false) &&
        (!context->power || !redfin_wifi_power_held()) &&
        (!context->transport_mode || fw_start_glink_contract()) &&
        (!context->host_mode || fw_start_assets_contract(context, false)) &&
        (!context->rmtfs_mode || (!context->rmtfs.poisoned && fw_start_rmtfs_contract(context, false))) &&
        (!context->wlfw_mode || (!context->wlfw_setup.poisoned && fw_start_wlfw_contract())) &&
        (!context->wlan_observe_mode || fw_start_wlan_contract());
    if (valid) for (unsigned i = 0; i < FW_START_MAPS; ++i) {
        const fw_start_map *entry = &context->mapping[i];
        if (!entry->map && !entry->memory && !entry->base) continue;
        if (!entry->map || !entry->memory || !entry->base ||
            entry->map->getVirtualAddress() != entry->base ||
            entry->map->getLength() != fw_start_region(context, i)[1]) { valid = false; break; }
    }
    if (valid && context->locked)
        valid = context->mapping[FW_START_TCSR].base &&
            *(const volatile uint32_t *)(context->mapping[FW_START_TCSR].base + RF_WIFI_SMP2P_LOCK_OFFSET) == 1;
    if (!valid && context == &fw_start) context->poisoned = true;
    return valid ? 0 : ECANCELED;
}
static bool fw_start_valid(void *opaque) { return !fw_start_check(opaque); }
static int fw_start_source_policy(void *opaque, uint64_t nonce)
{ return nonce == fw_probe.nonce ? fw_start_check(opaque) : ECANCELED; }

static int fw_start_map_range(fw_start_context *context, unsigned index)
{
    if (index >= FW_START_MAPS || fw_start_check(context) ||
        (index == FW_START_MPSS && (!context->reset || !context->setup))) return EPERM;
    fw_start_map *entry = &context->mapping[index];
    if (entry->memory || entry->map || entry->base) return EBUSY;
    const uint64_t *region = fw_start_region(context, index);
    uint64_t physical = region[0], bytes = region[1];
    if (!bytes || (index >= FW_START_RMTFS_SNAPSHOT_MAP && !context->rmtfs_mode)) return EPERM;
    bool readonly = index == FW_START_ASSETS_MAP || index == FW_START_RMTFS_SNAPSHOT_MAP;
    entry->memory = IOMemoryDescriptor::withPhysicalAddress(physical, bytes, readonly ? kIODirectionIn : kIODirectionInOut);
    IOOptionBits options = readonly ? kIOMapReadOnly | kIOMapDefaultCache :
        index == FW_START_SMEM || index == FW_START_MPSS || index == FW_START_METADATA_MAP ||
        index == FW_START_RMTFS_SCRATCH_MAP || index == FW_START_RMTFS_POOL_MAP ?
            kIOMapWriteCombineCache : kIOMapInhibitCache;
    entry->map = entry->memory ? entry->memory->map(options) : NULL;
    if (!entry->map || !entry->map->getVirtualAddress() ||
        entry->map->getLength() != bytes) return ENOMEM;
    entry->base = (uintptr_t)entry->map->getVirtualAddress();
    return fw_start_check(context);
}

static uint64_t fw_start_ns(void *opaque)
{
    (void)opaque;
    uint64_t ns = 0;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    return ns;
}
static void fw_start_scm_delay(void *opaque, unsigned microseconds)
{ if (!fw_start_check(opaque) && microseconds <= 30000) IODelay(microseconds); }
static int fw_start_invoke(void *opaque, rf_sq_regs *registers)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (!registers || fw_start_check(context) || !context->power || !context->function ||
        (registers->x[0] != context->function && registers->x[0] != 1)) return EPERM;
    IOLog("REDFIN WIFI START: SMC enter fn=%#llx phase=%u\n", registers->x[0], context->phase);
    register uint64_t x0 __asm__("x0") = registers->x[0], x1 __asm__("x1") = registers->x[1],
        x2 __asm__("x2") = registers->x[2], x3 __asm__("x3") = registers->x[3],
        x4 __asm__("x4") = registers->x[4], x5 __asm__("x5") = registers->x[5],
        x6 __asm__("x6") = registers->x[6], x7 __asm__("x7") = 0;
    __asm__ volatile("dsb sy\n\tsmc #0\n\tdsb sy"
        : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
        : : "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "cc", "memory");
    registers->x[0] = x0; registers->x[1] = x1; registers->x[2] = x2; registers->x[3] = x3;
    registers->x[4] = x4; registers->x[5] = x5; registers->x[6] = x6; registers->x[7] = x7;
    IOLog("REDFIN WIFI START: SMC returned status=%lld value=%#llx\n", (int64_t)x0, x1);
    return fw_start_check(context);
}
static int fw_start_pas(fw_start_context *context, unsigned command)
{
    if (fw_start_check(context) || !context->power || redfin_wifi_power_audit() ||
        (command == 6 && context->phase != FW_START_RESET) ||
        (command == 1 && (context->phase != FW_START_INIT || context->initialized ||
            fw_probe.boot.source.stage != RF_WIFI_FW_METADATA)) ||
        (command == 2 && (context->phase != FW_START_SETUP || !context->initialized)) ||
        (command == 5 && (context->phase != FW_START_AUTH || !context->setup || !context->reset ||
            fw_probe.boot.source.stage != RF_WIFI_FW_SEGMENTS || context->smp2p.stage != RF_WIFI_SMP2P_ARMED))) return EPERM;
    uint64_t address = command == 1 ? context->metadata[0] : command == 2 ? REDFIN_MPSS_BASE : 0;
    uint64_t bytes = command == 2 ? REDFIN_MPSS_BYTES : 0;
    context->function = UINT64_C(0x02000200) | command |
        (context->convention == 64 ? UINT64_C(0x40000000) : 0);
    rf_sq_report report = {};
    int error = rf_wifi_pas_run(&context->scm_ops, context->convention, command, address, bytes, &report);
    context->function = 0;
    IOLog("REDFIN WIFI START: PAS4 command=%u result=%d status=%lld value=%#llx calls=%u resumes=%u busy=%u\n",
        command, error, report.status, report.value[0], report.calls, report.resumes, report.busy_retries);
    return error;
}

static int fw_start_reset(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    return !fw_start_check(context) && context->reset && !context->auth_attempted ? 0 : EPERM;
}
static int fw_start_started(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    return !fw_start_check(context) && context->authenticated ? 0 : EPERM;
}
static int fw_start_lock(void *opaque, uint32_t timeout_ms)
{
    fw_start_context *context = (fw_start_context *)opaque;
    bool live = context->phase == FW_START_GLINK && context->authenticated &&
        context->smp2p.stage == RF_WIFI_SMP2P_READY;
    if (!timeout_ms || timeout_ms > 1000 || context->locked || fw_start_check(context) ||
        (!live && fw_start_reset(context))) return EPERM;
    volatile uint32_t *lock = (volatile uint32_t *)(context->mapping[FW_START_TCSR].base + RF_WIFI_SMP2P_LOCK_OFFSET);
    uint64_t first = fw_start_ns(context);
    do {
        if (fw_start_check(context) || (!live && fw_start_reset(context))) return EPERM;
        uint32_t value = *lock;
        __asm__ volatile("dmb oshld" ::: "memory");
        if (!value) {
            *lock = 1;
            __asm__ volatile("dsb osh" ::: "memory");
            if (*lock == 1) { context->locked = true; return fw_start_check(context); }
        }
        IODelay(50);
    } while (fw_start_ns(context) - first <= (uint64_t)timeout_ms * 1000000u);
    return ETIMEDOUT;
}
static int fw_start_unlock(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (context != &fw_start || !context->locked || current_thread() != fw_probe.owner ||
        !context->mapping[FW_START_TCSR].base) return EPERM;
    volatile uint32_t *lock = (volatile uint32_t *)(context->mapping[FW_START_TCSR].base + RF_WIFI_SMP2P_LOCK_OFFSET);
    if (*lock != 1) return EPERM;
    __asm__ volatile("dsb oshst" ::: "memory");
    *lock = 0;
    __asm__ volatile("dsb osh" ::: "memory");
    context->locked = false;
    return 0; /* A peer may acquire immediately; zero readback is not required. */
}
static int fw_start_smem_write(void *opaque, uint32_t offset, uint32_t value)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (offset % 4u || offset > REDFIN_SMEM_BYTES - 4u || fw_start_check(context)) return EPERM;
    ++context->stores;
    *(volatile uint32_t *)(context->mapping[FW_START_SMEM].base + offset) = value;
    __asm__ volatile("dmb oshst" ::: "memory");
    return fw_start_check(context);
}
static int fw_start_barrier(void *opaque)
{
    if (fw_start_check(opaque)) return EPERM;
    __asm__ volatile("dsb osh" ::: "memory");
    return fw_start_check(opaque);
}
static int fw_start_kick(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_check(context)) return EPERM;
    __asm__ volatile("dsb oshst" ::: "memory");
    *(volatile uint32_t *)(context->mapping[FW_START_IPCC].base + 0xcu) = RF_WIFI_SMP2P_IPCC_ID;
    __asm__ volatile("dsb osh" ::: "memory");
    return fw_start_check(context);
}
static int fw_start_ms(void *opaque, uint64_t *value)
{
    if (!value || fw_start_check(opaque)) return EPERM;
    *value = fw_start_ns(opaque) / 1000000u;
    return 0;
}
static int fw_start_pause(void *opaque, uint32_t microseconds)
{
    if (!microseconds || microseconds > 1000 || fw_start_check(opaque)) return EPERM;
    IODelay(microseconds);
    return fw_start_check(opaque);
}

static int fw_start_copy_check(void *opaque, const struct redfin_mpss_plan *plan, unsigned phase)
{
    fw_start_context *context = (fw_start_context *)opaque;
    return !fw_start_check(context) && plan == &fw_probe.workspace.plan &&
        plan->physical_base == REDFIN_MPSS_BASE && plan->memory_bytes == REDFIN_MPSS_BYTES &&
        ((phase == RF_WIFI_FW_METADATA && context->phase == FW_START_METADATA && !context->initialized &&
            context->mapping[FW_START_METADATA_MAP].base) ||
         (phase == RF_WIFI_FW_SEGMENTS && context->phase == FW_START_COPY && context->initialized && context->setup &&
            context->mapping[FW_START_MPSS].base && !fw_start_reset(context))) ? 0 : EPERM;
}
static uint8_t *fw_start_destination(fw_start_context *context, uint64_t physical, uint32_t bytes)
{
    bool metadata = context->phase == FW_START_METADATA;
    uint64_t base = metadata ? context->metadata[0] : REDFIN_MPSS_BASE;
    uint64_t length = metadata ? context->metadata[1] : REDFIN_MPSS_BYTES;
    if (!bytes || bytes > REDFIN_MPSS_COPY_CHUNK || bytes > length || physical < base ||
        physical - base > length - bytes ||
        fw_start_copy_check(context, &fw_probe.workspace.plan,
            context->phase == FW_START_METADATA ? RF_WIFI_FW_METADATA : RF_WIFI_FW_SEGMENTS)) return NULL;
    return (uint8_t *)(context->mapping[metadata ? FW_START_METADATA_MAP : FW_START_MPSS].base + physical - base);
}
static int fw_start_copy(void *opaque, uint64_t physical, const uint8_t *data, uint32_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    uint8_t *destination = fw_start_destination(context, physical, bytes);
    if (!data || !destination) return EPERM;
    memcpy(destination, data, bytes);
    __asm__ volatile("dsb osh" ::: "memory");
    if (!(++context->copies % 256u)) {
        if (redfin_wifi_power_audit()) return EPERM;
        IOLog("REDFIN WIFI START: copying chunks=%u\n", context->copies);
    }
    return fw_start_check(context);
}
static int fw_start_zero(void *opaque, uint64_t physical, uint32_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    uint8_t *destination = fw_start_destination(context, physical, bytes);
    if (!destination || context->phase != FW_START_COPY) return EPERM;
    memset(destination, 0, bytes);
    __asm__ volatile("dsb osh" ::: "memory");
    if (!(++context->copies % 256u)) {
        if (redfin_wifi_power_audit()) return EPERM;
        IOLog("REDFIN WIFI START: copying chunks=%u\n", context->copies);
    }
    return fw_start_check(context);
}
static int fw_start_readback(void *opaque, uint64_t physical, uint8_t *data, uint32_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    uint8_t *destination = fw_start_destination(context, physical, bytes);
    if (!data || !destination) return EPERM;
    __asm__ volatile("dsb osh" ::: "memory");
    memcpy(data, destination, bytes);
    return fw_start_check(context);
}
static int fw_start_sync(void *opaque, uint64_t physical, uint64_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    bool metadata = context->phase == FW_START_METADATA;
    if (!bytes || (metadata ? (physical != context->metadata[0] || bytes > context->metadata[1] ||
        fw_start_check(context)) : (physical != REDFIN_MPSS_BASE || bytes > REDFIN_MPSS_BYTES ||
        fw_start_reset(context)))) return EPERM;
    /* The sole destination mapping is Normal-NC, with no cacheable alias in
     * XNU's high-only RAM physmap. Complete actual writes before TrustZone. */
    __asm__ volatile("dsb sy" ::: "memory");
    return fw_start_check(context);
}

static int fw_start_glink_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_check(context) || !context->authenticated || context->phase != FW_START_GLINK ||
        context->smp2p.stage != RF_WIFI_SMP2P_READY || context->smp2p.poisoned ||
        !context->smp2p.peer || context->smp2p.slave_index >= 16) return EPERM;
    uint32_t at = context->smp2p.peer + 36u + 20u * context->smp2p.slave_index;
    if (at > REDFIN_SMEM_BYTES - 4u) return EPERM;
    uint32_t state = redfin_smem_u32((const volatile uint8_t *)context->mapping[FW_START_SMEM].base + at);
    return (state & 3u) == 2u ? 0 : EPERM;
}
static int fw_start_glink_lock(void *opaque) { return fw_start_lock(opaque, 1000); }
static int fw_start_glink_kick(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_glink_check(context)) return EPERM;
    __asm__ volatile("dsb oshst" ::: "memory");
    *(volatile uint32_t *)(context->mapping[FW_START_IPCC].base + 0xcu) = 0x00020000u;
    __asm__ volatile("dsb osh" ::: "memory");
    return fw_start_glink_check(context);
}
static int fw_start_glink_payload(void *opaque, uint32_t offset, const uint8_t *data, uint32_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    uint32_t tx = context->glink.tx;
    if (!tx || !data || !bytes || offset < tx || bytes > 16384u || offset - tx > 16384u - bytes ||
        (offset | bytes) % 4u || fw_start_glink_check(context)) return EPERM;
    memcpy((void *)(context->mapping[FW_START_SMEM].base + offset), data, bytes);
    __asm__ volatile("dsb osh" ::: "memory");
    return fw_start_glink_check(context);
}
static int fw_start_qrtr_queue(fw_start_context *context, uint32_t type, uint32_t from,
    uint32_t node, uint32_t to, const uint8_t *data, uint32_t bytes)
{
    if (!data || !bytes || bytes > RF_HOST_BLOCK + 4u || context->pending_count >= 32 || fw_start_glink_check(context))
        return ENOBUFS;
    uint8_t *packet = context->pending[context->pending_head];
    uint32_t length = 32u + ((bytes + 3u) & ~3u);
    memset(packet, 0, length);
    const uint32_t fields[8] = {1, type, 1, from, 0, bytes, node, to};
    for (unsigned i = 0; i < 8; ++i) rf_gl_encode(packet + 4u * i, fields[i]);
    memcpy(packet + 32u, data, bytes);
    context->pending_bytes[context->pending_head] = length;
    context->pending_head = (context->pending_head + 1u) % 32u; ++context->pending_count;
    return 0;
}
static void fw_start_qrtr_control(fw_start_context *context, uint32_t type, uint32_t from,
    uint32_t node, uint32_t to, uint32_t a, uint32_t b, uint32_t c = 0, uint32_t d = 0)
{
    uint8_t control[20];
    const uint32_t fields[5] = {type, a, b, c, d};
    for (unsigned i = 0; i < 5; ++i) rf_gl_encode(control + 4u * i, fields[i]);
    if (fw_start_qrtr_queue(context, type, from, node, to, control, sizeof(control))) context->poisoned = true;
}
static int fw_start_host_lookup(void *opaque, const char *path, const uint8_t **data, uint32_t *bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_glink_check(context)) return EPERM;
    if (!rf_wlan_asset_find(&context->assets, path, data, bytes)) return 0;
    const redfin_mpss_image *image = &fw_probe.workspace.image;
    if (!strcmp(path, "image/modem.mdt")) { *data = image->asset[0].data; *bytes = image->asset[0].bytes; return 0; }
    if (!strncmp(path, "image/modem.b", 13) && strlen(path) == 15 &&
        path[13] >= '0' && path[13] <= '9' && path[14] >= '0' && path[14] <= '9') {
        unsigned index = (unsigned)(path[13] - '0') * 10u + (unsigned)(path[14] - '0');
        for (unsigned i = 1; i < image->assets; ++i) if (image->asset[i].index == index) {
            *data = image->asset[i].data; *bytes = image->asset[i].bytes; return 0;
        }
    }
    return ENOENT;
}
static int fw_start_host_send(void *opaque, uint32_t from, uint32_t node, uint32_t to,
    const uint8_t *data, uint32_t bytes)
{ return fw_start_qrtr_queue((fw_start_context *)opaque, 1, from, node, to, data, bytes); }
static int fw_start_rmtfs_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_glink_check(context) || !context->rmtfs_mode || !context->rmtfs_shared ||
        !context->rmtfs.ready || !context->rmtfs_shadow) return EPERM;
    const volatile uint64_t *pool = (const volatile uint64_t *)context->mapping[FW_START_RMTFS_POOL_MAP].base;
    if (!pool || pool[0] != UINT64_C(0xa7a7a7a7a7a7a7a7) || pool[2047] != UINT64_C(0xa7a7a7a7a7a7a7a7) ||
        pool[(16384u + RF_RM_SHARED) / 8u] != UINT64_C(0xa7a7a7a7a7a7a7a7) ||
        pool[0x288000u / 8u - 1u] != UINT64_C(0xa7a7a7a7a7a7a7a7)) return EIO;
    return 0;
}
static int fw_start_rmtfs_barrier(void *opaque)
{
    if (fw_start_rmtfs_check(opaque)) return EPERM;
    __asm__ volatile("dsb sy" ::: "memory");
    return fw_start_rmtfs_check(opaque);
}
static int fw_start_rmtfs_send(void *opaque, uint32_t node, uint32_t port, const uint8_t *data, uint32_t bytes)
{ return fw_start_host_send(opaque, 0x4003, node, port, data, bytes); }
static void fw_start_rmtfs_event(void *, unsigned message, unsigned caller, unsigned bytes, unsigned error)
{
    IOLog("REDFIN WIFI RMTFS: message=%u caller=%u bytes=%u error=%u; volatile shadow only\n",
        message, caller, bytes, error);
}
static int fw_start_wlfw_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    return !fw_start_glink_check(context) && context->wlfw_mode && context->rmtfs_shared &&
        context->wlfw_port && context->qrtr_seen && context->wlfw_node == context->qrtr_peer &&
        fw_start_wlfw_contract() ? 0 : EPERM;
}
static int fw_start_wlfw_send(void *opaque, const uint8_t *data, uint32_t bytes)
{
    fw_start_context *context = (fw_start_context *)opaque;
    if (fw_start_wlfw_check(context) || !data || bytes < 7 || bytes > 48) return EPERM;
    int error = fw_start_qrtr_queue(context, 1, 0x4004, context->wlfw_node, context->wlfw_port, data, bytes);
    if (!error && rf_qmi_u16(data + 3) == 0x24) context->cap_sent = 1;
    return error;
}
static int fw_start_wlan_power_policy(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    return !fw_start_wlfw_check(context) && context->wlan_power_mode && fw_start_wlan_contract() &&
        context->wlfw_setup.stage == RF_WLFW_COMPLETE && context->wlfw_setup.msa_accepted &&
        !context->cap.result && !context->cap.error && (context->cap.valid & 13u) == 13u &&
        context->cap.chip == 0x4320 && context->cap.family == 0x4001 && context->cap.soc == 0x400b0000 &&
        context->cap.firmware == 0x33197fff && (!(context->cap.valid & 16u) || context->cap.chain <= 2) ? 0 : EPERM;
}
static void fw_start_host_event(void *opaque, unsigned kind, const char *name, uint32_t bytes)
{
    (void)opaque;
    IOLog("REDFIN WIFI HOST: event=%u file/service=%s bytes=%u; RAM only\n", kind, name, bytes);
}
static void fw_start_qrtr_packet(void *opaque, const uint8_t *data, uint32_t length)
{
    fw_start_context *context = (fw_start_context *)opaque;
    uint32_t type, source, from, confirm, size, destination, to, at;
    if (length >= 32 && rf_gl_u32(data) == 1) {
        type = rf_gl_u32(data + 4); source = rf_gl_u32(data + 8); from = rf_gl_u32(data + 12);
        confirm = rf_gl_u32(data + 16); size = rf_gl_u32(data + 20);
        destination = rf_gl_u32(data + 24); to = rf_gl_u32(data + 28); at = 32;
    } else if (length >= 16 && data[0] == 3 && !(data[2] & ~1u)) {
        type = data[1]; confirm = data[2] & 1u; size = rf_gl_u32(data + 4);
        source = (uint32_t)data[8] | (uint32_t)data[9] << 8;
        from = (uint32_t)data[10] | (uint32_t)data[11] << 8;
        destination = (uint32_t)data[12] | (uint32_t)data[13] << 8;
        to = (uint32_t)data[14] | (uint32_t)data[15] << 8;
        if (from == 0xfffeu) from = 0xfffffffeu;
        if (to == 0xfffeu) to = 0xfffffffeu;
        at = 16u + data[3];
    } else { context->poisoned = true; return; }
    if (at > length || !size || size > length - at || confirm > 1 ||
        (destination != 1 && destination != UINT32_MAX)) { context->poisoned = true; return; }
    if (!context->qrtr_seen) { context->qrtr_peer = source; context->qrtr_seen = 1; }
    if (confirm) fw_start_qrtr_control(context, 7, to, source, from, destination, to);
    if (context->host_mode && to != 0xfffffffeu) {
        int error = 0;
        if (type == 1 && to == 0x4001) error = rf_host_pd(&context->host, &context->host_ops, source, from, data + at, size);
        else if (type == 1 && to == 0x4003) {
            if (context->rmtfs_mode && size >= 7)
                IOLog("REDFIN WIFI RMTFS: request node=%u port=%#x message=%u payload_bytes=%u\n",
                    source, from, (unsigned)rf_qmi_u16(data + at + 3), size);
            if (source != context->qrtr_peer) error = EPERM;
            else error = context->rmtfs_mode ? rf_rm_request(&context->rmtfs, &context->rmtfs_ops,
                source, from, data + at, size) : rf_host_rmtfs_refuse(&context->host, &context->host_ops,
                    source, from, data + at, size);
        }
        else if (type == 1 && to == 0x4002) error = rf_host_tftp_request(&context->host, &context->host_ops,
            source, from, data + at, size);
        else if (type == 1 && to >= 0x4100 && to < 0x5100) error = rf_host_tftp_packet(&context->host,
            &context->host_ops, source, from, to, data + at, size);
        else if (type == 1 && to == 0x4004 && source == context->wlfw_node && from == context->wlfw_port) {
            if (context->wlan_power_mode && context->dynamic_sent && size >= 7 && rf_qmi_u16(data + at + 3) == 0x3b) {
                error = rf_wlfw_dynamic_parse(&context->dynamic, data + at, size);
                if (error) { context->poisoned = true; return; }
                context->dynamic_received = 1;
                IOLog("REDFIN WIFI WLFW: dynamic mask result=%u error=%u valid=%#x previous=%#llx current=%#llx\n",
                    context->dynamic.result, context->dynamic.error, context->dynamic.valid,
                    (unsigned long long)context->dynamic.previous, (unsigned long long)context->dynamic.current);
            } else if (context->wlfw_mode && context->wlfw_setup.attempted) {
                unsigned previous = context->wlfw_setup.stage;
                error = rf_wlfw_receive(&context->wlfw_setup, &context->wlfw_ops, data + at, size);
                if (error < 0) {
                    IOLog("REDFIN WIFI WLFW: rejected message=%#x rejuvenate=%u; retained until platform reset\n",
                        size >= 7 ? (unsigned)rf_qmi_u16(data + at + 3) : 0, context->wlfw_setup.rejuvenate);
                    context->poisoned = true; return;
                }
                if (!error) IOLog("REDFIN WIFI WLFW: received=%#x stage=%u->%u transaction=%u result=%u error=%u status=%#llx regions=%u MSA=%u FWready=%u\n",
                    (unsigned)rf_qmi_u16(data + at + 3), previous, context->wlfw_setup.stage,
                    context->wlfw_setup.transaction, context->wlfw_setup.result, context->wlfw_setup.error,
                    (unsigned long long)context->wlfw_setup.fw_status, context->wlfw_setup.regions,
                    context->wlfw_setup.msa_accepted, context->wlfw_setup.fw_ready);
                if (!error && previous == RF_WLFW_MSA_INFO && context->wlfw_setup.stage == RF_WLFW_MSA_READY)
                    for (unsigned i = 0; i < context->wlfw_setup.regions; ++i)
                        IOLog("REDFIN WIFI WLFW: MSA region=%u base=%#llx bytes=%#x secure=%u; native fixed permissions retained\n",
                            i, (unsigned long long)context->wlfw_setup.region[i].base,
                            context->wlfw_setup.region[i].bytes, context->wlfw_setup.region[i].secure);
                if (error == 1) error = 0;
                if (!error && size >= 7 && rf_qmi_u16(data + at + 3) == 0x2c)
                    IOLog("REDFIN WIFI WLFW: pin results valid=%#x power=%#x phy=%#x RF=%#x\n",
                        context->wlfw_setup.pin_valid, context->wlfw_setup.pin_value[0],
                        context->wlfw_setup.pin_value[1], context->wlfw_setup.pin_value[2]);
                if (context->wlfw_setup.stage == RF_WLFW_COMPLETE) {
                    context->cap = context->wlfw_setup.cap; context->cap_received = 1;
                }
            } else if (!context->wlfw_mode && context->cap_sent &&
                !rf_wlfw_cap_parse(&context->cap, data + at, size, 1)) context->cap_received = 1;
            if (context->cap_received && size >= 7 && rf_qmi_u16(data + at + 3) == 0x24)
                IOLog("REDFIN WIFI WLFW: CAP result=%u error=%u valid=%#x chip=%#x family=%#x board=%#x SoC=%#x firmware=%#x chain=%u chain_present=%u\n",
                    context->cap.result, context->cap.error, context->cap.valid, context->cap.chip, context->cap.family,
                    context->cap.board, context->cap.soc, context->cap.firmware, context->cap.chain,
                    (unsigned)((context->cap.valid & 16u) != 0));
        }
        if (error) IOLog("REDFIN WIFI HOST: refused request to=%#x bytes=%u result=%d\n", to, size, error);
        return;
    }
    if (to != 0xfffffffeu || size < 4) return;
    uint32_t command = rf_gl_u32(data + at);
    if (command == 2 && !context->qrtr_hello) {
        context->qrtr_hello = 1;
        fw_start_qrtr_control(context, 2, 0xfffffffeu, source, 0xfffffffeu, 0, 0);
        IOLog("REDFIN WIFI QRTR: HELLO from node=%u queued reply\n", source);
        if (context->host_mode && !context->host_announced) {
            fw_start_qrtr_control(context, 4, 0xfffffffeu, source, 0xfffffffeu, 0x40, 0x101, 1, 0x4001);
            fw_start_qrtr_control(context, 4, 0xfffffffeu, source, 0xfffffffeu, 4096, 1, 1, 0x4002);
            fw_start_qrtr_control(context, 4, 0xfffffffeu, source, 0xfffffffeu, 14, 1, 1, 0x4003);
            context->host_announced = 1;
            IOLog("REDFIN WIFI HOST: announced pd-mapper/TFTP/RMTFS; RMTFS volatile=%u, no storage access\n",
                (unsigned)context->rmtfs_mode);
        }
    } else if (command == 4 && size >= 20) {
        uint32_t service = rf_gl_u32(data + at + 4), instance = rf_gl_u32(data + at + 8);
        uint32_t node = rf_gl_u32(data + at + 12), port = rf_gl_u32(data + at + 16);
        ++context->qrtr_services;
        IOLog("REDFIN WIFI QRTR: service=%#x version=%u instance=%u node=%u port=%#x\n",
            service, instance & 255u, instance >> 8, node, port);
        if (service == 0x45 && (instance & 255u) == 1 && (!context->wlfw_mode || !(instance >> 8))) {
            if (context->wlfw_mode && (node != source || (context->wlfw_port &&
                (context->wlfw_node != node || context->wlfw_port != port)))) { context->poisoned = true; return; }
            context->wlfw_node = node; context->wlfw_port = port;
        }
    }
}
static int fw_start_transport_run(fw_start_context *context)
{
    context->phase = FW_START_GLINK;
    if (!fw_start_glink_contract() || fw_start_glink_check(context) || redfin_wifi_power_audit()) return EPERM;
    context->glink_ops = {context, (const volatile uint8_t *)context->mapping[FW_START_SMEM].base,
        fw_start_glink_check, fw_start_glink_lock, fw_start_unlock, fw_start_smem_write,
        fw_start_barrier, fw_start_glink_kick, fw_start_qrtr_packet, fw_start_glink_payload};
    if (context->host_mode) context->host_ops = {context, fw_start_glink_check, fw_start_host_lookup,
        fw_start_host_send, fw_start_host_event};
    if (context->rmtfs_mode) context->rmtfs_ops = {context, fw_start_rmtfs_check, fw_start_rmtfs_barrier,
        fw_start_rmtfs_send, fw_start_rmtfs_event};
    if (context->wlfw_mode) context->wlfw_ops = {context, fw_start_wlfw_check, fw_start_wlfw_send};
    int error = rf_gl_init(&context->glink, &context->glink_ops);
    IOLog("REDFIN WIFI GLINK: init=%d descriptor=%#x TX=%#x stores=%u\n",
        error, context->glink.descriptor, context->glink.tx, context->glink.stores);
    if (error) return error;
    error = rf_gl_say(&context->glink, &context->glink_ops, 0, 1, 1, NULL, 0);
    if (error) return error;
    uint64_t first = fw_start_ns(context), next_report = first;
    uint64_t timeout = context->wlan_observe_mode ? UINT64_C(30000000000) :
        context->host_mode ? UINT64_C(45000000000) : UINT64_C(10000000000);
    while (fw_start_ns(context) - first < timeout) {
        unsigned previous_ipa = context->smp2p.ipa_responses;
        int alive = context->host_mode ? rf_wifi_smp2p_ipa_respond(&context->smp2p, &context->smp_ops) :
            rf_wifi_smp2p_alive(&context->smp2p, &context->smp_ops);
        if (context->smp2p.ipa_responses != previous_ipa)
            IOLog("REDFIN WIFI HOST: native IPA query=%#x response=1 (APPS IPA vote absent)\n", context->smp2p.ipa_state);
        if (alive && alive != RF_WIFI_SMP2P_UNSTABLE) return alive;
        if (!alive) {
            error = rf_gl_pump(&context->glink, &context->glink_ops);
            if (error && error != RF_GL_AGAIN) {
                IOLog("REDFIN WIFI GLINK: parser=%d last=%u/%u/%#x waiting=%u head=%u tail=%u RXbytes=%u channel=%u intent=%u/%u\n",
                    error, context->glink.last_command, context->glink.last_p1, context->glink.last_p2,
                    context->glink.last_waiting, context->glink.head, context->glink.tail, context->glink.rx_bytes,
                    context->glink.channel, context->glink.last_intent_id, context->glink.last_intent_bytes);
                return error;
            }
            while (context->pending_count) {
                error = rf_gl_send_packet(&context->glink, &context->glink_ops,
                    context->pending[context->pending_tail], context->pending_bytes[context->pending_tail],
                    context->transport, sizeof(context->transport));
                if (error == RF_GL_AGAIN || (error == RF_GL_ARGUMENT && !context->glink.open)) break;
                if (error) return error;
                context->pending_tail = (context->pending_tail + 1u) % 32u; --context->pending_count;
            }
        }
        uint64_t now = fw_start_ns(context);
        if (now >= next_report) {
            IOLog("REDFIN WIFI GLINK: version=%u channel=%u ack=%u open=%u RX=%#x heard=%u sent=%u packets=%u services=%u WLFW=%#x\n",
                context->glink.version, context->glink.channel, context->glink.acknowledged,
                context->glink.open, context->glink.rx, context->glink.heard, context->glink.sent,
                context->glink.packets, context->qrtr_services, context->wlfw_port);
            next_report = now + 1000000000u;
            if (context->host_mode) IOLog("REDFIN WIFI HOST: pd=%u TFTP=%u reads=%u writes=%u missing=%u pending=%u cap=%u/%u IPA=%u/%#x/%u\n",
                context->host.pd_requests, context->host.requests, context->host.reads, context->host.writes,
                context->host.missing, context->pending_count, context->cap_sent, context->cap_received,
                context->smp2p.ipa_found, context->smp2p.ipa_state, context->smp2p.ipa_responses);
            if (context->host_mode && context->host.rmtfs_requests)
                IOLog("REDFIN WIFI HOST: RMTFS observed=%u last_message=%u (all requests refused)\n",
                    context->host.rmtfs_requests, context->host.rmtfs_message);
            if (context->rmtfs_mode) IOLog("REDFIN WIFI RMTFS: requests=%u opens=%u allocs=%u read_sectors=%u write_sectors=%u failures=%u\n",
                context->rmtfs.requests, context->rmtfs.opens, context->rmtfs.allocations,
                context->rmtfs.reads, context->rmtfs.writes, context->rmtfs.failures);
        }
        if (context->wlfw_port) {
            if (!context->host_mode) return 0;
            if (context->wlfw_mode) {
                if (!context->wlfw_setup.attempted) {
                    error = rf_wlfw_begin_features(&context->wlfw_setup, &context->wlfw_ops, context->wlan_power_mode ? 1u : 0u);
                    if (error) return error;
                    IOLog("REDFIN WIFI WLFW: native legacy indication/MSA/CAP handshake begins; fixed permissions, no MSA CPU map\n");
                }
                if (context->wlfw_setup.stage == RF_WLFW_FAILED) {
                    IOLog("REDFIN WIFI WLFW: stopped result=%u error=%u already_registered=%u\n",
                        context->wlfw_setup.result, context->wlfw_setup.error, context->wlfw_setup.already_registered);
                    return context->wlfw_setup.already_registered ? EBUSY : EIO;
                }
                if (context->wlfw_setup.stage == RF_WLFW_COMPLETE) {
                    if (!context->wlan_observe_mode) return 0;
                    if (!context->wlan_observed) {
                        if (context->wlan_power_mode) {
                            if (fw_start_wlan_power_policy(context)) return EPERM;
                            error = redfin_wifi_wlan_power_start((context->cap.valid & 16u) != 0, context->cap.chain,
                                context, fw_start_wlan_power_policy);
                            IOLog("REDFIN WIFI WLAN: native power sequence=%d; waiting for FW_READY\n", error);
                        } else {
                            error = redfin_wifi_wlan_resources_observe();
                            IOLog("REDFIN WIFI WLAN: resource observer=%d; no WLAN power writes, waiting for FW_READY\n", error);
                        }
                        if (error) return error;
                        context->wlan_observed = true;
                    }
                    if (context->wlan_power_mode && !context->dynamic_sent) {
                        uint8_t request[18]; rf_wlfw_dynamic_request(request);
                        error = fw_start_qrtr_queue(context, 1, 0x4004, context->wlfw_node, context->wlfw_port,
                            request, sizeof(request));
                        if (error) return error;
                        context->dynamic_sent = 1;
                        IOLog("REDFIN WIFI WLFW: queued native post-power dynamic feature mask1 transaction5\n");
                    }
                    if (context->wlfw_setup.fw_ready) return 0;
                }
            } else if (!context->cap_sent) {
                const uint8_t request[7] = {0, 1, 0, 0x24, 0, 0, 0};
                error = fw_start_qrtr_queue(context, 1, 0x4004, context->wlfw_node, context->wlfw_port,
                    request, sizeof(request));
                if (error) return error;
                context->cap_sent = 1;
                IOLog("REDFIN WIFI WLFW: queued native CAP transaction=1\n");
            }
            if (!context->wlfw_mode && context->cap_received) return context->cap.result ? EIO : 0;
        }
        if (fw_start_pause(context, 1000)) return EPERM;
    }
    return ETIMEDOUT;
}

static int fw_start_rmtfs_open(fw_start_context *context)
{
    if (!context->rmtfs_mode || context->rmtfs_attempted || context->convention != 64 || fw_start_check(context))
        return EPERM;
    const rf_wifi_fw_layout *layout = &fw_probe.boot.native_layout;
    if (context->rmtfs_snapshot[0] < layout->kernel_end ||
        (layout->ramdisk.bytes && context->rmtfs_snapshot[0] < layout->ramdisk.base + layout->ramdisk.bytes)) return EPERM;
    for (unsigned i = FW_START_RMTFS_SNAPSHOT_MAP; i < FW_START_MAPS; ++i) {
        int error = fw_start_map_range(context, i);
        if (error) return error;
    }
    const uint8_t *source = (const uint8_t *)context->mapping[FW_START_RMTFS_SNAPSHOT_MAP].base;
    for (uint64_t i = context->rmtfs_bytes; i < context->rmtfs_snapshot[1]; ++i) if (source[(size_t)i]) return EPERM;
    int error = rf_rm_image_open(&context->rmtfs, source, (size_t)context->rmtfs_bytes,
        context->rmtfs_sha256, redfin_mpss_kernel_sha256, NULL);
    if (error || fw_start_check(context)) return EPERM;
    size_t shadow_bytes = rf_rm_shadow_bytes(&context->rmtfs);
    if (!shadow_bytes || shadow_bytes > 12u * 1024u * 1024u) return EINVAL;
    context->rmtfs_shadow = IOMalloc(shadow_bytes);
    if (!context->rmtfs_shadow || rf_rm_shadow_open(&context->rmtfs, (uint8_t *)context->rmtfs_shadow, shadow_bytes))
        return ENOMEM;
    const volatile uint64_t *pool = (const volatile uint64_t *)context->mapping[FW_START_RMTFS_POOL_MAP].base;
    for (unsigned i = 0; i < 0x288000u / 8u; ++i) {
        uint64_t expected = i < 16384u / 8u || i >= (16384u + RF_RM_SHARED) / 8u ?
            UINT64_C(0xa7a7a7a7a7a7a7a7) : 0;
        if (pool[i] != expected) return EBUSY;
    }
    uint8_t *scratch = (uint8_t *)context->mapping[FW_START_RMTFS_SCRATCH_MAP].base;
    for (unsigned i = 0; i < 16384u; ++i) if (scratch[i]) return EBUSY;
    error = rf_rm_hyp_prepare(scratch, context->rmtfs_scratch[0], context->rmtfs_shared_reg[0]);
    if (error || fw_start_check(context)) return EPERM;
    __asm__ volatile("dsb sy" ::: "memory");
    context->phase = FW_START_RMTFS; context->rmtfs_attempted = true;
    context->function = UINT64_C(0x42000c16);
    rf_sq_report report = {};
    error = rf_rm_hyp_run(&context->scm_ops, context->rmtfs_scratch[0], &report);
    context->function = 0;
    IOLog("REDFIN WIFI RMTFS: HLOS/MSS share=%d status=%lld value=%#llx calls=%u resumes=%u shadow_bytes=%llu\n",
        error, (int64_t)report.status, (unsigned long long)report.value[0], report.calls, report.resumes,
        (unsigned long long)shadow_bytes);
    if (error) return error;
    context->rmtfs_shared = true;
    error = rf_rm_bind(&context->rmtfs,
        (volatile uint8_t *)(context->mapping[FW_START_RMTFS_POOL_MAP].base + 16384u),
        context->rmtfs_shared_reg[0], RF_RM_SHARED);
    if (error || fw_start_check(context)) return EPERM;
    IOLog("REDFIN WIFI RMTFS: four verified snapshots, shim-owned low buffer and volatile shadows ready\n");
    return 0;
}

static int fw_start_run(fw_start_context *context)
{
    context->phase = FW_START_SOURCE;
    const rf_wifi_fw_boot_policy policy = {context, fw_start_source_policy,
        fw_probe.excluded, fw_probe.exclusions};
    int error = redfin_wifi_fw_boot_open(&fw_probe.boot, &fw_probe.workspace, &policy);
    if (error) return error;
    if (context->metadata[0] < fw_probe.boot.native_layout.kernel_end ||
        context->metadata[0] + context->metadata[1] != fw_probe.boot.native_blob.physical ||
        (fw_probe.boot.native_layout.ramdisk.bytes && context->metadata[0] <
            fw_probe.boot.native_layout.ramdisk.base + fw_probe.boot.native_layout.ramdisk.bytes) ||
        fw_probe.workspace.image.asset[0].bytes > context->metadata[1]) return EPERM;
    if (context->host_mode) {
        if (context->assets_reg[0] < fw_probe.boot.native_layout.kernel_end ||
            (fw_probe.boot.native_layout.ramdisk.bytes && context->assets_reg[0] <
                fw_probe.boot.native_layout.ramdisk.base + fw_probe.boot.native_layout.ramdisk.bytes)) return EPERM;
        error = fw_start_map_range(context, FW_START_ASSETS_MAP);
        if (error) return error;
        const uint8_t *data = (const uint8_t *)context->mapping[FW_START_ASSETS_MAP].base;
        for (uint64_t i = context->assets_bytes; i < context->assets_reg[1]; ++i) if (data[(size_t)i]) return EPERM;
        error = rf_wlan_assets_open(&context->assets, data, (size_t)context->assets_bytes,
            context->assets_sha256, redfin_mpss_kernel_sha256, NULL);
        if (error || fw_start_check(context)) return EPERM;
        IOLog("REDFIN WIFI HOST: verified resident assets=%u bytes=%llu\n", context->assets.count,
            (unsigned long long)context->assets_bytes);
    }
    IOLog("REDFIN WIFI START: resident source verified; native PIL begins\n");
    context->phase = FW_START_POWER;
    error = redfin_wifi_power_start();
    if (error) return error;
    context->power = true;
    for (unsigned i = 0; i < FW_START_MPSS; ++i) {
        error = fw_start_map_range(context, i);
        if (error) return error;
    }
    error = fw_start_map_range(context, FW_START_METADATA_MAP);
    if (error) return error;
    const volatile uint8_t *metadata = (const volatile uint8_t *)context->mapping[FW_START_METADATA_MAP].base;
    for (unsigned i = 0; i < context->metadata[1]; ++i) if (metadata[i]) return EBUSY;
    context->scm_ops = {context, fw_start_valid, fw_start_invoke, fw_start_scm_delay, fw_start_ns};
    context->phase = FW_START_ABI;
    rf_sq_report report = {};
    context->convention = 64; context->function = UINT64_C(0xc2000601);
    error = rf_sq_run(&context->scm_ops, 64, RF_SQ_DETECT, 0, &report);
    if (error || !report.value[0]) {
        context->convention = 32; context->function = UINT64_C(0x82000601);
        error = rf_sq_run(&context->scm_ops, 32, RF_SQ_DETECT, 0, &report);
    }
    context->function = 0;
    if (error || !report.value[0]) return ENOTSUP;
    if (context->convention != 64) return ENOTSUP;
    IOLog("REDFIN WIFI START: native SCM convention=%u\n", context->convention);
    if (context->rmtfs_mode) {
        error = fw_start_rmtfs_open(context);
        if (error) return error;
    }
    const rf_wifi_fw_copy_ops copy = {context, fw_start_copy_check, fw_start_copy, fw_start_zero,
        fw_start_readback, fw_start_sync};
    context->phase = FW_START_METADATA;
    error = rf_wifi_fw_copy_metadata_to(&fw_probe.boot.source, &fw_probe.boot.source_ops, &copy,
        context->metadata[0], context->readback, sizeof(context->readback));
    if (error) return error;
    context->phase = FW_START_INIT;
    error = fw_start_pas(context, 1);
    if (error) return error;
    context->initialized = true;
    context->phase = FW_START_SETUP;
    error = fw_start_pas(context, 2);
    if (error) return error;
    context->setup = true; context->reset = true;
    context->smp_ops = {(const volatile uint8_t *)context->mapping[FW_START_SMEM].base,
        REDFIN_SMEM_BYTES, context, fw_start_check, fw_start_reset, fw_start_started,
        fw_start_lock, fw_start_unlock, fw_start_smem_write, fw_start_barrier,
        fw_start_kick, fw_start_ms, fw_start_pause};
    context->phase = FW_START_SMP2P;
    error = rf_wifi_smp2p_prepare(&context->smp2p, &context->smp_ops);
    IOLog("REDFIN WIFI START: SMP2P prepare=%d stage=%u stores=%u kicks=%u\n",
        error, context->smp2p.stage, context->smp2p.stores, context->smp2p.kicks);
    if (error) return error;
    error = fw_start_map_range(context, FW_START_MPSS);
    if (error) return error;
    context->phase = FW_START_COPY;
    error = rf_wifi_fw_copy_segments(&fw_probe.boot.source, &fw_probe.boot.source_ops, &copy,
        context->readback, sizeof(context->readback));
    if (error) return error;
    error = rf_wifi_smp2p_auth_begin(&context->smp2p, &context->smp_ops);
    if (error) return error;
    context->phase = FW_START_AUTH;
    /* AUTH uncertainty retains all mappings/votes; no forced PAS shutdown. */
    context->auth_attempted = true;
    error = fw_start_pas(context, 5);
    if (error) return error;
    context->authenticated = true; context->reset = false;
    context->phase = FW_START_READY;
    error = rf_wifi_smp2p_wait_ready(&context->smp2p, &context->smp_ops, RF_WIFI_SMP2P_MAX_READY_MS);
    IOLog("REDFIN WIFI START: SMP2P ready=%d stage=%u state=%#x handover=%u\n",
        error, context->smp2p.stage, context->smp2p.last_state, context->smp2p.handover);
    if (!error && context->transport_mode) error = fw_start_transport_run(context);
    return error;
}

static void fw_start_worker(void *, wait_result_t)
{
    const char *args = PE_boot_args(); unsigned bytes = 0;
    int mode = 0;
    bool mode_valid = PE_parse_boot_argn("redfinwififw", &mode, sizeof(mode)) && mode >= 2 && mode <= 4;
    DTEntry rmtfs_node;
    bool rmtfs_present = SecureDTLookupEntry(NULL, "/redfin-rmtfs", &rmtfs_node) == kSuccess;
    fw_start.transport_mode = mode >= 3; fw_start.host_mode = mode == 4;
    fw_start.rmtfs_mode = rmtfs_present && mode == 4;
    DTEntry wlfw_node;
    bool wlfw_present = SecureDTLookupEntry(NULL, "/redfin-wifi-wlfw", &wlfw_node) == kSuccess;
    fw_start.wlfw_mode = wlfw_present && mode == 4 && rmtfs_present;
    DTEntry wlan_node;
    bool wlan_present = SecureDTLookupEntry(NULL, "/redfin-wifi-wlan", &wlan_node) == kSuccess;
    fw_start.wlan_observe_mode = wlan_present && fw_start.wlfw_mode;
    uint32_t observe = 2;
    fw_start.wlan_power_mode = wlan_present && fw_property(wlan_node, "observe-only", &observe, sizeof(observe)) && !observe;
    if (args) while (bytes < sizeof(fw_probe.args) && args[bytes]) ++bytes;
    if (!args || bytes == sizeof(fw_probe.args) ||
        !mode_valid || !fw_probe_args(args, bytes + 1, &fw_probe.nonce, (unsigned)mode) ||
        !fw_probe_properties(&fw_probe, true) || !fw_start_metadata_contract(&fw_start, true) ||
        (mode >= 3 && !fw_start_glink_contract()) || (mode == 4 && !fw_start_assets_contract(&fw_start, true)) ||
        (rmtfs_present && (mode != 4 || !fw_start_rmtfs_contract(&fw_start, true))) ||
        (wlfw_present && (!fw_start.wlfw_mode || !fw_start_wlfw_contract())) ||
        (wlan_present && (!fw_start.wlan_observe_mode || !fw_start_wlan_contract()))) {
        IOLog("REDFIN WIFI START: refused exact native firmware args/exclusions\n");
        thread_terminate_self();
        __builtin_unreachable();
    }
    memcpy(fw_probe.args, args, bytes + 1); fw_probe.bytes = bytes + 1;
    fw_probe.owner = current_thread(); fw_probe.active = true; fw_start.active = true;
    IOLog("REDFIN WIFI START: serialized CPU0 worker interrupts=%u\n", (unsigned)ml_get_interrupts_enabled());
    int error = fw_start_run(&fw_start);
    IOLog("REDFIN WIFI START: result=%d phase=%u reset=%u init=%u setup=%u auth=%u smp_stage=%u copies=%u payload=%llu BSS=%llu retained=1\n",
        error, fw_start.phase, fw_start.reset, fw_start.initialized, fw_start.setup,
        fw_start.authenticated, fw_start.smp2p.stage, fw_start.copies,
        (unsigned long long)fw_probe.boot.source.copied_bytes,
        (unsigned long long)fw_probe.boot.source.zeroed_bytes);
    /* This bounded diagnostic never frees remote-visible state or retries.
     * The shim/PMIC watchdog resets the complete platform back to fastboot. */
    if (error) fw_start.poisoned = true;
    fw_start.active = false;
    fw_probe.active = false;
    thread_terminate_self();
    __builtin_unreachable();
}

extern "C" void redfin_wifi_fw_start(void)
{
    if (__atomic_exchange_n(&fw_probe_attempted, 1, __ATOMIC_RELAXED)) return;
    thread_t worker = THREAD_NULL;
    kern_return_t error = kernel_thread_start(fw_start_worker, NULL, &worker);
    if (error != KERN_SUCCESS) {
        IOLog("REDFIN WIFI START: worker creation failed=%d\n", error);
        return;
    }
    thread_deallocate(worker);
}
