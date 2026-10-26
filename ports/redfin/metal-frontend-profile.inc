/* SPDX-License-Identifier: MIT
 * Observe the actual existing runtime paths under their frontend gate.
 * All preparation, copies, resolves, fences and error results stay native.
 */
#include "util/os_time.h"

static uint64_t rwa_redfin_profile_clock(void)
{return (uint64_t)os_time_get_nano();}

static void rwa_redfin_profile_elapsed(struct rwa_device *device,unsigned field,uint64_t began)
{
   uint64_t now=rwa_redfin_profile_clock();
   if(device&&now>=began)device->frontend_stats[field]+=now-began;
}

#include "redfin_metal_constant_snapshot.inc"

int rwa_redfin_frontend_statistics(struct rwa_device *device,uint64_t *out,size_t words)
{
   if(!device||!out||words!=REDFIN_METAL_FRONTEND_WORDS)return -1;
   memcpy(out,device->frontend_stats,sizeof(device->frontend_stats));return 0;
}

static int rwa_redfin_profile_constant_snapshot(struct rwa_device *device,
   const struct air_resource *r,struct rwa_buffer *buffer,size_t offset,size_t bytes,
   struct pipe_constant_buffer *out,char *why,size_t why_size)
{
   if(!buffer||buffer->device!=device||!buffer->res||buffer->res->target!=PIPE_BUFFER||
      !bytes||offset>buffer->size||bytes>buffer->size-offset||
      offset>buffer->res->width0||bytes>buffer->res->width0-offset) {
      say(why,why_size,"constant snapshot exceeds its actual logical/native buffer");return -1;
   }
   uint64_t *s=device->frontend_stats;
   ++s[RF_MFP_CONSTANT_UPLOADS];s[RF_MFP_CONSTANT_BYTES]+=bytes;
   s[RF_MFP_CONSTANT_MAX_BYTES]=MAX2(s[RF_MFP_CONSTANT_MAX_BYTES],bytes);
   if(!r->size){++s[RF_MFP_CONSTANT_UNKNOWN];s[RF_MFP_CONSTANT_UNKNOWN_BYTES]+=bytes;}
   int selected=rwa_redfin_constant_gpu_snapshot(device,buffer,offset,bytes,out,why,why_size);
   if(selected<=0)return selected;
   if(!buffer->map){say(why,why_size,"constant snapshot has no CPU fallback mapping");return -1;}
   uint64_t began=rwa_redfin_profile_clock();
   int error=rwa_redfin_buffer_cpu_prepare(buffer,why,why_size);
   rwa_redfin_profile_elapsed(device,RF_MFP_CONSTANT_PREPARE_NS,began);
   if(error)return error;
   began=rwa_redfin_profile_clock();
   error=rwa_redfin_constant_upload(device,(const char *)buffer->map+offset,bytes,out,why,why_size);
   rwa_redfin_profile_elapsed(device,RF_MFP_CONSTANT_UPLOAD_NS,began);
   return error;
}

static void rwa_redfin_profile_submit_clear(struct rwa_device *device)
{
   uint64_t began=rwa_redfin_profile_clock();
   rwa_redfin_bindings_clear(device);
   rwa_redfin_profile_elapsed(device,RF_MFP_SUBMIT_CLEAR_NS,began);
}
static int rwa_redfin_profile_submit_resolve(struct rwa_device *device,char *why,size_t bytes)
{
   uint64_t began=rwa_redfin_profile_clock();
   int error=rwa_redfin_linear_resolve_all(device,why,bytes);
   rwa_redfin_profile_elapsed(device,RF_MFP_SUBMIT_RESOLVE_NS,began);
   return error;
}

/* Wrap only the runtime include, preserving its complete admission, actual
 * completion and failure handling. The outer measurement includes publication;
 * clear/resolve are named subsets and must not be added to that total. */
static int rwa_redfin_profile_submit_impl(struct rwa_device *,struct rwa_redfin_completion **,
   char *,size_t);
#define rwa_redfin_commands_submit rwa_redfin_profile_submit_impl
#define rwa_redfin_bindings_clear rwa_redfin_profile_submit_clear
#define rwa_redfin_linear_resolve_all rwa_redfin_profile_submit_resolve
#include "redfin_metal_queued.inc"
#undef rwa_redfin_linear_resolve_all
#undef rwa_redfin_bindings_clear
#undef rwa_redfin_commands_submit

int rwa_redfin_commands_submit(struct rwa_device *device,struct rwa_redfin_completion **out,
   char *why,size_t bytes)
{
   uint64_t began=rwa_redfin_profile_clock();
   int error=rwa_redfin_profile_submit_impl(device,out,why,bytes);
   if(device)++device->frontend_stats[RF_MFP_SUBMIT_CALLS];
   rwa_redfin_profile_elapsed(device,RF_MFP_SUBMIT_NS,began);
   return error;
}
