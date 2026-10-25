/* SPDX-License-Identifier: MIT */
/* Native20H392 status-bar adaptation for Redfin's complete physical panel.
 * Uses verified selectors and UIView coordinates, never private ivar offsets. */
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <dlfcn.h>
#include <mach-o/loader.h>
#include <sys/sysctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "gui-profile.h"
#include "graphics-exec-scope.h"
#include "statusbar-geometry.h"

static void (*native_layout)(id,SEL);
static __thread bool in_layout;
static Class time_class;
static char boot_nonce[17];
static unsigned log_count;

static void ui_log(const char *format,...)
{
    if (log_count++>=96) return;
    char line[768]; int prefix=snprintf(line,sizeof(line),"REDFIN UI: boot=%s pid=%d ",boot_nonce,getpid());
    if (prefix<0 || (size_t)prefix>=sizeof(line)) return;
    va_list args; va_start(args,format);
    int n=vsnprintf(line+prefix,sizeof(line)-(size_t)prefix,format,args); va_end(args);
    if (n<0 || (size_t)n>=sizeof(line)-(size_t)prefix-1) return;
    size_t length=(size_t)(prefix+n); line[length++]='\n';
    int fd=open("/private/var/mobile/Library/Logs/redfin-ui.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW,0600);
    if (fd>=0) { (void)write(fd,line,length); close(fd); }
}
static BOOL signature(Class cls,const char *name,const char *types,BOOL meta)
{
    Method m=meta ? class_getClassMethod(cls,sel_registerName(name)) :
        class_getInstanceMethod(cls,sel_registerName(name));
    return m && !strcmp(method_getTypeEncoding(m),types);
}
static BOOL native_uuid(IMP implementation)
{
    static const unsigned char expected[16]={REDFIN_UIKIT_UUID_BYTES};
    Dl_info info={0};
    if (!dladdr((void *)implementation,&info) || !info.dli_fbase) return NO;
    const struct mach_header_64 *h=info.dli_fbase;
    if (h->magic!=MH_MAGIC_64 || h->ncmds>4096 || h->sizeofcmds>1048576) return NO;
    const unsigned char *p=(const unsigned char *)(h+1),*end=p+h->sizeofcmds;
    for (unsigned i=0;i<h->ncmds;++i) {
        if ((size_t)(end-p)<sizeof(struct load_command)) return NO;
        const struct load_command *lc=(const struct load_command *)p;
        if (lc->cmdsize<sizeof(*lc) || lc->cmdsize>(size_t)(end-p)) return NO;
        if (lc->cmd==LC_UUID) return lc->cmdsize==sizeof(struct uuid_command) &&
            !memcmp(((const struct uuid_command *)lc)->uuid,expected,sizeof(expected));
        p+=lc->cmdsize;
    }
    return NO;
}
static struct redfin_ui_rect rectangle(CGRect r)
{return (struct redfin_ui_rect){r.origin.x,r.origin.y,r.size.width,r.size.height};}

static void cutout_layout(id object,SEL selector)
{
    native_layout(object,selector);
    if (in_layout || !NSThread.isMainThread) return;
    UIView *bar=object; UIWindow *window=bar.window;
    UIScreen *screen=window.screen;
    if (!window || screen!=UIScreen.mainScreen) return;
    CGRect fixed=[screen.fixedCoordinateSpace bounds];
    /* Native iPhoneX375x812@3 remains essential to its status-bar provider. */
    if (fabs(fixed.size.width-375)>0.5 || fabs(fixed.size.height-812)>0.5) return;
    in_layout=true;
    @try {
        CGRect camera=CGRectMake(fixed.origin.x,fixed.origin.y,
            fixed.size.width*145.0/1080.0,fixed.size.height*136.0/2340.0);
        CGRect blocked=[window convertRect:camera fromCoordinateSpace:screen.fixedCoordinateSpace];
        CGRect local=[bar convertRect:blocked fromView:window];
        CGRect previous=((CGRect (*)(id,SEL))objc_msgSend)(bar,sel_registerName("avoidanceFrame"));
        if (!CGRectEqualToRect(previous,local)) {
            ((void (*)(id,SEL,CGRect))objc_msgSend)(bar,sel_registerName("setAvoidanceFrame:"),local);
            native_layout(object,selector);
        }
        id identifier=((id (*)(id,SEL))objc_msgSend)(time_class,sel_registerName("identifier"));
        id item=((id (*)(id,SEL,id))objc_msgSend)(bar,sel_registerName("itemWithIdentifier:"),identifier);
        if (![item isKindOfClass:time_class]) { in_layout=false; return; }
        const char *selectors[]={"timeDisplayIdentifier","shortTimeDisplayIdentifier","pillTimeDisplayIdentifier"};
        for (unsigned i=0;i<sizeof(selectors)/sizeof(selectors[0]);++i) {
            id display=((id (*)(id,SEL))objc_msgSend)(time_class,sel_registerName(selectors[i]));
            UIView *view=((id (*)(id,SEL,id))objc_msgSend)(item,sel_registerName("viewForIdentifier:"),display);
            if (![view isKindOfClass:UIView.class] || view.hidden || view.alpha<=0 ||
                view.window!=window || !view.superview || CGRectIsEmpty(view.bounds)) continue;
            CGRect before=[view convertRect:view.bounds toView:window]; double shift=0;
            BOOL planned=redfin_ui_time_shift(rectangle(before),rectangle(blocked),rectangle(window.bounds),&shift);
            if (planned && fabs(shift)>0.01) {
                CGRect target=before; target.origin.x+=shift;
                CGPoint center=[view.superview convertPoint:CGPointMake(CGRectGetMidX(target),CGRectGetMidY(target)) fromView:window];
                view.center=center;
            }
            CGRect after=[view convertRect:view.bounds toView:window];
            static unsigned observations;
            if (observations++<8 || fabs(shift)>0.01)
                ui_log("time=%u native-avoidance=1 planned=%u shift=%.2f rect=%.2f,%.2f,%.2f,%.2f outside-camera=%u native-max-fps=%ld",
                    i,planned,shift,after.origin.x,after.origin.y,after.size.width,after.size.height,
                    !CGRectIntersectsRect(after,blocked),(long)screen.maximumFramesPerSecond);
        }
    } @catch (NSException *exception) {
        ui_log("layout-refused exception=%s",exception.name.UTF8String);
    }
    in_layout=false;
}

__attribute__((constructor)) static void install_cutout(void)
{
    char args[1024]={0}; size_t bytes=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || !bytes || bytes>sizeof(args) ||
        !redfin_ui_fullscreen(args,(unsigned)bytes)) return;
    const char *nonce=strstr(args,"redfinbootid=0x");
    if (!nonce || strlen(nonce+15)<16) return;
    memcpy(boot_nonce,nonce+15,16);
    Class bar=objc_getClass("_UIStatusBar"); time_class=objc_getClass("_UIStatusBarTimeItem");
    if (!bar || !time_class ||
        !signature(bar,"layoutSubviews","v16@0:8",NO) ||
        !signature(bar,"setAvoidanceFrame:","v48@0:8{CGRect={CGPoint=dd}{CGSize=dd}}16",NO) ||
        !signature(bar,"avoidanceFrame","{CGRect={CGPoint=dd}{CGSize=dd}}16@0:8",NO) ||
        !signature(bar,"itemWithIdentifier:","@24@0:8@16",NO) ||
        !signature(time_class,"identifier","@16@0:8",YES) ||
        !signature(time_class,"timeDisplayIdentifier","@16@0:8",YES) ||
        !signature(time_class,"shortTimeDisplayIdentifier","@16@0:8",YES) ||
        !signature(time_class,"pillTimeDisplayIdentifier","@16@0:8",YES) ||
        !signature(time_class,"viewForIdentifier:","@24@0:8@16",NO)) {
        ui_log("refused native status-bar method ABI differs"); return;
    }
    Method method=class_getInstanceMethod(bar,sel_registerName("layoutSubviews"));
    IMP original=method_getImplementation(method);
    if (!native_uuid(original)) { ui_log("refused UIKitCore UUID differs"); return; }
    native_layout=(void (*)(id,SEL))original;
    method_setImplementation(method,(IMP)cutout_layout);
    ui_log("installed native status-bar adapter full-panel=1080x2340 logical=1125x2436 camera=0,0,145,136");
}
