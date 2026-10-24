/* SPDX-License-Identifier: MIT */
/* Exact md0/UP adapter for the separately proved, held-CX GMU TCM leaf. */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <kern/processor.h>
#include <kern/cpu_number.h>
#include <arm64/redfin_gui_profile.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <machine/machine_routines.h>
#include <vm/vm_kern.h>
#include <vm/pmap.h>
#include <arm/pmap_public.h>
#include "redfin_gmu_probe.h"
#include "redfin_gmu_tcm.h"
#include "redfin_gpu_smmu.h"
#include "redfin_gpu_context.h"
#include "redfin_gmu_mapping.h"
#include "redfin_gmu_start.h"
#include "redfin_rpmh.h"
#include "redfin_gpu_command.h"
#include "redfin_gpu_runtime.h"
#include "redfin_gpu_service.h"

extern int redfin_spmi_return_ready(void);
extern int redfin_gui_cpu0(void);
extern int redfin_gpu_power_probe(void);
extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern vm_offset_t ml_io_map_wcomb(vm_offset_t, vm_size_t);
static bool gm_attempted;

struct gm_binding { const void *live, *expected; unsigned bytes; bool payload; };
struct gm_context {
    vm_offset_t base[3], gic, smmu, cb;
    const char *parent_args;
    void *parent_context;
    redfin_gmu_parent_valid_fn parent_valid;
    unsigned args_bytes;
    char args[608];
    struct gm_binding bindings[40];
    uint64_t breadcrumbs;
    unsigned binding_count, dtcm_writes, smmu_reads, smmu_guard, smmu_breadcrumbs;
    unsigned smmu_mode, cb_reads, cb_breadcrumbs;
    bool active, smmu_requested, smmu_ready, gx_requested, gx_granted;
};
static bool gm_memory_contract(struct gm_context *);
static int gm_memory_run(struct gm_context *, const struct rf_gs_snapshot *, const struct rf_gc_snapshot *);
static bool gm_start_contract(struct gm_context *);
static int gm_start_run(struct gm_context *);
static bool gx_contract(struct gm_context *);
static int gx_run(struct gm_context *);
static int gr_adopt(struct gm_context *);

bool redfin_gmu_boot_args_mode(const char *args,unsigned bytes,unsigned *mode)
{
    if(redfin_gpu_gui_profile(args,bytes,NULL)) {if(mode)*mode=6;return true;}
    return redfin_gmu_args_mode(args,bytes,mode);
}

static const uint64_t gm_reg[] = {
    0x00100000, 0x1f0000, 0x03d90000, 0x9000,
    0x03d6a000, 0x30000, 0x17a00000, 0x4000
};
static const uint64_t gm_dram_base = 0x180000000ULL, gm_dram_size = 0x80000000ULL;
static const uint32_t gm_chip = 0x06020001;
static const uint32_t gm_clock[] = {200000000, 31, 0x4000, 2, 6, 2, 0x71028, 3, 3, 0xf03, 0x103};
static const uint32_t gm_tcm[] = {2, 0x10004000, 0x7000, 2, 1, 1000};
static const uint32_t gm_parent[] = {0x30000, 64, 65535, 7, 416};
static const uint32_t gm_irqs[] = {336, 337};
static const uint64_t gm_smmu_reg[] = {0x03da0000, 0x10000};
static const uint32_t gm_smmu_streams[] = {4, 0x400, 5, 0x400};
static const uint32_t gm_smmu_format[] = {0x1000, 0x8000, 128, 8, 39, 36};
static const uint32_t gm_smmu_clocks[][4] = {
    {RF_GT_GCC, 0x7100c, 0x80000001u, 1},
    {RF_GT_GCC, 0x71018, 0x80000001u, 1},
    {RF_GT_GPUCC, 0x1078, 1, 1}, /* Native AHB HALT_DELAY: enable bit only. */
    {RF_GT_GPUCC, 0x5000, 0x80000001u, 1}
};
static const uint32_t gm_smmu_irqs[] = {705, 710, 711, 712, 713, 714, 715, 716, 717};
static const uint32_t gm_cb_policy[] = {1, 0x8000, RF_GC_MAP_BYTES, RF_GC_BANKS, 0x1000, RF_GC_WORDS};

