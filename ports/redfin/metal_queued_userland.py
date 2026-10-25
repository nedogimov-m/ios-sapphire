"""Separate serial Gallium encoding from actual native GPU completion."""
from ports.redfin.eagl_userland import replace_once

EXECUTION=r'''
/* Serial encoding admits up to two commands. Their real GPU waits and object
 * destruction run off this queue; callbacks may submit and wait reentrantly. */
#include <dispatch/dispatch.h>
static pthread_once_t redfin_execution_once=PTHREAD_ONCE_INIT;
static dispatch_queue_t redfin_execution_queue;
static dispatch_semaphore_t redfin_execution_slots;
static dispatch_group_t redfin_execution_tail; /* accessed only by encoder */
static void redfin_execution_init(void)
{
    dispatch_queue_attr_t attr=dispatch_queue_attr_make_with_qos_class(
        DISPATCH_QUEUE_SERIAL,QOS_CLASS_USER_INTERACTIVE,0);
    redfin_execution_queue=dispatch_queue_create("com.redfin.metal.encoding",attr);
    redfin_execution_slots=dispatch_semaphore_create(2);
    if(!redfin_execution_queue||!redfin_execution_slots)abort();
}
static void redfin_metal_schedule(dispatch_group_t group,
    void (^work)(dispatch_group_t,dispatch_block_t))
{
    if(!group||!work||pthread_once(&redfin_execution_once,redfin_execution_init))abort();
    dispatch_semaphore_wait(redfin_execution_slots,DISPATCH_TIME_FOREVER);
    dispatch_retain(group);
    dispatch_async(redfin_execution_queue,^{
        dispatch_group_t previous=redfin_execution_tail;
        redfin_execution_tail=group;dispatch_retain(group);
        __block int finished=0;
        dispatch_block_t finish=^{
            if(!__atomic_exchange_n(&finished,1,__ATOMIC_ACQ_REL)) {
                dispatch_group_leave(group);
                dispatch_semaphore_signal(redfin_execution_slots);
                dispatch_release(group);
            }
        };
        work(previous,finish);
        if(previous)dispatch_release(previous);
    });
}
'''

STATS=r'''
struct redfin_metal_encoded_stats {
    uint64_t queued,worker,acquired,submitted;
    uint64_t io_start[10],io_end[10];
    uint64_t bindings_start[REDFIN_METAL_BINDING_WORDS],bindings_end[REDFIN_METAL_BINDING_WORDS];
    uint64_t order_start[REDFIN_METAL_ORDERING_WORDS],order_end[REDFIN_METAL_ORDERING_WORDS];
    unsigned draws,computes;
    BOOL io_valid,bindings_valid,order_valid;
};
static void redfin_metal_encoded_report(const struct redfin_metal_encoded_stats *s,uint64_t finished)
{
    redfin_metal_completed(s->draws,s->computes,s->queued,s->worker,s->acquired,s->submitted,finished);
    if(!s->draws&&!s->computes)return;
    if(s->io_valid)redfin_metal_io_completed(s->io_start,s->io_end);
    static uint64_t sequence;uint64_t n=__atomic_add_fetch(&sequence,1,__ATOMIC_RELAXED);
    if(n>4&&(n&(n-1))&&(n%120))return;
    if(s->bindings_valid) {
        const uint64_t *a=s->bindings_start,*b=s->bindings_end;
        rw_print("REDFIN METAL BINDINGS: boot=%s sequence=%llu stage-requests=%llu descriptor-calls=%llu descriptor-skips=%llu constant-refreshes=%llu stale-slots=%llu graphics-calls=%llu graphics-skips=%llu vertex-calls=%llu vertex-skips=%llu live-stage-slots=%llu live-vertex-refs=%llu\n",redfin_fence_boot,(unsigned long long)n,
            (unsigned long long)(b[0]-a[0]),(unsigned long long)(b[1]-a[1]),(unsigned long long)(b[2]-a[2]),(unsigned long long)(b[3]-a[3]),
            (unsigned long long)(b[4]-a[4]),(unsigned long long)(b[6]-a[6]),(unsigned long long)(b[7]-a[7]),(unsigned long long)(b[8]-a[8]),
            (unsigned long long)(b[9]-a[9]),(unsigned long long)b[10],(unsigned long long)b[11]);
    }
    if(s->order_valid) {
        const uint64_t *a=s->order_start,*b=s->order_end;
        rw_print("REDFIN METAL ORDERING: boot=%s sequence=%llu queued=%llu encode-finishes=%llu CPU-drains=%llu deferred=%llu resolves=%llu GPU-barriers=%llu actual-retirement=1 async-wait=1\n",redfin_fence_boot,(unsigned long long)n,
            (unsigned long long)(b[0]-a[0]),(unsigned long long)(b[1]-a[1]),(unsigned long long)(b[2]-a[2]),
            (unsigned long long)(b[3]-a[3]),(unsigned long long)(b[4]-a[4]),(unsigned long long)(b[5]-a[5]));
    }
}
'''


