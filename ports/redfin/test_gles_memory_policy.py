from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class GLESMemoryPolicyTests(unittest.TestCase):
    def test_only_GLES_backboardd_selects_GPU_sysmem_and_auto_is_reversible(self):
        source=r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include "gles-memory-policy.h"
int main(void){
 const char *programs[]={NULL,"backboardd","SpringBoard","Photos","Phone","metal-check","backboardd-helper"};
 const char *apis[]={NULL,"gles","metal","","software"};
 const char *settings[]={NULL,"sysmem","auto","","gmem","llvmpipe"};
 for(unsigned p=0;p<7;++p)for(unsigned a=0;a<5;++a)for(unsigned s=0;s<6;++s){
  const char *choice=redfin_gles_memory_debug(programs[p],apis[a],settings[s]);
  assert(choice);
  bool active=p==1&&a==1&&(s==0||s==1);
  assert(!strcmp(choice,active?"sysmem":""));
 }
 return 0;
}
'''.replace('#include <assert.h>','#include <assert.h>\n#include <stdbool.h>')
        with tempfile.TemporaryDirectory(prefix='redfin-gles-memory-') as directory:
            path=Path(directory)/'policy.c';path.write_text(source);exe=path.with_suffix('')
            built=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
