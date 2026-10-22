"""Execute the actual physical-PMIC observer against fixed-target bus models."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


class TouchRailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host compiler unavailable')
        patch = Path(__file__).with_name('touch-rail-observe.patch').read_text()
        actual = '\n'.join(s[1:] for s in patch.splitlines()
                           if s.startswith('+') and not s.startswith('+++'))
        actual = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', actual)
        store = '*(volatile uint32_t *)(redfin_spmi_proof.observer + channel) = command;'
        assert actual.count(store) == 1
        actual = actual.replace(store, 'model_command(channel, command);')
        stub = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
typedef uintptr_t vm_offset_t;
typedef void *DTEntry;
#define kSuccess 0
static unsigned issue,mode,cpus,commands,table_reads,violations,wait_us,last_apid,last_reg,last_count;
static unsigned candidate_commands,voltage_reads,header_reads,preferred_commands;
static uint32_t mappings[512],owners[512];
static bool pending,status_seen;
static char output[16000];
static size_t used;
static struct {bool ready;vm_offset_t core,observer,config;uint32_t version;} redfin_spmi_proof;
static int model_printf(const char *fmt,...){
 va_list ap;va_start(ap,fmt);int n=vsnprintf(output+used,sizeof(output)-used,fmt,ap);va_end(ap);
 if(n<0 || (size_t)n>=sizeof(output)-used){violations++;return 0;}used+=(size_t)n;return n;
}
#define printf model_printf
static int PE_parse_boot_argn(const char *name,void *out,unsigned size){
 (void)size;*(uint32_t *)out=!strcmp(name,"cpus") ? cpus : mode;return 1;
}
static int redfin_spmi_return_ready(void){return issue!=4;}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
 (void)root;if(strcmp(path,"/") || issue==6)return -1;*out=(void*)1;return 0;
}
static int SecureDTGetProperty(DTEntry node,const char *key,const void **out,unsigned *n){
 static const char compatible[]="google,redfin\0qcom,sm7250";
 if(node!=(void*)1 || strcmp(key,"compatible")){violations++;return -1;}
 *out=issue==17 ? NULL : compatible;*n=sizeof(compatible);return 0;
}
static void delay(unsigned us){wait_us+=us;}
static bool target_fault(void){return ((mappings[last_apid]>>8)&0xfff)==0x150;}
static void model_command(unsigned channel,uint32_t command){
 if(channel%0x80 || channel/0x80>=512 || pending){violations++;return;}
 last_apid=channel/0x80;last_reg=(command>>4)&255;last_count=(command&15)+1;
 unsigned ppid=(mappings[last_apid]>>8)&0xfff;
 bool model=ppid==1 && last_reg==4 && last_count==2;
 bool candidate=ppid>=0x140 && ppid<=0x151 &&
  ((last_reg==4 && last_count==2)||(last_reg==8 && last_count==1)||
   (last_reg==0x40 && last_count==2)||(last_reg==0x45 && last_count==2));
 if((command&~0x08000fffu) || (command>>27)!=1 || (!model&&!candidate))violations++;
 commands++;candidate_commands+=candidate;preferred_commands+=last_apid==100;
 pending=true;status_seen=false;
}
static uint32_t redfin_spmi_rd(vm_offset_t base,unsigned offset){
 if(base==1){
  if(offset==0)return issue==9 ? 0x40000000 : redfin_spmi_proof.version;
  if(offset>=0x900 && offset<0x1100 && !(offset&3)){
   table_reads++;unsigned apid=(offset-0x900)/4;
   if(issue==10 && commands && apid==17 && target_fault())return mappings[apid]^0x100;
   return mappings[apid];
  }
 }else if(base==3 && offset>=0x700 && offset<0xf00 && !(offset&3)){
  return owners[(offset-0x700)/4];
 }else if(base==2 && pending){
  unsigned channel=last_apid*0x80;
  if(offset==channel+8){
   if(issue==12 && target_fault())return 0;
   status_seen=true;return issue==11 && target_fault() ? 9 : 1;
  }
  if(offset==channel+0x18 && status_seen){
   pending=false;unsigned ppid=(mappings[last_apid]>>8)&0xfff;
   if(ppid==1)return issue==8 ? 0x1f51 : 0x1e51;
   if(last_reg==4){header_reads++;return issue==14 && target_fault() ? 0x8004 : issue==20 && target_fault() ? 0x7d04 : 0x3504;}
   if(last_reg==0x40){voltage_reads++;return issue==15 && target_fault() && voltage_reads%2==0 ? 3300 : 3304;}
   if(last_reg==0x45)return 0x8007;
   if(last_reg==8)return 0x80;
  }
 }
 violations++;return 0;
}
'''
        wrapper = r'''
int run(unsigned variant){
 issue=variant;mode=variant==1 ? 0 : variant==2 ? 2 : 1;cpus=variant==3 ? 2 : 1;
 commands=table_reads=violations=wait_us=last_apid=last_reg=last_count=0;
 candidate_commands=voltage_reads=header_reads=preferred_commands=0;
 pending=status_seen=false;used=0;output[0]=0;redfin_rail_attempted=false;
 redfin_spmi_proof.ready=variant!=5;redfin_spmi_proof.core=1;
 redfin_spmi_proof.observer=variant==18 ? 0 : 2;redfin_spmi_proof.config=3;
 redfin_spmi_proof.version=variant==19 ? 0x70000000 : 0x50000000;
 memset(mappings,0,sizeof(mappings));memset(owners,0,sizeof(owners));
 mappings[0]=0x101;owners[0]=0;
 for(unsigned i=1;i<19;i++){mappings[i]=((0x13f+i)<<8)|1;owners[i]=2;}
 if(variant==7)mappings[0]=0;
 if(variant==13)mappings[17]=0;
 if(variant==16){mappings[100]=mappings[17];owners[100]=0;}
 return redfin_touch_rail_observe();
}
int again(void){return redfin_touch_rail_observe();}
unsigned stat(unsigned index){
 unsigned values[]={commands,table_reads,violations,wait_us,candidate_commands,voltage_reads,header_reads,preferred_commands};
 return index<8 ? values[index] : 0;
}
const char *log_text(void){return output;}
int guard(unsigned ppid,unsigned apid,unsigned address,unsigned count,int null_out){
 struct redfin_rail_target t={ppid,apid,apid<512 ? owners[apid] : 0,apid<512 ? mappings[apid] : 0};
 uint16_t value=0;return redfin_rail_read(&t,address,count,null_out ? NULL : &value);
}
'''
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        work = Path(cls.tmp.name)
        (work/'rail.c').write_text(stub+actual+wrapper)
        subprocess.run([cc,'-std=c11','-shared','-fPIC','-Wall','-Wextra','-Werror',
                        str(work/'rail.c'),'-o',str(work/'rail.so')],check=True,capture_output=True)
        cls.lib = C.CDLL(str(work/'rail.so'))
        cls.lib.run.argtypes = [C.c_uint]
        cls.lib.guard.argtypes = [C.c_uint]*4+[C.c_int]
        cls.lib.log_text.restype = C.c_char_p

    def run_case(self, variant=0):
        result = self.lib.run(variant)
        self.assertEqual(self.lib.stat(2),0,'wrong opcode, SID/APID/register, access or channel reuse')
        self.assertLessEqual(self.lib.stat(3),2800)
        return result,self.lib.log_text().decode()

    def test_default_unknown_modes_up_return_platform_and_verified_proof_before_access(self):
        for issue in (1,2,3,4,5,6,17,18,19):
            self.assertNotEqual(self.run_case(issue)[0],0)
            self.assertEqual((self.lib.stat(0),self.lib.stat(1)),(0,0))
        self.assertEqual(self.run_case(9)[0],errno.ENXIO)
        self.assertEqual((self.lib.stat(0),self.lib.stat(1)),(0,0))

    def test_model_apid_or_wrong_model_stops_before_candidate_reads(self):
        self.assertEqual(self.run_case(7)[0],errno.ENXIO)
        self.assertEqual(self.lib.stat(0),0)
        self.assertEqual(self.run_case(8)[0],errno.ENOTSUP)
        self.assertEqual(self.lib.stat(4),0)

    def test_bounded_candidates_only_read_and_no_readiness_or_index_claim(self):
        result,log=self.run_case()
        self.assertEqual(result,0)
        self.assertIn('candidate page=0x5000 raw VSET-mV=3304 MODE=0x7 ENABLE=0x80 STATUS=0x80',log)
        self.assertIn('present=18 unified=18 holes=0 stable=1',log)
        self.assertIn('L17 index and AVDD readiness unproven',log)
        self.assertEqual(self.lib.stat(0),146)
        commands=self.lib.stat(0)
        self.assertEqual(self.lib.again(),errno.EBUSY)
        self.assertEqual(self.lib.stat(0),commands)

    def test_mapping_changes_denial_and_timeout_stop_without_reuse(self):
        for issue,error in ((10,errno.EAGAIN),(11,errno.EIO),(12,errno.ETIMEDOUT)):
            self.assertEqual(self.run_case(issue)[0],error)
            commands=self.lib.stat(0)
            self.assertEqual(self.lib.again(),errno.EBUSY)
            self.assertEqual(self.lib.stat(0),commands)

    def test_apid_holes_are_explicit_and_do_not_prove_physical_absence(self):
        result,log=self.run_case(13)
        self.assertEqual(result,errno.ENXIO)
        self.assertIn('candidate SID1 page=0x5000 has no APID; physical absence unproven',log)

    def test_unknown_layout_header_only_and_changing_sample_marked(self):
        result,log=self.run_case(14)
        self.assertEqual(result,0)
        self.assertIn('page=0x5000 APID=17 write-owner=2 type=0x4 subtype=0x80',log)
        self.assertNotIn('candidate page=0x5000 raw VSET',log)
        self.assertEqual(self.lib.stat(5),34)
        result,log=self.run_case(15)
        self.assertEqual(result,errno.EAGAIN)
        self.assertIn('holes=0 stable=0',log)

    def test_linux_ee0_apid_preference_is_revalidated(self):
        self.assertEqual(self.run_case(16)[0],0)
        self.assertEqual(self.lib.stat(7),8)

    def test_observed_pmic5_7d_uses_source_generic_unified_branch_for_raw_reads_only(self):
        result,log=self.run_case(20)
        self.assertEqual(result,0)
        self.assertIn('page=0x5000 APID=17 write-owner=2 type=0x4 subtype=0x7d',log)
        self.assertIn('candidate page=0x5000 raw VSET-mV=3304',log)
        self.assertIn('PMIC5 range/mode policy unproven, raw observation only',log)
        self.assertIn('L17 index and AVDD readiness unproven',log)
        self.assertEqual(self.lib.stat(0),146)

    def test_read_helper_rejects_other_sid_peripheral_register_width_and_null_output(self):
        self.run_case()
        before=self.lib.stat(0)
        for args in ((0x150,17,0x5040,3,0),(0x150,17,0x5046,1,0),
                     (0x150,17,0x5140,2,0),(0x250,17,0x5040,2,0),
                     (0x150,512,0x5040,2,0),(0x150,16,0x5040,2,0),
                     (0x150,17,0x5040,2,1),(1,0,0x0104,1,0)):
            self.assertEqual(self.lib.guard(*args),errno.EINVAL)
        self.assertEqual(self.lib.stat(0),before)


if __name__=='__main__':
    unittest.main()
