/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_BENCHMARK_H
#define REDFIN_DISPLAY_BENCHMARK_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdbool.h>
#include <stdio.h>
#define REDFIN_DISPLAY_PROBE_REQUEST "/redfin/display-probe-request"
enum {RF_DISPLAY_PROBE_NONE,RF_DISPLAY_PROBE_PASSIVE,RF_DISPLAY_PROBE_ANIMATE,
    RF_DISPLAY_PROBE_CHECKED,RF_DISPLAY_PROBE_CONTROLS_CHECKED};
#define RF_DISPLAY_PROBE_WARMUP_SECONDS 8u
#define RF_DISPLAY_PROBE_MEASURE_SECONDS 10u
#define RF_DISPLAY_PROBE_ANIMATION_SECONDS 40u
#define RF_DISPLAY_PROBE_DEADLINE_SECONDS 45u
#define RF_DISPLAY_PROBE_IDLE_LIMIT_SECONDS 150u
#define RF_DISPLAY_PROBE_WINDOW_STABLE_SECONDS 2u
#define RF_DISPLAY_PROBE_WINDOW_RESTARTS 3u
enum {RF_DISPLAY_WINDOW_PENDING,RF_DISPLAY_WINDOW_READY,RF_DISPLAY_WINDOW_ACTIVE,RF_DISPLAY_WINDOW_REFUSED};
struct redfin_display_window_state {
    uintptr_t active,candidate;
    double since;
    unsigned restarts;
    bool refused;
};
/* Window replacement discards the old interval. A missing window consumes
 * one transition, not one retry per display callback. The caller's existing
 * finite wall/idle deadlines also cover waiting for a stable replacement. */
static inline unsigned redfin_display_probe_window(struct redfin_display_window_state *s,
    uintptr_t candidate,double now,bool *reset)
{
    if(!s||!reset)return RF_DISPLAY_WINDOW_REFUSED;
    *reset=false;
    if(s->refused)return RF_DISPLAY_WINDOW_REFUSED;
    if(s->active&&s->active==candidate)return RF_DISPLAY_WINDOW_ACTIVE;
    if(s->active) {
        s->active=0;s->candidate=0;s->since=now;*reset=true;
        if(++s->restarts>RF_DISPLAY_PROBE_WINDOW_RESTARTS) {
            s->refused=true;return RF_DISPLAY_WINDOW_REFUSED;
        }
    }
    if(candidate!=s->candidate||now<s->since) {
        s->candidate=candidate;s->since=now;return RF_DISPLAY_WINDOW_PENDING;
    }
    if(!candidate||now-s->since<RF_DISPLAY_PROBE_WINDOW_STABLE_SECONDS)return RF_DISPLAY_WINDOW_PENDING;
    s->active=candidate;return RF_DISPLAY_WINDOW_READY;
}
/* A root-owned regular control file selects one boot only. No persistent
 * animation is enabled by installing the adapter or by reading statistics. */
static inline unsigned redfin_display_probe_request(const char *data,size_t bytes,uint64_t nonce)
{
    static const char prefix[]="redfin-probe-v1:";
    static const char *const suffix[]={":passive\n",":animate\n",":animate-checked\n",":controls-checked\n"};
    const size_t head=sizeof(prefix)-1;
    if(!data||!nonce||bytes<head+16+9||bytes>head+16+18||memcmp(data,prefix,head))return RF_DISPLAY_PROBE_NONE;
    uint64_t found=0;
    for(unsigned i=0;i<16;++i) {
        unsigned c=(unsigned char)data[head+i],digit;
        if(c>='0'&&c<='9')digit=c-'0';
        else if(c>='a'&&c<='f')digit=c-'a'+10;
        else return RF_DISPLAY_PROBE_NONE;
        found=(found<<4)|digit;
    }
    if(found!=nonce)return RF_DISPLAY_PROBE_NONE;
    for(unsigned i=0;i<sizeof(suffix)/sizeof(suffix[0]);++i) {
        size_t tail=strlen(suffix[i]);
        if(bytes==head+16+tail&&!memcmp(data+head+16,suffix[i],tail))return i+1;
    }
    return RF_DISPLAY_PROBE_NONE;
}
static inline const char *redfin_display_probe_find(const char *data,size_t bytes,const char *tag)
{
    size_t length=strlen(tag);
    if(!data||length>bytes)return NULL;
    for(size_t i=0;i<=bytes-length;++i)if(!memcmp(data+i,tag,length))return data+i;
    return NULL;
}
/* 0: pending/missing, 1: both real jobs succeeded in this boot, 2: failure.
 * A rolling log from another nonce cannot authorize a measurement. */
