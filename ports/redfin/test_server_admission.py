"""Actual native forwarding must preserve each argument/result without forcing rendering."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from test_display_geometry import function
from ports.redfin import server_admission_abi
from ports.redfin.graphics_abi import Cache

HERE=Path(__file__).resolve().parent


class ServerAdmissionTests(unittest.TestCase):
    def test_pinned_actual_server_inventory_covers_every_original_method(self):
        with Cache() as c:proof=server_admission_abi.derive(c)
        self.assertEqual(len(proof['methods']),23)
        self.assertEqual(sum(m['observe_original_calls'] for m in proof['methods'].values()),8)
        self.assertFalse(proof['forces_render']);self.assertFalse(proof['changes_display_state'])
        self.assertFalse(proof['queries_create_server'])

    def test_actual_callbacks_forward_once_preserve_uint_bool_double_and_object_arguments(self):
        actual=(HERE/'server-admission.m').read_text()
        names=['admission_record','admission_update','admission_render','admission_can_update','admission_can_flags',
               'admission_set_enabled','admission_set_disabled','admission_set_compositing','admission_power']
        bodies='\n'.join(function(actual,('static BOOL ' if n in ('admission_can_update','admission_can_flags') else 'static void ')+n+'(') for n in names)
        structure=re.search(r'struct admission_call\s*\{[^}]+\};',actual).group()
        source=r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <assert.h>
#include <stdint.h>
#include <math.h>
enum{
#define RF_SERVER_METHOD(key,cls,selector,types,meta,hook) RF_AD_##key,
#include "server-admission-methods.def"
#undef RF_SERVER_METHOD
 RF_AD_COUNT
};
'''+structure+r'''
static struct admission_call admission_calls[RF_AD_COUNT];
static IMP admission_original[RF_AD_COUNT];
static bool admission_active;static double now;
static double admission_clock(void){return now;}
static id expected_object,expected_notification;static SEL expected_selector;
static unsigned originals,last_flags;static BOOL last_bool;static double last_time;
static void mark(id object,SEL selector){assert(object==expected_object&&selector==expected_selector);++originals;now+=0.000001;}
static void update(id o,SEL s){mark(o,s);}
static void render(id o,SEL s,double t){mark(o,s);last_time=t;}
static BOOL can(id o,SEL s,BOOL b){mark(o,s);last_bool=b;return !b;}
static BOOL flags(id o,SEL s,unsigned f){mark(o,s);last_flags=f;return (f&0x20)!=0;}
static void set(id o,SEL s,BOOL b){mark(o,s);last_bool=b;}
static void power(id o,SEL s,id n){mark(o,s);assert(n==expected_notification);}
'''+bodies+r'''
int main(){@autoreleasepool{
 expected_object=[NSObject new];expected_notification=[NSObject new];expected_selector=sel_registerName("unchanged:");
 admission_original[RF_AD_DISPLAY_UPDATE]=(IMP)update;admission_original[RF_AD_DISPLAY_RENDER]=(IMP)render;
 admission_original[RF_AD_DISPLAY_CAN_UPDATE]=(IMP)can;admission_original[RF_AD_DISPLAY_CAN_FLAGS]=(IMP)flags;
 admission_original[RF_AD_DISPLAY_SET_ENABLED]=(IMP)set;admission_original[RF_AD_DISPLAY_SET_DISABLED]=(IMP)set;
 admission_original[RF_AD_DISPLAY_SET_COMPOSITING]=(IMP)set;admission_original[RF_AD_DISPLAY_POWER]=(IMP)power;
 for(unsigned enabled=0;enabled<2;++enabled){
  admission_active=enabled;unsigned before=originals;
  admission_update(expected_object,expected_selector);
  admission_render(expected_object,expected_selector,123.75);assert(last_time==123.75);
  assert(admission_can_update(expected_object,expected_selector,NO)&&!last_bool);
  assert(!admission_can_update(expected_object,expected_selector,YES)&&last_bool);
  assert(admission_can_flags(expected_object,expected_selector,UINT32_MAX)&&last_flags==UINT32_MAX);
  assert(!admission_can_flags(expected_object,expected_selector,0)&&last_flags==0);
  admission_set_enabled(expected_object,expected_selector,YES);assert(last_bool);
  admission_set_disabled(expected_object,expected_selector,NO);assert(!last_bool);
  admission_set_compositing(expected_object,expected_selector,YES);assert(last_bool);
  admission_power(expected_object,expected_selector,expected_notification);
  assert(originals==before+10);
  assert(admission_calls[RF_AD_DISPLAY_RENDER].calls==enabled);
 }
 assert(admission_calls[RF_AD_DISPLAY_CAN_UPDATE].calls==2&&admission_calls[RF_AD_DISPLAY_CAN_UPDATE].allowed==1&&admission_calls[RF_AD_DISPLAY_CAN_UPDATE].denied==1);
 assert(admission_calls[RF_AD_DISPLAY_CAN_FLAGS].allowed==1&&admission_calls[RF_AD_DISPLAY_CAN_FLAGS].denied==1);
 for(unsigned i=0;i<RF_AD_COUNT;++i)if(admission_calls[i].calls){assert(admission_calls[i].ns>0&&admission_calls[i].maximum>0);}
}return 0;}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'forward.m';path.write_text(source)
            built=subprocess.run(['xcrun','clang','-fobjc-arc','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),'-framework','Foundation',str(path),'-o',str(root/'forward')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(root/'forward')],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
