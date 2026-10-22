/* SPDX-License-Identifier: MIT */
/* Exact md0/UP adapter for the separately proved, held-CX GMU TCM leaf. */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <machine/machine_routines.h>
#include "redfin_gmu_probe.h"
#include "redfin_gmu_tcm.h"

extern int redfin_spmi_return_ready(void);
extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
static bool gm_attempted;

struct gm_binding { const void *live, *expected; unsigned bytes; };
struct gm_context {
    vm_offset_t base[3], gic;
    const char *parent_args;
    void *parent_context;
    redfin_gmu_parent_valid_fn parent_valid;
    unsigned args_bytes;
    char args[608];
    struct gm_binding bindings[8];
    unsigned binding_count;
    bool active;
};

static const uint64_t gm_reg[] = {
    0x00100000, 0x1f0000, 0x03d90000, 0x9000,
    0x03d6a000, 0x30000, 0x17a00000, 0x4000
};
static const uint64_t gm_dram_base = 0x180000000ULL, gm_dram_size = 0x80000000ULL;
static const uint32_t gm_chip = 0x06020001;
static const uint32_t gm_clock[] = {200000000, 31, 0x4000, 2, 6, 2};
static const uint32_t gm_tcm[] = {1, 0x10004000, 0x7000, 2, 1, 1000};
static const uint32_t gm_parent[] = {0x30000, 64, 65535, 7, 416};
static const uint32_t gm_irqs[] = {336, 337};

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
    }
    return true;
}

static bool
gm_contract(struct gm_context *context)
{
    return gm_property(context, "/chosen", "dram-base", &gm_dram_base, sizeof(gm_dram_base)) &&
        gm_property(context, "/chosen", "dram-size", &gm_dram_size, sizeof(gm_dram_size)) &&
        gm_property(context, "/redfin-gmu", "reg", gm_reg, sizeof(gm_reg)) &&
        gm_property(context, "/redfin-gmu", "chip-id", &gm_chip, sizeof(gm_chip)) &&
        gm_property(context, "/redfin-gmu", "clock-policy", gm_clock, sizeof(gm_clock)) &&
        gm_property(context, "/redfin-gmu", "tcm-policy", gm_tcm, sizeof(gm_tcm)) &&
        gm_property(context, "/redfin-gmu", "cx-parent", gm_parent, sizeof(gm_parent)) &&
        gm_property(context, "/redfin-gmu", "interrupts", gm_irqs, sizeof(gm_irqs));
}

int
redfin_gmu_probe_contract(const char *frozen_args, unsigned args_bytes)
{
    const char *live = PE_boot_args();
    if (!redfin_gmu_args_valid(frozen_args, args_bytes) || !live ||
        memcmp(live, frozen_args, args_bytes))
        return ENOTSUP;
    return gm_contract(NULL) ? 0 : ENXIO;
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
        redfin_spmi_return_ready() != 1 || !context->parent_valid(context->parent_context))
        return false;
    for (unsigned i = 0; i < context->binding_count; i++) {
        const struct gm_binding *binding = &context->bindings[i];
        if (memcmp(binding->live, binding->expected, binding->bytes))
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
    }
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

int
redfin_gmu_probe(const char *frozen_args, unsigned args_bytes,
    void *held_cx_context, redfin_gmu_parent_valid_fn held_cx_valid)
{
    struct gm_context context = {0};
    struct rf_gt_report report = {0};
    int result;
    if (__atomic_exchange_n(&gm_attempted, true, __ATOMIC_ACQ_REL))
        return EBUSY;
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
    context.active = true;
    if (!gm_contract(&context) || !gm_valid(&context))
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
    result = rf_gt_run(&ops, gm_chip, &report);
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
    return result;
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
