/* SPDX-License-Identifier: MIT
 * Included by TopazModem.cpp after its packet/station functions. Only the
 * ath10k-compatible software engine is reused. Native Redfin owns firmware,
 * power, MMIO, memory and service lifetime through redfin_wifi_radio_ops.
 */
static struct redfin_wifi_wpa rf_station_wpa;
static bool rf_station_wpa_started, rf_radio_notified;
static uint8_t rf_last_m3[512], rf_last_m4[REDFIN_WIFI_WPA_REPLY_MOST + 14];
static unsigned rf_last_m3_bytes, rf_last_m4_bytes;
static struct redfin_wifi_radio_state rf_radio_snapshot;
static struct redfin_sta_state rf_station_snapshot;
static struct redfin_sta_bss rf_scan_snapshot[64];
static unsigned rf_scan_count, rf_scan_generation;
static unsigned rf_scan_snapshot_done;
static volatile bool rf_power_asked, rf_power_wanted;
static volatile unsigned rf_power_done;

static void rf_radio_wpa_reset(void)
{
    memset_s(&rf_station_wpa, sizeof(rf_station_wpa), 0, sizeof(rf_station_wpa));
    memset_s(rf_last_m3, sizeof(rf_last_m3), 0, sizeof(rf_last_m3));
    memset_s(rf_last_m4, sizeof(rf_last_m4), 0, sizeof(rf_last_m4));
    rf_station_wpa_started = false; rf_last_m3_bytes = rf_last_m4_bytes = 0;
}
static void rf_radio_station_eapol(const uint8_t *e, size_t length)
{
    uint8_t reply[REDFIN_WIFI_WPA_REPLY_MOST + 14] = {};
    unsigned reply_bytes = 0;
    const char *why = NULL;
    if ((s_state != S_4WAY && s_state != S_UP) || length < 14 + 4 || length > 14 + sizeof(rf_last_m3) ||
        memcmp(e + 6, s_bssid, 6) || e[12] != 0x88 || e[13] != 0x8e) return;
    if (rf_last_m3_bytes == length - 14 && rf_last_m4_bytes && !memcmp(rf_last_m3, e + 14, length - 14)) {
        /* Retransmit message4 without installing the same keys again. */
        (void)w_tx_ether(rf_last_m4, rf_last_m4_bytes, true);
        return;
    }
    if (s_state == S_UP && length >= 21 && !(e[19] & 1u)) return;
    if (!rf_station_wpa_started) {
        if (s_state != S_4WAY) return;
        bzero(&rf_station_wpa, sizeof(rf_station_wpa));
        memcpy(rf_station_wpa.pmk, s_pmk, 32);
        memcpy(rf_station_wpa.own, our_mac, 6); memcpy(rf_station_wpa.peer, s_bssid, 6);
        read_random(rf_station_wpa.own_nonce, 32);
        rf_station_wpa.rsn = s_rsn_ie; rf_station_wpa.rsn_length = sizeof(s_rsn_ie);
        rf_station_wpa_started = true;
    }
    int result = redfin_wifi_wpa_message(&rf_station_wpa, e + 14, (unsigned)length - 14,
        reply + 14, &reply_bytes, &why);
    if (result == REDFIN_WIFI_WPA_NOTHING) return;
    if (result == REDFIN_WIFI_WPA_BAD) {
        LOG("Redfin WPA2: rejected key message (%s)", why ? why : "invalid");
        if (s_state == S_4WAY) w_join_end(EAUTH);
        return;
    }
    memcpy(reply, s_bssid, 6); memcpy(reply + 6, our_mac, 6); reply[12] = 0x88; reply[13] = 0x8e;
    if (!w_tx_ether(reply, reply_bytes + 14u, true)) { w_join_end(EIO); return; }
    if (result == REDFIN_WIFI_WPA_ANSWER) {
        ++s_msg1s;
        return;
    }
    if (s_group_cipher != 4 || rf_station_wpa.group_length != 16) { w_join_end(EOPNOTSUPP); return; }
    bool accepted = true;
    if (result == REDFIN_WIFI_WPA_KEYS) accepted = w_install_key(false, 0, WMI_CIPHER_CCMP, rf_station_wpa.pairwise, 16);
    accepted = accepted && w_install_key(true, rf_station_wpa.group_index, WMI_CIPHER_CCMP,
        rf_station_wpa.group, rf_station_wpa.group_length, rf_station_wpa.group_counter);
    if (!accepted) { w_join_end(EIO); return; }
    if (result == REDFIN_WIFI_WPA_KEYS) {
        if (!w_peer_param(PEER_PARAM_AUTHORIZE, 1)) { w_join_end(EIO); return; }
        memcpy(rf_last_m3, e + 14, length - 14); rf_last_m3_bytes = (unsigned)length - 14;
        memcpy(rf_last_m4, reply, reply_bytes + 14u); rf_last_m4_bytes = reply_bytes + 14u;
        s_ptk_set = true; w_join_end(0);
    }
    memset_s(reply, sizeof(reply), 0, sizeof(reply));
}
static void rf_radio_snapshot_update(void)
{
    IOSimpleLockLock(rf_radio_status_lock);
    bzero(&rf_radio_snapshot, sizeof(rf_radio_snapshot));
    rf_radio_snapshot.htc = htc_ready; rf_radio_snapshot.wmi = wmi_ready;
    rf_radio_snapshot.ready = api_ready; rf_radio_snapshot.scanning = scanning;
    rf_radio_snapshot.phase = (unsigned)s_state; rf_radio_snapshot.last_error = (unsigned)s_result;
    rf_radio_snapshot.received = rx_up; rf_radio_snapshot.transmitted = tx_sent;
    rf_radio_snapshot.ssid_length = MIN(s_ssid_len, (uint8_t)32);
    memcpy(rf_radio_snapshot.ssid, s_ssid, rf_radio_snapshot.ssid_length);
    memcpy(rf_radio_snapshot.bssid, s_bssid, 6); rf_radio_snapshot.frequency = (uint16_t)s_freq;
    if (rf_scan_generation != scan_frames) {
        rf_scan_count = MIN(nbss, 64u);
        for (unsigned i = 0; i < rf_scan_count; ++i) {
            struct redfin_sta_bss *out = &rf_scan_snapshot[i];
            const struct bss *in = &bss[i];
            bzero(out, sizeof(*out));
            memcpy(out->bssid, in->bssid, 6); out->ssid_length = MIN(in->raw_ssid_len, (uint8_t)32);
            memcpy(out->ssid, in->raw_ssid, out->ssid_length); out->frequency = in->freq; out->rssi = in->rssi;
            out->beacon_interval = in->bintval; out->capability = in->capab; out->age_ms = g_ms - in->last_ms;
            out->elements_length = MIN(in->ie_len, (uint16_t)sizeof(in->ie));
            memcpy(out->elements, in->ie, out->elements_length);
        }
        rf_scan_generation = scan_frames;
    }
    bzero(&rf_station_snapshot, sizeof(rf_station_snapshot));
    rf_station_snapshot.phase = !rf_radio_enabled ? REDFIN_STA_OFF : s_state == S_UP ? REDFIN_STA_JOINED :
        s_state != S_IDLE ? REDFIN_STA_JOINING : scanning ? REDFIN_STA_SCANNING : REDFIN_STA_IDLE;
    rf_station_snapshot.last_error = s_result;
    if (s_state != S_IDLE) {
        for (unsigned i = 0; i < rf_scan_count; ++i)
            if (!memcmp(rf_scan_snapshot[i].bssid, s_bssid, 6)) { rf_station_snapshot.bss = rf_scan_snapshot[i]; break; }
        rf_station_snapshot.bss.ssid_length = rf_radio_snapshot.ssid_length;
        memcpy(rf_station_snapshot.bss.ssid, s_ssid, rf_radio_snapshot.ssid_length);
        memcpy(rf_station_snapshot.bss.bssid, s_bssid, 6); rf_station_snapshot.bss.frequency = (uint16_t)s_freq;
    }
    IOSimpleLockUnlock(rf_radio_status_lock);
    __atomic_store_n(&rf_scan_snapshot_done, api_scans_done, __ATOMIC_RELEASE);
}
extern "C" int redfin_wifi_radio_start(const struct redfin_wifi_radio_ops *ops)
{
    if (!ops || !ops->context || !ops->check || !ops->allocate || !ops->read || !ops->write || !ops->shadow ||
        ops->check(ops->context) || rf_radio_bus.context || pool || ce_up) return EPERM;
    rf_radio_status_lock = IOSimpleLockAlloc();
    if (!rf_radio_status_lock) return ENOMEM;
    rf_radio_bus = *ops; rf_radio_enabled = true;
    if (!ce_start() || rf_radio_error) return rf_radio_error ? rf_radio_error : EIO;
    rf_radio_snapshot_update();
    return 0;
}
extern "C" int redfin_wifi_radio_poll(uint32_t milliseconds)
{
    if (!rf_radio_bus.context || rf_radio_error || rf_radio_bus.check(rf_radio_bus.context)) return EIO;
    g_ms = milliseconds;
    if (__atomic_exchange_n(&rf_power_asked, false, __ATOMIC_ACQ_REL)) {
        bool on = __atomic_load_n(&rf_power_wanted, __ATOMIC_ACQUIRE);
        if (!on) { w_teardown(); api_scan_asked = false; next_scan_ms = 0; }
        rf_radio_enabled = on;
        if (on && api_ready) api_scan_asked = true;
        __atomic_add_fetch(&rf_power_done, 1, __ATOMIC_RELEASE);
    }
    radio_poll(milliseconds);
    rf_radio_snapshot_update();
    if (api_ready && !rf_radio_notified) { rf_radio_notified = true; redfin_wifi_radio_network_ready(); }
    return rf_radio_error;
}
extern "C" void redfin_wifi_radio_state(struct redfin_wifi_radio_state *out)
{
    if (!out) return;
    bzero(out, sizeof(*out));
    if (!rf_radio_status_lock) return;
    IOSimpleLockLock(rf_radio_status_lock); *out = rf_radio_snapshot; IOSimpleLockUnlock(rf_radio_status_lock);
}
extern "C" int redfin_wifi_radio_power(bool on)
{
    if (!rf_radio_bus.context || rf_radio_error) return ENXIO;
    unsigned before = __atomic_load_n(&rf_power_done, __ATOMIC_ACQUIRE);
    __atomic_store_n(&rf_power_wanted, on, __ATOMIC_RELEASE);
    __atomic_store_n(&rf_power_asked, true, __ATOMIC_RELEASE);
    for (unsigned i = 0; i < 200 && __atomic_load_n(&rf_power_done, __ATOMIC_ACQUIRE) == before; ++i) IOSleep(10);
    return __atomic_load_n(&rf_power_done, __ATOMIC_ACQUIRE) != before ? 0 : ETIMEDOUT;
}
extern "C" int redfin_wifi_radio_scan(const struct redfin_sta_scan *what)
{
    (void)what;
    if (!rf_radio_enabled) return ENETDOWN;
    int error = topaz_wlan_scan();
    if (error) return error;
    unsigned done = api_scans_done;
    for (unsigned i = 0; i < 100 && __atomic_load_n(&rf_scan_snapshot_done, __ATOMIC_ACQUIRE) != done; ++i) IOSleep(10);
    return __atomic_load_n(&rf_scan_snapshot_done, __ATOMIC_ACQUIRE) == done ? 0 : ETIMEDOUT;
}
extern "C" int redfin_wifi_radio_join(const struct redfin_sta_join *what)
{
    if (!what || !what->ssid_length || what->ssid_length > 32 || !rf_radio_enabled) return EINVAL;
    if (what->security == REDFIN_STA_OPEN) return topaz_wlan_join(what->ssid, what->ssid_length, what->bssid, NULL, 0);
    if (what->security != REDFIN_STA_WPA2_PSK) return EOPNOTSUPP;
    return what->passphrase_length ? topaz_wlan_join(what->ssid, what->ssid_length, what->bssid,
        what->passphrase, what->passphrase_length) : topaz_wlan_join_pmk(what->ssid, what->ssid_length, what->bssid, what->pmk);
}
extern "C" int redfin_wifi_radio_leave(void) { return topaz_wlan_leave(); }
extern "C" bool redfin_wifi_radio_heard(unsigned index, struct redfin_sta_bss *out)
{
    if (!out || !rf_radio_status_lock) return false;
    IOSimpleLockLock(rf_radio_status_lock);
    bool present = index < rf_scan_count; if (present) *out = rf_scan_snapshot[index];
    IOSimpleLockUnlock(rf_radio_status_lock); return present;
}
extern "C" void redfin_wifi_radio_station_state(struct redfin_sta_state *out)
{
    if (!out) return;
    bzero(out, sizeof(*out)); if (!rf_radio_status_lock) return;
    IOSimpleLockLock(rf_radio_status_lock); *out = rf_station_snapshot; IOSimpleLockUnlock(rf_radio_status_lock);
}
extern "C" unsigned redfin_wifi_radio_channels(struct redfin_sta_channel *out, unsigned most)
{
    unsigned count = MIN(most, NFREQ);
    if (!out) return 0;
    for (unsigned i = 0; i < count; ++i) {
        out[i].frequency = scan_freqs[i];
        out[i].flags = scan_freqs[i] >= 5260 && scan_freqs[i] <= 5700 ? REDFIN_STA_CHANNEL_PASSIVE | REDFIN_STA_CHANNEL_RADAR : 0;
    }
    return count;
}
extern "C" void redfin_wifi_radio_address(uint8_t out[6]) { if (out) topaz_wlan_address(out); }
extern "C" bool redfin_wifi_radio_transmit(const uint8_t *frame, size_t bytes)
{ return rf_radio_enabled && !rf_radio_error && topaz_wlan_transmit(frame, bytes); }
extern "C" void redfin_wifi_radio_abandon(void)
{
    rf_radio_error = EIO; rf_radio_enabled = false;
    rf_radio_wpa_reset();
    if (topaz_wlan_link_hook) topaz_wlan_link_hook(false);
    if (rf_radio_status_lock) {
        IOSimpleLockLock(rf_radio_status_lock);
        rf_station_snapshot.phase = REDFIN_STA_OFF; rf_station_snapshot.last_error = EIO;
        rf_radio_snapshot.last_error = EIO;
        IOSimpleLockUnlock(rf_radio_status_lock);
    }
}
