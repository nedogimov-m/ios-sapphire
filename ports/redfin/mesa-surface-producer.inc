/* SPDX-License-Identifier: MIT */
/* Called through the same process-owned IOKit connection as GPU submission. */
static pthread_once_t redfin_surface_producer_once=PTHREAD_ONCE_INIT;
static bool redfin_surface_producer_ready;
static void redfin_surface_producer_init(void)
{
   struct {uint32_t pipe,param;uint64_t value;uint32_t len,pad;} request=
      {0x10,RF_GU_PARAM,0,0,0};
   redfin_surface_producer_ready=!call(0x40,&request,sizeof(request)) && request.value==RF_GU_ABI;
}
uint32_t redwood_drm_surface_producer(int fd,uint32_t handle)
{
   (void)fd;
   pthread_once(&redfin_surface_producer_once,redfin_surface_producer_init);
   return handle && redfin_surface_producer_ready ? handle : 0;
}
int redwood_drm_surface_announce(int fd,const struct rf_gu_target *target,uint32_t fence)
{
   (void)fd;
   if(!target || !target->handle || !target->surface || !fence)return -1;
   struct rf_gu_surface_producer request={target->handle,target->surface,fence,0};
   return call(RF_GU_ANNOUNCE,&request,sizeof(request));
}
