"""Measured QG units, native ADC5/TSENS boundaries and thermal charge policy."""
import ctypes as C
import errno
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin import platform_power

HERE=Path(__file__).resolve().parent


class Sample(C.Structure):
    _fields_=[(n,C.c_uint32 if n in ('version','bytes','valid','faults','usb_type','integrated') else C.c_int32)
        for n in ('version','bytes','valid','uv','ua','mc','soc','present','external','charging','full','wireless',
                  'full_uah','design_uah','charge_uah','usb_uv','usb_ua','faults','usb_type','integrated')]


class PowerPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);p=Path(cls.tmp.name)
        (p/'policy.c').write_text('''
#include "power-policy.h"
#include "power-conversion.h"
static struct redfin_soc_tracker tracker;
int voltage(unsigned raw){return redfin_qg_voltage((uint16_t)raw);}
int current(unsigned raw,unsigned subtype){return redfin_qg_current((uint16_t)raw,subtype);}
int temperature(unsigned raw,int *out){return redfin_adc5_battery_temp((uint16_t)raw,out);}
int tsens(unsigned raw,int *out){return redfin_tsens_value(raw,out);}
int valid(struct redfin_power_sample *s){return redfin_power_valid(s);}
int pressure(int hot,int batt,unsigned previous){return redfin_thermal_pressure(hot,batt,previous);}
int charge(struct redfin_power_sample *s,unsigned fv,unsigned fcc,unsigned timer,unsigned jeita){return redfin_charger_enable_allowed(s,fv,fcc,timer,jeita);}
int pause_charge(struct redfin_power_sample *s){return redfin_charger_must_pause(s);}
unsigned faults(unsigned a,unsigned b,int voltage,int fv){return redfin_smb5_faults(a,b,voltage,fv);}
void charging_state(struct redfin_power_sample *s,unsigned status,unsigned enabled){redfin_smb5_state(s,status,enabled);}
int integrate(struct redfin_power_sample *s,uint64_t ns){return redfin_soc_update(&tracker,s,ns);}
void reset_tracker(void){tracker=(struct redfin_soc_tracker){0};}
''')
        subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-I',str(HERE),str(p/'policy.c'),'-o',str(p/'policy.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(p/'policy.so'))
        cls.lib.voltage.argtypes=[C.c_uint];cls.lib.current.argtypes=[C.c_uint,C.c_uint]
        cls.lib.tsens.argtypes=[C.c_uint,C.POINTER(C.c_int)]
        cls.lib.temperature.argtypes=[C.c_uint,C.POINTER(C.c_int)]
        cls.lib.pressure.argtypes=[C.c_int,C.c_int,C.c_uint]
        cls.lib.valid.argtypes=cls.lib.pause_charge.argtypes=[C.POINTER(Sample)]
        cls.lib.charge.argtypes=[C.POINTER(Sample),C.c_uint,C.c_uint,C.c_uint,C.c_uint]
        cls.lib.integrate.argtypes=[C.POINTER(Sample),C.c_uint64]
        cls.lib.faults.argtypes=[C.c_uint,C.c_uint,C.c_int,C.c_int];cls.lib.faults.restype=C.c_uint
        cls.lib.charging_state.argtypes=[C.POINTER(Sample),C.c_uint,C.c_uint]

    def sample(self):
        return Sample(1,C.sizeof(Sample),63,4000000,-1000000,30000,5000,1,0,0,0,0,
                      2000000,4000000,0,0,0,0,0,0)

    def test_qg_scaling_matches_independent_native_recovery_reading_and_current_sign(self):
        # The actual recovery snapshot reports4440253uV and +/-4272uA;
        # these are the corresponding QG codes with native10A/subtype4 scale.
        self.assertEqual(self.lib.voltage(22813),4440253)
        self.assertEqual(self.lib.current(0xfff2,4),4272)
        self.assertEqual(self.lib.current(14,4),-4272)
        self.assertEqual(self.lib.current(14,3),-2136)
        self.assertEqual(self.lib.current(0,4),0)

    def test_native_adc5_calibrated_thermistor_and_tsens_signed_validity(self):
        t=C.c_int(123456)
        self.assertTrue(self.lib.temperature(10867,C.byref(t)));self.assertEqual(t.value,36000)
        for raw in [0,1,0x8000,0xffff]:
            t.value=123456;self.assertFalse(self.lib.temperature(raw,C.byref(t)));self.assertEqual(t.value,123456)
        self.assertTrue(self.lib.tsens((1<<21)|420,C.byref(t)));self.assertEqual(t.value,42000)
        self.assertTrue(self.lib.tsens((1<<21)|0xf9c,C.byref(t)));self.assertEqual(t.value,-10000)
        for raw in [420,(1<<21)|0x7ff,(1<<21)|0x800]:
            t.value=123456;self.assertFalse(self.lib.tsens(raw,C.byref(t)));self.assertEqual(t.value,123456)

    def test_missing_or_unsafe_measurements_never_authorize_charge_enable(self):
        s=self.sample();s.external=1
        allow=lambda:self.lib.charge(C.byref(s),4450000,2000000,3,15)
        self.assertTrue(allow())
        for field,value in [('valid',s.valid&~4),('mc',45000),('mc',-1000),('uv',4500000),
            ('present',0),('faults',2),('bytes',C.sizeof(Sample)-4)]:
            before=getattr(s,field);setattr(s,field,value)
            self.assertFalse(allow(),field);self.assertTrue(self.lib.pause_charge(C.byref(s)),field)
            setattr(s,field,before)
        for fv,fcc,timer,jeita in [(4460000,2000000,3,15),(4450000,2050000,3,15),
            (4450000,2000000,0,15),(4450000,2000000,3,0)]:
            self.assertFalse(self.lib.charge(C.byref(s),fv,fcc,timer,jeita))
        s.external=0;self.assertFalse(allow())

    def test_real_heat_hysteresis_and_battery_critical_threshold(self):
        for hot,want in [(69900,0),(70000,1),(80000,2),(90000,3),(100000,4)]:
            self.assertEqual(self.lib.pressure(hot,30000,0),want)
        self.assertEqual(self.lib.pressure(76000,30000,2),2)
        self.assertEqual(self.lib.pressure(74900,30000,2),1)
        self.assertEqual(self.lib.pressure(40000,55000,0),4)
        self.assertEqual(self.lib.pressure(40000,53000,4),4)
        self.assertEqual(self.lib.pressure(40000,40000,1),0)

    def test_native_smb5_health_distinguishes_afp_jeita_and_measured_overvoltage(self):
        # AFP and soft JEITA indications are not the native hard-health bits.
        for status7 in [0,1,2,3,0x10,0x20,0x30,0x33]:
            self.assertEqual(self.lib.faults(0,status7,4440000,4450000),0)
        for hard in [4,8,12]:
            self.assertEqual(self.lib.faults(0,hard,4000000,4400000),hard<<8)
        self.assertEqual(self.lib.faults(2,0,4439999,4400000),0)
        self.assertEqual(self.lib.faults(2,0,4440000,4400000),2)
        for invalid in [0,3599999,4450001]:
            self.assertEqual(self.lib.faults(2,0,4000000,invalid),2)
        s=self.sample();s.external=1
        for state in range(8):
            self.lib.charging_state(C.byref(s),state,7)
            self.assertEqual(s.full,int(state in (0,5)))
            self.assertEqual(s.charging,int(state in (1,2,3,4)))
        self.lib.charging_state(C.byref(s),3,0);self.assertEqual(s.charging,0)
        s.faults=2;self.lib.charging_state(C.byref(s),3,7);self.assertEqual(s.charging,0)
        s.faults=0;s.external=0;self.lib.charging_state(C.byref(s),5,7)
        self.assertEqual((s.full,s.charging),(0,0))

    def test_current_integration_preserves_fraction_and_never_spans_an_unknown_gap(self):
        self.lib.reset_tracker();s=self.sample()
        self.assertTrue(self.lib.integrate(C.byref(s),1000000000));self.assertEqual(s.charge_uah,1000000)
        self.assertTrue(self.lib.integrate(C.byref(s),2000000000));self.assertEqual(s.charge_uah,999722)
        self.assertEqual(s.soc,4998);self.assertEqual(s.integrated,1)
        self.assertTrue(self.lib.integrate(C.byref(s),3000000000));self.assertEqual(s.charge_uah,999444)
        self.assertFalse(self.lib.integrate(C.byref(s),20000000000))
        # A later real monotonic seed resumes; no twenty-second guessed current.
        s.soc=4900;s.integrated=0
        self.assertTrue(self.lib.integrate(C.byref(s),21000000000));self.assertEqual(s.charge_uah,980000)
        s.external=1;s.full=1
        self.assertTrue(self.lib.integrate(C.byref(s),22000000000));self.assertEqual(s.soc,10000)

    def test_private_rtc_mapping_requires_the_actual_counter_and_bounded_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'anchor.json';value=dict(version=1,product='redfin',
                source='verified-offline-recovery/host-UTC',rtc_seconds=17000000,
                unix_offset_seconds=1770000000,uncertainty_ms=1001)
            path.write_text(json.dumps(value));self.assertEqual(platform_power.load_anchor(path),value)
            for key,bad in [('rtc_seconds',0),('uncertainty_ms',3000),('product','redwood'),('unix_offset_seconds',-1)]:
                original=value[key];value[key]=bad;path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):platform_power.load_anchor(path)
                value[key]=original


if __name__=='__main__':unittest.main()