static bool
gm_property(struct gm_context *context, const char *path, const char *key,
    const void *expected, unsigned size)
{
    DTEntry node;
    const void *raw = NULL;
    unsigned bytes = 0;
    if (SecureDTLookupEntry(NULL, path, &node) != kSuccess ||
        SecureDTGetProperty(node, key, &raw, &bytes) != kSuccess ||
        !raw || bytes != size || memcmp(raw, expected, size))
        return false;
    if (context) {
        if (context->binding_count >= sizeof(context->bindings) / sizeof(context->bindings[0]))
            return false;
        struct gm_binding *binding = &context->bindings[context->binding_count++];
        binding->live = raw;
        binding->expected = expected;
        binding->bytes = bytes;
        binding->payload = (!strcmp(path, "/redfin-gmu") && !strcmp(key, "firmware")) ||
            (!strcmp(path, "/redfin-gpu-command") &&
             (!strcmp(key, "sqe") || !strcmp(key, "zap-mdt") || !strcmp(key, "zap-segment")));
    }
    return true;
}

static bool
gm_contract(struct gm_context *context, unsigned mode)
{
    bool base = gm_property(context, "/chosen", "dram-base", &gm_dram_base, sizeof(gm_dram_base)) &&
        gm_property(context, "/chosen", "dram-size", &gm_dram_size, sizeof(gm_dram_size)) &&
        gm_property(context, "/redfin-gmu", "reg", gm_reg, sizeof(gm_reg)) &&
        gm_property(context, "/redfin-gmu", "chip-id", &gm_chip, sizeof(gm_chip)) &&
        gm_property(context, "/redfin-gmu", "clock-policy", gm_clock, sizeof(gm_clock)) &&
        gm_property(context, "/redfin-gmu", "tcm-policy", gm_tcm, sizeof(gm_tcm)) &&
        gm_property(context, "/redfin-gmu", "cx-parent", gm_parent, sizeof(gm_parent)) &&
        gm_property(context, "/redfin-gmu", "gic-intids", gm_irqs, sizeof(gm_irqs));
    if (!base || !mode)
        return base;
    return gm_property(context, "/redfin-gpu-smmu", "reg", gm_smmu_reg, sizeof(gm_smmu_reg)) &&
        gm_property(context, "/redfin-gpu-smmu", "chip-id", &gm_chip, sizeof(gm_chip)) &&
        gm_property(context, "/redfin-gpu-smmu", "stream-map", gm_smmu_streams, sizeof(gm_smmu_streams)) &&
        gm_property(context, "/redfin-gpu-smmu", "format-policy", gm_smmu_format, sizeof(gm_smmu_format)) &&
        gm_property(context, "/redfin-gpu-smmu", "clock-policy", gm_smmu_clocks, sizeof(gm_smmu_clocks)) &&
        gm_property(context, "/redfin-gpu-smmu", "gic-intids", gm_smmu_irqs, sizeof(gm_smmu_irqs)) &&
        (mode < 2 || gm_property(context, "/redfin-gpu-smmu", "context-policy",
            gm_cb_policy, sizeof(gm_cb_policy))) &&
        (mode < 3 || gm_memory_contract(context)) &&
        (mode < 4 || gm_start_contract(context)) &&
        (mode < 5 || gx_contract(context)) &&
        (mode != 6 || gm_property(context,"/redfin-gpu-command","runtime-policy",rf_gr_policy,sizeof(rf_gr_policy)));
}

int
redfin_gmu_probe_contract(const char *frozen_args, unsigned args_bytes)
{
    const char *live = PE_boot_args();
    unsigned mode = 0;
    if (!redfin_gmu_boot_args_mode(frozen_args, args_bytes, &mode) || !live ||
        memcmp(live, frozen_args, args_bytes))
        return ENOTSUP;
    return gm_contract(NULL, mode) ? 0 : ENXIO;
}

static uint32_t
gm_read32(vm_offset_t address)
{
    uint32_t value = *(volatile const uint32_t *)address;
    __asm__ volatile("dmb oshld" ::: "memory");
    return value;
}

