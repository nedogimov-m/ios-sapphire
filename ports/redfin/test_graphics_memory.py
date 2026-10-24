"""Exercise the native graphics memory adapter's task/scope/error boundaries."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.gui_profile import REQUIRED


class GraphicsMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('host C compiler absent')
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        board=Path(__file__).resolve().parent;root=Path(cls.temp.name)
        adapter=(board/'graphics-memory.inc').read_text().replace(
            '#include <arm64/redfin_gui_profile.h>','#include "gui-profile.h"')
        source=r'''
#include <string.h>
#include <errno.h>
#include <stdarg.h>
typedef void *task_t;
struct proc {const char *p_comm;int p_memstat_memlimit_active,p_memstat_memlimit_inactive;};
typedef struct proc *proc_t;
typedef struct {int memlimit_active;unsigned memlimit_active_attr;int memlimit_inactive;unsigned memlimit_inactive_attr;} memorystatus_memlimit_properties_t;
#define MEMORYSTATUS_MEMLIMIT_ATTR_FATAL 1
static struct proc process;
static const char *arguments;
static int calls,set_error,query_error,apply_limit,ledger_limit,locked;
static task_t current_task(void){return (void *)1;}
static proc_t current_proc(void){return &process;}
static const char *PE_boot_args(void){return arguments;}
static int proc_getpid(proc_t p){return p==&process?42:0;}
static void proc_list_lock(void){locked++;}
static void proc_list_unlock(void){locked--;}
static int task_get_phys_footprint_limit(task_t task,int *limit){
    if(task!=current_task())return EINVAL;
    if(query_error && calls)return EIO;
    *limit=ledger_limit;return 0;
}
static int memorystatus_set_memlimit_properties(int pid,memorystatus_memlimit_properties_t *entry){
    calls++;
    if(locked || pid!=42 || entry->memlimit_active!=512 || entry->memlimit_inactive!=512 ||
       entry->memlimit_active_attr!=1 || entry->memlimit_inactive_attr!=1)return EFAULT;
    if(set_error)return set_error;
    process.p_memstat_memlimit_active=entry->memlimit_active;
    process.p_memstat_memlimit_inactive=entry->memlimit_inactive;
    if(apply_limit)ledger_limit=entry->memlimit_active;
    return 0;
}
static int discard_log(const char *format,...){(void)format;return 0;}
#define printf discard_log
'''+adapter+r'''
int invoke(const char *args,const char *name,int owner,int failure,int apply,int query){
    process=(struct proc){name,50,50};arguments=args;calls=0;locked=0;
    set_error=failure;apply_limit=apply;query_error=query;ledger_limit=50;
    int result=redfin_graphics_memory_admit((task_t)(uintptr_t)owner);
    return locked?EDEADLK:result;
}
int setter_calls(void){return calls;}
int effective_limit(void){return ledger_limit;}
'''
        (root/'memory.c').write_text(source)
        result=subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-I',board,root/'memory.c','-o',root/'memory.so'],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        cls.lib=ctypes.CDLL(str(root/'memory.so'))
        cls.lib.invoke.argtypes=[ctypes.c_char_p,ctypes.c_char_p]+[ctypes.c_int]*4

    def arguments(self,mode=3):
        return (' '.join(sorted(REQUIRED)).replace('redfingui=1',f'redfingui={mode}')+
                ' redfinbootid=0x77162b76f74d3dc4').encode()

    def call(self,args,name=b'gpu-render',owner=1,failure=0,apply=1,query=0):
        result=self.lib.invoke(args,name,owner,failure,apply,query)
        return result,self.lib.setter_calls(),self.lib.effective_limit()

    def test_other_processes_or_profiles_cannot_change_native_memory_limits(self):
        for mode in (1,2):self.assertEqual(self.call(self.arguments(mode)),(0,0,50))
        for name in (b'SpringBoard',b'gpu-render-other',b'xpcproxy',b'backboardd-other'):
            self.assertEqual(self.call(self.arguments(),name),(0,0,50))
        self.assertEqual(self.call(self.arguments()+b' gpu=1'),(0,0,50))
        self.assertEqual(self.call(self.arguments(),owner=2),(1,0,50))
        self.assertEqual(self.call(self.arguments(),owner=0),(1,0,50))

    def test_selected_tasks_need_the_real_effective_limit_and_errors_propagate(self):
        for name in (b'gpu-render',b'backboardd'):
            self.assertEqual(self.call(self.arguments(),name),(0,1,512))
        self.assertEqual(self.call(self.arguments(),failure=12),(12,1,50))
        self.assertEqual(self.call(self.arguments(),apply=0),(22,1,50))
        self.assertEqual(self.call(self.arguments(),query=1),(22,1,512))
        self.assertEqual(self.call(None),(22,0,50))
        self.assertEqual(self.call(b'x'*608),(22,0,50))


if __name__=='__main__':unittest.main()
