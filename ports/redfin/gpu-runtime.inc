/* SPDX-License-Identifier: MIT */
/* Persistent GUI3 owner. The existing startup proof remains mandatory;
 * all objects are retained if DMA completion or TLB synchronization is lost.
 * Startup stays on CPU0. Runtime calls hold the IOKit mutex and a single
 * thread lease on one of the eight already verified, coherent CPUs.
 */
#include "redfin_gpu_runtime.h"
#include "redfin_gpu_service.h"
#include "redfin_gpu_display.h"
extern int redfin_gui_runtime_cpu(void);
static struct {
    thread_t caller;
    struct rf_gr_arena arena;
    struct rf_gm_memory pool;
    uint64_t *l2,*leaves;
    uint64_t *dirty_first,*dirty_end;
    uint64_t audit_ns,wait_ns,publish_ns,gpu_ticks,polls;
    uint32_t state,fence,completed;
    bool dirty;
} gr;

bool redfin_gpu_ready(void)
{return __atomic_load_n(&gr.state,__ATOMIC_ACQUIRE)==1;}
/* REDFIN_GPU_THREAD_LEASE_BEGIN */
bool redfin_gpu_runtime_caller(void)
{
    thread_t owner=__atomic_load_n(&gr.caller,__ATOMIC_ACQUIRE);
    return owner && owner==current_thread() && redfin_gpu_ready() && redfin_gui_runtime_cpu();
}
void *redfin_gpu_bind(void)
{
    thread_t previous=__atomic_exchange_n(&gr.caller,current_thread(),__ATOMIC_ACQ_REL);
    if(previous)redfin_gpu_poison("overlapping runtime thread lease");
    return (void *)previous;
}
void redfin_gpu_unbind(void *previous)
{
    thread_t expected=current_thread();
    if(!__atomic_compare_exchange_n(&gr.caller,&expected,(thread_t)previous,false,
        __ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))redfin_gpu_poison("runtime thread lease changed");
}
/* REDFIN_GPU_THREAD_LEASE_END */
void redfin_gpu_poison(const char *reason)
{
    if(__atomic_exchange_n(&gr.state,2,__ATOMIC_ACQ_REL)!=2)
        printf("REDFIN GPU RUNTIME STOP: %s; all DMA memory retained until reset\n",reason);
}
void redfin_gpu_stop(void)
{
    if(__atomic_exchange_n(&gr.state,3,__ATOMIC_ACQ_REL)==1)
        printf("REDFIN GPU RUNTIME: orderly stop; all GPU allocations held until reset\n");
}
void redfin_gpu_sync(void *address,uint64_t size,bool invalidate)
{
    uintptr_t at=(uintptr_t)address;
    if(size && (!at || size>RF_GR_BUFFER_MAX || at>UINTPTR_MAX-size))return;
    for(uintptr_t p=at&~(uintptr_t)63;p<at+size;p+=64) {
        if(invalidate)__asm__ volatile("dc civac, %0"::"r"(p):"memory");
        else __asm__ volatile("dc cvac, %0"::"r"(p):"memory");
    }
    __asm__ volatile("dsb sy":::"memory");
}
void redfin_gpu_invalidate(void *address,uint64_t size)
{
    uintptr_t at=(uintptr_t)address;
    if(!at || !size || size>RF_GR_BUFFER_MAX || (at&63u) || (size&63u) || at>UINTPTR_MAX-size)return;
    for(uintptr_t p=at;p<at+size;p+=64)
        __asm__ volatile("dc ivac, %0"::"r"(p):"memory");
    __asm__ volatile("dsb sy":::"memory");
}
static int gr_live(void)
{
    if(!redfin_gpu_ready() || !gx.context || gx.context->smmu_mode!=6 ||
        !(redfin_gui_cpu0() || redfin_gpu_runtime_caller()))return ENXIO;
    int error=gx_check(gx.context);
    if(error)redfin_gpu_poison("power/context ownership changed");
    return error;
}
/* Runtime snapshots remain complete, twice-read and compared to the exact
 * original foreign-state lease. Bracket the read-only snapshot with the
 * full parent/args/firmware/power guard; each nested read needs only this
 * serialized coherent-CPU/context metadata, rather than power MMIO and all
 * parents again. Power is held by this owner and checked at both boundaries.
 * No table publish, TLB store or ring doorbell uses this read-only shortcut. */
