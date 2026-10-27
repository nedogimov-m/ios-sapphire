"""The real finite animation owns its key and never changes the target model."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class DisplayContentAnimationTests(unittest.TestCase):
    def test_native_animation_admission_clock_collision_and_cleanup(self):
        actual=function((HERE/'display-probe.m').read_text(),'static BOOL content_animation(')
        source='''#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#include <assert.h>
#include <math.h>
'''+actual+'''
int main(){@autoreleasepool{
 CALayer *parent=[CALayer layer],*layer=[CALayer layer];[parent addSublayer:layer];
 parent.speed=0.75;parent.timeOffset=1.25;
 CATransform3D original=CATransform3DMakeTranslation(7,9,0);layer.transform=original;
 CABasicAnimation *other=[CABasicAnimation animationWithKeyPath:@"opacity"];other.duration=100;
 [layer addAnimation:other forKey:@"system-owner"];
 assert(!content_animation(nil,@"owned",1,40)&&!content_animation(layer,@"owned",NAN,40));
 CFTimeInterval before=[layer convertTime:CACurrentMediaTime() fromLayer:nil];
 assert(content_animation(layer,@"owned",1,40));
 CFTimeInterval after=[layer convertTime:CACurrentMediaTime() fromLayer:nil];
 CABasicAnimation *created=(CABasicAnimation *)[layer animationForKey:@"owned"];
 assert([created.keyPath isEqualToString:@"transform.translation.x"]&&created.additive&&created.autoreverses);
 assert(created.beginTime>=before&&created.beginTime<=after&&created.repeatDuration==40);
 assert(CATransform3DEqualToTransform(original,layer.transform)&&parent.speed==0.75&&parent.timeOffset==1.25);
 assert(!content_animation(layer,@"owned",1,40)&&[layer animationForKey:@"system-owner"]);
 [layer removeAnimationForKey:@"owned"];
 assert(![layer animationForKey:@"owned"]&&[layer animationForKey:@"system-owner"]&&CATransform3DEqualToTransform(original,layer.transform));
}return 0;}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'animation.m';path.write_text(source)
            built=subprocess.run(['xcrun','clang','-fobjc-arc','-O2','-Wall','-Wextra','-Werror',
                '-framework','Foundation','-framework','QuartzCore',str(path),'-o',str(root/'animation')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(root/'animation')],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
