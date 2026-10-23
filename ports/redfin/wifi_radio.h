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
