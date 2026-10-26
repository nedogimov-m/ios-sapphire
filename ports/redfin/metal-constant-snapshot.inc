/* SPDX-License-Identifier: MIT
 * Large misaligned constants are immutable, queue-ordered GPU snapshots.
 * Small/unsupported copies retain the real CPU preparation/uploader path.
 * This only changes runtime storage; no AIR/NIR or shader cache is modified.
 */
static bool
rwa_redfin_constant_gpu_supported(struct rwa_device *device,size_t offset,size_t bytes)
{
   if(device->software||!device->command_scope.active||bytes<REDFIN_METAL_GPU_SNAPSHOT_MIN||
      bytes>REDFIN_METAL_GPU_SNAPSHOT_CHUNK||offset>UINT32_MAX||bytes>UINT32_MAX-offset)
      return false;
   struct redfin_metal_constant_arena *arena=&device->constant_arena;
   if(!arena->queried) {
      arena->queried=true;
      uint64_t grid[3]={0},block[3]={0};
      struct pipe_screen *screen=device->screen;
      arena->supported=screen->get_compute_param&&
         screen->get_compute_param(screen,PIPE_SHADER_IR_NIR,PIPE_COMPUTE_CAP_MAX_GRID_SIZE,grid)==sizeof(grid)&&
         screen->get_compute_param(screen,PIPE_SHADER_IR_NIR,PIPE_COMPUTE_CAP_MAX_BLOCK_SIZE,block)==sizeof(block)&&
         grid[0]&&grid[1]&&grid[2]&&block[0]>=64&&block[1]&&block[2];
      arena->grid_x=grid[0];
   }
   /* The existing exact row helper selects a dword grid only when every
    * address and length is aligned. A byte grid must fit independently. */
   uint64_t units=((offset|bytes)&3)?bytes:bytes/4;
   return arena->supported&&(units+63)/64<=arena->grid_x;
}

/* 1: unsupported/allocation refused before emitting work, use CPU fallback.
 * 0: owns an immutable constant reference. -1: actual preparation/copy failed;
 * the caller must drain/retire already emitted work through its normal path. */
static int
rwa_redfin_constant_gpu_snapshot(struct rwa_device *device,struct rwa_buffer *source,
   size_t offset,size_t bytes,struct pipe_constant_buffer *out,char *why,size_t why_size)
{
   if(!rwa_redfin_constant_gpu_supported(device,offset,bytes))return 1;
   unsigned alignment=MAX2(64,device->ubo_offset_align);
   if((alignment&(alignment-1))||alignment>REDFIN_METAL_GPU_SNAPSHOT_CHUNK)return 1;
   struct redfin_metal_constant_arena *arena=&device->constant_arena;
   uint64_t at=((uint64_t)arena->offset+alignment-1)&~((uint64_t)alignment-1);
   if(!arena->resource||at>arena->resource->width0||bytes>arena->resource->width0-at) {
      /* No CPU mapping or write. Replacing the owner's reference cannot free
       * a chunk retained by a prior draw, dispatch or not-yet-retired batch. */
      struct pipe_resource shape={.target=PIPE_BUFFER,.format=PIPE_FORMAT_R8_UNORM,
         .bind=PIPE_BIND_CONSTANT_BUFFER|PIPE_BIND_SHADER_BUFFER,.usage=PIPE_USAGE_DEFAULT,
         .width0=REDFIN_METAL_GPU_SNAPSHOT_CHUNK,.height0=1,.depth0=1,.array_size=1};
      struct pipe_resource *next=device->screen->resource_create(device->screen,&shape);
      if(!next)return 1;
      pipe_resource_reference(&arena->resource,NULL);arena->resource=next;
      arena->offset=0;at=0;++device->frontend_stats[RF_MFP_CONSTANT_GPU_CHUNKS];
   }
   struct pipe_constant_buffer snapshot={.buffer_offset=(unsigned)at,.buffer_size=(unsigned)bytes};
   pipe_resource_reference(&snapshot.buffer,arena->resource);
   /* Reserve before encoding: a failure never makes an emitted slice reusable. */
   arena->offset=(unsigned)(at+bytes);
   uint64_t began=rwa_redfin_profile_clock();
   int error=rwa_redfin_buffer_prepare(source,why,why_size);
   rwa_redfin_profile_elapsed(device,RF_MFP_CONSTANT_PREPARE_NS,began);
   if(!error) {
      began=rwa_redfin_profile_clock();
      error=rwa_blit_rows(device,source->res,snapshot.buffer,offset,at,bytes,bytes,bytes,1,why,why_size);
      rwa_redfin_profile_elapsed(device,RF_MFP_CONSTANT_UPLOAD_NS,began);
   }
   if(error){pipe_resource_reference(&snapshot.buffer,NULL);return -1;}
   ++device->frontend_stats[RF_MFP_CONSTANT_GPU];
   device->frontend_stats[RF_MFP_CONSTANT_GPU_BYTES]+=bytes;
   *out=snapshot;return 0;
}
