/* SPDX-License-Identifier: MIT
 * Host contract over real AIR/NIR, without executing a software renderer.
 * A two-entry instance forces eviction while callers retain independent NIR.
 */
#include <stdarg.h>
#define REDFIN_AIR_CACHE_ENTRIES 2u
#include "compiler/air/redfin_metal_translation_cache.h"
#include "compiler/air/redfin_metal_function_constants.h"
#include "pipe/p_screen.h"
#include "util/disk_cache_os.h"
struct rwa_device {
   const nir_shader_compiler_options *nir_options;
   struct redfin_air_translation_cache translation_cache;
   struct redfin_air_stage_cache stage_cache;
   struct pipe_context *pipe;
   struct pipe_screen *screen;
   bool software;
};
static void say(char *out,size_t bytes,const char *format,...)
{
   va_list args;va_start(args,format);if(out&&bytes)vsnprintf(out,bytes,format,args);va_end(args);
}
#include "compiler/air/redfin_metal_function_constants.inc"
#include "compiler/air/redfin_metal_translation_cache.inc"
#include "redfin_metal_cache_finalizer.inc"
/* This compiler-only fixture has no graphics bindings to invalidate. */
static void rwa_redfin_graphics_invalidate(struct rwa_device *device){(void)device;}
#include "compiler/air/redfin_metal_stage_cache.inc"

static void redfin_host_cache_require(bool valid,const char *reason)
{ if(!valid)errx(1,"AIR template cache: %s",reason); }

/* No shader executes here. The callback owns the actual finalized NIR as a
 * state token, so allocation/deletion counts expose shared-state lifetimes.
 * Native pixel probes separately use the real A620 Gallium callbacks. */
static unsigned redfin_host_states_created,redfin_host_states_deleted;
static void *redfin_host_bound[2];
static void *redfin_host_state_create(struct pipe_context *pipe,const struct pipe_shader_state *state)
{
   redfin_host_cache_require(state->type==PIPE_SHADER_IR_NIR&&state->ir.nir,"real finalized NIR state");
   nir_validate_shader(state->ir.nir,"state creation");++redfin_host_states_created;return state->ir.nir;
}
static void redfin_host_bind_vs(struct pipe_context *pipe,void *state) {redfin_host_bound[0]=state;}
static void redfin_host_bind_fs(struct pipe_context *pipe,void *state) {redfin_host_bound[1]=state;}
static void redfin_host_state_delete(struct pipe_context *pipe,void *state)
{
   redfin_host_cache_require(state&&state!=redfin_host_bound[0]&&state!=redfin_host_bound[1],"unbind before last-state deletion");
   nir_validate_shader(state,"state deletion");++redfin_host_states_deleted;ralloc_free(state);
}
static void redfin_host_stages_run(struct rwa_device *device,nir_shader *first,nir_shader *second)
{
   struct pipe_context pipe={.create_vs_state=redfin_host_state_create,.create_fs_state=redfin_host_state_create,
      .bind_vs_state=redfin_host_bind_vs,.bind_fs_state=redfin_host_bind_fs,
      .delete_vs_state=redfin_host_state_delete,.delete_fs_state=redfin_host_state_delete};
   struct pipe_screen screen={.caps={.fs_position_is_sysval=true}};
   device->pipe=&pipe;device->screen=&screen;
   char why[512]={0};redfin_host_states_created=redfin_host_states_deleted=0;
   nir_shader_gather_info(first,nir_shader_get_entrypoint(first));
   nir_shader_gather_info(second,nir_shader_get_entrypoint(second));
   struct redfin_air_stage *a=redfin_air_stage_create(device,first,why,sizeof(why));
   struct redfin_air_stage *b=redfin_air_stage_create(device,second,why,sizeof(why));
   redfin_host_cache_require(a&&b&&a==b&&device->stage_cache.hits==1&&redfin_host_states_created==1,
      "equivalent finalized stages reuse one state");
   for(unsigned i=0;i<2;++i) {
      nir_shader *different=nir_shader_clone(NULL,first);
      different->info.label=ralloc_asprintf(different,"host eviction variant %u",i);
      struct redfin_air_stage *variant=redfin_air_stage_create(device,different,why,sizeof(why));
      redfin_host_cache_require(variant!=NULL,why);redfin_air_stage_release(variant);ralloc_free(different);
   }
   redfin_host_cache_require(device->stage_cache.evictions==1&&device->stage_cache.entries==2&&
      redfin_host_states_deleted==0,"eviction preserves retained pipelines");
   nir_validate_shader(a->cso,"retained real finalized NIR after stage eviction");
   redfin_air_stage_cache_finish(&device->stage_cache);
   redfin_host_cache_require(redfin_host_states_deleted==2,"cache teardown releases only unreferenced states");
   redfin_air_stage_release(a);
   redfin_host_cache_require(redfin_host_states_deleted==2,"independent pipeline reference");
   if(b->vertex)pipe.bind_vs_state(&pipe,b->cso);else pipe.bind_fs_state(&pipe,b->cso);
   redfin_air_stage_release(b);
   redfin_host_cache_require(redfin_host_states_created==3&&redfin_host_states_deleted==3,"last pipeline releases shared state once");
   device->pipe=NULL;device->screen=NULL;
   printf("; AIR STAGE CACHE: real-finalizer=1 equivalent-state-hit=1 forced-LRU=1 surviving-pipelines=1 last-reference-release=1 callback-only-no-shader-execution=1\n");
}

