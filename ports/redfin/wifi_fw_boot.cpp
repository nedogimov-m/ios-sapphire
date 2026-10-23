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
#endif
