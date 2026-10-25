/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_TRANSLATION_CACHE_H
#define REDFIN_METAL_TRANSLATION_CACHE_H
#include <stdint.h>
#include <stddef.h>
#ifndef REDFIN_AIR_CACHE_ENTRIES
#define REDFIN_AIR_CACHE_ENTRIES 32u
#endif
#define REDFIN_AIR_CACHE_BYTES (8u * 1024u * 1024u)
#define REDFIN_AIR_CACHE_STAT_WORDS 11u
struct redfin_air_cache_entry;
struct redfin_air_stage;
struct redfin_air_translation_cache {
    struct redfin_air_cache_entry *slots[REDFIN_AIR_CACHE_ENTRIES];
    uint64_t clock,hits,misses,evictions,bypasses;
    size_t bytes;
    unsigned entries;
};
struct redfin_air_stage_cache {
    struct redfin_air_stage *slots[REDFIN_AIR_CACHE_ENTRIES];
    uint64_t clock,hits,misses,evictions;
    size_t bytes;
    unsigned entries;
};
struct rwa_device;
__attribute__((visibility("default"))) int rwa_redfin_translation_cache_statistics(struct rwa_device *,uint64_t *,size_t);
#endif