static inline unsigned redfin_display_probe_checks(const char *metal,size_t metal_bytes,
    const char *gpu,size_t gpu_bytes,uint64_t nonce)
{
    if(!nonce)return 0;
    char boot[32],metal_success[128],gpu_boot[64],mode_begin[2][112],mode_end[2][112];
    snprintf(boot,sizeof(boot),"boot=%016llx ",(unsigned long long)nonce);
    snprintf(metal_success,sizeof(metal_success),"REDFIN METAL CHECK EXIT: boot=%016llx result=0 full-contract=1",(unsigned long long)nonce);
    snprintf(gpu_boot,sizeof(gpu_boot),"REDFIN GPU RENDER BOOT: %016llx",(unsigned long long)nonce);
    const char *modes[]={"gmem","sysmem"};
    for(unsigned i=0;i<2;++i) {
        snprintf(mode_begin[i],sizeof(mode_begin[i]),
            "REDFIN GLES MODE: boot=%016llx mode=%s hardware-required=1",(unsigned long long)nonce,modes[i]);
        snprintf(mode_end[i],sizeof(mode_end[i]),
            "REDFIN GLES MODE RESULT: boot=%016llx mode=%s result=0 hardware=1",(unsigned long long)nonce,modes[i]);
    }
    bool metal_done=false;
    for(size_t at=0;metal&&at<metal_bytes;) {
        const char *line=metal+at,*end=memchr(line,'\n',metal_bytes-at);
        size_t bytes=end?(size_t)(end-line):metal_bytes-at;
        if(!end)break; /* a concurrent writer has not finished this record */
        if(redfin_display_probe_find(line,bytes,boot)&&
           redfin_display_probe_find(line,bytes,"REDFIN METAL CHECK EXIT:")) {
            if(bytes!=strlen(metal_success)||memcmp(line,metal_success,bytes))return 2;
            metal_done=true;
        }
        at+=bytes+(end?1:0);
    }
    bool gpu_current=false,gpu_done=false;
    unsigned modes_started=0,modes_completed=0,mode_active=0;
    static const char gpu_success[]="REDFIN GPU RENDER RESULT: result=0 hardware=1 draws=2";
    static const char gpu_dual_success[]="REDFIN GPU RENDER RESULT: result=0 hardware=1 draws=4 modes=gmem,sysmem";
    for(size_t at=0;gpu&&at<gpu_bytes;) {
        const char *line=gpu+at,*end=memchr(line,'\n',gpu_bytes-at);
        size_t bytes=end?(size_t)(end-line):gpu_bytes-at;
        if(!end)break;
        if(redfin_display_probe_find(line,bytes,"REDFIN GPU RENDER BOOT:")) {
            gpu_current=bytes==strlen(gpu_boot)&&!memcmp(line,gpu_boot,bytes);
            gpu_done=false;
            modes_started=0;modes_completed=0;mode_active=0;
        } else if(gpu_current) {
            if(redfin_display_probe_find(line,bytes,"REDFIN GPU RENDER FAIL:"))return 2;
            if(redfin_display_probe_find(line,bytes,"REDFIN GLES MODE:")) {
                unsigned mode=0;
                for(unsigned i=0;i<2;++i)
                    if(bytes==strlen(mode_begin[i])&&!memcmp(line,mode_begin[i],bytes))mode=i+1;
                if(!mode||mode_active||gpu_done||
                    (mode==1?(modes_started!=0||modes_completed!=0):
                             (modes_started!=1||modes_completed!=1)))return 2;
                mode_active=mode;modes_started|=1u<<(mode-1);
            }
            if(redfin_display_probe_find(line,bytes,"REDFIN GLES MODE RESULT:")) {
                unsigned mode=0;
                for(unsigned i=0;i<2;++i)
                    if(bytes==strlen(mode_end[i])&&!memcmp(line,mode_end[i],bytes))mode=i+1;
                if(!mode||mode!=mode_active||gpu_done)return 2;
                modes_completed|=1u<<(mode-1);mode_active=0;
            }
            if(redfin_display_probe_find(line,bytes,"REDFIN GPU RENDER RESULT:")) {
                bool legacy=!modes_started&&bytes==sizeof(gpu_success)-1&&!memcmp(line,gpu_success,bytes);
                bool dual=modes_started==3&&modes_completed==3&&!mode_active&&
                    bytes==sizeof(gpu_dual_success)-1&&!memcmp(line,gpu_dual_success,bytes);
                if(gpu_done||(!legacy&&!dual))return 2;
                gpu_done=true;
            }
        }
        at+=bytes+1;
    }
    return metal_done&&gpu_done?1:0;
}
#endif
