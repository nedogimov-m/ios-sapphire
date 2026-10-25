/* SPDX-License-Identifier: MIT */
/* The original IOSurface is a bounded raw GPU buffer, never an unaligned
 * sampler/render target. Native NIR copies its rows to/from a real aligned
 * linear texture. Alias transitions pay the actual GPU fence and barriers. */
extern struct pipe_resource *redfin_freedreno_import_buffer(struct pipe_screen *,unsigned);
extern struct pipe_resource *redfin_freedreno_buffer_alias(struct pipe_screen *,
    struct pipe_resource *,unsigned *,unsigned *);

static void *
rwa_redfin_copy_shader(struct rwa_device *device,char *why,size_t why_size)
{
   if(device->linear_copy_cso)return device->linear_copy_cso;
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
   nir_def *column=nir_ishl_imm(&b,x,2);
   nir_def *source=nir_iadd(&b,parameters[4],nir_iadd(&b,nir_imul(&b,y,parameters[2]),column));
   nir_def *destination=nir_iadd(&b,parameters[5],nir_iadd(&b,nir_imul(&b,y,parameters[3]),column));
   nir_def *word=nir_load_ssbo(&b,1,32,nir_imm_int(&b,0),source,
      .align_mul=4,.align_offset=0,.access=ACCESS_NON_WRITEABLE);
   nir_store_ssbo(&b,word,nir_imm_int(&b,1),destination,
      .align_mul=4,.align_offset=0,.write_mask=1,.access=ACCESS_NON_READABLE);
   nir_pop_if(&b,NULL);
   nir_shader_gather_info(b.shader,nir_shader_get_entrypoint(b.shader));
   finalize_for_gallium(b.shader,device->screen);
   device->linear_copy_cso=device->pipe->create_compute_state(device->pipe,
      &(struct pipe_compute_state){.ir_type=PIPE_SHADER_IR_NIR,.prog=b.shader});
   if(!device->linear_copy_cso)say(why,why_size,"native GPU row-copy shader creation failed");
   return device->linear_copy_cso;
}

static int
rwa_redfin_copy_rows(struct rwa_texture *texture,bool output,char *why,size_t why_size)
{
   struct rwa_device *device=texture->device;struct pipe_context *pipe=device->pipe;
   struct pipe_resource *source=output?texture->linear_shadow_buffer:texture->linear_original;
   struct pipe_resource *destination=output?texture->linear_original:texture->linear_shadow_buffer;
   struct redfin_linear_copy_plan plan;
   unsigned cpp=util_format_get_blocksize(texture->res->format);
   if(!redfin_linear_copy_plan_make(&plan,texture->res->width0*cpp,texture->res->height0,
      output?texture->linear_shadow_pitch:texture->linear_pitch,
      output?texture->linear_pitch:texture->linear_shadow_pitch,
      output?texture->linear_shadow_offset:texture->linear_offset,
      output?texture->linear_offset:texture->linear_shadow_offset,
      source->width0,destination->width0)) {
      say(why,why_size,"native IOSurface row conversion escapes its actual buffers");return -1;
   }
   void *shader=rwa_redfin_copy_shader(device,why,why_size);if(!shader)return -1;
   if(redfin_metal_scope_prepare(&device->command_scope,false,command_scope_finish,device,why,why_size))return -1;
   if(pipe->memory_barrier)pipe->memory_barrier(pipe,PIPE_BARRIER_ALL);
   const struct pipe_shader_buffer buffers[2]={
      {.buffer=source,.buffer_size=source->width0},
      {.buffer=destination,.buffer_size=destination->width0}};
   struct pipe_constant_buffer constants={.user_buffer=&plan,.buffer_size=sizeof(plan)};
   pipe->bind_compute_state(pipe,shader);
   pipe->set_constant_buffer(pipe,PIPE_SHADER_COMPUTE,0,false,&constants);
   pipe->set_shader_buffers(pipe,PIPE_SHADER_COMPUTE,0,2,buffers,2);
   const struct pipe_grid_info grid={.work_dim=2,.block={64,1,1},
      .grid={(plan.words+63)/64,plan.rows,1}};
   pipe->launch_grid(pipe,&grid);
   int result=redfin_metal_scope_complete(&device->command_scope,false,command_scope_finish,device,why,why_size);
   if(!result) {
      if(pipe->memory_barrier)pipe->memory_barrier(pipe,PIPE_BARRIER_ALL);
      if(redfin_freedreno_alias_written(pipe,output?texture->linear_original:texture->res)) {
         device->command_scope.failed=true;say(why,why_size,"native GPU alias transition refused");result=-1;
      }
   }
   pipe->set_shader_buffers(pipe,PIPE_SHADER_COMPUTE,0,2,NULL,0);
   pipe->set_constant_buffer(pipe,PIPE_SHADER_COMPUTE,0,false,NULL);
   pipe->bind_compute_state(pipe,NULL);
   if(!result) {
      unsigned direction=output?1:0;
      uint64_t count=++device->linear_copies[direction];
      if(count<=4)fprintf(stderr,"REDFIN METAL LINEAR COPY: direction=%s width=%u height=%u pitch=%u aligned-pitch=%u actual-GPU-finish=1 CPU-pixel-copy=0\n",
         output?"resolve":"import",texture->res->width0,texture->res->height0,
         texture->linear_pitch,texture->linear_shadow_pitch);
   }
   return result;
}

static int
rwa_redfin_linear_import(struct rwa_texture *texture,const struct pipe_resource *templ,
    unsigned surface,unsigned offset,unsigned pitch,char *why,size_t why_size)
{
   struct rwa_device *device=texture->device;
   unsigned cpp=util_format_get_blocksize(templ->format);
   texture->linear_original=redfin_freedreno_import_buffer(device->screen,surface);
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
rwa_redfin_linear_prepare(struct rwa_texture *texture,char *why,size_t why_size)
{
   if(!texture||!texture->linear_original)return 0;
   struct rwa_device *device=texture->device;
   /* A draw later in the same command reads the actual earlier shadow writes.
    * Resolve to the original only after the command's real rendering fence. */
   if(texture->linear_dirty)return 0;
   for(struct rwa_texture *other=device->linear_textures;other;other=other->linear_next)
      if(other!=texture&&other->linear_surface==texture->linear_surface&&other->linear_dirty)
         if(rwa_redfin_linear_resolve(other,why,why_size))return -1;
   if(device->command_scope.active&&texture->linear_epoch==device->linear_epoch)return 0;
   int result=rwa_redfin_copy_rows(texture,false,why,why_size);
   if(!result)texture->linear_epoch=device->linear_epoch;
   return result;
}
static void
rwa_redfin_linear_written(struct rwa_texture *texture)
{
   if(!texture||!texture->linear_original)return;
   texture->linear_dirty=true;
   for(struct rwa_texture *other=texture->device->linear_textures;other;other=other->linear_next)
      if(other!=texture&&other->linear_surface==texture->linear_surface)other->linear_epoch=0;
}
static int
rwa_redfin_linear_resolve(struct rwa_texture *texture,char *why,size_t why_size)
{
   if(!texture||!texture->linear_dirty)return 0;
   int result=rwa_redfin_copy_rows(texture,true,why,why_size);
   if(!result)texture->linear_dirty=false;
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
