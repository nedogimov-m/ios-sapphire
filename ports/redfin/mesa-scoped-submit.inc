/* SPDX-License-Identifier: MIT */
/* The native BO list retains complete backing allocations. Separately describe
 * the actual views tracked by Freedreno so CPU access to another heap view does
 * not wait for unrelated work. Direct native-BO use keeps its complete span. */
static void redfin_msm_merge_scoped(struct fd_submit_sp *target,const struct fd_submit_sp *source)
{
    for(unsigned i=0;i<source->nr_bos;++i) {
        if(fd_submit_redfin_direct(source,i))fd_submit_append_bo(target,source->bos[i]);
        else fd_submit_append_bo_backing(target,source->bos[i]);
    }
    for(unsigned i=0;i<source->nr_suballoc_bos;++i)
        fd_submit_append_bo(target,source->suballoc_bos[i]);
}
static int redfin_msm_submit_scoped(struct fd_submit_sp *submit,struct fd_pipe *pipe,
    struct drm_msm_gem_submit *request)
{
    if(submit->nr_bos>RF_GW_MAX_BOS ||
       submit->nr_suballoc_bos>RF_GW_MAX_RANGES-submit->nr_bos){errno=E2BIG;return -1;}
    unsigned capacity=submit->nr_bos+submit->nr_suballoc_bos,count=0;
    struct rf_gw_submit_range *ranges=(struct rf_gw_submit_range *)calloc(capacity,sizeof(*ranges));
    if(!ranges){errno=ENOMEM;return -1;}
    bool covered[RF_GW_MAX_BOS]={false};int result=-1;
    for(unsigned i=0;i<submit->nr_suballoc_bos;++i) {
        struct fd_bo *view=submit->suballoc_bos[i],*native=fd_bo_heap_block(view);
        unsigned index=fd_submit_append_bo_backing(submit,native);
        if(index>=request->nr_bos){errno=EINVAL;goto done;}
        if(fd_submit_redfin_direct(submit,index))continue;
        uint64_t address=fd_bo_get_iova(view),base=fd_bo_get_iova(native);
        if(address<base||address-base>native->size||view->size>native->size-(address-base)) {
            errno=EINVAL;goto done;
        }
        ranges[count++]=(struct rf_gw_submit_range){index,0,address-base,view->size};
        covered[index]=true;
    }
    for(unsigned i=0;i<submit->nr_bos;++i)
        if(fd_submit_redfin_direct(submit,i)||!covered[i])
            ranges[count++]=(struct rf_gw_submit_range){i,0,0,submit->bos[i]->size};
    result=redwood_drm_submit_scoped(pipe->dev->fd,request,sizeof(*request),ranges,count);
done:
    free(ranges);return result;
}
