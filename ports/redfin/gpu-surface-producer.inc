/* SPDX-License-Identifier: MIT */
/* Caller holds the existing client lock and has reused GemInfo's full owned
 * image attestation. No queue/hardware/CPU-memory barrier is skipped by a
 * consumer: normal IOSurfaceLock/WaitFence and display FIFO are unchanged. */
static IOReturn gpuSurfaceAnnounce(gpu_buffer *b,const rf_gq_client *q,
    const rf_gu_surface_producer *r)
{
    if(!b || !q || !r || !r->handle || !r->surface || !r->fence || r->reserved ||
       !b->surface || b->surface->id!=r->surface || !b->fence ||
       b->fence>r->fence || r->fence>q->issued || b->producerFence>r->fence)
        return kIOReturnBadArgument;
    if(q->closing || q->failed)return kIOReturnNotReady;
    if(!b->surface->state || b->surface->state->getLength()<RF_GU_SEED_OFFSET+sizeof(uint32_t))
        return kIOReturnUnsupported;
    if(b->producerFence==r->fence)return kIOReturnSuccess;
    uint8_t *state=(uint8_t *)b->surface->state->getBytesNoCopy();
    if(!state)return kIOReturnUnsupported;
    volatile SInt32 *seed=(volatile SInt32 *)(state+RF_GU_SEED_OFFSET);
    /* Exactly the primitive used by IOSurfaceRootUserClient::trapUnlock.
     * Announced pixels may still be in flight. Do not mutate q or b->pending. */
    uint32_t value=(uint32_t)OSIncrementAtomic(seed)+1u;
    b->producerFence=r->fence;
    static uint64_t notices;
    uint64_t sample=__atomic_add_fetch(&notices,1,__ATOMIC_RELAXED);
    if(sample<=4 || !(sample%120))
        IOLog("REDFIN GPU SURFACE PRODUCER: n=%llu surface=%u cf=%u issued=%u seed=%u seed-only=1 completion=0\n",
            sample,r->surface,r->fence,q->issued,value);
    return kIOReturnSuccess;
}
