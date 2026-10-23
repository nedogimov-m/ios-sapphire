/* SPDX-License-Identifier: MIT
 * The preferred HackiOS kernel 8e61187098f2c26c5daee8f9f72b6416aa64b9ab
 * redwood_image.c/redwood_wifi.c use firmware in a resident boot image. Redfin
 * uses a dedicated flat segment, avoiding another filesystem and heap copy.
 * Only source RAM is mapped read-only. No UFS, MPSS mapping, SCM/PAS or startup.
 */
#include <pexpert/arm64/board_config.h>
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <pexpert/arm64/boot.h>
#include <mach/vm_param.h>
#include <machine/machine_routines.h>
#include <kern/thread.h>
#include <sys/errno.h>
#include "redfin_wifi_fw_boot.h"

extern "C" int redfin_spmi_return_ready(void);
extern "C" int redfin_mpss_kernel_sha256(void *, const uint8_t *, size_t, uint8_t[32]);
static_assert(sizeof(boot_args) == RF_WIFI_FW_BOOT_ARGS_BYTES, "Redfin boot-args ABI");

static bool fw_property(DTEntry node, const char *key, void *out, unsigned expected)
{
    const void *raw = NULL;
    unsigned bytes = 0;
    if (SecureDTGetProperty(node, key, &raw, &bytes) != kSuccess || !raw || bytes != expected) return false;
    memcpy(out, raw, bytes); return true;
}
static bool fw_identity(void)
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
static bool fw_profile(uint64_t *boot_id)
{
    int cpus = 0, spmi = 0, returned = 0;
    char root[16] = {};
    if (!fw_identity() || !PE_parse_boot_argn("cpus", &cpus, sizeof(cpus)) || cpus != 1 ||
        !PE_parse_boot_argn("rd", root, sizeof(root)) || root[15] || strcmp(root, "md0") ||
        !PE_parse_boot_argn("redfinspmi", &spmi, sizeof(spmi)) || spmi != 1 ||
        !PE_parse_boot_argn("redfinreturn", &returned, sizeof(returned)) || returned != 1 ||
        !PE_parse_boot_argn("redfinbootid", boot_id, sizeof(*boot_id)) || !*boot_id) return false;
    const char *const disabled[] = {"modem", "wifi", "gpu", "sweetusb"};
    for (unsigned i = 0; i < sizeof(disabled) / sizeof(disabled[0]); ++i) {
        int value = -1;
        if (!PE_parse_boot_argn(disabled[i], &value, sizeof(value)) || value) return false;
    }
    return true;
}
static bool fw_handoff(rf_wifi_fw_blob *blob, rf_wifi_fw_layout *layout)
{
    const boot_args *args = (const boot_args *)PE_state.bootArgs;
    uint64_t reg[2] = {}, mapped[2] = {}, base = 0, bytes = 0;
    uint32_t contract[4] = {}, expected[4] = {1, 4, 16384, 0x10000000};
    DTEntry firmware, memory_map, chosen;
    if (!args || args->Revision != 2 || args->Version != 2 || args->memSizeActual != args->memSize ||
        !fw_profile(&blob->boot_id) ||
        SecureDTLookupEntry(NULL, "/redfin-wifi-fw", &firmware) != kSuccess ||
        !fw_property(firmware, "reg", reg, sizeof(reg)) ||
        !fw_property(firmware, "bundle-bytes", &blob->bytes, sizeof(blob->bytes)) ||
        !fw_property(firmware, "bundle-sha256", blob->sha256, sizeof(blob->sha256)) ||
        !fw_property(firmware, "source-contract", contract, sizeof(contract)) || memcmp(contract, expected, sizeof(contract)) ||
        SecureDTLookupEntry(NULL, "/chosen/memory-map", &memory_map) != kSuccess ||
        !fw_property(memory_map, "RedfinWiFiFirmware", mapped, sizeof(mapped)) || memcmp(mapped, reg, sizeof(reg)) ||
        SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        !fw_property(chosen, "dram-base", &base, sizeof(base)) || base != args->physBase ||
        !fw_property(chosen, "dram-size", &bytes, sizeof(bytes)) || bytes != args->memSize)
        return false;
    blob->physical = reg[0]; blob->reserved = reg[1];
    layout->ram = {base, bytes};
    uint64_t kernel_end = (uint64_t)ml_static_vtop(vm_kernel_top);
    if (!kernel_end || kernel_end > UINT64_MAX - (RF_WIFI_FW_PAGE - 1u)) return false;
    layout->kernel_end = (kernel_end + RF_WIFI_FW_PAGE - 1u) & ~(RF_WIFI_FW_PAGE - 1u);
    layout->adt = {(uint64_t)ml_static_vtop((vm_offset_t)args->deviceTreeP), args->deviceTreeLength};
    if (!redfin_mpss_valid_range(layout->adt.base, layout->adt.bytes) ||
        layout->adt.base + layout->adt.bytes > UINT64_MAX - 15u) return false;
    /* XNU arm_init copies the incoming boot_args into const_boot_args. Its
     * current address is therefore not the original reserved handoff address.
     * Derive that original extent from the validated SWEETXNU v1 layout. */
    layout->arguments = {(layout->adt.base + layout->adt.bytes + 15u) & ~UINT64_C(15), sizeof(boot_args)};
    layout->top = args->topOfKernelData;
    const void *raw = NULL;
    unsigned length = 0;
    if (SecureDTGetProperty(memory_map, "RAMDisk", &raw, &length) == kSuccess) {
        if (!raw || length != sizeof(layout->ramdisk)) return false;
        memcpy(&layout->ramdisk, raw, length);
    }
    return rf_wifi_fw_layout_valid(blob, layout) != 0;
}
static int fw_check(void *opaque, const rf_wifi_fw_blob *blob, const rf_wifi_fw_layout *layout)
{
    rf_wifi_fw_boot *boot = (rf_wifi_fw_boot *)opaque;
    rf_wifi_fw_blob fresh_blob = {};
    rf_wifi_fw_layout fresh_layout = {};
    bool valid = boot && boot->active && !boot->poisoned && boot->owner &&
        boot->workspace && boot->source.workspace == boot->workspace &&
        (void *)current_thread() == boot->owner && PE_state.bootArgs == boot->arguments &&
        !memcmp(PE_state.bootArgs, boot->boot_args, sizeof(boot->boot_args)) &&
        __builtin_arm_rsr64("CurrentEL") == 4 && !(__builtin_arm_rsr64("MPIDR_EL1") & UINT64_C(0xff00ffffff)) &&
        redfin_spmi_return_ready() == 1 && boot->policy.check &&
        !boot->policy.check(boot->policy.context, blob->boot_id) &&
        fw_handoff(&fresh_blob, &fresh_layout) && !memcmp(blob, &boot->native_blob, sizeof(*blob)) &&
        !memcmp(layout, &boot->native_layout, sizeof(*layout)) &&
        !memcmp(&fresh_blob, blob, sizeof(*blob)) && !memcmp(&fresh_layout, layout, sizeof(*layout));
    if (valid && boot->source.pinned) {
        IOMemoryMap *mapping = (IOMemoryMap *)boot->mapping;
        valid = mapping && mapping->getLength() == blob->reserved &&
            mapping->getVirtualAddress() == (uintptr_t)boot->source.data;
    }
    if (!valid && boot) boot->poisoned = 1;
    return valid ? 0 : EPERM;
}
static void fw_unpin(void *opaque)
{
    rf_wifi_fw_boot *boot = (rf_wifi_fw_boot *)opaque;
    IOMemoryMap *mapping = (IOMemoryMap *)boot->mapping;
    IOMemoryDescriptor *memory = (IOMemoryDescriptor *)boot->memory;
    boot->mapping = boot->memory = NULL;
    OSSafeReleaseNULL(mapping); OSSafeReleaseNULL(memory);
}
static int fw_pin(void *opaque, uint64_t physical, uint64_t reserved, const uint8_t **out)
{
    rf_wifi_fw_boot *boot = (rf_wifi_fw_boot *)opaque;
    if (!out || boot->memory || boot->mapping || physical != boot->native_blob.physical ||
        reserved != boot->native_blob.reserved || fw_check(boot, &boot->native_blob, &boot->native_layout)) return EPERM;
    IOMemoryDescriptor *memory = IOMemoryDescriptor::withPhysicalAddress(physical, reserved, kIODirectionIn);
    boot->memory = memory;
    IOMemoryMap *mapping = memory ? memory->map(kIOMapReadOnly | kIOMapDefaultCache) : NULL;
    boot->mapping = mapping;
    if (!mapping || !mapping->getVirtualAddress() || mapping->getLength() != reserved) { fw_unpin(boot); return ENOMEM; }
    *out = (const uint8_t *)mapping->getVirtualAddress(); return 0;
}
static int fw_sha256(void *opaque, const uint8_t *data, size_t bytes, uint8_t digest[32])
{
    rf_wifi_fw_boot *boot = (rf_wifi_fw_boot *)opaque;
    int error = fw_check(boot, &boot->native_blob, &boot->native_layout);
    if (!error) error = redfin_mpss_kernel_sha256(NULL, data, bytes, digest);
    return error ? error : fw_check(boot, &boot->native_blob, &boot->native_layout);
}

