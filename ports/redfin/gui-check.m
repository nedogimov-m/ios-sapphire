/* SPDX-License-Identifier: MIT */
/* Opt-in native application smoke run for unattended capture boots. It only
 * opens Phone/Photos; it never places a call, sends a message or signs in. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <dlfcn.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "gui-profile.h"

static pid_t process(const char *name)
{
    int mib[]={CTL_KERN,KERN_PROC,KERN_PROC_ALL,0}; size_t bytes=0;
    if (sysctl(mib,4,NULL,&bytes,NULL,0) || !bytes || bytes>2*1024*1024) return -1;
    size_t capacity=bytes+65536; struct kinfo_proc *list=calloc(1,capacity);
    if (!list) return -1;
    bytes=capacity;
    if (sysctl(mib,4,list,&bytes,NULL,0) || bytes%sizeof(*list)) {free(list);return -1;}
    pid_t found=0;
    for (size_t i=0;i<bytes/sizeof(*list);++i)
        if (!strncmp(list[i].kp_proc.p_comm,name,sizeof(list[i].kp_proc.p_comm))) {
            found=list[i].kp_proc.p_pid; break;
        }
    free(list);return found;
}
static BOOL abi(Class cls,const char *selector,const char *types,BOOL meta)
{
    Method method=meta ? class_getClassMethod(cls,sel_registerName(selector)) :
        class_getInstanceMethod(cls,sel_registerName(selector));
    return method && !strcmp(method_getTypeEncoding(method),types);
}
int main(void)
{
    setvbuf(stdout,NULL,_IOLBF,0);setvbuf(stderr,NULL,_IOLBF,0);
    char args[1024]={0},nonce[17]={0};size_t bytes=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || !bytes || bytes>sizeof(args) ||
        !redfin_gpu_gui_profile(args,(unsigned)bytes,NULL)) return 0;
    BOOL capture=NO;
    for (unsigned at=0;at<bytes && args[at];) {
        if (args[at]==' ') {++at;continue;}
        unsigned start=at;while (at<bytes && args[at] && args[at]!=' ') ++at;
        if (redfin_gui_token(args+start,at-start,"redfinscreen=1")) capture=YES;
    }
    if (!capture || getuid()!=501) return 0;
    const char *boot=strstr(args,"redfinbootid=0x");
    if (!boot || strlen(boot+15)<16) return 2;
    memcpy(nonce,boot+15,16);
    @autoreleasepool {
        dlopen("/System/Library/Frameworks/CoreServices.framework/CoreServices",RTLD_NOW|RTLD_LOCAL);
        Class cls=objc_getClass("LSApplicationWorkspace");
        if (!abi(cls,"defaultWorkspace","@16@0:8",YES) ||
            !abi(cls,"openApplicationWithBundleID:","B24@0:8@16",NO)) {
            printf("REDFIN GUI CHECK: boot=%s refused native LS ABI differs\n",nonce);return 3;
        }
        printf("REDFIN GUI CHECK: boot=%s opt-in=1 mobile=1 preparing native Phone/Photos opens\n",nonce);
        sleep(65);
        pid_t spring=process("SpringBoard");
        if (spring<=0) {printf("REDFIN GUI CHECK: boot=%s SpringBoard-not-ready pid=%d\n",nonce,spring);return 4;}
        id workspace=((id (*)(id,SEL))objc_msgSend)(cls,sel_registerName("defaultWorkspace"));
        NSArray *bundles=@[@"com.apple.mobilephone",@"com.apple.mobileslideshow"];
        const char *names[]={"MobilePhone","MobileSlideShow"};
        for (unsigned i=0;i<bundles.count;++i) {
            @try {
                BOOL opened=((BOOL (*)(id,SEL,id))objc_msgSend)(workspace,
                    sel_registerName("openApplicationWithBundleID:"),bundles[i]);
                printf("REDFIN GUI CHECK OPEN: boot=%s bundle=%s accepted=%u spring-before=%d\n",
                    nonce,[bundles[i] UTF8String],opened,process("SpringBoard"));
                sleep(5);pid_t early=process(names[i]);sleep(12);pid_t late=process(names[i]),current=process("SpringBoard");
                printf("REDFIN GUI CHECK RESULT: boot=%s bundle=%s pid-5s=%d pid-17s=%d survived=%u spring-stable=%u spring=%d\n",
                    nonce,[bundles[i] UTF8String],early,late,early>0 && early==late,current==spring,current);
            } @catch (NSException *exception) {
                printf("REDFIN GUI CHECK EXCEPTION: boot=%s bundle=%s name=%s\n",nonce,
                    [bundles[i] UTF8String],exception.name.UTF8String);
            }
        }
    }
    return 0;
}
