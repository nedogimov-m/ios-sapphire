"""Exercise the actual opt-in native MSA reader with owned host RAM mappings."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class WiFiHangTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('host C++ compiler unavailable')
        source = (HERE / 'wifi_fw_start.inc').read_text()
        actual = 'static int fw_start_wlan_hang_observe' + source.split('static int fw_start_wlan_hang_observe', 1)[1].split('static void fw_start_host_event', 1)[0]
        actual = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', actual)
        assert actual.count('destination[i] = source[i];') == 1
        actual = actual.replace('destination[i] = source[i];', 'destination[i] = model_read(source + i);')
        prefix = r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <cerrno>
#include "wifi_qmi.h"
#include "wifi_wlfw.h"
#define REDFIN_MPSS_COPY_CHUNK 2048
struct fw_start_context {bool wlan_hang_mode;rf_wlfw_setup wlfw_setup;uint8_t readback[REDFIN_MPSS_COPY_CHUNK];};
static fw_start_context context;
static unsigned issue,checks,fail_check,created,mapped,released_map,released_memory,reads,violations;
static uint64_t physical,mapping_bytes;
static uint8_t ram[32768];
static char output[10000];static size_t used;
static int model_log(const char *format,...){
 va_list args;va_start(args,format);int n=vsnprintf(output+used,sizeof(output)-used,format,args);va_end(args);
 if(n<0 || (size_t)n>=sizeof(output)-used){violations++;return 0;}used+=(size_t)n;return n;
}
#define IOLog model_log
static int fw_start_wlan_power_policy(void *child){
 ++checks;
 if(issue==11 && checks==4)ram[256]^=1;
 if(issue==12 && checks==4)context.wlfw_setup.region[1].secure=1;
 return child!=&context || issue==5 || (fail_check && checks>=fail_check) ? -1 : 0;
}
static uint8_t model_read(const volatile uint8_t *pointer){
 uintptr_t at=(uintptr_t)pointer,base=(uintptr_t)ram;
 if(at<base || at>=base+mapping_bytes || (fail_check && checks>=fail_check)) {violations++;return 0;}
 ++reads;return *pointer;
}
enum {kIODirectionIn=1,kIOMapReadOnly=2,kIOMapWriteCombineCache=4};
class IOMemoryMap {
public:
 uintptr_t getVirtualAddress(){return issue==8 ? 0 : (uintptr_t)ram;}
 uint64_t getLength(){return mapping_bytes-(issue==9);}
 void release(){released_map++;}
};
static IOMemoryMap map_instance;
class IOMemoryDescriptor {
public:
 static IOMemoryDescriptor *withPhysicalAddress(uint64_t address,uint64_t bytes,unsigned direction);
 IOMemoryMap *map(unsigned options){
  ++mapped;if(options!=(kIOMapReadOnly|kIOMapWriteCombineCache))violations++;
  return issue==7 ? nullptr : &map_instance;
 }
 void release(){released_memory++;}
};
static IOMemoryDescriptor memory_instance;
IOMemoryDescriptor *IOMemoryDescriptor::withPhysicalAddress(uint64_t address,uint64_t bytes,unsigned direction){
 ++created;physical=address;mapping_bytes=bytes;
 if(direction!=kIODirectionIn || (address&16383) || address<0x8ba10000ULL ||
    !bytes || (bytes&16383) || bytes>32768 || address+bytes>0x8bc00000ULL)violations++;
 return issue==6 ? nullptr : &memory_instance;
}
#define OSSafeReleaseNULL(value) do {if(value){value->release();value=nullptr;}}while(0)
'''
        api = r'''
extern "C" void reset(unsigned variant,unsigned length,unsigned offset){
 issue=variant;checks=fail_check=created=mapped=released_map=released_memory=reads=violations=0;
 used=0;output[0]=0;physical=mapping_bytes=0;memset(&context,0,sizeof(context));
 for(unsigned i=0;i<sizeof(ram);++i)ram[i]=(uint8_t)i;
 context.wlan_hang_mode=variant!=4;
 rf_wlfw_setup *s=&context.wlfw_setup;s->stage=RF_WLFW_COMPLETE;s->msa_accepted=s->msa_ready_ind=1;
 s->regions=2;s->region[0]={0x8ba00000,0x10000,1};s->region[1]={0x8ba10000,0x1f0000,0};
 s->hang_valid=variant==1 ? 1 : 3;s->hang_offset=offset;s->hang_bytes=length;
 if(variant==2)s->region[1].secure=1;
 if(variant==13){s->region[1].base++;s->region[1].bytes--;}
 if(variant==14)s->msa_accepted=0;
 if(variant==15)s->stage=RF_WLFW_CAP;
 if(variant==16)s->poisoned=1;
 if(variant==17)s->region[1].bytes=0x200000;
 if(variant==18)s->region[0].bytes=0x20000;
}
extern "C" int run(void){return fw_start_wlan_hang_observe(&context);}
extern "C" void fail_after(unsigned n){fail_check=n;}
extern "C" unsigned metric(unsigned which){
 unsigned values[]={created,mapped,released_map,released_memory,reads,violations,checks};return which<7 ? values[which] : 0;
}
extern "C" uint64_t extent(unsigned which){return which ? mapping_bytes : physical;}
extern "C" const char *log_text(void){return output;}
'''
        cls.temporary = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'hang.cpp').write_text(prefix + actual + api)
        result = subprocess.run([compiler, '-std=c++17', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                                 '-I', str(HERE), str(directory / 'hang.cpp'), '-o', str(directory / 'hang.so')], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(directory / 'hang.so'))
        cls.lib.log_text.restype = C.c_char_p; cls.lib.extent.restype = C.c_uint64

    def reset(self, issue=0, length=96, offset=0x10100):
        self.lib.reset(issue, length, offset)

    def run_observer(self):
        result = self.lib.run()
        self.assertEqual(self.lib.metric(5), 0, 'wrong mapping, cache/write flags, range or read after cancellation')
        self.assertLessEqual(self.lib.metric(4), 800)
        return result

    def test_only_announced_bounded_nonsecure_pages_are_mapped_read_only_and_sampled_twice(self):
        self.reset()
        self.assertEqual(self.run_observer(), 0)
        self.assertEqual([self.lib.metric(i) for i in range(5)], [1, 1, 1, 1, 192])
        self.assertEqual((self.lib.extent(0), self.lib.extent(1)), (0x8ba10000, 16384))
        log = self.lib.log_text().decode()
        self.assertIn('bytes=96 stable=1', log); self.assertIn('+0 000102030405060708090a0b0c0d0e0f', log)
        self.reset(length=400, offset=0x13fff)
        self.assertEqual(self.run_observer(), 0)
        self.assertEqual(self.lib.extent(1), 32768); self.assertEqual(self.lib.metric(4), 800)

    def test_absent_secure_oversized_overlapping_unaccepted_and_partial_pages_never_map(self):
        for issue, length, offset in ((1, 96, 0x10100), (2, 96, 0x10100), (0, 401, 0x10100),
                                      (0, 0, 0x10100), (0, 400, 0x1fff00), (0, 96, 0),
                                      (13, 96, 0x10100), (14, 96, 0x10100), (15, 96, 0x10100),
                                      (16, 96, 0x10100), (17, 96, 0x10100), (18, 96, 0x10100)):
            self.reset(issue, length, offset)
            self.assertEqual(self.run_observer(), 0)
            self.assertEqual((self.lib.metric(0), self.lib.metric(4)), (0, 0))

    def test_mode_and_child_checks_precede_mapping_and_local_alias_failures_release_objects(self):
        for issue in (4, 5):
            self.reset(issue)
            self.assertEqual(self.run_observer(), errno.EPERM)
            self.assertEqual(self.lib.metric(0), 0)
        for issue, maps, released in ((6, 0, 0), (7, 1, 0), (8, 1, 1), (9, 1, 1)):
            self.reset(issue)
            self.assertEqual(self.run_observer(), errno.ENOMEM)
            self.assertEqual((self.lib.metric(1), self.lib.metric(2), self.lib.metric(3)), (maps, released, issue != 6))
            self.assertEqual(self.lib.metric(4), 0)

    def test_every_owner_check_can_cancel_without_further_loads_and_releases_only_local_aliases(self):
        self.reset(); self.assertEqual(self.run_observer(), 0); count = self.lib.metric(6)
        for at in range(1, count + 1):
            self.reset(); self.lib.fail_after(at)
            self.assertEqual(self.run_observer(), errno.EPERM)
            self.assertEqual(self.lib.metric(2), self.lib.metric(1))
            self.assertEqual(self.lib.metric(3), self.lib.metric(0))

    def test_unstable_data_is_reported_without_dump_retry_and_changed_permissions_stop_publication(self):
        self.reset(11)
        self.assertEqual(self.run_observer(), 0)
        log = self.lib.log_text().decode()
        self.assertIn('stable=0', log); self.assertNotIn('HANG: +', log)
        self.assertEqual(self.lib.metric(0), 1)
        self.reset(12)
        self.assertEqual(self.run_observer(), errno.EPERM)
        self.assertNotIn('HANG: +', self.lib.log_text().decode())


if __name__ == '__main__':
    unittest.main()
