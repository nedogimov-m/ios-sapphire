/* SPDX-License-Identifier: MIT */
/* Included by Mesa's OSMesa frontend, after OSMesaGetCurrentContext. */
#ifdef __APPLE__
extern int redfin_freedreno_fence_publish(struct pipe_fence_handle *);
GLAPI int GLAPIENTRY redfin_gl_frame_publish(void);

GLAPI int GLAPIENTRY
redfin_gl_frame_publish(void)
{
   OSMesaContext osmesa = OSMesaGetCurrentContext();
   if (!osmesa || !osmesa->st || !osmesa->st->pipe)
      return -1;
   struct pipe_context *pipe = osmesa->st->pipe;
   struct pipe_screen *screen = pipe->screen;
   const char *name = screen->get_name(screen);
   if (!name || !strstr(name, "FD620"))
      return -1;

   /* Flags0 drains Gallium's CPU thread synchronously, without waiting for
    * GPU completion. A zero-time GL client wait can leave that thread busy.
    * Use the same real kernel-admission check as native Metal afterwards. */
   struct pipe_fence_handle *fence = NULL;
   pipe->flush(pipe, &fence, 0);
   int result = fence ? redfin_freedreno_fence_publish(fence) : -1;
   screen->fence_reference(screen, &fence, NULL);
   return result;
}
#endif
