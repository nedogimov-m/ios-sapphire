/* SPDX-License-Identifier: MIT */
/* The serialized native radio owner selects its identity once, before vdev
 * creation and before publishing en0. The same owner publishes WLAN afterward.
 * No network names, credentials or address bytes are logged. */
static unsigned char redfin_station_identity[6];
static int redfin_station_identity_source;
static bool redfin_station_identity_attempted;

extern "C" int RedfinWiFiCopyStationAddress(uint8_t address[6]);
extern "C" int RedfinWiFiCopyStationAddress(uint8_t address[6])
{
    if(!address)return -1;
    if(!redfin_station_identity_attempted) {
        redfin_station_identity_attempted=true;
        IORegistryEntry *chosen=IORegistryEntry::fromPath("IODeviceTree:/chosen");
        OSData *data=chosen?OSDynamicCast(OSData,chosen->getProperty(RF_WIFI_IDENTITY_PROPERTY)):NULL;
        if(data) {
            data->retain();
            unsigned source=rf_wifi_identity_decode((const volatile unsigned char *)data->getBytesNoCopy(),
                data->getLength(),redfin_station_identity);
            chosen->removeProperty(RF_WIFI_IDENTITY_PROPERTY);
            bool removed=chosen->getProperty(RF_WIFI_IDENTITY_PROPERTY)==NULL;
            redfin_station_identity_source=source&&removed?(int)source:-1;
            data->release();
        } else if(chosen&&chosen->getProperty(RF_WIFI_IDENTITY_PROPERTY)) {
            chosen->removeProperty(RF_WIFI_IDENTITY_PROPERTY);redfin_station_identity_source=-1;
        }
        if(chosen)chosen->release();
        IOLog("REDFIN WIFI STATION IDENTITY: supplied=%u accepted=%u source=%u no-address-logged=1\n",
            redfin_station_identity_source!=0,redfin_station_identity_source>0,
            redfin_station_identity_source>0?(unsigned)redfin_station_identity_source:0);
    }
    if(redfin_station_identity_source>0)
        memcpy(address,redfin_station_identity,sizeof(redfin_station_identity));
    return redfin_station_identity_source;
}
