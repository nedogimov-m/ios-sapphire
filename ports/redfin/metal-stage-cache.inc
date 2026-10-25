/* SPDX-License-Identifier: MIT
 * Immutable Gallium stage states over canonical, finalized NIR. Each pipeline
 * and cache slot owns a reference; eviction never invalidates a live pipeline.
 * Shader variants remain keyed by the driver's ordinary draw-state keys.
 */
#include "nir_serialize.h"
#include "util/blob.h"
#include "util/hash_table.h"
struct redfin_air_stage {
   struct rwa_device *device;
   void *cso;
   uint8_t *key;
   size_t bytes;
   uint64_t used;
   uint32_t hash,references;
   bool vertex;
};

static void redfin_air_stage_release(struct redfin_air_stage *stage)
{
   if(!stage||--stage->references)return;
   struct pipe_context *pipe=stage->device->pipe;
   if(stage->vertex) {
      pipe->bind_vs_state(pipe,NULL);pipe->delete_vs_state(pipe,stage->cso);
   } else {
      pipe->bind_fs_state(pipe,NULL);pipe->delete_fs_state(pipe,stage->cso);
   }
   ralloc_free(stage);
}

static void redfin_air_stage_drop(struct redfin_air_stage_cache *cache,unsigned index)
{
   struct redfin_air_stage *stage=cache->slots[index];
   if(!stage)return;
   cache->bytes-=stage->bytes;--cache->entries;cache->slots[index]=NULL;
   redfin_air_stage_release(stage);
}

static void redfin_air_stage_cache_finish(struct redfin_air_stage_cache *cache)
{
   for(unsigned i=0;i<REDFIN_AIR_CACHE_ENTRIES;++i)redfin_air_stage_drop(cache,i);
}

static struct redfin_air_stage *redfin_air_stage_create(struct rwa_device *device,
   nir_shader *source,char *why,size_t why_size)
{
   nir_shader *clone=nir_shader_clone(NULL,source);
   if(!clone){say(why,why_size,"out of memory preparing a shader stage");return NULL;}
   finalize_for_gallium(clone,device->screen);nir_sweep(clone);
   bool vertex=source->info.stage==MESA_SHADER_VERTEX;
   struct redfin_air_stage_cache *cache=&device->stage_cache;
   struct blob key;blob_init(&key);nir_serialize(&key,clone,false);
   bool cacheable=!key.out_of_memory&&key.size<=REDFIN_AIR_CACHE_BYTES;
   uint32_t hash=cacheable?_mesa_hash_data(key.data,key.size):0;
   if(cache->clock==UINT64_MAX){redfin_air_stage_cache_finish(cache);cache->clock=0;}
   if(cacheable)for(unsigned i=0;i<REDFIN_AIR_CACHE_ENTRIES;++i) {
      struct redfin_air_stage *stage=cache->slots[i];
      if(!stage||stage->vertex!=vertex||stage->hash!=hash||stage->bytes!=key.size||
         memcmp(stage->key,key.data,key.size))continue;
      if(stage->references==UINT32_MAX)break;
      ++stage->references;stage->used=++cache->clock;++cache->hits;
      blob_finish(&key);ralloc_free(clone);return stage;
   }
   ++cache->misses;
   struct redfin_air_stage *stage=rzalloc(NULL,struct redfin_air_stage);
   if(!stage){blob_finish(&key);ralloc_free(clone);say(why,why_size,"out of memory owning a shader stage");return NULL;}
   stage->device=device;stage->vertex=vertex;stage->references=1;
   struct pipe_shader_state state={.type=PIPE_SHADER_IR_NIR,.ir.nir=clone};
   struct pipe_context *pipe=device->pipe;
   stage->cso=vertex?pipe->create_vs_state(pipe,&state):pipe->create_fs_state(pipe,&state);
   if(!stage->cso) {
      /* Preserve make_stage_cso's ownership contract: a refusing driver
       * may already have taken the NIR, so do not risk freeing it twice. */
      blob_finish(&key);ralloc_free(stage);say(why,why_size,"the driver refused a shader stage");return NULL;
   }
   if(cacheable) {
      stage->key=ralloc_memdup(stage,key.data,key.size);stage->bytes=key.size;
      if(stage->key) {
         while(cache->entries>=REDFIN_AIR_CACHE_ENTRIES||cache->bytes+stage->bytes>REDFIN_AIR_CACHE_BYTES) {
            unsigned oldest=REDFIN_AIR_CACHE_ENTRIES;
            for(unsigned i=0;i<REDFIN_AIR_CACHE_ENTRIES;++i)
               if(cache->slots[i]&&(oldest==REDFIN_AIR_CACHE_ENTRIES||cache->slots[i]->used<cache->slots[oldest]->used))oldest=i;
            if(oldest==REDFIN_AIR_CACHE_ENTRIES)break;
            redfin_air_stage_drop(cache,oldest);++cache->evictions;
         }
         unsigned slot=0;while(slot<REDFIN_AIR_CACHE_ENTRIES&&cache->slots[slot])++slot;
         if(slot<REDFIN_AIR_CACHE_ENTRIES&&cache->bytes+stage->bytes<=REDFIN_AIR_CACHE_BYTES) {
            ++stage->references;stage->used=++cache->clock;cache->slots[slot]=stage;
            ++cache->entries;cache->bytes+=stage->bytes;
         }
      }
   }
   blob_finish(&key);return stage;
}
