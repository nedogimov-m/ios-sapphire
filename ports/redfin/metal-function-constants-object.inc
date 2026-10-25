/* SPDX-License-Identifier: MIT */
/* Native Metal metadata and constant storage, paired to this installed cache.
 * Each returned function is a genuine fresh _MTLFunction. The association owns
 * its immutable values; no private C++ storage layout or shader rewrite is used. */
#include <CommonCrypto/CommonDigest.h>
static char redfin_function_values_key;
static Class redfin_specialized_function_class;
static struct redfin_metal_constants
redfin_function_constants(id function)
{
    NSData *data=objc_getAssociatedObject(function,&redfin_function_values_key);
    if(data.length%sizeof(struct redfin_metal_constant)||data.length/sizeof(struct redfin_metal_constant)>REDFIN_METAL_CONSTANTS_MAX)abort();
    return (struct redfin_metal_constants){.values=data.bytes,.count=(uint32_t)(data.length/sizeof(struct redfin_metal_constant))};
}
static id
redfin_function_error(NSError **error,NSString *reason)
{
    if(error)*error=[NSError errorWithDomain:@"RedfinMetal" code:4 userInfo:@{NSLocalizedDescriptionKey:reason}];
    rw_print("REDFIN METAL SPECIALIZATION REFUSED: %s\n",reason.UTF8String);return nil;
}
static NSUInteger
redfin_constant_bytes(MTLDataType type)
{
    if(type>=MTLDataTypeFloat&&type<=MTLDataTypeFloat4)return 4*(type-MTLDataTypeFloat+1);
    if(type>=MTLDataTypeHalf&&type<=MTLDataTypeHalf4)return 2*(type-MTLDataTypeHalf+1);
    if(type>=MTLDataTypeInt&&type<=MTLDataTypeInt4)return 4*(type-MTLDataTypeInt+1);
    if(type>=MTLDataTypeUInt&&type<=MTLDataTypeUInt4)return 4*(type-MTLDataTypeUInt+1);
    if(type>=MTLDataTypeShort&&type<=MTLDataTypeShort4)return 2*(type-MTLDataTypeShort+1);
    if(type>=MTLDataTypeUShort&&type<=MTLDataTypeUShort4)return 2*(type-MTLDataTypeUShort+1);
    if(type>=MTLDataTypeChar&&type<=MTLDataTypeChar4)return type-MTLDataTypeChar+1;
    if(type>=MTLDataTypeUChar&&type<=MTLDataTypeUChar4)return type-MTLDataTypeUChar+1;
    if(type>=MTLDataTypeBool&&type<=MTLDataTypeBool4)return type-MTLDataTypeBool+1;
    if(type>=MTLDataTypeLong&&type<=MTLDataTypeLong4)return 8*(type-MTLDataTypeLong+1);
    if(type>=MTLDataTypeULong&&type<=MTLDataTypeULong4)return 8*(type-MTLDataTypeULong+1);
    return 0;
}
static id
redfin_specialized_function_locked(id library,NSString *name,id values,NSString *specializedName,NSError **error)
{
    if(error)*error=nil;
    if(!name.length)return redfin_function_error(error,@"a function name is required");
    id prototype=((id (*)(id,SEL,id))objc_msgSend)(library,sel_getUid("newFunctionWithNameInternal:"),name);
    if(!prototype)return redfin_function_error(error,[NSString stringWithFormat:@"function %@ is absent from this library",name]);
    id snapshot=values?[values copy]:nil;
    NSDictionary *declarations=[prototype functionConstantsDictionary];
    NSMutableData *payload=[NSMutableData data];NSMutableSet *indices=[NSMutableSet set];
    BOOL valid=!declarations||[declarations isKindOfClass:[NSDictionary class]];
    if(declarations.count>REDFIN_METAL_CONSTANTS_MAX)valid=NO;
    NSString *failure=nil;
    @try {
        for(NSString *key in [[declarations allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
            MTLFunctionConstant *declaration=declarations[key];NSUInteger index=declaration.index;
            if(index>UINT32_MAX||[indices containsObject:@(index)]) {valid=NO;failure=@"invalid native function constant indices";break;}
            [indices addObject:@(index)];
            const void *pointer=snapshot?((const void *(*)(id,SEL,id))objc_msgSend)(snapshot,
                sel_getUid("constantValueWithFunctionConstant:"),declaration):NULL;
            if(!pointer) {
                if([declaration required]) {valid=NO;failure=[NSString stringWithFormat:@"required function constant %@ is missing",key];break;}
                continue;
            }
            NSUInteger bytes=redfin_constant_bytes([declaration type]);
            if(!bytes||bytes>32) {valid=NO;failure=[NSString stringWithFormat:@"unsupported type for function constant %@",key];break;}
            struct redfin_metal_constant item={.index=(uint32_t)index,.bytes=(uint32_t)bytes};
            memcpy(item.words,pointer,bytes);[payload appendBytes:&item length:sizeof(item)];
        }
    } @catch(NSException *exception) {valid=NO;failure=exception.reason;}
    [snapshot release];
    if(!valid) {[prototype release];return redfin_function_error(error,failure?:@"invalid native function constant metadata");}
    id plugin=((id (*)(id,SEL))objc_msgSend)(prototype,sel_getUid("pluginData"));
    unsigned char bitcodeType=((unsigned char (*)(id,SEL))objc_msgSend)(prototype,sel_getUid("bitcodeType"));
    /* This native factory returns a fresh concrete function and performs its
     * own retains for plugin/archive/function-input data. Its constructor is
     * NOT a copying API: directly copying its opaque struct would mis-own refs. */
    id function=((id (*)(id,SEL,id,unsigned char))objc_msgSend)(prototype,
        sel_getUid("newFunctionWithPluginData:bitcodeType:"),plugin,bitcodeType);
    [prototype release];if(!function)return redfin_function_error(error,@"native function allocation failed");
    Class concrete=objc_lookUpClass("_MTLFunctionInternal");
    if(object_getClass(function)!=concrete||class_getInstanceSize(concrete)!=class_getInstanceSize(redfin_specialized_function_class)) {
        [function release];return redfin_function_error(error,@"unexpected concrete native function class");
    }
    object_setClass(function,redfin_specialized_function_class);
    NSData *immutable=[payload copy];
    objc_setAssociatedObject(function,&redfin_function_values_key,immutable,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    /* The native clone preserves actual bitcode offset/type and ownership. */
    NSData *air=((id (*)(id,SEL))objc_msgSend)(function,sel_getUid("bitcodeData"));
    CC_SHA256_CTX hash;unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256_Init(&hash);
    CC_SHA256_Update(&hash,name.UTF8String,(CC_LONG)strlen(name.UTF8String));
    if(air.length<=UINT32_MAX)CC_SHA256_Update(&hash,air.bytes,(CC_LONG)air.length);
    CC_SHA256_Update(&hash,immutable.bytes,(CC_LONG)immutable.length);CC_SHA256_Final(digest,&hash);
    ((void (*)(id,SEL,const void *))objc_msgSend)(function,sel_getUid("setFunctionConstantSpecializationHash:"),digest);
    if(specializedName.length)[function setLabel:specializedName];
    const char *capture_option=getenv("REDFIN_METAL_DRAW_CAPTURE");
    BOOL capture_parameters=capture_option&&!strcmp(capture_option,"1");
    if(capture_parameters)rw_print("REDFIN METAL SPECIALIZATION: function=%s values=%lu native-function=1 immutable=1\n",name.UTF8String,
        (unsigned long)(immutable.length/sizeof(struct redfin_metal_constant)));
    /* Bounded rendering parameters let the host reproduce actual system
     * variants. The capture contains no device identity or user resources. */
    static unsigned snapshots;
    if(capture_parameters&&[name hasPrefix:@"fixed_"]&&__sync_fetch_and_add(&snapshots,1)<16) {
        char record[4096]={0};size_t used=0;BOOL complete=YES;
        const struct redfin_metal_constant *items=immutable.bytes;
        unsigned count=(unsigned)(immutable.length/sizeof(*items));
        for(unsigned i=0;i<count&&complete;++i) {
            int wrote=snprintf(record+used,sizeof(record)-used,"%s%u/",i?",":"",items[i].index);
            if(wrote<0||(size_t)wrote>=sizeof(record)-used){complete=NO;break;}used+=(size_t)wrote;
            const unsigned char *bytes=(const unsigned char *)items[i].words;
            for(unsigned j=0;j<items[i].bytes;++j) {
                wrote=snprintf(record+used,sizeof(record)-used,"%02x",bytes[j]);
                if(wrote<0||(size_t)wrote>=sizeof(record)-used){complete=NO;break;}used+=(size_t)wrote;
            }
        }
        if(complete)rw_print("REDFIN METAL CONSTANT SNAPSHOT: function=%s values=%u data=%s\n",name.UTF8String,count,record);
    }
    [immutable release];return function;
}
static id
redfin_specialized_function(id library,NSString *name,id values,NSString *specializedName,NSError **error)
{
    /* The public library APIs are concurrent; keep native metadata/cache
     * access serialized even when a caller uses our asynchronous factories. */
    @synchronized(library) {return redfin_specialized_function_locked(library,name,values,specializedName,error);}
}

struct redfin_function_hook {const char *selector;IMP replacement,original;};
static IMP redfin_function_original(SEL);
static BOOL redfin_function_library(id library)
{return [[library device] isKindOfClass:[RedwoodMetalDevice class]];}
static id redfin_function_sync(id self,SEL cmd,id name,id values,NSError **error)
{
    if(!redfin_function_library(self))return ((id (*)(id,SEL,id,id,NSError **))redfin_function_original(cmd))(self,cmd,name,values,error);
    return redfin_specialized_function(self,name,values,nil,error);
}
static id redfin_function_cache(id self,SEL cmd,id name,id values,id cache,NSError **error)
{
    if(!redfin_function_library(self))return ((id (*)(id,SEL,id,id,id,NSError **))redfin_function_original(cmd))(self,cmd,name,values,cache,error);
    return redfin_specialized_function(self,name,values,nil,error);
}
static id redfin_function_named(id self,SEL cmd,id name,id values,id cache,id specialized,NSError **error)
{
    if(!redfin_function_library(self))return ((id (*)(id,SEL,id,id,id,id,NSError **))redfin_function_original(cmd))(self,cmd,name,values,cache,specialized,error);
    return redfin_specialized_function(self,name,values,specialized,error);
}
static id redfin_function_descriptor(id self,SEL cmd,id descriptor,NSError **error)
{
    if(!redfin_function_library(self))return ((id (*)(id,SEL,id,NSError **))redfin_function_original(cmd))(self,cmd,descriptor,error);
    MTLFunctionDescriptor *shape=descriptor;
    if(shape.options)return redfin_function_error(error,@"function descriptor compiler-only options are unsupported");
    return redfin_specialized_function(self,shape.name,shape.constantValues,shape.specializedName,error);
}
static id redfin_function_descriptor_archive(id self,SEL cmd,id descriptor,id archive,NSError **error)
{
    if(!redfin_function_library(self))return ((id (*)(id,SEL,id,id,NSError **))redfin_function_original(cmd))(self,cmd,descriptor,archive,error);
    return redfin_function_descriptor(self,sel_getUid("newFunctionWithDescriptor:error:"),descriptor,error);
}
static id redfin_function_descriptor_cache(id self,SEL cmd,id descriptor,id archive,id cache,NSError **error)
{
    if(!redfin_function_library(self))return ((id (*)(id,SEL,id,id,id,NSError **))redfin_function_original(cmd))(self,cmd,descriptor,archive,cache,error);
    return redfin_function_descriptor(self,sel_getUid("newFunctionWithDescriptor:error:"),descriptor,error);
}
static void redfin_function_complete(id library,id name,id values,id specialized,void (^handler)(id,NSError *))
{
    /* Snapshot before enqueue: later mutation/reset of the caller's values is
     * independent of this compilation, including asynchronous entry points. */
    id frozen=[values copy],entry=[name copy],alias=[specialized copy];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{@autoreleasepool {
        NSError *error=nil;id function=redfin_specialized_function(library,entry,frozen,alias,&error);
        if(handler)handler(function,error);[function release];
    }});
    [frozen release];[entry release];[alias release];
}
static void redfin_function_async(id self,SEL cmd,id name,id values,void (^handler)(id,NSError *))
{
    if(!redfin_function_library(self)) {((void (*)(id,SEL,id,id,id))redfin_function_original(cmd))(self,cmd,name,values,handler);return;}
    redfin_function_complete(self,name,values,nil,handler);
}
static void redfin_function_async_cache(id self,SEL cmd,id name,id values,id cache,void (^handler)(id,NSError *))
{
    if(!redfin_function_library(self)) {((void (*)(id,SEL,id,id,id,id))redfin_function_original(cmd))(self,cmd,name,values,cache,handler);return;}
    redfin_function_complete(self,name,values,nil,handler);
}
static void redfin_function_async_named(id self,SEL cmd,id name,id values,id cache,id specialized,void (^handler)(id,NSError *))
{
    if(!redfin_function_library(self)) {((void (*)(id,SEL,id,id,id,id,id))redfin_function_original(cmd))(self,cmd,name,values,cache,specialized,handler);return;}
    redfin_function_complete(self,name,values,specialized,handler);
}
static void redfin_function_descriptor_async(id self,SEL cmd,id descriptor,void (^handler)(id,NSError *))
{
    if(!redfin_function_library(self)) {((void (*)(id,SEL,id,id))redfin_function_original(cmd))(self,cmd,descriptor,handler);return;}
    id frozen=[descriptor copy];dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{@autoreleasepool {
        NSError *error=nil;id function=redfin_function_descriptor(self,sel_getUid("newFunctionWithDescriptor:error:"),frozen,&error);
        if(handler)handler(function,error);[function release];
    }});[frozen release];
}
static void redfin_function_descriptor_async_cache(id self,SEL cmd,id descriptor,id archive,id cache,void (^handler)(id,NSError *))
{
    if(!redfin_function_library(self)) {((void (*)(id,SEL,id,id,id,id))redfin_function_original(cmd))(self,cmd,descriptor,archive,cache,handler);return;}
    redfin_function_descriptor_async(self,sel_getUid("newFunctionWithDescriptor:completionHandler:"),descriptor,handler);
}
static struct redfin_function_hook redfin_function_hooks[]={
    {"newFunctionWithName:constantValues:error:",(IMP)redfin_function_sync,NULL},
    {"newFunctionWithName:constantValues:functionCache:error:",(IMP)redfin_function_cache,NULL},
    {"newFunctionWithName:constantValues:pipelineLibrary:error:",(IMP)redfin_function_cache,NULL},
    {"newFunctionWithName:constantValues:functionCache:specializedName:error:",(IMP)redfin_function_named,NULL},
    {"newFunctionWithDescriptor:error:",(IMP)redfin_function_descriptor,NULL},
    {"newFunctionWithDescriptor:destinationArchive:error:",(IMP)redfin_function_descriptor_archive,NULL},
    {"newSpecializedFunctionWithDescriptorInternal:destinationArchive:functionCache:error:",(IMP)redfin_function_descriptor_cache,NULL},
    {"newFunctionWithName:constantValues:completionHandler:",(IMP)redfin_function_async,NULL},
    {"newFunctionWithName:constantValues:functionCache:specializedName:completionHandler:",(IMP)redfin_function_async_named,NULL},
    {"newFunctionWithName:constantValues:pipelineLibrary:completionHandler:",(IMP)redfin_function_async_cache,NULL},
    {"newFunctionWithDescriptor:completionHandler:",(IMP)redfin_function_descriptor_async,NULL},
    {"newFunctionWithDescriptor:destinationArchive:functionCache:completionHandler:",(IMP)redfin_function_descriptor_async_cache,NULL},
};
static IMP redfin_function_original(SEL selector)
{
    for(unsigned i=0;i<sizeof(redfin_function_hooks)/sizeof(*redfin_function_hooks);++i)
        if(sel_isEqual(selector,sel_getUid(redfin_function_hooks[i].selector)))return redfin_function_hooks[i].original;
    abort();
}
static BOOL redfin_function_needs_constants(id self,SEL selector)
{
    (void)self;(void)selector;
    /* Only our factory creates this subclass, after required-value validation.
     * Specialization is complete in the paired AIR compiler, independently of
     * the original generic bitcode's native function-constant declarations. */
    return NO;
}
static void redfin_install_function_constants_once(void)
{
    Class native=objc_lookUpClass("_MTLFunctionInternal");
    redfin_specialized_function_class=objc_allocateClassPair(native,"RedfinMetalSpecializedFunction",0);
    if(!redfin_specialized_function_class)abort();
    SEL needs=sel_getUid("needsFunctionConstantValues");Method method=class_getInstanceMethod(native,needs);
    if(!method||!class_addMethod(redfin_specialized_function_class,needs,(IMP)redfin_function_needs_constants,method_getTypeEncoding(method)))abort();
    objc_registerClassPair(redfin_specialized_function_class);
    Class library=objc_lookUpClass("_MTLLibrary");
    for(unsigned i=0;i<sizeof(redfin_function_hooks)/sizeof(*redfin_function_hooks);++i) {
        struct redfin_function_hook *hook=&redfin_function_hooks[i];SEL selector=sel_getUid(hook->selector);
        Method method=class_getInstanceMethod(library,selector);if(!method)abort();
        hook->original=class_replaceMethod(library,selector,hook->replacement,method_getTypeEncoding(method));
        if(!hook->original)abort();
    }
}
static void redfin_install_function_constants(void)
{
    static pthread_once_t once=PTHREAD_ONCE_INIT;
    if(pthread_once(&once,redfin_install_function_constants_once))abort();
}
