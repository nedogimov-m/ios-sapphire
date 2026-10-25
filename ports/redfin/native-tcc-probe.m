/* SPDX-License-Identifier: MIT */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "native-tcc-probe.h"

static bool native_framework(void *function)
{
    static const uint8_t uuid[16]={0x92,0xc9,0x86,0x5c,0x75,0xe5,0x31,0xcf,
        0xaa,0xdc,0x1c,0x3a,0x68,0x13,0x51,0x3e};
    Dl_info image={0};if(!dladdr(function,&image)||!image.dli_fbase)return false;
    const struct mach_header_64 *header=image.dli_fbase;
    if(header->magic!=MH_MAGIC_64||header->ncmds>1024||header->sizeofcmds>1048576)return false;
    const uint8_t *at=(const uint8_t *)(header+1),*end=at+header->sizeofcmds;
    for(unsigned i=0;i<header->ncmds;++i) {
        if((size_t)(end-at)<sizeof(struct load_command))return false;
        const struct load_command *command=(const struct load_command *)at;
        if(command->cmdsize<sizeof(*command)||command->cmdsize>(size_t)(end-at))return false;
        if(command->cmd==LC_UUID)return command->cmdsize==sizeof(struct uuid_command)&&
            !memcmp(((const struct uuid_command *)command)->uuid,uuid,sizeof(uuid));
        at+=command->cmdsize;
    }
    return false;
}
void redfin_native_tcc_probe(void (*report)(const char *,void *),void *context)
{
    static bool attempted;
    if(!report||__atomic_exchange_n(&attempted,true,__ATOMIC_RELAXED))return;
    void *library=dlopen("/System/Library/PrivateFrameworks/TCC.framework/TCC",RTLD_NOW|RTLD_LOCAL);
    if(!library)return;
    void *(*service)(CFStringRef)=(void *(*)(CFStringRef))dlsym(library,"tcc_service_singleton_for_CF_name");
    void *(*credential)(void)=(void *(*)(void))dlsym(library,"tcc_credential_singleton_for_self");
    void *(*server)(void)=(void *(*)(void))dlsym(library,"tcc_server_singleton_default");
    void *(*options_create)(void)=(void *(*)(void))dlsym(library,"tcc_message_options_create");
    void (*reply_policy)(void *,unsigned)=(void (*)(void *,unsigned))dlsym(library,"tcc_message_options_set_reply_handler_policy");
    void (*prompt_policy)(void *,unsigned)=(void (*)(void *,unsigned))dlsym(library,"tcc_message_options_set_request_prompt_policy");
    uint64_t (*right)(void *)=(uint64_t (*)(void *))dlsym(library,"tcc_authorization_record_get_authorization_right");
    void (*release)(void *)=(void (*)(void *))dlsym(library,"tcc_release");
    void (*request)(void *,void *,void *,void *,void *,void (^)(void *,void *))=
        (void (*)(void *,void *,void *,void *,void *,void (^)(void *,void *)))
        dlsym(library,"tcc_server_message_request_authorization");
    if(!service||!credential||!server||!options_create||!reply_policy||!prompt_policy||!right||!release||
        !request||!native_framework((void *)request)) {
        report("native-authorization-probe refused native API/UUID differs",context);return;
    }
    void *native_service=service(CFSTR("kTCCServicePhotos")),*native_credential=credential();
    void *native_server=server(),*options=options_create();
    if(!native_service||!native_credential||!native_server||!options) {
        if(options)release(options);report("native-authorization-probe native object unavailable",context);return;
    }
    /* Exact policies used by this installed framework's own preflight. */
    reply_policy(options,1);prompt_policy(options,2);
    request(native_server,options,native_credential,native_service,NULL,^(void *record,void *error) {
        @autoreleasepool {
            char line[1024];
            if(error) {
                @try {
#if __has_feature(objc_arc)
                    id native=(__bridge id)error;
#else
                    id native=(id)error;
#endif
                    NSError *failure=[native isKindOfClass:NSError.class]?native:nil;
                    NSString *description=[native description];
                    snprintf(line,sizeof(line),"native-authorization-reply record=%u error=1 class=%.96s domain=%.128s code=%ld description=%.576s no-prompt=1 original-answer-preserved=1",
                        record!=NULL,class_getName(object_getClass(native)),failure.domain.UTF8String ?: "(non-NSError)",
                        (long)failure.code,description.UTF8String ?: "(none)");
                } @catch (__unused id observation_error) {
                    snprintf(line,sizeof(line),"native-authorization-reply record=%u error=1 description-unavailable=1 no-prompt=1",record!=NULL);
                }
            } else snprintf(line,sizeof(line),"native-authorization-reply record=%u error=0 actual-right=%llu no-prompt=1 original-answer-preserved=1",
                record!=NULL,(unsigned long long)(record?right(record):UINT64_MAX));
            for(unsigned i=0;line[i];++i)if(line[i]=='\n'||line[i]=='\r')line[i]=' ';
            report(line,context);
            /* Match the native preflight's callback ownership even if the
             * framework must deliver an asynchronous error. */
            release(options);
        }
    });
    /* Keep this one framework handle: a pending native callback refers to it. */
}
