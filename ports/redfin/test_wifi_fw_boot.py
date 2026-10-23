"""Run the actual native boot-blob adapter with real guarded source storage."""
import ctypes as C
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings

import wifi_fw_blob as B
from test_wifi_firmware import REGION, SHA, bundle, sha256
from test_wifi_fw_source import HARNESS as SOURCE_HARNESS, private_bundle
from test_loader import mock_kernel
from tools import mkpayload

HERE = Path(__file__).resolve().parent

FIXTURE_API = r'''
const struct rf_wifi_fw_blob *fixture_blob(void){return &blob;}
const struct rf_wifi_fw_layout *fixture_layout(void){return &layout;}
const uint8_t *fixture_data(void){return source_bytes;}
struct redfin_mpss_workspace *fixture_workspace(void){return &workspace;}
const struct rf_wifi_fw_copy_ops *fixture_copy_ops(void){return &copy_ops;}
uint8_t *fixture_readback(void){return readback;}
void fixture_phase(unsigned value){phase=value;}
int fixture_hash(const uint8_t *data,size_t bytes,uint8_t output[32]){return selected_hash(NULL,data,bytes,output);}
'''

HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include "wifi_fw_boot.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t DTEntry;
typedef uintptr_t vm_offset_t;
typedef void *thread_t;
enum {kIODirectionIn=1,kIOMapReadOnly=0x100,kIOMapDefaultCache=0x200};
struct boot_args {
 uint16_t Revision,Version;uint64_t virtBase,physBase,memSize,topOfKernelData,video[6];
 uint32_t machineType;void *deviceTreeP;uint32_t deviceTreeLength;char CommandLine[608];
 uint64_t bootFlags,memSizeActual;
};
extern "C" {
const struct rf_wifi_fw_blob *fixture_blob(void);
const struct rf_wifi_fw_layout *fixture_layout(void);
const uint8_t *fixture_data(void);
struct redfin_mpss_workspace *fixture_workspace(void);
const struct rf_wifi_fw_copy_ops *fixture_copy_ops(void);
uint8_t *fixture_readback(void);
void fixture_phase(unsigned);
int fixture_hash(const uint8_t *,size_t,uint8_t[32]);
}
static boot_args args;
static struct {void *bootArgs;} PE_state;
static unsigned ready,owner,register_issue,bad_board,bad_node,bad_length,policy_live,policy_calls,lose_policy;
static unsigned descriptor_failure,map_failure,null_mapping,short_mapping,descriptors,mappings,released_descriptors,released_maps,unsafe;
static unsigned mode_cpus,mode_spmi,mode_return,mode_modem,mode_wifi,mode_gpu,mode_usb;
static uint64_t nonce,reg[2],bundle_bytes,chosen_base,chosen_bytes,memory_pair[2],ramdisk[2];
static uint32_t source_contract[4];static uint8_t digest[32];
static vm_offset_t vm_kernel_top;
static thread_t current_thread(void){return (thread_t)(uintptr_t)owner;}
static uint64_t register_value(const char *key){return !strcmp(key,"CurrentEL") ? (register_issue==1 ? 0 : 4) : (register_issue==2 ? 1 : 0);}
#define __builtin_arm_rsr64 register_value
static vm_offset_t ml_static_vtop(vm_offset_t address) {
 return address>=args.virtBase && address-args.virtBase<args.memSize ? args.physBase+address-args.virtBase : 0;
}
extern "C" int redfin_spmi_return_ready(void){return ready==1;}
extern "C" int redfin_mpss_kernel_sha256(void *,const uint8_t *data,size_t bytes,uint8_t out[32]){return fixture_hash(data,bytes,out);}
static int PE_parse_boot_argn(const char *key,void *output,int bytes) {
 if(!strcmp(key,"redfinbootid")){if(bytes!=8)return 0;memcpy(output,&nonce,8);return 1;}
 if(!strcmp(key,"rd")){if(bytes!=16)return 0;memset(output,0,16);memcpy(output,"md0",3);return 1;}
 unsigned value;
 if(!strcmp(key,"cpus"))value=mode_cpus;
 else if(!strcmp(key,"redfinspmi"))value=mode_spmi;
 else if(!strcmp(key,"redfinreturn"))value=mode_return;
 else if(!strcmp(key,"modem"))value=mode_modem;
 else if(!strcmp(key,"wifi"))value=mode_wifi;
 else if(!strcmp(key,"gpu"))value=mode_gpu;
 else if(!strcmp(key,"sweetusb"))value=mode_usb;
 else return 0;
 if(bytes!=4)return 0;memcpy(output,&value,4);return 1;
}
static int SecureDTLookupEntry(void *,const char *path,DTEntry *out) {
 if(!strcmp(path,"/")){*out=1;return 0;}
 if(!strcmp(path,"/chosen")){*out=2;return 0;}
 if(!strcmp(path,"/chosen/memory-map")){*out=3;return 0;}
 if(!strcmp(path,"/redfin-wifi-fw") && !bad_node){*out=4;return 0;}
 return 1;
}
static int SecureDTGetProperty(DTEntry entry,const char *key,const void **out,unsigned *bytes) {
 static const char board[]="google,redfin\0qcom,sm7250";
 static const char wrong[]="google,other\0qcom,sm7250";
 if(entry==1 && !strcmp(key,"compatible")){*out=bad_board ? wrong : board;*bytes=bad_board ? sizeof(wrong) : sizeof(board);return 0;}
 if(entry==2) {
  if(!strcmp(key,"dram-base"))*out=&chosen_base;
  else if(!strcmp(key,"dram-size"))*out=&chosen_bytes;
  else return 1;
  *bytes=8;return 0;
 }
 if(entry==3) {
  if(!strcmp(key,"RedfinWiFiFirmware")){*out=memory_pair;*bytes=16-(bad_length==5 ? 1 : 0);return 0;}
  if(!strcmp(key,"RAMDisk") && (ramdisk[0] || ramdisk[1])){*out=ramdisk;*bytes=16;return 0;}
 }
 if(entry==4) {
  if(!strcmp(key,"reg")){*out=reg;*bytes=16-(bad_length==1 ? 1 : 0);return 0;}
  if(!strcmp(key,"bundle-bytes")){*out=&bundle_bytes;*bytes=8-(bad_length==2 ? 1 : 0);return 0;}
  if(!strcmp(key,"bundle-sha256")){*out=digest;*bytes=32-(bad_length==3 ? 1 : 0);return 0;}
  if(!strcmp(key,"source-contract")){*out=source_contract;*bytes=16-(bad_length==4 ? 1 : 0);return 0;}
 }
 return 1;
}
class IOMemoryMap {
public:
 uintptr_t getVirtualAddress(){return null_mapping ? 0 : (uintptr_t)fixture_data();}
 uint64_t getLength(){return reg[1]-(short_mapping ? 4 : 0);}
 void release(){++released_maps;delete this;}
};
class IOMemoryDescriptor {
public:
 static IOMemoryDescriptor *withPhysicalAddress(uint64_t physical,uint64_t bytes,int direction) {
  if(descriptor_failure)return NULL;
  if(physical!=reg[0] || bytes!=reg[1] || direction!=kIODirectionIn){++unsafe;return NULL;}
  ++descriptors;return new IOMemoryDescriptor;
 }
 IOMemoryMap *map(unsigned options) {
  if(map_failure)return NULL;
  if(options!=(kIOMapReadOnly|kIOMapDefaultCache)){++unsafe;return NULL;}
  ++mappings;return new IOMemoryMap;
 }
 void release(){++released_descriptors;delete this;}
};
#define OSSafeReleaseNULL(pointer) do{if(pointer){(pointer)->release();(pointer)=NULL;}}while(0)
ACTUAL
static rf_wifi_fw_boot boot;
static const redfin_mpss_range exclusions[]={{0x180000000ULL,0x80000000ULL},{0xa0000000ULL,0x2300000ULL},{0xb7e41000ULL,0x400000ULL}};
static int policy_check(void *context,uint64_t id) {
 ++policy_calls;if(lose_policy && policy_calls>=lose_policy)policy_live=0;
 return context==&boot && policy_live && id==nonce ? 0 : -91;
}
extern "C" void native_reset(void) {
 memset(&boot,0,sizeof(boot));memset(&args,0,sizeof(args));
 const rf_wifi_fw_blob *b=fixture_blob();const rf_wifi_fw_layout *l=fixture_layout();
 args.Revision=args.Version=2;args.virtBase=0xfffffe0006000000ULL;
 args.physBase=l->ram.base;args.memSize=args.memSizeActual=l->ram.bytes;args.topOfKernelData=l->top;
 args.deviceTreeP=(void *)(uintptr_t)(args.virtBase+l->adt.base-args.physBase);args.deviceTreeLength=(uint32_t)l->adt.bytes;
 strcpy(args.CommandLine,"cpus=1 rd=md0 modem=0 wifi=0 gpu=0 sweetusb=0 redfinspmi=1 redfinreturn=1 redfinbootid=0x1");
 PE_state.bootArgs=&args;vm_kernel_top=args.virtBase+l->kernel_end-args.physBase;
 reg[0]=memory_pair[0]=b->physical;reg[1]=memory_pair[1]=b->reserved;
 bundle_bytes=b->bytes;memcpy(digest,b->sha256,32);chosen_base=l->ram.base;chosen_bytes=l->ram.bytes;
 source_contract[0]=1;source_contract[1]=4;source_contract[2]=16384;source_contract[3]=0x10000000;
 ramdisk[0]=l->ramdisk.base;ramdisk[1]=l->ramdisk.bytes;nonce=b->boot_id;ready=owner=policy_live=mode_cpus=mode_spmi=mode_return=1;
 register_issue=bad_board=bad_node=bad_length=policy_calls=lose_policy=0;
 descriptor_failure=map_failure=null_mapping=short_mapping=descriptors=mappings=released_descriptors=released_maps=unsafe=0;
 mode_modem=mode_wifi=mode_gpu=mode_usb=0;
}
extern "C" int native_open(void){const rf_wifi_fw_boot_policy policy={&boot,policy_check,exclusions,3};return redfin_wifi_fw_boot_open(&boot,fixture_workspace(),&policy);}
extern "C" int native_bad_workspace(void){const rf_wifi_fw_boot_policy policy={&boot,policy_check,exclusions,3};return redfin_wifi_fw_boot_open(&boot,(redfin_mpss_workspace *)&boot,&policy);}
extern "C" int native_metadata(void){fixture_phase(RF_WIFI_FW_METADATA);return rf_wifi_fw_copy_metadata(&boot.source,&boot.source_ops,fixture_copy_ops(),fixture_readback(),65536);}
extern "C" int native_segments(void){fixture_phase(RF_WIFI_FW_SEGMENTS);return rf_wifi_fw_copy_segments(&boot.source,&boot.source_ops,fixture_copy_ops(),fixture_readback(),65536);}
extern "C" void native_close(void){redfin_wifi_fw_boot_close(&boot);}
extern "C" void native_command(const uint8_t command[608]){memcpy(args.CommandLine,command,608);}
extern "C" void native_property(unsigned which,const uint8_t *data,unsigned bytes) {
 if(which==0 && bytes==16)memcpy(reg,data,16);
 if(which==1 && bytes==8)memcpy(&bundle_bytes,data,8);
 if(which==2 && bytes==32)memcpy(digest,data,32);
 if(which==3 && bytes==16)memcpy(source_contract,data,16);
 if(which==4 && bytes==16)memcpy(memory_pair,data,16);
}
extern "C" void native_option(unsigned which,uint64_t value) {
 switch(which) {
 case 0:ready=(unsigned)value;break;case 1:owner=(unsigned)value;break;case 2:register_issue=(unsigned)value;break;
 case 3:bad_board=(unsigned)value;break;case 4:bad_node=(unsigned)value;break;case 5:bad_length=(unsigned)value;break;
 case 6:policy_live=(unsigned)value;break;case 7:lose_policy=(unsigned)value;break;case 8:descriptor_failure=(unsigned)value;break;
 case 9:map_failure=(unsigned)value;break;case 10:null_mapping=(unsigned)value;break;case 11:short_mapping=(unsigned)value;break;
 case 12:reg[0]=value;break;case 13:reg[1]=value;break;case 14:bundle_bytes=value;break;case 15:memory_pair[0]=value;break;
 case 16:chosen_base=value;break;case 17:chosen_bytes=value;break;case 18:source_contract[1]=(uint32_t)value;break;
 case 19:nonce=value;break;case 20:args.CommandLine[0]=(char)value;break;case 21:args.topOfKernelData=value;break;
 case 22:mode_cpus=(unsigned)value;break;case 23:mode_modem=(unsigned)value;break;case 24:mode_wifi=(unsigned)value;break;
 case 25:mode_gpu=(unsigned)value;break;case 26:mode_usb=(unsigned)value;break;case 27:mode_return=(unsigned)value;break;
 case 28:mode_spmi=(unsigned)value;break;case 29:args.deviceTreeLength=(uint32_t)value;break;case 30:vm_kernel_top=(vm_offset_t)value;break;
 }
}
extern "C" uint64_t native_metric(unsigned which) {
 uint64_t values[]={descriptors,mappings,released_descriptors,released_maps,unsafe,policy_calls,boot.source.stage,
 boot.source.poisoned,boot.source.pinned,boot.source.metadata_written,boot.source.copied_bytes,boot.source.zeroed_bytes,
 boot.source.readback_bytes};
 return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
'''


class NativeWifiFirmwareBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c_compiler, cpp_compiler = shutil.which('cc'), shutil.which('c++')
        if not c_compiler or not cpp_compiler:
            raise unittest.SkipTest('host C/C++ compilers unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        fixture = directory / 'fixture.c'; fixture.write_text(SOURCE_HARNESS + FIXTURE_API)
        fixture_object = directory / 'fixture.o'
        subprocess.run([c_compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-I', str(HERE),
                        '-c', str(fixture), '-o', str(fixture_object)], check=True, capture_output=True)
        core = directory / 'core.o'
        subprocess.run([c_compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-I', str(HERE),
                        '-c', str(HERE / 'wifi_fw_source.c'), '-o', str(core)], check=True, capture_output=True)
        actual = '\n'.join(line for line in (HERE / 'wifi_fw_boot.cpp').read_text().splitlines() if not line.startswith('#include'))
        native = directory / 'native.cpp'; native.write_text(HARNESS.replace('ACTUAL', actual))
        library = directory / 'native.so'
        result = subprocess.run([cpp_compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                                 '-I', str(HERE), str(native), str(fixture_object), str(core), '-o', str(library)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.library = C.CDLL(str(library))
        cls.library.configure.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, SHA, C.c_size_t]
        cls.library.native_option.argtypes = [C.c_uint, C.c_uint64]
        cls.library.change_layout.argtypes = [C.c_uint, C.c_uint64]
        cls.library.native_command.argtypes = [C.c_void_p]
        cls.library.native_property.argtypes = [C.c_uint, C.c_void_p, C.c_uint]
        cls.library.native_metric.restype = C.c_uint64
        cls.library.metric.restype = C.c_uint64
        cls.addClassCleanup(cls.library.destroy)
        cls.addClassCleanup(cls.library.native_close)
        kernel, adt, ramdisk = [directory / name for name in ('kernel', 'device.adt', 'init')]
        kernel.write_bytes(mock_kernel())
        adt.write_bytes(B.mkadt.adt.serialize(B.mkadt.build(0x180000000, 0x80000000, seed=bytes(64))))
        ramdisk.write_bytes(b'private PID1 fixture')
        command = ('cpus=1 rd=md0 modem=0 wifi=0 gpu=0 sweetusb=0 redfinspmi=1 redfinreturn=1 '
                   'redfinbootid=0x0000000000000001')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            cls.payload, _info = mkpayload.build(kernel, adt, command, ramdisk)

    def setUp(self):
        self.library.native_close()
        self.configure(bundle(), 0x40000)

    def configure(self, data, storage):
        self.assertEqual(self.library.configure(data, len(data), hashlib.sha256(data).digest(), sha256, storage), 0)
        self.library.native_reset()

    def assert_closed(self):
        self.library.native_close()
        self.assertEqual(self.library.native_metric(0), self.library.native_metric(2))
        self.assertEqual(self.library.native_metric(1), self.library.native_metric(3))
        self.assertEqual(self.library.native_metric(4), 0)
        self.assertEqual(self.library.metric(4), 0)

    def report(self, data, digest):
        return {'schema': 1, 'bundle_bytes': len(data), 'bundle_sha256': digest,
                'assets': self.library.metric(13), 'memory_bytes': self.library.metric(14),
                'signature_authenticated': False, 'hardware_started': False}

    def adopt_payload(self, payload, report):
        offset, length = struct.unpack_from('<2Q', payload, 32)
        root, _end = B.mkadt.adt.parse(payload[offset:offset + length])
        node = next(child for child in root.children if child.name == 'redfin-wifi-fw')
        chosen = next(child for child in root.children if child.name == 'chosen')
        memory_map = next(child for child in chosen.children if child.name == 'memory-map')
        ramdisk = struct.unpack('<2Q', memory_map.prop('RAMDisk'))
        command = payload[72:680]
        nonce = next(word.split(b'=')[1] for word in command.split(b'\0', 1)[0].split() if word.startswith(b'redfinbootid='))
        for key, value in [(0, report['source_physical']), (3, int(nonce, 16)), (6, ramdisk[0]),
                           (7, report['adt_physical']), (8, length), (9, report['boot_args_physical']),
                           (10, 736), (11, report['top']), (12, ramdisk[0]), (13, ramdisk[1])]:
            self.library.change_layout(key, value)
        self.library.native_reset()
        self.library.native_command(command)
        for which, data in [(0, node.prop('reg')), (1, node.prop('bundle-bytes')),
                            (2, node.prop('bundle-sha256')), (3, node.prop('source-contract')),
                            (4, memory_map.prop('RedfinWiFiFirmware'))]:
            self.library.native_property(which, data, len(data))

    def test_real_native_read_only_mapping_invokes_actual_planner_and_guarded_copy(self):
        self.assertEqual(self.library.native_open(), 0)
        self.assertEqual(self.library.native_metadata(), 0)
        self.assertEqual(self.library.native_segments(), 0)
        self.assertEqual(self.library.native_metric(6), 4)
        self.assertEqual(self.library.native_metric(10), 74100)
        self.assertEqual(self.library.native_metric(12), 276 + 0x16000)
        self.assert_closed()

    def test_actual_packer_adt_handoff_is_consumed_by_native_adapter(self):
        data = bundle(); digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(self.library.native_open(), 0)
        checked = self.report(data, digest)
        self.assert_closed()
        payload, report = B.pack(self.payload, data, digest, checked, 0x8000000)
        self.configure(data, 0x40000)
        self.adopt_payload(payload, report)
        self.assertEqual(self.library.native_open(), 0)
        self.assertEqual(self.library.native_metadata(), 0)
        self.assertEqual(self.library.native_segments(), 0)
        self.assert_closed()

    def test_native_identity_handoff_source_extent_and_profile_errors_map_nothing(self):
        self.assertEqual(self.library.native_bad_workspace(), 1)
        self.assertEqual(self.library.native_metric(0), 0)
        for option, value in [(0, 0), (1, 0), (2, 1), (2, 2), (3, 1), (4, 1),
                              (12, 0), (13, 16384), (14, 0), (15, 0), (16, 0), (17, 16384),
                              (18, 6), (19, 0), (21, 0), (22, 8), (23, 1), (24, 1), (25, 1),
                              (26, 1), (27, 0), (28, 0), (29, 0), (30, 0)]:
            self.setUp(); self.library.native_option(option, value)
            self.assertNotEqual(self.library.native_open(), 0, (option, value))
            self.assertEqual(self.library.native_metric(0), 0, (option, value))
            self.assert_closed()
        for length in range(1, 6):
            self.setUp(); self.library.native_option(5, length)
            self.assertNotEqual(self.library.native_open(), 0)
            self.assertEqual(self.library.native_metric(0), 0)

    def test_all_descriptor_and_mapping_failures_release_owned_objects(self):
        for option in range(8, 12):
            self.setUp(); self.library.native_option(option, 1)
            self.assertNotEqual(self.library.native_open(), 0)
            self.assert_closed()

    def test_loss_of_native_thread_cpu_return_bootargs_dt_or_policy_blocks_copy(self):
        for option, value in [(0, 0), (1, 2), (2, 1), (2, 2), (3, 1), (4, 1), (6, 0),
                              (12, 0), (15, 0), (18, 6), (19, 2), (20, ord('x'))]:
            self.setUp(); self.assertEqual(self.library.native_open(), 0)
            self.library.native_option(option, value)
            self.assertNotEqual(self.library.native_metadata(), 0, (option, value))
            self.assertEqual(self.library.metric(3), 0)
            self.assertEqual(self.library.native_metric(7), 1)
            self.assert_closed()

    def test_native_source_is_one_attempt_and_cancelled_mapping_remains_owned_until_close(self):
        self.assertEqual(self.library.native_open(), 0)
        self.assertEqual(self.library.native_open(), 3)
        self.library.native_option(6, 0)
        self.assertNotEqual(self.library.native_metadata(), 0)
        self.assertEqual(self.library.native_metric(8), 1)
        self.assert_closed()
        self.assertEqual(self.library.native_open(), 3)

    @unittest.skipUnless(os.environ.get('REDFIN_WIFI_PRIVATE_BUNDLE'), 'private bundle not requested')
    def test_private_verified_bundle_executes_native_boot_adapter_and_owned_copy(self):
        data, selected = private_bundle()
        self.configure(data, REGION)
        self.assertEqual(self.library.native_open(), 0)
        checked = self.report(data, selected['bundle_sha256'])
        self.assert_closed()
        original = Path(os.environ.get('REDFIN_WIFI_PRIVATE_PAYLOAD', 'ports/redfin/out/wifi-native-v1/payload.bin')).read_bytes()
        payload, report = B.pack(original, data, selected['bundle_sha256'], checked, 0x8000000)
        self.configure(data, REGION)
        self.adopt_payload(payload, report)
        self.assertEqual(self.library.native_open(), 0)
        self.assertEqual(self.library.native_metadata(), 0)
        self.assertEqual(self.library.native_segments(), 0)
        self.assertEqual([self.library.native_metric(i) for i in (9, 10, 11, 12)],
                         [9420, 99384626, 191553563, 9420 + 99384626 + 191553563])
        self.assert_closed()


if __name__ == '__main__':
    unittest.main()
