"""The actual native-exec predicate admits only Apple's backboardd in GUI3."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.gui_profile import REQUIRED


class GraphicsExecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('host C compiler absent')
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name);board=Path(__file__).resolve().parent
        source=(board/'graphics-exec.inc').read_text().split('/* REDFIN_GRAPHICS_EXEC_TEST_BEGIN */',1)[1].split('/* REDFIN_GRAPHICS_EXEC_TEST_END */',1)[0]
        (root/'exec.c').write_text('#include <string.h>\n#include "gui-profile.h"\n'+source+
            '\nint selected(const char *a,unsigned n,const char *p,const char *b,unsigned z){return redfin_graphics_exec_selected(a,n,p,b,z);}\n')
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-I',board,
            root/'exec.c','-o',root/'exec.so'],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(root/'exec.so'));cls.lib.selected.argtypes=[ctypes.c_char_p,ctypes.c_uint,
            ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]

    def arguments(self,mode):
        return (' '.join(sorted(REQUIRED)).replace('redfingui=1',f'redfingui={mode}')+
                ' redfinbootid=0x77162b76f74d3dc4').encode()

    def test_complete_gui3_and_both_absolute_path_and_leaf_are_required(self):
        args=self.arguments(3)
        self.assertEqual(self.lib.selected(args,len(args)+1,b'/usr/libexec/backboardd',b'backboardd',10),1)
        for mode in (1,2):
            a=self.arguments(mode);self.assertEqual(self.lib.selected(a,len(a)+1,b'/usr/libexec/backboardd',b'backboardd',10),0)
        for path,name,n in ((b'/tmp/backboardd',b'backboardd',10),
            (b'/usr/libexec/backboardd',b'backboardd-other',16),(b'/usr/libexec/xpcproxy',b'xpcproxy',8),
            (b'/usr/libexec/backboardd',None,10),(None,b'backboardd',10)):
            self.assertEqual(self.lib.selected(args,len(args)+1,path,name,n),0)
        self.assertEqual(self.lib.selected(args,len(args),b'/usr/libexec/backboardd',b'backboardd',10),0)


if __name__=='__main__':unittest.main()
