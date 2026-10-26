/* SPDX-License-Identifier: MIT
 * The hardware mutex and current-thread lease cover every call. Publication
 * does not retire a client or release memory. All CPU-visible success still
 * requires the actual ordered cache-flush fence and complete native audit.
 */
static int gr_physical_collect(uint32_t observed)
{
    if(observed<gr.completed||observed>gr.fence)return EPROTO;
    for(uint32_t fence=gr.completed;fence<observed;) {
        ++fence;
        struct rf_gi_publication *slot=&gr.physical[fence%RF_GI_SLOTS];
        if(slot->fence!=fence)return EPROTO;
        unsigned offset=rf_gi_time_offset(fence);
        uint64_t start=(uint64_t)gm_scalar_read(gx.scratch+offset+4)<<32|
            gm_scalar_read(gx.scratch+offset);
        uint64_t end=(uint64_t)gm_scalar_read(gx.scratch+offset+12)<<32|
            gm_scalar_read(gx.scratch+offset+8);
        if(end<start)return EPROTO;
        gr.gpu_ticks+=end-start;slot->fence=0;gr.completed=fence;
    }
    return 0;
}
static int gr_physical_wait(uint32_t fence,bool idle)
{
    if(fence>gr.fence)return EINVAL;
    if(!idle&&fence<=gr.completed)return gr_live();
    uint64_t first=gm_time_ns(gx.context);
    struct gr_wait_sample observed={fence,0,0,0,idle};unsigned polls=0;
    const struct rf_gr_wait_ops ops={&observed,gr_wait_sample,gm_time_ns,gr_wait_pause};
    int error=rf_gr_wait(&ops,RF_A6_WAIT_NS,&polls);gr.polls+=polls;
    gr.wait_ns+=gm_time_ns(gx.context)-first;
    if(!error) {
        uint64_t audit_at=gm_time_ns(gx.context);error=gr_audit(false);
        gr.audit_ns+=gm_time_ns(gx.context)-audit_at;
        if(!error)error=gr_physical_collect(observed.done);
    }
    if(!error) {
        if(fence&&gr.completed&&(fence<=8||!(fence%256)))
            printf("REDFIN GPU PHYSICAL DONE: fence=%u observed=%u issued=%u idle=%u polls=%u real-audit=1\n",
                fence,observed.done,gr.fence,idle,polls);
        return 0;
    }
    printf("REDFIN GPU WAIT FAILED: wanted=%u observed=%u prior=%u rptr=%#x wptr=%#x status=%#x error=%d polls=%u elapsed-us=%llu\n",
        fence,observed.done,gr.completed,observed.rptr,gx.wptr,observed.status,error,polls,
        (unsigned long long)((gm_time_ns(gx.context)-first)/1000));
    gx_diagnostic(gx.context);redfin_gpu_poison("physical FIFO did not complete");
    return error;
}
int redfin_gpu_wait(uint32_t fence)
{return gr_physical_wait(fence,false);}
/* Nonblocking hardware observation only. It never grants client completion;
 * finish/wait must still perform the complete native audit and timestamps. */
