/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_WIFI_IDENTITY_H
#define REDFIN_WIFI_IDENTITY_H
#include <stdint.h>
#include <stddef.h>
#define RF_WIFI_IDENTITY_PROPERTY "redfin-wifi-identity"
#define RF_WIFI_IDENTITY_BYTES 16u
enum {RF_WIFI_IDENTITY_FACTORY=1,RF_WIFI_IDENTITY_LOCAL=2};

/* A local address is generated once by the private host identity provider,
 * never from a boot nonce or by the radio's per-boot random fallback. */
static inline unsigned rf_wifi_identity_decode(const volatile unsigned char *data,size_t bytes,
    unsigned char address[6])
{
    if(!data||bytes!=RF_WIFI_IDENTITY_BYTES||data[0]!=1||data[1]||data[2]||data[3]||
       (data[4]!=RF_WIFI_IDENTITY_FACTORY&&data[4]!=RF_WIFI_IDENTITY_LOCAL)||
       data[5]||data[6]||data[7]||data[14]||data[15]||(data[8]&1))return 0;
    unsigned any=0;for(unsigned i=8;i<14;++i)any|=data[i];
    if(!any||(data[4]==RF_WIFI_IDENTITY_LOCAL&&!(data[8]&2)))return 0;
    if(address)for(unsigned i=0;i<6;++i)address[i]=data[8+i];
    return data[4];
}
#endif
