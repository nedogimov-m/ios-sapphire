/* SPDX-License-Identifier: MIT
 * Compile the actual snapshot and row-copy routines. This receiver checks
 * exact deferred ranges/state/references; real A620 pixels are checked on device.
 */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pipe/p_context.h"
#include "pipe/p_state.h"
#include "pipe/p_screen.h"
#include "util/u_math.h"
#include "metal-command-scope.h"
#include "metal-constant-snapshot.h"
#include "metal-frontend-profile.h"
#include "metal-linear-import.h"
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"snapshot contract: %s at %u\n",#x,__LINE__);abort();}}while(0)
struct resource {struct pipe_resource pipe;uint8_t *data;bool destroyed;};
struct operation {
   struct pipe_resource *source,*destination;
   struct redfin_linear_copy_plan plan;
   unsigned bits,fill;
};
struct receiver {
   struct pipe_context pipe;struct pipe_screen screen;
   struct pipe_constant_buffer constants;
   struct pipe_shader_buffer buffers[2];void *shader;
   struct operation operations[64];unsigned count,finishes,cpu_prepares,cpu_uploads,clears,allocations;
   bool fail_create,fail_prepare,unsupported;
   struct resource *resources[128];unsigned resource_count;
};
struct rwa_device {
   struct pipe_context *pipe;struct pipe_screen *screen;
   struct redfin_metal_command_scope command_scope;
   struct redfin_metal_constant_arena constant_arena;
   uint64_t frontend_stats[REDFIN_METAL_FRONTEND_WORDS];
   unsigned ubo_offset_align;bool software;
};
struct rwa_buffer {struct rwa_device *device;struct pipe_resource *res;size_t size;void *map;bool gpu_pending;};
struct air_resource {unsigned size;};
static void say(char *out,size_t bytes,const char *format,...)
{va_list args;va_start(args,format);if(out&&bytes)vsnprintf(out,bytes,format,args);va_end(args);}
static void pipe_resource_reference(struct pipe_resource **at,struct pipe_resource *next)
{
   if(*at==next)return;
   if(next){REQUIRE(next->reference.count>0);++next->reference.count;}
   struct pipe_resource *old=*at;*at=next;
   if(old){REQUIRE(old->reference.count>0);if(!--old->reference.count)((struct resource *)old)->destroyed=true;}
}
static struct receiver *receiver(struct rwa_device *device){return (struct receiver *)device->pipe;}
static struct pipe_resource *create_resource(struct pipe_screen *screen,const struct pipe_resource *shape)
{
   struct receiver *r=(struct receiver *)((char *)screen-offsetof(struct receiver,screen));
   if(r->fail_create){r->fail_create=false;return NULL;}
   REQUIRE(r->resource_count<128);struct resource *res=calloc(1,sizeof(*res));REQUIRE(res);
   res->pipe=*shape;res->pipe.screen=screen;res->pipe.reference.count=1;
   res->data=malloc(shape->width0+64);REQUIRE(res->data);memset(res->data,0xa5,shape->width0+64);
   r->resources[r->resource_count++]=res;++r->allocations;return &res->pipe;
}
static int compute_param(struct pipe_screen *screen,enum pipe_shader_ir ir,enum pipe_compute_cap cap,void *out)
{
   struct receiver *r=(struct receiver *)((char *)screen-offsetof(struct receiver,screen));
   REQUIRE(ir==PIPE_SHADER_IR_NIR);
   if(r->unsupported)return 0;
   uint64_t values[3]={65535,65535,65535};
   if(cap==PIPE_COMPUTE_CAP_MAX_BLOCK_SIZE){values[0]=1024;values[1]=1024;values[2]=64;}
   else REQUIRE(cap==PIPE_COMPUTE_CAP_MAX_GRID_SIZE);
   if(out)memcpy(out,values,sizeof(values));return sizeof(values);
}
static void set_constants(struct pipe_context *pipe,enum pipe_shader_type stage,unsigned slot,bool owned,const struct pipe_constant_buffer *next)
{
   struct receiver *r=(struct receiver *)pipe;REQUIRE(stage==PIPE_SHADER_COMPUTE&&!slot&&!owned);
   pipe_resource_reference(&r->constants.buffer,next?next->buffer:NULL);
   r->constants.buffer_offset=next?next->buffer_offset:0;r->constants.buffer_size=next?next->buffer_size:0;
}
static void set_buffers(struct pipe_context *pipe,enum pipe_shader_type stage,unsigned first,unsigned count,const struct pipe_shader_buffer *next,unsigned writable)
{
   struct receiver *r=(struct receiver *)pipe;REQUIRE(stage==PIPE_SHADER_COMPUTE&&!first&&count==2&&(writable==0||writable==2));
   for(unsigned i=0;i<count;++i){pipe_resource_reference(&r->buffers[i].buffer,next?next[i].buffer:NULL);r->buffers[i].buffer_size=next?next[i].buffer_size:0;}
}
static void bind_compute(struct pipe_context *pipe,void *shader){((struct receiver *)pipe)->shader=shader;}
static void launch_grid(struct pipe_context *pipe,const struct pipe_grid_info *grid)
{
   struct receiver *r=(struct receiver *)pipe;REQUIRE(r->count<64&&r->constants.buffer&&r->buffers[0].buffer&&r->buffers[1].buffer);
   struct operation *op=&r->operations[r->count++];memset(op,0,sizeof(*op));
   memcpy(&op->plan,((struct resource *)r->constants.buffer)->data+r->constants.buffer_offset,sizeof(op->plan));
   op->bits=(unsigned)(uintptr_t)r->shader;
   REQUIRE((op->bits==8||op->bits==32)&&grid->block[0]==64&&grid->grid[0]==(op->plan.words+63)/64&&grid->grid[1]==op->plan.rows);
   pipe_resource_reference(&op->source,r->buffers[0].buffer);pipe_resource_reference(&op->destination,r->buffers[1].buffer);
}
static int finish(void *opaque,char *why,size_t bytes)
{
   (void)why;(void)bytes;struct rwa_device *device=opaque;struct receiver *r=receiver(device);++r->finishes;
   for(unsigned i=0;i<r->count;++i){struct operation *op=&r->operations[i];
      REQUIRE(op->destination&&!((struct resource *)op->destination)->destroyed);
      uint8_t *dst=((struct resource *)op->destination)->data;
      if(!op->source){memset(dst+op->plan.destination_offset,op->fill,op->plan.words);}
      else {REQUIRE(!((struct resource *)op->source)->destroyed);uint8_t *src=((struct resource *)op->source)->data;
         unsigned row_bytes=op->plan.words*(op->bits/8);
         for(unsigned row=0;row<op->plan.rows;++row){
            uint64_t a=op->plan.source_offset+(uint64_t)row*op->plan.source_pitch,b=op->plan.destination_offset+(uint64_t)row*op->plan.destination_pitch;
            REQUIRE(a<=op->source->width0&&row_bytes<=op->source->width0-a&&b<=op->destination->width0&&row_bytes<=op->destination->width0-b);
            memcpy(dst+b,src+a,row_bytes);
         }
      }
      pipe_resource_reference(&op->source,NULL);pipe_resource_reference(&op->destination,NULL);
   }
   r->count=0;return 0;
}
static int rwa_redfin_gpu_prepare(struct rwa_device *device,char *why,size_t bytes)
{(void)why;(void)bytes;return receiver(device)->fail_prepare||device->command_scope.failed?-1:0;}
static int rwa_redfin_buffer_prepare(struct rwa_buffer *buffer,char *why,size_t bytes)
{return rwa_redfin_gpu_prepare(buffer->device,why,bytes);}
static int rwa_redfin_buffer_cpu_prepare(struct rwa_buffer *buffer,char *why,size_t bytes)
{++receiver(buffer->device)->cpu_prepares;int error=buffer->gpu_pending?redfin_metal_scope_drain(&buffer->device->command_scope,finish,buffer->device,why,bytes):0;if(!error)buffer->gpu_pending=false;return error;}
static uint64_t rwa_redfin_profile_clock(void){static uint64_t tick;return ++tick;}
static void rwa_redfin_profile_elapsed(struct rwa_device *device,unsigned field,uint64_t began)
{device->frontend_stats[field]+=rwa_redfin_profile_clock()-began;}
static void *rwa_redfin_row_shader(struct rwa_device *device,unsigned bits,char *why,size_t bytes)
{(void)device;(void)why;(void)bytes;return (void *)(uintptr_t)bits;}
static void rwa_redfin_bindings_clear_stage(struct rwa_device *device,enum pipe_shader_type stage)
{REQUIRE(stage==PIPE_SHADER_COMPUTE);++receiver(device)->clears;}
static int rwa_blit_fail(char *why,size_t bytes,const char *message){say(why,bytes,"%s",message);return -1;}
static bool rwa_blit_range(uint64_t offset,uint64_t bytes,uint64_t total)
{return offset<=total&&bytes<=total-offset&&offset<=UINT32_MAX&&bytes<=UINT32_MAX-offset;}
static int rwa_blit_finish(struct rwa_device *device,char *why,size_t bytes)
{return redfin_metal_scope_complete(&device->command_scope,true,finish,device,why,bytes);}
static int rwa_redfin_constant_upload(struct rwa_device *device,const void *data,size_t bytes,struct pipe_constant_buffer *out,char *why,size_t why_size)
{
   (void)why;(void)why_size;++receiver(device)->cpu_uploads;
   struct pipe_resource shape={.target=PIPE_BUFFER,.width0=(unsigned)bytes,.bind=PIPE_BIND_CONSTANT_BUFFER};
   struct pipe_resource *res=create_resource(device->screen,&shape);if(!res)return -1;
   memcpy(((struct resource *)res)->data,data,bytes);*out=(struct pipe_constant_buffer){.buffer=res,.buffer_size=(unsigned)bytes};return 0;
}
#include "actual-rows.inc"
#include "metal-constant-snapshot.inc"
#include "actual-snapshot.inc"

