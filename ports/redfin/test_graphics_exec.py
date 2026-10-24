"""The actual native-exec predicate admits only Apple's backboardd in GUI3."""
import ctypes
from pathlib import Path
import shutil
import re
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
        path=b'executable_path=/usr/libexec/backboardd'
        self.assertEqual(self.lib.selected(args,len(args)+1,path,b'backboardd',10),1)
        for mode in (1,2):
            a=self.arguments(mode);self.assertEqual(self.lib.selected(a,len(a)+1,path,b'backboardd',10),0)
        for saved,name,n in ((b'executable_path=/tmp/backboardd',b'backboardd',10),
            (path,b'backboardd-other',16),(b'executable_path=/usr/libexec/xpcproxy',b'xpcproxy',8),
            (path,None,10),(None,b'backboardd',10),(b'/usr/libexec/backboardd',b'backboardd',10),
            (b'executable_path=usr/libexec/backboardd',b'backboardd',10)):
            self.assertEqual(self.lib.selected(args,len(args)+1,saved,name,n),0)
        self.assertEqual(self.lib.selected(args,len(args),path,b'backboardd',10),0)

    def test_actual_native_exec_save_path_layout_reaches_the_injection_predicate(self):
        board=Path(__file__).resolve().parent
        native=board.parents[1]/'research/redfin-build/dxb/xnu/bsd/kern/kern_exec.c'
        if not native.is_file():self.skipTest('prepared actual XNU exec source required')
        text=native.read_text()
        key=re.search(r'^#define EXECUTABLE_KEY .+$',text,re.M).group()
        function='static int\nexec_save_path'+text.split('static int\nexec_save_path',1)[1].split('\n}\n',1)[0]+'\n}\n'
        predicate=(board/'graphics-exec.inc').read_text().split('/* REDFIN_GRAPHICS_EXEC_TEST_BEGIN */',1)[1].split('/* REDFIN_GRAPHICS_EXEC_TEST_END */',1)[0]
        harness=r'''
#include <string.h>
#include <errno.h>
#include "gui-profile.h"
#define MAXPATHLEN 1024
#define MIN(a,b) ((a)<(b)?(a):(b))
#define UIO_USERSPACE32 1
#define UIO_USERSPACE64 2
#define UIO_SYSSPACE 3
#define CAST_DOWN(type,value) ((type)(uintptr_t)(value))
#ifndef __APPLE__
typedef uintptr_t user_addr_t;
#endif
struct image_params {char *ip_strings,*ip_strendp;size_t ip_strspace;};
static int copystr(const char *from,char *to,size_t limit,size_t *length){
    size_t n=strlen(from)+1;if(n>limit)return E2BIG;memcpy(to,from,n);*length=n;return 0;
}
static int copyinstr(user_addr_t from,char *to,size_t limit,size_t *length){
    return copystr((const char *)from,to,limit,length);
}
'''+key+'\n'+function+predicate+r'''
int saved_selected(const char *args,const char *path,const char *leaf){
    char storage[4096]={0};struct image_params image={storage,storage,sizeof(storage)};
    if(exec_save_path(&image,(user_addr_t)path,UIO_SYSSPACE,NULL))return -1;
    return redfin_graphics_exec_selected(args,(unsigned)strlen(args)+1,image.ip_strings,leaf,(unsigned)strlen(leaf));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);(directory/'save.c').write_text(harness)
            result=subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-I',board,
                directory/'save.c','-o',directory/'save.so'],capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr)
            lib=ctypes.CDLL(str(directory/'save.so'));lib.saved_selected.argtypes=[ctypes.c_char_p]*3
            self.assertEqual(lib.saved_selected(self.arguments(3),b'/usr/libexec/backboardd',b'backboardd'),1)
            self.assertEqual(lib.saved_selected(self.arguments(2),b'/usr/libexec/backboardd',b'backboardd'),0)
            self.assertEqual(lib.saved_selected(self.arguments(3),b'/tmp/backboardd',b'backboardd'),0)


if __name__=='__main__':unittest.main()
