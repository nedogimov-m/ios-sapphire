"""Exercise the actual initial touch caller, ownership and failure ordering."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def added_file(patch, name):
    section = (HERE / patch).read_text().split('+++ b/bsd/dev/' + name + '\n', 1)[1]
    section = section.split('diff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines() if line.startswith('+')) + '\n'


class InitialTouchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        work = Path(cls.temporary.name)
        for patch, name in (('touch-rail-ready.patch', 'redfin_touch_rail.h'),
                            ('rpmh-touch.patch', 'redfin_rpmh_touch.h')):
            (work / name).write_text(added_file(patch, name))
        actual = added_file('touch-start.patch', 'redfin_touch_start.c')
        actual = '\n'.join(line for line in actual.splitlines()
                           if not line.startswith('#include <'))
        model = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
#include <errno.h>
#include "redfin_rpmh_touch.h"
#define ARM64_BOARD_CONFIG_SWEET 1
static const char *names[]={"cpus","redfintouch","redfintouchsetup","redfinrpmhtouch",
 "redfinrail","sweettouch","sweetkeys","sweetusb","sweetcpufreq","sweetbattery",
 "modem","wifi","gpu","redfinusb","redfinwifi","redfingpu","redfinroot",
 "redfinufs","redfintouchevents"};
static uint32_t values[19]={1,2,1,1,1};
static bool present[19];
static unsigned variant,power_calls,ready_calls,setup_calls;
bool redfin_usb_platform(void){return variant!=1;}
int redfin_spmi_return_ready(void){return variant!=2;}
static bool PE_parse_boot_argn(const char *name,void *out,unsigned bytes){
 assert(bytes==4);
 for(unsigned i=0;i<19;i++)if(!strcmp(name,names[i])){
  if(!present[i])return false;memcpy(out,&values[i],4);return true;
 }
 abort();
}
int redfin_touch_rail_snapshot(void *context,struct redfin_touch_rail_state *out){
 assert(!context && out);return 0;
}
int redfin_rpmh_touch_prepare(const struct redfin_touch_rail_ops *ops){
 power_calls++;assert(ops && ops->initial_md0_drv2_lease);
 assert(ops->read==redfin_touch_rail_snapshot && !ops->context);
 return variant==9 ? EIO : 0;
}
int redfin_touch_rail_ready(void){
 ready_calls++;return variant==10 ? 0 : variant==11 ? -1 : variant==14 ? 2 : 1;
}
int redfin_touch_setup(bool rail,bool host){
 setup_calls++;assert(rail && host);return variant==12 ? EIO : 0;
}
ACTUAL
int main(int argc,char **argv){
 assert(argc==2);variant=(unsigned)strtoul(argv[1],NULL,0);
 for(unsigned i=0;i<13;i++)present[i]=true;
 switch(variant){
 case 3:values[0]=2;break;case 4:values[1]=1;break;
 case 5:values[2]=0;break;case 6:values[3]=0;break;
 case 7:values[4]=0;break;case 8:present[5]=false;break;
 case 13:present[4]=false;break;
 }
 if(variant>=100 && variant<108)values[5+variant-100]=1;
 if(variant>=200 && variant<206){present[13+variant-200]=true;values[13+variant-200]=1;}
 int first=redfin_touch_start_initial(),second=redfin_touch_start_initial();
 bool refused=(variant>=1 && variant<=8) || variant==13 || variant>=100;
 if(refused){assert(first==ENOTSUP && second==ENOTSUP);assert(!power_calls && !ready_calls && !setup_calls);}
 else{
  assert(second==EBUSY && power_calls==1);
  if(variant==9){assert(first==EIO && !ready_calls && !setup_calls);}
  else if(variant==10 || variant==11 || variant==14){assert(first==ENXIO && ready_calls==1 && !setup_calls);}
  else{assert(first==(variant==12 ? EIO : 0) && ready_calls==1 && setup_calls==1);}
 }
 return 0;
}
'''
        source, cls.executable = work / 'start.c', work / 'start'
        source.write_text(model.replace('ACTUAL', actual))
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', str(source), '-o', str(cls.executable)],
                       check=True, capture_output=True)

    def run_cases(self, cases):
        for variant in cases:
            with self.subTest(variant=variant):
                subprocess.run([str(self.executable), str(variant)], check=True, capture_output=True)

    def test_success_claims_once_and_runs_power_ready_then_id(self):
        self.run_cases([0])

    def test_platform_return_up_and_explicit_mode_guards(self):
        self.run_cases(range(1, 9))
        self.run_cases([13])

    def test_each_competing_legacy_or_native_path_prevents_ownership(self):
        self.run_cases(range(100, 108))
        self.run_cases(range(200, 206))

    def test_uncertain_power_and_nonexact_ready_never_reach_spi_or_retry(self):
        self.run_cases([9, 10, 11, 12, 14])


if __name__ == '__main__':
    unittest.main()
