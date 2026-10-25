"""Keep capture-only completed-presentation counts distinct from timer ticks."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin.gui_profile import REQUIRED


class Statistics(C.Structure):
    _fields_=[('version',C.c_uint32),('bytes',C.c_uint32),('ticks',C.c_uint64),
              ('presents',C.c_uint64),('gpu_presents',C.c_uint64),('panel_hz',C.c_uint32),('reserved',C.c_uint32)]


class DisplayStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        p=Path(cls.temp.name);board=Path(__file__).resolve().parent
        (p/'stats.c').write_text('''
#include "gui-profile.h"
#include "display-statistics.h"
int admit(const char *args,unsigned bytes,uint64_t nonce){return redfin_display_statistics_admit(args,bytes,nonce);}
int valid(const struct redfin_display_statistics *value){return redfin_display_statistics_valid(value);}
''')
        subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-I',str(board),str(p/'stats.c'),'-o',str(p/'stats.so')],capture_output=True,check=True)
        cls.lib=C.CDLL(str(p/'stats.so'));cls.lib.admit.argtypes=[C.c_char_p,C.c_uint,C.c_uint64]
        cls.lib.valid.argtypes=[C.POINTER(Statistics)]

    def arguments(self,mode=3,capture=True):
        value=' '.join(sorted(REQUIRED)).replace('redfingui=1','redfingui='+str(mode))
        value+=' redfinfit=1 redfinbootid=0x020afecf22835a8c'
        if capture:value+=' redfinscreen=1'
        return value.encode()

    def test_capture_requires_the_exact_gui_generation_and_does_not_admit_normal_boots(self):
        nonce=0x020afecf22835a8c;args=self.arguments()
        self.assertEqual(self.lib.admit(args,len(args)+1,nonce),1)
        for wrong in (0,nonce+1):self.assertEqual(self.lib.admit(args,len(args)+1,wrong),0)
        for wrong in (self.arguments(1),self.arguments(2),self.arguments(capture=False),
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


if __name__=='__main__':unittest.main()
