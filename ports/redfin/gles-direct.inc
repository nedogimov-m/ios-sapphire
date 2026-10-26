/* SPDX-License-Identifier: MIT */
/* Included by OSMesa after its ordinary publication helper. Kernel attested
 * full images only. The GL import still independently enforces image layout. */
#ifdef __APPLE__
extern uint32_t redfin_freedreno_surface_producer(struct pipe_resource *,uint32_t);
extern int redfin_freedreno_publish_surfaces(struct pipe_fence_handle *,const struct rf_gu_target *,unsigned);
GLAPI uint32_t GLAPIENTRY redfin_gl_surface_producer(uint32_t);
GLAPI int GLAPIENTRY redfin_gl_publish_surfaces(const struct rf_gu_target *,unsigned);

GLAPI uint32_t GLAPIENTRY
redfin_gl_surface_producer(uint32_t surface)
{
   OSMesaContext osmesa=OSMesaGetCurrentContext();
   if(!surface || !osmesa || !osmesa->st || !osmesa->st->pipe)return 0;
   struct pipe_screen *screen=osmesa->st->pipe->screen;
   const char *name=screen->get_name(screen);
   if(!name || !strstr(name,"FD620"))return 0;
   struct gl_context *ctx=osmesa->st->ctx;
   struct gl_texture_object *texture=ctx->Texture.Unit[ctx->Texture.CurrentUnit].CurrentTex[TEXTURE_2D_INDEX];
   struct pipe_resource *resource=st_get_texobj_resource(texture);
   return resource ? redfin_freedreno_surface_producer(resource,surface) : 0;
}

GLAPI int GLAPIENTRY
redfin_gl_publish_surfaces(const struct rf_gu_target *targets,unsigned count)
{
   if(!targets || !count || count>RF_GU_MAX_TARGETS)return -1;
   OSMesaContext osmesa=OSMesaGetCurrentContext();
   if(!osmesa || !osmesa->st || !osmesa->st->pipe)return -1;
   struct pipe_context *pipe=osmesa->st->pipe;
   struct pipe_screen *screen=pipe->screen;
   const char *name=screen->get_name(screen);
   if(!name || !strstr(name,"FD620"))return -1;
   struct pipe_fence_handle *fence=NULL;
   pipe->flush(pipe,&fence,0); /* CPU worker drained; GPU completion not waited. */
   int result=fence ? redfin_freedreno_publish_surfaces(fence,targets,count) : -1;
   screen->fence_reference(screen,&fence,NULL);
   return result;
}
#endif
