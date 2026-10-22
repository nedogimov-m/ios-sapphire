"""Run the actual trusted USB caller: gates, permanent lease and backend ordering."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from ports.redfin.test_usb_owned_route import added_file


PREFIX = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include "redfin_usb_owned.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
#define printf fake_printf
typedef void *DTEntry;
static unsigned logs,violations,callbacks;
static int fake_printf(const char *format,...){if(strstr(format,"REDFIN USB START:"))logs++;return 0;}
struct arg {const char *name;uint32_t value;bool present;};
static struct arg args[]={
 {"redfinusb",3,true},{"redfinusbowned",1,true},{"cpus",1,true},{"redfinreturn",1,true},
 {"sweettouch",0,true},{"sweetkeys",0,true},{"sweetusb",0,true},{"sweetcpufreq",0,true},
 {"sweetbattery",0,true},{"modem",0,true},{"wifi",0,true},{"gpu",0,true},
 {"redfintouch",0,false},{"redfintouchsetup",0,false},{"redfintouchevents",0,false},
 {"redfinrpmhtouch",0,false},{"redfinrpmh",0,false},{"redfinrail",0,false},
 {"redfinwifi",0,false},{"redfingpu",0,false},{"redfinroot",0,false},{"redfinufs",0,false},
 {"ufsrw",0,false},{"rootrw",0,false},{"redfinusbnet",0,false},{"redfinusblog",0,false},
 {"redfinfb",0,false},{"redfinscreen",0,false},{"sweethw",0,false},{"sweetusblog",0,false}
};
static char root_arg[80];
static bool root_present,ufsroot_present,platform_ok;
static int return_ready;
static unsigned dt_fault,backend_fault,registers,claims,revalidates,sequence;
static int nested_result;
static const void *saved_caller;
static struct redfin_usb_owned_policy saved_policy;
static bool PE_parse_boot_argn(const char *name,void *out,unsigned bytes){
 if(!strcmp(name,"rd")){
  if(!root_present)return false;
  size_t length=strlen(root_arg)+1;if(length>bytes)length=bytes;memcpy(out,root_arg,length);return true;
 }
 if(!strcmp(name,"ufsroot")){if(!ufsroot_present)return false;memset(out,0,bytes);return true;}
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(name,args[i].name)){
  if(bytes!=4){violations++;return false;}
  if(!args[i].present)return false;memcpy(out,&args[i].value,4);return true;
 }
 violations++;return false;
}
bool redfin_usb_platform(void){return platform_ok;}
int redfin_spmi_return_ready(void){return return_ready;}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
 (void)root;if(strcmp(path,"/redfin-usb-route")){violations++;return 1;}
 *out=(void *)1;return dt_fault==1 ? 1 : 0;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *bytes){
 if(node!=(void *)1)violations++;
 static uint8_t unaligned_reg[17],unaligned_sid[5];
 uint64_t reg[]={dt_fault==5?0x15004000:0x15000000,dt_fault==6?0x4000:0x100000};
 uint32_t sid=dt_fault==10?0xe1:0xe0;
 memcpy(unaligned_reg+1,reg,16);memcpy(unaligned_sid+1,&sid,4);
 if(!strcmp(name,"reg")){
  *out=dt_fault==3 ? NULL : unaligned_reg+1;*bytes=dt_fault==4?15:16;return dt_fault==2?1:0;
 }
 if(!strcmp(name,"stream-id")){
  *out=dt_fault==8 ? NULL : unaligned_sid+1;*bytes=dt_fault==9?8:4;return dt_fault==7?1:0;
 }
 violations++;return 1;
}
int redfin_usb_start_initial(void);
static bool backend_policy(unsigned stage){
 if(backend_fault==stage+3){args[11].value=1;args[11].present=true;}
 callbacks++;return saved_policy.exclusive && saved_policy.exclusive(saved_caller,saved_policy.context);
}
int redfin_usb_owned_register(const void *caller,const struct redfin_usb_owned_policy *policy){
 registers++;sequence=sequence*10+1;saved_caller=caller;saved_policy=*policy;
 if(backend_fault==7)nested_result=redfin_usb_start_initial();
 if(!backend_policy(1))return EPERM;
 return backend_fault==1?EIO:0;
}
int redfin_usb_owned_claim(const void *caller){
 claims++;sequence=sequence*10+2;if(caller!=saved_caller)violations++;
 if(!backend_policy(2))return EPERM;
 return backend_fault==2?ETIMEDOUT:0;
}
int redfin_usb_owned_revalidate(const void *caller){
 revalidates++;sequence=sequence*10+3;if(caller!=saved_caller)violations++;
 if(!backend_policy(3))return EPERM;
 return backend_fault==3?EAGAIN:0;
}
'''

SUFFIX = r'''
void reset(void){
 logs=violations=callbacks=registers=claims=revalidates=sequence=0;nested_result=0;
 saved_caller=NULL;memset(&saved_policy,0,sizeof(saved_policy));
 platform_ok=true;return_ready=1;dt_fault=backend_fault=0;root_present=true;ufsroot_present=false;
 strcpy(root_arg,"md0");__atomic_store_n(&redfin_initial_usb_lease,0,__ATOMIC_RELEASE);
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++){
  args[i].present=i<12;args[i].value=i==0?3:i<4?1:0;
 }
}
int set_arg(const char *name,unsigned value,bool present){
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(name,args[i].name)){
  args[i].value=value;args[i].present=present;return 1;
 }
 return 0;
}
void set_root(const char *text,bool present,bool ufsroot){
 memset(root_arg,0,sizeof(root_arg));strncpy(root_arg,text,sizeof(root_arg)-1);
 root_present=present;ufsroot_present=ufsroot;
}
void set_environment(bool platform,int ready,unsigned dt,unsigned fault){
 platform_ok=platform;return_ready=ready;dt_fault=dt;backend_fault=fault;
}
unsigned stat(unsigned n){
 const unsigned values[]={registers,claims,revalidates,sequence,logs,violations,
  __atomic_load_n(&redfin_initial_usb_lease,__ATOMIC_ACQUIRE),callbacks,(unsigned)nested_result};
 return n<9?values[n]:0;
}
unsigned probe(unsigned variant){
 static unsigned impostor;
 if(variant==0)return redfin_initial_usb_exclusive(&redfin_initial_usb_caller,&redfin_initial_usb_lease);
 if(!saved_policy.exclusive)return 0;
 if(variant==1)return saved_policy.exclusive(&impostor,saved_policy.context);
 if(variant==2)return saved_policy.exclusive(saved_caller,&impostor);
 if(variant==3){
  __atomic_store_n(&redfin_initial_usb_lease,2,__ATOMIC_RELEASE);
  bool result=saved_policy.exclusive(saved_caller,saved_policy.context);
  __atomic_store_n(&redfin_initial_usb_lease,1,__ATOMIC_RELEASE);return result;
 }
 return saved_policy.exclusive(saved_caller,saved_policy.context);
}
void occupy_lease(void){__atomic_store_n(&redfin_initial_usb_lease,1,__ATOMIC_RELEASE);}
'''


class USBStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        work = Path(cls.temp.name)
        patch = Path(__file__).with_name('usb-start.patch').read_text()
        actual = added_file(patch, 'bsd/dev/redfin_usb_start.c')
        actual = re.sub(r'^#include <[^\n]+\n', '', actual, flags=re.M)
        owned = Path(__file__).with_name('usb-owned-route.patch').read_text()
        (work / 'redfin_usb_owned.h').write_text(added_file(owned, 'bsd/dev/redfin_usb_owned.h'))
        (work / 'model.c').write_text(PREFIX + actual + SUFFIX)
        library = work / 'model.so'
        subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(work / 'model.c'), '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.set_arg.argtypes = [C.c_char_p, C.c_uint, C.c_bool]
        cls.lib.set_root.argtypes = [C.c_char_p, C.c_bool, C.c_bool]
        cls.lib.set_environment.argtypes = [C.c_bool, C.c_int, C.c_uint, C.c_uint]

    def setUp(self):
        self.lib.reset()

    def arg(self, name, value, present=True):
        self.assertEqual(self.lib.set_arg(name.encode(), value, present), 1)

    def run_start(self):
        result = self.lib.redfin_usb_start_initial()
        self.assertEqual(self.lib.stat(5), 0)
        return result

    def assert_refused(self):
        self.assertEqual(self.run_start(), errno.ENOTSUP)
        self.assertEqual(tuple(self.lib.stat(i) for i in (0, 1, 2, 6)), (0, 0, 0, 0))

    def test_success_registers_claims_strictly_revalidates_once_without_dma(self):
        self.assertEqual(self.lib.probe(0), 0)  # Good boot args alone are insufficient.
        self.assertEqual(self.run_start(), 0)
        self.assertEqual(tuple(self.lib.stat(i) for i in range(5)), (1, 1, 1, 123, 3))
        self.assertEqual(self.run_start(), errno.EBUSY)
        self.assertEqual(self.lib.stat(0), 1)
        self.assertEqual(self.lib.stat(6), 1)

    def test_exact_mode_opt_in_cpu_and_verified_return_are_required(self):
        for name, value in (('redfinusb', 2), ('redfinusb', 4), ('redfinusbowned', 0),
                            ('redfinusbowned', 2), ('cpus', 2), ('redfinreturn', 0)):
            with self.subTest(name=name, value=value):
                self.lib.reset();self.arg(name, value);self.assert_refused()
        for name in ('redfinusb', 'redfinusbowned', 'cpus', 'redfinreturn'):
            with self.subTest(missing=name):
                self.lib.reset();self.arg(name, 0, False);self.assert_refused()
        for platform, ready in ((False, 1), (True, 0), (True, -1), (True, 2)):
            self.lib.reset();self.lib.set_environment(platform, ready, 0, 0);self.assert_refused()

    def test_all_eight_legacy_paths_must_be_explicit_zero(self):
        for name in ('sweettouch', 'sweetkeys', 'sweetusb', 'sweetcpufreq',
                     'sweetbattery', 'modem', 'wifi', 'gpu'):
            for present in (False, True):
                with self.subTest(name=name, present=present):
                    self.lib.reset();self.arg(name, 1 if present else 0, present);self.assert_refused()

    def test_every_other_native_activation_and_write_path_is_disabled(self):
        for name in ('redfintouch', 'redfintouchsetup', 'redfintouchevents', 'redfinrpmhtouch',
                     'redfinrpmh', 'redfinrail', 'redfinwifi', 'redfingpu', 'redfinroot', 'redfinufs',
                     'ufsrw', 'rootrw', 'redfinusbnet', 'redfinusblog', 'redfinfb', 'redfinscreen',
                     'sweethw', 'sweetusblog'):
            with self.subTest(name=name):
                self.lib.reset();self.arg(name, 1);self.assert_refused()
        self.lib.reset()
        self.arg('redfinroot', 0);self.arg('redfinufs', 0)
        self.assertEqual(self.run_start(), 0)

    def test_md0_only_and_even_empty_ufsroot_is_refused(self):
        for text, present, ufsroot in ((b'md0', False, False), (b'ufsroot0', True, False),
                                       (b'md0-extra', True, False), (b'x'*79, True, False),
                                       (b'md0', True, True)):
            self.lib.reset();self.lib.set_root(text, present, ufsroot);self.assert_refused()

    def test_exact_live_adt_tuple_is_required_before_lease_or_registration(self):
        for fault in range(1, 11):
            with self.subTest(fault=fault):
                self.lib.reset();self.lib.set_environment(True, 1, fault, 0);self.assert_refused()

    def test_callback_has_permanent_context_and_rejects_impostors_or_bad_lease(self):
        self.assertEqual(self.run_start(), 0)
        self.assertEqual(self.lib.probe(4), 1)
        for variant in (1, 2, 3):
            self.assertEqual(self.lib.probe(variant), 0)
        self.assertEqual(self.lib.probe(4), 1)
        self.arg('gpu', 1)
        self.assertEqual(self.lib.probe(4), 0)
        self.assertEqual(tuple(self.lib.stat(i) for i in (0, 1, 2)), (1, 1, 1))

    def test_each_backend_failure_preserves_lease_and_never_retries_or_advances(self):
        for fault, error, counts in ((1, errno.EIO, (1, 0, 0)),
                                     (2, errno.ETIMEDOUT, (1, 1, 0)),
                                     (3, errno.EAGAIN, (1, 1, 1))):
            with self.subTest(fault=fault):
                self.lib.reset();self.lib.set_environment(True, 1, 0, fault)
                self.assertEqual(self.run_start(), error)
                self.assertEqual(self.run_start(), errno.EBUSY)
                self.assertEqual(tuple(self.lib.stat(i) for i in (0, 1, 2)), counts)
                self.assertEqual(self.lib.stat(6), 1)

    def test_callback_rechecks_disabled_paths_inside_each_backend(self):
        for fault, counts in ((4, (1, 0, 0)), (5, (1, 1, 0)), (6, (1, 1, 1))):
            with self.subTest(fault=fault):
                self.lib.reset();self.lib.set_environment(True, 1, 0, fault)
                self.assertEqual(self.run_start(), errno.EPERM)
                self.assertEqual(tuple(self.lib.stat(i) for i in (0, 1, 2)), counts)
                self.assertEqual(self.lib.stat(6), 1)

    def test_existing_or_reentrant_claim_cannot_register_a_second_owner(self):
        self.lib.occupy_lease()
        self.assertEqual(self.run_start(), errno.EBUSY)
        self.assertEqual(self.lib.stat(0), 0)
        self.lib.reset();self.lib.set_environment(True, 1, 0, 7)
        self.assertEqual(self.run_start(), 0)
        self.assertEqual(self.lib.stat(8), errno.EBUSY)
        self.assertEqual(tuple(self.lib.stat(i) for i in (0, 1, 2)), (1, 1, 1))


if __name__ == '__main__':
    unittest.main()
