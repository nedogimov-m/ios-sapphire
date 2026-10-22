/* SPDX-License-Identifier: MIT
 * Native Redfin AOP QMP transport for PAS4 modem load-state messages.
 * No mapping, interrupt registration or startup hook is provided here.
 */
#ifndef REDFIN_WIFI_AOP_H
#define REDFIN_WIFI_AOP_H
#include <stdint.h>

#define RF_WIFI_AOP_PHYSICAL UINT64_C(0x0c300000)
#define RF_WIFI_AOP_BYTES 0x1000u
#define RF_WIFI_AOP_IPCC_PHYSICAL UINT64_C(0x00408000)
#define RF_WIFI_AOP_IPCC_SEND 0x0cu
#define RF_WIFI_AOP_IPCC_ID 0u /* AOP client0, QMP signal0. */
#define RF_WIFI_AOP_UP 0x0000ffffu
#define RF_WIFI_AOP_DOWN 0xffff0000u
#define RF_WIFI_AOP_MESSAGE_BYTES 64u
#define RF_WIFI_AOP_HANDSHAKE_MS 5000u
#define RF_WIFI_AOP_TX_MS 1000u

enum rf_wifi_aop_error {
    RF_WIFI_AOP_OK, RF_WIFI_AOP_ARGUMENT, RF_WIFI_AOP_PLATFORM,
    RF_WIFI_AOP_DESCRIPTOR, RF_WIFI_AOP_CHANGED, RF_WIFI_AOP_BUSY,
    RF_WIFI_AOP_STATE, RF_WIFI_AOP_TIMEOUT
};

struct rf_wifi_aop_snapshot {
    uint32_t word[16];
    uint32_t tx_length, rx_length;
};

struct rf_wifi_aop_session {
    struct rf_wifi_aop_snapshot baseline;
    uint32_t attempted, open, poisoned, load_state, stores, notifications;
    int error;
};

struct rf_wifi_aop_ops {
    void *context;
    /* Write entry points require a serialized, exclusive native AOP/QMP lease.
     * The read-only observer instead requires a live read-only mapping lease;
     * it never grants write ownership. The platform
     * validates live FDT/msgram/IPCC mappings, owner/generation and CPU/thread
     * binding, with other AOP clients quiesced. check() must remain failed after
     * ownership loss. A boot argument or host marker cannot establish a lease.
     * Each callback performs only the indicated bounded 32-bit operation and
     * the appropriate architecture barriers. No IRQ receive/clear registers
     * are needed: this transport polls its own descriptor and TX length.
     */
    int (*check)(void *);
    int (*read32)(void *, uint32_t msgram_offset, uint32_t *value);
    int (*write32)(void *, uint32_t msgram_offset, uint32_t value);
    int (*notify_aop)(void *); /* IPCC_SEND_ID = client0/signal0 only. */
    int (*pause_us)(void *, uint32_t microseconds);
};

#ifdef __cplusplus
extern "C" {
#endif
/* Read-only: check/read32 suffice. Two complete equal descriptor snapshots
 * are required. Payloads are not read; only the two bounded queue lengths. */
int rf_wifi_aop_observe(const struct rf_wifi_aop_ops *, struct rf_wifi_aop_snapshot *);
/* One open attempt per lease. Adopt a fully open idle mailbox without stores,
 * or negotiate from a coherent closed state. Partial/stale states fail. */
int rf_wifi_aop_open(struct rf_wifi_aop_session *, const struct rf_wifi_aop_ops *);
/* Exactly modem load_state on, then off, once each. No arbitrary QMP command.
 * Completion means AOP consumed the TX mailbox, not that MPSS is running.
 * Any failure poisons the session; no retry, message erasure or link rollback
 * can make an uncertain delivery appear successful. Keep the lease quarantined.
 */
int rf_wifi_aop_load_state(struct rf_wifi_aop_session *, const struct rf_wifi_aop_ops *, int on);
#ifdef __cplusplus
}
#endif
#endif
