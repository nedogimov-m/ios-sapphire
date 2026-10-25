/* SPDX-License-Identifier: MIT
 * The Gallium gate protects this device. GPU consumers are ordered on its
 * queue; CPU byte reads explicitly pay the real fence when their data changed.
 */
#include "util/u_upload_mgr.h"

static void rwa_redfin_buffer_register(struct rwa_buffer *buffer)
{
   buffer->gpu_visible=true;
   for(struct rwa_buffer *other=buffer->device->all_buffers;other;other=other->all_next)
      if(rwa_redfin_buffers_share(buffer,other)&&other->gpu_pending) {
         buffer->gpu_pending=true;buffer->gpu_visible=false;
         buffer->gpu_write_epoch=MAX2(buffer->gpu_write_epoch,other->gpu_write_epoch);
      }
   buffer->all_next=buffer->device->all_buffers;
   buffer->device->all_buffers=buffer;
}
static void rwa_redfin_buffer_unregister(struct rwa_buffer *buffer)
{
   struct rwa_buffer **at=&buffer->device->all_buffers;
   while(*at&&*at!=buffer)at=&(*at)->all_next;
   if(*at==buffer)*at=buffer->all_next;
   buffer->all_next=NULL;
}
static void rwa_redfin_ordering_completed_epoch(struct rwa_device *device,uint64_t epoch)
{
   device->completed_epoch=MAX2(device->completed_epoch,epoch);
   if(device->gpu_memory_epoch<=epoch)device->gpu_memory_pending=false;
   for(struct rwa_buffer *b=device->all_buffers;b;b=b->all_next) {
      if(b->gpu_write_epoch<=epoch){b->gpu_pending=false;b->gpu_visible=true;}
   }
   for(struct rwa_texture *t=device->buffer_textures;t;t=t->buffer_next)
      if(t->buffer_write_epoch<=epoch)t->buffer_pending=false;
}
static void rwa_redfin_ordering_completed(struct rwa_device *device)
{
   ++device->ordering[1];
   rwa_redfin_ordering_completed_epoch(device,device->encoding_epoch?device->encoding_epoch:device->issued_epoch);
   if(!device->command_scope.active)device->encoding_epoch=0;
}
static int rwa_redfin_gpu_prepare(struct rwa_device *device,char *why,size_t bytes)
{
   if(device->queued_closing||__atomic_load_n(&device->queued_failed,__ATOMIC_ACQUIRE)) {
      say(why,bytes,"Metal native context is closing or retired");return -1;
   }
   if(!device->encoding_epoch) {
      if(device->issued_epoch==UINT64_MAX){say(why,bytes,"Metal work epoch exhausted");return -1;}
      device->encoding_epoch=++device->issued_epoch;
   }
   if(redfin_metal_scope_prepare(&device->command_scope,true,command_scope_finish,device,why,bytes))return -1;
   if(device->gpu_memory_pending) {
      /* Deliberately exclude FRAMEBUFFER: ordinary raster dependencies use
       * fd6's render graph, while these flags record shader/cache ordering. */
      if(device->pipe->memory_barrier)device->pipe->memory_barrier(device->pipe,
         PIPE_BARRIER_SHADER_BUFFER|PIPE_BARRIER_CONSTANT_BUFFER|PIPE_BARRIER_VERTEX_BUFFER|
         PIPE_BARRIER_INDEX_BUFFER|PIPE_BARRIER_TEXTURE|PIPE_BARRIER_IMAGE|
         PIPE_BARRIER_UPDATE_BUFFER|PIPE_BARRIER_UPDATE_TEXTURE);
      device->gpu_memory_pending=false;++device->ordering[5];
   }
   return 0;
}
static int rwa_redfin_gpu_complete(struct rwa_device *device,bool memory_write,char *why,size_t bytes)
{
   ++device->ordering[0];if(device->command_scope.active)++device->ordering[3];
   if(memory_write){device->gpu_memory_pending=true;device->gpu_memory_epoch=device->encoding_epoch;}
   return redfin_metal_scope_complete(&device->command_scope,true,command_scope_finish,device,why,bytes);
}
/* A different pipe_resource over the same BO is invisible to Gallium's resource
 * graph. Submit its producer before the layout/alias handoff, without a CPU
 * wait. The final command fence still covers every submitted batch. Ordinary
 * draws and repeated reads of the same shadow never come through this path. */
static int rwa_redfin_gpu_alias_transition(struct rwa_device *device,char *why,size_t bytes)
{
   if(rwa_redfin_gpu_prepare(device,why,bytes))return -1;
   if(device->command_scope.pending)device->pipe->flush(device->pipe,NULL,0);
   for(struct rwa_buffer *b=device->all_buffers;b;b=b->all_next)b->gpu_visible=true;
   return 0;
}
static int rwa_redfin_cpu_drain(struct rwa_device *device,char *why,size_t bytes)
{
   if(device->command_scope.pending||device->queued_tickets)++device->ordering[2];
   if(rwa_redfin_queued_drain(device,why,bytes))return -1;
   return redfin_metal_scope_drain(&device->command_scope,command_scope_finish,device,why,bytes);
}
static int rwa_redfin_constant_upload(struct rwa_device *device,const void *data,size_t bytes,
   struct pipe_constant_buffer *out,char *why,size_t why_size)
{
   if(!data||!bytes||bytes>UINT32_MAX||!device->pipe->const_uploader) {
      say(why,why_size,"constant upload has no bounded native uploader");return -1;
   }
   unsigned offset=0;struct pipe_resource *resource=NULL;
   u_upload_data(device->pipe->const_uploader,0,(unsigned)bytes,MAX2(64,device->ubo_offset_align),data,&offset,&resource);
   u_upload_unmap(device->pipe->const_uploader);
   if(!resource) {say(why,why_size,"native immutable constant upload failed");return -1;}
   *out=(struct pipe_constant_buffer){.buffer=resource,.buffer_offset=offset,.buffer_size=(unsigned)bytes};
   return 0;
}
int rwa_redfin_ordering_statistics(struct rwa_device *device,uint64_t *out,size_t words)
{
   if(!device||!out||words!=REDFIN_METAL_ORDERING_WORDS)return -1;
   memcpy(out,device->ordering,words*sizeof(*out));return 0;
}
