/* SPDX-License-Identifier: MIT
 * Per-device, bounded CPU templates. No GPU resource, external page, caller
 * pointer or descriptor binding is retained. Device calls are serialized by
 * the same native gate as the rest of this Gallium context.
 */
#include "nir_serialize.h"
#include "util/blob.h"
#include "util/hash_table.h"

struct redfin_air_cache_entry {
   struct air_shader_info info;
   uint8_t *key,*nir;
   size_t key_bytes,nir_bytes,charge;
   uint64_t used;
   uint32_t hash;
};

static int redfin_air_constant_compare(const void *left,const void *right)
{
   const struct redfin_metal_constant *a=left,*b=right;
   return a->index<b->index?-1:a->index>b->index;
}

static void redfin_air_key_u32(struct blob *key,uint32_t value)
{ blob_write_bytes(key,&value,sizeof(value)); }
static void redfin_air_key_u64(struct blob *key,uint64_t value)
{ blob_write_bytes(key,&value,sizeof(value)); }

static bool redfin_air_cache_key(struct blob *key,const void *bitcode,size_t bytes,
   const char *entry,const struct redfin_metal_constants *values)
{
   /* Large valid modules simply use the ordinary compiler. NULL legacy
    * defaults and an explicit empty/undefined native snapshot stay distinct.
    */
   if(!bitcode||bytes<4||bytes>1024u*1024u)return false;
   size_t name=entry?strnlen(entry,4097):0;
   if(name>4096)return false;
   redfin_air_key_u64(key,bytes);redfin_air_key_u32(key,(uint32_t)name);
   redfin_air_key_u32(key,entry!=NULL);redfin_air_key_u32(key,values!=NULL);
   blob_write_bytes(key,bitcode,bytes);
   if(name)blob_write_bytes(key,entry,name);
   if(values) {
      if(values->reserved||values->count>REDFIN_METAL_CONSTANTS_MAX||
         (values->count&&!values->values))return false;
      struct redfin_metal_constant ordered[REDFIN_METAL_CONSTANTS_MAX];
      if(values->count)memcpy(ordered,values->values,values->count*sizeof(*ordered));
      qsort(ordered,values->count,sizeof(*ordered),redfin_air_constant_compare);
      redfin_air_key_u32(key,values->count);
      for(unsigned i=0;i<values->count;++i) {
         if(!ordered[i].bytes||ordered[i].bytes>sizeof(ordered[i].words)||
            (i&&ordered[i-1].index==ordered[i].index))return false;
         redfin_air_key_u32(key,ordered[i].index);redfin_air_key_u32(key,ordered[i].bytes);
         blob_write_bytes(key,ordered[i].words,ordered[i].bytes);
      }
   }
   return !key->out_of_memory;
}

static size_t redfin_air_string_bytes(const char *text)
{ return text?strnlen(text,4097)+1:0; }

static size_t redfin_air_info_bytes(const struct air_shader_info *info)
{
   if(info->num_resources>512||info->num_varyings>128||
      info->num_vertex_attributes>128||info->num_notes>512)return SIZE_MAX;
   size_t bytes=sizeof(*info)+redfin_air_string_bytes(info->entry_point)+
      info->num_resources*sizeof(*info->resources)+info->num_varyings*sizeof(*info->varyings)+
      info->num_vertex_attributes*sizeof(*info->vertex_attributes)+info->num_notes*sizeof(*info->notes);
   for(unsigned i=0;i<info->num_resources;++i) {
      bytes+=redfin_air_string_bytes(info->resources[i].name);
      bytes+=redfin_air_string_bytes(info->resources[i].type_name);
   }
   for(unsigned i=0;i<info->num_varyings;++i)bytes+=redfin_air_string_bytes(info->varyings[i].name);
   for(unsigned i=0;i<info->num_vertex_attributes;++i) {
      bytes+=redfin_air_string_bytes(info->vertex_attributes[i].name);
      bytes+=redfin_air_string_bytes(info->vertex_attributes[i].type_name);
      bytes+=redfin_air_string_bytes(info->vertex_attributes[i].function_constant);
   }
   for(unsigned i=0;i<info->num_notes;++i)bytes+=redfin_air_string_bytes(info->notes[i]);
   return bytes;
}

