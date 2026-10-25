/* SPDX-License-Identifier: MIT
 * Command-local Gallium bindings. The frontend mutex serializes this state.
 * Cache resource references survive replacements and internal GPU helpers;
 * native command batches retain their own execution references as usual.
 */
static bool rwa_redfin_buffer_binding_equal(const struct pipe_shader_buffer *a,const struct pipe_shader_buffer *b)
{return a->buffer==b->buffer&&(!a->buffer||(a->buffer_offset==b->buffer_offset&&a->buffer_size==b->buffer_size));}
static bool rwa_redfin_image_binding_equal(const struct pipe_image_view *a,const struct pipe_image_view *b)
{
   if(a->resource!=b->resource)return false;
   if(!a->resource)return true;
   if(a->format!=b->format||a->access!=b->access||a->shader_access!=b->shader_access)return false;
   if(a->resource->target==PIPE_BUFFER)return a->u.buf.offset==b->u.buf.offset&&a->u.buf.size==b->u.buf.size;
   return a->u.tex.level==b->u.tex.level&&a->u.tex.first_layer==b->u.tex.first_layer&&
      a->u.tex.last_layer==b->u.tex.last_layer&&a->u.tex.single_layer_view==b->u.tex.single_layer_view&&
      a->u.tex.is_2d_view_of_3d==b->u.tex.is_2d_view_of_3d;
}
static void rwa_redfin_bindings_stage(struct rwa_device *device,enum pipe_shader_type stage,
   const struct pipe_constant_buffer constants[PIPE_MAX_CONSTANT_BUFFERS],unsigned constant_mask,
   const struct pipe_shader_buffer buffers[PIPE_MAX_SHADER_BUFFERS],unsigned num_buffers,unsigned writable,
   struct pipe_sampler_view *const views[16],unsigned num_views,
   const struct pipe_image_view images[16],unsigned num_images,void *const samplers[16],unsigned num_samplers)
{
   struct pipe_context *pipe=device->pipe;
   struct redfin_metal_stage_bindings *old=&device->bindings[stage];
   ++device->binding_stats[0];
   for(unsigned i=0;i<PIPE_MAX_CONSTANT_BUFFERS;++i) {
      if(constant_mask&(1u<<i)) {
         /* Shared/persistently mapped UBO bytes may change without a new
          * descriptor. Preserve the native constant reload on EVERY use. */
         pipe->set_constant_buffer(pipe,stage,i,false,&constants[i]);++device->binding_stats[3];
      } else if(old->constants&(1u<<i)) {
         pipe->set_constant_buffer(pipe,stage,i,false,NULL);++device->binding_stats[4];
      }
   }
   old->constants=constant_mask;
   unsigned span=MAX2(num_buffers,old->num_buffers);
   bool same=writable==old->writable&&num_buffers==old->num_buffers;
   for(unsigned i=0;same&&i<span;++i)same=rwa_redfin_buffer_binding_equal(&buffers[i],&old->buffers[i]);
   if(!same) {
      pipe->set_shader_buffers(pipe,stage,0,span,buffers,writable);++device->binding_stats[1];
      if(old->num_buffers>num_buffers)device->binding_stats[4]+=old->num_buffers-num_buffers;
      for(unsigned i=0;i<span;++i) {
         pipe_resource_reference(&old->buffers[i].buffer,buffers[i].buffer);
         old->buffers[i].buffer_offset=buffers[i].buffer_offset;old->buffers[i].buffer_size=buffers[i].buffer_size;
      }
      old->num_buffers=num_buffers;old->writable=writable;
   } else if(span)++device->binding_stats[2];
   span=MAX2(num_views,old->num_views);same=num_views==old->num_views;
   for(unsigned i=0;same&&i<span;++i)same=views[i]==old->views[i];
   if(!same) {
      pipe->set_sampler_views(pipe,stage,0,num_views,span-num_views,false,(struct pipe_sampler_view **)views);
      ++device->binding_stats[1];if(old->num_views>num_views)device->binding_stats[4]+=old->num_views-num_views;
      for(unsigned i=0;i<span;++i)pipe_sampler_view_reference(&old->views[i],views[i]);
      old->num_views=num_views;
   } else if(span)++device->binding_stats[2];
   span=MAX2(num_images,old->num_images);same=num_images==old->num_images;
   for(unsigned i=0;same&&i<span;++i)same=rwa_redfin_image_binding_equal(&images[i],&old->images[i]);
   if(!same) {
      pipe->set_shader_images(pipe,stage,0,num_images,span-num_images,images);++device->binding_stats[1];
      if(old->num_images>num_images)device->binding_stats[4]+=old->num_images-num_images;
      for(unsigned i=0;i<span;++i) {
         struct pipe_resource *retained=old->images[i].resource;
         pipe_resource_reference(&retained,images[i].resource);old->images[i]=images[i];old->images[i].resource=retained;
      }
      old->num_images=num_images;
   } else if(span)++device->binding_stats[2];
   span=MAX2(num_samplers,old->num_samplers);same=num_samplers==old->num_samplers;
   for(unsigned i=0;same&&i<span;++i)same=samplers[i]==old->samplers[i];
   if(!same) {
      pipe->bind_sampler_states(pipe,stage,0,span,(void **)samplers);++device->binding_stats[1];
      if(old->num_samplers>num_samplers)device->binding_stats[4]+=old->num_samplers-num_samplers;
      memcpy(old->samplers,samplers,span*sizeof(*samplers));old->num_samplers=num_samplers;
   } else if(span)++device->binding_stats[2];
}
static void rwa_redfin_bindings_clear_stage(struct rwa_device *device,enum pipe_shader_type stage)
{
   struct redfin_metal_stage_bindings *s=&device->bindings[stage];struct pipe_context *pipe=device->pipe;
   if(!s->constants&&!s->num_buffers&&!s->num_views&&!s->num_images&&!s->num_samplers)return;
   for(unsigned i=0;i<PIPE_MAX_CONSTANT_BUFFERS;++i)if(s->constants&(1u<<i))pipe->set_constant_buffer(pipe,stage,i,false,NULL);
   if(s->num_buffers)pipe->set_shader_buffers(pipe,stage,0,s->num_buffers,NULL,0);
   if(s->num_views)pipe->set_sampler_views(pipe,stage,0,0,s->num_views,false,NULL);
   if(s->num_images)pipe->set_shader_images(pipe,stage,0,0,s->num_images,NULL);
   if(s->num_samplers){void *none[16]={0};pipe->bind_sampler_states(pipe,stage,0,s->num_samplers,none);}
   device->binding_stats[1]+=(s->num_buffers!=0)+(s->num_views!=0)+(s->num_images!=0)+(s->num_samplers!=0);
   for(unsigned i=0;i<s->num_buffers;++i)pipe_resource_reference(&s->buffers[i].buffer,NULL);
   for(unsigned i=0;i<s->num_views;++i)pipe_sampler_view_reference(&s->views[i],NULL);
   for(unsigned i=0;i<s->num_images;++i)pipe_resource_reference(&s->images[i].resource,NULL);
   memset(s,0,sizeof(*s));++device->binding_stats[5];
}
static void rwa_redfin_graphics_invalidate(struct rwa_device *device)
{
   device->graphics_bindings.valid=0;device->graphics_bindings.dynamic_valid=0;
   device->graphics_bindings.vertices_required=true;
}
static void rwa_redfin_bindings_clear(struct rwa_device *device)
{
   for(unsigned i=0;i<PIPE_SHADER_TYPES;++i)rwa_redfin_bindings_clear_stage(device,(enum pipe_shader_type)i);
   struct redfin_metal_graphics_bindings *g=&device->graphics_bindings;
   if(g->num_vertices) {
      device->pipe->set_vertex_buffers(device->pipe,0,NULL);++device->binding_stats[8];
      for(unsigned i=0;i<g->num_vertices;++i)pipe_resource_reference(&g->vertices[i].buffer.resource,NULL);
   }
   memset(g,0,sizeof(*g));
}
static void rwa_redfin_sampler_forget(struct rwa_device *device,void *cso)
{
   if(!cso)return;
   for(unsigned i=0;i<PIPE_SHADER_TYPES;++i) {
      struct redfin_metal_stage_bindings *s=&device->bindings[i];
      for(unsigned j=0;j<s->num_samplers;++j)if(s->samplers[j]==cso){rwa_redfin_bindings_clear_stage(device,(enum pipe_shader_type)i);break;}
   }
}
static void rwa_redfin_bind_cso(struct rwa_device *device,enum redfin_metal_cso slot,void *cso)
{
   struct redfin_metal_graphics_bindings *g=&device->graphics_bindings;struct pipe_context *pipe=device->pipe;
   if((g->valid&(1u<<slot))&&g->cso[slot]==cso){++device->binding_stats[7];return;}
   switch(slot) {
   case RF_BIND_BLEND:pipe->bind_blend_state(pipe,cso);break;
   case RF_BIND_DSA:pipe->bind_depth_stencil_alpha_state(pipe,cso);break;
   case RF_BIND_RASTER:pipe->bind_rasterizer_state(pipe,cso);break;
   case RF_BIND_VS:pipe->bind_vs_state(pipe,cso);break;
   case RF_BIND_FS:pipe->bind_fs_state(pipe,cso);break;
   case RF_BIND_VELEM:pipe->bind_vertex_elements_state(pipe,cso);g->vertices_required=true;break;
   default:return;
   }
   g->cso[slot]=cso;g->valid|=1u<<slot;++device->binding_stats[6];
}
/* Consume the incoming vertex references exactly as Gallium's native setter
 * does, including a cache hit that need not call that setter. */
