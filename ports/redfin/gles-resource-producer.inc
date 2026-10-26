/* SPDX-License-Identifier: MIT */
/* The bound GL resource owns the BO reference throughout this query. Never
 * create/import a GEM handle outside freedreno's actual handle-table lock. */
#ifdef __APPLE__
extern uint32_t redwood_drm_surface_producer(int,uint32_t);
uint32_t redfin_freedreno_surface_producer(struct pipe_resource *,uint32_t);
uint32_t redfin_freedreno_surface_producer(struct pipe_resource *prsc,uint32_t surface)
{
   if(!prsc || !surface || prsc->target!=PIPE_TEXTURE_2D || prsc->last_level ||
      prsc->array_size!=1 || prsc->depth0!=1 || prsc->nr_samples>1 ||
      prsc->format!=PIPE_FORMAT_B8G8R8A8_UNORM)return 0;
   struct fd_resource *rsc=fd_resource(prsc);
   struct fd_bo *bo=rsc->bo;
   if(!bo || !__atomic_load_n(&bo->redfin_padding_ready,__ATOMIC_ACQUIRE) ||
      bo->redfin_surface!=surface)return 0;
   const struct rf_gp_view view={prsc->width0,prsc->height0,rsc->layout.pitch0,
      rsc->layout.slices[0].offset,4,1,1,prsc->nr_samples};
   uint64_t extent=rf_gp_full_image_extent(&bo->redfin_padding,&view,fd_bo_size(bo));
   if(!extent || rsc->layout.slices[0].size0!=extent)return 0;
   return redwood_drm_surface_producer(bo->dev->fd,bo->handle);
}
#endif
