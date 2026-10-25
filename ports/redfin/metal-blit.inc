/* SPDX-License-Identifier: MIT */
/* Metal transfers use the actual A6xx blitter or bounded NIR byte/word copies.
 * A native refusal never falls through to Gallium's generic CPU copy path. */
static int
rwa_blit_fail(char *why,size_t bytes,const char *message)
{say(why,bytes,"%s",message);return -1;}
static bool
rwa_blit_range(uint64_t offset,uint64_t bytes,uint64_t total)
{return offset<=total&&bytes<=total-offset&&offset<=UINT32_MAX&&bytes<=UINT32_MAX-offset;}
static int
rwa_blit_finish(struct rwa_device *device,char *why,size_t bytes)
{return redfin_metal_scope_complete(&device->command_scope,false,command_scope_finish,device,why,bytes);}
static int
rwa_blit_box(struct rwa_device *device,struct rwa_texture *texture,uint64_t level,uint64_t slice,
    const uint64_t origin[3],const uint64_t size[3],struct pipe_box *box,char *why,size_t bytes)
{
   if(!texture||texture->device!=device||!texture->res||texture->res->target==PIPE_BUFFER||
      texture->res->nr_samples>1||level>texture->res->last_level||
      format_is_depth_stencil(texture->res->format)||util_format_is_compressed(texture->res->format))
      return rwa_blit_fail(why,bytes,"native blit needs a same-device nonmultisample colour texture");
   const struct pipe_resource *r=texture->res;bool volume=r->target==PIPE_TEXTURE_3D;
   uint64_t dimensions[3]={u_minify(r->width0,level),u_minify(r->height0,level),volume?u_minify(r->depth0,level):1};
   if((volume&&slice)||(!volume&&slice>=texture->layers))return rwa_blit_fail(why,bytes,"blit slice exceeds its texture");
   unsigned o[3],s[3];
   for(unsigned i=0;i<3;++i) {
      if(!size[i]||origin[i]>dimensions[i]||size[i]>dimensions[i]-origin[i]||
         origin[i]>INT32_MAX||size[i]>INT32_MAX)return rwa_blit_fail(why,bytes,"blit region exceeds its mip level");
      o[i]=(unsigned)origin[i];s[i]=(unsigned)size[i];
   }
   return texture_box(texture,(unsigned)level,(unsigned)slice,o,s,box,why,bytes)?0:-1;
}
static int
rwa_blit_native(struct rwa_device *device,struct pipe_resource *source,unsigned source_level,const struct pipe_box *source_box,
    struct pipe_resource *destination,unsigned destination_level,const struct pipe_box *destination_box,unsigned filter,
    char *why,size_t bytes)
{
   if(redfin_metal_scope_prepare(&device->command_scope,false,command_scope_finish,device,why,bytes))return -1;
   struct pipe_blit_info info={.src={.resource=source,.level=source_level,.format=source->format,.box=*source_box},
      .dst={.resource=destination,.level=destination_level,.format=destination->format,.box=*destination_box},
      .mask=util_format_get_mask(source->format),.filter=filter};
   if(filter==PIPE_TEX_FILTER_NEAREST&&util_format_linear(source->format)==util_format_linear(destination->format))
      info.src.format=info.dst.format=util_format_linear(source->format);
   if(redfin_freedreno_gpu_blit(device->pipe,&info))return rwa_blit_fail(why,bytes,"A620 declined this GPU blit; no CPU fallback");
   return rwa_blit_finish(device,why,bytes);
}
static int
rwa_blit_rows(struct rwa_device *device,struct pipe_resource *source,struct pipe_resource *destination,
    uint64_t source_offset,uint64_t destination_offset,uint64_t source_pitch,uint64_t destination_pitch,
    uint64_t pixel_bytes,uint64_t rows,char *why,size_t bytes)
{
   if(!rows||!pixel_bytes||rows>UINT32_MAX||pixel_bytes>UINT32_MAX||source_pitch>UINT32_MAX||destination_pitch>UINT32_MAX||
      pixel_bytes>source_pitch||pixel_bytes>destination_pitch||source_offset>UINT32_MAX||destination_offset>UINT32_MAX||
      (rows-1)*source_pitch+pixel_bytes>UINT32_MAX-source_offset||
      (rows-1)*destination_pitch+pixel_bytes>UINT32_MAX-destination_offset||
      !rwa_blit_range(source_offset,(rows-1)*source_pitch+pixel_bytes,source->width0)||
      !rwa_blit_range(destination_offset,(rows-1)*destination_pitch+pixel_bytes,destination->width0))
      return rwa_blit_fail(why,bytes,"GPU row copy exceeds the actual buffer range");
   bool words=!((source_offset|destination_offset|source_pitch|destination_pitch|pixel_bytes)&3);
   struct redfin_linear_copy_plan plan={(unsigned)(words?pixel_bytes/4:pixel_bytes),(unsigned)rows,
      (unsigned)source_pitch,(unsigned)destination_pitch,(unsigned)source_offset,(unsigned)destination_offset};
   void *shader=rwa_redfin_row_shader(device,words?32:8,why,bytes);if(!shader)return -1;
   if(redfin_metal_scope_prepare(&device->command_scope,false,command_scope_finish,device,why,bytes))return -1;
   struct pipe_context *pipe=device->pipe;
   struct pipe_shader_buffer buffers[2]={{.buffer=source,.buffer_size=source->width0},
      {.buffer=destination,.buffer_size=destination->width0}};
   struct pipe_constant_buffer constants={.user_buffer=&plan,.buffer_size=sizeof(plan)};
   pipe->bind_compute_state(pipe,shader);pipe->set_constant_buffer(pipe,PIPE_SHADER_COMPUTE,0,false,&constants);
   pipe->set_shader_buffers(pipe,PIPE_SHADER_COMPUTE,0,2,buffers,2);
   const struct pipe_grid_info grid={.work_dim=2,.block={64,1,1},.grid={((uint64_t)plan.words+63)/64,plan.rows,1}};
   pipe->launch_grid(pipe,&grid);int result=rwa_blit_finish(device,why,bytes);
   pipe->set_shader_buffers(pipe,PIPE_SHADER_COMPUTE,0,2,NULL,0);pipe->set_constant_buffer(pipe,PIPE_SHADER_COMPUTE,0,false,NULL);
   pipe->bind_compute_state(pipe,NULL);
   if(!result&&pipe->memory_barrier)pipe->memory_barrier(pipe,PIPE_BARRIER_ALL);
   return result;
}
int
rwa_redfin_blit(struct rwa_device *device,struct rwa_buffer *source_buffer,struct rwa_buffer *destination_buffer,
    struct rwa_texture *source_texture,struct rwa_texture *destination_texture,const struct redfin_metal_blit *request,
    char *why,size_t bytes)
{
   if(!device||device->software||!request||request->options||request->operation<RF_BLIT_BUFFER||request->operation>RF_BLIT_SYNC)
      return rwa_blit_fail(why,bytes,"unsupported native Metal blit command/options");
   if((source_buffer&&source_buffer->device!=device)||(destination_buffer&&destination_buffer->device!=device)||
      (source_texture&&source_texture->device!=device)||(destination_texture&&destination_texture->device!=device))
      return rwa_blit_fail(why,bytes,"blit resources belong to another Metal device");
   if((source_buffer&&(!source_buffer->res||source_buffer->res->target!=PIPE_BUFFER||source_buffer->size>source_buffer->res->width0))||
      (destination_buffer&&(!destination_buffer->res||destination_buffer->res->target!=PIPE_BUFFER||destination_buffer->size>destination_buffer->res->width0)))
      return rwa_blit_fail(why,bytes,"blit buffer exceeds its native resource");
   if(rwa_redfin_buffer_prepare(source_buffer,why,bytes)||rwa_redfin_buffer_prepare(destination_buffer,why,bytes))return -1;
   if(redfin_metal_scope_prepare(&device->command_scope,false,command_scope_finish,device,why,bytes))return -1;
   static unsigned observations[RF_BLIT_INVALID];
   if(observations[request->operation]++<4)fprintf(stderr,
      "REDFIN METAL BLIT REQUEST: operation=%u size=%llux%llux%llu offsets=%llu/%llu pitches=%llu/%llu levels=%llu/%llu slices=%llu/%llu\n",
      request->operation,(unsigned long long)request->size[0],(unsigned long long)request->size[1],
      (unsigned long long)request->size[2],(unsigned long long)request->source_offset,
      (unsigned long long)request->destination_offset,(unsigned long long)request->row_bytes,
      (unsigned long long)request->image_bytes,(unsigned long long)request->source_level,
      (unsigned long long)request->destination_level,(unsigned long long)request->source_slice,
      (unsigned long long)request->destination_slice);
   int result=-1;struct pipe_context *pipe=device->pipe;
   if(request->operation==RF_BLIT_SYNC) {
      if(!source_buffer&&!source_texture)goto invalid;
      if(source_texture&&(request->source_level>source_texture->res->last_level||request->source_slice>=source_texture->layers))goto invalid;
      result=rwa_redfin_linear_resolve_all(device,why,bytes);
   } else if(request->operation==RF_BLIT_BUFFER||request->operation==RF_BLIT_FILL) {
      uint64_t count=request->size[0],destination=request->destination_offset;
      if(!destination_buffer||!rwa_blit_range(destination,count,destination_buffer->size))goto invalid;
      if(request->operation==RF_BLIT_FILL) {
         if(!count)return 0;
         if(request->fill_value>255||redfin_freedreno_gpu_fill(pipe,destination_buffer->res,
            (unsigned)destination,(unsigned)count,(uint8_t)request->fill_value))goto invalid;
         result=rwa_blit_finish(device,why,bytes);
      } else {
         uint64_t source=request->source_offset;
         if(!source_buffer||!rwa_blit_range(source,count,source_buffer->size))goto invalid;
         if(!count)return 0;
         uintptr_t sa=(uintptr_t)source_buffer->map,da=(uintptr_t)destination_buffer->map;
         bool shared=source_buffer->res==destination_buffer->res||
            (source_buffer->external_surface&&source_buffer->external_surface==destination_buffer->external_surface);
         bool overlap=shared&&source<destination+count&&destination<source+count;
         if(sa&&da&&sa<=UINTPTR_MAX-source_buffer->size&&da<=UINTPTR_MAX-destination_buffer->size)
            overlap|=sa+source<da+destination+count&&da+destination<sa+source+count;
         if(overlap)
            return rwa_blit_fail(why,bytes,"overlapping Metal buffer copy");
         result=rwa_blit_rows(device,source_buffer->res,destination_buffer->res,source,destination,count,count,count,1,why,bytes);
      }
   } else if(request->operation==RF_BLIT_TEXTURE) {
      struct pipe_box source,destination;
      if(rwa_blit_box(device,source_texture,request->source_level,request->source_slice,request->source_origin,request->size,&source,why,bytes)||
         rwa_blit_box(device,destination_texture,request->destination_level,request->destination_slice,request->destination_origin,request->size,&destination,why,bytes))return -1;
      if(util_format_linear(source_texture->res->format)!=util_format_linear(destination_texture->res->format))goto invalid;
      bool aliases=source_texture->res==destination_texture->res||
         (source_texture->redfin_surface&&source_texture->redfin_surface==destination_texture->redfin_surface);
      if(source_texture->buffer_parent&&destination_texture->buffer_parent&&
         rwa_redfin_buffers_share(source_texture->buffer_parent,destination_texture->buffer_parent)) {
         struct rwa_buffer *sp=source_texture->buffer_parent,*dp=destination_texture->buffer_parent;
         uint64_t cpp=util_format_get_blocksize(source_texture->res->format);
         uint64_t a=source_texture->buffer_offset+(uint64_t)source.y*source_texture->buffer_pitch+(uint64_t)source.x*cpp;
         uint64_t b=destination_texture->buffer_offset+(uint64_t)destination.y*destination_texture->buffer_pitch+(uint64_t)destination.x*cpp;
         if(sp->res!=dp->res&&!(sp->external_surface&&sp->external_surface==dp->external_surface)) {
            a+=(uintptr_t)sp->map;b+=(uintptr_t)dp->map;
         }
         if(rwa_redfin_view_rows_overlap(a,source_texture->buffer_pitch,(uint32_t)(source.width*cpp),source.height,
            b,destination_texture->buffer_pitch,(uint32_t)(destination.width*cpp),destination.height))
            return rwa_blit_fail(why,bytes,"overlapping buffer-backed Metal texture copy");
      }
      if(aliases&&request->source_level==request->destination_level&&
         source.x<destination.x+destination.width&&destination.x<source.x+source.width&&
         source.y<destination.y+destination.height&&destination.y<source.y+source.height&&
         source.z<destination.z+destination.depth&&destination.z<source.z+source.depth)
         return rwa_blit_fail(why,bytes,"overlapping Metal texture copy");
      if(rwa_redfin_linear_prepare(source_texture,why,bytes)||rwa_redfin_linear_prepare(destination_texture,why,bytes))return -1;
      for(int z=0;z<source.depth;++z) {
         struct pipe_box s=source,d=destination;s.z+=z;d.z+=z;s.depth=d.depth=1;
         if(rwa_blit_native(device,source_texture->res,request->source_level,&s,destination_texture->res,request->destination_level,&d,PIPE_TEX_FILTER_NEAREST,why,bytes))return -1;
      }
      rwa_redfin_linear_written(destination_texture);result=0;
   } else if(request->operation==RF_BLIT_UPLOAD||request->operation==RF_BLIT_DOWNLOAD) {
      bool upload=request->operation==RF_BLIT_UPLOAD;
      struct rwa_texture *texture=upload?destination_texture:source_texture;
      struct rwa_buffer *buffer=upload?source_buffer:destination_buffer;struct pipe_box region;
      if(!buffer)goto invalid;
      if(rwa_blit_box(device,texture,upload?request->destination_level:request->source_level,
         upload?request->destination_slice:request->source_slice,upload?request->destination_origin:request->source_origin,
         request->size,&region,why,bytes))return -1;
      uint64_t pixel_bytes=(uint64_t)region.width*util_format_get_blocksize(texture->res->format);
      uint64_t pitch=request->row_bytes?request->row_bytes:pixel_bytes;
      uint64_t image=request->image_bytes?request->image_bytes:pitch*region.height;
      uint64_t offset=upload?request->source_offset:request->destination_offset;
      if(pitch<pixel_bytes||pitch>UINT32_MAX||image<pitch*region.height||image>UINT32_MAX||
         !rwa_blit_range(offset,(uint64_t)(region.depth-1)*image+(region.height-1)*pitch+pixel_bytes,buffer->size))goto invalid;
      if(rwa_redfin_linear_prepare(texture,why,bytes))return -1;
      const struct pipe_resource shape={.target=PIPE_TEXTURE_2D,.format=texture->res->format,
         .width0=region.width,.height0=region.height,.depth0=1,.array_size=1,
         .bind=PIPE_BIND_SAMPLER_VIEW|PIPE_BIND_RENDER_TARGET|PIPE_BIND_LINEAR,.usage=PIPE_USAGE_DEFAULT};
      const uint64_t modifier=DRM_FORMAT_MOD_LINEAR;
      struct pipe_resource *stage=device->screen->resource_create_with_modifiers(device->screen,&shape,&modifier,1);
      unsigned stage_pitch=0,stage_offset=0;
      struct pipe_resource *stage_buffer=stage?redfin_freedreno_buffer_alias(device->screen,stage,&stage_pitch,&stage_offset):NULL;
      if(!stage||!stage_buffer){pipe_resource_reference(&stage_buffer,NULL);pipe_resource_reference(&stage,NULL);goto invalid;}
      result=0;
      for(int z=0;!result&&z<region.depth;++z) {
         struct pipe_box native=region,linear={.width=region.width,.height=region.height,.depth=1};native.z+=z;native.depth=1;
         if(upload) {
            result=rwa_blit_rows(device,buffer->res,stage_buffer,offset+(uint64_t)z*image,stage_offset,pitch,stage_pitch,pixel_bytes,region.height,why,bytes);
            if(!result)result=redfin_freedreno_alias_written(pipe,stage);
            if(!result)result=rwa_blit_native(device,stage,0,&linear,texture->res,request->destination_level,&native,PIPE_TEX_FILTER_NEAREST,why,bytes);
         } else {
            result=rwa_blit_native(device,texture->res,request->source_level,&native,stage,0,&linear,PIPE_TEX_FILTER_NEAREST,why,bytes);
            if(!result)result=rwa_blit_rows(device,stage_buffer,buffer->res,stage_offset,offset+(uint64_t)z*image,stage_pitch,pitch,pixel_bytes,region.height,why,bytes);
         }
      }
      pipe_resource_reference(&stage_buffer,NULL);pipe_resource_reference(&stage,NULL);
      if(!result&&upload)rwa_redfin_linear_written(texture);
   } else if(request->operation==RF_BLIT_MIPMAP) {
      struct rwa_texture *texture=destination_texture;
      if(!texture||!texture->res||texture->res->target==PIPE_BUFFER||texture->res->nr_samples>1||format_is_depth_stencil(texture->res->format)||
         util_format_is_compressed(texture->res->format)||texture->res->target==PIPE_TEXTURE_3D)goto invalid;
      if(texture->res->last_level==0)return 0;
      if(rwa_redfin_linear_prepare(texture,why,bytes))return -1;
      for(unsigned level=1;level<=texture->res->last_level;++level)for(unsigned layer=0;layer<texture->layers;++layer) {
         struct pipe_box s,d;const uint64_t origin[3]={0,0,0};
         const uint64_t source_size[3]={u_minify(texture->res->width0,level-1),u_minify(texture->res->height0,level-1),1};
         const uint64_t destination_size[3]={u_minify(texture->res->width0,level),u_minify(texture->res->height0,level),1};
         if(rwa_blit_box(device,texture,level-1,layer,origin,source_size,&s,why,bytes)||
            rwa_blit_box(device,texture,level,layer,origin,destination_size,&d,why,bytes))return -1;
         if(rwa_blit_native(device,texture->res,level-1,&s,texture->res,level,&d,PIPE_TEX_FILTER_LINEAR,why,bytes))return -1;
      }
      rwa_redfin_linear_written(texture);result=0;
   }
   if(!result&&destination_buffer)rwa_redfin_buffer_written(destination_buffer);
   if(!result&&!device->command_scope.active)result=rwa_redfin_linear_resolve_all(device,why,bytes);
   if(!result) {
      static uint64_t calls;uint64_t n=++calls;
      if(n<=12||!(n&(n-1)))fprintf(stderr,"REDFIN METAL BLIT: operation=%u sequence=%llu actual-native-completion=1 CPU-pixel-copy=0\n",request->operation,(unsigned long long)n);
   }
   return result;
invalid:
   return rwa_blit_fail(why,bytes,"invalid or unsupported native Metal blit resource/range");
}
