/* SPDX-License-Identifier: MIT */
struct rwa_buffer *
rwa_redfin_buffer_from_surface(struct rwa_device *device,unsigned surface,size_t length,void *original,
    char *why,size_t bytes)
{
   uint32_t extent=0;
   if(!device||device->software||!surface||!original||!redfin_buffer_extent(length,&extent)||
      (uintptr_t)original>UINTPTR_MAX-length) {
      say(why,bytes,"invalid native external Metal buffer");return NULL;
   }
#ifdef GALLIUM_FREEDRENO
   struct redwood_drm_surface info={.surface=surface};
   int surface_result=redwood_drm_surface(-1,&info);
   if(surface_result||info.offset||info.size<extent||info.size>UINT32_MAX) {
      say(why,bytes,"external Metal buffer needs actual zero-offset native pages (lookup=%d offset=%llu span=%llu need=%llu)",
          surface_result,(unsigned long long)info.offset,(unsigned long long)info.size,(unsigned long long)extent);return NULL;
   }
   struct rwa_buffer *buffer=calloc(1,sizeof(*buffer));
   if(!buffer){say(why,bytes,"external Metal buffer metadata allocation failed");return NULL;}
   buffer->res=redfin_freedreno_import_buffer(device->screen,surface);
   if(!buffer->res||buffer->res->width0<extent) {
      pipe_resource_reference(&buffer->res,NULL);free(buffer);
      say(why,bytes,"native GPU import did not retain the original external pages");return NULL;
   }
   buffer->device=device;buffer->size=length;buffer->map=original;buffer->external_surface=surface;
   fprintf(stderr,"REDFIN METAL EXTERNAL BUFFER: bytes=%zu original-pages=1 actual-kernel-import=1 CPU-pixel-copy=0\n",length);
   return buffer;
#else
   say(why,bytes,"external Metal buffers require the native A620 driver");return NULL;
#endif
}
