/* SPDX-License-Identifier: MIT */
#include "metal-queued.h"
#include "metal-blit.h"
#include "metal-ordering.h"
static int redfin_resource_queued(uint64_t nonce)
{
   enum {page=4096,offset=64,length=512};
   char why[512]={0};struct rwa_device *device=rwa_device_open(why,sizeof(why));
   struct rwa_buffer *parent=NULL,*snapshots[2]={NULL};struct rwa_redfin_completion *tickets[2]={NULL};
   uint8_t *maps[2]={NULL};int valid=device!=NULL,submitted=0,epochs=0,drained=0;
   uint64_t before[REDFIN_METAL_ORDERING_WORDS]={0},middle[REDFIN_METAL_ORDERING_WORDS]={0},after[REDFIN_METAL_ORDERING_WORDS]={0};
   if(!valid)goto done;
   parent=rwa_buffer_create(device,page,why,sizeof(why));uint8_t *bytes=parent?rwa_buffer_map(parent):NULL;
   valid=bytes!=NULL;if(bytes)memset(bytes,0xa5,page);
   for(unsigned i=0;i<2;++i) {
      snapshots[i]=rwa_buffer_create(device,page,why,sizeof(why));maps[i]=snapshots[i]?rwa_buffer_map(snapshots[i]):NULL;
      valid=valid&&maps[i];if(maps[i])memset(maps[i],0xa5,page);
   }
   valid=valid&&!rwa_redfin_ordering_statistics(device,before,REDFIN_METAL_ORDERING_WORDS);
   for(unsigned i=0;valid&&i<2;++i) {
      if(rwa_commands_begin(device,why,sizeof(why))){valid=0;break;}
      struct redfin_metal_blit fill={.operation=RF_BLIT_FILL,.fill_value=(uint8_t)(nonce+i*73),.destination_offset=offset,.size={length,1,1}};
      struct redfin_metal_blit copy={.operation=RF_BLIT_BUFFER,.size={page,1,1}};
      int error=rwa_redfin_blit(device,NULL,parent,NULL,NULL,&fill,why,sizeof(why))||
         rwa_redfin_blit(device,parent,snapshots[i],NULL,NULL,&copy,why,sizeof(why));
      if(rwa_redfin_commands_submit(device,&tickets[i],why,sizeof(why)))error=1;
      valid=!error&&tickets[i];if(valid)++submitted;
   }
   if(valid) {
      valid=!rwa_redfin_completion_wait(tickets[0],why,sizeof(why))&&
         !rwa_redfin_completion_retire(tickets[0],why,sizeof(why))&&
         !rwa_redfin_ordering_statistics(device,middle,REDFIN_METAL_ORDERING_WORDS);
      /* Ticket one retires after command two wrote the same parent. CPU map
       * must still see that later write as pending and drain its real ticket. */
      bytes=rwa_buffer_map(parent);
      valid=valid&&bytes&&!rwa_redfin_ordering_statistics(device,after,REDFIN_METAL_ORDERING_WORDS);
      epochs=valid&&middle[1]==before[1]+1&&after[1]==before[1]+2;
      drained=valid&&after[2]==middle[2]+1;
      for(unsigned i=0;valid&&i<page;++i) {
         int in=i>=offset&&i<offset+length;
         valid=maps[0][i]==(in?(uint8_t)nonce:0xa5)&&maps[1][i]==(in?(uint8_t)(nonce+73):0xa5)&&
            bytes[i]==(in?(uint8_t)(nonce+73):0xa5);
      }
   }
done:
   /* Retire before freeing native resources even on a partially emitted error. */
   for(unsigned i=0;i<2;++i)if(tickets[i])(void)rwa_redfin_completion_retire(tickets[i],why,sizeof(why));
   for(unsigned i=0;i<2;++i)if(snapshots[i])rwa_buffer_destroy(snapshots[i]);
   if(parent)rwa_buffer_destroy(parent);
   if(device)rwa_device_close(device); /* screen/context survive owned tickets */
   for(unsigned i=0;i<2;++i)if(tickets[i])rwa_redfin_completion_destroy(tickets[i]);
   printf("REDFIN METAL QUEUED RESOURCE RESULT: boot=%016llx admitted-before-wait=%d old-retire-preserves-new-write=%d CPU-drains-prior-ticket=%d deferred-device-close=1 pixels-guards=%d passed=%d%s%s\n",
      (unsigned long long)nonce,submitted,epochs,drained,valid,valid&&epochs&&drained,valid?"":" reason=",valid?"":why);
   return valid&&epochs&&drained;
}
