/* SPDX-License-Identifier: MIT */
/* Readonly process totals around actual IOKit calls and mappings.
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
    uint64_t value[8]; /* submit, allocation, other calls, map/unmap: count/ns */
} redfin_drm_profile={PTHREAD_MUTEX_INITIALIZER,{0}};
static inline void redfin_drm_profile_record(unsigned selector,uint64_t nanos)
{
    unsigned index=(selector==0x46||selector==0x52465352u)?0:selector==0x42?2:4;
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
static inline void redfin_drm_profile_map_record(uint64_t nanos)
{
    pthread_mutex_lock(&redfin_drm_profile.lock);
    ++redfin_drm_profile.value[6];redfin_drm_profile.value[7]+=nanos;
    pthread_mutex_unlock(&redfin_drm_profile.lock);
}
static inline void redfin_drm_profile_extended(uint64_t out[8])
{
    pthread_mutex_lock(&redfin_drm_profile.lock);
    for(unsigned i=0;i<8;++i)out[i]=redfin_drm_profile.value[i];
    pthread_mutex_unlock(&redfin_drm_profile.lock);
}
#endif
