/* SPDX-License-Identifier: MIT */
- (BOOL)redfinWillSubmit
{
    @synchronized(self) {
        if(!_redfinActive)_redfinActive=dispatch_group_create();
        if(!_redfinActive)return NO;
        dispatch_group_enter(_redfinActive);return YES;
    }
}
- (void)redfinDidFinish
{
    @synchronized(self) {dispatch_group_leave(_redfinActive);}
}
- (BOOL)isComplete
{
    @synchronized(self) {return !_redfinActive||dispatch_group_wait(_redfinActive,DISPATCH_TIME_NOW)==0;}
}
- (void)waitUntilComplete
{
    dispatch_group_t active=NULL;
    @synchronized(self) {active=_redfinActive;if(active)dispatch_retain(active);}
    if(active){dispatch_group_wait(active,DISPATCH_TIME_FOREVER);dispatch_release(active);}
}