extern "C" int redfin_wifi_fw_boot_open(rf_wifi_fw_boot *boot, redfin_mpss_workspace *workspace,
    const rf_wifi_fw_boot_policy *policy)
{
    if (!boot || !workspace || !policy || !policy->check || !policy->excluded ||
        policy->exclusions < 2 || policy->exclusions > REDFIN_MPSS_MAX_EXCLUSIONS) return RF_WIFI_FW_ARGUMENT;
    uintptr_t owner = (uintptr_t)boot, scratch = (uintptr_t)workspace;
    if (owner > UINTPTR_MAX - sizeof(*boot) || scratch > UINTPTR_MAX - sizeof(*workspace) ||
        (owner < scratch + sizeof(*workspace) && scratch < owner + sizeof(*boot))) return RF_WIFI_FW_ARGUMENT;
    if (boot->attempted) return RF_WIFI_FW_STATE;
    boot->attempted = 1;
    if (!fw_handoff(&boot->native_blob, &boot->native_layout)) return RF_WIFI_FW_LAYOUT;
    boot->policy = *policy;
    memcpy(boot->excluded, policy->excluded, policy->exclusions * sizeof(*policy->excluded));
    boot->policy.excluded = boot->excluded;
    boot->owner = (void *)current_thread(); boot->arguments = PE_state.bootArgs; boot->workspace = workspace;
    memcpy(boot->boot_args, PE_state.bootArgs, sizeof(boot->boot_args));
    boot->source_ops = {boot, fw_check, fw_pin, fw_unpin, fw_sha256};
    boot->active = 1;
    int error = rf_wifi_fw_source_open(&boot->source, &boot->native_blob, &boot->native_layout,
        boot->excluded, boot->policy.exclusions, workspace, &boot->source_ops);
    if (error) { boot->active = 0; boot->poisoned = 1; }
    return error;
}
extern "C" void redfin_wifi_fw_boot_close(rf_wifi_fw_boot *boot)
{
    if (!boot) return;
    rf_wifi_fw_source_close(&boot->source, &boot->source_ops);
    boot->active = 0;
}

