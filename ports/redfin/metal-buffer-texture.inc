/* SPDX-License-Identifier: MIT */
/* Buffer views alias actual prepared parent pages. All layout conversions are
 * native GPU work; order transitions before another view or raw-buffer use. */
static bool
rwa_redfin_buffers_share(const struct rwa_buffer *a,const struct rwa_buffer *b)
{
   if(!a||!b)return false;
   if(a==b||a->res==b->res||(a->external_surface&&a->external_surface==b->external_surface))return true;
   uintptr_t x=(uintptr_t)a->map,y=(uintptr_t)b->map;
   return x&&y&&x<=UINTPTR_MAX-a->size&&y<=UINTPTR_MAX-b->size&&x<y+b->size&&y<x+a->size;
}
static bool
rwa_redfin_view_rows_overlap(uint64_t a,uint32_t ap,uint32_t aw,uint32_t ah,
    uint64_t b,uint32_t bp,uint32_t bw,uint32_t bh)
{
   if(!aw||!bw||!ah||!bh||aw>ap||bw>bp||
      a>UINT64_MAX-((uint64_t)(ah-1)*ap+aw)||b>UINT64_MAX-((uint64_t)(bh-1)*bp+bw))return true;
   uint32_t i=0,j=0;
   while(i<ah&&j<bh) {
      uint64_t x=a+(uint64_t)i*ap,y=b+(uint64_t)j*bp;
      if(x+aw<=y)++i;else if(y+bw<=x)++j;else return true;
   }
   return false;
}
static int
rwa_redfin_buffer_prepare(struct rwa_buffer *buffer,char *why,size_t bytes)
{
   if(!buffer)return 0;
   struct rwa_device *device=buffer->device;
   for(struct rwa_texture *t=device->buffer_textures;t;t=t->buffer_next) {
      if(!rwa_redfin_buffers_share(t->buffer_parent,buffer))continue;
      if(t->buffer_pending) {
         if(redfin_metal_scope_prepare(&device->command_scope,false,command_scope_finish,device,why,bytes))return -1;
         t->buffer_pending=false;
      }
      if(rwa_redfin_linear_resolve(t,why,bytes))return -1;
   }
   return 0;
}
static int
rwa_redfin_buffer_texture_prepare(struct rwa_texture *texture,char *why,size_t bytes)
{
   if(!texture||!texture->buffer_parent)return 0;
   struct rwa_device *device=texture->device;
   for(struct rwa_texture *t=device->buffer_textures;t;t=t->buffer_next) {
      if(!rwa_redfin_buffers_share(t->buffer_parent,texture->buffer_parent))continue;
      if(t->buffer_pending) {
         if(redfin_metal_scope_prepare(&device->command_scope,false,command_scope_finish,device,why,bytes))return -1;
         t->buffer_pending=false;
      }
      if(t!=texture&&rwa_redfin_linear_resolve(t,why,bytes))return -1;
   }
   return 0;
}
static void
rwa_redfin_buffer_written(struct rwa_buffer *buffer)
{
   if(!buffer)return;
   struct rwa_device *device=buffer->device;bool aliases=false;
   for(struct rwa_texture *t=device->buffer_textures;t;t=t->buffer_next) {
      if(!rwa_redfin_buffers_share(t->buffer_parent,buffer))continue;
      aliases=true;t->linear_epoch=0;
      if(redfin_freedreno_alias_written(device->pipe,t->res))device->command_scope.failed=true;
   }
   if(aliases&&device->pipe->memory_barrier)device->pipe->memory_barrier(device->pipe,PIPE_BARRIER_ALL);
}
int
rwa_redfin_texture_buffer_link(struct rwa_texture *texture,struct rwa_buffer *parent,
    uint64_t offset,uint64_t pitch,char *why,size_t bytes)
{
   if(!texture||!parent||texture->buffer_parent||texture->device!=parent->device||
      texture->res->target!=PIPE_TEXTURE_2D||texture->res->last_level||texture->res->nr_samples>1||
      offset>parent->size||pitch>UINT32_MAX||!pitch||
      pitch*texture->res->height0>parent->size-offset||
      (uint64_t)texture->res->width0*util_format_get_blocksize(texture->res->format)>pitch) {
      say(why,bytes,"buffer texture exceeds its actual parent's logical rows");return -1;
   }
   texture->buffer_parent=parent;texture->buffer_offset=(unsigned)offset;texture->buffer_pitch=(unsigned)pitch;
   texture->buffer_next=parent->device->buffer_textures;parent->device->buffer_textures=texture;
   return 0;
}
static void
rwa_redfin_buffer_texture_release(struct rwa_texture *texture)
{
   if(!texture||!texture->buffer_parent)return;
   struct rwa_texture **at=&texture->device->buffer_textures;
   while(*at&&*at!=texture)at=&(*at)->buffer_next;
   if(*at==texture)*at=texture->buffer_next;
   texture->buffer_parent=NULL;texture->buffer_next=NULL;
}
