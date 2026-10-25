/* SPDX-License-Identifier: MIT */
/* Capture only: observe the installed TCCD's actual decisions and attribution.
 * Every original IMP is called once with its original arguments and its exact
 * result/error is returned. No grant, entitlement or database is modified. */
#include <objc/message.h>
#include <mach-o/loader.h>

static id (*native_tcc_evaluate)(id,SEL,id,id,id,NSUInteger);
static id (*native_tcc_independent)(id,SEL,id,id,id,id *);
static BOOL (*native_tcc_contains)(id,SEL,id,id,NSUInteger);
static unsigned native_tcc_records;

static bool native_tcc_image(IMP implementation)
{
    static const uint8_t uuid[16]={0x78,0xc8,0xcb,0xbe,0xb0,0xa3,0x3b,0xf1,
        0xac,0xcb,0x52,0xe1,0x52,0x86,0xb8,0x3c};
    Dl_info info={0};
    if(!dladdr((void *)implementation,&info)||!info.dli_fbase)return false;
    const struct mach_header_64 *header=info.dli_fbase;
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
static Method native_tcc_method(const char *cls,const char *selector,const char *types)
{
    Method method=class_getInstanceMethod(objc_getClass(cls),sel_registerName(selector));
    return method&&!strcmp(method_getTypeEncoding(method),types)&&
        native_tcc_image(method_getImplementation(method))?method:NULL;
}
static id native_tcc_object(id object,const char *selector)
{return object?((id (*)(id,SEL))objc_msgSend)(object,sel_registerName(selector)):nil;}
static int native_tcc_pid(id process)
{return process?((int (*)(id,SEL))objc_msgSend)(process,sel_registerName("pid")):-1;}
static NSUInteger native_tcc_number(id object,const char *selector)
{return object?((NSUInteger (*)(id,SEL))objc_msgSend)(object,sel_registerName(selector)):NSUIntegerMax;}
static BOOL native_tcc_photos(id service)
{
    NSString *name=native_tcc_object(service,"name");
    return [name isEqualToString:@"kTCCServicePhotos"]||[name isEqualToString:@"kTCCServicePhotosAdd"];
}
static BOOL native_tcc_entitled(id process,id service)
{
    NSDictionary *entitlements=native_tcc_object(process,"entitlements");
    id list=[entitlements isKindOfClass:NSDictionary.class]?entitlements[@"com.apple.private.tcc.allow"]:nil;
    return [list isKindOfClass:NSArray.class]&&[list containsObject:native_tcc_object(service,"name")];
}
static BOOL observe_tcc_contains(id object,SEL selector,id entitlement,id service,NSUInteger options)
{
    BOOL result=native_tcc_contains(object,selector,entitlement,service,options);
    @try {
    if(native_tcc_photos(service)&&__atomic_fetch_add(&native_tcc_records,1,__ATOMIC_RELAXED)<160)
        diagnostic_log("native-TCCD-contains target=%d key=%.128s options=%lu actual-result=%u cached-native-Photos-allow=%u",
            native_tcc_pid(object),[entitlement UTF8String] ?: "(none)",(unsigned long)options,
            result,native_tcc_entitled(object,service));
    } @catch (__unused id observation_error) { /* Preserve the original result. */ }
    return result;
}
static id observe_tcc_evaluate(id object,SEL selector,id process,id entitlement,id service,NSUInteger options)
{
    id result=native_tcc_evaluate(object,selector,process,entitlement,service,options);
    @try {
    if(native_tcc_photos(service)&&__atomic_fetch_add(&native_tcc_records,1,__ATOMIC_RELAXED)<160)
        diagnostic_log("native-TCCD-evaluate target=%d key=%.128s actual-right=%lu actual-reason=%lu native-Photos-allow=%u",
            native_tcc_pid(process),[entitlement UTF8String] ?: "(none)",
            (unsigned long)native_tcc_number(result,"right"),(unsigned long)native_tcc_number(result,"reason"),
            native_tcc_entitled(process,service));
    } @catch (__unused id observation_error) { /* Preserve the original result. */ }
    return result;
}
static id observe_tcc_independent(id object,SEL selector,id chain,id function,id service,id *error)
{
    id result=native_tcc_independent(object,selector,chain,function,service,error);
    @try {
    if(native_tcc_photos(service)&&__atomic_fetch_add(&native_tcc_records,1,__ATOMIC_RELAXED)<160) {
        id requesting=native_tcc_object(chain,"requestingProcess");
        id accessing=native_tcc_object(chain,"accessingProcess");
        id responsible=native_tcc_object(chain,"responsibleProcess");
        diagnostic_log("native-TCCD-attribution requestor=%d accessing=%d responsible=%d actual-right=%lu actual-reason=%lu requestor-Photos-allow=%u accessing-Photos-allow=%u",
            native_tcc_pid(requesting),native_tcc_pid(accessing),native_tcc_pid(responsible),
            (unsigned long)native_tcc_number(result,"right"),(unsigned long)native_tcc_number(result,"reason"),
            native_tcc_entitled(requesting,service),native_tcc_entitled(accessing,service));
    }
    } @catch (__unused id observation_error) { /* Preserve the original result. */ }
    return result;
}
static void install_native_tcc_observer(void)
{
    struct {const char *cls,*selector,*types;} required[]={
        {"TCCDProcess","pid","i16@0:8"},{"TCCDProcess","entitlements","@16@0:8"},
        {"TCCDService","name","@16@0:8"},{"TCCDAuthorizationRightState","right","Q16@0:8"},
        {"TCCDAuthorizationRightState","reason","Q16@0:8"},
        {"TCCDAttributionChain","requestingProcess","@16@0:8"},
        {"TCCDAttributionChain","accessingProcess","@16@0:8"},
        {"TCCDAttributionChain","responsibleProcess","@16@0:8"},
    };
    for(unsigned i=0;i<sizeof(required)/sizeof(required[0]);++i)
        if(!native_tcc_method(required[i].cls,required[i].selector,required[i].types))return;
    Method contains=native_tcc_method("TCCDProcess","hasEntitlement:containsService:options:","B40@0:8@16@24Q32");
    Method evaluate=native_tcc_method("TCCDServer","_evaluateForProcess:entitlementName:containsService:options:","@48@0:8@16@24@32Q40");
    Method independent=native_tcc_method("TCCDServer","evaluateUserIndependentEntitlementsForAccessByAttributionChain:forFunction:toService:error:","@48@0:8@16@24@32^@40");
    if(!contains||!evaluate||!independent)return;
    native_tcc_contains=(BOOL (*)(id,SEL,id,id,NSUInteger))method_getImplementation(contains);
    native_tcc_evaluate=(id (*)(id,SEL,id,id,id,NSUInteger))method_getImplementation(evaluate);
    native_tcc_independent=(id (*)(id,SEL,id,id,id,id *))method_getImplementation(independent);
    method_setImplementation(contains,(IMP)observe_tcc_contains);
    method_setImplementation(evaluate,(IMP)observe_tcc_evaluate);
    method_setImplementation(independent,(IMP)observe_tcc_independent);
    diagnostic_log("native-TCCD-observers-installed UUID-and-method-ABI-verified=1 original-results-preserved=1");
}
