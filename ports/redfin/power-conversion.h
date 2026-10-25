/* SPDX-License-Identifier: GPL-2.0-only */
/* PMIC5 battery thermistor table from Google kernel/msm
 * 500b3a2059c1eec0fec08ec56add06320ea901a8,
 * drivers/iio/adc/qcom-vadc-common.c, adcmap_batt_therm_100k.
 * Copyright (c) 2012-2020, The Linux Foundation. All rights reserved. */
#ifndef REDFIN_POWER_CONVERSION_H
#define REDFIN_POWER_CONVERSION_H
#include <stdbool.h>
#include <stdint.h>
static inline bool redfin_adc5_battery_temp(uint16_t raw,int32_t *mc)
{
    static const int16_t mv[]={1840,1835,1828,1821,1813,1803,1793,1781,1768,1753,
        1737,1719,1700,1679,1655,1630,1603,1574,1543,1510,1475,1438,1400,1360,
        1318,1276,1232,1187,1142,1097,1051,1005,960,915,871,828,786,745,705,
        666,629,594,560,527,497,467,439,413,388,365,343,322,302,284,267,251,
        235,221,208,195,184,173,163,153,144,136,128,120,114,107};
    if (!mc || !raw || raw>0x7fff) return false;
    int32_t voltage=(int32_t)((uint64_t)raw*1875/0x70e4);
    const unsigned count=sizeof(mv)/sizeof(mv[0]);
    if (voltage>mv[0] || voltage<mv[count-1]) return false;
    unsigned i=1;while (i<count && voltage<mv[i]) ++i;
    if (i==count) i=count-1;
    int32_t decic=-400+(int32_t)(i-1)*20+
        (voltage-mv[i-1])*20/(mv[i]-mv[i-1]);
    *mc=decic*100;return true;
}
#endif
