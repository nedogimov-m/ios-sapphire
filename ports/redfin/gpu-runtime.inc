/* SPDX-License-Identifier: MIT */
/* Persistent GUI3 owner. The existing startup proof remains mandatory;
 * all objects are retained if DMA completion or TLB synchronization is lost.
 * Called under the IOKit service lock, on the already verified CPU0.
 */
#include "redfin_gpu_runtime.h"
#include "redfin_gpu_service.h"
extern void *redfin_gui_worker_enter(void);
extern void redfin_gui_worker_leave(void *);
static struct {
    struct rf_gr_arena arena;
    struct rf_gm_memory pool;
    uint64_t *l2,*leaves;
    uint32_t state,fence,completed;
    bool dirty;
} gr;

bool redfin_gpu_ready(void)
{return __atomic_load_n(&gr.state,__ATOMIC_ACQUIRE)==1;}
void *redfin_gpu_bind(void)
{return redfin_gui_worker_enter();}
void redfin_gpu_unbind(void *previous)
{redfin_gui_worker_leave(previous);}
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
static int gr_live(void)
{
    if(!redfin_gpu_ready() || !gx.context || gx.context->smmu_mode!=6 || !redfin_gui_cpu0())return ENXIO;
    int error=gx_check(gx.context);
    if(error)redfin_gpu_poison("power/context ownership changed");
    return error;
}
int redfin_gpu_audit(void)
{
    int error=gr_live();if(!error)error=gx_audit(gx.context);
    if(error)redfin_gpu_poison("complete SMMU/foreign-state audit failed");
    return error;
}
static int gr_tlb(void)
{
    if(gr_live())return ENXIO;
    gm_memory_store(gx.context->cb+0x610,0); /* Owned ASID0 only. */
    gm_memory_store(gx.context->cb+0x7f0,1);
    for(unsigned i=0;i<1000;i++) {
        if(gr_live())return ECANCELED;
        if(!(gm_scalar_read(gx.context->cb+0x7f4)&1u)){gr.dirty=false;return 0;}
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
    if(gr_live() || (address&0xfffu) || (physical&0xfffu) ||
        !rf_gr_find(&gr.arena,address,4096) || physical<RF_GM_PT_RAM_BASE ||
        physical>RF_GM_PT_RAM_BASE+RF_GM_PT_RAM_BYTES-4096)return EINVAL;
    uint64_t *entry=gr_leaf(address);if(*entry)return EEXIST;
    *entry=physical|(read_only?0xec3u:0xe43u);
    redfin_gpu_sync(entry,8,false);gr.dirty=true;return 0;
}
int redfin_gpu_release(uint64_t address,uint64_t size)
{
    const struct rf_gr_object *object=rf_gr_find(&gr.arena,address,size);
    if(gr_live() || !object || object->address!=address || object->size!=size ||
        gr.completed!=gr.fence)return EBUSY;
    for(uint64_t at=address;at<address+size;at+=4096)*gr_leaf(at)=0;
    redfin_gpu_sync(gr_leaf(address),size/512,false);gr.dirty=true;
    int error=gr_tlb();if(error)return error;
    return rf_gr_release(&gr.arena,address,size)?0:EINVAL;
}
bool redfin_gpu_done(uint32_t fence)
{return !fence || (redfin_gpu_ready() && (int32_t)(gr.completed-fence)>=0);}
uint32_t redfin_gpu_last(void){return gr.fence;}
int redfin_gpu_submit(const uint64_t *addresses,const uint32_t *words,unsigned count,uint32_t *fence)
{
    if(!fence || gr.fence==UINT32_MAX)return EINVAL;
    int error=redfin_gpu_audit();if(error)return error;
    error=redfin_gpu_mapped();if(error)return error;
    uint32_t packets[RF_GR_PACKET_WORDS],next=gr.fence+1;
    unsigned n=rf_gr_submit_words(&gr.arena,addresses,words,count,next,packets,RF_GR_PACKET_WORDS);
    if(!n)return EINVAL;
    uint32_t rptr=gm_scalar_read(gx.gpu+4*0x806),ring_words=RF_A6_RING_BYTES/4;
    if(rptr!=gx.wptr || n>=ring_words){redfin_gpu_poison("ring was not idle");return EBUSY;}
    uint32_t *ring=gx.data[0].host;
    for(unsigned i=0;i<n;i++)ring[(gx.wptr+i)%ring_words]=packets[i];
    gm_memory_clean(&gx.data[0]);gr.fence=next;gx.wptr=(gx.wptr+n)%ring_words;
    gm_memory_store(gx.gpu+4*0x807,gx.wptr);
    uint64_t first=gm_time_ns(gx.context);
    for(unsigned i=0;i<5000 && gm_time_ns(gx.context)-first<RF_A6_WAIT_NS;i++) {
        if((error=gr_live()))break;
        uint32_t fault=gm_scalar_read(gx.gpu+4*0x821),irq=gm_scalar_read(gx.gpu+4*0x823);
        if(fault || (irq&0xf7u)){error=EIO;break;}
        uint32_t done=gm_scalar_read(gx.scratch+RF_GR_FENCE_AT);
        if(done==next && gm_scalar_read(gx.gpu+4*0x806)==gx.wptr &&
            !(gm_scalar_read(gx.gpu+4*0x210)&~1u)) {
            error=redfin_gpu_audit();if(error)break;
            gr.completed=next;*fence=next;
            if(next<=8 || !(next%256))printf("REDFIN GPU RUNTIME SUBMIT: fence=%u IBs=%u done=%u rptr=%u\n",
                next,count,done,gx.wptr);
            return 0;
        }
        delay(100);
    }
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
