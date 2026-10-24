/* SPDX-License-Identifier: MIT
 * Hardware boundary for the inherited ath10k-compatible station engine.
 * One native CPU0 worker owns all MMIO/DMA allocations. Other threads use
 * the station queue and Ethernet queue; they never enter these callbacks.
 */
#ifndef REDFIN_WIFI_RADIO_H
#define REDFIN_WIFI_RADIO_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
struct redfin_sta_scan;
struct redfin_sta_join;
struct redfin_sta_bss;
struct redfin_sta_state;
struct redfin_sta_channel;
/* Native Redfin mission: CE5 is the target/IPA OUT pipe. Firmware programs
 * its destination after HTT setup; APPS has no producer or RX queue there.
 * One table drives the software rings and the MMIO ownership checks. */
static const uint16_t redfin_wifi_ce_sources[12] = {16, 0, 0, 32, 2048, 0, 0, 2, 0, 0, 0, 0};
static const uint16_t redfin_wifi_ce_destinations[12] = {0, 512, 64, 0, 0, 0, 0, 2, 128, 512, 512, 512};
/* Native ath10k ce.h CE_DESC_ADDR_MASK: WCN3990 completion descriptors
 * carry address bits[34:0] separately from the upper control/metadata.
 * The CPU always uses its own posted-buffer pointer, never this field. */
#define REDFIN_WIFI_CE_DESC_ADDRESS UINT64_C(0x7ffffffff)
static inline bool redfin_wifi_mac_usable(const uint8_t address[6])
{
    return address && !(address[0] & 1u) &&
        (address[0] | address[1] | address[2] | address[3] | address[4] | address[5]);
}
static inline unsigned redfin_wifi_ce_receive_check(uint64_t reported, uint64_t posted,
    unsigned bytes, unsigned capacity)
{
    if (!bytes || bytes > capacity) return 1;
    if (!posted || (posted & ~REDFIN_WIFI_CE_DESC_ADDRESS) ||
        (reported & REDFIN_WIFI_CE_DESC_ADDRESS) != posted) return 2;
    return 0;
}
struct redfin_wifi_radio_ops {
    void *context;
    int (*check)(void *);
    void *(*allocate)(void *, uint64_t, uint64_t *);
    int (*read)(void *, uint32_t, uint32_t *);
    int (*write)(void *, uint32_t, uint32_t);
    int (*shadow)(void *, unsigned, uint32_t);
};
struct redfin_wifi_radio_state {
    unsigned htc, wmi, ready, scanning, phase, last_error;
    uint8_t ssid[32], ssid_length, bssid[6];
    uint16_t frequency;
    uint32_t received, transmitted;
};
#ifdef __cplusplus
extern "C" {
#endif
int redfin_wifi_radio_start(const struct redfin_wifi_radio_ops *);
int redfin_wifi_radio_poll(uint32_t milliseconds);
void redfin_wifi_radio_abandon(void);
void redfin_wifi_radio_state(struct redfin_wifi_radio_state *);
void redfin_wifi_radio_network_ready(void);
int redfin_wifi_radio_power(bool);
int redfin_wifi_radio_scan(const struct redfin_sta_scan *);
int redfin_wifi_radio_join(const struct redfin_sta_join *);
int redfin_wifi_radio_leave(void);
bool redfin_wifi_radio_heard(unsigned, struct redfin_sta_bss *);
void redfin_wifi_radio_station_state(struct redfin_sta_state *);
unsigned redfin_wifi_radio_channels(struct redfin_sta_channel *, unsigned);
void redfin_wifi_radio_address(uint8_t[6]);
bool redfin_wifi_radio_transmit(const uint8_t *, size_t);
#ifdef __cplusplus
}
#endif
#endif