static void
gm_write32(vm_offset_t address, uint32_t value)
{
    __asm__ volatile("dmb oshst" ::: "memory");
    *(volatile uint32_t *)address = value;
    __asm__ volatile("dsb osh" ::: "memory");
}

static bool
gm_valid(void *argument)
{
    struct gm_context *context = argument;
    const char *live = PE_boot_args();
    if (!context || !context->active || !context->args_bytes || !context->parent_args ||
        !context->parent_context || !context->parent_valid || !live ||
        memcmp(live, context->args, context->args_bytes) ||
        memcmp(context->parent_args, context->args, context->args_bytes) ||
        __builtin_arm_rsr64("CurrentEL") != 4 ||
        (__builtin_arm_rsr64("MPIDR_EL1") & 0xff00ffffffULL) ||
        (context->smmu_mode==6 ? !redfin_gui_cpu0() : redfin_spmi_return_ready()!=1) ||
        !context->parent_valid(context->parent_context))
        return false;
    for (unsigned i = 0; i < context->binding_count; i++) {
        const struct gm_binding *binding = &context->bindings[i];
        if (!binding->payload && memcmp(binding->live, binding->expected, binding->bytes))
            return false;
    }
    if (context->base[RF_GT_GCC] &&
        (gm_read32(context->base[RF_GT_GCC] + 0x71004) & 0x80000001u) != 1)
        return false;
    if (context->base[RF_GT_GPUCC] &&
        ((gm_read32(context->base[RF_GT_GPUCC] + 0x106c) & 3u) ||
         !(gm_read32(context->base[RF_GT_GPUCC] + 0x1540) & 0x80000000u)))
        return false;
    if (context->gic) {
        const uint32_t mask = 3u << 16;
        if ((gm_read32(context->gic + 0x128) | gm_read32(context->gic + 0x228) |
                gm_read32(context->gic + 0x328)) & mask)
            return false;
        if (context->smmu_requested &&
            ((gm_read32(context->gic + 0x158) | gm_read32(context->gic + 0x258) |
                gm_read32(context->gic + 0x358)) & 0x3fc2u))
            return false;
    }
    return true;
}

/* Firmware is an immutable private CPU source, absent from device DMA maps.
 * Check it at complete ownership audits, payload chunks and publication,
 * without re-comparing80KiB inside every nested clock/GIC MMIO access.
 * Arguments, policies/ranges, hashes, CPU/parent/GIC/CX remain per-access. */
static bool gm_payloads_valid(struct gm_context *context)
{
    if (!gm_valid(context)) return false;
    for (unsigned i = 0; i < context->binding_count; ++i) {
        const struct gm_binding *b = &context->bindings[i];
        if (b->payload && memcmp(b->live, b->expected, b->bytes)) return false;
    }
    return true;
}

/* One message per first register access; no polling-loop log stream. */
static bool
gm_breadcrumb(struct gm_context *context, unsigned unit, uint32_t at, bool writing)
{
    unsigned index;
    if (unit == RF_GT_GCC) {
        switch (at) {
        case 0: index = 0; break;
        case 4: index = 1; break;
        case 0xc: index = 2; break;
        case 0x40: index = 3; break;
        case 0x71028: index = 4; break;
        case 0x52010: index = 5; break;
        case 0x52000: index = 6; break;
        case 0x71154: index = 7; break;
        case 0x7100c: index = 8; break;
        case 0x71018: index = 9; break;
        default: return false;
        }
    } else if (unit == RF_GT_GPUCC) {
        switch (at) {
        case 0x1120: index = 10; break;
        case 0x1124: index = 11; break;
        case 0x1078: index = 12; break;
        case 0x5000: index = 13; break;
        case 0x1098: index = 14; break;
        case 0x100c: index = 15; break;
        case 0x1064: index = 16; break;
        default: return false;
        }
    } else if (unit == RF_GT_GMU) {
        switch (at) {
        case 0x14000: index = 17; break;
        case 0x14070: index = 18; break;
        case 0x14600: index = 19; break;
        case 0x14220: index = 20; break;
        case 0x7000: index = 21; break;
        case 0x7004: index = 22; break;
        default: return false;
        }
    } else {
        return false;
    }
    if (writing)
        index += 32;
    uint64_t bit = UINT64_C(1) << index;
    if (context->breadcrumbs & bit)
        return false;
    context->breadcrumbs |= bit;
    printf("REDFIN GMU ACCESS: unit=%u offset=%#x first-%s\n", unit, at, writing ? "write" : "read");
    return true;
}

