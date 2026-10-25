/* SPDX-License-Identifier: MIT
 * Encoding and retirement run under the frontend gate. A ticket's immutable,
 * fully published fence can be waited on from any thread. Its mutex shares
 * the one actual wait result with CPU consumers and other waiters.
 */
struct rwa_redfin_completion {
   struct rwa_redfin_completion *next;
   struct rwa_device *device;
   struct pipe_fence_handle *fence;
   pthread_mutex_t mutex;
   uint64_t epoch;
   bool waited,retired;
   int error;
};

int rwa_redfin_completion_wait(struct rwa_redfin_completion *ticket,char *why,size_t bytes)
{
   if(!ticket){say(why,bytes,"missing Metal completion ticket");return -1;}
   pthread_mutex_lock(&ticket->mutex);
   if(!ticket->waited) {
      bool done=!ticket->fence||ticket->device->screen->fence_finish(
         ticket->device->screen,NULL,ticket->fence,RWA_FENCE_TIMEOUT_NS);
      ticket->error=done?0:-1;ticket->waited=true;
      if(!done)__atomic_store_n(&ticket->device->queued_failed,true,__ATOMIC_RELEASE);
   }
   int error=ticket->error;
   pthread_mutex_unlock(&ticket->mutex);
   if(error)say(why,bytes,"Metal GPU completion failed; native context is retired");
   return error;
}

int rwa_redfin_completion_retire(struct rwa_redfin_completion *ticket,char *why,size_t bytes)
{
   if(!ticket)return -1;
   int error=rwa_redfin_completion_wait(ticket,why,bytes);
   struct rwa_device *device=ticket->device;
   if(!ticket->retired) {
      if(!error)rwa_redfin_ordering_completed_epoch(device,ticket->epoch);
      else {device->command_scope.failed=true;device->command_scope.completion_failed=true;}
      struct rwa_redfin_completion **at=&device->queued_tickets;
      while(*at&&*at!=ticket)at=&(*at)->next;
      if(*at==ticket)*at=ticket->next;
      ticket->next=NULL;ticket->retired=true;
   }
   /* A later command that really retired after a failed predecessor cannot
    * advertise success just because its own fence happened to signal. */
   if(__atomic_load_n(&device->queued_failed,__ATOMIC_ACQUIRE))error=-1;
   if(error&&why&&bytes&&!why[0])say(why,bytes,"Metal predecessor GPU completion failed");
   return error;
}

void rwa_redfin_completion_destroy(struct rwa_redfin_completion *ticket)
{
   if(!ticket)return;
   struct rwa_device *device=ticket->device;
   char why[128]={0};(void)rwa_redfin_completion_retire(ticket,why,sizeof(why));
   if(ticket->fence)device->screen->fence_reference(device->screen,&ticket->fence,NULL);
   pthread_mutex_destroy(&ticket->mutex);free(ticket);
   if(device->queued_owners)--device->queued_owners;
   if(device->queued_closing&&!device->queued_owners)rwa_redfin_device_destroy(device);
}

static int rwa_redfin_queued_drain(struct rwa_device *device,char *why,size_t bytes)
{
   /* The frontend gate holds this list stable. Waiting never needs the gate
    * itself, so a simultaneous off-thread completion cannot deadlock here. */
   while(device->queued_tickets) {
      if(rwa_redfin_completion_retire(device->queued_tickets,why,bytes))return -1;
   }
   return __atomic_load_n(&device->queued_failed,__ATOMIC_ACQUIRE)?-1:0;
}

int rwa_redfin_commands_submit(struct rwa_device *device,struct rwa_redfin_completion **out,
   char *why,size_t bytes)
{
   if(out)*out=NULL;
   if(!device||!out||!device->command_scope.active) {
      say(why,bytes,"Metal command scope is not active");return -1;
   }
   struct rwa_redfin_completion *ticket=calloc(1,sizeof(*ticket));
   if(!ticket||pthread_mutex_init(&ticket->mutex,NULL)) {
      free(ticket);
      /* Already emitted work must still pay its real drain on allocation
       * failure. The caller receives no fake ticket or completion. */
      int drained=rwa_commands_end(device,why,bytes);
      if(!drained)say(why,bytes,"out of memory retaining Metal completion");
      return -1;
   }
   ticket->device=device;ticket->epoch=device->encoding_epoch;
   rwa_redfin_bindings_clear(device);
   int error=0;
   if(!device->command_scope.failed) {
      device->pipe->set_framebuffer_state(device->pipe,&(struct pipe_framebuffer_state){0});
      if(rwa_redfin_linear_resolve_all(device,why,bytes))error=-1;
   } else error=-1;
   /* Opt-in image capture reads real pixels under this gate. Keep its heavy
    * diagnostic drain, without imposing that wait on ordinary composition. */
   if(rwa_redfin_trace_selected()&&rwa_redfin_cpu_drain(device,why,bytes))error=-1;
   bool required=device->command_scope.pending||device->queued_tickets;
   device->pipe->flush(device->pipe,&ticket->fence,0);
   int published=rwa_redfin_fence_publish(device,ticket->fence);
   if(published>0&&!required)device->screen->fence_reference(device->screen,&ticket->fence,NULL);
   if((required&&(!ticket->fence||published))||published<0) {
      say(why,bytes,"Metal GPU fence could not be published; context is retired");
      __atomic_store_n(&device->queued_failed,true,__ATOMIC_RELEASE);
      ticket->waited=true;ticket->error=-1;error=-1;
   }
   device->command_scope.active=false;device->command_scope.pending=false;
   device->encoding_epoch=0;
   ++device->queued_owners;
   struct rwa_redfin_completion **at=&device->queued_tickets;
   while(*at)at=&(*at)->next;
   *at=ticket;*out=ticket;
   rwa_redfin_bindings_clear(device);
   if(!error)rwa_redfin_trace_end(device);
   return error;
}

void rwa_device_close(struct rwa_device *device)
{
   if(!device)return;
   device->queued_closing=true;
   if(!device->queued_owners)rwa_redfin_device_destroy(device);
}
