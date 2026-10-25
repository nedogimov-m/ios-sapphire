/* SPDX-License-Identifier: MIT */
/* Native Redfin DT/Google msm 500b3a2059c1ee GPU bins and GMU DCVS ABI.
 * Frequencies are never inferred from a marketing name. The physical readonly
 * QFPROM cell selects one of the exact native profiles; unknown bins stay low.
 * Include after redfin_gpu_command.h. */
#ifndef REDFIN_GPU_DVFS_H
#define REDFIN_GPU_DVFS_H
#include <stddef.h>
#define RF_DVFS_LEVELS 7u
#define RF_DVFS_FRESH_NS UINT64_C(1000000000)
#define RF_DVFS_IDLE_NS UINT64_C(200000000)
static const uint32_t rf_dvfs_policy[]={1,0x780000,0x7000,0x1ea,2,5,8,1000,200};
static const uint32_t rf_dvfs_opps[][2]={
    {275000000,64},{400000000,128},{500000000,192},{540000000,256},
    {625000000,256},{670000000,320},{700000000,320},{750000000,384}
};
struct rf_dvfs_level {uint32_t khz,voltage,bw,minimum,maximum;};
struct rf_dvfs_profile {uint32_t bin,count;struct rf_dvfs_level level[RF_DVFS_LEVELS];};
#define RF_DVFS_LOW {275000,64,5,5,7}
#define RF_DVFS_400 {400000,128,7,5,8}
#define RF_DVFS_500 {500000,192,8,7,10}
#define RF_DVFS_625 {625000,256,10,9,12}
#define RF_DVFS_FAST {{0},RF_DVFS_LOW,RF_DVFS_400,RF_DVFS_500,RF_DVFS_625,{670000,320,10,9,12},{750000,384,10,9,12}}
#define RF_DVFS_MID {{0},RF_DVFS_LOW,RF_DVFS_400,RF_DVFS_500,RF_DVFS_625}
static const struct rf_dvfs_profile rf_dvfs_profiles[]={
    {0,7,RF_DVFS_FAST},{132,5,RF_DVFS_MID},
    {115,4,{{0},RF_DVFS_LOW,RF_DVFS_400,{540000,256,8,7,12}}},
    {158,7,RF_DVFS_FAST},{165,5,RF_DVFS_MID}
};
#undef RF_DVFS_FAST
#undef RF_DVFS_MID
#undef RF_DVFS_625
#undef RF_DVFS_500
#undef RF_DVFS_400
#undef RF_DVFS_LOW
struct rf_dvfs_thermal {uint64_t sampled_ns;int32_t hottest_mc,battery_mc;uint32_t pressure;};
static inline const struct rf_dvfs_profile *rf_dvfs_profile(uint32_t bin)
{
    for(unsigned i=0;i<sizeof(rf_dvfs_profiles)/sizeof(rf_dvfs_profiles[0]);++i)
        if(rf_dvfs_profiles[i].bin==bin)return &rf_dvfs_profiles[i];
    return NULL;
}
static inline int rf_dvfs_perf_make(const struct rf_dvfs_profile *profile,
    const struct rf_cmddb_resource *gfx,const struct rf_cmddb_resource *cx,
    const struct rf_cmddb_resource *mx,struct rf_a6_perf *out)
{
    if(!profile||profile!=rf_dvfs_profile(profile->bin)||!out)return EINVAL;
    struct rf_a6_perf p;int error=rf_a6_perf_make(gfx,cx,mx,&p);if(error)return error;
    p.gpu_levels=profile->count;
    for(unsigned i=0;i<profile->count;++i) {
        const struct rf_dvfs_level *level=&profile->level[i];
        p.gpu[i].khz=level->khz;p.gpu[i].acd=UINT32_MAX;
        error=rf_a6_arc_vote(gfx,mx,(uint16_t)level->voltage,&p.gpu[i].vote);
        if(error)return error;
    }
    *out=p;return 0;
}
/* Return a native GMU index, never an unchecked frequency or voltage. Missing
 * or stale real TSENS/battery inputs permit only the proven minimum OPP. */
static inline unsigned rf_dvfs_target(const struct rf_dvfs_profile *profile,
    uint64_t now,bool busy,const struct rf_dvfs_thermal *sample)
{
    if(!profile||profile!=rf_dvfs_profile(profile->bin))return 0;
    if(!busy||!sample||!sample->sampled_ns||now<sample->sampled_ns||
        now-sample->sampled_ns>RF_DVFS_FRESH_NS||sample->pressure>4||
        sample->hottest_mc < -40000||sample->hottest_mc>120000||
        sample->battery_mc < -20000||sample->battery_mc>85000)return 1;
    unsigned pressure=sample->pressure;
    if((sample->hottest_mc>=90000||sample->battery_mc>=55000)&&pressure<3)pressure=3;
    else if((sample->hottest_mc>=80000||sample->battery_mc>=50000)&&pressure<2)pressure=2;
    else if((sample->hottest_mc>=70000||sample->battery_mc>=45000)&&pressure<1)pressure=1;
    uint32_t cap=pressure>=3?275000:pressure==2?400000:pressure==1?500000:UINT32_MAX;
    unsigned result=1;
    for(unsigned i=2;i<profile->count;++i)if(profile->level[i].khz<=cap)result=i;
    return result;
}
#endif
