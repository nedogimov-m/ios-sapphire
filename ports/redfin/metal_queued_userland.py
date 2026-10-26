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
static uint64_t redfin_scheduling[REDFIN_METAL_SCHEDULING_WORDS];
static void redfin_scheduling_add(unsigned field,uint64_t count)
{__atomic_fetch_add(&redfin_scheduling[field],count,__ATOMIC_RELAXED);}
static void redfin_scheduling_read(uint64_t *counts)
{
    for(unsigned i=0;i<REDFIN_METAL_SCHEDULING_WORDS;++i)
        counts[i]=__atomic_load_n(&redfin_scheduling[i],__ATOMIC_RELAXED);
}
static void redfin_scheduling_wait(BOOL scheduled,BOOL blocked,BOOL early,uint64_t start)
{
    redfin_scheduling_add(scheduled?RF_MS_SCHEDULED_CALLS:RF_MS_COMPLETED_CALLS,1);
    redfin_scheduling_add(scheduled?RF_MS_SCHEDULED_BLOCKS:RF_MS_COMPLETED_BLOCKS,blocked);
    redfin_scheduling_add(scheduled?RF_MS_SCHEDULED_US:RF_MS_COMPLETED_US,
        redfin_phase_us(start,mach_absolute_time()));
    if(scheduled&&early)redfin_scheduling_add(RF_MS_EARLY_RETURNS,1);
}
static void redfin_scheduling_report(uint64_t sequence)
{
    uint64_t c[REDFIN_METAL_SCHEDULING_WORDS];redfin_scheduling_read(c);
    uint64_t n=c[RF_MS_SCHEDULED_CALLS]+c[RF_MS_COMPLETED_CALLS];
    rw_print("REDFIN METAL SCHEDULING: boot=%s sequence=%llu calls=%llu publications=%llu scheduled-calls=%llu scheduled-blocks=%llu scheduled-wait-us=%llu scheduled-before-completion=%llu completed-calls=%llu completed-blocks=%llu completed-wait-us=%llu scheduled-handlers=%llu completed-handlers=%llu real-retirement-required=1 process-cumulative=1\n",redfin_fence_boot,
        (unsigned long long)sequence,(unsigned long long)n,(unsigned long long)c[RF_MS_PUBLICATIONS],
        (unsigned long long)c[RF_MS_SCHEDULED_CALLS],(unsigned long long)c[RF_MS_SCHEDULED_BLOCKS],
        (unsigned long long)c[RF_MS_SCHEDULED_US],(unsigned long long)c[RF_MS_EARLY_RETURNS],
        (unsigned long long)c[RF_MS_COMPLETED_CALLS],(unsigned long long)c[RF_MS_COMPLETED_BLOCKS],
        (unsigned long long)c[RF_MS_COMPLETED_US],(unsigned long long)c[RF_MS_SCHEDULED_HANDLERS],
        (unsigned long long)c[RF_MS_COMPLETED_HANDLERS]);
}
struct redfin_metal_encoded_stats {
    uint64_t queued,worker,acquired,submitted;
    uint64_t io_start[10],io_end[10];
    uint64_t frontend_start[REDFIN_METAL_FRONTEND_WORDS],frontend_end[REDFIN_METAL_FRONTEND_WORDS];
    uint64_t bindings_start[REDFIN_METAL_BINDING_WORDS],bindings_end[REDFIN_METAL_BINDING_WORDS];
    uint64_t order_start[REDFIN_METAL_ORDERING_WORDS],order_end[REDFIN_METAL_ORDERING_WORDS];
    unsigned draws,computes;
    BOOL io_valid,frontend_valid,bindings_valid,order_valid;
};
struct redfin_metal_retirement_stats {
    uint64_t worker,native_done,previous_done,gate,retired,resources,slot;
    unsigned native_ticket;
};
static void redfin_metal_encoded_report(const struct redfin_metal_encoded_stats *s,
    const struct redfin_metal_retirement_stats *p)
{
    /* Assign one sequence to every observation of this command. The legacy
     * final-fence interval includes host retirement; the new row separates it. */
    uint64_t n=redfin_metal_completed(s->draws,s->computes,s->queued,s->worker,s->acquired,s->submitted,p->retired);
    if(!n)return;
    if(s->io_valid)redfin_metal_io_sequence(s->io_start,s->io_end,n);
    if(n>4&&(n&(n-1))&&(n%120))return;
    redfin_scheduling_report(n);
    rw_print("REDFIN METAL RETIREMENT: boot=%s sequence=%llu actual-finish=1 native-ticket=%u completion-queue-us=%llu native-wait-us=%llu predecessor-us=%llu retire-gate-us=%llu bookkeeping-us=%llu resources-us=%llu slot-us=%llu submit-to-ready-us=%llu\n",redfin_fence_boot,(unsigned long long)n,p->native_ticket,
        (unsigned long long)redfin_phase_us(s->submitted,p->worker),
        (unsigned long long)redfin_phase_us(p->worker,p->native_done),
        (unsigned long long)redfin_phase_us(p->native_done,p->previous_done),
        (unsigned long long)redfin_phase_us(p->previous_done,p->gate),
        (unsigned long long)redfin_phase_us(p->gate,p->retired),
        (unsigned long long)redfin_phase_us(p->retired,p->resources),
        (unsigned long long)redfin_phase_us(p->resources,p->slot),
        (unsigned long long)redfin_phase_us(s->submitted,p->slot));
    if(s->frontend_valid) {
        const uint64_t *a=s->frontend_start,*b=s->frontend_end;BOOL valid=YES;
        for(unsigned i=0;i<REDFIN_METAL_FRONTEND_WORDS;++i)if(b[i]<a[i])valid=NO;
        if(valid) {
#define RF_MFP_DELTA(f) ((unsigned long long)(b[f]-a[f]))
            /* These are nested scopes, not additive frame costs. The max is
             * cumulative for this device; all other fields are command deltas. */
            rw_print("REDFIN METAL FRONTEND: boot=%s sequence=%llu actual-finish=1 stage-calls=%llu stage-us=%llu draw-calls=%llu draw-us=%llu framebuffer-us=%llu draw-emit-us=%llu direct-constants=%llu snapshots=%llu snapshot-bytes=%llu maximum-snapshot-bytes-ever=%llu unknown-snapshots=%llu unknown-snapshot-bytes=%llu constant-prepare-us=%llu constant-copy-us=%llu submit-calls=%llu submit-us=%llu submit-clear-us=%llu submit-resolve-us=%llu proven-snapshots=%llu avoided-snapshot-bytes=%llu full-snapshots=%llu nested-scopes=1\n",redfin_fence_boot,(unsigned long long)n,
                RF_MFP_DELTA(RF_MFP_STAGE_CALLS),RF_MFP_DELTA(RF_MFP_STAGE_NS)/1000,
                RF_MFP_DELTA(RF_MFP_DRAW_CALLS),RF_MFP_DELTA(RF_MFP_DRAW_NS)/1000,
                RF_MFP_DELTA(RF_MFP_FRAMEBUFFER_NS)/1000,RF_MFP_DELTA(RF_MFP_DRAW_EMIT_NS)/1000,
                RF_MFP_DELTA(RF_MFP_CONSTANT_DIRECT),RF_MFP_DELTA(RF_MFP_CONSTANT_UPLOADS),
                RF_MFP_DELTA(RF_MFP_CONSTANT_BYTES),(unsigned long long)b[RF_MFP_CONSTANT_MAX_BYTES],
                RF_MFP_DELTA(RF_MFP_CONSTANT_UNKNOWN),RF_MFP_DELTA(RF_MFP_CONSTANT_UNKNOWN_BYTES),
                RF_MFP_DELTA(RF_MFP_CONSTANT_PREPARE_NS)/1000,RF_MFP_DELTA(RF_MFP_CONSTANT_UPLOAD_NS)/1000,
                RF_MFP_DELTA(RF_MFP_SUBMIT_CALLS),RF_MFP_DELTA(RF_MFP_SUBMIT_NS)/1000,
                RF_MFP_DELTA(RF_MFP_SUBMIT_CLEAR_NS)/1000,RF_MFP_DELTA(RF_MFP_SUBMIT_RESOLVE_NS)/1000,
                RF_MFP_DELTA(RF_MFP_CONSTANT_PROVEN),RF_MFP_DELTA(RF_MFP_CONSTANT_AVOIDED_BYTES),
                RF_MFP_DELTA(RF_MFP_CONSTANT_FALLBACK));
#undef RF_MFP_DELTA
        }
    }
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

SCHEDULING=r'''
/* Only native FIFO publication releases scheduling waiters. GPU completion,
 * CPU-visible resources, queue slots and errors keep their real retirement. */
- (void)redfinDeliverScheduled
{
    @synchronized(self) {
        if(!_redfinScheduled&&!_redfinFinalized)return;
        if(_redfinSchedulingPending) {
            _redfinSchedulingPending=NO;dispatch_group_leave(_redfinScheduling);
        }
        NSArray *scheduled=_scheduled;_scheduled=nil;
        redfin_scheduling_add(RF_MS_SCHEDULED_HANDLERS,scheduled.count);
        for(id handler in scheduled)[self redwoodDeliver:(void (^)(id))handler];
        [scheduled release];
    }
}
- (void)redfinPublishScheduled
{
    @synchronized(self) {
        if(_redfinScheduled||_redfinFinalized||_status==RW_CB_ERROR)return;
        _status=RW_CB_SCHEDULED;_redfinScheduled=YES;
        redfin_scheduling_add(RF_MS_PUBLICATIONS,1);
        [self redfinDeliverScheduled];
    }
}
- (void)waitUntilScheduled
{
    uint64_t start=mach_absolute_time();
    BOOL blocked=!_redfinFinalized&&!_redfinScheduled&&_status>=RW_CB_COMMITTED;
    if(blocked)dispatch_group_wait(_redfinScheduling,DISPATCH_TIME_FOREVER);
    redfin_scheduling_wait(YES,blocked,_redfinScheduled&&!_redfinFinalized,start);
}
- (void)waitUntilCompleted
{
    uint64_t start=mach_absolute_time();
    BOOL blocked=!_redfinFinalized&&_status>=RW_CB_COMMITTED;
    if(blocked)dispatch_group_wait(_redfinExecution,DISPATCH_TIME_FOREVER);
    redfin_scheduling_wait(NO,blocked,NO,start);
}
'''


def adapt(text):
    text=replace_once(text,'#include "metal-ordering.h"','#include "metal-ordering.h"\n#include "metal-queued.h"\n#include "metal-frontend-profile.h"\n#include "metal-scheduling.h"')
    text=replace_once(text,'\t_Atomic(BOOL) _redfinFinalized;',
        '\t_Atomic(BOOL) _redfinFinalized;\n\t_Atomic(BOOL) _redfinScheduled;\n'
        '\tdispatch_group_t _redfinScheduling;\n\tBOOL _redfinSchedulingPending;')
    text=replace_once(text,'\t_redfinExecution=dispatch_group_create();\n\tif (!_redfinExecution)',
        '\t_redfinExecution=dispatch_group_create();\n\t_redfinScheduling=dispatch_group_create();\n'
        '\tif (!_redfinExecution||!_redfinScheduling)')
    text=replace_once(text,'\tif (_redfinExecution) dispatch_release(_redfinExecution);',
        '\tif (_redfinExecution) dispatch_release(_redfinExecution);\n'
        '\tif (_redfinScheduling) dispatch_release(_redfinScheduling);')
    text=replace_once(text,'\t\tdispatch_group_enter(_redfinExecution);',
        '\t\tdispatch_group_enter(_redfinExecution);\n'
        '\t\tdispatch_group_enter(_redfinScheduling);_redfinSchedulingPending=YES;')
    point='\tint (*commands_end)(struct rwa_device *, char *, size_t);'
    text=replace_once(text,point,point+'''
    int (*commands_submit)(struct rwa_device *,struct rwa_redfin_completion **,char *,size_t);
    int (*frontend_statistics)(struct rwa_device *,uint64_t *,size_t);
    int (*completion_wait)(struct rwa_redfin_completion *,char *,size_t);
    int (*completion_retire)(struct rwa_redfin_completion *,char *,size_t);
    void (*completion_destroy)(struct rwa_redfin_completion *);''')
    point='\t*(void **)&mesa.commands_end = dlsym(mesa.handle, "rwa_commands_end");'
    text=replace_once(text,point,point+'''
    *(void **)&mesa.commands_submit=dlsym(mesa.handle,"rwa_redfin_commands_submit");
    *(void **)&mesa.frontend_statistics=dlsym(mesa.handle,"rwa_redfin_frontend_statistics");
    *(void **)&mesa.completion_wait=dlsym(mesa.handle,"rwa_redfin_completion_wait");
    *(void **)&mesa.completion_retire=dlsym(mesa.handle,"rwa_redfin_completion_retire");
    *(void **)&mesa.completion_destroy=dlsym(mesa.handle,"rwa_redfin_completion_destroy");''')
    text=replace_once(text,'if (mesa.redfin_compute_create == NULL ||',
        'if (!mesa.commands_submit || !mesa.frontend_statistics || !mesa.completion_wait || !mesa.completion_retire || !mesa.completion_destroy || mesa.redfin_compute_create == NULL ||')
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
    struct rwa_redfin_completion *ticket=NULL;BOOL published=NO;
    char why[512]={0};
    {
        REDFIN_MESA_SCOPE;
        struct rwa_device *device=[[_queue device] mesaDevice];
        stats.acquired=mach_absolute_time();
        stats.io_valid=mesa.submission_statistics(device,stats.io_start,10)==0;
        stats.frontend_valid=mesa.frontend_statistics(device,stats.frontend_start,REDFIN_METAL_FRONTEND_WORDS)==0;
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
            if(began) {
                int error=mesa.commands_submit(device,&ticket,why,sizeof(why));
                if(error)[self failWith:why];
                published=!error&&ticket&&_status!=RW_CB_ERROR;
            }
            stats.submitted=mach_absolute_time();
            for(RedwoodMetalWork *work in _work) {
                if(work->redfinClearOnly||work->redfinBlit.operation)continue;
                if(work->render)++stats.draws;else ++stats.computes;
            }
            stats.io_valid=stats.io_valid&&mesa.submission_statistics(device,stats.io_end,10)==0;
            stats.frontend_valid=stats.frontend_valid&&mesa.frontend_statistics(device,stats.frontend_end,REDFIN_METAL_FRONTEND_WORDS)==0;
            stats.bindings_valid=stats.bindings_valid&&mesa.binding_statistics(device,stats.bindings_end,REDFIN_METAL_BINDING_WORDS)==0;
            stats.order_valid=stats.order_valid&&mesa.ordering_statistics(device,stats.order_end,REDFIN_METAL_ORDERING_WORDS)==0;
        }
    } /* Release the Gallium gate before any actual GPU wait. */
    if(published)[self redfinPublishScheduled];
    if(previous)dispatch_retain(previous);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE,0),^{
        @autoreleasepool {
            struct redfin_metal_retirement_stats phases={.worker=mach_absolute_time(),.native_ticket=ticket!=NULL};
            BOOL report=NO;
            @try {
                char completed_why[512]={0};
                int error=ticket?mesa.completion_wait(ticket,completed_why,sizeof(completed_why)):0;
                phases.native_done=mach_absolute_time();
                if(previous)dispatch_group_wait(previous,DISPATCH_TIME_FOREVER);
                phases.previous_done=mach_absolute_time();phases.gate=phases.previous_done;
                if(ticket) {
                    REDFIN_MESA_SCOPE;
                    phases.gate=mach_absolute_time();
                    if(mesa.completion_retire(ticket,completed_why,sizeof(completed_why)))error=-1;
                    mesa.completion_destroy(ticket);
                }
                phases.retired=mach_absolute_time();
                if(error)[self failWith:completed_why];
                if(_status!=RW_CB_ERROR) {
                    _status=RW_CB_COMPLETED;
                    report=YES;
                }
            } @catch(NSException *exception) {
                [self failWith:exception.reason.UTF8String ?: "Metal completion raised an exception"];
            } @finally {
                if(previous)dispatch_release(previous);
                [self redfinFinishResources];
                phases.resources=mach_absolute_time();
                _redfinFinalized=YES;
                [self redwoodReturnSlot];
                phases.slot=mach_absolute_time();
                if(report)redfin_metal_encoded_report(&stats,&phases);
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
    # A native ticket covers actual flushed FIFO admission, including resolves.
    # An encoding refusal retains its full drain; it is not a scheduling success.
    text=replace_once(text,'- (NSUInteger)status { return _status; }',
        '- (NSUInteger)status {NSUInteger status=_status;return !_redfinFinalized&&status>=RW_CB_SCHEDULED?(_redfinScheduled?RW_CB_SCHEDULED:RW_CB_COMMITTED):status;}')
    first=text.index('- (void)waitUntilCompleted\n{')
    last=text.index('\n/*\n * HANDLERS,',first)
    text=text[:first]+SCHEDULING+text[last:]
    first=text.index('/*\n * HANDLERS, AND WHERE THEY RUN.')
    last=text.index('- (void)redwoodDeliver:(void (^)(id))handler',first)
    text=text[:first]+'''/* Scheduled handlers follow actual native FIFO publication. Completed handlers
 * follow actual fence retirement and resource readiness, including failures.
 * Both use the caller's completion queue or an off-encoder default, so callbacks
 * may submit and wait reentrantly. Late handlers are delivered exactly once. */
'''+text[last:]
    first=text.index('- (void)addScheduledHandler:');last=text.index('\n}\n',first)+3
    part=text[first:last]
    part=replace_once(part,'if (_status >= RW_CB_SCHEDULED)', 'if (_redfinScheduled||_redfinFinalized)')
    first_comment=part.index('\t/* scheduled or further,')
    last_comment=part.index('\tif (_redfinScheduled||_redfinFinalized)',first_comment)
    part=part[:first_comment]+'\t/* Native publication or final error cleanup releases scheduling. */\n'+part[last_comment:]
    part=replace_once(part,'[self redwoodDeliver:handler];',
        'redfin_scheduling_add(RF_MS_SCHEDULED_HANDLERS,1);[self redwoodDeliver:handler];')
    text=text[:first]+part+text[last:]
    first=text.index('- (void)addCompletedHandler:');last=text.index('\n}\n',first)+3
    part=text[first:last]
    part=replace_once(part,'[self redwoodDeliver:handler];',
        'redfin_scheduling_add(RF_MS_COMPLETED_HANDLERS,1);[self redwoodDeliver:handler];')
    text=text[:first]+part+text[last:]
    first=text.index('- (void)redwoodDeliverHandlers\n{');last=text.index('\n}\n',first)+3
    first=text.rfind('/* Called from the one place',0,first)
    if first<0:raise ValueError('unreviewed native handler completion block')
    text=text[:first]+r'''/* Called only after real retirement, or refusal before native work began. */
- (void)redwoodDeliverHandlers
{
    @synchronized(self) {
        if(!_redfinFinalized)return;
        [self redfinDeliverScheduled]; /* Failed/empty commands also release waiters. */
        NSArray *completed=_completed;_completed=nil;
        redfin_scheduling_add(RF_MS_COMPLETED_HANDLERS,completed.count);
        for(id handler in completed)[self redwoodDeliver:(void (^)(id))handler];
        [completed release];
    }
}
'''+text[last:]
    text+=r'''
int redfin_metal_frontend_statistics(id device,uint64_t *counts,size_t words)
{
    REDFIN_MESA_SCOPE;
    if(!device||![device isKindOfClass:[RedwoodMetalDevice class]]||!mesa_available()||
       !mesa.frontend_statistics)return -1;
    return mesa.frontend_statistics([(RedwoodMetalDevice *)device mesaDevice],counts,words);
}
int redfin_metal_scheduling_statistics(id device,uint64_t *counts,size_t words)
{
    if(!device||![device isKindOfClass:[RedwoodMetalDevice class]]||!counts||
       words!=REDFIN_METAL_SCHEDULING_WORDS)return -1;
    redfin_scheduling_read(counts);return 0;
}
'''
    return text
