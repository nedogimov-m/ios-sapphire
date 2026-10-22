"""Actual touch startup/lease C, with independent power and worker boundaries."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from ports.redfin import test_rpmh_touch as rpmh_model
from ports.redfin import test_touch_events_worker as worker_model
from ports.redfin.test_touch_events import function

HERE = Path(__file__).resolve().parent


def added(patch, name):
    section = (HERE / patch).read_text().split('+++ b/bsd/dev/' + name + '\n', 1)[1]
    section = section.split('diff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines() if line.startswith('+')) + '\n'


def without_includes(source):
    return re.sub(r'^#include.*\n', '', source, flags=re.M)


START_MODEL = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include "redfin_rpmh_touch.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
#define printf(...) ((void)0)
typedef uintptr_t DTEntry;
static unsigned bad,flow[16],flow_count,power_error,ready_value,setup_error,scan_error,event_error;
static unsigned platform_ok,return_ready,contract_fault,mutate_phase,consumer_checks;
static unsigned reenter_phase,reenter_result,scan_batches;
static bool identity,have_ops;
static struct redfin_touch_rail_ops saved_ops;
static const char *changed_key;
static char root_arg[16],ufsroot_arg[16];
static bool root_present,ufsroot_present;
struct test_arg {const char *name;uint32_t value;bool present;};
static struct test_arg args[]={
 {"cpus",1,true},{"redfintouch",2,true},{"redfintouchsetup",1,true},
 {"redfinrpmhtouch",1,true},{"redfinrail",1,true},{"redfinreturn",1,true},{"redfinspmi",1,true},
 {"sweettouch",0,true},{"sweetkeys",0,true},{"sweetusb",0,true},
 {"sweetcpufreq",0,true},{"sweetbattery",0,true},{"modem",0,true},{"wifi",0,true},{"gpu",0,true},
 {"sweethw",0,false},{"sweetusblog",0,false},{"sweetlog",0,false},
 {"redfinusb",0,false},{"redfinwifi",0,false},{"redfingpu",0,false},
 {"redfinroot",0,false},{"redfinufs",0,false},{"ufsrw",0,false},{"rootrw",0,false},
 {"redfintouchevents",0,false},{"redfintouchscan",0,false},{"redfinfb",0,false},
 {"redfinusbowned",0,false},{"redfinusbbypass",0,false},{"redfinusbcontexts",0,false},
 {"redfinusbgadget",0,false},
 {"redfinrpmh",0,false},{"redfinscreen",0,false},{"redfinusbnet",0,false},{"redfinusblog",0,false},
};
static void arg_set(const char *key,uint32_t value,int present){
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(args[i].name,key)){
  args[i].value=value;args[i].present=present;return;
 }
 bad++;
}
static bool PE_parse_boot_argn(const char *name,void *out,unsigned size){
 if(!strcmp(name,"rd") || !strcmp(name,"ufsroot")){
  bool present=!strcmp(name,"rd")?root_present:ufsroot_present;
  if(!present)return false;
  if(size!=16){bad++;return false;}
  memcpy(out,!strcmp(name,"rd")?root_arg:ufsroot_arg,16);return true;
 }
 if(size!=4){bad++;return false;}
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(name,args[i].name)){
  if(!args[i].present)return false;memcpy(out,&args[i].value,4);return true;
 }
 bad++;return false;
}
bool redfin_usb_platform(void){return platform_ok;}
int redfin_spmi_return_ready(void){return (int)return_ready;}
static int SecureDTLookupEntry(void *from,const char *name,DTEntry *entry){
 (void)from;if(contract_fault==1)return -1;
 if(!strcmp(name,"/arm-io/disp0")){*entry=1;return 0;}
 if(!strcmp(name,"/redfin-touch")){*entry=2;return 0;}
 bad++;return -1;
}
static int SecureDTGetProperty(DTEntry node,const char *key,const void **out,unsigned *size){
 static const uint64_t framebuffer[]={0xa0000000,0x2300000};
 static const uint32_t marker=1,width=1080,height=2340,stride=4320,cw=1125,ch=2436;
 static const uint32_t touch_size[]={1080,2340};
 const void *value=NULL;unsigned bytes=4,property=0;
 if(node==1){
  if(!strcmp(key,"redfin,abl-copy-only")){value=&marker;property=2;}
  else if(!strcmp(key,"redfin,framebuffer")){value=framebuffer;bytes=16;property=3;}
  else if(!strcmp(key,"width")){value=&width;property=4;}
  else if(!strcmp(key,"height")){value=&height;property=5;}
  else if(!strcmp(key,"stride")){value=&stride;property=6;}
  else if(!strcmp(key,"canvas-width")){value=&cw;property=7;}
  else if(!strcmp(key,"canvas-height")){value=&ch;property=8;}
  else if(!strcmp(key,"pixel-format")){value="BGRA";bytes=5;property=9;}
  else if(!strcmp(key,"compatible")){value="sweet,display";bytes=sizeof("sweet,display");property=10;}
 }else if(node==2){
  if(!strcmp(key,"compatible")){value="redfin,sec-touch";bytes=sizeof("redfin,sec-touch");property=11;}
  else if(!strcmp(key,"touch-size")){value=touch_size;bytes=8;property=12;}
 }
 if(!value){bad++;return -1;}
 static unsigned char altered[32];
 if(contract_fault==property){memcpy(altered,value,bytes);altered[0]^=1;value=altered;}
 if(contract_fault==property+20)bytes--;
 if(contract_fault==property+40)value=NULL;
 *out=value;*size=bytes;return 0;
}
int redfin_touch_start_initial(void);
static void step(unsigned value){
 if(flow_count>=16){bad++;return;}flow[flow_count++]=value;
 if(mutate_phase==value)arg_set(changed_key,1,1);
 if(reenter_phase==value){reenter_phase=0;reenter_result=(unsigned)redfin_touch_start_initial();}
}
int redfin_touch_rail_snapshot(void *context,struct redfin_touch_rail_state *out){
 if(context || !out)bad++;return 0;
}
int redfin_rpmh_touch_prepare(const struct redfin_touch_rail_ops *ops){
 step(1);if(!ops || ops->read!=redfin_touch_rail_snapshot || ops->context)bad++;
 if(ops){saved_ops=*ops;have_ops=true;}return (int)power_error;
}
int redfin_touch_rail_ready(void){step(2);return (int)ready_value;}
int redfin_touch_setup(bool rail,bool exclusive){
 step(3);if(!rail || !exclusive)bad++;identity=setup_error==0;return (int)setup_error;
}
bool redfin_touch_spi_identity_ready(void){return identity;}
int redfin_touch_spi_scan_probe(bool masked,unsigned batches){
 step(4);if(!masked || !identity || batches>4)bad++;scan_batches=batches;return (int)scan_error;
}
int redfin_touch_events_start(void){step(5);if(!identity)bad++;return (int)event_error;}
bool sweet_hid_redfin_touch_ready(void){consumer_checks++;return false;}
'''

START_MAIN = r'''
static unsigned callback_mask(void){
 if(!have_ops || !saved_ops.boot_lease_valid)return 0;
 unsigned result=0;const void *owner=saved_ops.boot_lease_owner;void *context=saved_ops.boot_lease_context;
 unsigned mode=saved_ops.boot_lease_mode;static int other;
 if(saved_ops.boot_lease_valid(owner,context,mode))result|=1;
 if(saved_ops.boot_lease_valid(NULL,context,mode))result|=2;
 if(saved_ops.boot_lease_valid(&other,context,mode))result|=4;
 if(saved_ops.boot_lease_valid(owner,NULL,mode))result|=8;
 if(saved_ops.boot_lease_valid(owner,&other,mode))result|=16;
 if(saved_ops.boot_lease_valid(owner,context,(mode+1)%3))result|=32;
 if(saved_ops.boot_lease_valid(owner,context,3))result|=64;
 return result;
}
int main(int argc,char **argv){
 platform_ok=return_ready=ready_value=1;root_present=true;memcpy(root_arg,"md0",4);
 if(argc<2)return 2;unsigned mode=(unsigned)strtoul(argv[1],NULL,0);
 if(mode==1)arg_set("redfintouchscan",1,1);
 if(mode==2){
  arg_set("redfintouchevents",1,1);arg_set("redfinroot",1,1);arg_set("redfinufs",3,1);
  arg_set("redfinfb",1,1);arg_set("ufsrw",0,1);arg_set("rootrw",0,1);arg_set("sweetlog",0,1);
  memset(root_arg,0,16);memcpy(root_arg,"ufsroot0",8);memcpy(ufsroot_arg,"userdata",8);ufsroot_present=true;
 }
 for(int i=2;i<argc;i++){
  char key[64]={0},text[64]={0};unsigned value=0,present=0;
  if(sscanf(argv[i],"arg:%63[^:]:%u:%u",key,&value,&present)==3)arg_set(key,value,(int)present);
  else if(sscanf(argv[i],"fail:%u:%u",&value,&present)==2){
   switch(value){case 1:power_error=present;break;case 2:ready_value=present;break;
    case 3:setup_error=present;break;case 4:scan_error=present;break;case 5:event_error=present;break;default:bad++;}
  }else if(sscanf(argv[i],"mutate:%u:%63s",&value,key)==2){
   mutate_phase=value;changed_key=argv[i]+strlen(argv[i])-strlen(key);
  }else if(sscanf(argv[i],"root:%63[^:]:%u",text,&present)==2){
   memset(root_arg,0,16);memcpy(root_arg,text,strlen(text)<16?strlen(text):16);root_present=present;
  }else if(sscanf(argv[i],"ufsroot:%63[^:]:%u",text,&present)==2){
   memset(ufsroot_arg,0,16);memcpy(ufsroot_arg,text,strlen(text)<16?strlen(text):16);ufsroot_present=present;
  }else if(sscanf(argv[i],"platform:%u",&value)==1)platform_ok=value;
  else if(sscanf(argv[i],"return:%u",&value)==1)return_ready=value;
  else if(sscanf(argv[i],"contract:%u",&value)==1)contract_fault=value;
  else if(sscanf(argv[i],"reenter:%u",&value)==1)reenter_phase=value;
  else bad++;
 }
 bool before=redfin_touch_boot_lease_valid(REDFIN_TOUCH_UFS_EVENTS);
 int first=redfin_touch_start_initial();
 bool after=redfin_touch_boot_lease_valid(REDFIN_TOUCH_UFS_EVENTS);unsigned callback=callback_mask();
 int second=redfin_touch_start_initial();
 fprintf(stdout,"%d %d %u %u %u %u %u %u %u %u %u",first,second,bad,consumer_checks,
  before,after,callback,have_ops?saved_ops.boot_lease_mode:99,
  have_ops?saved_ops.initial_md0_drv2_lease:0,reenter_result,scan_batches);
 for(unsigned i=0;i<flow_count;i++)fprintf(stdout," %u",flow[i]);
 fputc('\n',stdout);return 0;
}
'''

BACKEND_GLOBALS = r'''
static char lease_ufsroot[16];
static bool lease_ufsroot_present,lease_live;
static unsigned lease_mode,lease_calls,lease_deny;
static int lease_owner,lease_context;
'''

BACKEND_EXTRA = r'''
static bool test_lease(const void *owner,void *context,unsigned mode){
 lease_calls++;
 return lease_live && owner==&lease_owner && context==&lease_context && mode==lease_mode &&
     (!lease_deny || lease_calls!=lease_deny);
}
void lease_reset(const void *fixture,unsigned mode){
 host_reset(fixture);lease_mode=mode;lease_calls=lease_deny=0;lease_live=true;
 memset(lease_ufsroot,0,sizeof(lease_ufsroot));lease_ufsroot_present=false;
 host_arg("redfinreturn",1,1);host_arg("redfinspmi",1,1);
 host_arg("redfintouchscan",mode==1,1);host_arg("redfintouchevents",mode==2,1);
 host_arg("redfinfb",mode==2,1);host_arg("redfinufs",mode==2?3:0,1);
 host_arg("redfinroot",mode==2,1);host_arg("ufsrw",0,1);host_arg("rootrw",0,1);
 host_arg("sweetlog",0,1);
 if(mode==2){host_root("ufsroot0",1);memcpy(lease_ufsroot,"userdata",8);lease_ufsroot_present=true;}
}
void lease_config(unsigned issue,unsigned value){
 if(issue==0)lease_deny=value;else if(issue==1)lease_live=value;
 else if(issue==2)lease_ufsroot_present=value;else bad++;
}
int lease_prepare(unsigned issue){
 static int other;
 struct redfin_touch_rail_ops ops={.initial_md0_drv2_lease=lease_mode==0,
  .read=physical,.context=&context_token,.boot_lease_mode=lease_mode,
  .boot_lease_valid=test_lease,.boot_lease_owner=&lease_owner,.boot_lease_context=&lease_context};
 if(issue==1)ops.boot_lease_valid=NULL;
 if(issue==2)ops.boot_lease_owner=NULL;
 if(issue==3)ops.boot_lease_owner=&other;
 if(issue==4)ops.boot_lease_context=NULL;
 if(issue==5)ops.boot_lease_context=&other;
 if(issue==6)ops.boot_lease_mode=3;
 if(issue==7)ops.boot_lease_mode=(lease_mode+1)%3;
 if(issue==8)ops.initial_md0_drv2_lease=true;
 if(issue==9)ops.read=NULL;
 return redfin_rpmh_touch_prepare(&ops);
}
unsigned lease_stat(unsigned key){return key==0?lease_calls:lease_live;}
'''


def compile_c(compiler, source, output, *, shared=False):
    command = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror']
    if shared:
        command += ['-shared', '-fPIC']
    result = subprocess.run(command + [str(source), '-o', str(output)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)


def prepare_sources(root):
    dev = root / 'bsd/dev'
    dev.mkdir(parents=True)
    originals = {
        'redfin_touch_rail.h': 'touch-rail-ready.patch',
        'redfin_rpmh_touch.h': 'rpmh-touch.patch',
        'redfin_rpmh_touch.c': 'rpmh-touch.patch',
        'redfin_touch_start.c': 'touch-start.patch',
        'redfin_touch_events.c': 'touch-events.patch',
    }
    for name, patch in originals.items():
        (dev / name).write_text(added(patch, name))
    subprocess.run(['git', 'apply', '--include=bsd/dev/*', str(HERE / 'touch-event-start.patch')],
                   cwd=root, check=True)
    return dev


class TouchEventStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        dev = prepare_sources(root)
        for header in dev.glob('*.h'):
            shutil.copy2(header, root / header.name)
        (root / 'redfin_rpmh.h').write_text(rpmh_model.rpmh_file('redfin_rpmh.h'))
        start = root / 'start.c'
        start.write_text(START_MODEL + without_includes((dev / 'redfin_touch_start.c').read_text()) + START_MAIN)
        cls.executable = root / 'start'
        compile_c(compiler, start, cls.executable)

        prefix = rpmh_model.PREFIX
        match = re.search(r'static struct host_arg args\[\]=\{.*?\n\};', prefix, re.S)
        extra = ','.join('{"' + key + '",0,true}' for key in (
            'redfintouchscan', 'redfintouchevents', 'redfinufs', 'ufsrw', 'rootrw',
            'redfinfb', 'redfinreturn', 'redfinspmi', 'sweetlog', 'sweettouch', 'sweetcpufreq',
            'sweetusblog', 'redfinusbowned', 'redfinusbbypass', 'redfinusbcontexts',
            'redfinusbgadget', 'redfinusbnet', 'redfinusblog', 'redfinrpmh'))
        prefix = prefix[:match.start()] + match.group().replace('\n};', ',\n' + extra + '\n};') + prefix[match.end():]
        prefix = prefix.replace('static uint8_t db[RF_CMDDB_BYTES];', BACKEND_GLOBALS + '\nstatic uint8_t db[RF_CMDDB_BYTES];')
        parser = function(prefix, 'static bool PE_parse_boot_argn(')
        parser = parser.replace('{\n', '''{\n if(!strcmp(key,"ufsroot")){
  if(!lease_ufsroot_present)return false;
  if(size!=16){bad++;return false;}
  memcpy(out,lease_ufsroot,16);return true;
 }
''', 1)
        prefix = prefix.replace(function(prefix, 'static bool PE_parse_boot_argn('), parser)
        backend = without_includes((dev / 'redfin_rpmh_touch.c').read_text())
        for old, new in {
            '*(const volatile uint32_t *)(base + offset)': 'model_read(base,offset)',
            '*(volatile uint32_t *)(base + offset) = value;': 'model_write(base,offset,value);',
            '__asm__ volatile("dmb oshld" ::: "memory");': 'model_barrier();',
            '__asm__ volatile("dmb oshst" ::: "memory");': 'model_barrier();',
            '__asm__ volatile("dsb osh" ::: "memory");': 'model_barrier();',
        }.items():
            if backend.count(old) != 1:
                raise AssertionError('RPMh MMIO seam changed: ' + old)
            backend = backend.replace(old, new)
        source = root / 'backend.c'
        source.write_text(prefix + backend + rpmh_model.SUFFIX + BACKEND_EXTRA)
        library = root / 'backend.so'
        compile_c(compiler, source, library, shared=True)
        cls.backend = C.CDLL(str(library))
        cls.backend.lease_reset.argtypes = [C.c_void_p, C.c_uint]
        cls.backend.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
        cls.backend.host_root.argtypes = [C.c_char_p, C.c_int]
        cls.backend.host_config.argtypes = [C.c_uint, C.c_uint64]
        fixture = rpmh_model.database()
        struct.pack_into('<I', fixture, 144 + 0x200 + 16, 0x41300)
        cls.fixture = C.create_string_buffer(bytes(fixture))

    def setUp(self):
        self.reset_backend(0)

    def tearDown(self):
        self.assertEqual(self.backend.host_stat(3), 0, 'Unexpected RPMh MMIO, store order or physical callback')

    def start(self, mode=0, *commands):
        output = subprocess.check_output([str(self.executable), str(mode), *commands], text=True)
        values = list(map(int, output.split()))
        result = dict(zip(('first', 'second', 'bad', 'consumer_checks', 'before', 'after',
                           'callback', 'mode', 'md0', 'reenter', 'batches'), values[:11]))
        result['flow'] = values[11:]
        self.assertEqual(result['bad'], 0, 'Unexpected startup property, argument or backend call')
        self.assertEqual(result['consumer_checks'], 0, 'Boot thread must not poll HID readiness')
        self.assertEqual(result['before'], 0, 'Args cannot create the boot lease')
        return result

    def reset_backend(self, mode):
        self.backend.lease_reset(self.fixture, mode)

    def backend_counts(self):
        return tuple(self.backend.host_stat(key) for key in (0, 1, 2, 4))

    def test_legacy_id_scan_and_gui_have_exact_order_without_hid_wait(self):
        for mode, flow in ((0, [1, 2, 3]), (1, [1, 2, 3, 4]), (2, [1, 2, 3, 5])):
            with self.subTest(mode=mode):
                result = self.start(mode)
                self.assertEqual((result['first'], result['second']), (0, errno.EBUSY))
                self.assertEqual(result['flow'], flow)
                self.assertEqual(result['mode'], mode)
                self.assertEqual(result['md0'], int(mode == 0))
                self.assertEqual(result['after'], int(mode == 2))
                if mode:
                    self.assertEqual(result['callback'], 1, 'Only the exact static owner/context/mode may validate')
        self.assertLessEqual(self.start(1)['batches'], 4)
        self.assertEqual(self.start(2, 'arg:ufsrw:1:1', 'arg:rootrw:1:1')['first'], 0)

    def test_power_fresh_ready_identity_and_terminal_failures_keep_claim_sticky(self):
        for mode in range(3):
            for phase, error, flow in ((1, errno.EIO, [1]), (2, 0, [1, 2]),
                                       (2, 2, [1, 2]), (2, 0xffffffff, [1, 2]),
                                       (3, errno.EIO, [1, 2, 3])):
                with self.subTest(mode=mode, phase=phase, error=error):
                    result = self.start(mode, f'fail:{phase}:{error}')
                    self.assertEqual(result['first'], errno.ENXIO if phase == 2 else error)
                    self.assertEqual(result['second'], errno.EBUSY)
                    self.assertEqual(result['flow'], flow)
        for mode, phase in ((1, 4), (2, 5)):
            result = self.start(mode, f'fail:{phase}:{errno.EIO}')
            self.assertEqual((result['first'], result['second']), (errno.EIO, errno.EBUSY))
            self.assertEqual(result['flow'], [1, 2, 3, phase])

    def test_new_modes_require_explicit_flags_correct_root_and_disabled_competitors(self):
        legacy = ('sweettouch', 'sweetkeys', 'sweetusb', 'sweetcpufreq', 'sweetbattery', 'modem', 'wifi', 'gpu')
        for mode in (1, 2):
            for command in ('platform:0', 'return:0', 'arg:cpus:2:1', 'arg:redfinreturn:0:1',
                            'arg:redfinreturn:1:0', 'arg:redfinspmi:0:1', 'arg:redfinspmi:1:0'):
                result = self.start(mode, command)
                self.assertNotEqual(result['first'], 0)
                self.assertEqual(result['flow'], [])
            for key in legacy:
                for value, present in ((1, 1), (0, 0)):
                    result = self.start(mode, f'arg:{key}:{value}:{present}')
                    self.assertNotEqual(result['first'], 0)
                    self.assertEqual(result['flow'], [])
            for key in ('redfinusb', 'redfinwifi', 'redfingpu', 'sweethw'):
                result = self.start(mode, f'arg:{key}:1:1')
                self.assertNotEqual(result['first'], 0)
                self.assertEqual(result['flow'], [])
        for mode, commands in ((1, ('arg:redfintouchscan:2:1',)),
                               (2, ('arg:redfintouchevents:2:1',)),
                               (1, ('arg:redfintouchevents:1:1',)),
                               (2, ('arg:redfintouchscan:1:1',)),
                               (1, ('root:md0x:1',)), (1, ('root:md0:0',)),
                               (1, ('ufsroot:userdata:1',)),
                               (2, ('root:md0:1',)), (2, ('root:ufsroot0x:1',)),
                               (2, ('ufsroot:other:1',)), (2, ('ufsroot:userdata:0',)),
                               (2, ('arg:redfinroot:0:1',)), (2, ('arg:redfinufs:2:1',)),
                               (2, ('arg:redfinfb:0:1',)), (2, ('arg:ufsrw:1:1',)),
                               (2, ('arg:ufsrw:2:1', 'arg:rootrw:2:1')), (2, ('arg:sweetlog:1:1',))):
            with self.subTest(mode=mode, commands=commands):
                result = self.start(mode, *commands)
                self.assertNotEqual(result['first'], 0)
                self.assertEqual(result['flow'], [])

    def test_exact_gui_display_profile_precedes_claim_and_any_backend_call(self):
        for fault in (1,) + tuple(value + delta for value in range(2, 10) for delta in (0, 20, 40)):
            with self.subTest(fault=fault):
                result = self.start(2, f'contract:{fault}')
                self.assertNotEqual(result['first'], 0)
                self.assertEqual(result['flow'], [])

    def test_reentrant_start_cannot_acquire_second_owner(self):
        for mode in range(3):
            for phase in (1, 2, 3):
                result = self.start(mode, f'reenter:{phase}')
                self.assertEqual(result['first'], 0)
                self.assertEqual(result['reenter'], errno.EBUSY)
                self.assertEqual(result['second'], errno.EBUSY)

    def test_lost_source_policy_prevents_next_hardware_or_worker_stage(self):
        for mode in (1, 2):
            for phase in (1, 2, 3):
                with self.subTest(mode=mode, phase=phase):
                    result = self.start(mode, f'mutate:{phase}:redfinusb')
                    self.assertNotEqual(result['first'], 0)
                    self.assertNotIn(4, result['flow'])
                    self.assertNotIn(5, result['flow'])
                    if phase < 3:
                        self.assertNotIn(3, result['flow'])
                    self.assertEqual(result['callback'], 0)
                    self.assertEqual(result['after'], 0)

    def test_actual_backend_keeps_vote_resource_contract_for_all_three_modes(self):
        for mode in range(3):
            with self.subTest(mode=mode):
                self.reset_backend(mode)
                self.assertEqual(self.backend.lease_prepare(0), 0)
                self.assertEqual(self.backend_counts(), (3, 234, 19, 5))
                before = self.backend_counts()
                self.assertEqual(self.backend.lease_prepare(0), errno.EBUSY)
                self.assertEqual(self.backend_counts(), before)
                self.reset_backend(mode)
                self.backend.host_config(3, 14)
                self.backend.host_config(13, 0x87)
                self.assertEqual(self.backend.lease_prepare(0), 0)
                self.assertEqual(self.backend_counts(), (0, 0, 0, 2))

    def test_actual_backend_requires_durable_identity_bound_callback_for_new_modes(self):
        for mode in (1, 2):
            for issue in range(1, 8):
                with self.subTest(mode=mode, issue=issue):
                    self.reset_backend(mode)
                    self.assertNotEqual(self.backend.lease_prepare(issue), 0)
                    self.assertEqual(self.backend_counts(), (0, 0, 0, 0))
            for issue in (8, 9):
                self.reset_backend(mode)
                self.assertNotEqual(self.backend.lease_prepare(issue), 0)
                self.assertEqual(self.backend_counts(), (0, 0, 0, 0))
            self.reset_backend(mode)
            self.backend.lease_config(1, 0)
            self.assertNotEqual(self.backend.lease_prepare(0), 0)
            self.assertEqual(self.backend_counts(), (0, 0, 0, 0))

    def test_actual_backend_new_modes_keep_root_flags_and_callback_boundaries(self):
        for mode in (1, 2):
            self.reset_backend(mode)
            self.assertEqual(self.backend.lease_prepare(0), 0)
            calls = self.backend.lease_stat(0)
            self.assertGreater(calls, 0)
            for denied in range(1, calls + 1):
                with self.subTest(mode=mode, denied=denied):
                    self.reset_backend(mode)
                    self.backend.lease_config(0, denied)
                    self.assertNotEqual(self.backend.lease_prepare(0), 0)
                    self.assertLessEqual(self.backend.host_stat(2), 19)
                    if denied == 1:
                        self.assertEqual(self.backend_counts(), (0, 0, 0, 0))
                    if self.backend.host_stat(8):
                        before = self.backend_counts()
                        self.assertEqual(self.backend.lease_prepare(0), errno.EBUSY)
                        self.assertEqual(self.backend_counts(), before)
            for root in (b'md0x', b'ufsroot0x'):
                self.reset_backend(mode)
                self.backend.host_root(root, 1)
                self.assertNotEqual(self.backend.lease_prepare(0), 0)
                self.assertEqual(self.backend_counts(), (0, 0, 0, 0))


class TouchEventBootLeaseWorkerTests(worker_model.TouchEventWorkerTests):
    @classmethod
    def setUpClass(cls):
        worker_model.TouchEventWorkerTests.setUpClass()
        cls.addClassCleanup(worker_model.TouchEventWorkerTests.doClassCleanups)
        template = (Path(worker_model.TouchEventWorkerTests.tmp.name) / 'worker.c').read_text()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        dev = prepare_sources(root)
        for header in Path(worker_model.TouchEventWorkerTests.tmp.name).glob('*.h'):
            shutil.copy2(header, root / header.name)
        for header in dev.glob('*.h'):
            shutil.copy2(header, root / header.name)
        original = without_includes(added('touch-events.patch', 'redfin_touch_events.c'))
        updated = without_includes((dev / 'redfin_touch_events.c').read_text())
        for old, new in (
            ('*(volatile const uint32_t *)(base + offset)', 'model_read(base, offset)'),
            ('__asm__ volatile("dmb oshld" ::: "memory");', '(void)0;'),
        ):
            original = original.replace(old, new)
            updated = updated.replace(old, new)
        if template.count(original) != 1:
            raise AssertionError('Actual worker source seam changed')
        helpers = r'''
static unsigned sense_calls;
bool redfin_touch_boot_lease_valid(unsigned mode){
 if(mode!=REDFIN_TOUCH_UFS_EVENTS)violations++;
 return fault!=20 && !(fault==21 && emits) && !(fault==24 && begins) &&
     !(fault==25 && now>=200000000ull) && !(fault==26 && sense_calls) && !(fault==27 && emits>=10);
}
int redfin_touch_spi_events_sense_init(void){
 sense_calls++;
 if(!sweet_hid_redfin_touch_ready() || begins!=1)violations++;
 return fault==13?ENOTSUP:fault==22?EIO:0;
}
'''
        template = template.replace(original, helpers + updated)
        template = template.replace('fault=issue;enabled=flag;', 'sense_calls=0;fault=issue;enabled=flag;')
        template = template.replace('!(fault==19 && emits>=1);', '!(fault==19 && emits>=1) && !(fault==23 && begins);')
        template = template.replace('fault==14 ? 9 :', '(fault==14 || fault==27) ? 9 :')
        template += '\nunsigned boot_stat(unsigned n){return n==0?sense_calls:hid_down;}\n'
        source = root / 'worker.c'
        source.write_text('#include "redfin_rpmh_touch.h"\n' + template)
        library = root / 'worker.so'
        compile_c(shutil.which('cc'), source, library, shared=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint] * 3

    def test_transport_consumer_or_gic_loss_releases_down_and_stops(self):
        for issue, error in ((3, errno.EIO), (19, errno.EPIPE), (8, errno.EIO)):
            self.assertEqual(self.run_worker(issue), 0)
            self.assertEqual(self.lib.stat(10), error)
            self.assertEqual(self.lib.stat(7), 1)
            self.assertEqual([self.lib.emitted_value(i, 1) for i in range(self.lib.stat(8))], [1, 0])
            self.assertEqual(self.lib.boot_stat(1), 0)
        for issue in (4, 5):
            self.assertEqual(self.run_worker(issue), 0)
            self.assertEqual(self.lib.stat(10), errno.EPIPE)
            self.assertEqual(self.lib.stat(8), 0, 'Lost consumer/GIC proof during read must prevent DOWN')
            self.assertEqual(self.lib.stat(7), 1)

    def test_sensing_requires_real_hid_and_owned_open_session(self):
        self.assertEqual(self.run_worker(1), 0)
        self.assertEqual(self.lib.boot_stat(0), 0)
        for issue in (23, 24):
            with self.subTest(issue=issue):
                self.assertEqual(self.run_worker(issue), 0)
                self.assertEqual(self.lib.stat(10), errno.EPIPE)
                self.assertEqual(self.lib.boot_stat(0), 0)
                self.assertEqual(self.lib.stat(3), 0)
                self.assertEqual(self.lib.stat(7), 1)
        self.assertEqual(self.run_worker(22), 0)
        self.assertEqual(self.lib.stat(10), errno.EIO)
        self.assertEqual(self.lib.boot_stat(0), 1)
        self.assertEqual(self.lib.stat(4), 0)
        self.assertEqual(self.lib.stat(8), 0)

    def test_lease_loss_before_start_or_during_hid_wait_never_opens_spi(self):
        self.assertEqual(self.run_worker(20), errno.ENOTSUP)
        self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual(self.run_worker(25), 0)
        self.assertEqual(self.lib.stat(10), errno.EPERM)
        self.assertEqual(self.lib.stat(6), 0)
        self.assertEqual(self.lib.boot_stat(0), 0)
        self.assertEqual(self.lib.stat(3), 0)

    def test_lease_loss_after_sense_or_down_closes_and_releases_every_contact(self):
        self.assertEqual(self.run_worker(26), 0)
        self.assertEqual(self.lib.stat(10), errno.EBUSY)
        self.assertEqual(self.lib.boot_stat(0), 1)
        self.assertEqual(self.lib.stat(4), 0)
        self.assertEqual(self.lib.stat(8), 0)
        for issue, contacts in ((21, 1), (27, 10)):
            with self.subTest(issue=issue):
                self.assertEqual(self.run_worker(issue), 0)
                self.assertEqual(self.lib.stat(10), errno.EBUSY)
                self.assertEqual(self.lib.stat(8), contacts * 2)
                self.assertEqual([self.lib.emitted_value(i, 1) for i in range(contacts * 2)],
                                 [1] * contacts + [0] * contacts)
                self.assertEqual(self.lib.boot_stat(1), 0)
                self.assertEqual(self.lib.stat(7), 1)


if __name__ == '__main__':
    unittest.main()