struct fw_probe_context {
    rf_wifi_fw_boot boot;
    redfin_mpss_workspace workspace;
    redfin_mpss_range excluded[REDFIN_MPSS_MAX_EXCLUSIONS];
    char args[608];
    uint64_t nonce;
    thread_t owner;
    unsigned bytes, exclusions;
    bool active, poisoned;
};
static fw_probe_context fw_probe;
static uint32_t fw_probe_attempted;

static bool fw_probe_args(const char *args, unsigned bytes, uint64_t *nonce_out, unsigned mode = 1)
{
    if (mode != 1 && mode != 2) return false;
    const char *const required[] = {
        "debug=0xc", "serial=3", "cpus=1", "keepsyms=1", "-noprogress", "rd=md0",
        "sweettouch=0", "sweetkeys=0", "sweetusb=0", "sweetcpufreq=0", "sweetbattery=0",
        "modem=0", "wifi=0", "gpu=0", "redfinwifi=2", "redfinwifinative=1",
        mode == 1 ? "redfinwififw=1" : "redfinwififw=2", "redfinspmi=1", "redfinreturn=1"};
    uint32_t seen = 0;
    uint64_t nonce = 0;
    bool nonce_seen = false, trace_seen = false;
    if (!args || !bytes || bytes > sizeof(fw_probe.args) || args[bytes - 1]) return false;
    for (unsigned at = 0; at < bytes - 1;) {
        if (args[at] == ' ') { ++at; continue; }
        unsigned first = at;
        while (at < bytes - 1 && args[at] != ' ') {
            if ((unsigned char)args[at] < 33 || (unsigned char)args[at] > 126) return false;
            ++at;
        }
        unsigned length = at - first;
        bool known = false;
        for (unsigned i = 0; i < sizeof(required) / sizeof(required[0]); ++i) {
            if (strlen(required[i]) != length || memcmp(args + first, required[i], length)) continue;
            if (seen & (1u << i)) return false;
            seen |= 1u << i; known = true; break;
        }
        if (known) continue;
        if (length == sizeof("-enable_kprintf_spam") - 1 &&
            !memcmp(args + first, "-enable_kprintf_spam", length)) {
            if (trace_seen) return false;
            trace_seen = true; continue;
        }
        if (length != 31 || memcmp(args + first, "redfinbootid=0x", 15) || nonce_seen) return false;
        for (unsigned i = 15; i < 31; ++i) {
            unsigned digit = (unsigned)(args[first + i] - '0');
            if (digit > 9) {
                if (args[first + i] < 'a' || args[first + i] > 'f') return false;
                digit = (unsigned)(args[first + i] - 'a' + 10);
            }
            nonce = (nonce << 4) | digit;
        }
        if (!nonce) return false;
        nonce_seen = true;
    }
    if (!nonce_seen || seen != ((1u << (sizeof(required) / sizeof(required[0]))) - 1u)) return false;
    if (nonce_out) *nonce_out = nonce;
    return true;
}

