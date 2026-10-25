"""Execute real capability/HMAC/lifecycle code against native-shaped requests."""
import base64
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import hashlib
import hmac
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
class Actor(C.Structure):
    _fields_=[(k,C.c_uint32) for k in ['pid','version','uid','issuer']]
class Request(C.Structure):
    _fields_=[(k,C.c_uint32) for k in ['kind','flags','target_pid','target_version']]+[('class_name',C.c_char*160),('resource',C.c_char*1024)]
HARNESS=r'''
#include "sandbox-capabilities.h"
#include <CommonCrypto/CommonHMAC.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
static struct rf_sbx_registry registry;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static unsigned bad_random,bad_mac,key_generation;
static int random_bytes(void *p,uint8_t *out,size_t n){(void)p;if(bad_random)return -1;arc4random_buf(out,n);return 0;}
static int mac(void *p,const uint8_t *in,size_t n,uint8_t out[32]){(void)p;if(bad_mac)return -1;
 uint8_t key[32];for(unsigned i=0;i<32;++i)key[i]=(uint8_t)(i+1+key_generation);
 CCHmac(kCCHmacAlgSHA256,key,sizeof(key),in,n,out);return 0;}
static void lock(void *p){(void)p;pthread_mutex_lock(&mutex);}
static void unlock(void *p){(void)p;pthread_mutex_unlock(&mutex);}
static struct rf_sbx_ops ops={0,random_bytes,mac,lock,unlock};
void reset(void){memset(&registry,0,sizeof(registry));bad_random=bad_mac=key_generation=0;}
void fault(unsigned k,unsigned value){if(k==0)bad_random=value;if(k==1)bad_mac=value;if(k==2)key_generation=value;}
int issue(const struct rf_sbx_actor *a,const struct rf_sbx_request *q,char *out){return rf_sbx_issue(&registry,&ops,a,q,out);}
int consume(const struct rf_sbx_actor *a,const char *token,size_t n,uint64_t *out){return rf_sbx_consume(&registry,&ops,a,token,n,out);}
int release(const struct rf_sbx_actor *a,uint64_t handle){return rf_sbx_release(&registry,&ops,a,handle);}
void exited(const struct rf_sbx_actor *a){rf_sbx_exit(&registry,&ops,a);}
unsigned metric(unsigned which){unsigned total=0;lock(0);
 if(which==0)for(unsigned i=0;i<RF_SBX_ENTRIES;++i)total+=registry.entry[i].used!=0;
 if(which==1)for(unsigned i=0;i<RF_SBX_HANDLES;++i)total+=registry.handle[i].value!=0;
 if(which==2)for(unsigned i=0;i<RF_SBX_ENTRIES;++i)total+=registry.entry[i].references;
 unlock(0);return total;}
'''

class SandboxCapabilitiesTests(unittest.TestCase):
    def test_actual_native_issuer_gate_rejects_renamed_or_unvalidated_callers(self):
        source=(HERE/'sandbox-native.c').read_text();start=source.index('static bool is_native_tcc_manager(')
        end=source.index('\n}\n',start)+3;method=source[start:end]
        program=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define MAXPATHLEN 1024
