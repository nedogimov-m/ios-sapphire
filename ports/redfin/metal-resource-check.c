#include "metal-bindings.h"
/* SPDX-License-Identifier: MIT */
/* The same authored AIR contract runs on the Mac compiler and actual A620.
 * Host execution checks translation semantics; only a phone run proves GPU use.
 */
#include "air_metal.h"
#include "redfin_metal_function_constants.h"
#include "metal-translation-cache.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "metal-queued-resource-check.inc"

int redfin_metal_resource_check(const char *path, uint64_t nonce);

static int
redfin_resource_context(const char *path,uint64_t nonce,unsigned phase,uint64_t statistics[REDFIN_AIR_CACHE_STAT_WORDS])
{
   char why[1024] = {0};
   FILE *file = fopen(path, "rb");
   if (!file) {
      printf("REDFIN METAL RESOURCE RESULT: boot=%016llx missing-authored-AIR=1\n",
             (unsigned long long)nonce);
      return 0;
   }
   fseek(file, 0, SEEK_END);
   long length = ftell(file);
   rewind(file);
   void *bitcode = length > 0 && length <= 1048576 ? malloc((size_t)length) : NULL;
   int loaded = bitcode && fread(bitcode, 1, length, file) == (size_t)length;
   fclose(file);
   struct rwa_device *device = loaded ? rwa_device_open(why, sizeof(why)) : NULL;
   struct rwa_compute *compute = NULL;
   struct rwa_compute *enabled = NULL;
   struct rwa_buffer *buffers[2] = {NULL, NULL};
   struct rwa_texture *texture = NULL;
   struct rwa_sampler *samplers[2] = {NULL, NULL};
   unsigned completed = 0;
   int requirements = 0, missing_refused = 0, enabled_pixels = 0;
   int scoped=0,scope_ok=1,lower_clean=0;uint64_t binding_stats[REDFIN_METAL_BINDING_WORDS]={0};
   if (!device)
      goto done;
   printf("REDFIN METAL RESOURCE: boot=%016llx backend=%s\n",
          (unsigned long long)nonce, rwa_device_name(device));
   struct rwa_compute_info info = {0};
   struct redfin_metal_constant extra = {.index = 71, .bytes = 1};
   struct redfin_metal_constants values = {.values = &extra, .count = 1};
   compute = rwa_redfin_compute_create(device, bitcode, length, "redfin_resource_contract",
                                        &info, &values, why, sizeof(why));
   if (!compute)
      goto done;
   requirements = info.buffers == 2 && info.textures == 1 && info.samplers == 2;
   if (!requirements) {
      snprintf(why, sizeof(why), "inactive declarations still demand buffers=%u textures=%u samplers=%u",
               info.buffers, info.textures, info.samplers);
      goto done;
   }
   extra.words[0] = 1;
   enabled = rwa_redfin_compute_create(device, bitcode, length, "redfin_resource_contract",
                                        &info, &values, why, sizeof(why));
   if (!enabled)
      goto done;
   if (info.buffers != 8 || info.textures != 10 || info.samplers != 6) {
      snprintf(why, sizeof(why), "active high binding declarations were lost");
      goto done;
   }
   buffers[0] = rwa_buffer_create(device, 256, why, sizeof(why));
   buffers[1] = rwa_buffer_create(device, 32, why, sizeof(why));
   struct rwa_texture_shape shape = {
      .pixel_format = 70, .type = 2, .width = 2, .height = 1, .depth = 1,
      .array_length = 1, .mip_levels = 1, .sample_count = 1, .usage = 1,
   };
   texture = rwa_texture_create(device, &shape, why, sizeof(why));
   if (!buffers[0] || !buffers[1] || !texture)
      goto done;
   const uint8_t pixels[8] = {0, 64, 128, 255, 255, 192, 64, 255};
   const unsigned origin[3] = {0, 0, 0}, extent[3] = {2, 1, 1};
   if (rwa_texture_write(texture, 0, 0, origin, extent, pixels, 8, why, sizeof(why)))
      goto done;
   for (unsigned i = 0; i < 2; i++) {
      struct rwa_sampler_state state = {
         .address = {0, 0, 0}, .min_filter = i, .mag_filter = i,
         .max_anisotropy = 1, .normalized_coordinates = 1, .lod_max = 16,
      };
      samplers[i] = rwa_sampler_create(device, &state, why, sizeof(why));
   }
   uint32_t *output = rwa_buffer_map(buffers[0]);
   uint32_t *control = rwa_buffer_map(buffers[1]);
   if (!samplers[0] || !samplers[1] || !output || !control)
      goto done;
   struct rwa_texture *textures[1] = {texture};
   struct rwa_bindings bindings = {
      .buffers = buffers, .buffer_count = 2,
      .textures = textures, .texture_count = 1,
      .samplers = samplers, .sampler_count = 2,
   };
   const unsigned groups[3] = {1, 1, 1};
   memset(output, 0xa5, 256);
   missing_refused = rwa_dispatch(enabled, &bindings, groups, groups, why, sizeof(why)) < 0;
   for (unsigned i = 0; i < 256; i++)
      missing_refused &= ((uint8_t *)output)[i] == 0xa5;
   if (!missing_refused) {
      snprintf(why, sizeof(why), "active missing bindings were not refused before execution");
      goto done;
   }
   if(phase) {if(rwa_commands_begin(device,why,sizeof(why)))goto done;scoped=1;}
   for (unsigned round = 0; round < 32; round++) {
      uint32_t seed = ((((uint32_t)nonce ^ (phase*0x9816e3f0u)) + (round / 8) * 0x13715af8u) & ~7u) | (round & 7);
      for (unsigned i = 0; i < 8; i++)
         control[i] = seed ^ (i * 0x1987abcd);
      memset(output, 0xa5, 256);
      if (rwa_dispatch(compute, &bindings, groups, groups, why, sizeof(why)))
         goto done;
      if(scoped) {output=rwa_buffer_map(buffers[0]);if(!output)goto done;}
      unsigned mode = seed & 7;
      int nearest = (mode & 4) || (mode & 1);
      const float expected[3] = {
         mode & 2 ? 0 : nearest ? 1 : 0.5f,
         mode & 2 ? 0 : (nearest ? 192.0f : 128.0f) / 255.0f,
         mode & 2 ? 0 : (nearest ? 64.0f : 96.0f) / 255.0f,
      };
      float actual[3];
      memcpy(actual, output, sizeof(actual));
      for (unsigned i = 0; i < 3; i++) {
         if (!isfinite(actual[i]) || fabsf(actual[i] - expected[i]) > 1.1f / 255.0f) {
            printf("REDFIN METAL RESOURCE WORDS: round=%u seed=%08x", round, seed);
            for (unsigned word = 0; word < 9; word++) printf(" %08x", output[word]);
            printf("\n");
            snprintf(why, sizeof(why), "round %u sampler/null component %u: %g expected %g",
                     round, i, actual[i], expected[i]);
            goto done;
         }
      }
      const uint32_t words[6] = {
         mode & 4 ? 0x12345678u : control[mode & 3],
         mode & 2 ? 0 : 2, 0x31415926, seed, 0x7fc12345,
         mode & 1 ? 8737 : 4369,
      };
      for (unsigned i = 0; i < 6; i++) {
         if (output[3 + i] != words[i]) {
            snprintf(why, sizeof(why), "round %u word %u: %08x expected %08x",
                     round, 3 + i, output[3 + i], words[i]);
            goto done;
         }
      }
      for (unsigned i = 36; i < 256; i++) {
         if (i >= 40 && i < 44) continue;
         if (((uint8_t *)output)[i] != 0xa5) {
            snprintf(why, sizeof(why), "round %u modified output guard %u", round, i);
            goto done;
         }
      }
      if (output[10] != 0x100) {
         snprintf(why, sizeof(why), "defined false/true bytes in an undefined word changed: %08x", output[10]);
         goto done;
      }
      completed++;
   }
   struct rwa_buffer *full_buffers[8] = {[0] = buffers[0], [1] = buffers[1], [7] = buffers[1]};
   struct rwa_texture *full_textures[10] = {[0] = texture, [9] = texture};
   struct rwa_sampler *full_samplers[6] = {[0] = samplers[0], [1] = samplers[1], [5] = samplers[0]};
   struct rwa_bindings full = {
      .buffers = full_buffers, .buffer_count = 8, .textures = full_textures, .texture_count = 10,
      .samplers = full_samplers, .sampler_count = 6,
   };
   memset(output, 0xa5, 256);
   if (rwa_dispatch(enabled, &full, groups, groups, why, sizeof(why)))
      goto done;
   if(scoped) {output=rwa_buffer_map(buffers[0]);if(!output)goto done;}
   enabled_pixels = output[9] == (control[0] ^ 0x3f800000u) && output[10] == 0x101;
   for (unsigned i = 44; i < 256; i++)
      enabled_pixels &= ((uint8_t *)output)[i] == 0xa5;
   if (!enabled_pixels)
      snprintf(why, sizeof(why), "enabled high bindings returned incorrect output/guards");
   if(scoped&&enabled_pixels) {
      memset(output,0xa5,256);
      if(rwa_dispatch(compute,&bindings,groups,groups,why,sizeof(why)))goto done;
      output=rwa_buffer_map(buffers[0]);
      lower_clean=output&&output[9]==0xa5a5a5a5u&&output[10]==0x100;
      if(output)for(unsigned i=44;i<256;++i)lower_clean&=((uint8_t *)output)[i]==0xa5;
   }
done:
   if(scoped&&rwa_commands_end(device,why,sizeof(why)))scope_ok=0;
   if(device&&!rwa_redfin_binding_statistics(device,binding_stats,REDFIN_METAL_BINDING_WORDS)) {
      scope_ok=scope_ok&&!binding_stats[10]&&!binding_stats[11];
      if(phase)scope_ok=scope_ok&&lower_clean&&binding_stats[2]&&binding_stats[4];
   } else scope_ok=0;
   if(phase)printf("REDFIN METAL BINDING RESOURCE: boot=%016llx active-high-to-low=%u descriptor-skips=%llu stale-slots-cleared=%llu live-slots=%llu passed=%u\n",
      (unsigned long long)nonce,lower_clean,(unsigned long long)binding_stats[2],(unsigned long long)binding_stats[4],
      (unsigned long long)binding_stats[10],scope_ok);
   printf("REDFIN METAL RESOURCE RESULT: boot=%016llx rounds=%u private-branch-alias-sampler-phi-helper-null-global-bits-dynamic-lanes-guards=%u inactive-requirements=%u active-missing-refused=%u active-high-bindings-pixels-guards=%u%s%s\n",
          (unsigned long long)nonce, completed, completed == 32,
          requirements, missing_refused, enabled_pixels,
          completed == 32 && enabled_pixels ? "" : " reason=", completed == 32 && enabled_pixels ? "" : why);
   if (samplers[1]) rwa_sampler_destroy(samplers[1]);
   if (samplers[0]) rwa_sampler_destroy(samplers[0]);
   if (texture) rwa_texture_destroy(texture);
   if (buffers[1]) rwa_buffer_destroy(buffers[1]);
   if (buffers[0]) rwa_buffer_destroy(buffers[0]);
   if (compute) rwa_compute_destroy(compute);
   if (enabled) rwa_compute_destroy(enabled);
   if (device) rwa_redfin_translation_cache_statistics(device,statistics,REDFIN_AIR_CACHE_STAT_WORDS);
   if (device) rwa_device_close(device);
   free(bitcode);
   return completed == 32 && requirements && missing_refused && enabled_pixels && scope_ok;
}

int redfin_metal_resource_check(const char *path,uint64_t nonce)
{
   uint64_t first[REDFIN_AIR_CACHE_STAT_WORDS]={0},second[REDFIN_AIR_CACHE_STAT_WORDS]={0};
   int cold=redfin_resource_context(path,nonce,0,first);
   int warm=cold&&redfin_resource_context(path,nonce,1,second);
   int persistent=warm&&second[11]&&second[12]>=2&&second[18]>first[18];
   printf("REDFIN METAL PERSISTENCE RESULT: boot=%016llx contexts=2 cold-resource-pixels=%u warm-resource-pixels=%u air-file-hits=%llu ir3-file-hits=%llu pending-bytes=%llu stale-records=%llu passed=%u\n",
      (unsigned long long)nonce,cold,warm,(unsigned long long)second[12],
      (unsigned long long)(second[18]-first[18]),(unsigned long long)second[16],
      (unsigned long long)second[17],persistent);
   return persistent&&redfin_resource_queued(nonce);
}

#ifdef REDFIN_METAL_RESOURCE_STANDALONE
int main(int argc, char **argv)
{
   return argc == 2 && redfin_metal_resource_check(argv[1], 0x4ac72e981b630f40ull) ? 0 : 1;
}
#endif
