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

extern "C" int redfin_wifi_power_start(void);
extern "C" int redfin_wifi_power_held(void);
extern "C" int redfin_wifi_power_audit(void);
/* Built-in XNU worker exit; declaration is private to Mach compilation in
 * this pinned kernel's kern/thread.h. This is not an external kext KPI. */
extern "C" void thread_terminate_self(void);

enum { FW_START_SOURCE = 1, FW_START_POWER, FW_START_ABI, FW_START_RESET,
    FW_START_SMP2P, FW_START_METADATA, FW_START_INIT, FW_START_SETUP,
    FW_START_COPY, FW_START_AUTH, FW_START_READY };
enum { FW_START_SMEM, FW_START_TCSR, FW_START_IPCC, FW_START_MPSS, FW_START_METADATA_MAP, FW_START_MAPS };
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
};
static fw_start_context fw_start;

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

static int fw_start_check(void *opaque)
{
    fw_start_context *context = (fw_start_context *)opaque;
    bool valid = context == &fw_start && context->active && !context->poisoned && ml_get_interrupts_enabled() &&
        !fw_probe_check(&fw_probe, fw_probe.nonce) && fw_start_metadata_contract(context, false) &&
        (!context->power || !redfin_wifi_power_held());
    if (valid) for (unsigned i = 0; i < FW_START_MAPS; ++i) {
        const fw_start_map *entry = &context->mapping[i];
        if (!entry->map && !entry->memory && !entry->base) continue;
        if (!entry->map || !entry->memory || !entry->base ||
            entry->map->getVirtualAddress() != entry->base ||
            entry->map->getLength() != (i == FW_START_METADATA_MAP ? context->metadata[1] :
                fw_start_ranges[2u * i + 1u])) { valid = false; break; }
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
    uint64_t physical = index == FW_START_METADATA_MAP ? context->metadata[0] : fw_start_ranges[2u * index];
    uint64_t bytes = index == FW_START_METADATA_MAP ? context->metadata[1] : fw_start_ranges[2u * index + 1u];
    entry->memory = IOMemoryDescriptor::withPhysicalAddress(physical, bytes, kIODirectionInOut);
    entry->map = entry->memory ? entry->memory->map(
        index == FW_START_SMEM || index == FW_START_MPSS || index == FW_START_METADATA_MAP ?
            kIOMapWriteCombineCache : kIOMapInhibitCache) : NULL;
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
    if (!timeout_ms || timeout_ms > 1000 || context->locked || fw_start_reset(context)) return EPERM;
    volatile uint32_t *lock = (volatile uint32_t *)(context->mapping[FW_START_TCSR].base + RF_WIFI_SMP2P_LOCK_OFFSET);
    uint64_t first = fw_start_ns(context);
    do {
        if (fw_start_reset(context)) return EPERM;
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
    return error;
}

static void fw_start_worker(void *, wait_result_t)
{
    const char *args = PE_boot_args(); unsigned bytes = 0;
    if (args) while (bytes < sizeof(fw_probe.args) && args[bytes]) ++bytes;
    if (!args || bytes == sizeof(fw_probe.args) ||
        !fw_probe_args(args, bytes + 1, &fw_probe.nonce, 2) || !fw_probe_properties(&fw_probe, true) ||
        !fw_start_metadata_contract(&fw_start, true)) {
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
