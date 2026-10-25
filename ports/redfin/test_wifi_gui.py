"""Run the real frozen GUI/WLAN lease, including loss and shutdown fencing."""
import ctypes as C
from pathlib import Path
import re
import tempfile
import unittest

import gui_profile
from test_smp_gui import compile_shared, patched_source

HERE = Path(__file__).resolve().parent
ARGS = (' '.join(sorted(gui_profile.REQUIRED)) + ' redfinbootid=0x0123456789abcdef').replace(
    'redfingui=1', 'redfingui=2')


class WiFiGUILeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source = re.sub(r'^#include.*\n', '', (HERE / 'wifi_gui.c').read_text(), flags=re.M)
        stub = r'''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "gui-profile.h"
static char args[608], alternative[608];
static const char *live=args;
static unsigned profiles,full_checks,held_checks,starts,binds,restores,bad_start;
static int cpu0,full,held,rail,up,bind_ok;
static const char *PE_boot_args(void){return live;}
int redfin_gui_cpu0(void){return cpu0;}
void *redfin_gui_worker_enter(void){unsigned before=cpu0;++binds;if(bind_ok)cpu0=1;return (void *)(uintptr_t)(before+1);}
void redfin_gui_worker_leave(void *previous){++restores;cpu0=(int)(uintptr_t)previous-1;}
int redfin_spmi_return_ready(void){return up;}
bool redfin_touch_boot_lease_valid(unsigned mode){full_checks++;return mode==2 && full;}
bool redfin_touch_boot_lease_held(unsigned mode){held_checks++;return mode==2 && held;}
int redfin_touch_rail_ready(void){return rail;}
void redfin_wifi_fw_start(void){starts++;if(!cpu0)++bad_start;}
static bool counted_profile(const char *a,unsigned n,uint64_t *epoch){
 profiles++;return redfin_wifi_gui_profile(a,n,epoch);
}
#define redfin_wifi_gui_profile counted_profile
#define printf(...) ((void)0)
'''
        wrapper = r'''
void reset(const char *command){
 memset(args,0,sizeof(args));strncpy(args,command,sizeof(args)-1);
 memcpy(alternative,args,sizeof(args));live=args;
 profiles=full_checks=held_checks=starts=binds=restores=bad_start=0;cpu0=full=held=rail=bind_ok=1;up=0;
 wifi_gui_handoff=wifi_gui_bytes=0;wifi_gui_arguments=0;wifi_gui_epoch=0;
}
void fault(unsigned which){
 if(which==1)cpu0=0; if(which==2)held=0; if(which==3)full=0;
 if(which==4)rail=0; if(which==5)live=alternative;
 if(which==6)args[0]^=1; if(which==7)up=1;
 if(which==8){bind_ok=0;cpu0=0;}
}
unsigned stat(unsigned which){const unsigned v[]={profiles,full_checks,held_checks,starts,wifi_gui_handoff,binds,restores,bad_start};return which<8?v[which]:0;}
int hot(unsigned count){for(unsigned i=0;i<count;i++)if(!redfin_wifi_gui_ready())return 0;return 1;}
'''
        cls.lib = compile_shared(Path(cls.tmp.name), stub + source + wrapper, 'wifi_gui')
        cls.lib.reset.argtypes = [C.c_char_p]
        cls.lib.redfin_wifi_gui_boot_id.argtypes = [C.POINTER(C.c_uint64)]
        for name in ('redfin_wifi_gui_requested', 'redfin_wifi_gui_ready', 'redfin_wifi_return_held',
                     'redfin_wifi_gui_boot_id'):
            getattr(cls.lib, name).restype = C.c_bool

    def setUp(self):
        self.lib.reset(ARGS.encode())

    def test_overlay_matches_and_complete_handoff_is_required(self):
        self.assertEqual(patched_source('bsd/dev/redfin_wifi_gui.c'), (HERE / 'wifi_gui.c').read_text())
        self.assertTrue(self.lib.redfin_wifi_gui_requested())
        self.assertFalse(self.lib.redfin_wifi_gui_ready())
        for issue in (8, 3, 4):
            self.lib.reset(ARGS.encode())
            self.lib.fault(issue)
            self.lib.redfin_wifi_gui_start()
            self.assertEqual(self.lib.stat(3), 0)
        self.lib.reset(ARGS.replace('redfingui=2', 'redfingui=1').encode())
        self.lib.redfin_wifi_gui_start()
        self.assertFalse(self.lib.redfin_wifi_gui_requested())
        self.assertEqual(self.lib.stat(3), 0)

    def test_launch_rebinds_after_migration_and_restores_caller_affinity(self):
        self.lib.fault(1)
        self.lib.redfin_wifi_gui_start()
        self.assertEqual((self.lib.stat(3),self.lib.stat(5),self.lib.stat(6),self.lib.stat(7)),(1,1,1,0))
        self.assertFalse(self.lib.redfin_wifi_gui_ready(),'restored non-CPU0 caller has no radio write lease')

    def test_every_early_refusal_restores_affinity_without_starting_a_radio_writer(self):
        for issue in (3,4,8):
            self.lib.reset(ARGS.encode());self.lib.fault(issue);self.lib.redfin_wifi_gui_start()
            self.assertEqual((self.lib.stat(3),self.lib.stat(5),self.lib.stat(6)),(0,1,1))

    def test_hot_path_retains_epoch_without_reparsing_profile_or_touch_setup(self):
        self.lib.redfin_wifi_gui_start()
        counts = self.lib.stat(0), self.lib.stat(1)
        self.assertEqual(self.lib.hot(10000), 1)
        self.assertEqual((self.lib.stat(0), self.lib.stat(1)), counts)
        epoch = C.c_uint64()
        self.assertTrue(self.lib.redfin_wifi_gui_boot_id(C.byref(epoch)))
        self.assertEqual(epoch.value, 0x0123456789abcdef)
        self.assertTrue(self.lib.redfin_wifi_return_held())
        self.assertEqual(self.lib.stat(3), 1)

    def test_cpu_owner_argument_pointer_and_each_frozen_byte_are_checked(self):
        for issue in (1, 2, 5, 6):
            self.lib.reset(ARGS.encode())
            self.lib.redfin_wifi_gui_start()
            self.lib.fault(issue)
            self.assertFalse(self.lib.redfin_wifi_gui_ready(), issue)
            self.assertFalse(self.lib.redfin_wifi_return_held(), issue)
            epoch = C.c_uint64(99)
            self.assertFalse(self.lib.redfin_wifi_gui_boot_id(C.byref(epoch)), issue)
            self.assertEqual(epoch.value, 99)

    def test_shutdown_and_changed_arguments_cannot_restart_same_epoch(self):
        for mutate in (False, True):
            self.lib.reset(ARGS.encode())
            self.lib.redfin_wifi_gui_start()
            if mutate:
                self.lib.fault(6)
                self.assertFalse(self.lib.redfin_wifi_gui_ready())
                self.lib.fault(6)
            else:
                self.lib.redfin_wifi_gui_stop()
            self.assertTrue(self.lib.redfin_wifi_gui_requested())
            self.assertFalse(self.lib.redfin_wifi_gui_ready())
            self.lib.redfin_wifi_gui_start()
            self.lib.redfin_wifi_gui_stop()
            self.assertEqual(self.lib.stat(3), 1)
            self.assertEqual(self.lib.stat(4), 2)


if __name__ == '__main__':
    unittest.main()
