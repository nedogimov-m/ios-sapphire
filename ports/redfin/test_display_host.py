"""Actual content selection rejects unattached, empty, clipped and paused trees."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent

UIKIT=r'''
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#define CALayer RFTestLayer
#define CAContext RFTestContext
@class UIWindow,CAContext;
typedef NS_ENUM(NSInteger,UISceneActivationState){UISceneActivationStateUnattached=-1,UISceneActivationStateForegroundActive,UISceneActivationStateForegroundInactive,UISceneActivationStateBackground};
@interface UIScreen:NSObject
+ (UIScreen *)mainScreen;
@property(nonatomic) CGRect bounds;
@end
@interface UIWindowScene:NSObject
@property(nonatomic) UISceneActivationState activationState;
@end
@interface CALayer:NSObject
@property(nonatomic) CGRect bounds;
@property(nonatomic) CGPoint offset;
@property(nonatomic) float opacity,speed;
@property(nonatomic) BOOL hidden,masksToBounds;
@property(nonatomic,strong) id contents;
@property(nonatomic,strong) NSArray *sublayers;
@property(nonatomic,weak) CALayer *superlayer;
@property(nonatomic,strong) CAContext *ownedContext;
- (id)context;
- (CGRect)convertRect:(CGRect)rect toLayer:(CALayer *)layer;
@end
@interface CAContext:NSObject
@property(nonatomic) uint32_t contextId,displayId,commitId;
@end
@interface UIView:NSObject
@property(nonatomic,weak) UIWindow *window;
@property(nonatomic,strong) CALayer *layer;
@end
@interface UIViewController:NSObject
@property(nonatomic,strong) UIView *viewIfLoaded;
@end
@interface UIWindow:NSObject
@property(nonatomic,strong) UIScreen *screen;
@property(nonatomic,strong) CALayer *layer;
@property(nonatomic,strong) UIWindowScene *windowScene;
@property(nonatomic,strong) UIViewController *rootViewController;
@property(nonatomic) CGRect bounds;
@property(nonatomic) BOOL hidden,isKeyWindow,nativeVisible,hasContext;
@property(nonatomic) double alpha,windowLevel;
@property(nonatomic) uint32_t nativeId;
- (BOOL)_hasContext;
- (BOOL)_isVisible;
- (uint32_t)_contextId;
+ (NSArray *)allWindowsIncludingInternalWindows:(BOOL)internal onlyVisibleWindows:(BOOL)visible forScreen:(UIScreen *)screen;
@end
@interface _UISoftwareDimmingWindow:UIWindow
@end
@interface UIApplication:NSObject
@property(nonatomic,strong) NSArray *windows,*internalWindows;
+ (UIApplication *)sharedApplication;
@end
static const double UIWindowLevelStatusBar=1000;
'''

FIXTURE=r'''
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#include <assert.h>
#include "display-content.h"
static unsigned context_id_reads;
@implementation UIScreen
+ (UIScreen *)mainScreen{static UIScreen *s;if(!s){s=[UIScreen new];s.bounds=CGRectMake(0,0,375,812);}return s;}
@end
@implementation UIWindowScene
@end
@implementation CALayer
@synthesize sublayers=_sublayers;
- (instancetype)init{if((self=[super init])){_bounds=UIScreen.mainScreen.bounds;_opacity=_speed=1;}return self;}
- (void)setSublayers:(NSArray *)layers{for(CALayer *l in _sublayers)if(l.superlayer==self)l.superlayer=nil;_sublayers=layers;for(CALayer *l in layers)l.superlayer=self;}
- (id)context{return self.ownedContext?:self.superlayer.context;}
- (CGRect)convertRect:(CGRect)r toLayer:(CALayer *)root{for(CALayer *l=self;l&&l!=root;l=l.superlayer){r.origin.x+=l.offset.x;r.origin.y+=l.offset.y;}return r;}
@end
@implementation CAContext
@end
@implementation UIView
@end
@implementation UIViewController
@end
@implementation UIWindow
- (instancetype)init{if((self=[super init])){_screen=UIScreen.mainScreen;_bounds=_screen.bounds;_alpha=1;_layer=[CALayer new];_hasContext=_nativeVisible=YES;_nativeId=31;_layer.ownedContext=[CAContext new];_layer.ownedContext.contextId=_nativeId;_windowScene=[UIWindowScene new];}return self;}
- (BOOL)_hasContext{return self.hasContext;}
- (BOOL)_isVisible{return self.nativeVisible;}
- (uint32_t)_contextId{++context_id_reads;return self.nativeId;}
+ (NSArray *)allWindowsIncludingInternalWindows:(BOOL)internal onlyVisibleWindows:(BOOL)visible forScreen:(UIScreen *)s{assert(internal&&visible&&s==UIScreen.mainScreen);return UIApplication.sharedApplication.internalWindows;}
@end
@implementation _UISoftwareDimmingWindow
@end
@implementation UIApplication
+ (UIApplication *)sharedApplication{static UIApplication *a;if(!a)a=[UIApplication new];return a;}
@end
static CALayer *content(UIWindow *w){
 CALayer *root=[CALayer new],*pixels=[CALayer new];pixels.bounds=CGRectMake(0,0,30,30);pixels.contents=@1;root.sublayers=@[pixels];w.layer.sublayers=@[root];
 UIView *view=[UIView new];view.window=w;view.layer=root;w.rootViewController=[UIViewController new];w.rootViewController.viewIfLoaded=view;return root;
}
int main(){@autoreleasepool{
 UIWindow *w=[UIWindow new];CALayer *target=content(w),*pixels=target.sublayers[0];
 UIWindow *empty=[UIWindow new];empty.isKeyWindow=YES;empty.layer.sublayers=@[[CALayer new]];
 UIWindow *dimmer=[_UISoftwareDimmingWindow new];dimmer.isKeyWindow=YES;(void)content(dimmer);
 UIApplication.sharedApplication.windows=@[];UIApplication.sharedApplication.internalWindows=@[w,empty,dimmer];
 assert(!redfin_display_content_layer(empty)&&!redfin_display_content_layer(dimmer));
 assert(redfin_display_content_window(empty)==w&&redfin_display_content_layer(w)==target);
 assert(redfin_display_content_context(w,target)==31&&!redfin_display_content_context(w,w.layer));
 struct redfin_content_state state={0};w.layer.ownedContext.displayId=4;w.layer.ownedContext.commitId=9;
 assert(redfin_display_content_snapshot(w,target,&state)&&state.context==31&&state.display==4&&state.commit==9);
 assert(empty.isKeyWindow&&!w.isKeyWindow&&w.alpha==1&&w.layer.sublayers[0]==target);
 w.hidden=YES;assert(!redfin_display_content_window(empty));w.hidden=NO;
 w.nativeVisible=NO;assert(!redfin_display_content_layer(w));w.nativeVisible=YES;
 w.hasContext=NO;unsigned reads=context_id_reads;assert(!redfin_display_content_layer(w)&&context_id_reads==reads);w.hasContext=YES;
 w.windowScene.activationState=UISceneActivationStateBackground;assert(!redfin_display_content_layer(w));w.windowScene.activationState=UISceneActivationStateForegroundInactive;assert(redfin_display_content_layer(w)==target);
 w.layer.speed=0;assert(!redfin_display_content_layer(w));w.layer.speed=1;
 pixels.hidden=YES;assert(!redfin_display_content_layer(w));pixels.hidden=NO;
 pixels.opacity=0;assert(!redfin_display_content_layer(w));pixels.opacity=1;
 pixels.offset=CGPointMake(4000,0);assert(!redfin_display_content_layer(w));pixels.offset=CGPointZero;
 CALayer *clip=[CALayer new];clip.bounds=CGRectMake(0,0,10,10);clip.masksToBounds=YES;clip.sublayers=@[pixels];pixels.offset=CGPointMake(100,100);target.sublayers=@[clip];assert(!redfin_display_content_layer(w));clip.masksToBounds=NO;assert(redfin_display_content_layer(w)==target);
 target.ownedContext=[CAContext new];target.ownedContext.contextId=99;assert(!redfin_display_content_layer(w));target.ownedContext=nil;
 // Replacement of a content tree invalidates the old identity even when the
 // original controller still references it. The actual attached child wins.
 CALayer *replacement=[CALayer new],*image=[CALayer new];image.contents=@1;replacement.sublayers=@[image];w.layer.sublayers=@[replacement];
 assert(!redfin_display_content_context(w,target)&&redfin_display_content_layer(w)==replacement);
 NSMutableArray *oversized=[NSMutableArray new];for(unsigned i=0;i<129;++i)[oversized addObject:w];UIApplication.sharedApplication.internalWindows=oversized;assert(!redfin_display_content_window(w));
 assert(w.layer.speed==1&&!w.hidden&&w.nativeVisible&&w.hasContext&&w.layer.sublayers[0]==replacement);
}return 0;}
'''


@unittest.skipUnless(sys.platform=='darwin','native Objective-C runtime required')
class DisplayHostTests(unittest.TestCase):
    def test_real_selection_requires_attached_context_and_visible_content(self):
        with tempfile.TemporaryDirectory(prefix='redfin-display-content-') as directory:
            root=Path(directory)
            headers={'UIKit/UIKit.h':UIKIT,'QuartzCore/QuartzCore.h':'',
                'native-image-uuid.h':r'''
#include <stdint.h>
#include <string.h>
#include <objc/runtime.h>
#define REDFIN_UIKIT_UUID_BYTES 0
#define REDFIN_QUARTZ_UUID_BYTES 0
static int redfin_native_image_uuid(const void *p,const uint8_t *u){return p&&u;}
static Class redfin_fixture_class(const char *name){
 if(!strcmp(name,"CALayer"))return objc_getClass("RFTestLayer");
 if(!strcmp(name,"CAContext"))return objc_getClass("RFTestContext");
 return objc_getClass(name);
}
#define objc_getClass redfin_fixture_class
'''}
            for name,data in headers.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(data)
            (root/'content.m').write_bytes((HERE/'display-content.m').read_bytes())
            (root/'fixture.m').write_text(FIXTURE)
            built=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(root),'-I'+str(HERE),'-framework','Foundation','-framework','CoreGraphics',
                str(root/'content.m'),str(root/'fixture.m'),'-o',str(root/'content')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(root/'content')],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
