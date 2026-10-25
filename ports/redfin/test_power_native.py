"""Run actual native power transaction/governor code against faulted hardware.

Only MMIO/time/map primitives are replaced. Real command framing, bounded
polling, lease checks, conversion completion/restoration and OSM policy run.
"""
import ctypes as C
import errno
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent

PREFIX=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include "power-policy.h"
#define VM_WIMG_IO 7
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
static vm_offset_t power_core,power_observer,power_config;
static uint32_t power_version;
static bool power_spmi_ok;
static unsigned power_throttles;
static void IOLog(const char *s,...){(void)s;}
static uint32_t maps[512],owners[512],data_words[512][2],pending_addr[512],pending_count[512];
static uint8_t pmic[11][256];
static unsigned scenario,reads,writes,polls,delays,adc_requests,adc_cfg_writes,sleeps;
static bool adc_busy;
static uint32_t osm[3][0x1000/4];
'''
MODEL=r'''
static int target_for_apid(unsigned apid){for(unsigned i=0;i<P_COUNT;i++)if(power_targets[i].apid==apid)return (int)i;return -1;}
static int domain_for_base(uintptr_t base){for(unsigned i=0;i<3;i++)if(base==power_contract[15+i])return (int)i;return -1;}
static vm_offset_t ml_io_map_unmappable(vm_offset_t p,vm_size_t n,unsigned mode){(void)n;(void)mode;return p;}
static void IODelay(unsigned n){delays+=n;}
static void IOSleep(unsigned n){
 sleeps+=n;
 if(adc_busy && scenario!=31){adc_busy=false;pmic[P_ADC][8]=1;pmic[P_ADC][9]^=0x20;}
}
static uint32_t power_rd(vm_offset_t base,unsigned offset){
 if(base==0x0c440000){if(!offset)return 0x50000000;return offset>=0x900 && offset<0x1100?maps[(offset-0x900)/4]:0;}
 if(base==0x0c40a000)return offset>=0x700 && offset<0xf00?owners[(offset-0x700)/4]:0;
 if(base==0x0e600000){
  unsigned apid=offset/0x80,at=offset%0x80;
  if(at==8){polls++;return scenario==10?0:scenario==11?3:1;}
  if(at==0x18 || at==0x1c){
   int t=target_for_apid(apid);if(t<0)return 0;
   unsigned address=pending_addr[apid]+(at==0x1c?4:0);uint32_t result=0;
   for(unsigned i=0;i<4 && address+i<256;i++)result|=(uint32_t)pmic[t][address+i]<<(8*i);
   return result;
  }
 }
 if(base>=0x0c600000 && base<0x0e600000){if(offset==8){polls++;return scenario==10?0:scenario==11?3:1;}}
 int domain=domain_for_base(base);if(domain>=0 && offset<0x1000)return osm[domain][offset/4];
 return 0;
}
static void power_wr(vm_offset_t base,unsigned offset,uint32_t value){
 if(base==0x0e600000){
  unsigned apid=offset/0x80;reads++;pending_addr[apid]=(value>>4)&255;pending_count[apid]=(value&7)+1;return;
 }
 if(base>=0x0c600000 && base<0x0e600000){
  unsigned apid=(unsigned)((base-0x0c600000)/0x10000);
  if(offset==0x10 || offset==0x14){data_words[apid][offset==0x14]=value;
   if(scenario==12 && offset==0x10)maps[apid]^=0x100;
   return;}
  if(!offset){
   writes++;int t=target_for_apid(apid);if(t<0)return;
   unsigned address=(value>>4)&255,n=(value&7)+1;
   for(unsigned i=0;i<n;i++)pmic[t][address+i]=(uint8_t)(data_words[apid][i/4]>>(8*(i%4)));
   if(t==P_ADC && address==0x42){adc_cfg_writes++;if(scenario==40 && adc_cfg_writes>1)pmic[t][0x44]^=1;}
   if(t==P_ADC && address==0x47){
    adc_requests++;
    if(scenario!=30){adc_busy=true;pmic[t][8]=2;}
   }
  }
  return;
 }
 int domain=domain_for_base(base);if(domain>=0 && offset<0x1000){osm[domain][offset/4]=value;writes++;}
}
'''
SUFFIX=r'''
extern "C" {
void reset_model(unsigned mode){
 scenario=mode;reads=writes=polls=delays=adc_requests=adc_cfg_writes=sleeps=0;adc_busy=false;power_spmi_ok=false;
 memset(pmic,0,sizeof(pmic));memset(maps,0,sizeof(maps));memset(owners,0,sizeof(owners));
 memset(data_words,0,sizeof(data_words));memset(pending_addr,0,sizeof(pending_addr));memset(osm,0,sizeof(osm));
 memset(power_domains,0,sizeof(power_domains));power_throttles=0;
 for(unsigned i=0;i<P_COUNT;i++){
  power_targets[i].apid=512;power_targets[i].mapping=0;power_targets[i].writer=0;
  maps[i+2]=0x80000000u|(power_targets[i].ppid<<8);
 }
 pmic[P_REVID][4]=0x51;pmic[P_REVID][5]=0x2e;
 pmic[P_ADC][8]=1;pmic[P_ADC][9]=0x20;
 pmic[P_ADC][0x42]=0x81;pmic[P_ADC][0x43]=0x80;pmic[P_ADC][0x44]=0x12;pmic[P_ADC][0x45]=0xa0;pmic[P_ADC][0x46]=0;
 pmic[P_ADC][0x50]=0x73;pmic[P_ADC][0x51]=0x2a;
 for(unsigned i=0;i<3;i++){
  unsigned cores=i?2:6;osm[i][0]=1;osm[i][0x920/4]=0;
  osm[i][0x110/4]=cores<<16;
  osm[i][(0x110+32)/4]=(1u<<30)|(cores<<16)|50;
  osm[i][(0x110+64)/4]=(1u<<30)|(cores<<16)|100;
  for(unsigned r=3;r<40;r++)osm[i][(0x110+32*r)/4]=osm[i][(0x110+64)/4];
 }
}
int initialize(void){return power_spmi_init();}
unsigned metric(unsigned i){unsigned a[]={reads,writes,polls,delays,power_spmi_ok,adc_requests,adc_cfg_writes,sleeps,power_throttles};return i<9?a[i]:999;}
int read_target(unsigned which,unsigned address,unsigned n){uint8_t out[8]={};return power_read(which,address,out,n);}
int write_target(unsigned which,unsigned address,unsigned n){const uint8_t data[8]={1,2,3,4,5,6,7,8};return power_write(which,address,data,n);}
int charge_bit(unsigned address,unsigned bit,int on){return power_bit(address,bit,on!=0);}
int adc(unsigned channel,unsigned *result){uint16_t value=0xcafe;int error=power_adc(channel,&value);*result=value;return error;}
unsigned reg(unsigned t,unsigned address){return pmic[t][address&255];}
void set_reg(unsigned t,unsigned address,unsigned value){pmic[t][address&255]=(uint8_t)value;}
void change_owner(unsigned t,unsigned owner){owners[t+2]=owner;}
void domains(void){power_domains_init();}
void pressure(unsigned p){power_limit_domains(p);}
unsigned domain_reg(unsigned d,unsigned offset){return osm[d][offset/4];}
void set_domain_reg(unsigned d,unsigned offset,unsigned value){osm[d][offset/4]=value;}
}
'''


class PowerNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);p=Path(cls.tmp.name)
        source=(HERE/'native-power.inc').read_text()
        contract=re.search(r'static const uint32_t power_contract\[\]=\{.*?\};',source,re.S).group()
        targets=source[source.index('enum {P_REVID'):source.index('struct power_tsens')]
        domains=source[source.index('struct power_domain '):source.index('static struct redfin_soc_tracker')]
        body='\n'.join(function(source,signature) for signature in [
            'static bool power_match(', 'static int power_poll(', 'static int power_read(',
            'static int power_byte(', 'static int power_write(', 'static int power_bit(',
            'static int power_adc(', 'static bool power_spmi_init(',
            'static void power_domains_init(', 'static void power_limit_domains('])
        (p/'native.cpp').write_text(PREFIX+contract+targets+domains+MODEL+body+SUFFIX)
        r=subprocess.run(['c++','-std=c++17','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-I',str(HERE),
            str(p/'native.cpp'),'-o',str(p/'native.so')],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr)
        cls.lib=C.CDLL(str(p/'native.so'))
        cls.lib.adc.argtypes=[C.c_uint,C.POINTER(C.c_uint)]
        for name in ['metric','reg','domain_reg']:getattr(cls.lib,name).restype=C.c_uint

    def begin(self,scenario=0):
        self.lib.reset_model(scenario);self.assertTrue(self.lib.initialize())
    def metrics(self):return [self.lib.metric(i) for i in range(9)]

    def test_observer_reads_and_exact_write_scope_preserve_other_pmic_peripherals(self):
        self.begin();before=self.metrics()
        self.assertEqual(self.lib.read_target(1,0x48c0,2),0)
        self.assertEqual(self.lib.metric(1),0)
        for which,address,n in [(1,0x4900,1),(1,0x48ff,2),(1,0x48c0,9),
            (11,0x4800,1),(3,0x3100,0)]:
            count=self.lib.metric(0);self.assertEqual(self.lib.read_target(which,address,n),errno.EINVAL if which>=11 or n in [0,9] or (address&255)+n>256 else errno.ENXIO)
            self.assertEqual(self.lib.metric(0),count)
        for which,address,n in [(4,0x1070,1),(1,0x4842,1),(10,0x6040,4),(3,0x3150,2)]:
            self.assertEqual(self.lib.write_target(which,address,n),errno.EINVAL)
        self.assertEqual(self.lib.metric(1),before[1])
        self.assertEqual(self.lib.charge_bit(0x1042,128,1),errno.EINVAL)
        self.assertEqual(self.lib.metric(1),before[1])
        self.lib.set_reg(4,0x1042,0xa0)
        self.assertEqual(self.lib.charge_bit(0x1042,1,1),0)
        self.assertEqual(self.lib.reg(4,0x1042),0xa1)

    def test_native_owner_and_mid_transaction_mapping_change_never_issue_a_foreign_command(self):
        self.lib.reset_model(0);self.lib.change_owner(3,3);self.assertTrue(self.lib.initialize())
        self.assertEqual(self.lib.write_target(3,0x3142,5),errno.EPERM);self.assertEqual(self.lib.metric(1),0)
        self.begin(12)
        self.assertEqual(self.lib.write_target(4,0x1042,1),errno.EAGAIN)
        self.assertEqual(self.lib.metric(1),0);self.assertFalse(self.lib.metric(4))

    def test_uncertain_spmi_completion_is_bounded_and_cannot_be_retried(self):
        self.lib.reset_model(10);self.assertFalse(self.lib.initialize())
        self.assertEqual(self.lib.metric(2),1000);self.assertFalse(self.lib.metric(4))
        count=self.lib.metric(0);self.assertEqual(self.lib.read_target(1,0x48c0,2),errno.ENXIO)
        self.assertEqual(self.lib.metric(0),count);self.assertEqual(self.lib.metric(1),0)
        self.lib.reset_model(11);self.assertFalse(self.lib.initialize());self.assertEqual(self.lib.metric(2),1)

    def test_adc_requires_fresh_completion_and_restores_the_exact_native_configuration(self):
        self.begin();saved=[self.lib.reg(3,a) for a in range(0x42,0x47)]
        out=C.c_uint();self.assertEqual(self.lib.adc(0x4a,C.byref(out)),0);self.assertEqual(out.value,0x2a73)
        self.assertEqual([self.lib.reg(3,a) for a in range(0x42,0x47)],saved)
        self.assertEqual(self.lib.metric(5),1);self.assertEqual(self.lib.metric(6),2)
        self.lib.set_reg(3,8,2);count=self.lib.metric(1)
        self.assertEqual(self.lib.adc(0x4a,C.byref(out)),errno.EBUSY);self.assertEqual(self.lib.metric(1),count)

    def test_stale_eoc_late_adc_and_restore_failure_do_not_publish_a_sample(self):
        for scenario in [30,31]:
            self.begin(scenario);out=C.c_uint()
            self.assertEqual(self.lib.adc(0x4a,C.byref(out)),errno.ETIMEDOUT)
            self.assertEqual(out.value,0xcafe);self.assertFalse(self.lib.metric(4))
            self.assertEqual(self.lib.metric(6),1);self.assertEqual(self.lib.metric(7),100)
        self.begin(40);out=C.c_uint();self.assertEqual(self.lib.adc(0x4a,C.byref(out)),errno.EIO)
        self.assertEqual(out.value,0xcafe);self.assertFalse(self.lib.metric(4))

    def test_osm_uses_only_native_rows_and_retires_on_foreign_state_change(self):
        self.begin();self.lib.domains();self.lib.pressure(0)
        self.assertEqual([self.lib.domain_reg(i,0x920) for i in range(3)],[2,2,2])
        self.lib.pressure(2);self.assertEqual([self.lib.domain_reg(i,0x920) for i in range(3)],[1,1,1])
        self.lib.pressure(4);self.assertEqual([self.lib.domain_reg(i,0x920) for i in range(3)],[0,0,0])
        self.lib.set_domain_reg(1,0x920,99);before=self.lib.metric(1)
        self.lib.pressure(0);self.assertEqual(self.lib.domain_reg(1,0x920),99)
        self.assertEqual(self.lib.domain_reg(0,0x920),2)
        self.assertEqual(self.lib.metric(1)-before,2)
        before=self.lib.metric(1);self.lib.set_domain_reg(0,0x150,0);self.lib.pressure(3)
        self.assertEqual(self.lib.domain_reg(0,0x920),2)
        self.assertEqual(self.lib.metric(1)-before,1)

    def test_gold_prime_use_native_lut_core_count_two_and_refuse_boost_only_rows(self):
        self.begin()
        # One CPU belongs to each Gold/Prime domain, but native DT max_cores
        # is2. Rows tagged1 alone cannot become its ordinary thermal ceiling.
        for row in range(40):
            offset=0x110+32*row
            value=self.lib.domain_reg(1,offset)
            self.lib.set_domain_reg(1,offset,(value&~(7<<16))|(1<<16))
        self.lib.domains();self.lib.pressure(0)
        self.assertEqual([self.lib.domain_reg(i,0x920) for i in range(3)],[2,0,2])


if __name__=='__main__':unittest.main()
