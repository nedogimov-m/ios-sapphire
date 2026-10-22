"""Run both actual rail overlays, including the trusted producer and valid VSET."""
import ast
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


def harness_literal(name):
    tree=ast.parse((HERE/'test_touch_rail.py').read_text())
    values=[ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)]
    assert len(values)==1
    return values[0]


class RailState(C.Structure):
    _fields_=[('index_verified',C.c_bool),('pmic_type',C.c_uint8),('pmic_subtype',C.c_uint8),
              ('sid',C.c_uint8),('peripheral_type',C.c_uint8),('peripheral_subtype',C.c_uint8),
              ('base',C.c_uint16),('millivolts',C.c_uint16),('valid_millivolts',C.c_uint16),
              ('mode',C.c_uint8),('enable',C.c_uint8),('status',C.c_uint8)]


class TouchRailReadyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        work=Path(cls.tmp.name)
        dev=work/'bsd/dev';dev.mkdir(parents=True)
        base='\n'.join(s[1:] for s in (HERE/'touch-rail-observe.patch').read_text().splitlines()
                       if s.startswith('+') and not s.startswith('+++'))+'\n'
        (dev/'redfin_spmi.c').write_text('#if defined(ARM64_BOARD_CONFIG_SWEET)\n'+base+'#endif\n')
        subprocess.run(['git','apply',str(HERE/'touch-rail-ready.patch')],cwd=work,
                       check=True,capture_output=True)
        actual=(dev/'redfin_spmi.c').read_text()
        actual=re.sub(r'__asm__ volatile\([^;]*;','(void)0;',actual)
        store='*(volatile uint32_t *)(redfin_spmi_proof.observer + channel) = command;'
        assert actual.count(store)==1
        actual=actual.replace(store,'model_command(channel, command);')
        stub=harness_literal('stub')

        def replace(old,new):
            nonlocal stub
            assert stub.count(old)==1,(old,stub.count(old))
            stub=stub.replace(old,new)

        replace('#include <errno.h>','#include <errno.h>\n#define ARM64_BOARD_CONFIG_SWEET 1\n'
                'static unsigned phase,ready_variant,hardware_reads,ready_volt_reads,ready_model_reads,valid_reads;')
        replace('(last_reg==0x40 && last_count==2)||(last_reg==0x45 && last_count==2));',
                '(last_reg==0x40 && last_count==2)||(last_reg==0x42 && last_count==2)||'
                '(last_reg==0x45 && last_count==2));')
        replace('static uint32_t redfin_spmi_rd(vm_offset_t base,unsigned offset){',r'''
static uint32_t redfin_spmi_rd(vm_offset_t base,unsigned offset){
 hardware_reads++;
 if(phase && ready_variant==19 && base==1 && offset==0)return 0x40000000;
 if(phase && ready_variant==14 && base==1 && offset==0x900+17*4 && last_apid==17)
  return mappings[17]^0x100;
 if(phase && ready_variant==17 && base==3 && offset==0x700+17*4)return 1;
''')
        replace('if(offset==channel+8){',r'''
if(offset==channel+8){
   if(phase && target_fault() && ready_variant==15)return 9;
   if(phase && target_fault() && ready_variant==16)return 0;
''')
        replace('if(ppid==1)return issue==8 ? 0x1f51 : 0x1e51;',r'''
if(ppid==1){
    if(phase){ready_model_reads++;if(ready_variant==1 || (ready_variant==18 && ready_model_reads>1))return 0x1f51;}
    return issue==8 ? 0x1f51 : 0x1e51;
   }
   if(phase && last_reg==4 && target_fault() && ready_variant==2)return 0x7c04;
   if(issue==21 && last_reg==4 && ppid==0x140)return 0x3505;
   if(last_reg==0x42){valid_reads++;return phase && ready_variant==4 ? 3300 : 3304;}
   if(phase && last_reg==0x40 && target_fault()){
    ready_volt_reads++;
    if(ready_variant==3 || (ready_variant==13 && ready_volt_reads>1))return 3300;
   }
   if(phase && last_reg==0x45 && target_fault()){
    if(ready_variant==5)return 0x8003;
    if(ready_variant==6)return 0x8004;
    if(ready_variant==7)return 7;
    if(ready_variant==8)return 0x8107;
   }
   if(phase && last_reg==8 && target_fault()){
    if(ready_variant==9)return 3;
    if(ready_variant==10)return 0xa3;
    if(ready_variant==11)return 0xff;
    if(ready_variant==12)return 0x83;
    if(ready_variant==22)return 0xc3;
 if(ready_variant==23)return 0x87;
 if(ready_variant==24)return 0xa7;
 if(ready_variant==25)return 0x8f;
 if(ready_variant==26)return 0x97;
 if(ready_variant==27)return 0xc7;
   }
''')
        # The producer must observe exact7d at5000 before publishing its proof.
        replace('return issue==14 && target_fault() ? 0x8004 : issue==20 && target_fault() ? 0x7d04 : 0x3504;',
                'return issue==14 && target_fault() ? 0x8004 : target_fault() ? 0x7d04 : 0x3504;')
        wrapper=harness_literal('wrapper').replace('int run(unsigned variant){','int base_run(unsigned variant){')
        extra=r'''
int prepare(unsigned producer,unsigned variant){
 phase=0;ready_variant=0;hardware_reads=ready_volt_reads=ready_model_reads=valid_reads=0;
 redfin_rail_observation_complete=false;redfin_rail_poisoned=false;redfin_rail_snapshot_busy=0;
 int result=base_run(producer);
 phase=1;ready_variant=variant;ready_volt_reads=ready_model_reads=valid_reads=0;
 if(variant==20)mode=0;
 if(variant==21)cpus=2;
 return result;
}
int ready_value(void){return redfin_touch_rail_ready();}
int snapshot_value(struct redfin_touch_rail_state *out){return redfin_touch_rail_snapshot(NULL,out);}
unsigned proof_stat(unsigned index){
 unsigned values[]={hardware_reads,commands,violations,redfin_rail_observation_complete,redfin_rail_poisoned,valid_reads,wait_us};
 return index<7 ? values[index] : 0;
}
void set_busy(unsigned busy){redfin_rail_snapshot_busy=busy;}
void corrupt_target(void){redfin_rail_verified_targets[1].ppid=0x151;}
unsigned state_size(void){return sizeof(struct redfin_touch_rail_state);}
'''
        (work/'ready.c').write_text(stub+actual+wrapper+extra)
        subprocess.run([cc,'-std=c11','-shared','-fPIC','-Wall','-Wextra','-Werror','-I',str(dev),
                        str(work/'ready.c'),'-o',str(work/'ready.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(work/'ready.so'))
        cls.lib.prepare.argtypes=[C.c_uint,C.c_uint]
        cls.lib.snapshot_value.argtypes=[C.POINTER(RailState)]
        assert cls.lib.state_size()==C.sizeof(RailState)

    def prepare(self,producer=20,variant=0):
        result=self.lib.prepare(producer,variant)
        self.assertEqual(self.lib.proof_stat(2),0)
        return result

    def ready(self):
        result=self.lib.ready_value()
        self.assertEqual(self.lib.proof_stat(2),0,'unexpected SID/APID/register/opcode or channel reuse')
        self.assertIn(result,(0,1))
        return result

    def test_full_scan_fresh_configured_valid_voltage_and_power_state_prove_ready(self):
        self.assertEqual(self.prepare(),0)
        self.assertEqual(self.ready(),1)
        self.assertEqual(self.lib.proof_stat(5),2)
        state=RailState()
        self.assertEqual(self.lib.snapshot_value(C.byref(state)),0)
        self.assertTrue(state.index_verified)
        self.assertEqual((state.base,state.peripheral_subtype,state.millivolts,state.valid_millivolts),
                         (0x5000,0x7d,3304,3304))
        self.assertEqual((state.mode,state.enable,state.status),(7,0x80,0x80))

    def test_failed_incomplete_wrong_model_or_non_ldo_scan_never_permits_further_mmio(self):
        for producer in (7,8,10,11,12,13,14,17,19,21):
            self.prepare(producer)
            before=tuple(self.lib.proof_stat(i) for i in (0,1))
            self.assertEqual(self.ready(),0)
            self.assertEqual(tuple(self.lib.proof_stat(i) for i in (0,1)),before)

    def test_configured_value_alone_and_wrong_mode_enable_status_never_prove_power(self):
        for variant in (3,4,5,6,7,8,9,10,11,13,22):
            self.prepare(variant=variant)
            self.assertEqual(self.ready(),0)
        self.prepare(variant=12)
        self.assertEqual(self.ready(),1)  # READY plus source-family mode-state low bits.

    def test_fresh_model_subtype_map_owner_denial_timeout_or_bracket_change_invalidates_proof(self):
        for variant in (1,2,14,15,16,17,18,19):
            self.prepare(variant=variant)
            self.assertEqual(self.ready(),0)
            self.assertEqual(self.lib.proof_stat(3),0)
            before=tuple(self.lib.proof_stat(i) for i in (0,1))
            self.assertEqual(self.ready(),0)
            self.assertEqual(tuple(self.lib.proof_stat(i) for i in (0,1)),before)

    def test_observed_pmic5_status87_proves_two_fresh_power_samples(self):
        self.prepare(variant=12)
        self.assertEqual(self.ready(),1)
        baseline=tuple(self.lib.proof_stat(i) for i in (0,1,5))
        self.prepare(variant=23)
        self.assertEqual(self.ready(),1)
        self.assertEqual(tuple(self.lib.proof_stat(i) for i in (0,1,5)),baseline)
        self.assertEqual(self.lib.proof_stat(5),2)

    def test_status87_still_rejects_ocp_and_all_reserved_status_bits(self):
        for variant in (24,25,26,27):
            with self.subTest(variant=variant):
                self.prepare(variant=variant)
                self.assertEqual(self.ready(),0)

    def test_flags_up_and_serialization_refuse_before_bus_access(self):
        for variant in (20,21):
            self.prepare(variant=variant)
            before=tuple(self.lib.proof_stat(i) for i in (0,1))
            self.assertEqual(self.ready(),0)
            self.assertEqual(tuple(self.lib.proof_stat(i) for i in (0,1)),before)
        self.prepare();self.lib.set_busy(1)
        before=tuple(self.lib.proof_stat(i) for i in (0,1))
        self.assertEqual(self.ready(),0)
        self.assertEqual(tuple(self.lib.proof_stat(i) for i in (0,1)),before)

    def test_target_identity_cache_cannot_redirect_voltage_reads(self):
        self.prepare();self.lib.corrupt_target()
        before=tuple(self.lib.proof_stat(i) for i in (0,1))
        self.assertEqual(self.ready(),0)
        self.assertEqual(tuple(self.lib.proof_stat(i) for i in (0,1)),before)
        self.assertEqual(self.lib.proof_stat(3),0)


if __name__=='__main__':
    unittest.main()