static bool redfin_air_info_copy(void *owner,struct air_shader_info *out,const struct air_shader_info *source)
{
   *out=*source;
   out->resources=NULL;out->varyings=NULL;out->vertex_attributes=NULL;out->notes=NULL;
#define REDFIN_AIR_COPY_STRING(destination,original) do { \
   if((original)&&strnlen((original),4097)>4096)return false; \
   (destination)=ralloc_strdup(owner,(original)); \
   if((original)&&!(destination))return false; \
} while(0)
   REDFIN_AIR_COPY_STRING(out->entry_point,source->entry_point);
   if(source->num_resources) {
      out->resources=ralloc_memdup(owner,source->resources,source->num_resources*sizeof(*out->resources));
      if(!out->resources)return false;
      for(unsigned i=0;i<source->num_resources;++i) {
         REDFIN_AIR_COPY_STRING(out->resources[i].name,source->resources[i].name);
         REDFIN_AIR_COPY_STRING(out->resources[i].type_name,source->resources[i].type_name);
      }
   }
   if(source->num_varyings) {
      out->varyings=ralloc_memdup(owner,source->varyings,source->num_varyings*sizeof(*out->varyings));
      if(!out->varyings)return false;
      for(unsigned i=0;i<source->num_varyings;++i)
         REDFIN_AIR_COPY_STRING(out->varyings[i].name,source->varyings[i].name);
   }
   if(source->num_vertex_attributes) {
      out->vertex_attributes=ralloc_memdup(owner,source->vertex_attributes,
         source->num_vertex_attributes*sizeof(*out->vertex_attributes));
      if(!out->vertex_attributes)return false;
      for(unsigned i=0;i<source->num_vertex_attributes;++i) {
         REDFIN_AIR_COPY_STRING(out->vertex_attributes[i].name,source->vertex_attributes[i].name);
         REDFIN_AIR_COPY_STRING(out->vertex_attributes[i].type_name,source->vertex_attributes[i].type_name);
         REDFIN_AIR_COPY_STRING(out->vertex_attributes[i].function_constant,source->vertex_attributes[i].function_constant);
      }
   }
   if(source->num_notes) {
      out->notes=ralloc_memdup(owner,source->notes,source->num_notes*sizeof(*out->notes));
      if(!out->notes)return false;
      for(unsigned i=0;i<source->num_notes;++i)REDFIN_AIR_COPY_STRING(out->notes[i],source->notes[i]);
   }
#undef REDFIN_AIR_COPY_STRING
   return true;
}

static void redfin_air_cache_drop(struct redfin_air_translation_cache *cache,unsigned index)
{
   struct redfin_air_cache_entry *entry=cache->slots[index];
   if(!entry)return;
   cache->bytes-=entry->charge;--cache->entries;cache->slots[index]=NULL;ralloc_free(entry);
}

static void redfin_air_cache_finish(struct redfin_air_translation_cache *cache)
{
   for(unsigned i=0;i<REDFIN_AIR_CACHE_ENTRIES;++i)redfin_air_cache_drop(cache,i);
}

static void redfin_air_cache_insert(struct rwa_device *device,const struct blob *key,
   uint32_t hash,nir_shader *nir,const struct air_shader_info *info)
{
   struct redfin_air_translation_cache *cache=&device->translation_cache;
   size_t metadata=redfin_air_info_bytes(info);
   if(metadata==SIZE_MAX||metadata>REDFIN_AIR_CACHE_BYTES){++cache->bypasses;return;}
   struct blob binary;blob_init(&binary);nir_serialize(&binary,nir,false);
   if(binary.out_of_memory||binary.size>REDFIN_AIR_CACHE_BYTES||
      key->size+metadata+sizeof(struct redfin_air_cache_entry)>REDFIN_AIR_CACHE_BYTES-binary.size) {
      blob_finish(&binary);++cache->bypasses;return;
   }
   struct redfin_air_cache_entry *entry=rzalloc(NULL,struct redfin_air_cache_entry);
   if(!entry){blob_finish(&binary);++cache->bypasses;return;}
   entry->key=ralloc_memdup(entry,key->data,key->size);
   entry->nir=ralloc_memdup(entry,binary.data,binary.size);
   entry->key_bytes=key->size;entry->nir_bytes=binary.size;
   entry->charge=sizeof(*entry)+metadata+key->size+binary.size;entry->hash=hash;
   blob_finish(&binary);
   if(!entry->key||!entry->nir||!redfin_air_info_copy(entry,&entry->info,info)) {
      ralloc_free(entry);++cache->bypasses;return;
   }
   while(cache->entries>=REDFIN_AIR_CACHE_ENTRIES||cache->bytes+entry->charge>REDFIN_AIR_CACHE_BYTES) {
      unsigned oldest=REDFIN_AIR_CACHE_ENTRIES;
      for(unsigned i=0;i<REDFIN_AIR_CACHE_ENTRIES;++i)
         if(cache->slots[i]&&(oldest==REDFIN_AIR_CACHE_ENTRIES||cache->slots[i]->used<cache->slots[oldest]->used))oldest=i;
      if(oldest==REDFIN_AIR_CACHE_ENTRIES){ralloc_free(entry);++cache->bypasses;return;}
      redfin_air_cache_drop(cache,oldest);++cache->evictions;
   }
   unsigned slot=0;while(slot<REDFIN_AIR_CACHE_ENTRIES&&cache->slots[slot])++slot;
   entry->used=++cache->clock;cache->slots[slot]=entry;++cache->entries;cache->bytes+=entry->charge;
}

