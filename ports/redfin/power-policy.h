/* SPDX-License-Identifier: MIT */
/* Redfin power/thermal units and bounded policy. No hardware access here.
 * Register conversions follow Google kernel/msm 500b3a2059c1ee:
 * qg-{util,defs}.c, smb5-reg.h and tsens2xxx.c. */
#ifndef REDFIN_POWER_POLICY_H
#define REDFIN_POWER_POLICY_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#define RF_POWER_ABI 1u
#define RF_POWER_VOLTAGE (1u<<0)
#define RF_POWER_CURRENT (1u<<1)
#define RF_POWER_TEMP (1u<<2)
#define RF_POWER_SOC (1u<<3)
#define RF_POWER_CHARGER (1u<<4)
#define RF_POWER_CAPACITY (1u<<5)
#define RF_POWER_REQUIRED (RF_POWER_VOLTAGE|RF_POWER_CURRENT|RF_POWER_TEMP|RF_POWER_SOC|RF_POWER_CHARGER)
struct redfin_power_sample {
    uint32_t version,bytes,valid;
    int32_t voltage_uv,current_ua,temperature_mc,soc_hundredths;
    int32_t present,external,charging,full,wireless;
    int32_t full_uah,design_uah,charge_uah,usb_voltage_uv,usb_current_ua;
    uint32_t charger_faults,usb_type,soc_integrated;
};
struct redfin_soc_tracker {
    int64_t charge_uams,full_uams;
    uint64_t last_ns;
    bool initialized;
};

static inline uint16_t redfin_power_u16(const uint8_t p[2])
{return (uint16_t)p[0]|(uint16_t)((uint16_t)p[1]<<8);}
static inline int32_t redfin_qg_voltage(uint16_t raw)
{return (int32_t)((uint64_t)raw*194637u/1000u);}
/* QG current is negative into the battery. IOPMPowerSource is positive. */
static inline int32_t redfin_qg_current(uint16_t raw,unsigned subtype)
{
    int32_t signed_raw=(raw&0x8000u) ? (int32_t)raw-65536 : (int32_t)raw;
    return (int32_t)(-(int64_t)signed_raw*(subtype==3 ? 152588 : 305176)/1000);
}
static inline bool redfin_tsens_value(uint32_t status,int32_t *temperature)
{
    if (!temperature || !(status&(1u<<21))) return false;
    int32_t value=(int32_t)(status&0xfffu);
    if (value&0x800) value-=4096;
    value*=100;
    if (value < -40000 || value>150000) return false;
    *temperature=value;return true;
}
static inline bool redfin_power_valid(const struct redfin_power_sample *s)
{
    return s && s->version==RF_POWER_ABI && s->bytes==sizeof(*s) &&
        (s->valid&RF_POWER_REQUIRED)==RF_POWER_REQUIRED &&
        s->voltage_uv>=2500000 && s->voltage_uv<=4700000 &&
        s->current_ua>=-10000000 && s->current_ua<=10000000 &&
        s->temperature_mc>=-40000 && s->temperature_mc<=100000 &&
        s->soc_hundredths>=0 && s->soc_hundredths<=10000 &&
        (s->present==0 || s->present==1) && (s->external==0 || s->external==1) &&
        (!s->charging || (s->present && s->external && !s->full && !s->charger_faults));
}
/* A measured seed plus elapsed, measured current; never estimate SOC from
 * terminal voltage. Preserve fractional charge between samples. Long/missing
 * samples are refused rather than integrated as though the last current held. */
static inline bool redfin_soc_update(struct redfin_soc_tracker *t,
    struct redfin_power_sample *s,uint64_t now)
{
    if (!t || !redfin_power_valid(s) || !now || !(s->valid&RF_POWER_CAPACITY) ||
        s->full_uah<500000 || s->full_uah>6000000) return false;
    int64_t full=(int64_t)s->full_uah*3600000;
    if (!t->initialized) {
        t->charge_uams=full*s->soc_hundredths/10000;t->full_uams=full;
        t->last_ns=now;t->initialized=true;
    } else {
        if (now<=t->last_ns || now-t->last_ns>10000000000ULL || full!=t->full_uams) {
            t->initialized=false;return false;
        }
        uint64_t ms=(now-t->last_ns)/1000000;
        if (!ms) return true;
        t->charge_uams+=(int64_t)s->current_ua*(int64_t)ms;
        t->last_ns+=ms*1000000;
        if (s->full) t->charge_uams=full;
        if (t->charge_uams<0) t->charge_uams=0;
        if (t->charge_uams>full) t->charge_uams=full;
        s->soc_integrated=1;
    }
    s->soc_hundredths=(int32_t)(t->charge_uams*10000/full);
    s->charge_uah=(int32_t)(t->charge_uams/3600000);return true;
}
static inline unsigned redfin_thermal_pressure(int32_t hottest_mc,int32_t battery_mc,
    unsigned previous)
{
    static const int32_t up[]={70000,80000,90000,100000};
    unsigned level=0;
    while (level<4 && hottest_mc>=up[level]) ++level;
    if (battery_mc>=45000 && level<1) level=1;
    if (battery_mc>=50000 && level<2) level=2;
    if (battery_mc>=55000 && level<4) level=4;
    if (previous<=4 && level<previous) {
        int32_t threshold=up[previous-1]-5000;
        if (hottest_mc>=threshold || (previous==1 && battery_mc>=42000) ||
            (previous==2 && battery_mc>=47000) || (previous==4 && battery_mc>=52000)) return previous;
    }
    return level;
}
static inline bool redfin_charger_enable_allowed(const struct redfin_power_sample *s,
    unsigned float_uv,unsigned charge_ua,unsigned safety_timer,unsigned jeita)
{
    return redfin_power_valid(s) && s->present && s->external && !s->charger_faults &&
        s->temperature_mc>=10000 && s->temperature_mc<=43000 && s->voltage_uv<4450000 &&
        float_uv>=3600000 && float_uv<=4450000 && charge_ua>0 && charge_ua<=2000000 &&
        (safety_timer&3u)==3u && (jeita&15u)==15u;
}
static inline bool redfin_charger_must_pause(const struct redfin_power_sample *s)
{
    return !redfin_power_valid(s) || !s->present || s->charger_faults ||
        s->temperature_mc<0 || s->temperature_mc>=45000 || s->voltage_uv>=4500000;
}
#endif
