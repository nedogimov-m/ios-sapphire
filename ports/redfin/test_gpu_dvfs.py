"""Exercise native fuse/bin/rail pairing and the actual serialized DCVS adapter."""
import ctypes as C
import errno
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from ports.redfin import gpu_dvfs,mkadt
from ports.redfin.memory import _tree
from test_gpu_command import rpmh_header

HERE=Path(__file__).resolve().parent
HARNESS=r'''
#include <stdint.h>
#include <string.h>
#include "redfin_rpmh.h"
#include "include/redfin_gpu_mapping.h"
#include "include/redfin_gpu_dvfs.h"
static struct {
 const struct rf_dvfs_profile *dvfs_profile;struct rf_a6_perf performance;
 uint64_t dvfs_activity;unsigned dvfs_index,dvfs_bandwidth,dvfs_changes;
 uintptr_t gpu;uint32_t wptr;void *context;
} gx;
static uint64_t clock_ns;static struct rf_dvfs_thermal thermal;
static unsigned live,audits,hfis,poisoned,fault_audit,fault_hfi,fault_thermal,rptr;
static uint32_t request[4];
static int gr_live(void){return live&&!poisoned?0:ECANCELED;}
static uint32_t gm_scalar_read(uintptr_t at){(void)at;return rptr;}
static uint64_t gm_time_ns(void *p){(void)p;return clock_ns;}
static int redfin_gpu_thermal(uint64_t *at,int32_t *hot,int32_t *battery,unsigned *pressure){
 if(fault_thermal)return ENXIO;*at=thermal.sampled_ns;*hot=thermal.hottest_mc;*battery=thermal.battery_mc;*pressure=thermal.pressure;return 0;
}
static int redfin_gpu_audit(void){return ++audits==fault_audit?EFAULT:gr_live();}
static int gx_hfi(void *p,unsigned id,uint32_t *words,unsigned count){
 (void)p;if(id!=30||count!=4||words[0]||words[1]!=1)return EINVAL;
 memcpy(request,words,sizeof(request));++hfis;return hfis==fault_hfi?ETIMEDOUT:0;
}
static void redfin_gpu_poison(const char *why){(void)why;++poisoned;}
#define printf(...) ((void)0)
@ADAPTER@
void reset(unsigned bin){
 memset(&gx,0,sizeof(gx));gx.dvfs_profile=rf_dvfs_profile(bin);
 gx.performance.gpu_levels=gx.dvfs_profile?gx.dvfs_profile->count:2;
 if(gx.dvfs_profile)for(unsigned i=0;i<gx.dvfs_profile->count;++i)gx.performance.gpu[i].khz=gx.dvfs_profile->level[i].khz;
 gx.dvfs_index=1;gx.dvfs_bandwidth=5;clock_ns=UINT64_C(100000000000);
 thermal=(struct rf_dvfs_thermal){clock_ns,50000,32000,0};
 live=1;audits=hfis=poisoned=fault_audit=fault_hfi=fault_thermal=rptr=0;memset(request,0,sizeof(request));
}
int run(unsigned activity){return gr_dvfs(activity!=0);}
void set_thermal(int hot,int battery,unsigned pressure){thermal.hottest_mc=hot;thermal.battery_mc=battery;thermal.pressure=pressure;thermal.sampled_ns=clock_ns;}
void advance(unsigned ms){clock_ns+=(uint64_t)ms*1000000u;}
void fault(unsigned audit,unsigned hfi,unsigned temp,unsigned ring){fault_audit=audit;fault_hfi=hfi;fault_thermal=temp;rptr=ring;}
unsigned metric(unsigned i){unsigned a[]={gx.dvfs_index,gx.dvfs_bandwidth,audits,hfis,poisoned,request[2],request[3]};return i<7?a[i]:0;}
unsigned target(unsigned bin,uint64_t now,unsigned busy,uint64_t sampled,int hot,int battery,unsigned pressure){
 struct rf_dvfs_thermal s={sampled,hot,battery,pressure};return rf_dvfs_target(rf_dvfs_profile(bin),now,busy!=0,&s);
}
const void *native(unsigned which){return which==0?(const void *)rf_dvfs_policy:which==1?(const void *)rf_dvfs_opps:(const void *)rf_dvfs_profiles;}
unsigned native_bytes(unsigned which){return which==0?sizeof(rf_dvfs_policy):which==1?sizeof(rf_dvfs_opps):sizeof(rf_dvfs_profiles);}
int rails(unsigned bin,unsigned bad,unsigned index,uint32_t *vote){
 struct rf_cmddb_resource gfx={.type=RF_CMDDB_ARC,.aux_version=0x1000,.level_count=7,.levels={0,64,128,192,256,320,384}};
 struct rf_cmddb_resource cx={.type=RF_CMDDB_ARC,.aux_version=0x1000,.level_count=3,.levels={0,48,64}};
 struct rf_cmddb_resource mx=gfx;struct rf_a6_perf p;
 if(bad)gfx.level_count=2;
 int error=rf_dvfs_perf_make(rf_dvfs_profile(bin),&gfx,&cx,&mx,&p);
 if(!error){if(index>=p.gpu_levels)return ERANGE;*vote=p.gpu[index].vote;}return error;
}
'''


class DVFSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        p=Path(cls.temp.name);(p/'redfin_rpmh.h').write_text(rpmh_header())
        source=(HERE/'gpu-runtime.inc').read_text()
        adapter=source[source.index('static int gr_dvfs(bool activity)'):source.index('\nint redfin_gpu_dvfs_idle')]
        (p/'model.c').write_text(HARNESS.replace('@ADAPTER@',adapter))
        built=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                              '-I',str(p),'-I',str(HERE),str(p/'model.c'),'-o',str(p/'model.so')],capture_output=True,text=True)
        if built.returncode:raise RuntimeError(built.stderr)
        cls.lib=C.CDLL(str(p/'model.so'));cls.lib.native.restype=C.c_void_p
        cls.lib.target.argtypes=[C.c_uint,C.c_uint64,C.c_uint,C.c_uint64,C.c_int,C.c_int,C.c_uint]
        cls.lib.rails.argtypes=[C.c_uint,C.c_uint,C.c_uint,C.POINTER(C.c_uint32)]

    def setUp(self):self.lib.reset(0)

    def test_native_c_tables_match_exact_host_boot_contract(self):
        words=[gpu_dvfs.POLICY,tuple(v for row in gpu_dvfs.OPPS for v in row),gpu_dvfs.profile_words()]
        for which,values in enumerate(words):
            self.assertEqual(C.string_at(self.lib.native(which),self.lib.native_bytes(which)),mkadt.u32(*values))

    def test_each_bin_selects_its_own_native_maximum_and_temperature_caps(self):
        now=100000000000
        for bin,rows in gpu_dvfs.PROFILES:
            self.assertEqual(self.lib.target(bin,now,1,now,50000,32000,0),len(rows)-1)
            for pressure,cap in [(1,500000),(2,400000),(3,275000),(4,275000)]:
                expected=max(i for i,row in enumerate(rows) if row[0]<=cap)
                self.assertEqual(self.lib.target(bin,now,1,now,50000,32000,pressure),expected)
            self.assertEqual(self.lib.target(bin,now,0,now,50000,32000,0),1)
        self.assertEqual(self.lib.target(255,now,1,now,50000,32000,0),0)

    def test_stale_missing_future_invalid_or_hot_inputs_cannot_authorize_boost(self):
        now=100000000000
        for sampled,hot,battery,pressure in [(0,50000,32000,0),(now-1000000001,50000,32000,0),
                (now+1,50000,32000,0),(now,-273150,32000,0),(now,50000,-273150,0),
                (now,50000,32000,5),(now,95000,32000,0),(now,50000,56000,0)]:
            self.assertEqual(self.lib.target(0,now,1,sampled,hot,battery,pressure),1)

    def test_native_voltage_votes_require_all_selected_bin_levels(self):
        for bin,rows in gpu_dvfs.PROFILES:
            for index,row in enumerate(rows):
                vote=C.c_uint32();self.assertEqual(self.lib.rails(bin,0,index,C.byref(vote)),0)
                self.assertEqual(vote.value>>16,row[1])
            self.assertNotEqual(self.lib.rails(bin,1,len(rows)-1,C.byref(C.c_uint32())),0)

    def test_actual_adapter_boosts_once_throttles_and_returns_to_minimum_when_idle(self):
        self.assertEqual(self.lib.run(1),0)
        self.assertEqual([self.lib.metric(i) for i in [0,1,2,3,5,6]],[6,10,2,1,6,10])
        self.assertEqual(self.lib.run(1),0);self.assertEqual(self.lib.metric(3),1)
        self.lib.set_thermal(75000,32000,1);self.assertEqual(self.lib.run(0),0)
        self.assertEqual((self.lib.metric(0),self.lib.metric(1)),(3,8))
        self.lib.advance(201);self.assertEqual(self.lib.run(0),0)
        self.assertEqual((self.lib.metric(0),self.lib.metric(1)),(1,5))

    def test_actual_hfi_failure_or_boundary_audit_stops_without_pretending_completion(self):
        for audit,hfi in [(1,0),(0,1),(2,0)]:
            self.lib.reset(0);self.lib.fault(audit,hfi,0,0)
            self.assertNotEqual(self.lib.run(1),0)
            self.assertEqual((self.lib.metric(0),self.lib.metric(4)),(1,1))
            calls=self.lib.metric(3);self.assertNotEqual(self.lib.run(1),0)
            self.assertEqual(self.lib.metric(3),calls)

    def test_busy_ring_invalid_lease_or_missing_real_thermal_data_never_boosts(self):
        self.lib.fault(0,0,0,1);self.assertEqual(self.lib.run(1),errno.EBUSY)
        self.assertEqual(self.lib.metric(3),0)
        self.lib.fault(0,0,1,0);self.assertEqual(self.lib.run(1),0)
        self.assertEqual((self.lib.metric(0),self.lib.metric(3)),(1,0))

    def test_actual_captured_native_fdt_binds_all_bins_and_rejects_mutated_fuse_or_opp(self):
        path=HERE.parent.parent/'research/redfin-root/device.dtb'
        if not path.exists():self.skipTest('optional private native Redfin DTB')
        nodes,_=_tree(path.read_bytes())
        def tree():
            t=mkadt.build(0x180000000,0x80000000,0,smp=True,smp_cpus=8)
            t.children.append(mkadt.node('redfin-gpu-command',[('runtime-policy',mkadt.u32(1))]))
            return t
        proof=gpu_dvfs.add_contract(tree(),nodes);self.assertEqual(proof['bins'],5)
        for path,key,value in [('/soc/qfprom@780000/gpu_speed_bin@1ea','bits',struct.pack('>II',6,8)),
                ('/soc/gpu-opp-table/opp-750000000','opp-microvolt',struct.pack('>I',320))]:
            changed={p:dict(v) for p,v in nodes.items()};changed[path][key]=value
            with self.assertRaises(ValueError):gpu_dvfs.add_contract(tree(),changed)