static bool gr_snapshot_valid(void *argument)
{
    struct gm_context *c=argument;
    return redfin_gpu_ready() && c && c==gx.context && c->smmu_mode==6 &&
        (redfin_gui_cpu0() || redfin_gpu_runtime_caller()) && !gx.poisoned && gx.mapping.state.active &&
        !gx.mapping.state.poisoned;
}
static int gr_snapshot_global(void *argument,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || !rf_gs_read_allowed(at,&gx.mapping.state.expected) || !gr_snapshot_valid(c))return EPERM;
    *value=gm_scalar_read(c->smmu+at);return 0;
}
static int gr_snapshot_bank(void *argument,unsigned bank,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!value || !rf_gc_allowed(bank,at) || !gr_snapshot_valid(c))return EPERM;
    *value=gm_scalar_read(c->cb+4096*bank+at);return 0;
}
static int gr_snapshot(void *argument,struct rf_gs_snapshot *global,struct rf_gc_snapshot *banks)
{
    int error=gr_live();if(error || !gm_payloads_valid(argument))return error?error:ECANCELED;
    const struct rf_gs_ops go={argument,gr_snapshot_valid,gr_snapshot_global};
    const struct rf_gc_ops bo={argument,gr_snapshot_valid,gr_snapshot_bank};
    error=rf_gs_snapshot_run(&go,gm_chip,global);
    if(!error)error=rf_gc_snapshot_run(&bo,global,banks);
    if(!error)error=gr_live();
    return error?error:gm_payloads_valid(argument)?0:ECANCELED;
}
static int gr_snapshot_read(void *argument,unsigned block,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    if(!block)return gr_snapshot_global(c,at,value);
    if(block!=1 || !value || !gr_snapshot_valid(c) ||
        (!rf_gc_allowed(0,at) && at!=0x28 && at!=0x2c && at!=0x7f4))return EPERM;
    *value=gm_scalar_read(c->cb+at);return 0;
}
static int gr_source_read(void *argument,unsigned unit,uint32_t at,uint32_t *value)
{
    struct gm_context *c=argument;
    /* The complete audit brackets this read-only 16-register source check.
     * Re-entering gm_valid in both rf_gt_rd and gm_read otherwise repeats
     * every parent/power read twice for each individual clock register.
     * Keep the native offset allowlist and exact coherent caller lease. */
    if(!value || !gr_snapshot_valid(c) || unit>RF_GT_GPUCC ||
        !c->base[unit] || !rf_gt_allowed(unit,at,false))return EPERM;
    *value=gm_scalar_read(c->base[unit]+at);return 0;
}
int redfin_gpu_audit(void)
{
    struct gm_context *c=gx.context;
    int error=gr_live();
    struct rf_gt_report clock={0};
    const struct rf_gt_ops source={.context=c,.valid=gr_snapshot_valid,.read=gr_source_read};
    if(!error)error=rf_gt_source_live_power(&source,&clock,true,c->gx_requested);
    for(unsigned i=0;!error && i<sizeof(gm_smmu_clocks)/sizeof(gm_smmu_clocks[0]);++i) {
        const uint32_t *w=gm_smmu_clocks[i];
        if((gm_scalar_read(c->base[w[0]]+w[1])&w[2])!=w[3])error=EAGAIN;
    }
    struct rf_gmm_ops o=gx_mapping_ops;o.context=c;o.sample=gr_snapshot;o.read=gr_snapshot_read;
    if(!error)error=rf_a6_map_verify(&gx.mapping,&o);
    if(!error)for(unsigned bank=0;bank<2;bank++)
        if(gm_scalar_read(c->cb+4096*bank+0x28) || gm_scalar_read(c->cb+4096*bank+0x2c))error=EAGAIN;
    if(!error)error=gr_live();
    if(!error && !gm_payloads_valid(c))error=ECANCELED;
    if(error)redfin_gpu_poison("complete SMMU/foreign-state audit failed");
    return error;
}
static void gr_dirty(uint64_t *first,uint64_t *end)
{
    if(!gr.dirty_first || first<gr.dirty_first)gr.dirty_first=first;
    if(!gr.dirty_end || end>gr.dirty_end)gr.dirty_end=end;
    gr.dirty=true;
}
static int gr_tlb(void)
{
    if(gr_live())return ENXIO;
    if(gr.dirty_first && gr.dirty_end)
        redfin_gpu_sync(gr.dirty_first,(uint64_t)(gr.dirty_end-gr.dirty_first)*8,false);
    if(gr_live())return ENXIO;
    gm_memory_store(gx.context->cb+0x610,0); /* Owned ASID0 only. */
    gm_memory_store(gx.context->cb+0x7f0,1);
    for(unsigned i=0;i<1000;i++) {
        if(gr_live())return ECANCELED;
        if(!(gm_scalar_read(gx.context->cb+0x7f4)&1u)) {
            gr.dirty=false;gr.dirty_first=gr.dirty_end=NULL;return 0;
        }
        delay(1);
    }
    redfin_gpu_poison("owned TLB synchronization timeout");return ETIMEDOUT;
}
int redfin_gpu_mapped(void)
{return gr.dirty?gr_tlb():gr_live();}
uint64_t redfin_gpu_address(uint64_t size)
{return gr_live() || (size&0xfffu)?0:rf_gr_allocate(&gr.arena,size);}
static uint64_t *gr_leaf(uint64_t address)
{return gr.leaves+((address-RF_GR_BASE)>>12);}
int redfin_gpu_map(uint64_t address,uint64_t physical,bool read_only)
{
    /* This writes CPU-owned page tables only. Full live checks bracket the
     * buffer allocation and its one final cache/TLB publication. */
    if(!redfin_gpu_ready() || !(redfin_gui_cpu0() || redfin_gpu_runtime_caller()) ||
        gx.poisoned || (address&0xfffu) || (physical&0xfffu) ||
        !rf_gr_find(&gr.arena,address,4096) || physical<RF_GM_PT_RAM_BASE ||
        physical>RF_GM_PT_RAM_BASE+RF_GM_PT_RAM_BYTES-4096)return EINVAL;
    uint64_t *entry=gr_leaf(address);if(*entry)return EEXIST;
    *entry=rf_gr_page_entry(physical,read_only);
    gr_dirty(entry,entry+1);return 0;
}
/* Kernel display presenter only; no IOKit selector accepts physical pages.
 * The ordinary mapper above remains restricted to XNU-owned upper RAM.
 * AppleCLCD supplies only its independently validated fixed splash surface. */