static bool fw_probe_properties(fw_probe_context *context, bool capture)
{
    DTEntry node;
    uint32_t contract[4] = {}, expected[4] = {1, 4, REDFIN_MPSS_MAX_EXCLUSIONS, 0};
    const void *raw = NULL;
    unsigned bytes = 0;
    if (SecureDTLookupEntry(NULL, "/redfin-wifi-fw", &node) != kSuccess ||
        !fw_property(node, "probe-contract", contract, sizeof(contract)) ||
        memcmp(contract, expected, sizeof(expected)) ||
        SecureDTGetProperty(node, "probe-exclusions", &raw, &bytes) != kSuccess ||
        !raw || bytes % sizeof(redfin_mpss_range) ||
        bytes < 2 * sizeof(redfin_mpss_range) || bytes > sizeof(context->excluded)) return false;
    if (!capture)
        return bytes == context->exclusions * sizeof(redfin_mpss_range) &&
            !memcmp(raw, context->excluded, bytes);
    memcpy(context->excluded, raw, bytes);
    context->exclusions = bytes / sizeof(redfin_mpss_range);
    bool kernel = false, display = false;
    const redfin_mpss_range mpss = {REDFIN_MPSS_BASE, REDFIN_MPSS_BYTES};
    for (unsigned i = 0; i < context->exclusions; ++i) {
        const redfin_mpss_range *range = &context->excluded[i];
        if (!redfin_mpss_valid_range(range->base, range->bytes) ||
            redfin_mpss_intersects(range->base, range->bytes, mpss.base, mpss.bytes)) return false;
        kernel |= range->base == UINT64_C(0x180000000) && range->bytes == UINT64_C(0x80000000);
        display |= range->base == UINT64_C(0xa0000000) && range->bytes == UINT64_C(0x2300000);
    }
    return kernel && display;
}

static int fw_probe_check(void *opaque, uint64_t boot_id)
{
    fw_probe_context *context = (fw_probe_context *)opaque;
    const char *live = PE_boot_args();
    bool valid = context == &fw_probe && context->active && !context->poisoned &&
        live && context->bytes && boot_id == context->nonce &&
        current_thread() == context->owner && redfin_spmi_return_ready() == 1 &&
        __builtin_arm_rsr64("CurrentEL") == 4 &&
        !(__builtin_arm_rsr64("MPIDR_EL1") & UINT64_C(0xff00ffffff)) &&
        !memcmp(live, context->args, context->bytes) && fw_probe_properties(context, false);
    if (context == &fw_probe && !valid) context->poisoned = true;
    return valid ? 0 : ECANCELED;
}

extern "C" void redfin_wifi_fw_source_probe(void)
{
    if (__atomic_exchange_n(&fw_probe_attempted, 1, __ATOMIC_RELAXED)) return;
    fw_probe_context *context = &fw_probe;
    const char *args = PE_boot_args();
    unsigned bytes = 0;
    if (args) while (bytes < sizeof(context->args) && args[bytes]) ++bytes;
    if (!args || bytes == sizeof(context->args) ||
        !fw_probe_args(args, bytes + 1, &context->nonce) ||
        !fw_probe_properties(context, true)) {
        IOLog("REDFIN WIFI FW: refused exact source-probe args/exclusions before mapping\n");
        return;
    }
    memcpy(context->args, args, bytes + 1); context->bytes = bytes + 1;
    context->owner = current_thread(); context->active = true;
    const rf_wifi_fw_boot_policy policy = {
        context, fw_probe_check, context->excluded, context->exclusions};
    IOLog("REDFIN WIFI FW: native resident source preflight begins; no destination/PAS/start\n");
    int error = redfin_wifi_fw_boot_open(&context->boot, &context->workspace, &policy);
    if (!error) error = fw_probe_check(context, context->nonce);
    const struct redfin_mpss_plan *plan = &context->workspace.plan;
    IOLog("REDFIN WIFI FW: result=%d stage=%u pinned=%u bytes=%llu PHDR=%u loads=%u assets=%u payload=%llu BSS=%llu; source-only\n",
        error, context->boot.source.stage, context->boot.source.pinned,
        (unsigned long long)context->boot.native_blob.bytes, plan->phdrs, plan->segments,
        context->workspace.image.assets, (unsigned long long)plan->file_bytes,
        (unsigned long long)plan->zero_bytes);
    redfin_wifi_fw_boot_close(&context->boot);
    context->active = false;
}
#include "redfin_wifi_fw_start.inc"
#endif
