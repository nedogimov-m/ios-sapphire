/* SPDX-License-Identifier: MIT */
/* Native MobileWiFi password persistence and bounded network readiness.
 * The private API/probe model is HackiOS userland906425b wifipw_test.c.
 * Only a synthetic unjoined network marker is accessed. Real network names,
 * passwords, addresses, cookies and account credentials are never logged. */
#import <Foundation/Foundation.h>
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <mach/mach_time.h>
#include <sys/sysctl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "gui-profile.h"

static uint64_t now_ms(void)
{
    mach_timebase_info_data_t scale={};mach_timebase_info(&scale);
    uint64_t ticks=mach_absolute_time();
    return scale.denom ? (ticks/scale.denom*scale.numer+(ticks%scale.denom)*scale.numer/scale.denom)/1000000 : 0;
}
static void password_probe(const char *nonce)
{
    void *library=dlopen("/System/Library/PrivateFrameworks/MobileWiFi.framework/MobileWiFi",RTLD_NOW|RTLD_LOCAL);
    CFStringRef (*copy)(CFStringRef)=library ? (CFStringRef (*)(CFStringRef))dlsym(library,"WiFiSecurityCopyPassword") : NULL;
    Boolean (*set)(CFStringRef,CFStringRef)=library ? (Boolean (*)(CFStringRef,CFStringRef))dlsym(library,"WiFiSecuritySetPassword") : NULL;
    if (!copy || !set) {printf("REDFIN WIFI PASSWORD: boot=%s native-API=0\n",nonce);return;}
    CFStringRef network=CFSTR("redfin-native-persistence-probe-unjoined-v1");
    CFStringRef marker=CFSTR("Redfin synthetic MobileWiFi persistence marker v1.");
    CFStringRef value=copy(network);
    BOOL existing=value && CFGetTypeID(value)==CFStringGetTypeID() && CFEqual(value,marker);
    if (value) CFRelease(value);
    Boolean written=existing ? true : set(network,marker);
    value=copy(network);
    BOOL exact=value && CFGetTypeID(value)==CFStringGetTypeID() && CFEqual(value,marker);
    if (value) CFRelease(value);
    printf("REDFIN WIFI PASSWORD: boot=%s native-API=1 existing=%u write-accepted=%u exact=%u synthetic-unjoined=1\n",nonce,existing,written,exact);
}
static unsigned interface_state(void)
{
    struct ifaddrs *list=NULL;if (getifaddrs(&list)) return 0;
    unsigned state=0;
    for (struct ifaddrs *p=list;p;p=p->ifa_next) {
        if (!p->ifa_name || strcmp(p->ifa_name,"en0")) continue;
        state|=1;
        if ((p->ifa_flags&(IFF_UP|IFF_RUNNING))==(IFF_UP|IFF_RUNNING)) state|=2;
        if (p->ifa_addr && p->ifa_addr->sa_family==AF_INET) {
            uint32_t address=ntohl(((struct sockaddr_in *)p->ifa_addr)->sin_addr.s_addr);
            if (address && address!=UINT32_MAX && (address>>16)!=0xa9fe && (address>>24)!=127) state|=4;
        }
    }
    freeifaddrs(list);return state;
}
static void https_check(const char *nonce)
{
    NSURLSessionConfiguration *configuration=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.timeoutIntervalForRequest=12;configuration.timeoutIntervalForResource=15;
    configuration.URLCache=nil;configuration.HTTPCookieStorage=nil;
    configuration.HTTPShouldSetCookies=NO;
    NSURLSession *session=[NSURLSession sessionWithConfiguration:configuration];
    __block BOOL finished=NO;
    __block NSInteger status=0,error_code=0;
    __block NSString *domain=nil;
    __block NSUInteger bytes=0;
    NSURL *url=[NSURL URLWithString:@"https://captive.apple.com/hotspot-detect.html"];
    NSURLSessionDataTask *task=[session dataTaskWithURL:url completionHandler:^(NSData *data,NSURLResponse *response,NSError *error) {
        if ([response isKindOfClass:NSHTTPURLResponse.class]) status=((NSHTTPURLResponse *)response).statusCode;
        error_code=error.code;domain=error.domain;bytes=data.length;
        __atomic_store_n(&finished,YES,__ATOMIC_RELEASE);
    }];
    [task resume];uint64_t start=now_ms();
    while (!__atomic_load_n(&finished,__ATOMIC_ACQUIRE) && now_ms()-start<16000)
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    BOOL complete=__atomic_load_n(&finished,__ATOMIC_ACQUIRE);
    printf("REDFIN WIFI HTTPS: boot=%s completed=%u status=%ld bytes=%lu error-domain=%s error-code=%ld native-trust=1\n",
        nonce,complete,complete ? (long)status : 0,complete ? (unsigned long)bytes : 0,
        complete && domain ? domain.UTF8String : "none",complete ? (long)error_code : 0);
    [session invalidateAndCancel];
}
int main(void)
{
    setvbuf(stdout,NULL,_IOLBF,0);setvbuf(stderr,NULL,_IOLBF,0);
    char args[608]={},nonce[17]={};size_t bytes=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || bytes>sizeof(args) ||
        !redfin_gpu_gui_profile(args,(unsigned)bytes,NULL)) return 0;
    const char *at=strstr(args,"redfinbootid=0x");if (!at || strlen(at+15)<16) return 2;
    memcpy(nonce,at+15,16);
    @autoreleasepool {
        printf("REDFIN WIFI CHECK: boot=%s started-at-ms=%llu\n",nonce,(unsigned long long)now_ms());
        password_probe(nonce);
        unsigned previous=UINT32_MAX;uint64_t start=now_ms();BOOL online=NO;
        while (now_ms()-start<115000) {
            unsigned state=interface_state();
            if (state!=previous) {
                printf("REDFIN WIFI READY: boot=%s boot-ms=%llu interface=%u running=%u ipv4=%u\n",
                    nonce,(unsigned long long)now_ms(),(state&1)!=0,(state&2)!=0,(state&4)!=0);previous=state;
            }
            if ((state&7)==7) {online=YES;https_check(nonce);break;}
            usleep(250000);
        }
        printf("REDFIN WIFI CHECK RESULT: boot=%s online=%u boot-ms=%llu\n",nonce,online,(unsigned long long)now_ms());
    }
    return 0;
}
