"""Compile and execute the actual md0 native Wi-Fi observer with fake IOKit."""
import ctypes as C
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import wifi_platform as P
from test_rpmh_probe import added_file, database
from test_wifi_smem import fixture as smem_fixture

HERE = Path(__file__).resolve().parent

HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include "wifi_aop.h"
#include "wifi_smem.h"
#include "redfin_rpmh.h"
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t DTEntry;
typedef uint64_t IOOptionBits;
enum {kIODirectionIn=1, kIOMapReadOnly=0x100, kIOMapInhibitCache=0x200, kIOMapWriteCombineCache=0x400};
alignas(16) static uint8_t aop[0x1000],smem[REDFIN_SMEM_BYTES],db[RF_CMDDB_BYTES];
static uint64_t ranges[6],ram_base,ram_bytes,boot_id;
static uint32_t witness[12],marker;
static int enabled,cpus,spmi,returned,ready,modem,wifi,gpu,usb,gui,smp,wifi_mode;
static int bad_board,bad_node,bad_length,fail_descriptor,fail_mapping,short_mapping,null_mapping;
static unsigned descriptors,mappings,created_memory,created_maps,released_memory,released_maps,unsafe;
static unsigned proof_calls,lose_proof;
static uint32_t *attempt_pointer;
static char root[16],output[8192];
static size_t output_used;
static void IOLog(const char *format,...) {
    va_list args;va_start(args,format);
    int count=vsnprintf(output+output_used,sizeof(output)-output_used,format,args);
    va_end(args);
    if(count>0 && (size_t)count<sizeof(output)-output_used)output_used+=(size_t)count;
}
static int PE_parse_boot_argn(const char *key,void *out,int size) {
    int value;
    if(!strcmp(key,"rd")){if(size!=16)return 0;memcpy(out,root,16);return 1;}
    if(!strcmp(key,"redfinbootid")){if(size!=8)return 0;memcpy(out,&boot_id,8);return 1;}
    if(!strcmp(key,"redfinwifinative"))value=enabled;
    else if(!strcmp(key,"redfinwifi"))value=wifi_mode;
    else if(!strcmp(key,"cpus"))value=cpus;
    else if(!strcmp(key,"redfinspmi"))value=spmi;
    else if(!strcmp(key,"redfinreturn"))value=returned;
    else if(!strcmp(key,"modem"))value=modem;
    else if(!strcmp(key,"wifi"))value=wifi;
    else if(!strcmp(key,"gpu"))value=gpu;
    else if(!strcmp(key,"sweetusb"))value=usb;
    else if(!strcmp(key,"redfingui"))value=gui;
    else if(!strcmp(key,"redfinsmp"))value=smp;
    else return 0;
    if(size!=4)return 0;
    memcpy(out,&value,4);return 1;
}
extern "C" int redfin_spmi_return_ready(void) {
    ++proof_calls;return ready && (!lose_proof || proof_calls<lose_proof);
}
static int SecureDTLookupEntry(void *,const char *path,DTEntry *out) {
    if(!strcmp(path,"/")){*out=1;return 0;}
    if(!strcmp(path,"/chosen")){*out=2;return 0;}
    if(!strcmp(path,"/redfin-wifi-native") && !bad_node){*out=3;return 0;}
    return 1;
}
static int SecureDTGetProperty(DTEntry entry,const char *key,const void **out,unsigned *bytes) {
    static const char board[]="D22AP\0iPhone10,3\0google,redfin\0qcom,sm7250";
    static const char wrong[]="google,redfin-clone\0qcom,sm7250";
    if(entry==1 && !strcmp(key,"compatible")) {
        *out=bad_board ? wrong : board;*bytes=bad_board ? sizeof(wrong) : sizeof(board);return 0;
    }
    if(entry==2) {
        if(!strcmp(key,"dram-base"))*out=&ram_base;
        else if(!strcmp(key,"dram-size"))*out=&ram_bytes;
        else return 1;
        *bytes=8;return 0;
    }
    if(entry==3) {
        if(!strcmp(key,"reg")){*out=ranges;*bytes=sizeof(ranges)-(bad_length==1 ? 1 : 0);return 0;}
        if(!strcmp(key,"source-contract")){*out=witness;*bytes=sizeof(witness)-(bad_length==2 ? 1 : 0);return 0;}
        if(!strcmp(key,"live-fdt-verified")){*out=&marker;*bytes=4-(bad_length==3 ? 1 : 0);return 0;}
    }
    return 1;
}
class IOMemoryMap {
public:
    uintptr_t address;uint64_t bytes;unsigned index;
    uintptr_t getVirtualAddress(){return null_mapping==(int)index ? 0 : address;}
    uint64_t getLength(){return short_mapping==(int)index ? bytes-4 : bytes;}
    void release(){++released_maps;delete this;}
};
class IOMemoryDescriptor {
public:
    uintptr_t address;uint64_t bytes;unsigned index;
    static IOMemoryDescriptor *withPhysicalAddress(uint64_t physical,uint64_t size,int direction) {
        ++descriptors;
        if(fail_descriptor==(int)descriptors)return NULL;
        uintptr_t address=0;
        if(physical==RF_WIFI_AOP_PHYSICAL && size==RF_WIFI_AOP_BYTES)address=(uintptr_t)aop;
        if(physical==REDFIN_SMEM_PHYSICAL && size==REDFIN_SMEM_BYTES)address=(uintptr_t)smem;
        if(physical==0x80860000 && size==RF_CMDDB_BYTES)address=(uintptr_t)db;
        if(!address || direction!=kIODirectionIn){++unsafe;return NULL;}
        ++created_memory;
        IOMemoryDescriptor *result=new IOMemoryDescriptor;
        result->address=address;result->bytes=size;result->index=descriptors;return result;
    }
    IOMemoryMap *map(IOOptionBits options) {
        ++mappings;
        IOOptionBits expected=kIOMapReadOnly|(address==(uintptr_t)aop ? kIOMapInhibitCache : kIOMapWriteCombineCache);
        if(options!=expected){++unsafe;return NULL;}
        if(fail_mapping==(int)mappings)return NULL;
        ++created_maps;IOMemoryMap *result=new IOMemoryMap;
        result->address=address;result->bytes=bytes;result->index=index;return result;
    }
    void release(){++released_memory;delete this;}
};
#define OSSafeReleaseNULL(pointer) do{if(pointer){(pointer)->release();(pointer)=NULL;}}while(0)
static uint32_t wf_test_exchange(uint32_t *where,uint32_t value,int) {
    attempt_pointer=where;uint32_t old=*where;*where=value;return old;
}
#define __atomic_exchange_n wf_test_exchange
ACTUAL
#undef __atomic_exchange_n
extern "C" void reset(void) {
    if(attempt_pointer)*attempt_pointer=0;
    memset(aop,0,sizeof(aop));memset(smem,0,sizeof(smem));memset(db,0,sizeof(db));
    const uint64_t r[6]={RF_WIFI_AOP_PHYSICAL,RF_WIFI_AOP_BYTES,REDFIN_SMEM_PHYSICAL,REDFIN_SMEM_BYTES,0x80860000,RF_CMDDB_BYTES};
    const uint32_t w[12]={1,4,384,384,3,435,428,1,0,0x20002,1,3};
    memcpy(ranges,r,sizeof(r));memcpy(witness,w,sizeof(w));marker=1;
    ram_base=0x180000000;ram_bytes=0x80000000;boot_id=1234;
    enabled=cpus=spmi=returned=ready=1;modem=wifi=gpu=usb=gui=smp=0;
    wifi_mode=2;
    bad_board=bad_node=bad_length=fail_descriptor=fail_mapping=short_mapping=null_mapping=0;
    descriptors=mappings=created_memory=created_maps=released_memory=released_maps=unsafe=0;
    proof_calls=lose_proof=0;memset(root,0,sizeof(root));memcpy(root,"md0",3);
    memset(output,0,sizeof(output));output_used=0;
}
extern "C" void set_option(unsigned which,uint64_t value) {
    switch(which) {
    case 0:enabled=(int)value;break;case 1:cpus=(int)value;break;case 2:spmi=(int)value;break;
    case 3:returned=(int)value;break;case 4:ready=(int)value;break;case 5:modem=(int)value;break;
    case 6:wifi=(int)value;break;case 7:gpu=(int)value;break;case 8:usb=(int)value;break;
    case 9:gui=(int)value;break;case 10:smp=(int)value;break;case 11:bad_board=(int)value;break;
    case 12:bad_node=(int)value;break;case 13:bad_length=(int)value;break;
    case 14:fail_descriptor=(int)value;break;case 15:fail_mapping=(int)value;break;
    case 16:short_mapping=(int)value;break;case 17:null_mapping=(int)value;break;
    case 18:marker=(uint32_t)value;break;case 19:ram_base=value;break;case 20:ram_bytes=value;break;
    case 21:boot_id=value;break;case 22:lose_proof=(unsigned)value;break;
    case 23:memcpy(root,"ufsroot0",9);break;case 24:memset(root,'x',sizeof(root));break;
    case 25:wifi_mode=(int)value;break;
    }
}
extern "C" void mutate_range(unsigned index,uint64_t value){if(index<6)ranges[index]=value;}
extern "C" void mutate_witness(unsigned index,uint32_t value){if(index<12)witness[index]=value;}
extern "C" const char *get_output(void){return output;}
extern "C" uint8_t *get_region(unsigned which){return which==0 ? aop : which==1 ? smem : db;}
extern "C" unsigned metric(unsigned which) {
    const unsigned values[]={descriptors,mappings,created_memory,created_maps,released_memory,released_maps,unsafe,proof_calls};
    return which<8 ? values[which] : 0;
}
extern "C" int select_turbo(const uint16_t *levels,unsigned count) {
    if(count>16)return -2;rf_cmddb_resource resource={};resource.level_count=count;
    memcpy(resource.levels,levels,count*2);return wf_selector(&resource,384);
}
'''


class NativeWifiProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('host C++ compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        (cls.directory / 'redfin_rpmh.h').write_text(added_file('redfin_rpmh.h'))
        actual = '\n'.join(line for line in (HERE / 'wifi_native_probe.cpp').read_text().splitlines()
                           if not line.startswith('#include'))
        source = cls.directory / 'probe.cpp'
        source.write_text(HARNESS.replace('ACTUAL', actual))
        library = cls.directory / 'probe.so'
        subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(HERE), '-I', str(cls.directory), '-x', 'c++', str(source),
                        str(HERE / 'wifi_aop.c'), '-o', str(library)], check=True, capture_output=True)
        cls.library = C.CDLL(str(library))
        cls.library.set_option.argtypes = [C.c_uint, C.c_uint64]
        cls.library.mutate_range.argtypes = [C.c_uint, C.c_uint64]
        cls.library.mutate_witness.argtypes = [C.c_uint, C.c_uint32]
        cls.library.get_output.restype = C.c_char_p
        cls.library.get_region.restype = C.c_void_p
        cls.library.select_turbo.argtypes = [C.POINTER(C.c_uint16), C.c_uint]

    def setUp(self):
        self.library.reset()
        aop = bytearray(4096)
        struct.pack_into('<16I', aop, 0, 0x4d41494c, 1, 0, 0xffff, 0xffff,
                         0xffff, 0xffff, 128, 0x600, 0xffff, 0xffff, 0xffff, 0xffff,
                         128, 0x800, 0)
        C.memmove(self.library.get_region(0), bytes(aop), len(aop))
        smem = bytes(smem_fixture(False))
        C.memmove(self.library.get_region(1), smem, len(smem))
        db = database()
        db[144 + 3 * 24:144 + 3 * 24 + 8] = b'mss.lvl\0'
        C.memmove(self.library.get_region(2), bytes(db), len(db))

    def run_probe(self):
        before = [hashlib.sha256(C.string_at(self.library.get_region(i), size)).digest()
                  for i, size in enumerate((4096, 0x200000, 0x20000))]
        self.library.redfin_wifi_native_observe()
        after = [hashlib.sha256(C.string_at(self.library.get_region(i), size)).digest()
                 for i, size in enumerate((4096, 0x200000, 0x20000))]
        self.assertEqual(after, before, 'probe must not modify AOP/SMEM/CMD-DB')
        self.assertEqual(self.library.metric(6), 0, 'only exact read-only mappings allowed')
        self.assertEqual(self.library.metric(2), self.library.metric(4), 'every descriptor must release')
        self.assertEqual(self.library.metric(3), self.library.metric(5), 'every map must release')
        return self.library.get_output().decode()

    def test_probe_executes_real_parsers_and_reports_all_native_prerequisites(self):
        output = self.run_probe()
        self.assertIn('AOP raw status=0 magic=0x4d41494c version=1', output)
        self.assertIn('AOP observation status=0 pending_tx=0 pending_rx=0', output)
        self.assertIn('SMEM status=0 partitions=1 modem=1', output)
        self.assertIn('resource xo.lvl status=0', output)
        self.assertIn('resource cx.lvl status=0', output)
        self.assertIn('resource mss.lvl status=0', output)
        self.assertIn('mss.lvl raw_AUX=[0,48,128,384]', output)
        self.assertIn('TURBO_selector=3', output)
        self.assertIn('no PAS/power/SMEM writes or notifications', output)
        self.assertEqual((self.library.metric(0), self.library.metric(1)), (3, 3))

    def test_md0_up_identity_and_return_failures_map_nothing(self):
        cases = [(0, 0), (0, 2), (1, 8), (2, 0), (3, 0), (4, 0), (5, 1), (6, 1),
                 (7, 1), (8, 2), (9, 1), (10, 1), (11, 1), (12, 1), (18, 0),
                 (19, 0), (19, 0x80860000), (20, 0), (21, 0), (23, 1), (24, 1), (25, 1), (25, 0)]
        for option, value in cases:
            self.setUp()
            self.library.set_option(option, value)
            with self.subTest(option=option, value=value):
                output = self.run_probe()
                self.assertEqual(self.library.metric(0), 0)
                if option != 0:
                    self.assertIn('refused', output)

    def test_exact_all_adt_values_lengths_and_physical_ranges_are_mandatory(self):
        for index, expected in enumerate(P.WITNESS):
            self.setUp()
            self.library.mutate_witness(index, expected ^ 1)
            with self.subTest(witness=index):
                self.assertIn('refused', self.run_probe())
                self.assertEqual(self.library.metric(0), 0)
        for index, expected in enumerate(value for pair in P.PROBE_RANGES for value in pair):
            self.setUp()
            self.library.mutate_range(index, expected ^ 4)
            with self.subTest(range=index):
                self.assertIn('refused', self.run_probe())
                self.assertEqual(self.library.metric(0), 0)
        for length in (1, 2, 3):
            self.setUp()
            self.library.set_option(13, length)
            with self.subTest(length=length):
                self.assertIn('refused', self.run_probe())
                self.assertEqual(self.library.metric(0), 0)

    def test_each_mapping_failure_releases_every_acquired_object(self):
        for option in (14, 15, 16, 17):
            for failure in (1, 2, 3):
                self.setUp()
                self.library.set_option(option, failure)
                with self.subTest(option=option, failure=failure):
                    self.assertIn('mapping/return check failed', self.run_probe())

    def test_malformed_aop_descriptor_still_reports_raw_values_without_indirect_reads(self):
        for offset, value in ((0, 0), (4, 2), (8, 1), (0x38, 0xfffffff0), (0x34, 4096)):
            self.setUp()
            C.memmove(self.library.get_region(0) + offset, struct.pack('<I', value), 4)
            with self.subTest(offset=offset):
                output = self.run_probe()
                self.assertIn('AOP observation status=3', output)
                self.assertIn('AOP raw status=0', output)
                self.assertIn('resource mss.lvl', output)

    def test_pending_aop_message_is_reported_and_preserved(self):
        C.memmove(self.library.get_region(0) + 0x800, struct.pack('<I', 64), 4)
        output = self.run_probe()
        self.assertIn('pending_tx=64', output)
        self.assertNotIn('refused', output)

    def test_return_lease_loss_ends_observation_and_releases_maps(self):
        self.library.set_option(22, 25)
        output = self.run_probe()
        self.assertIn('AOP observation status=2', output)
        self.assertNotIn('SMEM status=', output)
        self.assertNotIn('resource ', output)

    def test_observer_only_attempts_once_including_after_mapping_failure(self):
        self.library.set_option(15, 2)
        self.run_probe()
        before = self.library.metric(0), self.library.metric(1)
        self.library.set_option(15, 0)
        self.run_probe()
        self.assertEqual((self.library.metric(0), self.library.metric(1)), before)

    def test_arc_selector_uses_consumer_table_and_refuses_ambiguous_padding(self):
        for values, expected in [((0, 48, 128, 384), 3), ((0, 48, 384, 416, 0, 0), 2),
                                 ((0, 48, 256, 416), 3), ((0, 48, 128), -1),
                                 ((16, 48, 384), -1), ((0, 384, 0, 416), -1),
                                 ((0, 384, 384), -1), ((), -1)]:
            array = (C.c_uint16 * len(values))(*values)
            with self.subTest(values=values):
                self.assertEqual(self.library.select_turbo(array, len(values)), expected)

    def test_kernel_overlay_exports_the_exact_probe_and_entry_header(self):
        patch = (HERE / 'wifi-native-probe.patch').read_text()
        for source, destination in [('wifi_native_probe.cpp', 'RedfinWiFiProbe.cpp'),
                                    ('wifi_native_probe.h', 'redfin_wifi_native_probe.h')]:
            section = patch.split('+++ b/iokit/Kernel/arm/' + destination + '\n', 1)[1]
            section = section.split('diff --git ', 1)[0]
            actual = ''.join(line[1:] for line in section.splitlines(keepends=True) if line.startswith('+'))
            self.assertEqual(actual, (HERE / source).read_text())


if __name__ == '__main__':
    unittest.main()