static void redfin_host_disk_run(const void *bitcode,size_t bytes,const struct redfin_metal_constants *native,
   const struct air_shader_info *original)
{
   const nir_shader_compiler_options *options=ir3_get_compiler_options(compiler);
   struct rwa_device later={.nir_options=options};void *owner=ralloc_context(NULL);
   struct air_shader_info info={0};char why[512]={0};uint64_t stats[REDFIN_AIR_CACHE_STAT_WORDS]={0};
   nir_shader *nir=redfin_air_cached_translate(&later,owner,bitcode,bytes,NULL,native,&info,why,sizeof(why));
   rwa_redfin_translation_cache_statistics(&later,stats,REDFIN_AIR_CACHE_STAT_WORDS);
   redfin_host_cache_require(nir&&stats[11]&&stats[12]&&later.translation_cache.hits==0,
      "fresh context restores the real file without a memory-cache hit");
   redfin_host_cache_require(info.num_resources==original->num_resources&&info.num_varyings==original->num_varyings&&
      info.num_vertex_attributes==original->num_vertex_attributes&&info.vertex_attributes_read==original->vertex_attributes_read&&
      info.num_notes==original->num_notes&&info.threadgroup_bytes==original->threadgroup_bytes&&
      info.fbfetch_targets==original->fbfetch_targets&&info.raster_order_groups==original->raster_order_groups&&
      !strcmp(info.entry_point,original->entry_point),"persistent unpruned reflection counts and flags");
   nir_validate_shader(nir,"actual file-restored NIR");
   struct disk_cache *disk=later.translation_cache.disk;
   redfin_host_cache_require(disk&&disk->max_size==REDFIN_MESA_DISK_TARGET,"explicit disk eviction target");
   struct blob exact;blob_init(&exact);
   redfin_host_cache_require(redfin_air_cache_key(&exact,bitcode,bytes,NULL,native),"persistent exact key");
   cache_key key;disk_cache_compute_key(disk,exact.data,exact.size,key);
   char *filename=disk_cache_get_cache_filename(disk,key);
   size_t saved_bytes=0;void *saved=disk_cache_get(disk,key,&saved_bytes);
   redfin_host_cache_require(filename&&saved&&saved_bytes>=24,"real cache file exists");
   void *too_large=malloc(REDFIN_MESA_DISK_PENDING+1u);
   redfin_host_cache_require(too_large!=NULL,"queue budget fixture allocation");
   memset(too_large,0x5a,REDFIN_MESA_DISK_PENDING+1u);
   uint64_t before[REDFIN_MESA_DISK_WORDS],after[REDFIN_MESA_DISK_WORDS];
   redfin_mesa_disk_cache_statistics(disk,before);
   disk_cache_put(disk,key,too_large,REDFIN_MESA_DISK_PENDING+1u,NULL);free(too_large);
   redfin_mesa_disk_cache_statistics(disk,after);
   redfin_host_cache_require(after[4]==before[4]+1&&after[5]<=REDFIN_MESA_DISK_PENDING,"background queue rejects oversized work without stalling");
   /* A valid Mesa CRC with an old AIR record version must be a cold miss. */
   /* Content-addressed Mesa entries are immutable: replace the fixture file
    * explicitly, as the production invalid-record path also does. */
   ((uint32_t *)saved)[1]=99;disk_cache_remove(disk,key);
   disk_cache_put(disk,key,saved,saved_bytes,NULL);free(saved);
   redfin_air_cache_finish(&later.translation_cache);
   struct rwa_device stale={.nir_options=options};struct air_shader_info rebuilt={0};
   nir_shader *fresh=redfin_air_cached_translate(&stale,owner,bitcode,bytes,NULL,native,&rebuilt,why,sizeof(why));
   rwa_redfin_translation_cache_statistics(&stale,stats,REDFIN_AIR_CACHE_STAT_WORDS);
   redfin_host_cache_require(fresh&&stats[17]==1,"old AIR version rejected and compiled again");
   nir_validate_shader(fresh,"cold fallback from stale disk schema");
   redfin_air_cache_finish(&stale.translation_cache);
   /* Damage the actual compressed file: Mesa must reject its CRC and repair. */
   int fd=open(filename,O_RDWR|O_CLOEXEC|O_NOFOLLOW);struct stat st;unsigned char value;
   redfin_host_cache_require(fd>=0&&!fstat(fd,&st)&&st.st_size>0&&
      pread(fd,&value,1,st.st_size-1)==1,"owned cache corruption fixture");
   value^=0x80;redfin_host_cache_require(pwrite(fd,&value,1,st.st_size-1)==1,"corrupt one compressed byte");close(fd);
   struct rwa_device corrupt={.nir_options=options};
   nir_shader *repaired=redfin_air_cached_translate(&corrupt,owner,bitcode,bytes,NULL,native,&rebuilt,why,sizeof(why));
   rwa_redfin_translation_cache_statistics(&corrupt,stats,REDFIN_AIR_CACHE_STAT_WORDS);
   redfin_host_cache_require(repaired&&stats[13]&&stats[12]==0,"CRC failure falls back to real translation");
   nir_validate_shader(repaired,"cold fallback from corrupted compressed file");
   redfin_air_cache_finish(&corrupt.translation_cache);
   struct rwa_device recovered={.nir_options=options};
   nir_shader *restored=redfin_air_cached_translate(&recovered,owner,bitcode,bytes,NULL,native,&rebuilt,why,sizeof(why));
   rwa_redfin_translation_cache_statistics(&recovered,stats,REDFIN_AIR_CACHE_STAT_WORDS);
   redfin_host_cache_require(restored&&stats[12]&&stats[17]==0,"next fresh context reads the repaired file");
   nir_validate_shader(restored,"repaired file survives another context");
   redfin_air_cache_finish(&recovered.translation_cache);
   struct disk_cache *other=redfin_mesa_disk_cache_create("redfin-air-fd620-v1","different-compiler-contract",0);
   redfin_host_cache_require(other!=NULL,"separate compiler namespace fixture");
   cache_key other_key;disk_cache_compute_key(other,exact.data,exact.size,other_key);
   size_t wrong_size=0;void *wrong=disk_cache_get(other,other_key,&wrong_size);
   redfin_host_cache_require(!wrong&&!wrong_size,"different compiler identity never reuses cached NIR");
   disk_cache_destroy(other);free(filename);blob_finish(&exact);ralloc_free(owner);
   printf("; AIR DISK CACHE: fresh-context=1 real-NIR-and-reflection=1 bounded-async-queue=1 stale-version-fallback=1 CRC-rejection-repair=1 compiler-namespace=1\n");
}

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
   if(first->info.stage==MESA_SHADER_VERTEX||first->info.stage==MESA_SHADER_FRAGMENT)
      redfin_host_stages_run(&device,first,second);
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
   redfin_host_disk_run(bitcode,bytes,&native,&second_info);
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
