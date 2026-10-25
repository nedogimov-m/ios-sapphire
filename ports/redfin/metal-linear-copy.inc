/* SPDX-License-Identifier: MIT */
/* The original IOSurface is a bounded raw GPU buffer, never an unaligned
 * sampler/render target. Native NIR copies its rows to/from a real aligned
 * linear texture. Alias handoffs submit in queue order; CPU consumers and
 * scope completion pay the real final fence. */
extern struct pipe_resource *redfin_freedreno_import_buffer(struct pipe_screen *,unsigned);
extern struct pipe_resource *redfin_freedreno_buffer_alias(struct pipe_screen *,
    struct pipe_resource *,unsigned *,unsigned *);

static void *
rwa_redfin_row_shader(struct rwa_device *device,unsigned bits,char *why,size_t why_size)
{
   void **slot=bits==8?&device->linear_byte_copy_cso:&device->linear_copy_cso;
   if(*slot)return *slot;
   nir_builder b=nir_builder_init_simple_shader(MESA_SHADER_COMPUTE,device->nir_options,
      "Redfin native IOSurface row conversion");
   b.shader->info.workgroup_size[0]=64;b.shader->info.workgroup_size[1]=1;
   b.shader->info.workgroup_size[2]=1;b.shader->info.workgroup_size_variable=false;
   b.shader->info.num_ubos=1;b.shader->info.num_ssbos=2;
   nir_def *parameters[6];
   for(unsigned i=0;i<6;++i)parameters[i]=nir_load_ubo(&b,1,32,nir_imm_int(&b,0),nir_imm_int(&b,4*i),
      .align_mul=4,.align_offset=0,.range_base=4*i,.range=4);
   nir_def *id=nir_load_global_invocation_id(&b,32),*x=nir_channel(&b,id,0),*y=nir_channel(&b,id,1);
   nir_push_if(&b,nir_iand(&b,nir_ult(&b,x,parameters[0]),nir_ult(&b,y,parameters[1])));
   nir_def *column=bits==8?x:nir_ishl_imm(&b,x,2);
   nir_def *source=nir_iadd(&b,parameters[4],nir_iadd(&b,nir_imul(&b,y,parameters[2]),column));
   nir_def *destination=nir_iadd(&b,parameters[5],nir_iadd(&b,nir_imul(&b,y,parameters[3]),column));
   nir_def *word=nir_load_ssbo(&b,1,bits,nir_imm_int(&b,0),source,
      .align_mul=bits/8,.align_offset=0,.access=ACCESS_NON_WRITEABLE);
   nir_store_ssbo(&b,word,nir_imm_int(&b,1),destination,
      .align_mul=bits/8,.align_offset=0,.write_mask=1,.access=ACCESS_NON_READABLE);
   nir_pop_if(&b,NULL);
   nir_shader_gather_info(b.shader,nir_shader_get_entrypoint(b.shader));
   finalize_for_gallium(b.shader,device->screen);
   *slot=device->pipe->create_compute_state(device->pipe,
      &(struct pipe_compute_state){.ir_type=PIPE_SHADER_IR_NIR,.prog=b.shader});
   if(!*slot)say(why,why_size,"native GPU row-copy shader creation failed");
   return *slot;
}

static int
rwa_redfin_copy_rows(struct rwa_texture *texture,bool output,char *why,size_t why_size)
{
   struct rwa_device *device=texture->device;struct pipe_context *pipe=device->pipe;
   struct pipe_resource *source=output?texture->linear_shadow_buffer:texture->linear_original;
   struct pipe_resource *destination=output?texture->linear_original:texture->linear_shadow_buffer;
   unsigned cpp=util_format_get_blocksize(texture->res->format);
   /* Shadow texture and its raw buffer are distinct Gallium resources. The
    * submit resolves GMEM and orders their shared BO without a CPU wait. */
   if(output||(!texture->buffer_parent&&texture->linear_surface)) {
      if(rwa_redfin_gpu_alias_transition(device,why,why_size))return -1;
   } else if(rwa_redfin_buffer_prepare(texture->buffer_parent,why,why_size))return -1;
   int result=rwa_blit_rows(device,source,destination,
      output?texture->linear_shadow_offset:texture->linear_offset,
      output?texture->linear_offset:texture->linear_shadow_offset,
      output?texture->linear_shadow_pitch:texture->linear_pitch,
      output?texture->linear_pitch:texture->linear_shadow_pitch,
      (uint64_t)texture->res->width0*cpp,texture->res->height0,why,why_size);
   if(!result)result=rwa_redfin_gpu_alias_transition(device,why,why_size);
   if(!result&&redfin_freedreno_alias_written(pipe,output?texture->linear_original:texture->res)) {
      device->command_scope.failed=true;say(why,why_size,"native GPU alias transition refused");result=-1;
   }
   if(!result) {
      unsigned direction=output?1:0;uint64_t count=++device->linear_copies[direction];
      if(count<=4)fprintf(stderr,"REDFIN METAL LINEAR COPY: direction=%s width=%u height=%u pitch=%u aligned-pitch=%u queue-ordered-GPU=1 CPU-pixel-copy=0\n",
         output?"resolve":"import",texture->res->width0,texture->res->height0,
         texture->linear_pitch,texture->linear_shadow_pitch);
   }
   return result;
}

