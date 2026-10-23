"""Actual CE observer and native adapter: no register access before mode ACK."""
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
from test_wifi_snoc import snoc_nodes

HERE = Path(__file__).resolve().parent
HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include "wifi_snoc.h"
#include "wifi_ce.h"
enum {RF_MISSION_MODE=2,RF_MISSION_COMPLETE=3};
static uint32_t registers[RF_CE_MAP_BYTES/4];
static unsigned issue,checks,reads,maps,violations,fail_check,fail_read,change_at;
static uint64_t clock_ns;
static bool mapped;
enum {kIODirectionIn=1,kIOMapReadOnly=2,kIOMapInhibitCache=4};
class IOMemoryMap {
 public:uintptr_t getVirtualAddress(){return issue==13 ? 0 : (uintptr_t)registers;}
 uint64_t getLength(){return issue==12 ? 0x4000 : RF_CE_MAP_BYTES;}
};
static IOMemoryMap model_mapping;
class IOMemoryDescriptor {
 public:static IOMemoryDescriptor *withPhysicalAddress(uint64_t physical,uint64_t bytes,unsigned direction);
 IOMemoryMap *map(unsigned flags){
  if(flags!=(kIOMapReadOnly|kIOMapInhibitCache))violations++;
  mapped=issue!=11;return issue==11 ? NULL : &model_mapping;
 }
};
static IOMemoryDescriptor model_memory;
IOMemoryDescriptor *IOMemoryDescriptor::withPhysicalAddress(uint64_t physical,uint64_t bytes,unsigned direction){
 ++maps;if(physical!=RF_CE_BASE || bytes!=RF_CE_MAP_BYTES || direction!=kIODirectionIn)violations++;
 return issue==10 ? NULL : &model_memory;
}
struct fw_start_map {IOMemoryDescriptor *memory;IOMemoryMap *map;uintptr_t base;};
struct fw_start_context {
 bool mission_mode;struct {unsigned poisoned,stage,waiting,responses;} mission;
 uint64_t mission_settle_ns;struct fw_start_map ce_map;struct rf_ce_snapshot ce;
};
static struct fw_start_context fw_start;
static int fw_start_glink_check(void *ctx){++checks;return ctx!=&fw_start || issue==1 || (fail_check&&checks>=fail_check) ? EPERM : 0;}
static int fw_start_snoc_check(void *ctx){return ctx!=&fw_start || issue==2 ? EPERM : 0;}
static int fw_start_mission_check(void *ctx){return ctx!=&fw_start || issue==14 ? EPERM : 0;}
static int redfin_wifi_power_audit(void){return issue==15 ? EPERM : 0;}
static uint64_t fw_start_ns(void *ctx){(void)ctx;return clock_ns;}
static void IOLog(const char *format,...){(void)format;}
static uint32_t model_ldr(uintptr_t address){
 ++reads;uintptr_t start=(uintptr_t)registers;
 if(!mapped || address<start || address>=start+sizeof(registers) || !rf_ce_read_allowed((uint32_t)(address-start))){violations++;return 0xffffffff;}
 uint32_t value=registers[(address-start)/4];
 if(change_at&&reads==change_at)value^=1;
 return fail_read&&reads>=fail_read ? 0xffffffff : value;
}
'''
API = r'''
extern "C" {
void reset(unsigned value){
 issue=value;checks=reads=maps=violations=fail_check=fail_read=change_at=0;clock_ns=200;mapped=false;
 memset(&fw_start,0,sizeof(fw_start));memset(registers,0,sizeof(registers));
 fw_start.mission_mode=issue!=3;fw_start.mission.stage=issue==5 ? RF_MISSION_MODE : RF_MISSION_COMPLETE;
 fw_start.mission.poisoned=issue==4;fw_start.mission.waiting=issue==6;fw_start.mission.responses=issue==7 ? 1 : 2;
 fw_start.mission_settle_ns=issue==8 ? 0 : 100;if(issue==9)clock_ns=99;
}
int run(void){return fw_start_ce_observe(&fw_start);}
void failure(unsigned which,unsigned at){if(which==0)fail_check=at;else if(which==1)fail_read=at;else change_at=at;}
uint32_t metric(unsigned which){
 uint32_t values[]={checks,reads,maps,violations,fw_start.ce.stage,fw_start.ce.stable,fw_start.ce.reads,
 fw_start.ce.error,fw_start.ce.changed_offset};return which<9 ? values[which] : 0;
}
int allowed(unsigned at){return rf_ce_read_allowed(at);}
}
'''


class CeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('c++'): raise unittest.SkipTest('host C++ compiler unavailable')
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        adapter = (HERE / 'wifi_mission.inc').read_text().split('static int fw_start_ce_check', 1)[1]
        adapter = 'static int fw_start_ce_check' + adapter
        adapter, count = re.subn(r'__asm__ volatile\("ldr %w0,.*?: "memory"\);',
                                'value = model_ldr(address);', adapter, flags=re.S)
        assert count == 1
        (directory / 'ce.cpp').write_text(HARNESS + adapter + API)
        result = subprocess.run(['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), str(directory / 'ce.cpp'), '-o', str(directory / 'ce.so')], capture_output=True, text=True)
        if result.returncode: raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(directory / 'ce.so')); cls.lib.metric.restype = C.c_uint32

    def setUp(self): self.lib.reset(0)

    def test_native_adapter_reads_exactly_two_complete_samples_with_readonly_device_mapping(self):
        self.assertEqual(self.lib.run(), 0)
        self.assertEqual([self.lib.metric(i) for i in (1, 2, 3, 4, 5, 6)], [414, 1, 0, 3, 1, 414])
        self.assertNotEqual(self.lib.run(), 0); self.assertEqual(self.lib.metric(1), 414)

    def test_missing_owner_readiness_mission_ack_or_settle_deadline_never_maps_or_reads_ce(self):
        for issue in (*range(1, 10), 14, 15):
            self.lib.reset(issue); self.assertNotEqual(self.lib.run(), 0)
            self.assertEqual([self.lib.metric(i) for i in (1, 2, 3)], [0, 0, 0])

    def test_failed_partial_or_wrong_mapping_never_reads_a_register(self):
        for issue in range(10, 14):
            self.lib.reset(issue); self.assertNotEqual(self.lib.run(), 0)
            self.assertEqual(self.lib.metric(1), 0); self.assertEqual(self.lib.metric(3), 0)

    def test_every_native_owner_check_including_after_observation_stops_later_io(self):
        self.lib.run(); checks = self.lib.metric(0)
        for at in range(1, checks + 1):
            self.lib.reset(0); self.lib.failure(0, at)
            self.assertNotEqual(self.lib.run(), 0)
            self.assertLessEqual(self.lib.metric(0), at)
            self.assertEqual(self.lib.metric(3), 0)

    def test_inaccessible_or_changed_register_stops_before_following_read(self):
        for which, start, error in ((1, 1, errno.EIO), (2, 208, errno.EAGAIN)):
            for at in range(start, 415):
                self.lib.reset(0); self.lib.failure(which, at)
                self.assertEqual(self.lib.run(), error)
                self.assertEqual(self.lib.metric(1), at); self.assertEqual(self.lib.metric(5), 0)

    def test_allowlist_only_reaches_reviewed_ce_and_wrapper_registers(self):
        offsets = (0, 4, 8, 0x0c, 0x10, 0x14, 0x18, 0x2c, 0x30, 0x34, 0x38, 0x3c, 0x40, 0x44, 0x48, 0x4c, 0x50)
        allowed = {0x1000*i + at for i in range(12) for at in offsets} | {0xc000, 0xc004, 0xc008}
        for at in range(0x10000): self.assertEqual(bool(self.lib.allowed(at)), at in allowed)
        self.assertEqual(self.lib.allowed(0xffffffff), 0)

    def test_native_producer_keeps_mission_opt_in_and_binds_ath10k_not_ath11k_geometry(self):
        source = snoc_nodes(); root = mkadt.build(0x180000000, 0x80000000)
        P.add_wlfw_contract(root, source); P.add_wlan_observer_contract(root, source, power=True, bdf=True)
        P.add_snoc_observer_contract(root, source, mission=True)
        node = next(n for n in root.children if n.name == 'redfin-wifi-snoc')
        self.assertEqual(node.prop('mission-enable'), struct.pack('<I', 1))
        self.assertEqual(struct.unpack('<10I', node.prop('mission-contract')), (1, 0x23, 0x22, 6, 12, 21, 12, 0, 0x240000, 0x1000))
        with self.assertRaises(ValueError): P.add_snoc_observer_contract(root, source, mission=1)


if __name__ == '__main__': unittest.main()