static void rwa_redfin_bind_vertices(struct rwa_device *device,unsigned count,struct pipe_vertex_buffer *vertices)
{
   struct redfin_metal_graphics_bindings *g=&device->graphics_bindings;
   bool same=g->vertices_valid&&!g->vertices_required&&count==g->num_vertices;
   for(unsigned i=0;same&&i<count;++i)same=vertices[i].buffer.resource==g->vertices[i].buffer.resource&&
      vertices[i].buffer_offset==g->vertices[i].buffer_offset&&vertices[i].is_user_buffer==g->vertices[i].is_user_buffer;
   if(same) {
      for(unsigned i=0;i<count;++i)pipe_resource_reference(&vertices[i].buffer.resource,NULL);
      ++device->binding_stats[9];return;
   }
   unsigned span=MAX2(count,g->num_vertices);
   for(unsigned i=0;i<span;++i) {
      pipe_resource_reference(&g->vertices[i].buffer.resource,i<count?vertices[i].buffer.resource:NULL);
      g->vertices[i].buffer_offset=i<count?vertices[i].buffer_offset:0;g->vertices[i].is_user_buffer=false;
   }
   device->pipe->set_vertex_buffers(device->pipe,count,vertices);++device->binding_stats[8];
   g->num_vertices=count;g->vertices_valid=true;g->vertices_required=false;
}
static void rwa_redfin_bind_dynamic(struct rwa_device *device,const struct pipe_viewport_state *viewport,
   const struct pipe_scissor_state *scissor,const struct pipe_blend_color *blend)
{
   struct redfin_metal_graphics_bindings *g=&device->graphics_bindings;struct pipe_context *pipe=device->pipe;
   if(!(g->dynamic_valid&1u)||memcmp(&g->viewport,viewport,sizeof(*viewport))) {
      pipe->set_viewport_states(pipe,0,1,viewport);g->viewport=*viewport;g->dynamic_valid|=1u;++device->binding_stats[6];
   } else ++device->binding_stats[7];
   if(!(g->dynamic_valid&2u)||memcmp(&g->scissor,scissor,sizeof(*scissor))) {
      pipe->set_scissor_states(pipe,0,1,scissor);g->scissor=*scissor;g->dynamic_valid|=2u;++device->binding_stats[6];
   } else ++device->binding_stats[7];
   if(!(g->dynamic_valid&4u)||memcmp(&g->blend,blend,sizeof(*blend))) {
      pipe->set_blend_color(pipe,blend);g->blend=*blend;g->dynamic_valid|=4u;++device->binding_stats[6];
   } else ++device->binding_stats[7];
}
static void rwa_redfin_bind_stencil(struct rwa_device *device,const struct pipe_stencil_ref *stencil)
{
   struct redfin_metal_graphics_bindings *g=&device->graphics_bindings;
   if(!(g->dynamic_valid&8u)||memcmp(&g->stencil,stencil,sizeof(*stencil))) {
      device->pipe->set_stencil_ref(device->pipe,*stencil);g->stencil=*stencil;g->dynamic_valid|=8u;++device->binding_stats[6];
   } else ++device->binding_stats[7];
}
int rwa_redfin_binding_statistics(struct rwa_device *device,uint64_t *out,size_t words)
{
   if(!device||!out||words!=REDFIN_METAL_BINDING_WORDS)return -1;
   memcpy(out,device->binding_stats,words*sizeof(*out));out[10]=out[11]=0;
   for(unsigned i=0;i<PIPE_SHADER_TYPES;++i) {
      const struct redfin_metal_stage_bindings *s=&device->bindings[i];out[10]+=util_bitcount(s->constants);
      for(unsigned j=0;j<s->num_buffers;++j)out[10]+=s->buffers[j].buffer!=NULL;
      for(unsigned j=0;j<s->num_views;++j)out[10]+=s->views[j]!=NULL;
      for(unsigned j=0;j<s->num_images;++j)out[10]+=s->images[j].resource!=NULL;
      for(unsigned j=0;j<s->num_samplers;++j)out[10]+=s->samplers[j]!=NULL;
   }
   for(unsigned i=0;i<device->graphics_bindings.num_vertices;++i)out[11]+=device->graphics_bindings.vertices[i].buffer.resource!=NULL;
   return 0;
}
