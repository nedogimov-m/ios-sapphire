"""The finite workload must select a visible content window, excluding dimmers."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


@unittest.skipUnless(sys.platform=='darwin','native Objective-C runtime required')
class DisplayHostTests(unittest.TestCase):
    def test_empty_key_window_or_native_software_dimmer_cannot_own_the_workload(self):
        actual=(HERE/'display-probe.m').read_text()
        body='\n'.join(function(actual,name) for name in (
            'static BOOL fullscreen_window(', 'static UIWindow *animation_host('))
        source=r'''
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <objc/runtime.h>
#include <assert.h>
@interface UIScreen:NSObject
+ (UIScreen *)mainScreen;
@property(nonatomic) CGRect bounds;
@end
@implementation UIScreen
+ (UIScreen *)mainScreen{static UIScreen *s;if(!s){s=[UIScreen new];s.bounds=CGRectMake(0,0,375,812);}return s;}
@end
@interface CALayer:NSObject
@property(nonatomic,strong) NSArray *sublayers;
@property(nonatomic,strong) id contents;
@end
@implementation CALayer
@end
@interface UIWindow:NSObject
@property(nonatomic,strong) UIScreen *screen;
@property(nonatomic,strong) CALayer *layer;
@property(nonatomic) CGRect bounds;
@property(nonatomic) BOOL hidden,isKeyWindow;
@property(nonatomic) double alpha,windowLevel;
@end
@implementation UIWindow
- (instancetype)init{if((self=[super init])){_screen=UIScreen.mainScreen;_bounds=_screen.bounds;_alpha=1;_layer=[CALayer new];}return self;}
@end
@interface _UISoftwareDimmingWindow:UIWindow
@end
@implementation _UISoftwareDimmingWindow
@end
@interface UIApplication:NSObject
@property(nonatomic,strong) NSArray *windows;
+ (UIApplication *)sharedApplication;
@end
@implementation UIApplication
+ (UIApplication *)sharedApplication{static UIApplication *app;if(!app)app=[UIApplication new];return app;}
@end
static const double UIWindowLevelStatusBar=1000;
'''+body+r'''
int main(){@autoreleasepool{
 UIWindow *content=[UIWindow new];content.layer.sublayers=@[@1];
 UIWindow *empty=[UIWindow new];empty.isKeyWindow=YES;
 UIWindow *dimmer=[_UISoftwareDimmingWindow new];dimmer.isKeyWindow=YES;dimmer.layer.sublayers=@[@1];
 UIApplication.sharedApplication.windows=@[content,empty,dimmer];
 assert(!fullscreen_window(empty)&&!fullscreen_window(dimmer)&&fullscreen_window(content));
 assert(animation_host(empty)==content);
 content.hidden=YES;assert(!animation_host(empty));content.hidden=NO;
 content.alpha=0.5;assert(!animation_host(empty));content.alpha=1;
 content.windowLevel=2000;assert(!animation_host(empty));content.windowLevel=0;
 content.layer.sublayers=nil;content.layer.contents=@1;assert(animation_host(empty)==content);
 assert(empty.isKeyWindow&&dimmer.isKeyWindow&&!content.hidden&&content.alpha==1);
}return 0;}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-display-host-') as directory:
            root=Path(directory);path=root/'host.m';path.write_text(source)
            compiled=subprocess.run(['xcrun','clang','-fobjc-arc','-fblocks','-O2','-Wall','-Wextra','-Werror',
                '-framework','Foundation','-framework','CoreGraphics',str(path),'-o',str(root/'host')],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(root/'host')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
