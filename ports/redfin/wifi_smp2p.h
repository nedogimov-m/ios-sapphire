/* SPDX-License-Identifier: MIT
 * Native Redfin APPS/MPSS SMP2P: allocation, fresh ready and acknowledged stop.
 * Hardware bindings remain the platform manager's responsibility.
 */
#ifndef REDFIN_WIFI_SMP2P_H
#define REDFIN_WIFI_SMP2P_H
#include <stddef.h>
#include <stdint.h>
#include "wifi_smem.h"

#define RF_WIFI_SMP2P_IN 435u
#define RF_WIFI_SMP2P_OUT 428u
#define RF_WIFI_SMP2P_BYTES 340u
#define RF_WIFI_SMP2P_PADDED 344u
#define RF_WIFI_SMP2P_WORDS (RF_WIFI_SMP2P_PADDED / 4u)
#define RF_WIFI_SMP2P_IPCC_ID 0x00020002u
#define RF_WIFI_SMP2P_TCSR_PHYSICAL UINT64_C(0x01f40000)
#define RF_WIFI_SMP2P_TCSR_BYTES 0x20000u
#define RF_WIFI_SMP2P_LOCK_OFFSET 0x3000u
#define RF_WIFI_SMP2P_LOCK_APPS 1u
#define RF_WIFI_SMP2P_MAX_READY_MS 10000u
#define RF_WIFI_SMP2P_MAX_STOP_MS 1000u

enum rf_wifi_smp2p_error {
    RF_WIFI_SMP2P_OK, RF_WIFI_SMP2P_ARGUMENT, RF_WIFI_SMP2P_PLATFORM,
    RF_WIFI_SMP2P_SMEM, RF_WIFI_SMP2P_BUSY, RF_WIFI_SMP2P_SPACE,
    RF_WIFI_SMP2P_STATE, RF_WIFI_SMP2P_CHANGED, RF_WIFI_SMP2P_BAD_PEER,
    RF_WIFI_SMP2P_FATAL, RF_WIFI_SMP2P_RESTART, RF_WIFI_SMP2P_TIMEOUT,
    RF_WIFI_SMP2P_NOT_FOUND, RF_WIFI_SMP2P_UNSTABLE
};
enum rf_wifi_smp2p_stage {
    RF_WIFI_SMP2P_IDLE, RF_WIFI_SMP2P_PREPARING, RF_WIFI_SMP2P_PREPARED,
    RF_WIFI_SMP2P_ARMED, RF_WIFI_SMP2P_READY, RF_WIFI_SMP2P_WAIT_FAILED,
    RF_WIFI_SMP2P_STOPPING, RF_WIFI_SMP2P_STOPPED, RF_WIFI_SMP2P_QUARANTINED
};

struct rf_wifi_smp2p_ops {
    const volatile uint8_t *smem;
    size_t smem_bytes;
    void *context;
    /* A native MPSS lease pins exact SMEM/TCSR/IPCC mappings and CPU/thread,
     * excludes other APPS writers and binds PAS state to this same session.
     * Allocator ownership must serialize APPS threads and remain IRQ-safe.
     * During lock(), check() also verifies physical lock3 still belongs to
     * APPS1. No boot arg, SMEM absence or raw boolean can establish PAS state.
     */
    int (*check)(void *);
    int (*pas_reset)(void *);  /* Proven remote held in reset, not a guess. */
    int (*pas_started)(void *); /* This session's authenticated PAS4 succeeded. */
    int (*lock)(void *, uint32_t timeout_ms); /* Native TCSR lock3 only. */
    /* Always called once after a successful lock, including failures. It must
     * release only a physically verified APPS-owned lock, even on cancellation;
     * never unlock a foreign owner's mutex or leave our lock blocking recovery.
     */
    int (*unlock)(void *);
    int (*write32)(void *, uint32_t smem_offset, uint32_t value);
    int (*barrier)(void *); /* Publish uncached data/header before free/version. */
    int (*kick)(void *); /* IPCC client2/signal2 only; no receive IRQ clearing. */
    int (*now_ms)(void *, uint64_t *);
    int (*pause_us)(void *, uint32_t);
};

struct rf_wifi_smp2p_session {
    uint32_t remote_pid,bound_pid; /* zero/default1 MPSS; native ADSP/PAS1 host2 */
    uint32_t attempted, stage, poisoned, allocator_locked;
    int error, platform_error;
    uint32_t partition, partition_bytes, cacheline, entry, data;
    uint32_t hosts, version, toc_count, toc_entry, toc[12];
    uint32_t own[RF_WIFI_SMP2P_WORDS];
    uint32_t peer, peer_seen, peer_features, peer_restart, peer_valid;
    uint32_t slave_index, slave_found, last_state, handover;
    uint8_t names[16][16];
    uint32_t stores, kicks;
    uint32_t ipa_index, ipa_found, ipa_state, ipa_responses;
    /* Raw native WLAN notification entry; presence is separate from value0.
     * Recording it sends no reply and does not establish WLAN FW_READY. */
    uint32_t wlan_index, wlan_found, wlan_state;
};

#ifdef __cplusplus
extern "C" {
#endif
/* One cold attempt. Refuse existing 428/435 or cached allocation at preparation;
 * append only a new bounded 428 in the validated APPS/MODEM private partition.
 * Both master-kernel and ipa outbound entries come from the pinned Lito DT.
 */
/* Read-only cold-start witness before INIT/MEM_SETUP. This never claims reset
 * ownership, allocates or changes a session. Only successful native setup can
 * subsequently authorize destination RAM writes. */
int rf_wifi_smp2p_cold(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *);
int rf_wifi_smp2p_prepare(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *);
/* Called immediately before PAS AUTH, while pas_reset() remains provable. It
 * records inbound 435 absent again, so a later new ready object is fresh. */
int rf_wifi_smp2p_auth_begin(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *);
/* Called only after PAS AUTH success. Negotiate features/restart ACK once;
 * require new inbound 435 and ready, fail on fatal or any later remote restart.
 * A timeout permits only the bounded shutdown path, not another ready attempt.
 */
int rf_wifi_smp2p_wait_ready(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *, uint32_t timeout_ms);
/* Read-only continuing liveness/identity check for this established session. */
int rf_wifi_smp2p_alive(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *);
/* Respond to a fresh native IPA bit0 query with this port's absent APPS IPA
 * clock vote (complete=1,vote=0). This does not report aggregate hardware power. */
int rf_wifi_smp2p_ipa_respond(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *);
/* Require stop-ack low before setting only master-kernel bit0, then a fresh
 * high ACK. Clear our stop bit only after that ACK; timeout retains it and
 * quarantines. PAS shutdown is the caller's next step after success. */
int rf_wifi_smp2p_stop(struct rf_wifi_smp2p_session *, const struct rf_wifi_smp2p_ops *, uint32_t timeout_ms);
#ifdef __cplusplus
}
#endif
#endif
