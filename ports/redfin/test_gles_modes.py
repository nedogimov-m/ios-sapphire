"""The native checker starts exactly one bounded independent sysmem process."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class GLESModesTests(unittest.TestCase):
    def test_actual_spawn_preserves_unrelated_environment_and_handles_exit_interrupt_timeout(self):
        body=function((HERE/'gpu-render.c').read_text(),'static int sysmem_process(')
        source=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
static unsigned fault,spawns,polls,pauses,kills;
static char *items[]={"FD_MESA_DEBUG=gmem","OSMESA_SOFTWARE=0","HOME=/private/test",
 "MESA_DEBUG=context","EXACT_RETAINED=unchanged",NULL};
char **fixture_environ=items;
static int mock_spawn(pid_t *pid,const char *path,void *files,void *attributes,char *const args[],char *const environment[]){
 assert(!strcmp(path,"/redfin/bin/gpu-render")&&!files&&!attributes);
 assert(!strcmp(args[0],path)&&!strcmp(args[1],"--sysmem-child")&&!args[2]);
 unsigned gpu=0,software=0,home=0,retained=0,debug=0;
 for(unsigned i=0;environment[i];++i){
  if(!strncmp(environment[i],"FD_MESA_DEBUG=",14)){assert(!strcmp(environment[i],"FD_MESA_DEBUG=sysmem"));++gpu;}
  else if(!strncmp(environment[i],"OSMESA_SOFTWARE=",16)){assert(!strcmp(environment[i],"OSMESA_SOFTWARE=0"));++software;}
  else if(!strcmp(environment[i],"HOME=/private/test"))++home;
  else if(!strcmp(environment[i],"EXACT_RETAINED=unchanged"))++retained;
  else if(!strcmp(environment[i],"MESA_DEBUG=context"))++debug;
  else assert(0);
 }
 assert(gpu==1&&software==1&&home==1&&retained==1&&debug==1);
 ++spawns;*pid=23;return fault==1?EAGAIN:0;
}
static pid_t mock_wait(pid_t pid,int *status,int flags){
 assert(pid==23);++polls;
 if(!flags){assert(kills==1&&!status);return pid;}
 assert(flags==WNOHANG&&status);
 if(fault==4&&polls==1){errno=EINTR;return -1;}
 if(fault==5)return 0;
 if(fault==6){errno=ECHILD;return -1;}
 if(fault==2)*status=SIGKILL;
 else *status=fault==3?7<<8:0;
 return pid;
}
static int mock_sleep(unsigned usec){assert(usec==100000);++pauses;return 0;}
static int mock_kill(pid_t pid,int signal){assert(pid==23&&signal==SIGKILL);++kills;return 0;}
#define environ fixture_environ
#define posix_spawn mock_spawn
#define waitpid mock_wait
#define usleep mock_sleep
#define kill mock_kill
'''+body+r'''
int main(void){
 for(fault=0;fault<7;++fault){
  spawns=polls=pauses=kills=0;int result=sysmem_process();
  int wanted[]={0,53,54,7,0,56,55};assert(result==wanted[fault]&&spawns==1);
  assert(kills==(fault==5));assert(pauses==(fault==5?900u:fault==4?1u:0u));
  assert(!strcmp(items[0],"FD_MESA_DEBUG=gmem"));
 }
 char *many[4098];for(unsigned i=0;i<4098;++i)many[i]="EXACT_RETAINED=unchanged";
 fixture_environ=many;spawns=0;assert(sysmem_process()==51&&!spawns);
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='redfin-gles-modes-') as directory:
            path=Path(directory)/'modes.c';path.write_text(source);exe=path.with_suffix('')
            result=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(path),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