static int
rwa_redfin_linear_backing(struct rwa_texture *texture,const struct pipe_resource *templ,
    struct pipe_resource *original,unsigned surface,unsigned offset,unsigned pitch,char *why,size_t why_size)
{
   struct rwa_device *device=texture->device;
   unsigned cpp=util_format_get_blocksize(templ->format);
   texture->linear_original=original; /* owns this real native resource reference */
   if(!texture->linear_original||!redfin_linear_layout_fits(templ->width0,templ->height0,cpp,
      pitch,offset,texture->linear_original->width0))goto fail;
   const uint64_t modifier=DRM_FORMAT_MOD_LINEAR;
   if(!device->screen->resource_create_with_modifiers)goto fail;
   texture->res=device->screen->resource_create_with_modifiers(device->screen,templ,&modifier,1);
   if(!texture->res)goto fail;
   texture->linear_shadow_buffer=redfin_freedreno_buffer_alias(device->screen,texture->res,
      &texture->linear_shadow_pitch,&texture->linear_shadow_offset);
   if(!texture->linear_shadow_buffer||texture->linear_shadow_pitch%64)goto fail;
   texture->linear_pitch=pitch;texture->linear_offset=offset;texture->linear_surface=surface;
   struct redfin_linear_copy_plan plan;
   if(!redfin_linear_copy_plan_make(&plan,templ->width0*cpp,templ->height0,pitch,
      texture->linear_shadow_pitch,offset,texture->linear_shadow_offset,
      texture->linear_original->width0,texture->linear_shadow_buffer->width0))goto fail;
   texture->linear_next=device->linear_textures;device->linear_textures=texture;
   return 0;
fail:
   pipe_resource_reference(&texture->linear_shadow_buffer,NULL);
   pipe_resource_reference(&texture->linear_original,NULL);
   pipe_resource_reference(&texture->res,NULL);
   say(why,why_size,"IOSurface %u pitch %u has no valid bounded native GPU conversion",surface,pitch);
   return -1;
}


static int
rwa_redfin_linear_import(struct rwa_texture *texture,const struct pipe_resource *templ,
    unsigned surface,unsigned offset,unsigned pitch,char *why,size_t why_size)
{
   return rwa_redfin_linear_backing(texture,templ,redfin_freedreno_import_buffer(texture->device->screen,surface),
      surface,offset,pitch,why,why_size);
}

static int
rwa_redfin_linear_prepare(struct rwa_texture *texture,char *why,size_t why_size)
{
   if(!texture)return 0;
   if(rwa_redfin_buffer_texture_prepare(texture,why,why_size))return -1;
   if(!texture->linear_original)return 0;
   struct rwa_device *device=texture->device;
   /* Keep the newest shadow for repeated GPU consumers in this command.
    * A different alias resolves it to the parent in queue order. */
   if(texture->linear_dirty)return 0;
   for(struct rwa_texture *other=device->linear_textures;other;other=other->linear_next)
      if(texture->linear_surface&&other!=texture&&other->linear_surface==texture->linear_surface&&other->linear_dirty)
         if(rwa_redfin_linear_resolve(other,why,why_size))return -1;
   if(device->command_scope.active&&texture->linear_epoch==device->linear_epoch)return 0;
   int result=rwa_redfin_copy_rows(texture,false,why,why_size);
   if(!result)texture->linear_epoch=device->linear_epoch;
   return result;
}
static void
rwa_redfin_linear_changed(struct rwa_texture *texture,bool gpu)
{
   if(!texture)return;
   struct rwa_device *device=texture->device;
   if(texture->linear_original)texture->linear_dirty=true;
   unsigned surface=texture->linear_surface?texture->linear_surface:texture->redfin_surface;
   for(struct rwa_texture *other=device->linear_textures;other;other=other->linear_next)
      if(surface&&other!=texture&&other->linear_surface==surface)other->linear_epoch=0;
   if(texture->buffer_parent) {
      texture->buffer_pending=gpu&&(device->command_scope.active||device->command_scope.pending);
      rwa_redfin_buffer_changed(texture->buffer_parent,texture,gpu);
   }
   texture->linear_epoch=device->linear_epoch;
}
static void
rwa_redfin_linear_written(struct rwa_texture *texture)
{rwa_redfin_linear_changed(texture,true);}
static void
rwa_redfin_linear_cpu_written(struct rwa_texture *texture)
{rwa_redfin_linear_changed(texture,false);}
static int
rwa_redfin_linear_resolve(struct rwa_texture *texture,char *why,size_t why_size)
{
   if(!texture||!texture->linear_dirty)return 0;
   int result=rwa_redfin_copy_rows(texture,true,why,why_size);
   if(!result) {
      texture->linear_dirty=false;
      ++texture->device->ordering[4];
      rwa_redfin_buffer_written(texture->buffer_parent);
      texture->linear_epoch=texture->device->linear_epoch;
   }
   return result;
}
static int
rwa_redfin_linear_resolve_all(struct rwa_device *device,char *why,size_t why_size)
{
   for(struct rwa_texture *t=device->linear_textures;t;t=t->linear_next)
      if(rwa_redfin_linear_resolve(t,why,why_size))return -1;
   return 0;
}
static void
rwa_redfin_linear_release(struct rwa_texture *texture)
{
   if(!texture->linear_original)return;
   char why[192]={0};
   if(rwa_redfin_linear_resolve(texture,why,sizeof(why))) {
      texture->device->command_scope.failed=true;
      fprintf(stderr,"REDFIN METAL LINEAR RELEASE: actual completion failed: %s\n",why);
   }
   struct rwa_texture **link=&texture->device->linear_textures;
   while(*link&&*link!=texture)link=&(*link)->linear_next;
   if(*link==texture)*link=texture->linear_next;
   pipe_resource_reference(&texture->linear_shadow_buffer,NULL);
   pipe_resource_reference(&texture->linear_original,NULL);
}
