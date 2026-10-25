"""The native TLS table and QuartzCore's macro table have different bases."""
from pathlib import Path
import ctypes
import shutil
import struct
import subprocess
import tempfile
import unittest

from ports.redfin.graphics_abi import decode_gl_wrapper
from ports.redfin.gui_profile import REQUIRED


class GraphicsABITests(unittest.TestCase):
    def stub(self,slot=0x78,context=0x20):
        # Actual A64 instruction forms, with different context/function bases.
        return struct.pack('<8I',0xd53bd068,0xf9407908,0xb40000a8,0xaa0003e1,
            0xf9400002 | ((slot//8)<<10) | (8<<5),
            0xf9400000 | ((context//8)<<10) | (8<<5),0xd61f0040,0xd65f03c0)

    def test_gl_clear_slot_is_relative_to_native_context_before_macro_prefix(self):
        layout=decode_gl_wrapper(self.stub())
        self.assertEqual(layout,dict(native_slot=0x78,context_offset=32,tls_offset=240))
        self.assertEqual(layout['native_slot']-layout['context_offset'],0x58)

    def test_different_argument_registers_and_context_loaded_over_table_register(self):
        words=[0xd53bd068,0xf9407908,0xb4000108,0xf9496d03,0xf9401108,
               0x2a0003e9,0x2a0103e2,0xaa0803e0,0xaa0903e1,0xd61f0060]
        layout=decode_gl_wrapper(struct.pack('<10I',*words))
        self.assertEqual(layout['context_offset'],32)
        self.assertEqual(layout['native_slot']-32,0x12b8)

    def test_missing_context_or_branch_is_refused(self):
        for raw in (self.stub()[:20],self.stub()[:24],struct.pack('<I',0xd65f03c0),b'x'):
            with self.assertRaises(ValueError):decode_gl_wrapper(raw)


class GraphicsAMFITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('host C compiler absent')
        cls.temp=tempfile.TemporaryDirectory();root=Path(__file__).resolve().parent
        text=(root/'graphics-amfi.inc').read_text()
        function='static int\nredfin_graphics_amfi_syscall'+text.split('static int\nredfin_graphics_amfi_syscall',1)[1].split('static const struct mac_policy_ops',1)[0]
        source=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "gui-profile.h"
#include "graphics-exec-scope.h"
#define ENOPOLICY 103
#ifndef __APPLE__
typedef uint64_t user_addr_t;
#endif
struct proc {int pid;};
static const char *boot_args,*process_name;
static int input_error,output_error;
static unsigned copies,references;
static const char *PE_boot_args(void){return boot_args;}
static int proc_pid(struct proc *p){return p->pid;}
typedef struct vnode {int value;} *vnode_t;
static struct vnode executable;
static vnode_t proc_getexecutablevnode(struct proc *p){(void)p;if(!strcmp(process_name,"missing-vnode"))return NULL;
 references++;return &executable;}
static int vnode_put(vnode_t v){if(v!=&executable || references!=1)__builtin_trap();references--;return 0;}
static int vn_getpath(vnode_t v,char *out,int *bytes){(void)v;if(!strcmp(process_name,"path-error"))return 14;
 const char *name=!strcmp(process_name,"backboardd")?"/usr/libexec/backboardd":process_name;
 int n=snprintf(out,(unsigned)*bytes,"%s%s",name[0]=='/'?"":"/tmp/",name);
 if(n<0 || n>=*bytes)return 63;*bytes=n+1;return 0;}
static int copyin(user_addr_t from,void *to,unsigned bytes){if(input_error)return input_error;memcpy(to,(void *)from,bytes);return 0;}
static int copyout(const void *from,user_addr_t to,unsigned bytes){copies++;if(output_error)return output_error;memcpy((void *)to,from,bytes);return 0;}
'''+function+r'''
int invoke(const char *args,const char *name,int call,int in_error,int out_error,uint64_t *flags){
    boot_args=args;process_name=name;input_error=in_error;output_error=out_error;copies=references=0;
    struct proc p={42};struct {uint64_t input;user_addr_t output;} q={0,(user_addr_t)flags};
    return redfin_graphics_amfi_syscall(&p,call,(user_addr_t)&q);
}
unsigned copy_count(void){return copies;}
unsigned reference_count(void){return references;}
'''
        directory=Path(cls.temp.name);(directory/'adapter.c').write_text(source)
        compile=subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror','-I',str(root),
            str(directory/'adapter.c'),'-o',str(directory/'adapter.so')],capture_output=True,text=True)
        if compile.returncode:raise RuntimeError(compile.stderr)
        cls.lib=ctypes.CDLL(str(directory/'adapter.so'))
        cls.lib.invoke.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,
                                ctypes.POINTER(ctypes.c_uint64)]
        cls.lib.invoke.restype=ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'temp'):cls.temp.cleanup()

    def args(self,mode=3):
        # Reuse the same exact profile text as image construction.
        flags=sorted(REQUIRED-{'redfingui=1','sweetfb_hz=10'})
        return (' '.join(flags+[f'redfingui={mode}','redfinfit=2','sweetfb_hz=60',
            'redfinbootid=0x020afecf22835a8c'])).encode()

    def call(self,args,name=b'backboardd',number=0x5a,input_error=0,output_error=0):
        flags=ctypes.c_uint64(0x1234)
        result=self.lib.invoke(args,name,number,input_error,output_error,ctypes.byref(flags))
        self.assertEqual(self.lib.reference_count(),0)
        return result,flags.value,self.lib.copy_count()

    def test_other_processes_profiles_or_requests_retain_no_policy(self):
        for args,name,number in ((self.args(1),b'backboardd',0x5a),(self.args(2),b'backboardd',0x5a),
            (self.args(),b'SpringBoard',0x5a),(self.args(),b'backboardd',0x60),
            (self.args()+b' gpu=1',b'backboardd',0x5a)):
            self.assertEqual(self.call(args,name,number),(103,0x1234,0))

    def test_exact_gui3_backboardd_gets_native_flags_and_copy_errors_propagate(self):
        self.assertEqual(self.call(self.args()),(0,0xff,1))
        self.assertEqual(self.call(self.args(),input_error=14),(14,0x1234,0))
        self.assertEqual(self.call(self.args(),output_error=14),(14,0x1234,1))

    def test_fullscreen_system_apps_need_their_actual_vnode_path(self):
        full=self.args().replace(b'redfinfit=2',b'redfinfit=1')
        path=b'/System/Library/CoreServices/SpringBoard.app/SpringBoard'
        self.assertEqual(self.call(full,path),(0,0xff,1))
        self.assertEqual(self.call(self.args(),path),(103,0x1234,0))
        for bad in [b'/tmp/SpringBoard',b'/Applications/MobilePhone.app/PlugIns/extension',b'SpringBoard']:
            self.assertEqual(self.call(full,bad),(103,0x1234,0))

    def test_missing_failed_and_oversize_vnode_paths_release_their_native_iocount(self):
        for path in [b'missing-vnode',b'path-error',b'/'+b'a'*300]:
            self.assertEqual(self.call(self.args(),path),(103,0x1234,0))

    def test_native_daemon_observation_requires_its_exact_vnode_and_capture_profile(self):
        capture=self.args()+b' redfinscreen=1'
        for path in (b'/System/Library/Frameworks/AssetsLibrary.framework/Support/assetsd',
                     b'/System/Library/PrivateFrameworks/TCC.framework/Support/tccd'):
            self.assertEqual(self.call(capture,path),(0,0xff,1))
            self.assertEqual(self.call(self.args(),path),(103,0x1234,0))
            for arguments in (self.args(1)+b' redfinscreen=1',self.args(2)+b' redfinscreen=1',
                              capture+b' redfinscreen=1',capture+b' gpu=1'):
                self.assertEqual(self.call(arguments,path),(103,0x1234,0))
        for wrong in (b'assetsd',b'/tmp/assetsd',path+b'-other',b'/tmp/tccd',b'tccd',
                      b'/System/Library/PrivateFrameworks/TCC.framework/Support/tccd/plugin'):
            self.assertEqual(self.call(capture,wrong),(103,0x1234,0))


if __name__=='__main__':unittest.main()
