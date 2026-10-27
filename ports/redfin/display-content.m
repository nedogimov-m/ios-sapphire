/* SPDX-License-Identifier: MIT
 * Observe an existing, visible, attached content tree. Never create a window,
 * context, view, surface, scene or replacement layer to manufacture a workload.
 */
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <math.h>
#include <string.h>
#include "native-image-uuid.h"
#include "display-content.h"

static BOOL content_methods_ready(void)
{
    static BOOL attempted,ready;
    if(attempted)return ready;
    attempted=YES;
    const uint8_t uikit[16]={REDFIN_UIKIT_UUID_BYTES},quartz[16]={REDFIN_QUARTZ_UUID_BYTES};
    const struct {const char *cls,*selector,*types;BOOL meta,ui;} methods[]={
        {"UIWindow","_hasContext","B16@0:8",NO,YES},
        {"UIWindow","_contextId","I16@0:8",NO,YES},
        {"UIWindow","_isVisible","B16@0:8",NO,YES},
        {"UIWindow","allWindowsIncludingInternalWindows:onlyVisibleWindows:forScreen:","@32@0:8B16B20@24",YES,YES},
        {"CALayer","context","@16@0:8",NO,NO},
        {"CAContext","contextId","I16@0:8",NO,NO},
        {"CAContext","displayId","I16@0:8",NO,NO},
        {"CAContext","commitId","I16@0:8",NO,NO},
    };
    for(unsigned i=0;i<sizeof(methods)/sizeof(methods[0]);++i) {
        Class cls=objc_getClass(methods[i].cls);
        SEL selector=sel_registerName(methods[i].selector);
        Method method=methods[i].meta?class_getClassMethod(cls,selector):class_getInstanceMethod(cls,selector);
        if(!method||strcmp(method_getTypeEncoding(method),methods[i].types)||
           !redfin_native_image_uuid((const void *)method_getImplementation(method),methods[i].ui?uikit:quartz))return NO;
    }
    ready=YES;return YES;
}

static BOOL content_window_visible(UIWindow *window)
{
    if(!window||!content_methods_ready()||window.hidden||!isfinite(window.alpha)||window.alpha<0.99||
       window.screen!=UIScreen.mainScreen)return NO;
    Class dimmer=objc_getClass("_UISoftwareDimmingWindow");
    if(dimmer&&[window isKindOfClass:dimmer])return NO;
    if(!((BOOL (*)(id,SEL))objc_msgSend)(window,sel_registerName("_hasContext"))||
       !((BOOL (*)(id,SEL))objc_msgSend)(window,sel_registerName("_isVisible")))return NO;
    CGSize wanted=UIScreen.mainScreen.bounds.size,size=window.bounds.size;
    if(!isfinite(size.width)||!isfinite(size.height)||size.width<wanted.width*0.9||size.height<wanted.height*0.9)return NO;
    UIWindowScene *scene=window.windowScene;
    return !scene||scene.activationState==UISceneActivationStateForegroundActive||
        scene.activationState==UISceneActivationStateForegroundInactive;
}

uint32_t redfin_display_content_context(UIWindow *window,CALayer *layer)
{
    if(!content_window_visible(window)||!layer||layer==window.layer)return 0;
    BOOL attached=NO;
    unsigned ancestors=0;
    for(CALayer *at=layer;at&&ancestors++<128;at=at.superlayer) {
        if(at.hidden||!isfinite(at.opacity)||at.opacity<0.01||!isfinite(at.speed)||at.speed<=0)return 0;
        if(at==window.layer){attached=YES;break;}
    }
    if(!attached)return 0;
    id context=((id (*)(id,SEL))objc_msgSend)(layer,sel_registerName("context"));
    if(!context)context=((id (*)(id,SEL))objc_msgSend)(window.layer,sel_registerName("context"));
    Class cls=objc_getClass("CAContext");
    if(!context||!cls||![context isKindOfClass:cls])return 0;
    uint32_t wanted=((uint32_t (*)(id,SEL))objc_msgSend)(window,sel_registerName("_contextId"));
    uint32_t actual=((uint32_t (*)(id,SEL))objc_msgSend)(context,sel_registerName("contextId"));
    return wanted&&wanted==actual?wanted:0;
}

bool redfin_display_content_snapshot(UIWindow *window,CALayer *layer,struct redfin_content_state *state)
{
    uint32_t context=redfin_display_content_context(window,layer);
    if(!state||!context)return false;
    id native=((id (*)(id,SEL))objc_msgSend)(layer,sel_registerName("context"));
    if(!native)native=((id (*)(id,SEL))objc_msgSend)(window.layer,sel_registerName("context"));
    struct redfin_content_state observed={context,
        ((uint32_t (*)(id,SEL))objc_msgSend)(native,sel_registerName("displayId")),
        ((uint32_t (*)(id,SEL))objc_msgSend)(native,sel_registerName("commitId"))};
    *state=observed;return true;
}

