/* SPDX-License-Identifier: MIT */
/* Native, idempotent first-library creation through the installed Photos API.
 * Never replace a database, synthesize its schema or suppress a Photos assert. */
#import <Foundation/Foundation.h>
#import <Photos/Photos.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <CommonCrypto/CommonDigest.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysctl.h>
#include <unistd.h>
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
    if (handle) dlclose(handle);
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
            Class photo=NSClassFromString(@"PHPhotoLibrary");
            Class manager=NSClassFromString(@"PLPhotoLibraryPathManager");
            if (!manager) dlopen("/System/Library/PrivateFrameworks/PhotoLibraryServicesCore.framework/PhotoLibraryServicesCore",RTLD_NOW|RTLD_LOCAL);
            manager=NSClassFromString(@"PLPhotoLibraryPathManager");
            if (!method_matches(photo,"systemPhotoLibraryURL","@16@0:8") ||
                !method_matches(photo,"createOrUpgradePhotoLibraryWithWellKnownIdentifier:error:","B32@0:8q16^@24") ||
                !method_matches(photo,"openPhotoLibraryWithWellKnownIdentifier:error:","@32@0:8q16^@24") ||
                !method_matches(manager,"isSystemPhotoLibraryURL:","B24@0:8@16") ||
                !method_matches(manager,"wellKnownPhotoLibraryIdentifierForURL:","q24@0:8@16")) {
                printf("REDFIN PHOTO INIT REFUSED: actual native method ABI differs\n"); return 5;
            }
            NSURL *url=((id (*)(id,SEL))objc_msgSend)(photo,sel_registerName("systemPhotoLibraryURL"));
            NSString *path=url.URLByResolvingSymlinksInPath.path;
            BOOL system=((BOOL (*)(id,SEL,id))objc_msgSend)(manager,sel_registerName("isSystemPhotoLibraryURL:"),url);
            if (!url || !url.isFileURL || !system || ![path hasPrefix:@"/private/var/mobile/"] ||
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
            if (!existing) {
                BOOL created=((BOOL (*)(id,SEL,NSInteger,NSError **))objc_msgSend)(photo,
                    sel_registerName("createOrUpgradePhotoLibraryWithWellKnownIdentifier:error:"),identifier,&error);
                printf("REDFIN PHOTO INIT CREATE: success=%u error=%s\n",created,error ? error.description.UTF8String : "none");
                if (!created) return 8;
            }
            error=nil;
            id library=((id (*)(id,SEL,NSInteger,NSError **))objc_msgSend)(photo,
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
