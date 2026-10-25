/* SPDX-License-Identifier: MIT
 * Only CPU shader templates and unpruned reflection are persisted. No process
 * address, live resource, page binding or opaque driver state enters this file.
 * Mesa owns compression, CRC, atomic replacement and bounded background I/O.
 */
#include "util/redfin_mesa_disk_cache.h"
#include "util/redfin_mesa_cache_build.h"

static bool redfin_air_disk_string_put(struct blob *blob,const char *text)
{
   size_t bytes=text?strnlen(text,4097)+1:0;
   if(bytes>4097)return false;
   blob_write_uint32(blob,bytes);if(bytes)blob_write_bytes(blob,text,bytes);
   return !blob->out_of_memory;
}
static bool redfin_air_disk_string_get(struct blob_reader *blob,void *owner,const char **out)
{
   uint32_t bytes=blob_read_uint32(blob);*out=NULL;
   if(blob->overrun||bytes>4097)return false;
   if(!bytes)return true;
   const char *text=blob_read_bytes(blob,bytes);
   if(blob->overrun||!text||text[bytes-1]||memchr(text,0,bytes-1))return false;
   *out=ralloc_strndup(owner,text,bytes-1);return *out!=NULL;
}

static bool redfin_air_disk_info_put(struct blob *blob,const struct air_shader_info *info)
{
   if(redfin_air_info_bytes(info)==SIZE_MAX)return false;
#define RF_PUT(object,field) blob_write_uint32(blob,(object)->field)
#define RF_STRING(value) do {if(!redfin_air_disk_string_put(blob,value))return false;} while(0)
   RF_PUT(info,stage);RF_PUT(info,num_resources);RF_PUT(info,num_varyings);
   RF_PUT(info,num_vertex_attributes);RF_PUT(info,vertex_attributes_read);
   RF_PUT(info,num_render_targets);RF_PUT(info,fbfetch_targets);
   RF_PUT(info,raster_order_groups);RF_PUT(info,num_notes);RF_PUT(info,threadgroup_bytes);
   RF_STRING(info->entry_point);
   for(unsigned i=0;i<info->num_resources;++i) {
      const struct air_resource *r=&info->resources[i];
      RF_PUT(r,kind);RF_PUT(r,index);RF_PUT(r,size);RF_PUT(r,read);RF_PUT(r,write);
      RF_PUT(r,param);RF_PUT(r,inline_sampler);blob_write_uint64(blob,r->sampler_state);
      RF_PUT(r,raster_order_group);RF_PUT(r,argbuf_set);RF_PUT(r,argbuf_id);
      const struct air_sampler_state *s=&r->sampler;
      for(unsigned j=0;j<3;++j)blob_write_uint32(blob,s->address[j]);
      RF_PUT(s,mag_filter);RF_PUT(s,min_filter);RF_PUT(s,mip_filter);RF_PUT(s,pixel_coord);
      RF_PUT(s,compare_func);RF_PUT(s,max_anisotropy);RF_PUT(s,lod_min);RF_PUT(s,lod_max);
      RF_PUT(s,border_color);RF_PUT(s,reduction);RF_STRING(r->name);RF_STRING(r->type_name);
   }
   for(unsigned i=0;i<info->num_varyings;++i) {
      const struct air_varying *v=&info->varyings[i];
      RF_PUT(v,slot);RF_PUT(v,components);RF_PUT(v,flat);RF_PUT(v,centroid);
      RF_PUT(v,sample);RF_PUT(v,no_perspective);RF_STRING(v->name);
   }
   for(unsigned i=0;i<info->num_vertex_attributes;++i) {
      const struct air_vertex_attribute *v=&info->vertex_attributes[i];
      RF_PUT(v,index);RF_PUT(v,location);RF_PUT(v,components);RF_PUT(v,driver_location);
      RF_PUT(v,bit_size);RF_PUT(v,base_type);RF_PUT(v,used);
      RF_STRING(v->name);RF_STRING(v->type_name);RF_STRING(v->function_constant);
   }
   for(unsigned i=0;i<info->num_notes;++i)RF_STRING(info->notes[i]);
#undef RF_STRING
#undef RF_PUT
   return !blob->out_of_memory;
}
static bool redfin_air_disk_info_get(struct blob_reader *blob,void *owner,struct air_shader_info *info)
{
   memset(info,0,sizeof(*info));
#define RF_GET(object,field) ((object)->field=blob_read_uint32(blob))
#define RF_STRING(value) do {if(!redfin_air_disk_string_get(blob,owner,&(value)))return false;} while(0)
   RF_GET(info,stage);RF_GET(info,num_resources);RF_GET(info,num_varyings);
   RF_GET(info,num_vertex_attributes);RF_GET(info,vertex_attributes_read);
   RF_GET(info,num_render_targets);RF_GET(info,fbfetch_targets);
   RF_GET(info,raster_order_groups);RF_GET(info,num_notes);RF_GET(info,threadgroup_bytes);
   if(blob->overrun||info->num_resources>512||info->num_varyings>128||
      info->num_vertex_attributes>128||info->num_notes>512||
      (info->stage!=MESA_SHADER_VERTEX&&info->stage!=MESA_SHADER_FRAGMENT&&info->stage!=MESA_SHADER_COMPUTE))return false;
   RF_STRING(info->entry_point);
   if(info->num_resources)info->resources=rzalloc_array(owner,struct air_resource,info->num_resources);
   if(info->num_varyings)info->varyings=rzalloc_array(owner,struct air_varying,info->num_varyings);
   if(info->num_vertex_attributes)info->vertex_attributes=rzalloc_array(owner,struct air_vertex_attribute,info->num_vertex_attributes);
   if(info->num_notes)info->notes=rzalloc_array(owner,const char *,info->num_notes);
   if((info->num_resources&&!info->resources)||(info->num_varyings&&!info->varyings)||
      (info->num_vertex_attributes&&!info->vertex_attributes)||(info->num_notes&&!info->notes))return false;
   for(unsigned i=0;i<info->num_resources;++i) {
      struct air_resource *r=&info->resources[i];
      RF_GET(r,kind);RF_GET(r,index);RF_GET(r,size);RF_GET(r,read);RF_GET(r,write);
      RF_GET(r,param);RF_GET(r,inline_sampler);r->sampler_state=blob_read_uint64(blob);
      r->raster_order_group=(int32_t)blob_read_uint32(blob);RF_GET(r,argbuf_set);RF_GET(r,argbuf_id);
      struct air_sampler_state *s=&r->sampler;
      for(unsigned j=0;j<3;++j)s->address[j]=blob_read_uint32(blob);
      RF_GET(s,mag_filter);RF_GET(s,min_filter);RF_GET(s,mip_filter);RF_GET(s,pixel_coord);
      RF_GET(s,compare_func);RF_GET(s,max_anisotropy);RF_GET(s,lod_min);RF_GET(s,lod_max);
      RF_GET(s,border_color);RF_GET(s,reduction);RF_STRING(r->name);RF_STRING(r->type_name);
      if(r->kind>AIR_RESOURCE_SAMPLER)return false;
   }
   for(unsigned i=0;i<info->num_varyings;++i) {
      struct air_varying *v=&info->varyings[i];
      RF_GET(v,slot);RF_GET(v,components);RF_GET(v,flat);RF_GET(v,centroid);
      RF_GET(v,sample);RF_GET(v,no_perspective);RF_STRING(v->name);
   }
   for(unsigned i=0;i<info->num_vertex_attributes;++i) {
      struct air_vertex_attribute *v=&info->vertex_attributes[i];
      RF_GET(v,index);RF_GET(v,location);RF_GET(v,components);RF_GET(v,driver_location);
      RF_GET(v,bit_size);RF_GET(v,base_type);RF_GET(v,used);
      RF_STRING(v->name);RF_STRING(v->type_name);RF_STRING(v->function_constant);
   }
   for(unsigned i=0;i<info->num_notes;++i)RF_STRING(info->notes[i]);
#undef RF_STRING
#undef RF_GET
   return !blob->overrun;
}
static struct disk_cache *redfin_air_disk_open(struct rwa_device *device)
{
   struct redfin_air_translation_cache *cache=&device->translation_cache;
   if(!cache->disk_attempted) {
      cache->disk_attempted=true;
      if(!device->software)cache->disk=redfin_mesa_disk_cache_create("redfin-air-fd620-v1",REDFIN_MESA_CACHE_BUILD_ID,0);
   }
   return cache->disk;
}
static void redfin_air_disk_store(struct rwa_device *device,const struct redfin_air_cache_entry *entry)
{
   struct disk_cache *cache=redfin_air_disk_open(device);if(!cache)return;
   struct blob data;blob_init(&data);
   blob_write_uint32(&data,0x52464143u);blob_write_uint32(&data,1);
   blob_write_uint64(&data,entry->key_bytes);blob_write_uint64(&data,entry->nir_bytes);
   blob_write_bytes(&data,entry->key,entry->key_bytes);blob_write_bytes(&data,entry->nir,entry->nir_bytes);
   if(redfin_air_disk_info_put(&data,&entry->info)&&data.size<=REDFIN_MESA_DISK_ITEM) {
      cache_key key;disk_cache_compute_key(cache,entry->key,entry->key_bytes,key);
      disk_cache_put(cache,key,data.data,data.size,NULL);
   }
   blob_finish(&data);
}
static nir_shader *redfin_air_disk_load(struct rwa_device *device,void *owner,const struct blob *exact,
   struct air_shader_info *info)
{
   struct redfin_air_translation_cache *cache=&device->translation_cache;
   struct disk_cache *disk=redfin_air_disk_open(device);if(!disk)return NULL;
   cache_key key;disk_cache_compute_key(disk,exact->data,exact->size,key);
   size_t size=0;void *data=disk_cache_get(disk,key,&size);
   if(!data){disk_cache_remove(disk,key);return NULL;}
   void *temporary=ralloc_context(NULL);nir_shader *nir=NULL;
   struct blob_reader reader;blob_reader_init(&reader,data,size);
   uint32_t magic=blob_read_uint32(&reader),version=blob_read_uint32(&reader);
   uint64_t key_bytes=blob_read_uint64(&reader),nir_bytes=blob_read_uint64(&reader);
   if(!temporary||reader.overrun||magic!=0x52464143u||version!=1||key_bytes!=exact->size||
      !nir_bytes||nir_bytes>REDFIN_AIR_CACHE_BYTES)goto invalid;
   const void *stored=blob_read_bytes(&reader,key_bytes);
   if(reader.overrun||!stored||memcmp(stored,exact->data,exact->size))goto invalid;
   const void *binary=blob_read_bytes(&reader,nir_bytes);
   if(reader.overrun||!binary)goto invalid;
   struct air_shader_info copied;
   if(!redfin_air_disk_info_get(&reader,temporary,&copied)||reader.current!=reader.end)goto invalid;
   struct blob_reader nir_reader;blob_reader_init(&nir_reader,binary,nir_bytes);
   nir=nir_deserialize(temporary,device->nir_options,&nir_reader);
   if(!nir||nir_reader.overrun||nir_reader.current!=nir_reader.end||nir->info.stage!=copied.stage)goto invalid;
   ralloc_adopt(owner,temporary);ralloc_free(temporary);free(data);*info=copied;return nir;
invalid:
   ralloc_free(temporary);free(data);++cache->disk_invalid;disk_cache_remove(disk,key);return NULL;
}