static BOOL content_intersects(CALayer *layer,CALayer *root)
{
    CGRect visible=[layer convertRect:layer.bounds toLayer:root];
    if(!(isfinite(visible.origin.x)&&isfinite(visible.origin.y)&&
        isfinite(visible.size.width)&&isfinite(visible.size.height)&&
        visible.size.width>0&&visible.size.height>0))return NO;
    unsigned count=0;
    for(CALayer *at=layer.superlayer;at&&at!=root&&count++<128;at=at.superlayer)
        if(at.masksToBounds)visible=CGRectIntersection(visible,[at convertRect:at.bounds toLayer:root]);
    return CGRectIntersectsRect(visible,root.bounds);
}

static BOOL content_has_pixels(CALayer *root)
{
    __unsafe_unretained CALayer *pending[256];unsigned count=1,visited=0;
    pending[0]=root;
    while(count&&visited++<256) {
        CALayer *layer=pending[--count];
        if(layer.hidden||layer.opacity<0.01||!content_intersects(layer,root))continue;
        if(layer.contents)return YES;
        for(CALayer *child in layer.sublayers) {
            if(count==256)return NO;
            pending[count++]=child;
        }
    }
    return NO;
}

CALayer *redfin_display_content_layer(UIWindow *window)
{
    if(!NSThread.isMainThread||!content_window_visible(window))return nil;
    // viewIfLoaded observes the existing tree without starting another scene.
    UIView *view=window.rootViewController.viewIfLoaded;
    CALayer *preferred=view.window==window?view.layer:nil;
    if(preferred&&redfin_display_content_context(window,preferred)&&content_intersects(preferred,window.layer)&&
       content_has_pixels(preferred))return preferred;
    for(CALayer *layer in window.layer.sublayers.reverseObjectEnumerator)
        if(redfin_display_content_context(window,layer)&&content_intersects(layer,window.layer)&&
           content_has_pixels(layer))return layer;
    return nil;
}

static NSArray *content_windows(void)
{
    if(!NSThread.isMainThread||!content_methods_ready())return nil;
    id found=((id (*)(id,SEL,BOOL,BOOL,id))objc_msgSend)(UIWindow.class,
        sel_registerName("allWindowsIncludingInternalWindows:onlyVisibleWindows:forScreen:"),YES,YES,UIScreen.mainScreen);
    return [found isKindOfClass:NSArray.class]&&[found count]<=128?found:nil;
}

UIWindow *redfin_display_content_window(UIWindow *fallback)
{
    NSArray *windows=content_windows();if(!windows)return nil;
    for(UIWindow *window in windows)
        if([window isKindOfClass:UIWindow.class]&&window.isKeyWindow&&redfin_display_content_layer(window))return window;
    for(UIWindow *window in windows.reverseObjectEnumerator)
        if([window isKindOfClass:UIWindow.class]&&window.windowLevel<=UIWindowLevelStatusBar&&
           redfin_display_content_layer(window))return window;
    return redfin_display_content_layer(fallback)?fallback:nil;
}

void redfin_display_content_trace(uint64_t nonce,void (*output)(uint64_t,const char *,...))
{
    if(!output)return;
    NSArray *windows=content_windows();
    output(nonce,"content-inventory native-ABI=%u windows=%lu bounded=12 no-view-or-context-created=1",
        content_methods_ready(),(unsigned long)windows.count);
    unsigned count=0;
    for(UIWindow *window in windows) {
        if(count++==12)break;
        if(![window isKindOfClass:UIWindow.class])continue;
        UIView *view=window.rootViewController.viewIfLoaded;
        CALayer *target=redfin_display_content_layer(window);
        output(nonce,"content-window class=%s key=%u visible=%u hidden=%u alpha=%.3f level=%.3f scene=%ld root-loaded=%u view-attached=%u root-sublayers=%lu root-speed=%.3f target=%s context=%u",
            class_getName(window.class),window.isKeyWindow,content_window_visible(window),window.hidden,
            window.alpha,(double)window.windowLevel,window.windowScene?(long)window.windowScene.activationState:-9,
            view!=nil,view.window==window,(unsigned long)window.layer.sublayers.count,(double)window.layer.speed,
            target?class_getName(target.class):"none",redfin_display_content_context(window,target));
    }
}