int redfin_gpu_map_display(uint64_t address,uint64_t physical)
{
    if(!redfin_gpu_ready() || !(redfin_gui_cpu0() || redfin_gpu_runtime_caller()) ||
        gx.poisoned || (address&0xfffu) || !rf_gd_panel_page(physical) ||
        !rf_gr_find(&gr.arena,address,4096))return EINVAL;
    uint64_t *entry=gr_leaf(address);if(*entry)return EEXIST;
    *entry=rf_gr_page_entry(physical,false);
    gr_dirty(entry,entry+1);return 0;
}
int redfin_gpu_release(uint64_t address,uint64_t size)
{
    const struct rf_gr_object *object=rf_gr_find(&gr.arena,address,size);
    if(gr_live() || !object || object->address!=address || object->size!=size ||
        gr.completed!=gr.fence)return EBUSY;
    for(uint64_t at=address;at<address+size;at+=4096)*gr_leaf(at)=0;
    gr_dirty(gr_leaf(address),gr_leaf(address+size));
    int error=gr_tlb();if(error)return error;
    return rf_gr_release(&gr.arena,address,size)?0:EINVAL;
}
bool redfin_gpu_done(uint32_t fence)
{return !fence || (redfin_gpu_ready() && (int32_t)(gr.completed-fence)>=0);}
uint32_t redfin_gpu_last(void){return gr.fence;}
struct gr_wait_sample {
    uint32_t wanted,done,rptr,status;
};
static int gr_wait_sample(void *argument,bool *complete)
{
    struct gr_wait_sample *s=argument;
    int error=gr_live();if(error)return error;
    uint32_t fault=gm_scalar_read(gx.gpu+4*0x821),irq=gm_scalar_read(gx.gpu+4*0x823);
    if(fault || (irq&0xf7u))return EIO;
    s->done=gm_scalar_read(gx.scratch+RF_GR_FENCE_AT);
    s->rptr=gm_scalar_read(gx.gpu+4*0x806);s->status=gm_scalar_read(gx.gpu+4*0x210);
    *complete=s->done==s->wanted && s->rptr==gx.wptr && !(s->status&~1u);return 0;
}
static void gr_wait_pause(void *argument,unsigned microseconds)
{(void)argument;delay(microseconds);}
int redfin_gpu_submit(const uint64_t *addresses,const uint32_t *words,unsigned count,uint32_t *fence)
{
    if(!fence || gr.fence==UINT32_MAX)return EINVAL;
    uint64_t audit_at=gm_time_ns(gx.context);
    int error=redfin_gpu_audit();if(error)return error;
    gr.audit_ns+=gm_time_ns(gx.context)-audit_at;
    error=redfin_gpu_mapped();if(error)return error;
    uint32_t packets[RF_GR_PACKET_WORDS],next=gr.fence+1;
    unsigned n=rf_gr_submit_words(&gr.arena,addresses,words,count,next,packets,RF_GR_PACKET_WORDS);
    if(!n)return EINVAL;
    uint32_t rptr=gm_scalar_read(gx.gpu+4*0x806),ring_words=RF_A6_RING_BYTES/4;
    if(rptr!=gx.wptr || n>=ring_words){redfin_gpu_poison("ring was not idle");return EBUSY;}
    uint64_t publish_at=gm_time_ns(gx.context);
    uint32_t *ring=gx.data[0].host;
    for(unsigned i=0;i<n;i++)ring[(gx.wptr+i)%ring_words]=packets[i];
    unsigned first_words=n<ring_words-gx.wptr?n:ring_words-gx.wptr;
    redfin_gpu_sync(ring+gx.wptr,4*first_words,false);
    if(first_words<n)redfin_gpu_sync(ring,4*(n-first_words),false);
    if(gr_live())return ECANCELED;
    gr.fence=next;gx.wptr=(gx.wptr+n)%ring_words;
    gm_memory_store(gx.gpu+4*0x807,gx.wptr);
    gr.publish_ns+=gm_time_ns(gx.context)-publish_at;
    uint64_t first=gm_time_ns(gx.context);
    struct gr_wait_sample observed={next,0,0,0};unsigned polls=0;
    const struct rf_gr_wait_ops ops={&observed,gr_wait_sample,gm_time_ns,gr_wait_pause};
    error=rf_gr_wait(&ops,RF_A6_WAIT_NS,&polls);gr.polls+=polls;
    gr.wait_ns+=gm_time_ns(gx.context)-first;
    if(!error) {
        audit_at=gm_time_ns(gx.context);error=redfin_gpu_audit();
        gr.audit_ns+=gm_time_ns(gx.context)-audit_at;
        if(!error) {
            uint64_t start=(uint64_t)gm_scalar_read(gx.scratch+RF_GR_TIME_AT+4)<<32 |
                gm_scalar_read(gx.scratch+RF_GR_TIME_AT);
            uint64_t end=(uint64_t)gm_scalar_read(gx.scratch+RF_GR_TIME_AT+12)<<32 |
                gm_scalar_read(gx.scratch+RF_GR_TIME_AT+8);
            if(end>=start)gr.gpu_ticks+=end-start;
            gr.completed=next;*fence=next;
            if(next<=8 || !(next%256)) {
                printf("REDFIN GPU RUNTIME SUBMIT: fence=%u IBs=%u done=%u rptr=%u\n",next,count,observed.done,gx.wptr);
                printf("REDFIN GPU RUNTIME TIMING: submits=%u audit-us=%llu publish-us=%llu wait-us=%llu gpu-us=%llu polls=%llu cpu=%u\n",
                    next,gr.audit_ns/1000/next,gr.publish_ns/1000/next,gr.wait_ns/1000/next,
                    gr.gpu_ticks*5/96/next,gr.polls,(unsigned)cpu_number());
            }
            return 0;
        }
    }
    printf("REDFIN GPU WAIT FAILED: wanted=%u observed=%u prior=%u rptr=%#x wptr=%#x status=%#x error=%d polls=%u elapsed-us=%llu\n",
        next,observed.done,gr.completed,observed.rptr,gx.wptr,observed.status,error,polls,
        (unsigned long long)((gm_time_ns(gx.context)-first)/1000));
    gx_diagnostic(gx.context);redfin_gpu_poison("submission did not complete");
    return error?error:ETIMEDOUT;
}
static int gr_adopt(struct gm_context *c)
{
    if(c->smmu_mode!=6 || gr.state || gx.stage!=6 || gx.submissions!=4 ||
        gx.pas_completed!=3 || !gx.mapping.state.active || gx_audit(c))return EPERM;
    /* The mode5 root/L2/leaf pages are immutable except the previously empty
     * L2 slots128..383 reserved for this separate 512MiB runtime arena. */
    vm_offset_t host=0;
    if(kmem_alloc_contig(kernel_map,&host,RF_GR_TABLE_BYTES,PAGE_MASK,
        (ppnum_t)((RF_GM_PT_RAM_BASE+RF_GM_PT_RAM_BYTES-1)>>PAGE_SHIFT),0,
        KMA_KOBJECT|KMA_ZERO|KMA_DATA,VM_KERN_MEMORY_IOKIT)!=KERN_SUCCESS)return ENOMEM;
    gr.pool=(struct rf_gm_memory){(void *)host,kvtophys(host),RF_GR_TABLE_BYTES,0x230,0};
    if(!rf_gm_memory_valid(&gr.pool))return ERANGE;
    for(unsigned i=0;i<RF_GR_TABLE_BYTES;i+=4096)
        if(kvtophys(host+i)!=gr.pool.physical+i)return ERANGE;
    gr.l2=(uint64_t *)((uint8_t *)gx.pool.host+4096);gr.leaves=(uint64_t *)host;
    for(unsigned i=0;i<RF_GR_TABLES;i++)if(gr.l2[(RF_GR_BASE>>21)+i])return EBUSY;
    gm_memory_clean(&gr.pool);
    for(unsigned i=0;i<RF_GR_TABLES;i++)gr.l2[(RF_GR_BASE>>21)+i]=(gr.pool.physical+4096*i)|3u;
    gm_memory_clean(&gx.pool);
    __atomic_store_n(&gr.state,1,__ATOMIC_RELEASE);gr.dirty=true;
    int error=gr_tlb();if(error)return error;
    printf("REDFIN GPU RUNTIME: adopted=1 tables=%u arena=%#llx+%#llx chip=0x06020001 MHz=275\n",
        RF_GR_TABLES,RF_GR_BASE,RF_GR_BYTES);
    return redfin_gpu_audit();
}
