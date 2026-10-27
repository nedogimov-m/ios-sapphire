/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GPU_QUEUE_H
#define REDFIN_GPU_QUEUE_H
#include <stdbool.h>
#include <stdint.h>
#include <sys/errno.h>
#define RF_GQ_ABI 1u
#define RF_GQ_PARAM 0x52465131u
#define RF_GQ_MAX_JOBS 16u
#define RF_GQ_MAX_BYTES (4u<<20)
#define RF_GQ_WAIT_NS UINT64_C(2000000000)
#define RF_GQ_COLD_OUTPUT_NS UINT64_C(10000000000)
struct rf_gq_budget {uint32_t jobs;uint64_t bytes;};
struct rf_gq_client {uint32_t issued,retired,completed,failed,pending;int first_error;bool closing;};
static inline int rf_gq_reserve(struct rf_gq_budget *b,uint64_t bytes)
{
    if(!b||!bytes||bytes>RF_GQ_MAX_BYTES)return EINVAL;
    if(b->jobs>=RF_GQ_MAX_JOBS||b->bytes>RF_GQ_MAX_BYTES-bytes)return EAGAIN;
    ++b->jobs;b->bytes+=bytes;return 0;
}
static inline int rf_gq_unreserve(struct rf_gq_budget *b,uint64_t bytes)
{
    if(!b||!b->jobs||!bytes||bytes>b->bytes)return EINVAL;
    --b->jobs;b->bytes-=bytes;return 0;
}
/* Only the serialized accept path issues a client fence. It denotes queued
 * work until retirement records a real native GPU finish and cache invalidate. */
static inline int rf_gq_accept(struct rf_gq_client *q,uint32_t *fence)
{
    if(!q||!fence||q->closing||q->failed)return ECANCELED;
    if(q->issued==UINT32_MAX||q->pending>=RF_GQ_MAX_JOBS)return EOVERFLOW;
    *fence=++q->issued;++q->pending;return 0;
}
static inline int rf_gq_retire(struct rf_gq_client *q,uint32_t fence,int error)
{
    if(!q||!fence||!q->pending||fence!=q->retired+1||fence>q->issued)return EPROTO;
    q->retired=fence;--q->pending;
    if(error&&!q->failed){q->failed=fence;q->first_error=error;}
    if(!q->failed)q->completed=fence;
    return 0;
}
static inline int rf_gq_status(const struct rf_gq_client *q,uint32_t fence)
{
    if(!q||!fence||fence>q->issued)return EINVAL;
    /* A failed predecessor does not release a later job's retained pages. */
    if(fence>q->retired)return EAGAIN;
    if(q->failed&&fence>=q->failed)return q->first_error?q->first_error:EIO;
    return fence<=q->completed?0:EAGAIN;
}
/* drm_msm uses an absolute monotonic timespec. Zero is a nonblocking poll;
 * huge valid deadlines are bounded without overflowing their conversion. */
static inline int rf_gq_deadline(int64_t seconds,int64_t nanos,uint64_t now,uint64_t *end)
{
    if(!end||seconds<0||nanos<0||nanos>=1000000000)return EINVAL;
    uint64_t limit=now>UINT64_MAX-RF_GQ_WAIT_NS?UINT64_MAX:now+RF_GQ_WAIT_NS;
    uint64_t requested=(uint64_t)seconds>(UINT64_MAX-(uint64_t)nanos)/UINT64_C(1000000000)?UINT64_MAX:
        (uint64_t)seconds*UINT64_C(1000000000)+(uint64_t)nanos;
    *end=requested<limit?requested:limit;return 0;
}
#endif