static nir_shader *redfin_air_cached_translate(struct rwa_device *device,void *owner,
   const void *bitcode,size_t bytes,const char *name,const struct redfin_metal_constants *values,
   struct air_shader_info *info,char *why,size_t why_size)
{
   struct redfin_air_translation_cache *cache=&device->translation_cache;
   struct blob key;blob_init(&key);
   bool cacheable=owner&&redfin_air_cache_key(&key,bitcode,bytes,name,values);
   uint32_t hash=cacheable?_mesa_hash_data(key.data,key.size):0;
   if(cache->clock==UINT64_MAX){redfin_air_cache_finish(cache);cache->clock=0;}
   if(cacheable)for(unsigned i=0;i<REDFIN_AIR_CACHE_ENTRIES;++i) {
      struct redfin_air_cache_entry *entry=cache->slots[i];
      if(!entry||entry->hash!=hash||entry->key_bytes!=key.size||memcmp(entry->key,key.data,key.size))continue;
      void *temporary=ralloc_context(NULL);struct blob_reader reader;
      blob_reader_init(&reader,entry->nir,entry->nir_bytes);
      nir_shader *nir=temporary?nir_deserialize(temporary,device->nir_options,&reader):NULL;
      struct air_shader_info copied;
      if(nir&&!reader.overrun&&reader.current==reader.end&&redfin_air_info_copy(temporary,&copied,&entry->info)) {
         ralloc_adopt(owner,temporary);ralloc_free(temporary);*info=copied;
         entry->used=++cache->clock;++cache->hits;blob_finish(&key);return nir;
      }
      ralloc_free(temporary);redfin_air_cache_drop(cache,i);++cache->bypasses;break;
   }
   if(cacheable)++cache->misses;else ++cache->bypasses;
   void *temporary=ralloc_context(NULL);struct air_constant_value *constants=NULL;
   if(!temporary){blob_finish(&key);say(why,why_size,"out of memory translating a shader");return NULL;}
   int count=rwa_redfin_constants_for_module(temporary,bitcode,bytes,values,&constants,why,why_size);
   if(count<0){ralloc_free(temporary);blob_finish(&key);return NULL;}
   const struct air_to_nir_options options={.constants=constants,.num_constants=(unsigned)count};
   const char *error=NULL;
   nir_shader *nir=air_to_nir(owner,bitcode,bytes,name,&options,device->nir_options,info,&error);
   if(!nir)say(why,why_size,"%s",error?error:"the module could not be translated");
   ralloc_free(temporary);
   if(nir&&cacheable)redfin_air_cache_insert(device,&key,hash,nir,info);
   blob_finish(&key);return nir;
}

int rwa_redfin_translation_cache_statistics(struct rwa_device *device,uint64_t *out,size_t words)
{
   if(!device||!out||words!=REDFIN_AIR_CACHE_STAT_WORDS)return -1;
   const struct redfin_air_translation_cache *cache=&device->translation_cache;
   out[0]=cache->hits;out[1]=cache->misses;out[2]=cache->entries;
   out[3]=cache->bytes;out[4]=cache->evictions;out[5]=cache->bypasses;
   out[6]=device->stage_cache.hits;out[7]=device->stage_cache.misses;
   out[8]=device->stage_cache.entries;out[9]=device->stage_cache.bytes;
   out[10]=device->stage_cache.evictions;return 0;
}
