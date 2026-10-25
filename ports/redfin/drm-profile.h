/* SPDX-License-Identifier: MIT */
/* Readonly process totals around actual IOKit allocation/submit calls.
 * Counter collection never changes the request, return value or fence. */
#ifndef REDFIN_DRM_PROFILE_H
#define REDFIN_DRM_PROFILE_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <pthread.h>
__attribute__((visibility("default"))) int redfin_drm_profile_read(uint64_t *,size_t);
static struct {
    pthread_mutex_t lock;
    uint64_t value[4]; /* submit calls/ns, allocation calls/ns */
} redfin_drm_profile={PTHREAD_MUTEX_INITIALIZER,{0}};
static inline void redfin_drm_profile_record(unsigned selector,uint64_t nanos)
{
    if(selector!=0x46&&selector!=0x42)return;
    unsigned index=selector==0x46?0:2;
    pthread_mutex_lock(&redfin_drm_profile.lock);
    ++redfin_drm_profile.value[index];redfin_drm_profile.value[index+1]+=nanos;
    pthread_mutex_unlock(&redfin_drm_profile.lock);
}
static inline void redfin_drm_profile_snapshot(uint64_t out[4])
{
    pthread_mutex_lock(&redfin_drm_profile.lock);
    for(unsigned i=0;i<4;++i)out[i]=redfin_drm_profile.value[i];
    pthread_mutex_unlock(&redfin_drm_profile.lock);
}
#endif
