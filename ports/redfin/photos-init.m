/* SPDX-License-Identifier: MIT */
/* Native, idempotent first-library creation through the installed Photos API.
 * Never replace a database, synthesize its schema or suppress a Photos assert. */
#import <Foundation/Foundation.h>
#import <Photos/Photos.h>
#import <Security/Security.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <CommonCrypto/CommonDigest.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include <stdlib.h>
#include <limits.h>
#include <sys/time.h>
#include "gui-profile.h"

extern int memorystatus_control(uint32_t, int32_t, uint32_t, void *, size_t);
struct photo_limits {int32_t active;uint32_t active_attributes;int32_t inactive;uint32_t inactive_attributes;};

static int
memory_limit(void)
{
    /* Actual8796 SET/GET_MEMLIMIT_PROPERTIES and fatal attributes. The signed
     * program requests the native memorystatus entitlement, for itself only. */
    struct photo_limits wanted={512,1,512,1}, actual={0};
    if (memorystatus_control(7,getpid(),0,&wanted,sizeof(wanted)) ||
        memorystatus_control(8,getpid(),0,&actual,sizeof(actual))) return errno ? errno : EIO;
    return actual.active==512 && actual.inactive==512 ? 0 : EINVAL;
}

static BOOL
method_matches(Class cls, const char *name, const char *types)
{
    Method method=cls ? class_getClassMethod(cls,sel_registerName(name)) : NULL;
    return method && !strcmp(method_getTypeEncoding(method),types);
}

static BOOL
instance_method_matches(Class cls,const char *name,const char *types)
{
    Method method=cls ? class_getInstanceMethod(cls,sel_registerName(name)) : NULL;
    return method && !strcmp(method_getTypeEncoding(method),types);
}

static void
identity_proof(const char *nonce)
{
    void *handle=dlopen("/usr/lib/libMobileGestalt.dylib",RTLD_NOW|RTLD_LOCAL);
    CFTypeRef (*copy)(CFStringRef)=handle ? (CFTypeRef (*)(CFStringRef))dlsym(handle,"MGCopyAnswer") : NULL;
    CFTypeRef value=copy ? copy(CFSTR("SerialNumber")) : NULL;
    char serial[256]={0}; BOOL present=NO;
    if (value && CFGetTypeID(value)==CFStringGetTypeID())
        present=CFStringGetCString((CFStringRef)value,serial,sizeof(serial),kCFStringEncodingASCII) && serial[0];
    unsigned char digest[CC_SHA256_DIGEST_LENGTH]={0}; char hex[65]={0};
    if (present) {
        CC_SHA256(serial,(CC_LONG)strlen(serial),digest);
        for (unsigned i=0;i<sizeof(digest);++i) snprintf(hex+2*i,3,"%02x",digest[i]);
    }
    printf("REDFIN IDENTITY PROOF: boot=%s MobileGestalt-serial=%u sha256=%s\n",nonce,present,hex);
    memset(serial,0,sizeof(serial));
    if (value) CFRelease(value);
    value=copy ? copy(CFSTR("ModelNumber")) : NULL;
    present=NO; memset(digest,0,sizeof(digest)); memset(hex,0,sizeof(hex));
    if (value && CFGetTypeID(value)==CFStringGetTypeID())
        present=CFStringGetCString((CFStringRef)value,serial,sizeof(serial),kCFStringEncodingASCII) && serial[0];
    if (present) {
        CC_SHA256(serial,(CC_LONG)strlen(serial),digest);
        for (unsigned i=0;i<sizeof(digest);++i) snprintf(hex+2*i,3,"%02x",digest[i]);
    }
    printf("REDFIN IDENTITY MODEL PROOF: boot=%s MobileGestalt-model=%u sha256=%s\n",nonce,present,hex);
    memset(serial,0,sizeof(serial)); memset(digest,0,sizeof(digest)); memset(hex,0,sizeof(hex));
    if (value) CFRelease(value);
    if (handle) dlclose(handle);
}

/* Exercise the real SecItem/securityd/AKS path, without a user's password.
 * An existing exact item on a later boot proves native decrypt persistence. */
