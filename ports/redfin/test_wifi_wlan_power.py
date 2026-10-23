"""Exercise the actual typed WLAN RSC writer and its live-child lease.

The established base BCM ledger is modeled; actual ARC tables, VRM tables,
RSC ownership/command bytes, IOKit mappings, parent-held checks and per-store
failure/cancellation paths are executed from wifi_native_probe.cpp.
"""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_rpmh_probe import added_file
from test_wifi_power import harness, database as arc_database, ARGS

HERE = Path(__file__).resolve().parent
ADDRESSES = (0x40800, 0x42100, 0x41d00, 0x41a00, 0x41900)
NAMES = ('ldoa1', 'ldoa14', 'ldoc2', 'ldoc11', 'ldoc10')


def database():
    data = arc_database()
    struct.pack_into('<5H', data, 24, 4, 0x400, 0x800, 5, 0x100)
    for i, (name, address) in enumerate(zip(NAMES, ADDRESSES)):
        at = 144 + 0x400 + 24 * i
        data[at:at + 8] = name.encode().ljust(8, b'\0')
        struct.pack_into('<IIIHH', data, at + 8, 0, 0, address, 4, 4 * i)
    return data


PROPERTIES = r'''
    if(entry==5) {
        static const uint32_t source[11]={1,4,2,435,428,3,1,125,129,512,6};
        static const uint64_t rates[4]={393600000,3936000000,0,8171520000};
        static const uint64_t reg[8]={0x80900000,0x200000,0x1f40000,0x20000,0x408000,0x1000,0x8c000000,0x11800000};
        static const char names[]="CE0\0SN6\0SN0\0SH0\0MC0\0ACV";
        if(!strcmp(key,"source-contract")){*out=source;*bytes=sizeof(source);return 0;}
        if(!strcmp(key,"bandwidth")){*out=rates;*bytes=sizeof(rates);return 0;}
        if(!strcmp(key,"reg")){*out=reg;*bytes=sizeof(reg);return 0;}
        if(!strcmp(key,"bcm-names")){*out=names;*bytes=sizeof(names);return 0;}
    }
    if(entry==6) {
        static uint32_t source[10]={2,5,4,4,0,352,1800,1304,3000,3000};
        static uint32_t observe;
        source[0]=wlan_binding==2 ? 3 : 2;observe=wlan_binding==3 ? 1 : 0;
        if(!strcmp(key,"source-contract")){*out=source;*bytes=sizeof(source);return 0;}
        if(!strcmp(key,"resource-names")){*out=rf_wlan_supply_names;*bytes=sizeof(rf_wlan_supply_names);return 0;}
        if(!strcmp(key,"resource-addresses")){*out=rf_wlan_supply_addresses;*bytes=sizeof(rf_wlan_supply_addresses);return 0;}
        if(!strcmp(key,"observe-only")){*out=&observe;*bytes=4;return 0;}
    }
'''


API = r'''
static int wlan_child(void *p){
    ++child_checks;
    if(p!=&child_alive||!child_alive||(child_fail_after&&child_checks>=child_fail_after))return -99;
    return redfin_wifi_power_held();
}
extern "C" int wlan_prepare(void){
    wlan_binding=child_alive=1;child_checks=child_fail_after=0;
    int error=wf_power_acquire(false);if(error)return error;
    /* Base BCM acquisition was tested separately; keep its proven ledger
     * while this harness exercises the later VRM transactions. */
    wf_power.firmware=true;wf_power.bandwidth_held=63;
    write_count=unsafe=0;memset(trace,0,sizeof(trace));return redfin_wifi_power_held();
}
extern "C" int wlan_start(unsigned present,uint32_t chain){return redfin_wifi_wlan_power_start(present,chain,&child_alive,wlan_child);}
extern "C" void wlan_option(unsigned which,unsigned value){
    if(which==0)wlan_binding=value;if(which==1)child_alive=value;if(which==2)child_fail_after=value;
}
extern "C" unsigned wlan_metric(unsigned which){
    unsigned values[]={wf_power.wlan_held,wf_power.wlan_powered,wf_power.wlan_busy,wf_power.wlan_attempted,
        child_checks,wf_power.active,wf_power.wlan_resources_valid};return which<7 ? values[which] : 0;
}
extern "C" int wlan_sealed_store(void){return wf_power_store(&wf_power,WFP_RSC,0xd30,0x10108);}
'''


class WlanPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('host C++ compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'redfin_rpmh.h').write_text(added_file('redfin_rpmh.h'))
        source = harness()
        source = source.replace('#define ARM64_BOARD_CONFIG_SWEET 1',
            'static unsigned wlan_binding=1,child_alive=1,child_checks,child_fail_after;\n#define ARM64_BOARD_CONFIG_SWEET 1')
        needle = 'if(!strcmp(path,"/redfin-wifi-power") && !bad_power_node){*out=4;return 0;}'
        assert source.count(needle) == 1
        source = source.replace(needle, needle + '\n'
            '    if(!strcmp(path,"/redfin-wifi-start")){*out=5;return 0;}\n'
            '    if(!strcmp(path,"/redfin-wifi-wlan") && wlan_binding){*out=6;return 0;}')
        needle = '    if(entry==4) {'
        assert source.count(needle) == 1
        source = source.replace(needle, PROPERTIES + needle)
        needle = 'if(mutation_kind==7)model_put(rsc,0xd30,0x10109);'
        assert source.count(needle) == 1
        source = source.replace(needle, needle + '\n'
            '        if(mutation_kind==8)model_put(db,144+0x400+16,0x40900);')
        actual = '\n'.join(line for line in (HERE / 'wifi_native_probe.cpp').read_text().splitlines()
                           if not line.startswith('#include'))
        needle = 'if (context->firmware) for (unsigned i = 0; i < RF_WIFI_BW_COUNT; ++i) {'
        assert actual.count(needle) == 2
        # Only the established BCM table is modeled. ARC/VRM immutable table
        # checks and the complete physical writer remain actual source.
        actual = actual.replace(needle, 'if (false && context->firmware) for (unsigned i = 0; i < RF_WIFI_BW_COUNT; ++i) {', 1)
        needle = '*(volatile uint32_t *)(context->base[unit] + offset) = value;'
        assert actual.count(needle) == 1
        actual = actual.replace(needle, 'wf_harness_write(context->base[unit], unit, offset, value);')
        (directory / 'test.cpp').write_text(source.replace('ACTUAL', actual) + API)
        library = directory / 'test.so'
        result = subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
            '-I', str(HERE), '-I', str(directory), '-x', 'c++', str(directory / 'test.cpp'),
            str(HERE / 'wifi_aop.c'), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = C.CDLL(str(library)); cls.lib.power_args.argtypes = [C.c_char_p]
        cls.lib.power_region.restype = C.c_void_p

    def setUp(self):
        self.lib.power_reset(); self.lib.power_args(ARGS.encode())
        aop = bytearray(0x1000)
        struct.pack_into('<16I', aop, 0, 0x4d41494c, 1, 0, 0xffff, 0xffff0000,
                         0xffff0000, 0xffff0000, 104, 0xc0, 0xffff0000, 0xffff0000,
                         0xffff0000, 0xffff0000, 728, 0x128, 0)
        C.memmove(self.lib.power_region(0), bytes(aop), len(aop))
        C.memmove(self.lib.power_region(5), bytes(database()), 0x20000)
        # An enabled foreign SLEEP command is part of the inherited lease.
        # Disabled command storage has no active ownership to compare.
        for offset, value in ((0x1c, 1), (0x30, 0x10108), (0x34, 0x65000), (0x38, 0x55)):
            C.memmove(self.lib.power_region(2) + 0xd00 + 2 * 0x2a0 + offset, struct.pack('<I', value), 4)
        self.assertEqual(self.lib.wlan_prepare(), 0)

    def writes(self):
        return [tuple(self.lib.power_trace(i, field) for field in range(3)) for i in range(self.lib.power_metric(0))]

    def test_all_fifteen_typed_votes_use_only_owned_active_slot_and_reseal_parent(self):
        before_aop = C.string_at(self.lib.power_region(0), 0x1000)
        before_other = C.string_at(self.lib.power_region(2) + 0xfa0, 0x10000 - 0xfa0)
        self.assertEqual(self.lib.wlan_start(0, 0), 0)
        self.assertEqual([self.lib.wlan_metric(i) for i in (0, 1, 2, 3, 5)], [0x7fff, 1, 0, 1, 1])
        self.assertEqual(self.lib.power_metric(0), 195)
        self.assertEqual(self.lib.power_metric(6), 0)
        writes = self.writes()
        self.assertTrue(all(unit == 2 for unit, _, _ in writes))
        expected = [(0x40800, 352), (0x40808, 4), (0x40804, 1), (0x42100, 1800), (0x42108, 4), (0x42104, 1),
                    (0x41d00, 1304), (0x41d08, 4), (0x41d04, 1), (0x41a00, 3000), (0x41a08, 4), (0x41a04, 1),
                    (0x41900, 3000), (0x41908, 4), (0x41904, 1)]
        self.assertEqual([(writes[13 * i + 1][2], writes[13 * i + 2][2]) for i in range(15)], expected)
        self.assertEqual(C.string_at(self.lib.power_region(0), 0x1000), before_aop)
        self.assertEqual(C.string_at(self.lib.power_region(2) + 0xfa0, 0x10000 - 0xfa0), before_other)
        self.assertNotEqual(self.lib.wlan_sealed_store(), 0); self.assertEqual(self.lib.power_metric(0), 195)
        self.assertNotEqual(self.lib.wlan_start(0, 0), 0); self.assertEqual(self.lib.power_metric(0), 195)

    def test_one_chain_profile_omits_all_chain1_votes_and_keeps_global_parent_votes(self):
        self.assertEqual(self.lib.wlan_start(1, 1), 0)
        self.assertEqual(self.lib.power_metric(0), 156)
        self.assertEqual(self.lib.wlan_metric(0), 0xfff)
        self.assertEqual(self.lib.power_metric(1), 7)
        self.assertFalse(any(offset == 0xd34 and value in (0x41a00, 0x41a04, 0x41a08) for _, offset, value in self.writes()))

    def test_every_uncertain_mmio_store_and_owner_loss_stops_without_cleanup_writes(self):
        for mode in (7, 8):  # Failed readback, then loss of the return/owner proof.
            for position in range(1, 196):
                with self.subTest(mode=mode, position=position):
                    self.setUp(); self.lib.power_option(mode, position)
                    self.assertNotEqual(self.lib.wlan_start(0, 0), 0)
                    self.assertEqual(self.lib.power_metric(0), position)
                    self.assertEqual(self.lib.power_metric(2), 1)
                    self.assertEqual(self.lib.wlan_metric(1), 0)
                    self.assertEqual(self.lib.wlan_metric(5), 1)  # Mappings retained for reset.

    def test_foreign_binding_missing_child_and_unknown_chain_refuse_before_writes(self):
        for binding in (0, 2, 3):
            self.setUp(); self.lib.wlan_option(0, binding)
            self.assertNotEqual(self.lib.wlan_start(0, 0), 0); self.assertEqual(self.lib.power_metric(0), 0)
        self.setUp(); self.lib.wlan_option(1, 0)
        self.assertNotEqual(self.lib.wlan_start(0, 0), 0); self.assertEqual(self.lib.power_metric(0), 0)
        self.setUp(); self.assertNotEqual(self.lib.wlan_start(1, 3), 0); self.assertEqual(self.lib.power_metric(0), 0)

    def test_child_epoch_loss_cancels_only_typed_progress_and_preserves_base_vote_ledger(self):
        self.lib.wlan_option(2, 30)
        self.assertNotEqual(self.lib.wlan_start(0, 0), 0)
        self.assertGreater(self.lib.power_metric(0), 0); self.assertLess(self.lib.power_metric(0), 195)
        self.assertEqual(self.lib.wlan_metric(1), 0); self.assertEqual(self.lib.power_metric(1), 7)

    def test_changed_immutable_vrm_metadata_or_foreign_controller_state_stops_progress(self):
        for kind in range(1, 9):
            for position in (1, 14, 195):
                with self.subTest(kind=kind, position=position):
                    self.setUp(); self.lib.power_option(9, position); self.lib.power_option(10, kind)
                    self.assertNotEqual(self.lib.wlan_start(0, 0), 0)
                    self.assertEqual(self.lib.power_metric(0), position)
                    self.assertEqual(self.lib.wlan_metric(1), 0)

    def test_missing_or_incomplete_hardware_ack_times_out_without_cleanup_stores(self):
        for issue in (1, 2, 3):
            self.setUp(); self.lib.power_option(6, issue)
            self.assertNotEqual(self.lib.wlan_start(0, 0), 0)
            self.assertEqual(self.lib.power_metric(0), 8)
            self.assertEqual(self.lib.wlan_metric(0), 0); self.assertEqual(self.lib.wlan_metric(1), 0)


if __name__ == '__main__':
    unittest.main()
