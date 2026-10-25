/* SPDX-License-Identifier: MIT */
/* Included by the paired AIR frontend, after its native texture/surface types. */
static int
rwa_redfin_apply_raster(struct rwa_render *render,const struct rwa_draw *draw,
    unsigned width,unsigned height,char *why,size_t why_size)
{
   const struct redfin_metal_raster_state *s=draw->redfin_raster;
   if(!redfin_metal_raster_valid(s)) {say(why,why_size,"invalid native Metal raster state");return -1;}
   struct pipe_context *pipe=render->device->pipe;
   double x=0,y=0,w=width,h=height;
   double near=draw->depth_range?draw->depth_range[0]:0,far=draw->depth_range?draw->depth_range[1]:1;
   if(s&&(s->flags&1u)){x=s->viewport[0];y=s->viewport[1];w=s->viewport[2];h=s->viewport[3];near=s->viewport[4];far=s->viewport[5];}
   pipe->set_viewport_states(pipe,0,1,&(struct pipe_viewport_state){
      .scale={(float)(w/2),(float)(-h/2),(float)(far-near)},
      .translate={(float)(x+w/2),(float)(y+h/2),(float)near}});
   uint32_t clip[4];redfin_metal_scissor(s,width,height,clip);
   pipe->set_scissor_states(pipe,0,1,&(struct pipe_scissor_state){
      .minx=clip[0],.miny=clip[1],.maxx=clip[2],.maxy=clip[3]});
   struct pipe_blend_color blend={0};if(s)memcpy(blend.color,s->blend_color,sizeof(blend.color));
   pipe->set_blend_color(pipe,&blend);
   struct pipe_rasterizer_state state;memset(&state,0,sizeof(state));
   state.cull_face=s&&s->cull==1?PIPE_FACE_FRONT:s&&s->cull==2?PIPE_FACE_BACK:PIPE_FACE_NONE;
   state.front_ccw=s&&s->winding;state.half_pixel_center=1;state.bottom_edge_rule=1;
   state.depth_clip_near=state.depth_clip_far=!(s&&s->depth_clip);
   state.depth_clamp=s&&s->depth_clip;
   state.clip_halfz=1;state.multisample=render->shape.sample_count>1;state.scissor=1;
   state.line_width=state.point_size=1;
   state.fill_front=state.fill_back=s&&s->fill?PIPE_POLYGON_MODE_LINE:PIPE_POLYGON_MODE_FILL;
   if(s) {
      state.offset_units=s->depth_bias;state.offset_scale=s->slope_scale;state.offset_clamp=s->bias_clamp;
      state.offset_tri=s->depth_bias!=0||s->slope_scale!=0||s->bias_clamp!=0;
   }
   if(memcmp(&state,&render->redfin_raster_state,sizeof(state))) {
      void *next=pipe->create_rasterizer_state(pipe,&state);
      if(!next){say(why,why_size,"native Metal raster state allocation failed");return -1;}
      void *previous=render->rast;pipe->bind_rasterizer_state(pipe,next);
      render->rast=next;render->redfin_raster_state=state;
      if(previous)pipe->delete_rasterizer_state(pipe,previous);
   }
   return 0;
}

/* Load actions belong to the pass, before any draw, including an encoder that
 * has no draws. Each attachment has an independent clear colour and mask. */
int
rwa_redfin_clear_pass(struct rwa_device *device,struct rwa_texture *const *colors,
    unsigned count,unsigned mask,const float values[8][4],struct rwa_texture *depth,
    const float *depth_value,const unsigned *stencil_value,char *why,size_t why_size)
{
   if(!device||count>PIPE_MAX_COLOR_BUFS||(mask&~((1u<<count)-1))||
      (count&&!colors)||(mask&&!values))return -1;
   if(!mask&&!depth_value&&!stencil_value)return 0;
   if(redfin_metal_scope_prepare(&device->command_scope,true,command_scope_finish,device,why,why_size))return -1;
   struct pipe_context *pipe=device->pipe;
   struct pipe_surface *surfaces[PIPE_MAX_COLOR_BUFS]={0},*zs=NULL;
   struct pipe_framebuffer_state fb={.nr_cbufs=count};
   int result=-1;
   for(unsigned i=0;i<count+(depth?1u:0u);++i) {
      struct rwa_texture *t=i<count?colors[i]:depth;if(!t){if(mask&(1u<<i))goto done;continue;}
      if(t->device!=device||!attachment_shape_fits(t,MAX2(1,t->res->nr_samples),"clear attachment",why,why_size))goto done;
      if(!(t->res->bind&(i<count?PIPE_BIND_RENDER_TARGET:PIPE_BIND_DEPTH_STENCIL)))goto done;
      if(!fb.width){fb.width=t->shape.width;fb.height=MAX2(1,t->shape.height);fb.samples=MAX2(1,t->res->nr_samples);}
      else if(fb.width!=t->shape.width||fb.height!=MAX2(1,t->shape.height)||fb.samples!=MAX2(1,t->res->nr_samples))goto done;
      struct pipe_surface **target=i<count?&surfaces[i]:&zs;
      pipe_surface_reference(target,rwa_render_surface(t));if(!*target)goto done;
      if(i<count)fb.cbufs[i]=*target;else fb.zsbuf=*target;
   }
   if(!fb.width)goto done;
   if(depth_value&&(!depth||!format_has_depth(depth->res->format)))goto done;
   if(stencil_value&&(!depth||!format_has_stencil(depth->res->format)))goto done;
   pipe->set_framebuffer_state(pipe,&fb);
   for(unsigned i=0;i<count;++i)if(mask&(1u<<i)) {
      union pipe_color_union color;
      for(unsigned c=0;c<4;++c) {
         double value=values[i][c];if(!isfinite(value))goto done;
         if(util_format_is_pure_uint(colors[i]->res->format))
            color.ui[c]=value<=0?0:value>=UINT32_MAX?UINT32_MAX:(uint32_t)value;
         else if(util_format_is_pure_sint(colors[i]->res->format))
            color.i[c]=value<=INT32_MIN?INT32_MIN:value>=INT32_MAX?INT32_MAX:(int32_t)value;
         else color.f[c]=(float)value;
      }
      pipe->clear(pipe,PIPE_CLEAR_COLOR0<<i,NULL,&color,0,0);
   }
   if(depth_value||stencil_value) {
      unsigned clear=(depth_value?PIPE_CLEAR_DEPTH:0)|(stencil_value?PIPE_CLEAR_STENCIL:0);
      pipe->clear(pipe,clear,NULL,NULL,depth_value?*depth_value:0,stencil_value?*stencil_value:0);
   }
   result=redfin_metal_scope_complete(&device->command_scope,true,command_scope_finish,device,why,why_size);
done:
   if(!device->command_scope.active)pipe->set_framebuffer_state(pipe,&(struct pipe_framebuffer_state){0});
   for(unsigned i=0;i<count;++i)pipe_surface_reference(&surfaces[i],NULL);
   pipe_surface_reference(&zs,NULL);
   if(result&&why&&why_size&&!why[0])say(why,why_size,"invalid native Metal pass load action");
   return result;
}
