/* SPDX-License-Identifier: MIT */
/* Generic unclassified BO references stay READ|WRITE. Resource-graph intent
 * belongs to each retained view and each batch, never to the reusable fd_bo.
 * Unknown intent wins when independently built submissions are merged. */
#define REDFIN_MSM_ACCESS_UNKNOWN 4u
static unsigned redfin_msm_wire_access(unsigned access)
{return access&REDFIN_MSM_ACCESS_UNKNOWN?0:access&RF_GA_RW;}
static void redfin_msm_merge_scoped(struct fd_submit_sp *target,const struct fd_submit_sp *source)
{
    for(unsigned i=0;i<target->nr_bos&&i<RF_GW_MAX_BOS;++i)
        if(fd_submit_redfin_direct(target,i)&&!target->redfin_bo_access[i])
            target->redfin_bo_access[i]=REDFIN_MSM_ACCESS_UNKNOWN;
    for(unsigned i=0;i<target->nr_suballoc_bos&&i<RF_GW_MAX_RANGES;++i)
        if(!target->redfin_view_access[i])target->redfin_view_access[i]=REDFIN_MSM_ACCESS_UNKNOWN;
    for(unsigned i=0;i<source->nr_bos;++i) {
        if(fd_submit_redfin_direct(source,i)) {
            unsigned access=i<RF_GW_MAX_BOS?source->redfin_bo_access[i]:0;
            fd_submit_redfin_resource_use(&target->base,source->bos[i],access?access:REDFIN_MSM_ACCESS_UNKNOWN);
        } else fd_submit_append_bo_backing(target,source->bos[i]);
    }
    for(unsigned i=0;i<source->nr_suballoc_bos;++i) {
        unsigned access=i<RF_GW_MAX_RANGES?source->redfin_view_access[i]:0;
        fd_submit_redfin_resource_use(&target->base,source->suballoc_bos[i],access?access:REDFIN_MSM_ACCESS_UNKNOWN);
    }
}
static int redfin_msm_submit_scoped(struct fd_submit_sp *submit,struct fd_pipe *pipe,
    struct drm_msm_gem_submit *request)
{
    if(submit->nr_bos>RF_GW_MAX_BOS ||
       submit->nr_suballoc_bos>RF_GW_MAX_RANGES-submit->nr_bos){errno=E2BIG;return -1;}
    unsigned capacity=submit->nr_bos+submit->nr_suballoc_bos,count=0;
    struct rf_gw_submit_range *ranges=(struct rf_gw_submit_range *)calloc(capacity,sizeof(*ranges));
    if(!ranges){errno=ENOMEM;return -1;}
    bool covered[RF_GW_MAX_BOS]={false};uint8_t whole_access[RF_GW_MAX_BOS]={0};int result=-1;
    for(unsigned i=0;i<submit->nr_bos;++i)
        whole_access[i]=(uint8_t)(fd_submit_redfin_direct(submit,i)&&!submit->redfin_bo_access[i]?
            REDFIN_MSM_ACCESS_UNKNOWN:submit->redfin_bo_access[i]);
    for(unsigned i=0;i<submit->nr_suballoc_bos;++i) {
        struct fd_bo *view=submit->suballoc_bos[i],*native=fd_bo_heap_block(view);
        unsigned index=fd_submit_append_bo_backing(submit,native);
        if(index>=request->nr_bos){errno=EINVAL;goto done;}
        if(fd_submit_redfin_direct(submit,index)) {
            unsigned access=submit->redfin_view_access[i];
            whole_access[index]|=(uint8_t)(access?access:REDFIN_MSM_ACCESS_UNKNOWN);
            continue;
        }
        uint64_t address=fd_bo_get_iova(view),base=fd_bo_get_iova(native);
        if(address<base||address-base>native->size||view->size>native->size-(address-base)) {
            errno=EINVAL;goto done;
        }
        unsigned access=redfin_msm_wire_access(submit->redfin_view_access[i]);
        ranges[count++]=(struct rf_gw_submit_range){index,access,address-base,view->size};
        covered[index]=true;
    }
    for(unsigned i=0;i<submit->nr_bos;++i)
        if(fd_submit_redfin_direct(submit,i)||!covered[i])
            ranges[count++]=(struct rf_gw_submit_range){i,redfin_msm_wire_access(whole_access[i]),0,submit->bos[i]->size};
    result=redwood_drm_submit_access(pipe->dev->fd,request,sizeof(*request),ranges,count);
done:
    free(ranges);return result;
}