static void
keychain_proof(const char *nonce)
{
    static const unsigned char marker[]="Redfin native Keychain persistence probe v1.";
    CFMutableDictionaryRef query=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    if (!query) return;
    CFDictionarySetValue(query,kSecClass,kSecClassGenericPassword);
    CFDictionarySetValue(query,kSecAttrService,CFSTR("com.redfin.keychain.persistence-probe"));
    CFDictionarySetValue(query,kSecAttrAccount,CFSTR("local-device"));
    CFDictionarySetValue(query,kSecAttrAccessGroup,CFSTR("com.redfin.photos-init"));
    CFDictionarySetValue(query,kSecReturnData,kCFBooleanTrue);
    CFDictionarySetValue(query,kSecMatchLimit,kSecMatchLimitOne);
    CFTypeRef value=NULL;
    OSStatus status=SecItemCopyMatching(query,&value),add=errSecSuccess;
    BOOL existing=status==errSecSuccess;
    if (status==errSecItemNotFound) {
        CFMutableDictionaryRef item=CFDictionaryCreateMutableCopy(NULL,0,query);
        if (item) {
            CFDictionaryRemoveValue(item,kSecReturnData);
            CFDictionaryRemoveValue(item,kSecMatchLimit);
            CFDictionarySetValue(item,kSecAttrAccessible,kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly);
            CFDataRef data=CFDataCreate(NULL,marker,sizeof(marker)-1);
            if (data) {
                CFDictionarySetValue(item,kSecValueData,data);
                add=SecItemAdd(item,NULL); CFRelease(data);
            } else add=errSecAllocate;
            CFRelease(item);
        } else add=errSecAllocate;
        if (add==errSecSuccess || add==errSecDuplicateItem) status=SecItemCopyMatching(query,&value);
    }
    BOOL valid=status==errSecSuccess && value && CFGetTypeID(value)==CFDataGetTypeID() &&
        CFDataGetLength((CFDataRef)value)==(CFIndex)(sizeof(marker)-1) &&
        !memcmp(CFDataGetBytePtr((CFDataRef)value),marker,sizeof(marker)-1);
    printf("REDFIN KEYCHAIN PROBE: boot=%s existing=%u add-status=%d read-status=%d exact=%u\n",
        nonce,existing,(int)add,(int)status,valid);
    if (value) CFRelease(value);
    CFRelease(query);
}

/* Observe Security/TCC's own answers for this signed helper. Preserve all
 * native authorization decisions; no policy override or database edit. */
static void
authorization_proof(const char *nonce)
{
    void *security=dlopen("/System/Library/Frameworks/Security.framework/Security",RTLD_NOW|RTLD_LOCAL);
    CFTypeRef (*task_create)(CFAllocatorRef)=security ? (CFTypeRef (*)(CFAllocatorRef))dlsym(security,"SecTaskCreateFromSelf") : NULL;
    CFTypeRef (*copy)(CFTypeRef,CFStringRef,CFErrorRef *)=security ?
        (CFTypeRef (*)(CFTypeRef,CFStringRef,CFErrorRef *))dlsym(security,"SecTaskCopyValueForEntitlement") : NULL;
    uint32_t (*flags)(CFTypeRef)=security ? (uint32_t (*)(CFTypeRef))dlsym(security,"SecTaskGetCodeSignStatus") : NULL;
    Boolean (*validated)(CFTypeRef)=security ? (Boolean (*)(CFTypeRef))dlsym(security,"SecTaskEntitlementsValidated") : NULL;
    CFStringRef (*identity)(CFTypeRef,CFErrorRef *)=security ?
        (CFStringRef (*)(CFTypeRef,CFErrorRef *))dlsym(security,"SecTaskCopySigningIdentifier") : NULL;
    CFTypeRef task=task_create ? task_create(NULL) : NULL;
    CFErrorRef error=NULL;CFTypeRef allow=task && copy ? copy(task,CFSTR("com.apple.private.tcc.allow"),&error) : NULL;
    BOOL entitled=allow && CFGetTypeID(allow)==CFArrayGetTypeID() &&
        CFArrayContainsValue((CFArrayRef)allow,CFRangeMake(0,CFArrayGetCount((CFArrayRef)allow)),CFSTR("kTCCServicePhotos"));
    void *tcc=dlopen("/System/Library/PrivateFrameworks/TCC.framework/TCC",RTLD_NOW|RTLD_LOCAL);
    long (*preflight)(CFStringRef,CFDictionaryRef)=tcc ? (long (*)(CFStringRef,CFDictionaryRef))dlsym(tcc,"tcc_authorization_preflight") : NULL;
    long authorization=preflight ? preflight(CFSTR("kTCCServicePhotos"),NULL) : -1;
    CFErrorRef identity_error=NULL;
    CFStringRef signing=task && identity ? identity(task,&identity_error) : NULL;
    BOOL identity_matches=signing && CFEqual(signing,CFSTR("com.redfin.photos-init"));
    struct timeval now={};gettimeofday(&now,NULL);
    printf("REDFIN PHOTO AUTHORIZATION: boot=%s SecTask=%u flags=%#x native-photos-entitlement=%u entitlement-error=%ld TCC-preflight=%ld calendar-valid=%u validated=%d signing-identity=%u identity-error=%ld\n",
        nonce,task!=NULL,task && flags ? flags(task) : 0,entitled,error ? (long)CFErrorGetCode(error) : 0,
        authorization,(uint64_t)now.tv_sec>=1577836800ULL,task && validated ? validated(task) : -1,
        identity_matches,identity_error ? (long)CFErrorGetCode(identity_error) : 0);
    if (signing) CFRelease(signing);if (identity_error) CFRelease(identity_error);
    if (allow) CFRelease(allow);if (error) CFRelease(error);if (task) CFRelease(task);
}