static int
gm_read(void *argument, unsigned unit, uint32_t at, uint32_t *value)
{
    struct gm_context *context = argument;
    if (!value || unit >= 3 || !context->base[unit] || !rf_gt_allowed(unit, at, false))
        return EINVAL;
    if (!gm_valid(context))
        return ECANCELED;
    if (gm_breadcrumb(context, unit, at, false) && !gm_valid(context))
        return ECANCELED;
    *value = gm_read32(context->base[unit] + at);
    return 0;
}

static int
gm_write(void *argument, unsigned unit, uint32_t at, uint32_t value)
{
    struct gm_context *context = argument;
    if (unit >= 3 || !context->base[unit] || !rf_gt_allowed(unit, at, true) ||
        (unit == RF_GT_GMU && at == 0x14000 && value != 1))
        return EINVAL;
    if (!gm_valid(context))
        return ECANCELED;
    bool logged = gm_breadcrumb(context, unit, at, true);
    if (unit == RF_GT_GMU && (at == 0x7000 || at == 0x7004)) {
        if (context->dtcm_writes++ == 2) {
            printf("REDFIN GMU STEP: DTCM restore begins; reset held\n");
            logged = true;
        }
    }
    if (logged && !gm_valid(context))
        return ECANCELED;
    gm_write32(context->base[unit] + at, value);
    return 0;
}

static void
gm_delay(void *argument, unsigned microseconds)
{
    (void)argument;
    delay((int)microseconds); /* Leaf delays are bounded to at most 1000us. */
}

static uint64_t
gm_time_ns(void *argument)
{
    uint64_t nanoseconds;
    (void)argument;
    absolutetime_to_nanoseconds(mach_absolute_time(), &nanoseconds);
    return nanoseconds;
}

static bool
gm_smmu_valid(void *argument)
{
    struct gm_context *context = argument;
    struct rf_gt_report source = {0};
    uint32_t value;
    if (!context)
        return false;
    context->smmu_guard = 1;
    if (!context->smmu_requested || !context->smmu_ready || !gm_payloads_valid(context))
        return false;
    const struct rf_gt_ops ops = {.context = context, .valid = gm_valid, .read = gm_read};
    context->smmu_guard = 2;
    if (rf_gt_source_live(&ops, &source, true))
        return false;
    context->smmu_guard = 3;
    if (gm_read(context, RF_GT_GCC, 0x71028, &value) || (value & 3u) != 3)
        return false;
    for (unsigned i = 0; i < sizeof(gm_smmu_clocks) / sizeof(gm_smmu_clocks[0]); i++) {
        const uint32_t *clock = gm_smmu_clocks[i];
        if (gm_read(context, clock[0], clock[1], &value) || (value & clock[2]) != clock[3])
            return false;
    }
    context->smmu_guard = 4;
    if (gm_read(context, RF_GT_GMU, 0x14000, &value) || value != 1 ||
        gm_read(context, RF_GT_GMU, 0x14070, &value) || value != 0 ||
        gm_read(context, RF_GT_GMU, 0x14600, &value) || value != 0)
        return false;
    context->smmu_guard = 5;
    return true;
}

static bool
gm_smmu_step(struct gm_context *context, unsigned bit, const char *phase, uint32_t at)
{
    if (context->smmu_breadcrumbs & (1u << bit))
        return false;
    context->smmu_breadcrumbs |= 1u << bit;
    printf("REDFIN SMMU ACCESS: phase=%s first-offset=%#x; global-only\n", phase, at);
    return true;
}

static uint32_t
gm_scalar_read(vm_offset_t address)
{
    uint32_t raw;
    __asm__ volatile("ldr %w0, [%1]" : "=r"(raw) : "r"(address) : "memory");
    __asm__ volatile("dmb oshld" ::: "memory");
    return raw;
}

