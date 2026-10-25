/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_MESA_DISK_CACHE_H
#define REDFIN_MESA_DISK_CACHE_H
#include "util/disk_cache.h"
#include <stdint.h>
#include <stddef.h>
#define REDFIN_MESA_DISK_DIRECTORY "redfin_shader_cache-v1"
#define REDFIN_MESA_DISK_TARGET (32u * 1024u * 1024u)
#define REDFIN_MESA_DISK_PENDING (4u * 1024u * 1024u)
#define REDFIN_MESA_DISK_ITEM (8u * 1024u * 1024u)
#define REDFIN_MESA_DISK_WORDS 6u
struct disk_cache *redfin_mesa_disk_cache_create(const char *,const char *,uint64_t);
void redfin_mesa_disk_cache_statistics(struct disk_cache *,uint64_t[REDFIN_MESA_DISK_WORDS]);
__attribute__((visibility("default"))) int redfin_ir3_disk_cache_statistics(uint64_t *,size_t);
void redfin_ir3_record_compile(uint64_t);
#endif
