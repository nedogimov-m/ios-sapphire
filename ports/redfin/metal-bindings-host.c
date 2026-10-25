/* SPDX-License-Identifier: MIT
 * Execute the actual binding cache against an ownership-counting receiver.
 * No host shader execution or A620 pixel result is simulated here.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pipe/p_context.h"
#include "pipe/p_state.h"
#include "pipe/p_screen.h"
#include "util/u_math.h"
#define REDFIN_METAL_BINDINGS_RUNTIME 1
#include "metal-bindings.h"
#define REQUIRE(x) do {if(!(x)){fprintf(stderr,"binding contract: %s at %u\n",#x,__LINE__);abort();}}while(0)
struct resource {struct pipe_resource pipe;unsigned destroyed;};
struct view {struct pipe_sampler_view pipe;unsigned destroyed;};
static void pipe_resource_reference(struct pipe_resource **at,struct pipe_resource *next)
{
   if(*at==next)return;
   if(next){REQUIRE(next->reference.count>0);++next->reference.count;}
   struct pipe_resource *old=*at;*at=next;
   if(old){REQUIRE(old->reference.count>0);if(!--old->reference.count)old->screen->resource_destroy(old->screen,old);}
}
static void pipe_sampler_view_reference(struct pipe_sampler_view **at,struct pipe_sampler_view *next)
{
   if(*at==next)return;
   if(next){REQUIRE(next->reference.count>0);++next->reference.count;}
   struct pipe_sampler_view *old=*at;*at=next;
   if(old){REQUIRE(old->reference.count>0);if(!--old->reference.count)old->context->sampler_view_destroy(old->context,old);}
}
struct rwa_device {
   struct pipe_context *pipe;
   struct redfin_metal_stage_bindings bindings[PIPE_SHADER_TYPES];
   struct redfin_metal_graphics_bindings graphics_bindings;
   uint64_t binding_stats[REDFIN_METAL_BINDING_WORDS];
};
#include "metal-bindings.inc"
struct receiver_stage {
   struct pipe_constant_buffer cb[PIPE_MAX_CONSTANT_BUFFERS];
   struct pipe_shader_buffer buffers[PIPE_MAX_SHADER_BUFFERS];
   struct pipe_sampler_view *views[16];struct pipe_image_view images[16];void *samplers[16];
   unsigned writable;
};
struct receiver {
   struct pipe_context pipe;struct receiver_stage stage[PIPE_SHADER_TYPES];
   struct pipe_vertex_buffer vertices[PIPE_MAX_ATTRIBS];unsigned num_vertices,vertex_calls,constant_calls;
   void *cso[RF_BIND_CSO_COUNT];unsigned cso_calls,dynamic_calls;
};
static void resource_destroy(struct pipe_screen *screen,struct pipe_resource *p)
{(void)screen;struct resource *r=(struct resource *)p;REQUIRE(!r->destroyed&&p->reference.count==0);++r->destroyed;}
static void view_destroy(struct pipe_context *pipe,struct pipe_sampler_view *p)
{(void)pipe;struct view *v=(struct view *)p;REQUIRE(!v->destroyed&&p->reference.count==0);++v->destroyed;pipe_resource_reference(&p->texture,NULL);}
static void set_constant(struct pipe_context *pipe,enum pipe_shader_type stage,uint slot,bool owned,const struct pipe_constant_buffer *next)
{
   REQUIRE(!owned);struct receiver *r=(struct receiver *)pipe;struct pipe_constant_buffer *at=&r->stage[stage].cb[slot];
   pipe_resource_reference(&at->buffer,next?next->buffer:NULL);at->buffer_offset=next?next->buffer_offset:0;at->buffer_size=next?next->buffer_size:0;++r->constant_calls;
}
static void set_buffers(struct pipe_context *pipe,enum pipe_shader_type stage,unsigned first,unsigned count,const struct pipe_shader_buffer *next,unsigned writable)
{
   struct receiver_stage *s=&((struct receiver *)pipe)->stage[stage];
   for(unsigned i=0;i<count;++i){struct pipe_shader_buffer *at=&s->buffers[first+i];pipe_resource_reference(&at->buffer,next?next[i].buffer:NULL);
      at->buffer_offset=next?next[i].buffer_offset:0;at->buffer_size=next?next[i].buffer_size:0;}
   s->writable=writable;
}
static void set_views(struct pipe_context *pipe,enum pipe_shader_type stage,unsigned first,unsigned count,unsigned trailing,bool owned,struct pipe_sampler_view **next)
{
   REQUIRE(!owned);struct receiver_stage *s=&((struct receiver *)pipe)->stage[stage];
   for(unsigned i=0;i<count+trailing;++i)pipe_sampler_view_reference(&s->views[first+i],i<count&&next?next[i]:NULL);
}
static void set_images(struct pipe_context *pipe,enum pipe_shader_type stage,unsigned first,unsigned count,unsigned trailing,const struct pipe_image_view *next)
{
   struct receiver_stage *s=&((struct receiver *)pipe)->stage[stage];
   for(unsigned i=0;i<count+trailing;++i){struct pipe_image_view *at=&s->images[first+i];struct pipe_resource *p=at->resource;
      pipe_resource_reference(&p,i<count&&next?next[i].resource:NULL);*at=i<count&&next?next[i]:(struct pipe_image_view){0};at->resource=p;}
}
static void set_samplers(struct pipe_context *pipe,enum pipe_shader_type stage,unsigned first,unsigned count,void **next)
{struct receiver_stage *s=&((struct receiver *)pipe)->stage[stage];for(unsigned i=0;i<count;++i)s->samplers[first+i]=next?next[i]:NULL;}
#define CSO_CALLBACK(name,slot) static void name(struct pipe_context *pipe,void *state){struct receiver *r=(struct receiver *)pipe;r->cso[slot]=state;++r->cso_calls;}
CSO_CALLBACK(blend_state,RF_BIND_BLEND)
CSO_CALLBACK(depth_state,RF_BIND_DSA)
CSO_CALLBACK(raster_state,RF_BIND_RASTER)
CSO_CALLBACK(vertex_state,RF_BIND_VS)
CSO_CALLBACK(fragment_state,RF_BIND_FS)
CSO_CALLBACK(elements_state,RF_BIND_VELEM)
static void set_vertices(struct pipe_context *pipe,unsigned count,const struct pipe_vertex_buffer *next)
{
   struct receiver *r=(struct receiver *)pipe;
   for(unsigned i=0;i<r->num_vertices;++i)pipe_resource_reference(&r->vertices[i].buffer.resource,NULL);
   memset(r->vertices,0,sizeof(r->vertices));
   for(unsigned i=0;i<count;++i)r->vertices[i]=next[i]; /* native ownership transfer */
   r->num_vertices=count;++r->vertex_calls;
}
static void viewport(struct pipe_context *pipe,unsigned first,unsigned count,const struct pipe_viewport_state *v)
{(void)first;(void)count;(void)v;++((struct receiver *)pipe)->dynamic_calls;}
static void scissor(struct pipe_context *pipe,unsigned first,unsigned count,const struct pipe_scissor_state *v)
{(void)first;(void)count;(void)v;++((struct receiver *)pipe)->dynamic_calls;}
static void blend_color(struct pipe_context *pipe,const struct pipe_blend_color *v)
{(void)v;++((struct receiver *)pipe)->dynamic_calls;}
static void stencil(struct pipe_context *pipe,struct pipe_stencil_ref v)
{(void)v;++((struct receiver *)pipe)->dynamic_calls;}
static void apply(struct rwa_device *device,enum pipe_shader_type stage,
   struct pipe_constant_buffer *cb,unsigned constants,struct pipe_shader_buffer *buffers,unsigned nb,unsigned writable,
   struct pipe_sampler_view **views,unsigned nv,struct pipe_image_view *images,unsigned ni,void **samplers,unsigned ns)
{rwa_redfin_bindings_stage(device,stage,cb,constants,buffers,nb,writable,views,nv,images,ni,samplers,ns);}
int main(void)
{
   struct pipe_screen screen={.resource_destroy=resource_destroy};
   struct receiver actual={.pipe={.set_constant_buffer=set_constant,.set_shader_buffers=set_buffers,.set_sampler_views=set_views,
      .set_shader_images=set_images,.bind_sampler_states=set_samplers,.sampler_view_destroy=view_destroy,
      .bind_blend_state=blend_state,.bind_depth_stencil_alpha_state=depth_state,.bind_rasterizer_state=raster_state,
      .bind_vs_state=vertex_state,.bind_fs_state=fragment_state,.bind_vertex_elements_state=elements_state,
      .set_vertex_buffers=set_vertices,.set_viewport_states=viewport,.set_scissor_states=scissor,.set_blend_color=blend_color,.set_stencil_ref=stencil}};
   struct rwa_device device={.pipe=&actual.pipe};
   struct resource a={0},b={0},c={0},d={0};struct resource *resources[]={&a,&b,&c,&d};
   for(unsigned i=0;i<4;++i){resources[i]->pipe.screen=&screen;resources[i]->pipe.reference.count=1;resources[i]->pipe.width0=512;resources[i]->pipe.target=(i==0||i==3)?PIPE_BUFFER:PIPE_TEXTURE_2D;}
   struct view va={.pipe={.context=&actual.pipe}},vb={.pipe={.context=&actual.pipe}};
   va.pipe.reference.count=vb.pipe.reference.count=1;pipe_resource_reference(&va.pipe.texture,&b.pipe);pipe_resource_reference(&vb.pipe.texture,&c.pipe);
   int cso[8]={0};
   struct pipe_constant_buffer cb[PIPE_MAX_CONSTANT_BUFFERS]={0};struct pipe_shader_buffer buffers[PIPE_MAX_SHADER_BUFFERS]={0};
   struct pipe_sampler_view *views[16]={0};struct pipe_image_view images[16]={0};void *samplers[16]={0};
   cb[9]=(struct pipe_constant_buffer){.buffer=&a.pipe,.buffer_offset=64,.buffer_size=64};
   buffers[7]=(struct pipe_shader_buffer){.buffer=&a.pipe,.buffer_offset=128,.buffer_size=64};views[9]=&va.pipe;
   images[5]=(struct pipe_image_view){.resource=&b.pipe,.format=PIPE_FORMAT_R8G8B8A8_UNORM,.access=3,.shader_access=3};samplers[15]=&cso[0];
   apply(&device,PIPE_SHADER_FRAGMENT,cb,1u<<9,buffers,8,1u<<7,views,10,images,6,samplers,16);
   uint64_t calls=device.binding_stats[1];REQUIRE(calls==4&&actual.stage[PIPE_SHADER_FRAGMENT].writable==(1u<<7));
   apply(&device,PIPE_SHADER_FRAGMENT,cb,1u<<9,buffers,8,1u<<7,views,10,images,6,samplers,16);
   REQUIRE(device.binding_stats[1]==calls&&device.binding_stats[2]==4&&actual.constant_calls==2);
   /* Change image access/layer metadata while retaining its exact resource. */
   images[5].u.tex.last_layer=1;
   apply(&device,PIPE_SHADER_FRAGMENT,cb,1u<<9,buffers,8,1u<<7,views,10,images,6,samplers,16);
   REQUIRE(device.binding_stats[1]==calls+1);
   memset(cb,0,sizeof(cb));memset(buffers,0,sizeof(buffers));memset(views,0,sizeof(views));memset(images,0,sizeof(images));memset(samplers,0,sizeof(samplers));
   cb[0]=(struct pipe_constant_buffer){.buffer=&a.pipe,.buffer_size=32};buffers[0]=(struct pipe_shader_buffer){.buffer=&a.pipe,.buffer_size=32};views[0]=&vb.pipe;samplers[0]=&cso[1];
   apply(&device,PIPE_SHADER_FRAGMENT,cb,1,buffers,1,0,views,1,images,0,samplers,1);
   struct receiver_stage *low=&actual.stage[PIPE_SHADER_FRAGMENT];REQUIRE(!low->cb[9].buffer&&!low->writable);
   for(unsigned i=1;i<16;++i)REQUIRE(!low->views[i]&&!low->images[i].resource&&!low->samplers[i]);
   for(unsigned i=1;i<PIPE_MAX_SHADER_BUFFERS;++i)REQUIRE(!low->buffers[i].buffer);
   REQUIRE(device.binding_stats[4]>0);
   /* Deleting an API sampler clears every real stage that still names it. */
   apply(&device,PIPE_SHADER_COMPUTE,cb,1,buffers,1,0,views,1,images,0,samplers,1);
   rwa_redfin_sampler_forget(&device,&cso[1]);
   REQUIRE(!actual.stage[PIPE_SHADER_FRAGMENT].samplers[0]&&!actual.stage[PIPE_SHADER_COMPUTE].samplers[0]);
   /* Repeated CSO/dynamic/vertex bindings consume all incoming refs, on hits
    * as well as native setter calls. A new element state forces the vertex
    * setter after it, even when the actual buffer descriptor is identical. */
   struct pipe_viewport_state vp={0};struct pipe_scissor_state sc={0};struct pipe_blend_color bc={0};struct pipe_stencil_ref sr={0};
   for(unsigned draw=0;draw<5;++draw) {
      for(unsigned k=0;k<RF_BIND_CSO_COUNT;++k)rwa_redfin_bind_cso(&device,(enum redfin_metal_cso)k,&cso[k]);
      rwa_redfin_bind_dynamic(&device,&vp,&sc,&bc);rwa_redfin_bind_stencil(&device,&sr);
      struct pipe_vertex_buffer v={0};pipe_resource_reference(&v.buffer.resource,&d.pipe);rwa_redfin_bind_vertices(&device,1,&v);
   }
   REQUIRE(actual.cso_calls==6&&actual.dynamic_calls==4&&actual.vertex_calls==1&&d.pipe.reference.count==3&&device.binding_stats[9]==4);
   rwa_redfin_bind_cso(&device,RF_BIND_VELEM,&cso[7]);struct pipe_vertex_buffer v={0};pipe_resource_reference(&v.buffer.resource,&d.pipe);rwa_redfin_bind_vertices(&device,1,&v);
   REQUIRE(actual.vertex_calls==2&&d.pipe.reference.count==3);
   rwa_redfin_graphics_invalidate(&device);rwa_redfin_bind_cso(&device,RF_BIND_VS,&cso[3]);
   v=(struct pipe_vertex_buffer){0};
   pipe_resource_reference(&v.buffer.resource,&d.pipe);rwa_redfin_bind_vertices(&device,1,&v);REQUIRE(actual.vertex_calls==3);
   /* Error/scope cleanup removes frontend and receiver bindings while a
    * separately retained native batch still owns the backing resource. */
   struct pipe_resource *pending=NULL;pipe_resource_reference(&pending,&d.pipe);
   rwa_redfin_bindings_clear(&device);uint64_t stats[REDFIN_METAL_BINDING_WORDS];
   REQUIRE(!rwa_redfin_binding_statistics(&device,stats,REDFIN_METAL_BINDING_WORDS)&&!stats[10]&&!stats[11]);
   REQUIRE(!actual.num_vertices&&d.pipe.reference.count==2);
   for(unsigned stage=0;stage<PIPE_SHADER_TYPES;++stage) {
      for(unsigned i=0;i<PIPE_MAX_CONSTANT_BUFFERS;++i)REQUIRE(!actual.stage[stage].cb[i].buffer);
      for(unsigned i=0;i<PIPE_MAX_SHADER_BUFFERS;++i)REQUIRE(!actual.stage[stage].buffers[i].buffer);
      for(unsigned i=0;i<16;++i)REQUIRE(!actual.stage[stage].views[i]&&!actual.stage[stage].images[i].resource&&!actual.stage[stage].samplers[i]);
   }
   struct pipe_resource *owner=&d.pipe;pipe_resource_reference(&owner,NULL);REQUIRE(!d.destroyed&&d.pipe.reference.count==1);
   pipe_resource_reference(&pending,NULL);REQUIRE(d.destroyed==1);
   struct pipe_sampler_view *held=&va.pipe;pipe_sampler_view_reference(&held,NULL);held=&vb.pipe;pipe_sampler_view_reference(&held,NULL);
   for(unsigned i=0;i<3;++i){owner=&resources[i]->pipe;pipe_resource_reference(&owner,NULL);REQUIRE(resources[i]->destroyed==1);}
   REQUIRE(va.destroyed==1&&vb.destroyed==1);
   puts("actual binding cache: descriptor reuse, constant refresh, sparse cleanup, CSO/vertex ownership and error lifetime PASS");return 0;
}
