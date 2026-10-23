/* SPDX-License-Identifier: MIT
 * Immutable boot-blob ingestion and guarded MPSS copy/readback. No device I/O,
 * power, SCM/PAS or filesystem interface is provided by this module.
 */
#ifndef REDFIN_WIFI_FW_SOURCE_H
#define REDFIN_WIFI_FW_SOURCE_H
#include "wifi_firmware.h"

#define RF_WIFI_FW_PAGE UINT64_C(16384)
#define RF_WIFI_FW_BOOT_ARGS_BYTES 736u
#define RF_WIFI_FW_MAX_ADT 0x200000u

enum rf_wifi_fw_error {
    RF_WIFI_FW_OK, RF_WIFI_FW_ARGUMENT, RF_WIFI_FW_LAYOUT, RF_WIFI_FW_STATE,
    RF_WIFI_FW_PLATFORM, RF_WIFI_FW_HASH, RF_WIFI_FW_PLAN, RF_WIFI_FW_CHANGED,
    RF_WIFI_FW_READBACK
};
enum rf_wifi_fw_stage {
    RF_WIFI_FW_IDLE, RF_WIFI_FW_PINNED, RF_WIFI_FW_VERIFIED,
    RF_WIFI_FW_METADATA, RF_WIFI_FW_SEGMENTS, RF_WIFI_FW_QUARANTINED,
    RF_WIFI_FW_CLOSED
};
struct rf_wifi_fw_blob {
    uint64_t physical, bytes, reserved, boot_id;
    uint8_t sha256[32];
};
struct rf_wifi_fw_layout {
    struct redfin_mpss_range ram, adt, arguments, ramdisk;
    uint64_t kernel_end, top;
};
struct rf_wifi_fw_source_ops {
    void *context;
    /* Native source lease: current worker/CPU and boot generation, exact
     * immutable boot data and mappings, with the full blob pinned read-only.
     * Host fixtures must instead own the entire backing storage. A DT flag or
     * raw reset boolean cannot establish native destination-write authority. */
    int (*check)(void *, const struct rf_wifi_fw_blob *, const struct rf_wifi_fw_layout *);
    /* Pin the exact reserved extent, including zero page padding. Failure
     * cleans its own partial acquisition. No fallback/remap/retry is allowed. */
    int (*pin)(void *, uint64_t physical, uint64_t reserved, const uint8_t **);
    /* Release only this session's read-only mapping, including cancellation. */
    void (*unpin)(void *);
    redfin_mpss_sha256_fn sha256;
};
struct rf_wifi_fw_copy_ops {
    void *context;
    /* Separate destination authority. Native implementation must prove the
     * same exclusive MPSS lease and appropriate PAS reset/INIT/MEM_SETUP state
     * for this phase; source ownership never grants an MPSS write lease.
     * This offline module does not query or change PAS state itself. */
    int (*check)(void *, const struct redfin_mpss_plan *, unsigned phase);
    /* Native callbacks supply the memory attributes and architecture/cache
     * barriers. read() must observe the actual destination, not a software
     * mirror; sync() must complete the required clean/publish before returning. */
    int (*write)(void *, uint64_t, const uint8_t *, uint32_t);
    int (*zero)(void *, uint64_t, uint32_t);
    int (*read)(void *, uint64_t, uint8_t *, uint32_t);
    int (*sync)(void *, uint64_t, uint64_t);
};
struct rf_wifi_fw_source {
    uint32_t attempted, stage, poisoned, pinned;
    int error, platform_error, planner_error;
    struct rf_wifi_fw_blob blob;
    struct rf_wifi_fw_layout layout;
    struct rf_wifi_fw_source_ops operations;
    const uint8_t *data;
    struct redfin_mpss_workspace *workspace;
    uint8_t workspace_sha256[32];
    uint64_t metadata_written, copied_bytes, zeroed_bytes, readback_bytes;
};

#ifdef __cplusplus
extern "C" {
#endif
int rf_wifi_fw_layout_valid(const struct rf_wifi_fw_blob *, const struct rf_wifi_fw_layout *);
/* One attempt. Uses the actual redfin_mpss_bundle_open() implementation, all
 * original PHDR indices, per-asset hashes and exact live exclusion list.
 * Workspace is new caller-owned unpublished memory, not a kernel stack item;
 * keep it pinned and unchanged for the entire source lease. */
int rf_wifi_fw_source_open(struct rf_wifi_fw_source *, const struct rf_wifi_fw_blob *,
    const struct rf_wifi_fw_layout *, const struct redfin_mpss_range *, size_t,
    struct redfin_mpss_workspace *, const struct rf_wifi_fw_source_ops *);
/* Staged copy mechanism for the real native platform manager: metadata first,
 * then segments only after the caller's independently proven PAS setup. Every
 * write/zero is bounded to 64KiB and read back before progress is published.
 * The 64KiB readback buffer is caller-owned private storage. No SMC is invoked. */
int rf_wifi_fw_copy_metadata(struct rf_wifi_fw_source *, const struct rf_wifi_fw_source_ops *,
    const struct rf_wifi_fw_copy_ops *, uint8_t *readback, size_t readback_bytes);
/* Separate source-backed PAS metadata scratch; the destination lease must
 * authorize its exact reserved extent. This grants no MPSS segment authority. */
int rf_wifi_fw_copy_metadata_to(struct rf_wifi_fw_source *, const struct rf_wifi_fw_source_ops *,
    const struct rf_wifi_fw_copy_ops *, uint64_t physical, uint8_t *readback, size_t readback_bytes);
int rf_wifi_fw_copy_segments(struct rf_wifi_fw_source *, const struct rf_wifi_fw_source_ops *,
    const struct rf_wifi_fw_copy_ops *, uint8_t *readback, size_t readback_bytes);
void rf_wifi_fw_source_close(struct rf_wifi_fw_source *, const struct rf_wifi_fw_source_ops *);
#ifdef __cplusplus
}
#endif
#endif
