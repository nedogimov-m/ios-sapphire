"""Compile the common dispatch and verify no observer precedes return proof."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PeripheralStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        patch = Path(__file__).with_name('peripheral-start.patch').read_text()
        added = '\n'.join(s[1:] for s in patch.splitlines()
                          if s.startswith('+') and not s.startswith('+++'))
        actual = added.split('/* REDFIN_PERIPHERAL_START_TEST_BEGIN */', 1)[1].split(
            '/* REDFIN_PERIPHERAL_START_TEST_END */', 1)[0]
        prefix = r'''
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
static uint32_t modes[6],cpus;
static uint64_t boot_id;
static unsigned boot_logs;
static int ready,calls[6];
static int IOLog(const char *format,...) {
 if(!strncmp(format,"REDFIN BOOT ID:",15)) {
  if(strcmp(format,"REDFIN BOOT ID: %016llx\n"))abort();
  va_list args;va_start(args,format);
  if(va_arg(args,unsigned long long)!=boot_id)abort();
  va_end(args);boot_logs++;
 }
 return 0;
}
static int PE_parse_boot_argn(const char *s,void *out,unsigned n) {
 if(!strcmp(s,"redfinbootid")) {
  if(n!=8)abort();memcpy(out,&boot_id,8);return boot_id!=0;
 }
 if(n!=4)abort();
 const char *names[]={"redfintouch","redfinusb","redfinwifi","redfingpu","redfinrpmh","redfinrail"};
 if(!strcmp(s,"cpus")){memcpy(out,&cpus,4);return 1;}
 for(unsigned i=0;i<6;i++)if(!strcmp(s,names[i])){memcpy(out,&modes[i],4);return 1;}
 return 0;
}
static int redfin_spmi_return_ready(void){return ready;}
static int redfin_touch_probe(void){calls[0]++;return 0;}
static void redfin_usb_probe(void){calls[1]++;}
static void redfin_wifi_observe(void){calls[2]++;}
static int redfin_gpu_probe(void){calls[3]++;return 0;}
static int redfin_rpmh_probe(void){calls[4]++;return 0;}
static int redfin_touch_rail_observe(void){calls[5]++;return 0;}
static int redfin_touch_start_initial(void){calls[0]++;return 0;}
static int redfin_usb_start_initial(void){calls[1]++;return 0;}
'''
        suffix = r'''
int main(int argc,char **argv){
 if(argc!=9 && argc!=10)return 2;
 for(unsigned i=0;i<6;i++)modes[i]=(uint32_t)strtoul(argv[i+1],NULL,0);
 ready=atoi(argv[7]);cpus=(uint32_t)strtoul(argv[8],NULL,0);
 if(argc==10)boot_id=strtoull(argv[9],NULL,0);
 for(int i=0;i<3;i++)redfin_peripherals_observe();
 if(boot_logs!=(boot_id ? 1u : 0u))return 3;
 printf("%d %d %d %d %d %d\n",calls[0],calls[1],calls[2],calls[3],calls[4],calls[5]);return 0;
}
'''
        (root/'start.cpp').write_text(prefix+actual+suffix)
        cls.executable = root/'start'
        subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17', '-Wall',
                        '-Wextra', '-Werror', str(root/'start.cpp'), '-o', str(cls.executable)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, modes, ready=1, cpus=1, boot_id=0):
        output = subprocess.check_output([str(self.executable), *map(str, modes), str(ready), str(cpus), str(boot_id)])
        return tuple(map(int, output.split()))

    def test_default_off(self):
        self.assertEqual(self.run_case((0, 0, 0, 0, 0, 0), ready=0), (0, 0, 0, 0, 0, 0))

    def test_boot_id_printed_once_even_without_observers(self):
        for boot_id in (1, 0x0123456789abcdef, 0xffffffffffffffff):
            self.assertEqual(self.run_case((0, 0, 0, 0, 0, 0), ready=0, boot_id=boot_id), (0, 0, 0, 0, 0, 0))

    def test_unverified_return_or_smp_never_dispatches(self):
        for ready, cpus in ((0, 1), (1, 0), (1, 2), (1, 8)):
            self.assertEqual(self.run_case((1, 1, 1, 1, 1, 1), ready, cpus), (0, 0, 0, 0, 0, 0))

    def test_unknown_mode_refuses_entire_group(self):
        for i in range(6):
            modes = [1] * 6
            modes[i] = 4 if i == 1 else 3 if i == 0 else 2
            self.assertEqual(self.run_case(modes), (0, 0, 0, 0, 0, 0))

    def test_explicit_usb_route_mode_dispatches_usb_once(self):
        self.assertEqual(self.run_case((0, 2, 0, 0, 0, 0)), (0, 1, 0, 0, 0, 0))

    def test_explicit_initial_touch_mode_dispatches_once_after_return(self):
        self.assertEqual(self.run_case((2, 0, 0, 0, 0, 1)), (1, 0, 0, 0, 0, 1))
        self.assertEqual(self.run_case((2, 0, 0, 0, 0, 1), ready=0), (0, 0, 0, 0, 0, 0))

    def test_explicit_owned_usb_mode_dispatches_once_after_return(self):
        self.assertEqual(self.run_case((0, 3, 0, 0, 0, 0)), (0, 1, 0, 0, 0, 0))
        self.assertEqual(self.run_case((0, 3, 0, 0, 0, 0), ready=0), (0, 0, 0, 0, 0, 0))

    def test_only_requested_observers_run_once(self):
        for mask in range(64):
            modes = tuple((mask >> bit) & 1 for bit in range(6))
            self.assertEqual(self.run_case(modes), modes)


if __name__ == '__main__':
    unittest.main()