static int
gm_smmu_read(void *argument, uint32_t at, uint32_t *value)
{
    struct gm_context *context = argument;
    static const struct rf_gs_snapshot limits = {
        .page_bytes = 0x1000, .global_bytes = 0x8000,
        .streams = RF_GS_MAX_STREAMS, .contexts = RF_GS_MAX_CONTEXTS
    };
    if (!context || !value || !context->smmu || !rf_gs_read_allowed(at, &limits))
        return EINVAL;
    if (!gm_smmu_valid(context))
        return ECANCELED;
    bool logged = false;
    if (at == 0x20)
        logged = context->smmu_reads ? gm_smmu_step(context, 4, "recheck", at) :
            gm_smmu_step(context, 0, "ids", at);
    else if (at == 0)
        logged = gm_smmu_step(context, 1, "globals", at);
    else if (at == 0x800)
        logged = gm_smmu_step(context, 2, "routes", at);
    else if (at == 0x1000)
        logged = gm_smmu_step(context, 3, "gr1-metadata", at);
    if (logged && !gm_smmu_valid(context))
        return ECANCELED;
    /* Explicit scalar LDR for HYP-intercepted globals; never a CB page. */
    *value = gm_scalar_read(context->smmu + at);
    context->smmu_reads++;
    return 0;
}

static int
gm_cb_read(void *argument, unsigned bank, uint32_t at, uint32_t *value)
{
    struct gm_context *context = argument;
    if (!context || !context->cb || context->smmu_mode < 2 ||
        !value || !rf_gc_allowed(bank, at))
        return EINVAL;
    if (!gm_smmu_valid(context))
        return ECANCELED;
    if (!(context->cb_breadcrumbs & (1u << bank))) {
        context->cb_breadcrumbs |= 1u << bank;
        printf("REDFIN GPU CONTEXT ACCESS: bank=%u first-offset=%#x; read-only\n", bank, at);
        if (!gm_smmu_valid(context))
            return ECANCELED;
    }
    *value = gm_scalar_read(context->cb + bank * 0x1000 + at);
    context->cb_reads++;
    return 0;
}

#include "redfin_gmu_memory.inc"
#include "redfin_gmu_start.inc"
#include "redfin_gpu_command.inc"
#include "redfin_gpu_runtime.inc"

static int
gm_cb_run(struct gm_context *context, const struct rf_gs_snapshot *global)
{
    struct rf_gc_snapshot snapshot = {0};
    int result = ECANCELED;
    if (context->smmu_mode >= 2 && global->stable && global->map_format_supported &&
        !global->error && global->stage == 4 && global->contexts >= RF_GC_BANKS &&
        !global->stage2_contexts && gm_smmu_valid(context)) {
        printf("REDFIN GPU CONTEXT STEP: stable globals; inspect CB0/1, no table dereference\n");
        if (gm_smmu_valid(context)) {
            context->cb = ml_io_map(RF_GS_PHYS + 0x8000, RF_GC_MAP_BYTES);
            if (!context->cb) {
                result = ENOMEM;
            } else {
                const struct rf_gc_ops ops = {context, gm_smmu_valid, gm_cb_read};
                result = rf_gc_snapshot_run(&ops, global, &snapshot);
            }
        }
    }
    printf("REDFIN GPU CONTEXT: result=%d stage=%u reads=%u completed=%u stable=%u disabled=%#x faults=%#x changed=%u/%#x; no writes/ownership\n",
        result, snapshot.stage, snapshot.reads, context->cb_reads, snapshot.stable,
        snapshot.disabled_mask, snapshot.fault_mask, snapshot.changed_bank, snapshot.changed_offset);
    for (unsigned bank = 0; bank < RF_GC_BANKS; bank++) {
        const uint32_t *w = snapshot.words[bank];
        printf("REDFIN GPU CONTEXT BANK: bank=%u SCTLR=%#x TCR2=%#x TTBR0=%#x/%#x TCR=%#x CONTEXTID=%#x MAIR=%#x/%#x FSR=%#x FAR=%#x/%#x FSYNR=%#x\n",
            bank, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8], w[9], w[10], w[11]);
    }
    if (!result && context->smmu_mode >= 3) result = gm_memory_run(context, global, &snapshot);
    if (!result && context->smmu_mode >= 4) result = gm_start_run(context);
    if (!result && context->smmu_mode >= 5) result = gx_run(context);
    return result;
}