int main(void)
{
    setvbuf(stdout,NULL,_IOLBF,0); setvbuf(stderr,NULL,_IOLBF,0);
    char args[1024]={0}, nonce[17]={0}; size_t bytes=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || !bytes || bytes>sizeof(args) ||
        !redfin_gpu_gui_profile(args,(unsigned)bytes,NULL)) return 0;
    const char *at=strstr(args,"redfinbootid=0x");
    if (!at || strlen(at+15)<16) return 2;
    memcpy(nonce,at+15,16);
    printf("REDFIN PHOTO INIT BOOT: %s pid=%d uid=%u\n",nonce,getpid(),getuid());
    if (getuid()!=501) { printf("REDFIN PHOTO INIT REFUSED: native mobile user required\n"); return 3; }
    int limit=memory_limit();
    printf("REDFIN PHOTO INIT MEMORY: limit=512 error=%d\n",limit);
    @autoreleasepool {
        @try {
            identity_proof(nonce);
            if (limit) return 4;
            keychain_proof(nonce);
            authorization_proof(nonce);
            Class photo=NSClassFromString(@"PHPhotoLibrary");
            Class manager=NSClassFromString(@"PLPhotoLibraryPathManager");
            if (!manager) dlopen("/System/Library/PrivateFrameworks/PhotoLibraryServicesCore.framework/PhotoLibraryServicesCore",RTLD_NOW|RTLD_LOCAL);
            manager=NSClassFromString(@"PLPhotoLibraryPathManager");
            if (!method_matches(photo,"systemPhotoLibraryURL","@16@0:8") ||
                !method_matches(photo,"createOrUpgradePhotoLibraryWithWellKnownIdentifier:error:","B32@0:8q16^@24") ||
                !method_matches(photo,"openPhotoLibraryWithWellKnownIdentifier:error:","@32@0:8q16^@24") ||
                !instance_method_matches(photo,"initWithPhotoLibraryURL:","@24@0:8@16") ||
                !instance_method_matches(photo,"createOrUpgradeLibraryUsingOptions:error:","B32@0:8@16^@24") ||
                !method_matches(manager,"isSystemPhotoLibraryURL:","B24@0:8@16") ||
                !method_matches(manager,"wellKnownPhotoLibraryIdentifierForURL:","q24@0:8@16")) {
                printf("REDFIN PHOTO INIT REFUSED: actual native method ABI differs\n"); return 5;
            }
            NSURL *url=((id (*)(id,SEL))objc_msgSend)(photo,sel_registerName("systemPhotoLibraryURL"));
            if (!url || !url.isFileURL) {
                printf("REDFIN PHOTO INIT REFUSED: native system-library URL missing or non-file\n"); return 6;
            }
            /* Foundation may canonicalize /private/var back to /var. Compare
             * actual filesystem canonical paths, with a directory boundary,
             * rather than requiring one spelling of this native mobile home. */
            char canonical[PATH_MAX]={0},mobile[PATH_MAX]={0};
            const char *native=url.isFileURL ? url.fileSystemRepresentation : NULL;
            int path_error=0;
            if (!native || !realpath(native,canonical)) path_error=errno ? errno : ENOENT;
            if (!realpath("/var/mobile",mobile) && !path_error) path_error=errno ? errno : ENOENT;
            NSString *path=canonical[0] ? [NSString stringWithUTF8String:canonical] : nil;
            BOOL system=((BOOL (*)(id,SEL,id))objc_msgSend)(manager,sel_registerName("isSystemPhotoLibraryURL:"),url);
            size_t mobile_bytes=strlen(mobile);
            BOOL within=mobile_bytes && !strncmp(canonical,mobile,mobile_bytes) && canonical[mobile_bytes]=='/';
            printf("REDFIN PHOTO INIT URL: file=%u system=%u canonical=%u within-mobile=%u error=%d path=%s\n",
                url.isFileURL,system,canonical[0]!=0,within,path_error,canonical[0] ? canonical : "(none)");
            if (!url || !url.isFileURL || !system || path_error || !within ||
                [path containsString:@"Syndication.photoslibrary"]) {
                printf("REDFIN PHOTO INIT REFUSED: expected the native mobile system-library URL\n"); return 6;
            }
            NSInteger identifier=((NSInteger (*)(id,SEL,id))objc_msgSend)(manager,
                sel_registerName("wellKnownPhotoLibraryIdentifierForURL:"),url);
            if (identifier<0) { printf("REDFIN PHOTO INIT REFUSED: no native well-known identifier\n"); return 7; }
            NSFileManager *files=NSFileManager.defaultManager;
            NSArray *candidates=@[[path stringByAppendingPathComponent:@"PhotoData/Photos.sqlite"],
                                  [path stringByAppendingPathComponent:@"database/Photos.sqlite"],
                                  [path stringByAppendingPathComponent:@"Photos.sqlite"]];
            BOOL existing=NO;
            for (NSString *candidate in candidates) if ([files fileExistsAtPath:candidate]) existing=YES;
            printf("REDFIN PHOTO INIT LIBRARY: id=%ld existing=%u path=%s\n",(long)identifier,existing,path.UTF8String);
            NSError *error=nil;
            id library=nil;
            if (identifier==0) {
                /* The system Media library is an ordinary URL library, not a
                 * named well-known library. Native identifier0 is intentional;
                 * passing it to the class well-known API is an API misuse.
                 * The instance path creates/opens/upgrades using Apple's own
                 * options/error handling, including an already-existing store. */
                BOOL ready=NO;
                for (unsigned attempt=1;attempt<=6;++attempt) {
                    error=nil;
                    library=((id (*)(id,SEL,id))objc_msgSend)([photo alloc],
                        sel_registerName("initWithPhotoLibraryURL:"),url);
                    ready=library && ((BOOL (*)(id,SEL,id,NSError **))objc_msgSend)(library,
                        sel_registerName("createOrUpgradeLibraryUsingOptions:error:"),nil,&error);
                    printf("REDFIN PHOTO INIT SYSTEM URL: ready=%u native-instance=1 attempt=%u error=%s\n",
                        ready,attempt,error ? error.description.UTF8String : "none");
                    if (ready) break;
                    /* The first assetsd can lose its startup race with TCC.
                     * Retry only a native XPC interruption/unavailable service;
                     * never retry a library/schema/authorization failure. Each
                     * attempt uses a fresh native instance and the same URL. */
                    BOOL transient=([error.domain isEqualToString:PHPhotosErrorDomain] && error.code==4103) ||
                        ([error.domain isEqualToString:NSCocoaErrorDomain] && (error.code==4097 || error.code==4099));
                    if (!transient || attempt==6) break;
                    library=nil;sleep(3);authorization_proof(nonce);
                }
                if (!ready) return 8;
            } else if (!existing) {
                BOOL created=((BOOL (*)(id,SEL,NSInteger,NSError **))objc_msgSend)(photo,
                    sel_registerName("createOrUpgradePhotoLibraryWithWellKnownIdentifier:error:"),identifier,&error);
                printf("REDFIN PHOTO INIT CREATE: success=%u error=%s\n",created,error ? error.description.UTF8String : "none");
                if (!created) return 8;
            }
            error=nil;
            if (!library) library=((id (*)(id,SEL,NSInteger,NSError **))objc_msgSend)(photo,
                    sel_registerName("openPhotoLibraryWithWellKnownIdentifier:error:"),identifier,&error);
            if (!library) {
                printf("REDFIN PHOTO INIT OPEN: success=0 error=%s\n",error ? error.description.UTF8String : "none"); return 9;
            }
            PHFetchResult *assets=[PHAsset fetchAssetsWithOptions:nil];
            printf("REDFIN PHOTO INIT RESULT: boot=%s native=1 ready=%u assets=%lu existing=%u\n",
                nonce,assets!=nil,(unsigned long)assets.count,existing);
            return assets ? 0 : 10;
        } @catch (NSException *exception) {
            printf("REDFIN PHOTO INIT EXCEPTION: name=%s reason=%s\n",exception.name.UTF8String,exception.reason.UTF8String);
            return 11;
        }
    }
}
