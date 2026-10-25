"""Execute the real final selector with captures off and concurrent publication."""
import ctypes as C
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_display_geometry import FB, production_sources
from ports.redfin.gui_profile import REQUIRED
from ports.redfin.test_display_statistics import PhysicalStatistics, Statistics

HERE=Path(__file__).resolve().parent
PREFIX=r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <atomic>
#include <thread>
#include "gui-profile.h"
#include "display-statistics.h"
enum {kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnBusy=2,kIOReturnNotReady=3};
struct IOExternalMethodArguments {
 unsigned scalarInputCount;const uint64_t *scalarInput;
 size_t structureInputSize;void *structureInputDescriptor,*structureOutputDescriptor,*structureOutput;
 size_t structureOutputSize;unsigned scalarOutputCount;
};
struct AppleCLCD {
 bool fRedfinCopyOnly=true;void *fRedfinCaptureLock=nullptr;
 uint32_t fRedfinVsyncUS=11111;redfin_display_statistics_state fRedfinStatistics={};
};
static const char *boot_arguments;
static const char *PE_boot_args(){return boot_arguments;}
static uint64_t mach_absolute_time(){return 192000000;}
struct Client {
 AppleCLCD *fFB;
 int query(uint32_t selector,IOExternalMethodArguments *args) {
  switch(selector) {
'''
SUFFIX=r'''
  default:return kIOReturnBadArgument;
  }
 }
};
extern "C" int snapshot(const char *arguments,uint64_t nonce,unsigned version,
 unsigned scenario,void *out,size_t bytes) {
 boot_arguments=arguments;AppleCLCD fb;
 redfin_display_statistics_record(&fb.fRedfinStatistics,true);
 redfin_display_statistics_record(&fb.fRedfinStatistics,false);
 redfin_display_statistics_record(&fb.fRedfinStatistics,true);
 if(scenario==2)fb.fRedfinCopyOnly=false;
 if(scenario==3)fb.fRedfinStatistics.sequence|=1;
 Client client={scenario==1?nullptr:&fb};
 IOExternalMethodArguments args={1,&nonce,0,nullptr,nullptr,out,bytes,99};
 return client.query(version==2?REDFIN_DISPLAY_STATISTICS_SELECTOR_V2:
                     REDFIN_DISPLAY_STATISTICS_SELECTOR,&args);
}
extern "C" unsigned concurrent_pair() {
 redfin_display_statistics_state state={};std::atomic<bool> start{false},done{false};
 std::atomic<unsigned> errors{0},ready{0};
 std::thread readers[4];
 for(auto &reader:readers)reader=std::thread([&]{
  ++ready;while(!start.load())std::this_thread::yield();
  unsigned attempts=0;
  do {
   uint64_t p=0,g=0;
   if(redfin_display_statistics_read(&state,&p,&g)&&g!=p/3)++errors;
   ++attempts;
  }while(!done.load()||attempts<2048);
 });
 while(ready.load()!=4)std::this_thread::yield();
 start=true;
 for(unsigned i=1;i<=100000;++i)redfin_display_statistics_record(&state,i%3==0);
 done=true;for(auto &reader:readers)reader.join();
 uint64_t p=0,g=0;
 if(!redfin_display_statistics_read(&state,&p,&g)||p!=100000||g!=33333)++errors;
 return errors;
}
'''


class NativeDisplayStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        root=Path(cls.tmp.name)
        source=production_sources(root)[FB]
        begin=source.index('\tcase REDFIN_DISPLAY_STATISTICS_SELECTOR:')
        end=source.index('\tcase kSweetFBGetLayerDefaultSurface:',begin)
        selector=source[begin:end]
        # The host fixture substitutes only the actual privileged register read.
        selector,count=re.subn(
            r'uint64_t frequency=0;\n#if defined\(__arm64__\) \|\| defined\(__aarch64__\)\n'
            r'.*?\n#endif', 'uint64_t frequency=19200000;',selector,flags=re.S)
        if count!=1:raise RuntimeError('native frequency read changed')
        (root/'selector.cpp').write_text(PREFIX+selector+SUFFIX)
        subprocess.run(['c++','-std=c++17','-O2','-shared','-fPIC','-pthread',
            '-Wall','-Wextra','-Werror','-I',str(HERE),str(root/'selector.cpp'),
            '-o',str(root/'selector.so')],capture_output=True,check=True)
        cls.lib=C.CDLL(str(root/'selector.so'))
        cls.lib.snapshot.argtypes=[C.c_char_p,C.c_uint64,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t]
        cls.nonce=0x020afecf22835a8c
        cls.arguments=(' '.join(sorted(REQUIRED)).replace('redfingui=1','redfingui=3')+
                       ' redfinfit=1 redfinbootid=0x020afecf22835a8c').encode()

    def test_ordinary_final_selectors_work_without_any_capture_lock(self):
        for version,kind in ((1,Statistics),(2,PhysicalStatistics)):
            value=kind()
            self.assertEqual(self.lib.snapshot(self.arguments,self.nonce,version,0,
                                               C.byref(value),C.sizeof(value)),0)
            self.assertEqual((value.version,value.bytes,value.presents,value.gpu_presents,
                              value.panel_hz),(version,C.sizeof(value),3,2,90))
            if version==2:self.assertEqual(value.counter_hz,19200000)

    def test_invalid_generation_or_writer_in_progress_preserves_the_output(self):
        for scenario,nonce,size,expected in ((1,self.nonce,48,1),(2,self.nonce,48,1),
                (3,self.nonce,48,2),(0,self.nonce+1,48,1),(0,self.nonce,47,1)):
            value=(C.c_ubyte*48)(*([0xa5]*48))
            self.assertEqual(self.lib.snapshot(self.arguments,nonce,2,scenario,value,size),expected)
            self.assertEqual(bytes(value),b'\xa5'*48)

    def test_concurrent_readers_never_observe_a_split_cpu_gpu_completion_pair(self):
        self.assertEqual(self.lib.concurrent_pair(),0)


if __name__=='__main__':unittest.main()