static int
gm_smmu_run(struct gm_context *context, const struct rf_gt_report *gmu)
{
    struct rf_gs_snapshot snapshot = {0};
    int result = EPERM;
    if (!gmu->error && gmu->stage == RF_GT_DONE && gmu->reset_held && gmu->source_200m &&
        gmu->counter_live && gmu->dtcm_restored && !gmu->dtcm_dirty) {
        context->smmu_ready = true;
        printf("REDFIN SMMU STEP: fresh GMU DONE; recheck held parent/source/reset/IRQs\n");
        if (!gm_smmu_valid(context)) {
            result = ECANCELED;
        } else {
            context->smmu = ml_io_map(RF_GS_PHYS, RF_GS_BYTES / 2);
            if (!context->smmu) {
                result = ENOMEM;
            } else {
                const struct rf_gs_ops ops = {context, gm_smmu_valid, gm_smmu_read};
                result = rf_gs_snapshot_run(&ops, gm_chip, &snapshot);
            }
        }
    }
    printf("REDFIN SMMU: result=%d stage=%u guard=%u reads=%u completed=%u stable=%u format=%u changed=%#x; no CB/write/table ownership\n",
        result, snapshot.stage, context->smmu_guard, snapshot.reads, context->smmu_reads,
        snapshot.stable, snapshot.map_format_supported, snapshot.changed_offset);
    printf("REDFIN SMMU IDS: complete=%u IDR=%#x/%#x/%#x/%#x page=%#x global=%#x streams=%u contexts=%u stage2=%u bits=%u/%u/%u/%u\n",
        context->smmu_reads >= 4, snapshot.id0, snapshot.id1, snapshot.id2, snapshot.id7,
        snapshot.page_bytes, snapshot.global_bytes, snapshot.streams, snapshot.contexts,
        snapshot.stage2_contexts, snapshot.sid_bits, snapshot.input_bits,
        snapshot.output_bits, snapshot.virtual_bits);
    if (snapshot.stage >= 3) {
        printf("REDFIN SMMU GLOBAL: first-pass CR0=%#x GFSR=%#x syndrome=%#x/%#x/%#x\n",
            snapshot.control, snapshot.fault, snapshot.syndrome[0], snapshot.syndrome[1], snapshot.syndrome[2]);
        for (unsigned i = 0; i < snapshot.streams && i < RF_GS_MAX_STREAMS; i++)
            printf("REDFIN SMMU ROUTE: first-pass slot=%u SMR=%#x S2CR=%#x\n", i, snapshot.smr[i], snapshot.s2cr[i]);
        for (unsigned i = 0; i < snapshot.contexts && i < RF_GS_MAX_CONTEXTS; i++)
            printf("REDFIN SMMU GR1: first-pass bank=%u CBAR=%#x CBA2R=%#x\n", i, snapshot.cbar[i], snapshot.cba2r[i]);
    }
    if (snapshot.stable)
        printf("REDFIN SMMU ANALYSIS: stream4=%u/%u stream5=%u/%u unreferenced=%#x malformed=%u; unreferenced is not owned\n",
            snapshot.gmu_matches[0], snapshot.gmu_slot[0], snapshot.gmu_matches[1], snapshot.gmu_slot[1],
            snapshot.unreferenced_mask, snapshot.malformed_routes);
    if (!result && context->smmu_mode >= 2)
        result = gm_cb_run(context, &snapshot);
    return result;
}