static void queue_fill(struct rwa_device *device,struct rwa_buffer *buffer,unsigned value)
{
   struct receiver *r=receiver(device);struct operation *op=&r->operations[r->count++];*op=(struct operation){.fill=value,.plan={.words=(unsigned)buffer->size}};
   pipe_resource_reference(&op->destination,buffer->res);buffer->gpu_pending=true;device->command_scope.pending=true;
}
int main(void)
{
   struct receiver actual={.pipe={.set_constant_buffer=set_constants,.set_shader_buffers=set_buffers,.bind_compute_state=bind_compute,.launch_grid=launch_grid},
      .screen={.resource_create=create_resource,.get_compute_param=compute_param}};
   struct rwa_device device={.pipe=&actual.pipe,.screen=&actual.screen,.ubo_offset_align=64};
   struct pipe_resource shape={.target=PIPE_BUFFER,.width0=320*1024+63};
   struct rwa_buffer source={.device=&device,.res=create_resource(&actual.screen,&shape),.size=shape.width0};
   source.map=((struct resource *)source.res)->data;memset(source.map,0x13,source.size);
   struct air_resource unknown={0};char why[256]={0};
   REQUIRE(!redfin_metal_scope_begin(&device.command_scope));
   const unsigned offsets[5]={1,3,4,63,5};struct pipe_constant_buffer slices[5]={0};
   for(unsigned i=0;i<5;++i){if(i)queue_fill(&device,&source,0x13+i);
      REQUIRE(!rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,offsets[i],source.size-offsets[i],&slices[i],why,sizeof(why)));
      REQUIRE(slices[i].buffer_offset%64==0&&slices[i].buffer_size==source.size-offsets[i]);
      REQUIRE(i?device.command_scope.pending:!device.command_scope.pending);
   }
   REQUIRE(actual.finishes==0&&actual.cpu_prepares==1&&device.frontend_stats[RF_MFP_CONSTANT_GPU]==4&&device.frontend_stats[RF_MFP_CONSTANT_GPU_CHUNKS]==2);
   REQUIRE(slices[1].buffer!=slices[4].buffer&&slices[1].buffer_offset!=slices[2].buffer_offset);
   REQUIRE(!redfin_metal_scope_end(&device.command_scope,finish,&device,why,sizeof(why))&&actual.finishes==1);
   for(unsigned i=0;i<5;++i){struct resource *res=(struct resource *)slices[i].buffer;
      for(unsigned j=0;j<slices[i].buffer_size;++j)REQUIRE(res->data[slices[i].buffer_offset+j]==0x13+i);
      for(unsigned j=slices[i].buffer_offset+slices[i].buffer_size;j<res->pipe.width0&&j%64;++j)REQUIRE(res->data[j]==0xa5);
      for(unsigned j=res->pipe.width0;j<res->pipe.width0+64;++j)REQUIRE(res->data[j]==0xa5);
      pipe_resource_reference(&slices[i].buffer,NULL);
   }
   /* Small copies stay on CPU. Invalid logical/native ranges emit nothing. */
   REQUIRE(!redfin_metal_scope_begin(&device.command_scope));source.gpu_pending=false;
   struct pipe_constant_buffer result={0};unsigned queued=actual.count;
   REQUIRE(!rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,3,67,&result,why,sizeof(why))&&actual.cpu_prepares==2);
   pipe_resource_reference(&result.buffer,NULL);
   REQUIRE(rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,source.size-3,4,&result,why,sizeof(why))<0&&actual.count==queued);
   source.size+=4;REQUIRE(rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,source.size-4,4,&result,why,sizeof(why))<0);source.size-=4;
   /* A refusal before work preserves the real CPU dependency wait. */
   queue_fill(&device,&source,0x91);device.constant_arena.offset=REDFIN_METAL_GPU_SNAPSHOT_CHUNK;
   actual.fail_create=true;
   REQUIRE(!rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,1,source.size-1,&result,why,sizeof(why))&&actual.finishes==2&&actual.cpu_prepares==3);
   REQUIRE(((struct resource *)result.buffer)->data[0]==0x91);pipe_resource_reference(&result.buffer,NULL);
   /* Work emitted before a later error retains its source/destination until
    * the failed scope pays its actual drain, even after API owners go away. */
   queue_fill(&device,&source,0x92);
   REQUIRE(!rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,3,source.size-3,&result,why,sizeof(why)));
   struct resource *pending=(struct resource *)result.buffer,*original=(struct resource *)source.res;
   pipe_resource_reference(&result.buffer,NULL);pipe_resource_reference(&device.constant_arena.resource,NULL);
   actual.fail_prepare=true;
   REQUIRE(rwa_redfin_profile_constant_snapshot(&device,&unknown,&source,3,source.size-3,&result,why,sizeof(why))<0&&device.command_scope.pending);
   pipe_resource_reference(&source.res,NULL);REQUIRE(!pending->destroyed&&!original->destroyed);
   device.command_scope.failed=true;
   REQUIRE(redfin_metal_scope_end(&device.command_scope,finish,&device,why,sizeof(why))<0&&actual.finishes==3);
   REQUIRE(pending->destroyed&&original->destroyed);
   pipe_resource_reference(&device.constant_arena.resource,NULL);
   /* Unsupported caps, legacy calls, excessive grid and alignment use CPU. */
   device.command_scope=(struct redfin_metal_command_scope){.active=true};actual.fail_prepare=false;
   device.constant_arena=(struct redfin_metal_constant_arena){0};actual.unsupported=true;
   REQUIRE(!rwa_redfin_constant_gpu_supported(&device,1,16384));actual.unsupported=false;
   device.constant_arena=(struct redfin_metal_constant_arena){.queried=true,.supported=true,.grid_x=1};
   REQUIRE(!rwa_redfin_constant_gpu_supported(&device,1,16384));
   device.command_scope.active=false;REQUIRE(!rwa_redfin_constant_gpu_supported(&device,4,16384));
   pipe_resource_reference(&device.constant_arena.resource,NULL);
   for(unsigned i=0;i<actual.resource_count;++i){REQUIRE(actual.resources[i]->destroyed);free(actual.resources[i]->data);free(actual.resources[i]);}
   puts("actual immutable snapshots: bounds/fallback/order/rollover/error/lifetime PASS");return 0;
}
