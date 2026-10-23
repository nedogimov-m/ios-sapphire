"""Run the actual WLAN PMIC observer with modeled observer-only bus channels."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

import mkadt
import wifi_platform as P
from test_wifi_wlan import source_nodes

HERE = Path(__file__).resolve().parent


class WiFiPmicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host compiler unavailable')
        patch = (HERE / 'touch-rail-observe.patch').read_text()
        rail = '\n'.join(line[1:] for line in patch.splitlines()
                         if line.startswith('+') and not line.startswith('+++'))
        mapping = 'static bool\nredfin_rail_mapping' + rail.split('static bool\nredfin_rail_mapping', 1)[1].split('/* APID', 1)[0]
        actual = (HERE / 'wifi_pmic.inc').read_text()
        actual = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', actual)
        store = '*(volatile uint32_t *)(redfin_spmi_proof.observer + channel) = command;'
        assert actual.count(store) == 1
        actual = actual.replace(store, 'model_command(channel, command);')
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
typedef uintptr_t vm_offset_t;
struct redfin_rail_target { unsigned ppid,apid,owner;uint32_t mapping; };
static struct {bool ready;vm_offset_t core,observer,config;uint32_t version;} redfin_spmi_proof;
static bool redfin_rail_attempted,redfin_rail_poisoned;
static unsigned redfin_rail_snapshot_busy;
static unsigned issue,commands,violations,wait_us,last_apid,last_reg,last_count,phase,checks,fail_check;
static unsigned configured_reads,preferred_commands;
static uint32_t mappings[512],owners[512];
static bool pending,status_seen,alive;
static char output[20000];static size_t used;
static int log_printf(const char *format,...){
 va_list args;va_start(args,format);int n=vsnprintf(output+used,sizeof(output)-used,format,args);va_end(args);
 if(n<0 || (size_t)n>=sizeof(output)-used){violations++;return 0;}used+=(size_t)n;return n;
}
#define printf log_printf
static bool ml_get_interrupts_enabled(void){return issue!=2;}
static uint64_t model_rsr(const char *name){return !strcmp(name,"CurrentEL") ? (issue==3 ? 8 : 4) : issue==4 ? 0x100 : 0;}
#define __builtin_arm_rsr64(name) model_rsr(name)
static bool redfin_spmi_return_ready(void){return issue!=5;}
static bool redfin_rail_platform(void){return issue!=6;}
static void delay(unsigned us){wait_us+=us;}
static int child_check(void *child){
 ++checks;return child!=&alive || !alive || (fail_check && checks>=fail_check) ? -1 : 0;
}
static void model_command(unsigned channel,uint32_t command){
 if(channel%0x80 || channel/0x80>=512 || pending){violations++;return;}
 last_apid=channel/0x80;last_reg=(command>>4)&255;last_count=(command&15)+1;
 unsigned ppid=(mappings[last_apid]>>8)&0xfff;
 bool model=(ppid==1 || ppid==0x401) && last_reg==4 && last_count==2;
 bool supply=(ppid==0x140 || ppid==0x14d || ppid==0x541 || ppid==0x54a || ppid==0x549) &&
  (((last_reg==4 || last_reg==0x40 || last_reg==0x42 || last_reg==0x45) && last_count==2) ||
   (last_reg==8 && last_count==1));
 if((command&~0x08000fffu) || (command>>27)!=1 || (!model&&!supply))violations++;
 commands++;preferred_commands+=last_apid==100;pending=true;status_seen=false;
}
static uint32_t redfin_spmi_rd(vm_offset_t base,unsigned offset){
 if(base==1){
  if(!offset)return redfin_spmi_proof.version;
  if(offset>=0x900 && offset<0x1100 && !(offset&3)){
   unsigned apid=(offset-0x900)/4;
   if(issue==7 && pending && apid==4)return mappings[apid]^0x100;
   return mappings[apid];
  }
 }else if(base==3 && offset>=0x700 && offset<0xf00 && !(offset&3)){
  unsigned apid=(offset-0x700)/4;return issue==8 && pending && apid==4 ? owners[apid]^1 : owners[apid];
 }else if(base==2 && pending){
  unsigned channel=last_apid*0x80,ppid=(mappings[last_apid]>>8)&0xfff;
  if(offset==channel+8){
   if(issue==9 && last_apid==4)return 0;
   status_seen=true;return issue>=10 && issue<=12 && last_apid==4 ? 1u|(1u<<(issue-9)) : 1;
  }
  if(offset==channel+0x18 && status_seen){
   pending=false;
   if(ppid==1)return 0x1e51;
   if(ppid==0x401)return issue==13 ? 0x2051 : 0x1f51;
   if(last_reg==4)return issue==14 && ppid==0x541 ? 0x2004 : 0x6b04;
   if(last_reg==0x40){configured_reads++;return issue==15 && ppid==0x541 && !(configured_reads&1) ? 1305 : 1304;}
   if(last_reg==0x42)return phase ? 1304 : 0;
   if(last_reg==0x45)return phase ? 0x8004 : 4;
   if(last_reg==8)return phase ? 0x87 : 3;
  }
 }
 violations++;return 0;
}
'''
        api = r'''
void reset(unsigned variant){
 issue=variant;commands=violations=wait_us=last_apid=last_reg=last_count=phase=checks=fail_check=0;
 configured_reads=preferred_commands=0;used=0;output[0]=0;pending=status_seen=false;alive=variant!=1;
 memset(&redfin_wp,0,sizeof(redfin_wp));memset(mappings,0,sizeof(mappings));memset(owners,0,sizeof(owners));
 redfin_spmi_proof.ready=true;redfin_spmi_proof.core=1;redfin_spmi_proof.observer=2;
 redfin_spmi_proof.config=3;redfin_spmi_proof.version=0x50000000;
 redfin_rail_attempted=redfin_rail_poisoned=false;redfin_rail_snapshot_busy=0;
 for(unsigned i=0;i<7;i++){mappings[i]=(redfin_wp_ppids[i]<<8)|1;owners[i]=4;}
 if(variant==16)mappings[4]=0;
 if(variant==17){mappings[100]=mappings[4];owners[100]=0;}
 if(variant==18)redfin_rail_snapshot_busy=1;
 if(variant==19)redfin_rail_attempted=true;
}
int run(unsigned value){phase=value;return redfin_wifi_wlan_pmic_observe(value,&alive,child_check);}
int other_child(unsigned value){phase=value;return redfin_wifi_wlan_pmic_observe(value,&phase,child_check);}
void fail_after(unsigned value){fail_check=value;}
unsigned metric(unsigned which){
 unsigned values[]={commands,violations,wait_us,checks,preferred_commands,redfin_wp.poisoned};
 return which<6 ? values[which] : 0;
}
int guard(unsigned index,unsigned offset,unsigned count,unsigned kind){
 redfin_wp.active=true;uint16_t out=0;struct redfin_rail_target copy=redfin_wp.targets[index%7];
 int result=redfin_wp_read(kind==1 ? &copy : &redfin_wp.targets[index%7],offset,count,kind==2 ? NULL : &out);
 redfin_wp.active=false;return result;
}
const char *log_text(void){return output;}
'''
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        (directory / 'pmic.c').write_text(prefix + mapping + actual + api)
        result = subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                                 str(directory / 'pmic.c'), '-o', str(directory / 'pmic.so')], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(directory / 'pmic.so'))
        cls.lib.log_text.restype = C.c_char_p
        cls.lib.guard.argtypes = [C.c_uint] * 4

    def setUp(self):
        self.lib.reset(0)

    def run_phase(self, phase):
        result = self.lib.run(phase)
        self.assertEqual(self.lib.metric(1), 0, 'wrong SID/APID, opcode, register, width, mapping or channel reuse')
        self.assertLessEqual(self.lib.metric(2), 2500)
        return result

    def test_three_ordered_phases_observe_disabled_and_enabled_states_without_a_power_decision(self):
        for phase in range(3):
            self.assertEqual(self.run_phase(phase), 0)
            self.assertEqual(self.lib.metric(0), 54 * (phase + 1))
        log = self.lib.log_text().decode()
        self.assertIn('phase=0 candidate PPID=0x541', log)
        self.assertIn('valid_mV=0 MODE=0x4 ENABLE=0 STATUS=0x3 ready=0', log)
        self.assertIn('valid_mV=1304 MODE=0x4 ENABLE=0x80 STATUS=0x87 ready=1', log)
        self.assertIn('no supply-readiness claim', log)
        for phase in range(4):
            self.assertNotEqual(self.run_phase(phase), 0)
        self.assertEqual(self.lib.metric(0), 162)

    def test_profile_owner_irq_cpu_and_competing_observer_checks_precede_bus_commands(self):
        for issue in (1, 2, 3, 4, 5, 6, 18, 19):
            self.lib.reset(issue)
            self.assertNotEqual(self.run_phase(0), 0)
            self.assertEqual(self.lib.metric(0), 0)
        self.lib.reset(0)
        self.assertNotEqual(self.run_phase(1), 0)
        self.assertEqual(self.lib.metric(0), 0)

    def test_mapping_owner_loss_denial_timeout_and_changed_samples_quarantine_until_reset(self):
        for issue in (7, 8, 9, 10, 11, 12, 15):
            self.lib.reset(issue)
            self.assertNotEqual(self.run_phase(0), 0)
            before = self.lib.metric(0)
            for phase in range(3):
                self.assertNotEqual(self.run_phase(phase), 0)
            self.assertEqual(self.lib.metric(0), before)
            self.assertEqual(self.lib.metric(5), 1)

    def test_wrong_model_and_absent_apid_never_read_supply_fields(self):
        for issue, commands in ((13, 2), (16, 0)):
            self.lib.reset(issue)
            self.assertNotEqual(self.run_phase(0), 0)
            self.assertEqual(self.lib.metric(0), commands)

    def test_unknown_layout_is_header_only_and_ee0_mapping_is_preferred(self):
        self.lib.reset(14)
        self.assertEqual(self.run_phase(0), 0)
        self.assertEqual(self.lib.metric(0), 46)
        self.assertIn('header=0x2004 unified=0', self.lib.log_text().decode())
        self.lib.reset(17)
        self.assertEqual(self.run_phase(0), 0)
        self.assertEqual(self.lib.metric(4), 10)

    def test_every_policy_check_can_cancel_without_any_subsequent_channel_reuse(self):
        self.assertEqual(self.run_phase(0), 0)
        count = self.lib.metric(3)
        for at in range(1, count + 1):
            self.lib.reset(0); self.lib.fail_after(at)
            self.assertNotEqual(self.run_phase(0), 0)
            before = self.lib.metric(0)
            self.assertNotEqual(self.run_phase(0), 0)
            self.assertEqual(self.lib.metric(0), before)

    def test_read_allowlist_rejects_other_register_width_target_pointer_and_null_output(self):
        self.assertEqual(self.run_phase(0), 0)
        before = self.lib.metric(0)
        for values in ((0, 0x40, 2, 0), (2, 0x46, 1, 0), (2, 0x40, 3, 0),
                       (2, 0x45, 1, 0), (2, 8, 2, 0), (2, 0x40, 2, 1), (2, 0x40, 2, 2)):
            self.assertEqual(self.lib.guard(*values), errno.EINVAL)
        self.assertEqual(self.lib.metric(0), before)
        self.assertNotEqual(self.lib.other_child(1), 0)
        self.assertEqual(self.lib.metric(0), before)


class WiFiPmicProducerTests(unittest.TestCase):
    @staticmethod
    def nodes():
        source = source_nodes(); words = lambda *v: struct.pack('>' + 'I' * len(v), *v)
        spmi = '/soc/qcom,spmi@c440000'
        source[spmi] = {'compatible': b'qcom,spmi-pmic-arb\0', 'qcom,ee': words(0),
                        '#address-cells': words(2), '#size-cells': words(0)}
        for name, sid in (('pm8150', 0), ('pm8150', 1), ('pm8150l', 4), ('pm8150l', 5)):
            source[f'{spmi}/qcom,{name}@{sid}'] = {'compatible': b'qcom,spmi-pmic\0', 'reg': words(sid, 0)}
        return source

    def test_pmic_profile_requires_native_power_and_binds_actual_pmic_sids(self):
        source = self.nodes(); root = mkadt.build(0x180000000, 0x80000000)
        P.add_wlfw_contract(root, source)
        P.add_wlan_observer_contract(root, source, power=True, pmic=True)
        node = next(node for node in root.children if node.name == 'redfin-wifi-wlan')
        self.assertEqual(node.prop('pmic-observe'), struct.pack('<I', 1))
        self.assertEqual(struct.unpack('<7I', node.prop('pmic-candidates')), (1, 0x401, 0x140, 0x14d, 0x541, 0x54a, 0x549))
        for issue in ('power', 'ee', 'sid', 'disabled', 'missing'):
            source = self.nodes(); spmi = '/soc/qcom,spmi@c440000'
            if issue == 'ee': source[spmi]['qcom,ee'] = struct.pack('>I', 1)
            if issue == 'sid': source[spmi + '/qcom,pm8150l@5']['reg'] = struct.pack('>II', 3, 0)
            if issue == 'disabled': source[spmi + '/qcom,pm8150l@5']['status'] = b'disabled\0'
            if issue == 'missing': del source[spmi + '/qcom,pm8150l@4']
            root = mkadt.build(0x180000000, 0x80000000); P.add_wlfw_contract(root, source)
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                P.add_wlan_observer_contract(root, source, power=issue != 'power', pmic=True)


if __name__ == '__main__':
    unittest.main()
