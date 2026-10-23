/* SPDX-License-Identifier: MIT
 * Preferred HackiOS station/ifnet boundary over Redfin's native transport.
 * Only the native firmware worker services the radio. BSD/UI callers enqueue
 * scans/joins/frames through the station and packet engine's existing queues.
 */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <sys/kpi_mbuf.h>
#include <sys/redfin_wifi_net.h>
#include <sys/redfin_wifi_sta.h>
#include <sys/redfin_wifi_radio.h>

extern void (*topaz_wlan_rx_hook)(const uint8_t *, size_t);
extern void (*topaz_wlan_link_hook)(bool);
static struct redfin_sta_ops station;
static struct redfin_net_link link;
static unsigned published;
static bool leaving, linked;

static bool transmit(mbuf_t packet, size_t length)
{
    uint8_t frame[REDFIN_NET_FRAME_MAX];
    return length >= 14 && length <= sizeof(frame) && !mbuf_copydata(packet, 0, length, frame) &&
        redfin_wifi_radio_transmit(frame, length);
}
static int leave(void)
{
    leaving = true;
    return redfin_wifi_radio_leave();
}
static int join(const struct redfin_sta_join *what)
{
    leaving = false;
    return redfin_wifi_radio_join(what);
}
static int power(bool on)
{
    if (!on) leaving = true;
    return redfin_wifi_radio_power(on);
}
static void heard(void (*each)(const struct redfin_sta_bss *, void *), void *context)
{
    struct redfin_sta_bss one;
    for (unsigned i = 0; i < 64 && redfin_wifi_radio_heard(i, &one); ++i) each(&one, context);
}
static void link_changed(bool up)
{
    bool lost = linked && !up && !leaving;
    linked = up;
    redfin_net_link_state(up);
    if (lost) redfin_sta_lost(ECONNRESET);
}
void redfin_wifi_radio_network_ready(void)
{
    if (__atomic_exchange_n(&published, 1, __ATOMIC_ACQ_REL)) return;
    station.power = power;
    station.scan = redfin_wifi_radio_scan;
    station.heard = heard;
    station.join = join;
    station.leave = leave;
    station.state = redfin_wifi_radio_station_state;
    station.channels = redfin_wifi_radio_channels;
    redfin_wifi_radio_address(station.address);
    link.name = "Redfin WLAN"; link.wireless = true; link.up = false; link.transmit = transmit;
    memcpy(link.address, station.address, sizeof(link.address));
    topaz_wlan_rx_hook = redfin_net_input;
    topaz_wlan_link_hook = link_changed;
    redfin_sta_attach(&station);
    if (!redfin_net_attach(&link)) {
        printf("REDFIN WIFI: iOS network interface attach failed\n");
        redfin_sta_attach(NULL);
        topaz_wlan_rx_hook = NULL; topaz_wlan_link_hook = NULL;
    } else printf("REDFIN WIFI: native station, ifnet and Apple80211 provider published\n");
}
