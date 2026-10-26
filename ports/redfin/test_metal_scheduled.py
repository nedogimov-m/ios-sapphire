"""Actual adapted command methods: native publication precedes real retirement."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from ports.redfin import metal_userland,metal_queued_userland

ROOT=Path(__file__).resolve().parents[2]


def method(text,signature):
    at=text.index(signature+'\n{');end=text.index('\n}\n',at)+3
    return text[at:end]


def block_end(text,start):
    tokens=re.finditer(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]',text[start:],re.S)
    depth=0
    for token in tokens:
        if token[0]=='{':depth+=1
        elif token[0]=='}':
            depth-=1
            if not depth:return start+token.end()
    raise ValueError('unbalanced native encoding loop')


class MetalScheduledTests(unittest.TestCase):
    def test_actual_publication_waiters_callbacks_errors_resources_and_reentrant_deallocation(self):
        upstream=ROOT/'research/hackios-upstream/userland/userland/src/redwoodmetal.m'
        native=metal_userland.adapt_driver(upstream.read_text())
        execute=method(native,'- (void)redfinEncodeAfter:(dispatch_group_t)previous finish:(dispatch_block_t)finish')
        at=execute.index('\tfor (RedwoodMetalWork *work in _work) {');brace=execute.index('{',at)
        # Replace only recorded draw/compute encoding. All actual status,
        # publication, wait, callback and retirement paths remain compiled.
        execute=execute[:at]+'\tif(_status==0)goto done;\n'+execute[block_end(execute,brace):]
        methods='\n'.join([method(native,'- (void)commit'),execute,
            *(method(native,name) for name in (
                '- (void)waitUntilCompleted','- (void)waitUntilScheduled',
                '- (void)redfinPublishScheduled','- (void)redfinDeliverScheduled',
                '- (void)redwoodDeliver:(void (^)(id))handler',
                '- (void)addScheduledHandler:(void (^)(id))handler',
                '- (void)addCompletedHandler:(void (^)(id))handler',
                '- (void)redwoodDeliverHandlers','- (void)failWith:(const char *)reason')),
            re.search(r'^- \(NSUInteger\)status \{[^\n]*\}',native,re.M).group()])
        source=r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <mach/mach_time.h>
#include "metal-ordering.h"
#include "metal-bindings.h"
#include "metal-queued.h"
#include "metal-frontend-profile.h"
#include "metal-scheduling.h"
#include "retained-memory.h"
enum {RW_CB_COMMITTED=2,RW_CB_SCHEDULED=3,RW_CB_COMPLETED=4,RW_CB_ERROR=5};
static dispatch_semaphore_t entered,release_fence,publish_entered,release_publish,dealloc_done;
static dispatch_queue_t callbacks_queue;
static unsigned fail_fence,fail_begin,fail_submit,fail_mark,submitted,block_publish;
static _Atomic(unsigned) visible;
struct rwa_redfin_completion {unsigned fail;};
static int begin(void *d,char *why,size_t n){(void)d;if(fail_begin){snprintf(why,n,"native begin refusal");return -7;}return 0;}
static int submit(void *d,struct rwa_redfin_completion **ticket,char *why,size_t n){
 (void)d;*ticket=calloc(1,sizeof(**ticket));assert(*ticket);(*ticket)->fail=fail_fence;
 if(block_publish){dispatch_semaphore_signal(publish_entered);assert(!dispatch_semaphore_wait(release_publish,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));}
 __atomic_add_fetch(&submitted,1,__ATOMIC_RELEASE);
 if(fail_submit){snprintf(why,n,"encoding refusal after native work");return -7;}return 0;
}
static int wait_ticket(struct rwa_redfin_completion *ticket,char *why,size_t n){
 dispatch_semaphore_signal(entered);
 assert(!dispatch_semaphore_wait(release_fence,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 if(ticket->fail){snprintf(why,n,"actual native fence failure");return -7;}
 visible=42;return 0;
}
static int retire(struct rwa_redfin_completion *ticket,char *why,size_t n){(void)why;(void)n;return ticket->fail?-1:0;}
static void destroy(struct rwa_redfin_completion *ticket){free(ticket);}
static int statistics(void *d,uint64_t *counts,size_t n){(void)d;memset(counts,0,n*8);return 0;}
static struct {int (*commands_begin)(void *,char *,size_t);int (*commands_submit)(void *,struct rwa_redfin_completion **,char *,size_t);
 int (*completion_wait)(struct rwa_redfin_completion *,char *,size_t);
 int (*completion_retire)(struct rwa_redfin_completion *,char *,size_t);
 void (*completion_destroy)(struct rwa_redfin_completion *);
 int (*submission_statistics)(void *,uint64_t *,size_t);
 int (*ordering_statistics)(void *,uint64_t *,size_t);
 int (*binding_statistics)(void *,uint64_t *,size_t);
 int (*frontend_statistics)(void *,uint64_t *,size_t);
 int (*raster_statistics)(void *,uint64_t *,size_t);
 int (*retained_statistics)(void *,uint64_t *,size_t);} mesa={begin,submit,wait_ticket,retire,destroy,statistics,statistics,statistics,statistics,statistics,statistics};
static const char redfin_fence_boot[]="host-publication-fixture";
static void rw_print(const char *format,...){(void)format;}
static uint64_t redfin_phase_us(uint64_t a,uint64_t b){mach_timebase_info_data_t s;assert(!mach_timebase_info(&s));return b>=a?(uint64_t)(((__uint128_t)(b-a)*s.numer)/s.denom/1000):0;}
static uint64_t redfin_metal_completed(unsigned a,unsigned b,uint64_t c,uint64_t d,uint64_t e,uint64_t f,uint64_t g)
 {(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;return 0;}
static void redfin_metal_io_sequence(const uint64_t *a,const uint64_t *b,uint64_t n){(void)a;(void)b;(void)n;}
'''+metal_userland.LOCKING+metal_queued_userland.EXECUTION+metal_queued_userland.STATS+r'''
@interface TestDevice : NSObject
- (void *)mesaDevice;
@end
@implementation TestDevice
- (void *)mesaDevice{return (void *)1;}
@end
@interface TestQueue : NSObject
- (TestDevice *)device;
- (dispatch_queue_t)redwoodCompletionQueue;
@end
@implementation TestQueue
- (TestDevice *)device {static TestDevice *device;static dispatch_once_t once;dispatch_once(&once,^{device=[TestDevice new];});return device;}
- (dispatch_queue_t)redwoodCompletionQueue{return callbacks_queue;}
@end
@interface RedwoodMetalWork : NSObject { @public id render;BOOL redfinClearOnly;struct {unsigned operation;} redfinBlit; }
@end
@implementation RedwoodMetalWork
@end
@class TestCommand;
#define RedwoodMetalCommandBuffer TestCommand
@interface TestCommand : NSObject {
 @public _Atomic(NSUInteger) _status;_Atomic(BOOL) _redfinFinalized,_redfinScheduled;
 dispatch_group_t _redfinExecution,_redfinScheduling;uint64_t _redfinQueuedTicks;
 BOOL _redfinSchedulingPending;
 TestQueue *_queue;NSMutableArray *_work,*_scheduled,*_completed;NSError *_error;
 BOOL _testResourceActive,_testDealloc;unsigned _testReturnCount;
}
- (void)commit;
- (NSUInteger)status;
- (void)redfinEncodeAfter:(dispatch_group_t)previous finish:(dispatch_block_t)finish;
- (void)waitUntilCompleted;
- (void)waitUntilScheduled;
- (void)redfinPublishScheduled;
- (void)redfinDeliverScheduled;
- (void)redwoodDeliver:(void (^)(id))handler;
- (void)addScheduledHandler:(void (^)(id))handler;
- (void)addCompletedHandler:(void (^)(id))handler;
- (void)failWith:(const char *)reason;
- (void)redwoodReturnSlot;
- (void)redwoodDeliverHandlers;
- (BOOL)redfinMarkResources;
- (void)redfinFinishResources;
@end
@implementation TestCommand
- (instancetype)init {
 if((self=[super init])){_queue=[TestQueue new];_work=[NSMutableArray new];_status=1;_redfinExecution=dispatch_group_create();_redfinScheduling=dispatch_group_create();}return self;
}
- (void)dealloc {
 if(_testDealloc) {
  TestCommand *nested=[TestCommand new];[nested commit];dispatch_semaphore_signal(release_fence);[nested waitUntilCompleted];
  assert(nested->_redfinFinalized&&nested->_status==4);[nested release];dispatch_semaphore_signal(dealloc_done);
 }
 assert(!_testResourceActive);
 [_queue release];[_work release];[_error release];[_scheduled release];[_completed release];
 dispatch_release(_redfinExecution);dispatch_release(_redfinScheduling);[super dealloc];
}
- (void)redwoodReturnSlot {assert(_redfinFinalized&&!_testResourceActive);assert(++_testReturnCount==1);}
- (BOOL)redfinMarkResources {assert(!_testResourceActive);_testResourceActive=YES;return !fail_mark;}
- (void)redfinFinishResources {assert(_testResourceActive);_testResourceActive=NO;}
'''+methods+r'''
@end
static void take(dispatch_semaphore_t s){assert(!dispatch_semaphore_wait(s,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));}
static void joined(dispatch_group_t g){assert(!dispatch_group_wait(g,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));}
static void blocked(dispatch_group_t g){assert(dispatch_group_wait(g,dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_MSEC))!=0);}
int main(void) {
 @autoreleasepool {
  entered=dispatch_semaphore_create(0);release_fence=dispatch_semaphore_create(0);
  publish_entered=dispatch_semaphore_create(0);release_publish=dispatch_semaphore_create(0);
  callbacks_queue=dispatch_queue_create("actual-command-callbacks",DISPATCH_QUEUE_SERIAL);
  for(unsigned trial=0;trial<3;++trial) {
   fail_fence=trial==1;fail_submit=trial==2;visible=0;block_publish=1;
   TestCommand *command=[TestCommand new];
   dispatch_semaphore_t scheduled=dispatch_semaphore_create(0),completed=dispatch_semaphore_create(0),wait_entered=dispatch_semaphore_create(0);
   __block unsigned ns=0,nc=0;
   void (^onScheduled)(id)=^(TestCommand *c){[c waitUntilScheduled];assert(c.status>=RW_CB_SCHEDULED);++ns;dispatch_semaphore_signal(scheduled);};
   void (^onCompleted)(id)=^(TestCommand *c){assert(c->_redfinFinalized&&!c->_testResourceActive&&c->_testReturnCount==1);++nc;dispatch_semaphore_signal(completed);};
   [command addScheduledHandler:onScheduled];[command addScheduledHandler:onScheduled];[command addCompletedHandler:onCompleted];
   [command commit];take(publish_entered);
   assert(command.status==RW_CB_COMMITTED&&!command->_redfinScheduled&&!command->_redfinFinalized&&command->_testResourceActive&&!visible);
   dispatch_group_t sw=dispatch_group_create(),cw=dispatch_group_create();
   dispatch_group_async(sw,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{dispatch_semaphore_signal(wait_entered);[command waitUntilScheduled];});
   dispatch_group_async(cw,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{dispatch_semaphore_signal(wait_entered);[command waitUntilCompleted];});
   take(wait_entered);take(wait_entered);blocked(sw);blocked(cw);
   dispatch_semaphore_signal(release_publish);take(entered);
   assert(!command->_redfinFinalized&&command->_testResourceActive&&!visible);
   if(!fail_submit){assert(command.status==RW_CB_SCHEDULED&&command->_redfinScheduled);joined(sw);take(scheduled);take(scheduled);}
   else {assert(command.status==RW_CB_COMMITTED&&!command->_redfinScheduled);blocked(sw);assert(!ns);}
   [command addScheduledHandler:onScheduled];
   blocked(cw);assert(!nc&&command->_testResourceActive);
   dispatch_semaphore_signal(release_fence);joined(sw);joined(cw);[command waitUntilCompleted];
   if(fail_submit){take(scheduled);take(scheduled);}take(scheduled);take(completed);
   assert(command->_redfinFinalized&&!command->_testResourceActive&&command->_testReturnCount==1);
   assert(command.status==(trial?RW_CB_ERROR:RW_CB_COMPLETED));assert(fail_fence?!visible:visible==42);
   [command addScheduledHandler:onScheduled];[command addCompletedHandler:onCompleted];take(scheduled);take(completed);
   assert(ns==4&&nc==2&&dispatch_group_wait(command->_redfinScheduling,DISPATCH_TIME_NOW)==0);
   dispatch_release(sw);dispatch_release(cw);dispatch_release(scheduled);dispatch_release(completed);dispatch_release(wait_entered);[command release];
  }
  fail_fence=0;fail_submit=0;visible=0;submitted=0;block_publish=0;
  dispatch_semaphore_t run_callback=dispatch_semaphore_create(0),callback_done=dispatch_semaphore_create(0);
  TestCommand *first=[TestCommand new],*second=[TestCommand new];
  [first addScheduledHandler:^(TestCommand *c){
   take(run_callback);[c waitUntilScheduled];TestCommand *nested=[TestCommand new];[nested commit];
   dispatch_semaphore_signal(release_fence);[nested waitUntilCompleted];assert(nested.status==RW_CB_COMPLETED);[nested release];dispatch_semaphore_signal(callback_done);
  }];
  [first commit];[second commit];take(entered);take(entered);
  assert(__atomic_load_n(&submitted,__ATOMIC_ACQUIRE)==2);
  assert(first.status==RW_CB_SCHEDULED&&second.status==RW_CB_SCHEDULED&&first->_testResourceActive&&second->_testResourceActive&&!visible);
  dispatch_semaphore_signal(run_callback);dispatch_semaphore_signal(release_fence);dispatch_semaphore_signal(release_fence);
  [second waitUntilCompleted];[first waitUntilCompleted];take(callback_done);take(entered);
  assert(first->_redfinFinalized&&second->_redfinFinalized);[first release];[second release];dispatch_release(run_callback);dispatch_release(callback_done);
  dealloc_done=dispatch_semaphore_create(0);
  TestCommand *released=[TestCommand new];released->_testDealloc=YES;[released commit];[released release];take(entered);
  dispatch_semaphore_signal(release_fence);take(dealloc_done);take(entered);dispatch_release(dealloc_done);
  for(unsigned trial=0;trial<2;++trial){
   fail_begin=trial==0;fail_mark=trial==1;TestCommand *refused=[TestCommand new];[refused commit];[refused waitUntilScheduled];[refused waitUntilCompleted];
   assert(refused->_redfinFinalized&&refused.status==RW_CB_ERROR&&!refused->_testResourceActive&&!refused->_redfinScheduled);[refused release];
  }
  fail_begin=0;fail_mark=0;TestCommand *uncommitted=[TestCommand new];[uncommitted waitUntilScheduled];[uncommitted waitUntilCompleted];assert(uncommitted.status==1);[uncommitted release];
  uint64_t counts[REDFIN_METAL_SCHEDULING_WORDS];redfin_scheduling_read(counts);
  assert(counts[RF_MS_PUBLICATIONS]>=6&&counts[RF_MS_EARLY_RETURNS]>=2&&counts[RF_MS_SCHEDULED_BLOCKS]>=3&&counts[RF_MS_COMPLETED_BLOCKS]>=3);
  dispatch_sync(callbacks_queue,^{});dispatch_release(callbacks_queue);
  dispatch_release(entered);dispatch_release(release_fence);dispatch_release(publish_entered);dispatch_release(release_publish);
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'status.m').write_text(source)
            built=subprocess.run(['cc','-std=gnu11','-O2','-fblocks','-pthread','-Wall','-Wextra','-Werror',
                '-I'+str(ROOT/'ports/redfin'),str(root/'status.m'),'-framework','Foundation','-o',str(root/'status')],capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr.decode(errors='replace'))
            result=subprocess.run([str(root/'status')],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))


if __name__=='__main__':unittest.main()
