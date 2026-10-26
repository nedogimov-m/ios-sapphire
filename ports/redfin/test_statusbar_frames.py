"""Exercise the production late-clock hooks on the real Objective-C runtime."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


@unittest.skipUnless(sys.platform=='darwin','requires the native Objective-C runtime')
class StatusBarFrameTests(unittest.TestCase):
    def test_late_native_frames_inheritance_and_weak_ownership_preserve_other_views(self):
        actual=(HERE/'statusbar-cutout.m').read_text()
        actual=actual[actual.index('@interface RedfinClockBinding'):actual.index('static void cutout_layout(')]
        source=r'''
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <objc/runtime.h>
#include <assert.h>
#include <math.h>
#include <string.h>
#include "statusbar-geometry.h"
@class UIWindow;
@interface UIScreen : NSObject
+ (UIScreen *)mainScreen;
- (id)fixedCoordinateSpace;
- (CGRect)bounds;
@end
@implementation UIScreen
+ (UIScreen *)mainScreen {static UIScreen *screen; if(!screen)screen=[UIScreen new];return screen;}
- (id)fixedCoordinateSpace{return self;}
- (CGRect)bounds{return CGRectMake(0,0,375,812);}
@end
@interface UIView : NSObject {CGRect _bounds;CGPoint _center;}
@property(nonatomic,weak) UIWindow *window;
@property(nonatomic,weak) UIView *superview;
@property(nonatomic) BOOL hidden;
@property(nonatomic) double alpha;
@property(nonatomic) CGRect frame,bounds;
@property(nonatomic) CGPoint center;
@property(nonatomic) unsigned nativeFrames;
- (void)layoutSubviews;
- (CGRect)convertRect:(CGRect)rect toView:(UIView *)view;
- (CGPoint)convertPoint:(CGPoint)point fromView:(UIView *)view;
@end
@implementation UIView
- (instancetype)init {if((self=[super init]))_alpha=1;return self;}
- (CGRect)frame{return CGRectMake(_center.x-_bounds.size.width/2,_center.y-_bounds.size.height/2,_bounds.size.width,_bounds.size.height);}
- (void)setFrame:(CGRect)value{_bounds.size=value.size;_center=CGPointMake(CGRectGetMidX(value),CGRectGetMidY(value));++self.nativeFrames;}
- (CGRect)bounds{return _bounds;}
- (void)setBounds:(CGRect)value{_bounds=value;}
- (CGPoint)center{return _center;}
- (void)setCenter:(CGPoint)value{_center=value;}
- (void)layoutSubviews{self.center=CGPointMake(45,23);}
- (CGRect)convertRect:(CGRect)rect toView:(UIView *)view{(void)view;CGRect frame=self.frame;rect.origin.x+=frame.origin.x-_bounds.origin.x;rect.origin.y+=frame.origin.y-_bounds.origin.y;return rect;}
- (CGPoint)convertPoint:(CGPoint)point fromView:(UIView *)view{(void)view;return point;}
@end
@interface UIWindow : UIView
@property(nonatomic,strong) UIScreen *screen;
- (CGRect)convertRect:(CGRect)rect fromCoordinateSpace:(id)space;
@end
@implementation UIWindow
- (CGRect)convertRect:(CGRect)rect fromCoordinateSpace:(id)space{(void)space;return rect;}
@end
@interface NativeClock : UIView
@end
@implementation NativeClock
- (void)setFrame:(CGRect)value{[super setFrame:value];}
@end
@interface ChildClock : NativeClock
@end
@implementation ChildClock
- (void)setFrame:(CGRect)value{[super setFrame:value];}
@end
static __thread bool in_layout;
static void ui_log(const char *format,...){(void)format;}
static BOOL native_uuid(IMP implementation){return implementation!=NULL;}
static BOOL signature(Class cls,const char *name,const char *types,BOOL meta){
 Method method=meta?class_getClassMethod(cls,sel_registerName(name)):class_getInstanceMethod(cls,sel_registerName(name));
 return method&&!strcmp(method_getTypeEncoding(method),types);
}
static struct redfin_ui_rect rectangle(CGRect r){return (struct redfin_ui_rect){r.origin.x,r.origin.y,r.size.width,r.size.height};}
'''+actual+r'''
static void check(UIView *clock){assert(fabs(clock.frame.origin.x-(375.0*145/1080+3))<1e-8);}
int main(){@autoreleasepool{
 UIWindow *window=[UIWindow new];window.screen=UIScreen.mainScreen;window.frame=CGRectMake(0,0,375,812);
 UIView *bar=[UIView new];bar.window=window;bar.frame=window.frame;
 IMP base=class_getMethodImplementation(UIView.class,@selector(setCenter:));
 for(Class cls in @[NativeClock.class,ChildClock.class]){
  UIView *clock=[cls new];clock.window=window;clock.superview=bar;
  clock.frame=CGRectMake(21,14,30,18);assert(bind_clock(clock,bar));correct_clock(clock,NO);check(clock);
  for(unsigned i=0;i<30;++i){
   unsigned frames=clock.nativeFrames;
   clock.frame=CGRectMake(21,14,29+i%3,18);check(clock);assert(clock.nativeFrames==frames+1);
   clock.center=CGPointMake(40,23);check(clock);
   clock.bounds=CGRectMake(0,0,60,18);check(clock);
   [clock layoutSubviews];check(clock);
  }
  UIView *unrelated=[cls new];unrelated.window=window;unrelated.superview=bar;
  unrelated.frame=CGRectMake(21,14,30,18);assert(unrelated.frame.origin.x==21);
  in_layout=true;clock.frame=CGRectMake(21,14,30,18);assert(clock.frame.origin.x==21);in_layout=false;
  correct_clock(clock,NO);check(clock);
  UIView *temporary=[UIView new];temporary.window=window;assert(bind_clock(clock,temporary));
  __weak UIView *weak=temporary;temporary=nil;assert(!weak);
  clock.frame=CGRectMake(21,14,30,18);assert(clock.frame.origin.x==21);
 }
 assert(class_getMethodImplementation(UIView.class,@selector(setCenter:))==base);
 assert(clock_hook_count==2);
}return 0;}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-clock-frames-') as directory:
            path=Path(directory)/'frames.m';path.write_text(source);exe=path.with_suffix('')
            compiled=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),'-framework','Foundation','-framework','CoreGraphics',str(path),'-o',str(exe)],
                capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
