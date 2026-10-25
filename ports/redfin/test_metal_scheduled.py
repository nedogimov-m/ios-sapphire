"""Real adapted ObjC command status/waiters must cover an outstanding native fence."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from ports.redfin import metal_userland

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
    def test_native_status_and_wait_until_scheduled_do_not_outrun_the_real_end_fence(self):
        upstream=ROOT/'research/hackios-upstream/userland/userland/src/redwoodmetal.m'
        native=metal_userland.adapt_driver(upstream.read_text())
        execute=method(native,'- (void)redfinExecute')
        at=execute.index('\tfor (RedwoodMetalWork *work in _work) {');brace=execute.index('{',at)
        # Replace only encoding with an empty workload. Keep the actual status
        # stores, real-end call, error cleanup and waiter methods unchanged.
        execute=execute[:at]+'\tif(_status==0)goto done;\n'+execute[block_end(execute,brace):]
        methods='\n'.join([method(native,'- (void)commit'),execute,
            method(native,'- (void)waitUntilCompleted'),
            re.search(r'^- \(void\)waitUntilScheduled \{[^\n]*\}',native,re.M).group(),
            method(native,'- (void)failWith:(const char *)reason')])
        source=r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#include <stdint.h>
#include <mach/mach_time.h>
#include "metal-ordering.h"
enum {RW_CB_COMMITTED=2,RW_CB_SCHEDULED=3,RW_CB_COMPLETED=4,RW_CB_ERROR=5};
static dispatch_semaphore_t entered,release_fence;
static unsigned fail_fence,fail_begin,visible;
static int begin(void *d,char *why,size_t n){(void)d;if(fail_begin){snprintf(why,n,"native begin refusal");return -7;}return 0;}
static int end(void *d,char *why,size_t n){
 (void)d;dispatch_semaphore_signal(entered);
 assert(!dispatch_semaphore_wait(release_fence,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 if(fail_fence){snprintf(why,n,"actual native fence failure");return -7;}
 visible=42;return 0;
}
static int statistics(void *d,uint64_t *counts,size_t n){(void)d;memset(counts,0,n*8);return 0;}
static struct {int (*commands_begin)(void *,char *,size_t);int (*commands_end)(void *,char *,size_t);
 int (*submission_statistics)(void *,uint64_t *,size_t);
 int (*ordering_statistics)(void *,uint64_t *,size_t);} mesa={begin,end,statistics,statistics};
static const char redfin_fence_boot[]="host-fence-fixture";
static void rw_print(const char *format,...){(void)format;}
static void redfin_metal_completed(unsigned a,unsigned b,uint64_t c,uint64_t d,uint64_t e,uint64_t f,uint64_t g)
 {(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;}
static void redfin_metal_io_completed(const uint64_t *a,const uint64_t *b){(void)a;(void)b;}
'''+metal_userland.LOCKING+metal_userland.EXECUTION+r'''
@interface TestDevice : NSObject
- (void *)mesaDevice;
@end
@implementation TestDevice
- (void *)mesaDevice{return (void *)1;}
@end
@interface TestQueue : NSObject
- (TestDevice *)device;
@end
@implementation TestQueue
- (TestDevice *)device {static TestDevice *device;static dispatch_once_t once;dispatch_once(&once,^{device=[TestDevice new];});return device;}
@end
@interface RedwoodMetalWork : NSObject { @public id render;BOOL redfinClearOnly;struct {unsigned operation;} redfinBlit; }
@end
@implementation RedwoodMetalWork
@end
@interface TestCommand : NSObject {
 @public _Atomic(NSUInteger) _status;_Atomic(BOOL) _redfinFinalized;
 dispatch_group_t _redfinExecution;uint64_t _redfinQueuedTicks;
 TestQueue *_queue;NSMutableArray *_work;NSError *_error;
 BOOL _testResourceActive;
}
- (void)commit;
- (void)redfinExecute;
- (void)waitUntilCompleted;
- (void)waitUntilScheduled;
- (void)failWith:(const char *)reason;
- (void)redwoodReturnSlot;
- (void)redwoodDeliverHandlers;
- (BOOL)redfinMarkResources;
- (void)redfinFinishResources;
@end
@implementation TestCommand
- (instancetype)init {
 if((self=[super init])){_queue=[TestQueue new];_work=[NSMutableArray new];_status=1;_redfinExecution=dispatch_group_create();}return self;
}
- (void)dealloc {[_queue release];[_work release];[_error release];dispatch_release(_redfinExecution);[super dealloc];}
- (void)redwoodReturnSlot {assert(_redfinFinalized&&!_testResourceActive);}
- (void)redwoodDeliverHandlers {assert(_redfinFinalized);}
- (BOOL)redfinMarkResources {assert(!_testResourceActive);_testResourceActive=YES;return YES;}
- (void)redfinFinishResources {assert(_testResourceActive);_testResourceActive=NO;}
'''+methods+r'''
@end
int main(void) {
 @autoreleasepool {
  entered=dispatch_semaphore_create(0);release_fence=dispatch_semaphore_create(0);
  for(unsigned trial=0;trial<2;++trial) {
   fail_fence=trial;visible=0;TestCommand *command=[TestCommand new];[command commit];
   assert(!dispatch_semaphore_wait(entered,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
   assert(command->_status==RW_CB_COMMITTED && !command->_redfinFinalized && command->_testResourceActive && !visible);
   dispatch_group_t waiter=dispatch_group_create();
   dispatch_group_async(waiter,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{[command waitUntilScheduled];});
   assert(dispatch_group_wait(waiter,dispatch_time(DISPATCH_TIME_NOW,50*NSEC_PER_MSEC))!=0);
   dispatch_semaphore_signal(release_fence);
   assert(!dispatch_group_wait(waiter,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
   [command waitUntilCompleted];
   assert(command->_redfinFinalized && !command->_testResourceActive && command->_status==(trial?RW_CB_ERROR:RW_CB_COMPLETED));
   assert(trial?!visible:visible==42);
   dispatch_release(waiter);[command release];
  }
  fail_begin=1;TestCommand *refused=[TestCommand new];[refused commit];[refused waitUntilCompleted];
  assert(refused->_redfinFinalized&&refused->_status==RW_CB_ERROR&&!refused->_testResourceActive);[refused release];
  dispatch_release(entered);dispatch_release(release_fence);
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'status.m').write_text(source)
            built=subprocess.run(['cc','-std=gnu11','-O2','-fblocks','-pthread','-Wall','-Wextra','-Werror',
                '-I'+str(ROOT/'ports/redfin'),
                str(root/'status.m'),'-framework','Foundation','-o',str(root/'status')],capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr.decode(errors='replace'))
            result=subprocess.run([str(root/'status')],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))


if __name__=='__main__':unittest.main()
