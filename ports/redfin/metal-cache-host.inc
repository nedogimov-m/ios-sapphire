/* SPDX-License-Identifier: MIT
 * Host contract over real AIR/NIR, without executing a software renderer.
 * A two-entry instance forces eviction while callers retain independent NIR.
 */
#include <stdarg.h>
#define REDFIN_AIR_CACHE_ENTRIES 2u
#include "compiler/air/redfin_metal_translation_cache.h"
#include "compiler/air/redfin_metal_function_constants.h"
struct rwa_device {
   const nir_shader_compiler_options *nir_options;
   struct redfin_air_translation_cache translation_cache;
   struct redfin_air_stage_cache stage_cache;
};
static void say(char *out,size_t bytes,const char *format,...)
{
   va_list args;va_start(args,format);if(out&&bytes)vsnprintf(out,bytes,format,args);va_end(args);
}
#include "compiler/air/redfin_metal_function_constants.inc"
#include "compiler/air/redfin_metal_translation_cache.inc"

static void redfin_host_cache_require(bool valid,const char *reason)
{ if(!valid)errx(1,"AIR template cache: %s",reason); }

static void redfin_host_cache_run(const void *bitcode,size_t bytes,
   const struct air_to_nir_options *options)
{
   struct rwa_device device={.nir_options=ir3_get_compiler_options(compiler)};
   void *first_owner=ralloc_context(NULL),*second_owner=ralloc_context(NULL),*third_owner=ralloc_context(NULL);
   struct redfin_metal_constant fields[REDFIN_METAL_CONSTANTS_MAX]={0},reversed[REDFIN_METAL_CONSTANTS_MAX]={0};
   unsigned count=0;
   for(unsigned i=0;i<options->num_constants;++i)if(!options->constants[i].undefined) {
      redfin_host_cache_require(count<REDFIN_METAL_CONSTANTS_MAX,"bounded snapshot");
      fields[count].index=options->constants[i].index;fields[count].bytes=32;
      memcpy(fields[count].words,options->constants[i].words,32);++count;
   }
   for(unsigned i=0;i<count;++i)reversed[i]=fields[count-1-i];
   struct redfin_metal_constants native={.values=fields,.count=count},reverse={.values=reversed,.count=count};
   char why[512]={0};struct air_shader_info first_info={0},second_info={0},third_info={0};
   nir_shader *first=redfin_air_cached_translate(&device,first_owner,bitcode,bytes,NULL,&native,&first_info,why,sizeof(why));
   redfin_host_cache_require(first!=NULL,why);
   nir_shader *second=redfin_air_cached_translate(&device,second_owner,bitcode,bytes,NULL,&reverse,&second_info,why,sizeof(why));
   redfin_host_cache_require(second&&second!=first&&device.translation_cache.hits==1,"canonical reordered key hit with independent NIR");
   nir_validate_shader(second,"actual deserialized template");
   redfin_host_cache_require(first_info.entry_point&&second_info.entry_point&&
      first_info.entry_point!=second_info.entry_point&&!strcmp(first_info.entry_point,second_info.entry_point),"independent entry metadata");
   redfin_host_cache_require(first_info.num_resources==second_info.num_resources&&
      first_info.num_varyings==second_info.num_varyings&&
      first_info.num_vertex_attributes==second_info.num_vertex_attributes,"complete interface counts");
   if(first_info.num_resources) {
      redfin_host_cache_require(first_info.resources!=second_info.resources,"independent resource arrays");
      unsigned index=second_info.resources[0].index;first_info.resources[0].index^=0xff;
      redfin_host_cache_require(second_info.resources[0].index==index,"resource mutation isolation");
   }
   if(first_info.num_varyings) {
      redfin_host_cache_require(first_info.varyings!=second_info.varyings,"independent varying arrays");
      unsigned slot=second_info.varyings[0].slot;first_info.varyings[0].slot^=0xff;
      redfin_host_cache_require(second_info.varyings[0].slot==slot,"varying mutation isolation");
   }
   if(first_info.num_vertex_attributes)redfin_host_cache_require(
      first_info.vertex_attributes!=second_info.vertex_attributes,"independent attribute arrays");
   char saved_name[4097];snprintf(saved_name,sizeof(saved_name),"%s",second_info.entry_point);
   char *name=ralloc_strdup(third_owner,saved_name);
   ralloc_free(first_owner);first_owner=NULL;
   /* Entry presence is part of the key even when the selected function agrees. */
   nir_shader *third=redfin_air_cached_translate(&device,third_owner,bitcode,bytes,name,&native,&third_info,why,sizeof(why));
   redfin_host_cache_require(third&&device.translation_cache.misses==2,"explicit entry has its own key");
   /* Deliberately insert a third owned, serialized real NIR template to force
    * LRU eviction without assuming a different specialization is valid. */
   struct blob eviction;blob_init(&eviction);redfin_air_key_u32(&eviction,0x45564943u);
   redfin_air_cache_insert(&device,&eviction,_mesa_hash_data(eviction.data,eviction.size),second,&second_info);
   blob_finish(&eviction);
   redfin_host_cache_require(device.translation_cache.evictions==1&&device.translation_cache.entries==2&&
      device.translation_cache.bytes<=REDFIN_AIR_CACHE_BYTES,"bounded forced LRU");
   nir_validate_shader(second,"live NIR after its cached template was evicted");
   ralloc_free(third_owner);third_owner=NULL;
   redfin_air_cache_finish(&device.translation_cache);
   nir_validate_shader(second,"live NIR after all templates and other callers released");
   redfin_host_cache_require(!strcmp(second_info.entry_point,saved_name),"surviving metadata");
   /* Presence, lengths and exact bytes are semantically significant. */
   struct blob legacy,empty;blob_init(&legacy);blob_init(&empty);
   struct redfin_metal_constants undefined={0};
   redfin_host_cache_require(redfin_air_cache_key(&legacy,bitcode,bytes,NULL,NULL)&&
      redfin_air_cache_key(&empty,bitcode,bytes,NULL,&undefined)&&
      (legacy.size!=empty.size||memcmp(legacy.data,empty.data,legacy.size)),"legacy versus explicit undefined key");
   blob_finish(&legacy);blob_finish(&empty);
   struct redfin_metal_constants invalid={.reserved=1};
   nir_shader *refused=redfin_air_cached_translate(&device,second_owner,bitcode,bytes,NULL,&invalid,&third_info,why,sizeof(why));
   redfin_host_cache_require(!refused&&!device.translation_cache.entries,"invalid snapshot never inserted");
   ralloc_free(second_owner);
   printf("; AIR CACHE: reordered-hit=1 independent-NIR-and-metadata=1 real-serialization=1 forced-LRU=1 surviving-release=1 undefined-distinction=1 invalid-refusal=1\n");
}
