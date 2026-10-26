/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_BENCHMARK_H
#define REDFIN_DISPLAY_BENCHMARK_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdbool.h>
#include <stdio.h>
#define REDFIN_DISPLAY_PROBE_REQUEST "/redfin/display-probe-request"
enum {RF_DISPLAY_PROBE_NONE,RF_DISPLAY_PROBE_PASSIVE,RF_DISPLAY_PROBE_ANIMATE,RF_DISPLAY_PROBE_CHECKED};
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
    static const char *const suffix[]={":passive\n",":animate\n",":animate-checked\n"};
    const size_t head=sizeof(prefix)-1;
    if(!data||!nonce||bytes<head+16+9||bytes>head+16+17||memcmp(data,prefix,head))return RF_DISPLAY_PROBE_NONE;
    uint64_t found=0;
    for(unsigned i=0;i<16;++i) {
        unsigned c=(unsigned char)data[head+i],digit;
        if(c>='0'&&c<='9')digit=c-'0';
        else if(c>='a'&&c<='f')digit=c-'a'+10;
        else return RF_DISPLAY_PROBE_NONE;
        found=(found<<4)|digit;
    }
    if(found!=nonce)return RF_DISPLAY_PROBE_NONE;
    for(unsigned i=0;i<3;++i) {
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
    char boot[32],gpu_boot[64];
    snprintf(boot,sizeof(boot),"boot=%016llx ",(unsigned long long)nonce);
    snprintf(gpu_boot,sizeof(gpu_boot),"REDFIN GPU RENDER BOOT: %016llx\n",(unsigned long long)nonce);
    bool metal_done=false;
    for(size_t at=0;metal&&at<metal_bytes;) {
        const char *line=metal+at,*end=memchr(line,'\n',metal_bytes-at);
        size_t bytes=end?(size_t)(end-line):metal_bytes-at;
        if(redfin_display_probe_find(line,bytes,boot)&&
           redfin_display_probe_find(line,bytes,"REDFIN GRAPHICS MEMORY:")&&
           redfin_display_probe_find(line,bytes,"phase=checker-after ") ) {
            if(!redfin_display_probe_find(line,bytes,"status=0 "))return 2;
            metal_done=true;
        }
        at+=bytes+(end?1:0);
    }
    const char *begin=redfin_display_probe_find(gpu,gpu_bytes,gpu_boot);
    if(!begin)return 0;
    size_t remaining=gpu_bytes-(size_t)(begin-gpu);
    if(redfin_display_probe_find(begin,remaining,"REDFIN GPU RENDER FAIL:"))return 2;
    const char *result=redfin_display_probe_find(begin,remaining,"REDFIN GPU RENDER RESULT:");
    if(!result)return 0;
    size_t tail=gpu_bytes-(size_t)(result-gpu);
    if(!redfin_display_probe_find(result,tail,"REDFIN GPU RENDER RESULT: result=0 hardware=1 draws=2\n"))return 2;
    return metal_done?1:0;
}
#endif
