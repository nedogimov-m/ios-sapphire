"""The real asynchronous resource gate must block reuse through every submission."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin import metal_userland
from ports.redfin.test_metal_scheduled import method

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class MetalCompletionTests(unittest.TestCase):
    def test_actual_resource_and_command_methods_keep_overlapping_users_and_waiters(self):
        upstream=ROOT/'research/hackios-upstream/userland/userland/src/redwoodmetal.m'
        adapted=metal_userland.adapt_driver(upstream.read_text())
        commands='\n'.join(method(adapted,name) for name in ('- (BOOL)redfinMarkResources','- (void)redfinFinishResources'))
        resource=(HERE/'metal-resource-completion.inc').read_text()
        source=r'''
#import <Foundation/Foundation.h>
#include <assert.h>
@interface RedwoodMetalBuffer:NSObject {dispatch_group_t _redfinActive;}
- (BOOL)redfinWillSubmit;
- (void)redfinDidFinish;
- (BOOL)isComplete;
- (void)waitUntilComplete;
@end
@implementation RedwoodMetalBuffer
'''+resource+r'''
- (void)dealloc{assert([self isComplete]);if(_redfinActive)dispatch_release(_redfinActive);[super dealloc];}
@end
@interface RedwoodMetalTexture:RedwoodMetalBuffer
@end
@implementation RedwoodMetalTexture
@end
@interface Command:NSObject {NSMutableArray *_redfinResources,*_redfinInFlightResources;}
- (instancetype)initWithResources:(NSArray *)resources;
- (BOOL)redfinMarkResources;
- (void)redfinFinishResources;
@end
@implementation Command
- (instancetype)initWithResources:(NSArray *)resources{if((self=[super init]))_redfinResources=[resources mutableCopy];return self;}
- (void)dealloc{[_redfinResources release];[_redfinInFlightResources release];[super dealloc];}
'''+commands+r'''
@end
int main(void){@autoreleasepool{
 RedwoodMetalBuffer *buffer=[RedwoodMetalBuffer new];RedwoodMetalTexture *texture=[RedwoodMetalTexture new];
 Command *first=[[Command alloc] initWithResources:@[buffer,texture,buffer,texture,@1]];
 Command *second=[[Command alloc] initWithResources:@[texture,texture]];
 assert(buffer.isComplete&&texture.isComplete);assert([first redfinMarkResources]);assert([second redfinMarkResources]);
 assert(!buffer.isComplete&&!texture.isComplete);
 dispatch_group_t bufferWait=dispatch_group_create(),textureWait=dispatch_group_create();
 dispatch_semaphore_t entered=dispatch_semaphore_create(0);
 dispatch_group_async(bufferWait,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{dispatch_semaphore_signal(entered);[buffer waitUntilComplete];});
 dispatch_group_async(textureWait,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{dispatch_semaphore_signal(entered);[texture waitUntilComplete];});
 for(unsigned i=0;i<2;++i)assert(!dispatch_semaphore_wait(entered,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 assert(dispatch_group_wait(bufferWait,dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_MSEC))!=0);
 assert(dispatch_group_wait(textureWait,dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_MSEC))!=0);
 [first redfinFinishResources];assert(buffer.isComplete&&!texture.isComplete);
 assert(!dispatch_group_wait(bufferWait,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 assert(dispatch_group_wait(textureWait,dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_MSEC))!=0);
 [second redfinFinishResources];assert(texture.isComplete);
 assert(!dispatch_group_wait(textureWait,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
 [second redfinFinishResources]; /* emptied finish list cannot double-leave */
 dispatch_release(entered);dispatch_release(bufferWait);dispatch_release(textureWait);
 [first release];[second release];[buffer release];[texture release];
}return 0;}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'gate.m').write_text(source)
            built=subprocess.run(['cc','-std=gnu11','-O2','-fblocks','-pthread','-Wall','-Wextra','-Werror',
                str(root/'gate.m'),'-framework','Foundation','-o',str(root/'gate')],capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr.decode(errors='replace'))
            ran=subprocess.run([str(root/'gate')],capture_output=True,timeout=15)
            self.assertEqual(ran.returncode,0,ran.stderr.decode(errors='replace'))


if __name__=='__main__':unittest.main()
