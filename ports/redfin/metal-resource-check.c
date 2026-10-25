/* SPDX-License-Identifier: MIT */
/* The same authored AIR contract runs on the Mac compiler and actual A620.
 * Host execution checks translation semantics; only a phone run proves GPU use.
 */
#include "air_metal.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int redfin_metal_resource_check(const char *path, uint64_t nonce);

int
redfin_metal_resource_check(const char *path, uint64_t nonce)
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
   struct rwa_buffer *buffers[2] = {NULL, NULL};
   struct rwa_texture *texture = NULL;
   struct rwa_sampler *samplers[2] = {NULL, NULL};
   unsigned completed = 0;
   if (!device)
      goto done;
   printf("REDFIN METAL RESOURCE: boot=%016llx backend=%s\n",
          (unsigned long long)nonce, rwa_device_name(device));
   struct rwa_compute_info info = {0};
   compute = rwa_compute_create(device, bitcode, length, "redfin_resource_contract",
                                 &info, why, sizeof(why));
   if (!compute)
      goto done;
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
   for (unsigned round = 0; round < 32; round++) {
      uint32_t seed = (((uint32_t)nonce + (round / 8) * 0x13715af8u) & ~7u) | (round & 7);
      for (unsigned i = 0; i < 8; i++)
         control[i] = seed ^ (i * 0x1987abcd);
      memset(output, 0xa5, 256);
      if (rwa_dispatch(compute, &bindings, groups, groups, why, sizeof(why)))
         goto done;
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
         if (((uint8_t *)output)[i] != 0xa5) {
            snprintf(why, sizeof(why), "round %u modified output guard %u", round, i);
            goto done;
         }
      }
      completed++;
   }
done:
   printf("REDFIN METAL RESOURCE RESULT: boot=%016llx rounds=%u private-branch-alias-sampler-phi-helper-null-global-bits-dynamic-lanes-guards=%u%s%s\n",
          (unsigned long long)nonce, completed, completed == 32,
          completed == 32 ? "" : " reason=", completed == 32 ? "" : why);
   if (samplers[1]) rwa_sampler_destroy(samplers[1]);
   if (samplers[0]) rwa_sampler_destroy(samplers[0]);
   if (texture) rwa_texture_destroy(texture);
   if (buffers[1]) rwa_buffer_destroy(buffers[1]);
   if (buffers[0]) rwa_buffer_destroy(buffers[0]);
   if (compute) rwa_compute_destroy(compute);
   if (device) rwa_device_close(device);
   free(bitcode);
   return completed == 32;
}

#ifdef REDFIN_METAL_RESOURCE_STANDALONE
int main(int argc, char **argv)
{
   return argc == 2 && redfin_metal_resource_check(argv[1], 0x4ac72e981b630f40ull) ? 0 : 1;
}
#endif
