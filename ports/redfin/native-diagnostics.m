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
#include <mach/mach.h>
#include <mach/task_info.h>
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
static void observe_authorization(bool query_tcc);

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
                /* A service can throw before its background observer runs.
                 * Capture its real audit-token/Security answers at that point;
                 * do not make another TCC request on the throwing thread. */
                if (diagnostic_photos) observe_authorization(false);
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

static void observe_authorization(bool query_tcc)
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
    /* TCCD uses the audit-token constructor and batched entitlement API.
     * Observe that exact native path as well as CreateFromSelf above. */
    audit_token_t audit={0};mach_msg_type_number_t count=TASK_AUDIT_TOKEN_COUNT;
    kern_return_t audit_status=task_info(mach_task_self(),TASK_AUDIT_TOKEN,(task_info_t)&audit,&count);
    CFTypeRef (*from_audit)(CFAllocatorRef,audit_token_t)=security ?
        (CFTypeRef (*)(CFAllocatorRef,audit_token_t))dlsym(security,"SecTaskCreateWithAuditToken") : NULL;
    CFDictionaryRef (*values)(CFTypeRef,CFArrayRef,CFErrorRef *)=security ?
        (CFDictionaryRef (*)(CFTypeRef,CFArrayRef,CFErrorRef *))dlsym(security,"SecTaskCopyValuesForEntitlements") : NULL;
    CFTypeRef remote=audit_status==KERN_SUCCESS && count==TASK_AUDIT_TOKEN_COUNT && from_audit ? from_audit(NULL,audit) : NULL;
    const void *key=CFSTR("com.apple.private.tcc.allow");
    CFArrayRef keys=CFArrayCreate(NULL,&key,1,&kCFTypeArrayCallBacks);error=NULL;
    CFDictionaryRef entries=remote && values && keys ? values(remote,keys,&error) : NULL;
    CFTypeRef list=entries ? CFDictionaryGetValue(entries,key) : NULL;
    bool remote_photos=list && CFGetTypeID(list)==CFArrayGetTypeID() &&
        CFArrayContainsValue((CFArrayRef)list,CFRangeMake(0,CFArrayGetCount((CFArrayRef)list)),CFSTR("kTCCServicePhotos"));
    diagnostic_log("audit-SecTask=%u task-info=%#x own-pid=%u flags=%#x validated=%d batched-photos-entitlement=%u error=%ld",
        remote!=NULL,audit_status,audit.val[5]==(unsigned)getpid(),remote && flags ? flags(remote) : 0,
        remote && validated ? validated(remote) : -1,remote_photos,error ? (long)CFErrorGetCode(error) : 0);
    if (error) CFRelease(error);
    if (entries) CFRelease(entries);
    if (keys) CFRelease(keys);
    if (remote) CFRelease(remote);
    if (!query_tcc) return;
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
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
            @autoreleasepool {observe_authorization(true);}
        });
}