#define CS_VALID 1
struct proc {const char *identity,*p_textvp;unsigned platform,flags;};
typedef struct proc *proc_t;
static const char *csproc_get_identity(proc_t p){return p->identity;}
static unsigned csproc_get_platform_binary(proc_t p){return p->platform;}
static unsigned proc_getcsflags(proc_t p){return p->flags;}
static int vn_getpath(const char *p,char *out,int *n){size_t bytes=strlen(p)+1;if(bytes>(size_t)*n)return 1;memcpy(out,p,bytes);*n=(int)bytes;return 0;}
'''+method+r'''
int main(void) {
 const char *path="/System/Library/PrivateFrameworks/TCC.framework/Support/tccd";
 struct proc p={"com.apple.tccd",path,1,CS_VALID};assert(is_native_tcc_manager(&p));
 p.platform=0;assert(!is_native_tcc_manager(&p));p.platform=1;
 p.flags=0;assert(!is_native_tcc_manager(&p));p.flags=CS_VALID;
 p.identity="com.apple.assetsd";assert(!is_native_tcc_manager(&p));p.identity="com.apple.tccd";
 p.p_textvp="/private/var/mobile/tccd";assert(!is_native_tcc_manager(&p));
 p.p_textvp="/System/Library/PrivateFrameworks/TCC.framework/Support/tccd-evil";assert(!is_native_tcc_manager(&p));
 p.p_textvp=0;assert(!is_native_tcc_manager(&p));return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'policy.c').write_text(program)
            result=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(p/'policy.c'),'-o',str(p/'policy')],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            subprocess.run([str(p/'policy')],check=True,capture_output=True)

    @classmethod
    def setUpClass(cls):
        cc=shutil.which('cc')
        if not cc:raise unittest.SkipTest('native host C compiler required')
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);p=Path(cls.temp.name)
        (p/'model.c').write_text(HARNESS)
        result=subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-pthread',
            '-I',str(HERE),str(p/'model.c'),str(HERE/'sandbox-capabilities.c'),'-o',str(p/'model.so')],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        cls.lib=C.CDLL(str(p/'model.so'))
        cls.lib.issue.argtypes=[C.POINTER(Actor),C.POINTER(Request),C.c_void_p]
        cls.lib.consume.argtypes=[C.POINTER(Actor),C.c_void_p,C.c_size_t,C.POINTER(C.c_uint64)]
        cls.lib.release.argtypes=[C.POINTER(Actor),C.c_uint64]
        cls.lib.exited.argtypes=[C.POINTER(Actor)]

    def setUp(self):
        self.lib.reset();self.issuer=Actor(38,1,501,1);self.client=Actor(247,7,501,0)

    @staticmethod
    def request(kind=3,resource=b'',name=b'com.apple.tcc.kTCCServicePhotos',flags=0,pid=0,version=0):
        return Request(kind,flags,pid,version,name,resource)

    def issue(self,q=None,owner=None):
        out=C.create_string_buffer(2048);error=self.lib.issue(C.byref(owner or self.issuer),C.byref(q or self.request()),out)
        return error,out.value+b'\0'

    def consume(self,token,owner=None):
        handle=C.c_uint64(0x123);error=self.lib.consume(C.byref(owner or self.client),token,len(token),C.byref(handle))
        return error,handle.value

    def test_actual_hmac_scope_roundtrip_balanced_handles_and_token_reuse(self):
        error,token=self.issue();self.assertEqual(error,0);self.assertLess(len(token),2048)
        raw=base64.urlsafe_b64decode(token[6:-1]);self.assertEqual(raw[:8],b'RFSBX01\0')
        self.assertEqual(raw[-32:],hmac.new(bytes(range(1,33)),raw[:-32],hashlib.sha256).digest())
        self.assertEqual(struct.unpack_from('<6I',raw,8),(3,0,501,0,0,0))
        self.assertEqual(self.lib.metric(0),0,'issuing an opaque token does not fabricate an active reference')
        e,h1=self.consume(token);self.assertEqual(e,0);e,h2=self.consume(token);self.assertEqual(e,0);self.assertNotEqual(h1,h2)
        self.assertEqual([self.lib.metric(i) for i in range(3)],[1,2,2])
        self.assertEqual(self.lib.release(C.byref(self.client),h1),0)
        self.assertNotEqual(self.lib.release(C.byref(self.client),h1),0)
        self.assertEqual(self.lib.release(C.byref(self.client),h2),0)
        self.assertEqual([self.lib.metric(i) for i in range(3)],[0,0,0])
        self.assertEqual(self.consume(token)[0],0,'a released native bearer token can be consumed again in the same boot')

    def test_issuer_role_and_uid_cannot_be_forged_by_an_untrusted_request(self):
        for owner in [Actor(247,7,501,0),Actor(0,1,501,1),Actor(38,0,501,1)]:
            self.assertNotEqual(self.issue(owner=owner)[0],0)
        error,token=self.issue();self.assertEqual(error,0)
        self.assertNotEqual(self.consume(token,Actor(248,1,502,0))[0],0)
        self.assertEqual(self.lib.metric(0),0)

    def test_target_binding_rejects_wrong_pid_and_reused_process_generation(self):
        q=self.request(flags=0x30000,pid=247,version=7);e,token=self.issue(q);self.assertEqual(e,0)
        for actor in [Actor(248,7,501,0),Actor(247,8,501,0)]:self.assertNotEqual(self.consume(token,actor)[0],0)
        e,handle=self.consume(token);self.assertEqual(e,0)
        for actor in [Actor(248,7,501,0),Actor(247,8,501,0)]:self.assertNotEqual(self.lib.release(C.byref(actor),handle),0)
        self.lib.exited(C.byref(Actor(247,8,501,0)));self.assertEqual(self.lib.metric(1),1)
        self.lib.exited(C.byref(self.client));self.assertEqual(self.lib.metric(1),0)

    def test_every_modified_token_byte_and_truncation_is_rejected_without_a_handle(self):
        _,token=self.issue()
        for size in range(len(token)):
            e,h=self.consume(token[:size]);self.assertNotEqual(e,0);self.assertEqual(h,0x123)
        for i in range(len(token)):
            value=bytearray(token);value[i]=ord('A') if value[i]!=ord('A') else ord('B')
            self.assertNotEqual(self.consume(bytes(value))[0],0,i)
        self.assertEqual([self.lib.metric(i) for i in range(3)],[0,0,0])

    def test_real_resource_and_class_scope_are_authenticated_and_bounded(self):
        e,root_token=self.issue(self.request(0,b'/'));self.assertEqual(e,0)
        self.assertEqual(self.consume(root_token)[0],0,'preserve the installed TCCD root-resource/TCC-class ABI')
        self.assertNotEqual(self.issue(self.request(0,b'/',b'com.apple.app-sandbox.read-write'))[0],0)
        e,token=self.issue(self.request(0,b'/private/var/mobile/Media/PhotoData',b'com.apple.app-sandbox.read-write'))
        self.assertEqual(e,0);self.assertEqual(self.consume(token)[0],0)
        for path in [b'/etc',b'/private/var/mobile/MediaOther',b'/private/var/mobile/Media/../Library',
                     b'/private/var/mobile/Media//PhotoData',b'/private/var/mobile/Media/./PhotoData',b'relative']:
            self.assertNotEqual(self.issue(self.request(0,path,b'com.apple.app-sandbox.read-write'))[0],0,path)
        for q in [self.request(name=b'com.apple.tcc.'),self.request(name=b'arbitrary'),self.request(1,b'mach-service'),
                  self.request(resource=b'not-empty'),self.request(flags=1),self.request(flags=0x20000,version=1),
                  self.request(flags=0x10000),self.request(pid=247),self.request(version=1)]:
            self.assertNotEqual(self.issue(q)[0],0)

    def test_maximum_native_payload_fits_the_installed_2048byte_output_allocation(self):
        name=b'com.apple.tcc.'+b'x'*(159-14)
        root=b'/private/var/mobile/Media/'
        path=root+b'p'*(1023-len(root))
        e,token=self.issue(self.request(0,path,name));self.assertEqual(e,0)
        self.assertLessEqual(len(token),2048);self.assertEqual(self.consume(token)[0],0)

    def test_real_mac_or_entropy_failures_never_turn_into_success(self):
        for kind in [0,1]:
            self.lib.fault(kind,1);self.assertNotEqual(self.issue()[0],0);self.lib.fault(kind,0)
        e,token=self.issue();self.assertEqual(e,0)
        for kind in [0,1]:
            self.lib.fault(kind,1);e,h=self.consume(token);self.assertNotEqual(e,0);self.assertEqual(h,0x123);self.lib.fault(kind,0)
        self.lib.fault(2,1);self.assertNotEqual(self.consume(token)[0],0,'another boot key cannot authenticate a retained token')
        self.assertEqual(self.lib.metric(0),0)

    def test_reference_exhaustion_is_bounded_and_process_exit_recovers_capacity(self):
        _,token=self.issue()
        for _ in range(2048):self.assertEqual(self.consume(token)[0],0)
        self.assertNotEqual(self.consume(token)[0],0);self.assertEqual(self.lib.metric(1),2048)
        self.lib.exited(C.byref(self.client));self.assertEqual([self.lib.metric(i) for i in range(3)],[0,0,0])
        self.assertEqual(self.consume(token)[0],0)

    def test_parallel_consumers_preserve_ownership_and_cleanup(self):
        e,token=self.issue();self.assertEqual(e,0)
        def run(index):
            owner=Actor(1000+index,1,501,0)
            for _ in range(120):
                e,h=self.consume(token,owner)
                if e:return e
                e=self.lib.release(C.byref(owner),h)
                if e:return e
            self.lib.exited(C.byref(owner));return 0
        with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(list(pool.map(run,range(8))),[0]*8)
        self.assertEqual([self.lib.metric(i) for i in range(3)],[0,0,0])
