/* SPDX-License-Identifier: MIT */
/* Read-only, capture-only native Photos exception and authorization evidence.
 * The runtime receives the same exception and its prior preprocessor remains
 * in the chain. No TCC answer, database, entitlement or exception is replaced. */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <execinfo.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include "gui-profile.h"
#include "graphics-exec-scope.h"

static char diagnostic_nonce[17];
static const char *diagnostic_process;
static bool diagnostic_photos;
static id (*prior_exception)(id);
static __thread bool recording;
static unsigned exceptions;

static void diagnostic_log(const char *format,...)
{
    char line[1536];
    int prefix=snprintf(line,sizeof(line),"REDFIN NATIVE OBSERVATION: boot=%s pid=%d process=%s ",
        diagnostic_nonce,getpid(),diagnostic_process);
    if (prefix<0 || (size_t)prefix>=sizeof(line)) return;
    va_list args;va_start(args,format);
    int bytes=vsnprintf(line+prefix,sizeof(line)-(size_t)prefix,format,args);va_end(args);
    if (bytes<0) return;
    size_t length=strnlen(line,sizeof(line)-2);line[length++]='\n';
    (void)write(STDERR_FILENO,line,length);
    int fd=open("/private/var/mobile/Library/Logs/redfin-ui.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if (fd>=0) {(void)write(fd,line,length);close(fd);}
}

static id observe_exception(id exception)
{
    if (!recording && __atomic_fetch_add(&exceptions,1,__ATOMIC_RELAXED)<24) {
        recording=true;
        @try {
            if ([exception isKindOfClass:NSException.class]) {
                NSException *native=exception;
                diagnostic_log("exception=%s reason=%.768s original-continued=1",
                    native.name.UTF8String,native.reason.UTF8String ?: "(none)");
                void *frames[16];int count=backtrace(frames,16);
                for (int i=0;i<count;++i) diagnostic_log("exception-frame=%d address=%p",i,frames[i]);
            }
        } @catch (__unused id logging_error) {
            diagnostic_log("exception-description-unavailable original-continued=1");
        }
        recording=false;
    }
    return prior_exception ? prior_exception(exception) : exception;
}

static void observe_authorization(void)
{
    void *security=dlopen("/System/Library/Frameworks/Security.framework/Security",RTLD_NOW|RTLD_LOCAL);
    CFTypeRef (*create)(CFAllocatorRef)=security ? (CFTypeRef (*)(CFAllocatorRef))dlsym(security,"SecTaskCreateFromSelf") : NULL;
    uint32_t (*flags)(CFTypeRef)=security ? (uint32_t (*)(CFTypeRef))dlsym(security,"SecTaskGetCodeSignStatus") : NULL;
    Boolean (*validated)(CFTypeRef)=security ? (Boolean (*)(CFTypeRef))dlsym(security,"SecTaskEntitlementsValidated") : NULL;
    CFTypeRef (*entitlement)(CFTypeRef,CFStringRef,CFErrorRef *)=security ?
        (CFTypeRef (*)(CFTypeRef,CFStringRef,CFErrorRef *))dlsym(security,"SecTaskCopyValueForEntitlement") : NULL;
    CFTypeRef task=create ? create(kCFAllocatorDefault) : NULL;
    CFErrorRef error=NULL;
    CFTypeRef allowed=task && entitlement ? entitlement(task,CFSTR("com.apple.private.tcc.allow"),&error) : NULL;
    bool photos=allowed && CFGetTypeID(allowed)==CFArrayGetTypeID() &&
        CFArrayContainsValue((CFArrayRef)allowed,CFRangeMake(0,CFArrayGetCount((CFArrayRef)allowed)),CFSTR("kTCCServicePhotos"));
    diagnostic_log("self-SecTask=%u flags=%#x validated=%d photos-entitlement=%u entitlement-error=%ld",
        task!=NULL,task && flags ? flags(task) : 0,task && validated ? validated(task) : -1,
        photos,error ? (long)CFErrorGetCode(error) : 0);
    if (error) CFRelease(error);
    if (allowed) CFRelease(allowed);
    if (task) CFRelease(task);
    void *tcc=dlopen("/System/Library/PrivateFrameworks/TCC.framework/TCC",RTLD_NOW|RTLD_LOCAL);
    long (*preflight)(CFStringRef)=tcc ? (long (*)(CFStringRef))dlsym(tcc,"tcc_authorization_preflight") : NULL;
    diagnostic_log("self-native-TCC-preflight=%ld",preflight ? preflight(CFSTR("kTCCServicePhotos")) : -1);
}

__attribute__((constructor)) static void install_native_observation(void)
{
    char args[1024]={0},path[1024]={0};size_t bytes=sizeof(args);uint32_t path_bytes=sizeof(path);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || !bytes || bytes>sizeof(args) ||
        !redfin_diagnostic_requested(args,(unsigned)bytes) || _NSGetExecutablePath(path,&path_bytes)) return;
    if (redfin_diagnostic_executable(path)) {diagnostic_process="assetsd";diagnostic_photos=true;}
    else if (!strcmp(path,"/Applications/MobileSlideShow.app/MobileSlideShow")) {diagnostic_process="Photos";diagnostic_photos=true;}
    else if (!strcmp(path,"/System/Library/CoreServices/SpringBoard.app/SpringBoard")) diagnostic_process="SpringBoard";
    else if (!strcmp(path,"/Applications/MobilePhone.app/MobilePhone")) diagnostic_process="Phone";
    else if (!strcmp(path,"/Applications/Preferences.app/Preferences")) diagnostic_process="Preferences";
    else if (!strcmp(path,"/Applications/AppStore.app/AppStore")) diagnostic_process="AppStore";
    else return;
    const char *nonce=strstr(args,"redfinbootid=0x");
    if (!nonce || strlen(nonce+15)<16) return;
    memcpy(diagnostic_nonce,nonce+15,16);
    id (*(*set_preprocessor)(id (*)(id)))(id)=
        (id (*(*)(id (*)(id)))(id))dlsym(RTLD_DEFAULT,"objc_setExceptionPreprocessor");
    if (!set_preprocessor) return;
    prior_exception=set_preprocessor(observe_exception);
    diagnostic_log("exception-observer-installed native-semantics-preserved=1");
    if (diagnostic_photos)
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC),dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
            @autoreleasepool {observe_authorization();}
        });
}
