/* SPDX-License-Identifier: MIT
 * Keep Mesa's atomic files, compression, CRC, namespaced keys and background
 * writer. Redfin supplies a reproducible compiler identity and bounded queued
 * payload. The filesystem size is an eviction target shared by its caches.
 */
struct disk_cache *redfin_mesa_disk_cache_create(const char *gpu,const char *id,uint64_t flags)
{
   struct disk_cache *cache=disk_cache_type_create(gpu,id,
      REDFIN_MESA_DISK_DIRECTORY,flags,DISK_CACHE_MULTI_FILE,REDFIN_MESA_DISK_TARGET);
   if(cache&&cache->path_init_failed){disk_cache_destroy(cache);cache=NULL;}
   return cache;
}
void redfin_mesa_disk_cache_statistics(struct disk_cache *cache,uint64_t out[REDFIN_MESA_DISK_WORDS])
{
   memset(out,0,REDFIN_MESA_DISK_WORDS*sizeof(*out));if(!cache)return;
   out[0]=!cache->path_init_failed;
   out[1]=p_atomic_read(&cache->redfin_hits);out[2]=p_atomic_read(&cache->redfin_misses);
   out[3]=p_atomic_read(&cache->redfin_puts);out[4]=p_atomic_read(&cache->redfin_drops);
   out[5]=p_atomic_read(&cache->redfin_pending);
}