int redfin_gpu_poll(uint32_t fence)
{
    if(!fence||fence>gr.fence)return EINVAL;
    if(fence<=gr.completed)return gr_live();
    struct gr_wait_sample observed={fence,0,0,0,false};bool done=false;
    int error=gr_wait_sample(&observed,&done);
    if(!error&&done)return 0;
    struct rf_gi_publication *slot=&gr.physical[fence%RF_GI_SLOTS];
    uint64_t now=gm_time_ns(gx.context);
    if(!error&&(slot->fence!=fence||now<slot->published_ns))error=EPROTO;
    if(!error&&now-slot->published_ns>=RF_A6_WAIT_NS)error=ETIMEDOUT;
    if(!error)return EAGAIN;
    gx_diagnostic(gx.context);redfin_gpu_poison("physical poll lost fence/ownership/deadline");
    return error;
}
int redfin_gpu_quiesce(void)
{
    int error=gr_live();if(error)return error;
    /* Once all published fences have been audited and no new publication
     * exists, a guarded actual idle observation needs no duplicate audit. */
    uint32_t rptr=gm_scalar_read(gx.gpu+4*0x806),status=gm_scalar_read(gx.gpu+4*0x210);
    if(gm_scalar_read(gx.gpu+4*0x821)||(gm_scalar_read(gx.gpu+4*0x823)&0xf7u)) {
        redfin_gpu_poison("physical idle observation has an actual GPU fault");return EIO;
    }
    if(gr.completed==gr.fence&&rptr==gx.wptr&&!(status&~1u))return gr_live();
    return gr_physical_wait(gr.fence,true);
}
int redfin_gpu_publish(const uint64_t *addresses,const uint32_t *words,unsigned count,uint32_t *fence)
{
    if(!fence||gr.fence==UINT32_MAX)return EINVAL;
    *fence=0;
    int error=gr_live();if(error)return error;
    if(!rf_gi_can_publish(gr.fence,gr.completed)) {
        error=redfin_gpu_wait(gr.completed+1);if(error)return error;
    }
    uint32_t next=gr.fence+1,packets[RF_GR_PACKET_WORDS];
    struct rf_gi_publication *slot=&gr.physical[next%RF_GI_SLOTS];
    if(slot->fence){redfin_gpu_poison("physical timestamp slot still owned");return EBUSY;}
    unsigned n=rf_gi_submit_words(&gr.arena,addresses,words,count,next,packets,RF_GR_PACKET_WORDS);
    if(!n)return EINVAL;
    uint64_t audit_at=gm_time_ns(gx.context);
    error=gr_audit(false);if(error)return error;
    gr.audit_ns+=gm_time_ns(gx.context)-audit_at;
    error=redfin_gpu_mapped();if(error)return error;
    error=gr_dvfs(true);
    if(error==EBUSY) {
        error=redfin_gpu_quiesce();if(!error)error=gr_dvfs(true);
    }
    if(error)return error;
    uint32_t ring_words=RF_A6_RING_BYTES/4;
    uint32_t rptr=gm_scalar_read(gx.gpu+4*0x806);
    if(!rf_gi_ring_room(rptr,gx.wptr,ring_words,n)) {
        error=redfin_gpu_quiesce();if(error)return error;
        rptr=gm_scalar_read(gx.gpu+4*0x806);
        if(!rf_gi_ring_room(rptr,gx.wptr,ring_words,n)) {
            redfin_gpu_poison("physical ring room unavailable after real idle");return EBUSY;
        }
    }
    uint32_t actual_before=gm_scalar_read(gx.scratch+RF_GR_FENCE_AT);bool ignored=false;
    error=rf_gi_counter(gr.fence,gr.completed,actual_before,gr.completed,&ignored);
    if(error){redfin_gpu_poison("physical fence counter changed");return error;}
    uint64_t publish_at=gm_time_ns(gx.context);uint32_t *ring=gx.data[0].host;
    for(unsigned i=0;i<n;++i)ring[(gx.wptr+i)%ring_words]=packets[i];
    unsigned first_words=n<ring_words-gx.wptr?n:ring_words-gx.wptr;
    redfin_gpu_sync(ring+gx.wptr,4*first_words,false);
    if(first_words<n)redfin_gpu_sync(ring,4*(n-first_words),false);
    if(gr_live())return ECANCELED;
    *slot=(struct rf_gi_publication){next,count,publish_at};
    gr.fence=next;gx.wptr=(gx.wptr+n)%ring_words;
    gm_memory_store(gx.gpu+4*0x807,gx.wptr);*fence=next;
    gr.publish_ns+=gm_time_ns(gx.context)-publish_at;
    bool overlap=actual_before+1<next;
    if(overlap)++gr.physical_overlap;
    unsigned pending=next-actual_before;
    if(pending>gr.physical_max_pending)gr.physical_max_pending=pending;
    if(next<=8||!(next%256)||(overlap&&gr.physical_overlap<=4))
        printf("REDFIN GPU PHYSICAL PUB: fence=%u IBs=%u prior-done=%u pending=%u overlap=%llu max-pending=%u ring=%u/%u owned-slots=1\n",
            next,count,actual_before,pending,gr.physical_overlap,gr.physical_max_pending,rptr,gx.wptr);
    return 0;
}
/* Kernel display commands/stage storage remain synchronous and may be reused
 * only after the exact prior/current hardware work has really become idle. */
int redfin_gpu_submit(const uint64_t *addresses,const uint32_t *words,unsigned count,uint32_t *fence)
{
    if(!fence)return EINVAL;
    int error=redfin_gpu_quiesce();if(error)return error;
    uint32_t published=0;error=redfin_gpu_publish(addresses,words,count,&published);
    if(!error)error=redfin_gpu_quiesce();
    if(!error)*fence=published;return error;
}
