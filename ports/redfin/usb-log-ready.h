/* Unhooked USB logger readiness/critical-marker protocol. Pure CPU state only.
 * No USB, GPU, SMMU, thread, socket or boot-argument startup occurs here.
 * A future dedicated coordinator must retain live USB/return ownership and
 * independently enforce the GPU leaf's contract before every hardware access.
 */
#ifndef REDFIN_USB_LOG_READY_H
#define REDFIN_USB_LOG_READY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RF_ULR_BYTES 48u
#define RF_ULR_FRAME_BYTES 90u /* Ethernet14 + IPv4(no options)20 + UDP8 + payload48 */
#define RF_ULR_PORT 5141u
#define RF_ULR_HOST_IPV4 0xc0a80701u
#define RF_ULR_MAX_MARKERS 16u
#define RF_ULR_MAX_REJECTED 16u
#define RF_ULR_MAX_LEASE_NS UINT64_C(30000000000)
#define RF_ULR_HOST_TIMEOUT_NS UINT64_C(10000000000)
#define RF_ULR_MARKER_TIMEOUT_NS UINT64_C(500000000)

enum rf_ulr_kind { RF_ULR_HELLO = 1, RF_ULR_HELLO_ACK, RF_ULR_MARKER, RF_ULR_MARKER_ACK };
enum rf_ulr_operation { RF_ULR_READ32 = 1, RF_ULR_WRITE32 };
enum rf_ulr_phase { RF_ULR_EMPTY, RF_ULR_HELLO_TX, RF_ULR_HELLO_WAIT,
    RF_ULR_READY, RF_ULR_MARKER_TX, RF_ULR_MARKER_WAIT, RF_ULR_MARKER_ACKED, RF_ULR_FAILED };

struct rf_ulr_message {
    uint32_t kind, sequence;
    uint64_t boot_nonce, cookie, address;
    uint32_t operation, value;
};

/* The caller serializes these pure operations; never hold that lock while
 * sending, waiting or accessing MMIO. Completion/RX workers post bounded
 * receipts to the coordinator rather than waiting on a GPU operation.
 * Zero-initialize once; the owner, peer interface and lease last until reset.
 * Time is monotonic nanoseconds. lease_end is the existing gadget's deadline,
 * not a fresh lease. The core neither extends nor releases USB ownership. */
struct rf_ulr_session {
    uint64_t boot_nonce, cookie, lease_end, request_end, last_time;
    uint32_t phase, error, interface_index, markers, rejected;
    struct rf_ulr_message pending;
};

#ifdef __cplusplus
extern "C" {
#endif
int rf_ulr_encode(const struct rf_ulr_message *, uint8_t *, size_t);
int rf_ulr_decode(const uint8_t *, size_t, struct rf_ulr_message *);
int rf_ulr_begin(struct rf_ulr_session *, uint64_t boot_nonce, uint64_t cookie,
    uint32_t owned_interface_index, uint64_t now, uint64_t existing_lease_end,
    uint8_t message[RF_ULR_BYTES]);
int rf_ulr_poll(struct rf_ulr_session *, uint64_t now);
int rf_ulr_marker(struct rf_ulr_session *, uint64_t address, uint32_t operation,
    uint32_t value, uint64_t now, uint8_t message[RF_ULR_BYTES]);

/* Only the owned DWC3 event worker may supply this receipt, after matching
 * the pending control packet, a successful EP_TX XferComplete, HWO clear,
 * successful TRB status and zero residual length for the complete frame.
 * sock_send success, ud.tx_frames and ud.tx_busy=false are insufficient.
 * This is a trusted transport callback, not a boolean from a boot argument. */
int rf_ulr_tx_completed(struct rf_ulr_session *, const uint8_t *, size_t,
    uint32_t completed_frame_bytes, int completion_error, uint64_t now);

/* The dedicated RX adapter supplies checksum-validated UDP payload and actual
 * receive-interface metadata. Other destination ports return ENOMSG without
 * touching state; the existing ARP/ICMP/UDP5140 path remains unchanged. */
int rf_ulr_ack(struct rf_ulr_session *, uint32_t receive_interface_index,
    uint32_t source_ipv4, uint16_t source_port, uint16_t destination_port,
    const uint8_t *, size_t, uint64_t now);
bool rf_ulr_listener_ready(struct rf_ulr_session *, uint64_t now);

/* Consume exactly one matching, completed and host-acknowledged marker.
 * This is delivery evidence only. It never authorizes or invokes GPU MMIO. */
int rf_ulr_take_marker(struct rf_ulr_session *, uint64_t address,
    uint32_t operation, uint32_t value, uint64_t now);
void rf_ulr_abort(struct rf_ulr_session *, int error);
#ifdef __cplusplus
}
#endif
#endif
