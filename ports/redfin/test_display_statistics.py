"""Nonce-bound ordinary completed-presentation counts stay distinct from ticks."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin.gui_profile import REQUIRED


class Statistics(C.Structure):
    _fields_=[('version',C.c_uint32),('bytes',C.c_uint32),('ticks',C.c_uint64),
              ('presents',C.c_uint64),('gpu_presents',C.c_uint64),('panel_hz',C.c_uint32),('reserved',C.c_uint32)]


class PhysicalStatistics(C.Structure):
    _fields_=Statistics._fields_+[('counter_hz',C.c_uint64)]


class DisplayStatisticsTests(unittest.TestCase):
    def test_final_native_header_is_the_exact_owned_statistics_contract(self):
        from ports.redfin.test_usb_owned_route import added_file
        from ports.redfin.test_overlay_sources import sensor_overlay
        here=Path(__file__).resolve().parent;target='iokit/Kernel/arm/RedfinDisplayStatistics.h'
        before=added_file((here/'native-observability.patch').read_text(),target)
        self.assertEqual(sensor_overlay(before,target),(here/'display-statistics.h').read_text())

    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        p=Path(cls.temp.name);board=Path(__file__).resolve().parent
        (p/'stats.c').write_text('''
#include "gui-profile.h"
#include "display-statistics.h"
int admit(const char *args,unsigned bytes,uint64_t nonce){return redfin_display_statistics_admit(args,bytes,nonce);}
int valid(const struct redfin_display_statistics *value){return redfin_display_statistics_valid(value);}
int physical(const struct redfin_display_statistics_v2 *value){return redfin_display_statistics_valid_v2(value);}
''')
        subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-I',str(board),str(p/'stats.c'),'-o',str(p/'stats.so')],capture_output=True,check=True)
        cls.lib=C.CDLL(str(p/'stats.so'));cls.lib.admit.argtypes=[C.c_char_p,C.c_uint,C.c_uint64]
        cls.lib.valid.argtypes=[C.POINTER(Statistics)]
        cls.lib.physical.argtypes=[C.POINTER(PhysicalStatistics)]

    def arguments(self,mode=3,capture=True):
        value=' '.join(sorted(REQUIRED)).replace('redfingui=1','redfingui='+str(mode))
        value+=' redfinfit=1 redfinbootid=0x020afecf22835a8c'
        if capture:value+=' redfinscreen=1'
        return value.encode()

    def test_readonly_query_accepts_ordinary_gui3_but_requires_the_exact_generation(self):
        nonce=0x020afecf22835a8c;args=self.arguments()
        self.assertEqual(self.lib.admit(args,len(args)+1,nonce),1)
        ordinary=self.arguments(capture=False)
        self.assertEqual(self.lib.admit(ordinary,len(ordinary)+1,nonce),1)
        for wrong in (0,nonce+1):self.assertEqual(self.lib.admit(args,len(args)+1,wrong),0)
        for wrong in (self.arguments(1),self.arguments(2),
                      args+b' redfinscreen=1',args+b' gpu=1',b'x'*608):
            self.assertEqual(self.lib.admit(wrong,len(wrong)+1,nonce),0)
        self.assertEqual(self.lib.admit(args,len(args),nonce),0)
        self.assertEqual(self.lib.admit(None,0,nonce),0)

    def test_only_completed_presentations_and_verified_panel_modes_form_a_valid_snapshot(self):
        self.assertEqual(C.sizeof(Statistics),40)
        value=Statistics(1,40,5000,31,30,90,0)
        self.assertEqual(self.lib.valid(C.byref(value)),1)
        for field,bad in (('version',0),('bytes',39),('ticks',0),('gpu_presents',32),('panel_hz',89),('reserved',1)):
            old=getattr(value,field);setattr(value,field,bad)
            self.assertEqual(self.lib.valid(C.byref(value)),0);setattr(value,field,old)
        value.presents=value.gpu_presents=0;value.panel_hz=60
        self.assertEqual(self.lib.valid(C.byref(value)),1)
        self.assertEqual(self.lib.valid(None),0)

    def test_extended_snapshot_requires_actual_counter_frequency_and_keeps_v1_unchanged(self):
        self.assertEqual(C.sizeof(PhysicalStatistics),48)
        value=PhysicalStatistics(2,48,1234,60,59,90,0,19200000)
        self.assertEqual(self.lib.physical(C.byref(value)),1)
        for field,bad in (('version',1),('bytes',40),('ticks',0),('gpu_presents',61),
                          ('panel_hz',89),('reserved',1),('counter_hz',0),('counter_hz',1000000001)):
            old=getattr(value,field);setattr(value,field,bad)
            self.assertEqual(self.lib.physical(C.byref(value)),0);setattr(value,field,old)
        value.counter_hz=24000000;self.assertEqual(self.lib.physical(C.byref(value)),1)
        self.assertEqual(self.lib.physical(None),0)


if __name__=='__main__':unittest.main()