def adapt(text):
    text=replace_once(text,'#include "metal-ordering.h"','#include "metal-ordering.h"\n#include "metal-queued.h"')
    point='\tint (*commands_end)(struct rwa_device *, char *, size_t);'
    text=replace_once(text,point,point+'''
    int (*commands_submit)(struct rwa_device *,struct rwa_redfin_completion **,char *,size_t);
    int (*completion_wait)(struct rwa_redfin_completion *,char *,size_t);
    int (*completion_retire)(struct rwa_redfin_completion *,char *,size_t);
    void (*completion_destroy)(struct rwa_redfin_completion *);''')
    point='\t*(void **)&mesa.commands_end = dlsym(mesa.handle, "rwa_commands_end");'
    text=replace_once(text,point,point+'''
    *(void **)&mesa.commands_submit=dlsym(mesa.handle,"rwa_redfin_commands_submit");
    *(void **)&mesa.completion_wait=dlsym(mesa.handle,"rwa_redfin_completion_wait");
    *(void **)&mesa.completion_retire=dlsym(mesa.handle,"rwa_redfin_completion_retire");
    *(void **)&mesa.completion_destroy=dlsym(mesa.handle,"rwa_redfin_completion_destroy");''')
    text=replace_once(text,'if (mesa.redfin_compute_create == NULL ||',
        'if (!mesa.commands_submit || !mesa.completion_wait || !mesa.completion_retire || !mesa.completion_destroy || mesa.redfin_compute_create == NULL ||')
    first=text.index('/* A native -commit enqueues work;');last=text.index('/* Completion evidence',first)
    text=text[:first]+EXECUTION+'\n'+text[last:]
    # Reporting depends on the existing actual-fence timing helpers, so put
    # its declaration immediately before the next function after those helpers.
    at=text.index('static bool\nmesa_available(')
    text=text[:at]+STATS+'\n'+text[at:]
    point='''\t\tredfin_metal_schedule(_redfinExecution,^{
\t\t\t@autoreleasepool {[self redfinExecute];}
\t\t});'''
    text=replace_once(text,point,'''        [self retain]; /* explicit execution anchor, released off encoder */
        void *command=(void *)self;
        redfin_metal_schedule(_redfinExecution,^(dispatch_group_t previous,dispatch_block_t finish){
            @autoreleasepool {[(RedwoodMetalCommandBuffer *)command redfinEncodeAfter:previous finish:finish];}
        });''')
    first=text.index('- (void)redfinExecute\n{');last=text.index('\n/* A draw, built out of',first)
    old=text[first:last]
    a=old.index('\t_status = RW_CB_COMMITTED;');b=old.index('done:;',a)+len('done:;')
    loop=old[a:b]
    execute=r'''- (void)redfinEncodeAfter:(dispatch_group_t)previous finish:(dispatch_block_t)finish
{
    struct redfin_metal_encoded_stats stats={.queued=_redfinQueuedTicks,.worker=mach_absolute_time()};
    struct rwa_redfin_completion *ticket=NULL;
    char why[512]={0};
    {
        REDFIN_MESA_SCOPE;
        struct rwa_device *device=[[_queue device] mesaDevice];
        stats.acquired=mach_absolute_time();
        stats.io_valid=mesa.submission_statistics(device,stats.io_start,10)==0;
        stats.bindings_valid=mesa.binding_statistics(device,stats.bindings_start,REDFIN_METAL_BINDING_WORDS)==0;
        stats.order_valid=mesa.ordering_statistics(device,stats.order_start,REDFIN_METAL_ORDERING_WORDS)==0;
        BOOL began=NO;
        @try {
            if(mesa.commands_begin(device,why,sizeof(why))) [self failWith:why];
            else {
                began=YES;
''' + loop + r'''
            }
        } @catch(NSException *exception) {
            [self failWith:exception.reason.UTF8String ?: "Metal encoding raised an exception"];
        } @finally {
            if(began&&mesa.commands_submit(device,&ticket,why,sizeof(why))) [self failWith:why];
            stats.submitted=mach_absolute_time();
            for(RedwoodMetalWork *work in _work) {
                if(work->redfinClearOnly||work->redfinBlit.operation)continue;
                if(work->render)++stats.draws;else ++stats.computes;
            }
            stats.io_valid=stats.io_valid&&mesa.submission_statistics(device,stats.io_end,10)==0;
            stats.bindings_valid=stats.bindings_valid&&mesa.binding_statistics(device,stats.bindings_end,REDFIN_METAL_BINDING_WORDS)==0;
            stats.order_valid=stats.order_valid&&mesa.ordering_statistics(device,stats.order_end,REDFIN_METAL_ORDERING_WORDS)==0;
        }
    } /* Release the Gallium gate before any actual GPU wait. */
    if(previous)dispatch_retain(previous);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE,0),^{
        @autoreleasepool {
            @try {
                char completed_why[512]={0};
                int error=ticket?mesa.completion_wait(ticket,completed_why,sizeof(completed_why)):0;
                if(previous)dispatch_group_wait(previous,DISPATCH_TIME_FOREVER);
                if(ticket) {
                    REDFIN_MESA_SCOPE;
                    if(mesa.completion_retire(ticket,completed_why,sizeof(completed_why)))error=-1;
                    mesa.completion_destroy(ticket);
                }
                if(error)[self failWith:completed_why];
                if(_status!=RW_CB_ERROR) {
                    _status=RW_CB_SCHEDULED;
                    _status=RW_CB_COMPLETED;
                    redfin_metal_encoded_report(&stats,mach_absolute_time());
                }
            } @catch(NSException *exception) {
                [self failWith:exception.reason.UTF8String ?: "Metal completion raised an exception"];
            } @finally {
                if(previous)dispatch_release(previous);
                [self redfinFinishResources];
                _redfinFinalized=YES;
                [self redwoodReturnSlot];
                finish(); /* group/slot only after actual native retirement */
                [self redwoodDeliverHandlers];
                [self release]; /* user deallocators run off serial encoder */
            }
        }
    });
    /* No access to self after publishing the completing block. */
}
'''
    text=text[:first]+execute+text[last:]
    # An encoding refusal can be recorded before previously emitted GPU work
    # retires. Public Error/Completed status and scheduled waiters must cover
    # that real fence and resource cleanup too.
    text=replace_once(text,'- (NSUInteger)status { return _status; }',
        '- (NSUInteger)status {NSUInteger status=_status;return !_redfinFinalized&&status>=RW_CB_SCHEDULED?RW_CB_COMMITTED:status;}')
    text=replace_once(text,
        '- (void)waitUntilScheduled {if (_status<RW_CB_SCHEDULED && _status>=RW_CB_COMMITTED) [self waitUntilCompleted];}',
        '- (void)waitUntilScheduled {[self waitUntilCompleted];}')
    # Failed encoding can set Error before its emitted work has retired.
    first=text.index('- (void)addScheduledHandler:');last=text.index('\n}\n',first)+3
    part=text[first:last]
    part=replace_once(part,'if (_status >= RW_CB_SCHEDULED)', 'if (_redfinFinalized)')
    text=text[:first]+part+text[last:]
    return text