int
redfin_gmu_probe(const char *frozen_args, unsigned args_bytes,
    void *held_cx_context, redfin_gmu_parent_valid_fn held_cx_valid)
{
    static struct gm_context context;
    struct rf_gt_report report = {0};
    int result;
    if (__atomic_exchange_n(&gm_attempted, true, __ATOMIC_ACQ_REL))
        return EBUSY;
    memset(&context, 0, sizeof(context));
    result = redfin_gmu_probe_contract(frozen_args, args_bytes);
    if (result)
        return result;
    if (!held_cx_context || !held_cx_valid)
        return EINVAL;
    context.parent_args = frozen_args;
    context.parent_context = held_cx_context;
    context.parent_valid = held_cx_valid;
    context.args_bytes = args_bytes;
    memcpy(context.args, frozen_args, args_bytes);
    if (!redfin_gmu_boot_args_mode(frozen_args, args_bytes, &context.smmu_mode))
        return ENOTSUP;
    context.smmu_requested = context.smmu_mode != 0;
    context.active = true;
    if (!gm_contract(&context, context.smmu_mode) || !gm_valid(&context))
        return EPERM;
    context.base[RF_GT_GCC] = ml_io_map(0x100000, 0x1f0000);
    if (!context.base[RF_GT_GCC])
        return ENOMEM;
    if (!gm_valid(&context))
        return EAGAIN;
    context.base[RF_GT_GPUCC] = ml_io_map(0x3d90000, 0x9000);
    if (!context.base[RF_GT_GPUCC])
        return ENOMEM;
    if (!gm_valid(&context))
        return EAGAIN;
    context.gic = ml_io_map(0x17a00000, 0x4000);
    if (!context.gic)
        return ENOMEM;
    if (!gm_valid(&context))
        return EAGAIN;
    context.base[RF_GT_GMU] = ml_io_map(0x3d6a000, 0x30000);
    if (!context.base[RF_GT_GMU])
        return ENOMEM;
    if (!gm_valid(&context))
        return EAGAIN;
    const struct rf_gt_ops ops = {&context, gm_valid, gm_read, gm_write, gm_delay, gm_time_ns};
    printf("REDFIN GMU STEP: clock preflight begins; CM3 release is forbidden\n");
    result = rf_gt_run(&ops, gm_chip, &report);
    if (!context.smmu_requested || result)
        context.active = false;
    printf("REDFIN GMU: result=%d stage=%u reads=%u writes=%u polls=%u source200=%u counter=%u restored=%u dirty=%u; no firmware/DMA/GX\n",
        result, report.stage, report.reads, report.writes, report.polls, report.source_200m,
        report.counter_live, report.dtcm_restored, report.dtcm_dirty);
    printf("REDFIN GMU CLOCK: MODE=%#x L=%#x USER=%#x ALPHA=%#x MISC=%#x source=%#x/%#x branch=%#x/%#x CX=%#x HW=%#x GX=%#x\n",
        report.pll_mode, report.pll_l, report.pll_user, report.pll_alpha, report.misc,
        report.source_before, report.source_after, report.gmu_clock_before,
        report.gmu_clock_after, report.cx, report.cx_hw, report.gx);
    printf("REDFIN GMU RESET: before=%#x after=%#x asserted=%u INIT=%#x HFI=%#x counter=%#x/%#x delta=%u elapsed-ns=%llu\n",
        report.reset_before, report.reset_after, report.reset_held, report.result_before,
        report.hfi_before, report.counter_before, report.counter_after, report.counter_delta,
        (unsigned long long)report.counter_elapsed_ns);
    printf("REDFIN GMU TCM: saved=%#x/%#x pattern=%#x/%#x restored=%#x/%#x\n",
        report.saved[0], report.saved[1], report.pattern_read[0], report.pattern_read[1],
        report.restored[0], report.restored[1]);
    if (context.smmu_requested && !result)
        result = gm_smmu_run(&context, &report);
    context.active = !result && context.smmu_mode==6 && redfin_gpu_ready();
    return result;
}

void redfin_gpu_gui_start(void)
{
    const char *args=PE_boot_args();unsigned bytes=0;
    if(!args)return;
    while(bytes<608 && args[bytes])bytes++;
    if(bytes==608 || !redfin_gpu_gui_profile(args,bytes+1,NULL))return;
    if(!redfin_gui_cpu0()) {printf("REDFIN GPU GUI: CPU0/root proof unavailable\n");return;}
    int error=redfin_gpu_power_probe();
    printf("REDFIN GPU GUI: complete startup result=%d runtime=%u\n",error,redfin_gpu_ready());
    if(!error && redfin_gpu_ready())RedfinGPUStart();
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
