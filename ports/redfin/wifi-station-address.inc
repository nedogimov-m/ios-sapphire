/* SPDX-License-Identifier: MIT */
extern "C" int RedfinWiFiCopyStationAddress(uint8_t address[6]);
static bool redfin_radio_select_station(uint8_t address[6],const uint8_t firmware[6])
{
    int source=RedfinWiFiCopyStationAddress(address);
    if(source<0) {
        rf_radio_error=EINVAL;
        LOG("wmi: invalid supplied persistent station identity; native start refused");
        return false;
    }
    if(source>0) {
        LOG("wmi: persistent station identity selected source=%u",(unsigned)source);
        return true;
    }
    /* Older diagnostic profiles without the new private contract retain
     * their original behavior. Production images supply the stable identity. */
    if(redfin_wifi_mac_usable(firmware))memcpy(address,firmware,6);
    else {
        read_random(address,6);address[0]=(address[0]&0xfcu)|2u;
        LOG("wmi: using one per-boot locally administered station address");
    }
    return true;
}
