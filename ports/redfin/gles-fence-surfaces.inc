/* SPDX-License-Identifier: MIT */
/* Same real CPU-thread/kernel publication as Metal, followed by metadata-only
 * IOSurface announcements tied to that actual logical fence and live handle. */
#ifdef __APPLE__
int redfin_freedreno_publish_surfaces(struct pipe_fence_handle *,const struct rf_gu_target *,unsigned);
int redfin_freedreno_publish_surfaces(struct pipe_fence_handle *fence,
    const struct rf_gu_target *targets,unsigned count)
{
   if(!targets || !count || count>RF_GU_MAX_TARGETS)return -1;
   int result=redfin_freedreno_fence_publish(fence);
   if(result)return result;
   while(fence->last_fence)fence=fence->last_fence;
   if(!fence->fence || !fence->fence->kfence)return -1;
   for(unsigned i=0;i<count;++i)
      if(!targets[i].handle || !targets[i].surface ||
         redwood_drm_surface_announce(-1,&targets[i],fence->fence->kfence))
         return -1;
   return 0;
}
#endif
