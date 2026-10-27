/* SPDX-License-Identifier: MIT */
/* Borrow one finite SpringBoard idle assertion. Never replace an existing
 * client's assertion or alter passcode, wake, lock or persistent idle policy. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <stdlib.h>
#include "native-image-uuid.h"
#include "idle-system.h"

static id idle_assertion;
static Method idle_method(Class cls,const char *name,const char *types,BOOL meta,const uint8_t uuid[16])
{
    Method method=meta?class_getClassMethod(cls,sel_registerName(name)):class_getInstanceMethod(cls,sel_registerName(name));
    return method&&!strcmp(method_getTypeEncoding(method),types)&&
        redfin_native_image_uuid((const void *)method_getImplementation(method),uuid)?method:NULL;
}
bool redfin_idle_system_begin(uint64_t nonce)
{
    const char *process=getprogname();
    if(!nonce||idle_assertion||!NSThread.isMainThread||!process||strcmp(process,"SpringBoard"))return false;
    const uint8_t springboard[16]={REDFIN_SB_UUID_BYTES},baseboard[16]={REDFIN_BB_UUID_BYTES};
    Class coordinator_class=objc_getClass("SBIdleTimerGlobalCoordinator"),assertion_class=objc_getClass("BSSimpleAssertion");
    if(!coordinator_class||!assertion_class||
       !idle_method(coordinator_class,"sharedInstanceIfExists","@16@0:8",YES,springboard)||
       !idle_method(coordinator_class,"acquireIdleTimerDisableAssertionForReason:","@24@0:8@16",NO,springboard)||
       !idle_method(coordinator_class,"isIdleTimerDisabled","B16@0:8",NO,springboard)||
       !idle_method(assertion_class,"isValid","B16@0:8",NO,baseboard)||
       !idle_method(assertion_class,"invalidate","v16@0:8",NO,baseboard))return false;
    id coordinator=((id (*)(id,SEL))objc_msgSend)(coordinator_class,sel_registerName("sharedInstanceIfExists"));
    if(!coordinator)return false;
    NSString *reason=[NSString stringWithFormat:@"com.redfin.finite-display-probe.%016llx",(unsigned long long)nonce];
    id assertion=((id (*)(id,SEL,id))objc_msgSend)(coordinator,
        sel_registerName("acquireIdleTimerDisableAssertionForReason:"),reason);
    if(!assertion)return false;
    idle_assertion=assertion;
    BOOL valid=[assertion isKindOfClass:assertion_class]&&
        ((BOOL (*)(id,SEL))objc_msgSend)(assertion,sel_registerName("isValid"))&&
        ((BOOL (*)(id,SEL))objc_msgSend)(coordinator,sel_registerName("isIdleTimerDisabled"));
    if(!valid){(void)redfin_idle_system_end();return false;}
    return true;
}
bool redfin_idle_system_end(void)
{
    if(!NSThread.isMainThread)return false;
    id assertion=idle_assertion;if(!assertion)return true;
    ((void (*)(id,SEL))objc_msgSend)(assertion,sel_registerName("invalidate"));
    BOOL released=!((BOOL (*)(id,SEL))objc_msgSend)(assertion,sel_registerName("isValid"));
    if(released)idle_assertion=nil;return released;
}
