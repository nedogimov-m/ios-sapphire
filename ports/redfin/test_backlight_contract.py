"""Execute actual backlight property publication and native parameter requests."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from ports.redfin import brightness_abi

HERE=Path(__file__).resolve().parent


class BacklightContractTests(unittest.TestCase):
    def test_native_property_types_and_raw_nits_requests_match_actual_driver(self):
        actual=(HERE/'display-controls.inc').read_text()
        body='\n'.join(function(actual,name) for name in (
            'static bool redfin_backlight_parameters(',
            'static bool redfin_legacy_brightness_nits(',
            'IOReturn AppleCLCD::redfinBacklightProperties('))
        source=r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <map>
#include <string>
#include "controls-policy.h"
using IOReturn=int;enum{kIOReturnSuccess,kIOReturnBadArgument};
struct OSObject {unsigned refs=1;virtual ~OSObject(){};void retain(){++refs;}void release(){assert(refs);if(!--refs)delete this;}};
struct OSNumber:OSObject {uint64_t value;explicit OSNumber(uint64_t n):value(n){}
 static OSNumber *withNumber(uint64_t n,unsigned bits){(void)bits;return new OSNumber(n);}
 uint64_t unsigned64BitValue(){return value;}};
struct OSDictionary:OSObject {std::map<std::string,OSObject *> items;
 static OSDictionary *withCapacity(unsigned n){(void)n;return new OSDictionary;}
 ~OSDictionary(){for(auto &p:items)p.second->release();}
 bool setObject(const char *key,OSObject *value){if(!value)return false;value->retain();auto it=items.find(key);if(it!=items.end())it->second->release();items[key]=value;return true;}
 OSObject *getObject(const char *key){auto it=items.find(key);return it==items.end()?nullptr:it->second;}};
#define OSDynamicCast(type,value) dynamic_cast<type *>(value)
#define OSSafeReleaseNULL(value) do{if(value){value->release();value=nullptr;}}while(0)
struct AppleARMBacklight {OSDictionary *properties=OSDictionary::withCapacity(3);
 ~AppleARMBacklight(){properties->release();}
 bool setProperty(const char *key,OSObject *object){return properties->setObject(key,object);}
 bool setProperty(const char *key,uint64_t value,unsigned width){OSNumber *number=OSNumber::withNumber(value,width);bool ok=setProperty(key,number);number->release();return ok;}};
struct redfin_display_controls {AppleARMBacklight *backlight;};
struct AppleCLCD {redfin_display_controls *fRedfinControls;uint64_t last=0;unsigned requests=0;
 IOReturn redfinSetBrightness(uint64_t nits){uint32_t level=0;if(!rf_panel_nits_to_dbv(nits,&level))return kIOReturnBadArgument;last=nits;++requests;return kIOReturnSuccess;}
 IOReturn redfinBacklightProperties(OSObject *);};
static void IOLog(const char *format,...){(void)format;}
'''+body+r'''
static uint64_t number(OSDictionary *d,const char *key){auto *n=OSDynamicCast(OSNumber,d->getObject(key));assert(n);return n->unsigned64BitValue();}
static void put(OSDictionary *d,const char *key,uint64_t value){auto *n=OSNumber::withNumber(value,64);assert(d->setObject(key,n));n->release();}
int main(){
 AppleARMBacklight backlight;redfin_display_controls controls={&backlight};AppleCLCD fb;fb.fRedfinControls=&controls;
 assert(redfin_backlight_parameters(&backlight,409));
 auto *outer=OSDynamicCast(OSDictionary,backlight.properties->getObject("IODisplayParameters"));assert(outer);
 auto *brightness=OSDynamicCast(OSDictionary,outer->getObject("brightness"));assert(brightness);
 assert(number(brightness,"min")==4&&number(brightness,"max")==1023&&number(brightness,"value")==409);
 assert(!redfin_backlight_parameters(&backlight,1024));
 OSDictionary *request=OSDictionary::withCapacity(2);put(request,"brightness-nits",125ULL<<16);
 assert(fb.redfinBacklightProperties(request)==kIOReturnSuccess&&fb.last==125ULL<<16);
 put(request,"brightness-nits",250);assert(fb.redfinBacklightProperties(request)==kIOReturnSuccess&&fb.last==250ULL<<16);
 unsigned before=fb.requests;put(request,"brightness-nits",501ULL<<16);
 assert(fb.redfinBacklightProperties(request)==kIOReturnBadArgument&&fb.requests==before);request->release();
 request=OSDictionary::withCapacity(1);put(request,"brightness",1023);
 assert(fb.redfinBacklightProperties(request)==kIOReturnSuccess&&fb.last==500ULL<<16);
 put(request,"brightness",409);assert(fb.redfinBacklightProperties(request)==kIOReturnSuccess);
 uint32_t dbv=0;assert(rf_panel_nits_to_dbv(fb.last,&dbv)&&dbv==409);request->release();
 request=OSDictionary::withCapacity(1);auto *nested=OSDictionary::withCapacity(1),*entry=OSDictionary::withCapacity(1);
 put(entry,"value",256);nested->setObject("brightness",entry);request->setObject("IODisplayParameters",nested);entry->release();nested->release();
 assert(fb.redfinBacklightProperties(request)==kIOReturnSuccess);assert(rf_panel_nits_to_dbv(fb.last,&dbv)&&dbv==256);request->release();
 request=OSDictionary::withCapacity(1);nested=OSDictionary::withCapacity(0);request->setObject("brightness-nits",nested);nested->release();
 before=fb.requests;assert(fb.redfinBacklightProperties(request)==kIOReturnBadArgument&&fb.requests==before);request->release();
 request=OSDictionary::withCapacity(1);put(request,"unrelated-native-property",1);
 assert(fb.redfinBacklightProperties(request)==kIOReturnSuccess&&fb.requests==before);request->release();
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-backlight-contract-') as directory:
            root=Path(directory);path=root/'properties.cpp';path.write_text(source)
            compiled=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(path),'-o',str(root/'properties')],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            run=subprocess.run([str(root/'properties')],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_installed_CoreBrightness_requires_dictionary_and_typed_ignore_IOMFB(self):
        from ports.redfin.graphics_abi import Cache,DEFAULT_CACHE
        if not DEFAULT_CACHE.is_file():self.skipTest('actual native20H392 cache required')
        with Cache() as cache:proof=brightness_abi.derive(cache)
        self.assertEqual(proof['required_dictionary'],'IODisplayParameters')
        self.assertEqual(proof['ignore_IOMFB_property'],'uint32 CFData')
        self.assertFalse(proof['physical_calibration_claimed'])


if __name__=='__main__':unittest.main()
