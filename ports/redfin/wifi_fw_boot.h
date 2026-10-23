/* SPDX-License-Identifier: MIT
 * Optional native boot-blob source. No startup hook or destination access.
 */
#ifndef REDFIN_WIFI_FW_BOOT_H
#define REDFIN_WIFI_FW_BOOT_H
#include "wifi_fw_source.h"

struct rf_wifi_fw_boot_policy {
    void *context;
    /* Actual platform worker lease, not a host/DT marker. Must remain failed
     * after loss and bind the same freshly validated live exclusion set. */
    int (*check)(void *, uint64_t boot_id);
    const struct redfin_mpss_range *excluded;
    size_t exclusions;
};
/* Allocate in the platform worker's private context, never on the entry stack.
 * Workspace and 64KiB readback storage are separately caller-owned. */
struct rf_wifi_fw_boot {
    struct rf_wifi_fw_source source;
    struct rf_wifi_fw_source_ops source_ops;
    struct rf_wifi_fw_boot_policy policy;
    struct redfin_mpss_range excluded[REDFIN_MPSS_MAX_EXCLUSIONS];
    struct rf_wifi_fw_blob native_blob;
    struct rf_wifi_fw_layout native_layout;
    struct redfin_mpss_workspace *workspace;
    void *memory, *mapping, *owner, *arguments;
    uint8_t boot_args[RF_WIFI_FW_BOOT_ARGS_BYTES];
    uint32_t attempted, active, poisoned;
};
#ifdef __cplusplus
extern "C" {
#endif
int redfin_wifi_fw_boot_open(struct rf_wifi_fw_boot *, struct redfin_mpss_workspace *,
    const struct rf_wifi_fw_boot_policy *);
void redfin_wifi_fw_boot_close(struct rf_wifi_fw_boot *);
/* Separate exact CPU0/md0 probe: validate/pin/hash/parse source, then close.
 * No destination mapping, PAS, power, SMEM or firmware start. */
void redfin_wifi_fw_source_probe(void);
/* Separate native PAS4 startup. Requires the exact firmware/power/bus contract. */
void redfin_wifi_fw_start(void);
#ifdef __cplusplus
}
#endif
#endif
