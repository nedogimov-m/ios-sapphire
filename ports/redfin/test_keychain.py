"""NIST AES wrap vectors and the real native AKS descriptor/persistence path."""
import ctypes as C
import errno
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from ports.redfin import keychain_material as material

HERE=Path(__file__).resolve().parent

AES=r'''
#include <CommonCrypto/CommonCryptor.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
struct aes_ctx_test {uint8_t key[32];unsigned length,calls,fail;};
static int test_block(void *opaque,const uint8_t in[16],uint8_t out[16],int decrypt){
 auto *c=(aes_ctx_test *)opaque;if(c->fail && ++c->calls==c->fail)return EIO;
 size_t bytes=0;return CCCrypt(decrypt?kCCDecrypt:kCCEncrypt,kCCAlgorithmAES,kCCOptionECBMode,
   c->key,c->length,NULL,in,16,out,16,&bytes) || bytes!=16 ? EIO : 0;
}
static int encrypt_block(void *c,const uint8_t in[16],uint8_t out[16]){return test_block(c,in,out,0);}
static int decrypt_block(void *c,const uint8_t in[16],uint8_t out[16]){return test_block(c,in,out,1);}
'''
NATIVE=r'''
#include <vector>
#include <algorithm>
#include <assert.h>
#define OSDynamicCast(type,object) ((type *)(object))
static void IOLog(const char *,...){}
typedef unsigned IOReturn;
enum {kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnNotReady=2,
 kIOReturnNotPermitted=3,kIOReturnNoSpace=4,kIOReturnUnderrun=5};
#define SWEET_AKS_SYSTEM_HANDLE 0
class OSData {public:std::vector<uint8_t> bytes;unsigned refs=1;
 OSData(const uint8_t *p,size_t n):bytes(p,p+n){} unsigned getLength(){return (unsigned)bytes.size();}
 void *getBytesNoCopy(){return bytes.data();}void retain(){++refs;}void release(){--refs;}};
class IORegistryEntry {public:OSData *data;bool block_remove=false;
 IORegistryEntry(OSData *d):data(d){}OSData *getProperty(const char *){return data;}
 void removeProperty(const char *){if(!block_remove)data=NULL;}};
static unsigned wire_prepares,wire_completes,wire_reads,wire_writes;
class Descriptor {public:uint8_t *data;size_t bytes;bool short_read=false,short_write=false;
 bool fail_prepare=false,fail_complete=false;unsigned wired=0;
 Descriptor(uint8_t *p,size_t n):data(p),bytes(n){}size_t getLength(){return bytes;}
 IOReturn prepare(){wire_prepares++;if(fail_prepare)return 7;assert(!wired);wired++;return 0;}
 IOReturn complete(){assert(wired==1);wire_completes++;wired--;return fail_complete?8:0;}
 size_t readBytes(size_t offset,void *out,size_t n){assert(wired);wire_reads++;if(offset>bytes || n>bytes-offset)return 0;
  if(short_read && n)--n;memcpy(out,data+offset,n);return n;}
 size_t writeBytes(size_t offset,const void *in,size_t n){assert(wired);wire_writes++;if(offset>bytes || n>bytes-offset)return 0;
  if(short_write && n)--n;memcpy(data+offset,in,n);return n;}};
typedef Descriptor IOMemoryDescriptor;
struct IOExternalMethodArguments {
 unsigned scalarInputCount=0,scalarOutputCount=0;uint64_t *scalarInput=NULL,*scalarOutput=NULL;
 Descriptor *structureInputDescriptor=NULL,*structureOutputDescriptor=NULL;
 const void *structureInput=NULL;void *structureOutput=NULL;
 size_t structureInputSize=0,structureOutputSize=0,structureOutputDescriptorSize=0;
};
typedef aes_ctx_test aes_encrypt_ctx;typedef aes_ctx_test aes_decrypt_ctx;
static int aes_encrypt_key(const uint8_t *p,int n,aes_encrypt_ctx *out){
 if(n!=16 && n!=24 && n!=32)return 1;memset(out,0,sizeof(*out));memcpy(out->key,p,n);out->length=n;return 0;}
static int aes_decrypt_key(const uint8_t *p,int n,aes_decrypt_ctx *out){return aes_encrypt_key(p,n,out);}
static int aes_encrypt_cbc(const uint8_t *in,const uint8_t *iv,unsigned n,uint8_t *out,aes_encrypt_ctx *c){
 static const uint8_t zero[16]={};if(n!=1 || memcmp(iv,zero,16))return 1;return encrypt_block(c,in,out);}
static int aes_decrypt_cbc(const uint8_t *in,const uint8_t *iv,unsigned n,uint8_t *out,aes_decrypt_ctx *c){
 static const uint8_t zero[16]={};if(n!=1 || memcmp(iv,zero,16))return 1;return decrypt_block(c,in,out);}
'''
WRAPPERS=r'''
extern "C" int kw(int unwrap,const uint8_t *key,unsigned key_bytes,const uint8_t *iv,
 const uint8_t *in,unsigned n,uint8_t *out,unsigned cap,unsigned fail){
 aes_ctx_test ctx={};memcpy(ctx.key,key,key_bytes);ctx.length=key_bytes;ctx.fail=fail;
 return unwrap?redfin_kw_unwrap(decrypt_block,&ctx,iv,in,n,out,cap):
  redfin_kw_wrap(encrypt_block,&ctx,iv,in,n,out,cap);
}
extern "C" unsigned prepare(const uint8_t *p,unsigned n,unsigned blocked){
 redfin_kc_ready=redfin_kc_attempted=false;redfin_kc_notified=false;
 memset(&redfin_kc_encrypt,0,sizeof(redfin_kc_encrypt));memset(&redfin_kc_decrypt,0,sizeof(redfin_kc_decrypt));
 OSData data(p,n);IORegistryEntry chosen(&data);chosen.block_remove=blocked;
 RedfinKeychainPrepare(&chosen);
 return (redfin_kc_ready?1u:0u)|(chosen.data?0u:2u)|(data.refs==1?4u:0u);
}
extern "C" unsigned transform(unsigned unwrap,uint8_t *in,unsigned n,unsigned key_class,unsigned handle,
 uint8_t *out,unsigned cap,unsigned flags,uint64_t *actual_class,unsigned *actual_bytes){
 uint64_t scalars[2]={handle,key_class};IOExternalMethodArguments a;
 a.scalarInput=scalars;a.scalarInputCount=flags&16?1:2;
 a.scalarOutput=actual_class;a.scalarOutputCount=flags&32?0:1;
 a.structureInput=in;a.structureInputSize=n;a.structureOutput=out;a.structureOutputSize=cap;
 Descriptor input(in,n),output(out,cap);input.short_read=flags&4;output.short_write=flags&8;
 input.fail_prepare=flags&64;output.fail_prepare=flags&128;
 input.fail_complete=flags&256;output.fail_complete=flags&512;
 wire_prepares=wire_completes=wire_reads=wire_writes=0;
 if(flags&1)a.structureInputDescriptor=&input;if(flags&2)a.structureOutputDescriptor=&output;
 unsigned result=redfin_kc_transform(&a,unwrap);
 assert(!input.wired && !output.wired);
 *actual_bytes=(unsigned)((flags&2)?a.structureOutputDescriptorSize:a.structureOutputSize);return result;
}
extern "C" unsigned descriptor_state(uint8_t *out,unsigned capacity,unsigned flags,unsigned *actual){
 Descriptor output(out,capacity);IOExternalMethodArguments a;
 a.structureOutputDescriptor=&output;output.fail_prepare=flags&1;output.short_write=flags&2;output.fail_complete=flags&4;
 wire_prepares=wire_completes=wire_reads=wire_writes=0;
 unsigned error=sweet_aks_device_state(&a);assert(!output.wired);
 *actual=(unsigned)a.structureOutputDescriptorSize;return error;
}
extern "C" unsigned wire_metric(unsigned i){unsigned values[]={wire_prepares,wire_completes,wire_reads,wire_writes};return i<4?values[i]:999;}
extern "C" unsigned config(uint8_t *out,unsigned cap,unsigned which){
 IOExternalMethodArguments a;a.structureOutput=out;a.structureOutputSize=cap;
 unsigned r=which?redfin_kc_bag_uuid(&a):redfin_kc_configuration(&a);
 return r?0:(unsigned)a.structureOutputSize;
}
'''


class KeychainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name)
        for name in ['libkern/c++/OSData.h','libkern/crypto/aes.h']:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('/* test declarations precede native include */\n')
        (root/'RedfinKeywrap.h').write_text((HERE/'include/redfin_keywrap.h').read_text())
        native=HERE.parents[1]/'research/redfin-build/dxb/xnu/iokit/Kernel/arm/SweetKeyStore.cpp'
        if not native.is_file():raise unittest.SkipTest('prepared native AKS helper required')
        text=native.read_text()
        helper='static IOReturn\nsweet_aks_struct_out'+text.split('static IOReturn\nsweet_aks_struct_out',1)[1].split('\n}\n',1)[0]+'\n}\n'
        der='static uint32_t\nsweet_aks_der_pair'+text.split('static uint32_t\nsweet_aks_der_pair',1)[1].split('\n}\n',1)[0]+'\n}\n'
        state='static IOReturn\nsweet_aks_device_state'+text.split('static IOReturn\nsweet_aks_device_state',1)[1].split('\n}\n',1)[0]+'\n}\n'
        source=root/'keychain.cpp';library=root/'keychain.dylib'
        native_state=re.search(r'^#define SWEET_AKS_LOCK_STATE\s+0x[0-9a-f]+$',text,re.M).group()
        source.write_text(AES+NATIVE+native_state+'\n'+(HERE/'keychain-runtime.inc').read_text()+helper+der+state+WRAPPERS)
        result=subprocess.run(['c++','-std=c++17','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-Wno-misleading-indentation','-I',str(root),str(source),'-o',str(library)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        cls.lib=C.CDLL(str(library));cls.lib.kw.argtypes=[C.c_int,C.c_void_p,C.c_uint,C.c_void_p,C.c_void_p,C.c_uint,C.c_void_p,C.c_uint,C.c_uint]
        cls.lib.prepare.argtypes=[C.c_void_p,C.c_uint,C.c_uint]
        cls.lib.transform.argtypes=[C.c_uint,C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_uint,C.c_uint,
            C.POINTER(C.c_uint64),C.POINTER(C.c_uint)]
        cls.lib.config.argtypes=[C.c_void_p,C.c_uint,C.c_uint]
        cls.lib.descriptor_state.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.POINTER(C.c_uint)]

    def kw(self,unwrap,key,iv,data,capacity=None,fail=0):
        size=capacity if capacity is not None else len(data)+(8 if not unwrap else -8)
        out=C.create_string_buffer(b'\x7c'*max(80,size),max(80,size)+1)
        result=self.lib.kw(unwrap,key,len(key),iv,data,len(data),out,size,fail)
        return result,bytes(out)[:size]

    def seed(self,changed=False):
        raw=(1).to_bytes(4,'little')*2+bytes(range(1,33))+bytes(range(17,33))
        if changed:raw=raw[:8]+bytes([99])+raw[9:]
        self.assertEqual(self.lib.prepare(raw,len(raw),0),7);return raw

    def transform(self,unwrap,data,key_class=6,flags=0,capacity=None,handle=0):
        data=C.create_string_buffer(data,len(data)+1);size=capacity if capacity is not None else len(data)-1+(8 if not unwrap else -8)
        out=C.create_string_buffer(b'\x7c'*80,81);actual=C.c_uint64(0xdeadbeef);written=C.c_uint(0)
        result=self.lib.transform(unwrap,data,len(data)-1,key_class,handle,out,size,flags,C.byref(actual),C.byref(written))
        return result,bytes(out)[:size],actual.value,written.value

    def test_nist_rfc3394_known_answers_including_native_256bit_kek(self):
        cases=[(16,'00112233445566778899aabbccddeeff','1fa68b0a8112b447aef34bd8fb5a7b829d3e862371d2cfe5'),
            (32,'00112233445566778899aabbccddeeff','64e8c3f9ce0f5ba263e9777905818a2a93c8191e7d6e8ae7'),
            (32,'00112233445566778899aabbccddeeff000102030405060708090a0b0c0d0e0f',
             '28c9f404c4b810f4cbccb35cfb87f8263f5786e2d80ed326cbc7f0e71a99f43bfb988b9b7a02dd21')]
        for n,plain,cipher in cases:
            key=bytes(range(n));plain=bytes.fromhex(plain);cipher=bytes.fromhex(cipher);iv=b'\xa6'*8
            self.assertEqual(self.kw(0,key,iv,plain),(0,cipher))
            self.assertEqual(self.kw(1,key,iv,cipher),(0,plain))

    def test_corruption_wrong_class_and_provider_failure_clear_plaintext(self):
        key=bytes(range(32));iv=b'RDK\x01\0\0\0\x06';plain=bytes(range(32))
        error,wrapped=self.kw(0,key,iv,plain);self.assertEqual(error,0)
        for at in range(len(wrapped)):
            broken=bytearray(wrapped);broken[at]^=1
            self.assertEqual(self.kw(1,key,iv,bytes(broken)),(errno.EBADMSG,bytes(len(plain))))
        self.assertEqual(self.kw(1,key,b'RDK\x01\0\0\0\x07',wrapped),(errno.EBADMSG,bytes(len(plain))))
        for unwrap,data,size in [(0,plain,40),(1,wrapped,32)]:
            self.assertEqual(self.kw(unwrap,key,iv,data,fail=5),(errno.EIO,bytes(size)))

    def test_native_descriptor_and_inband_results_survive_context_reset(self):
        for flags in (0,1,2,3):
            raw=self.seed();plain=bytes(range(32));result,wrapped,key_class,actual=self.transform(0,plain,flags=flags)
            self.assertEqual((result,key_class,actual),(0,6,40))
            self.assertEqual(self.lib.prepare(raw,len(raw),0),7)
            result,recovered,_,actual=self.transform(1,wrapped,flags=flags)
            self.assertEqual((result,recovered,actual),(0,plain,32))
            self.seed(changed=True)
            self.assertEqual(self.transform(1,wrapped,flags=flags)[0],3)

    def test_native_short_buffers_descriptors_and_wrong_bag_never_succeed(self):
        self.seed();plain=bytes(range(32))
        for flags,cap,wanted in [(0,39,4),(3,39,4),(1|4,40,5),(2|8,40,5),(16,40,1),(32,40,1)]:
            self.assertEqual(self.transform(0,plain,flags=flags,capacity=cap)[0],wanted)
        self.assertEqual(self.transform(0,plain,handle=1)[0],1)
        for length in (0,1,8,15,17,65,72,80):
            self.assertEqual(self.transform(0,bytes(length),capacity=80)[0],1)
        raw=self.seed();self.assertEqual(self.lib.prepare(raw,len(raw),1),4)
        self.assertEqual(self.transform(0,plain)[0],2)
        for broken in [raw[:55],bytes(56),raw[:8]+bytes(32)+raw[40:]]:
            self.assertEqual(self.lib.prepare(broken,len(broken),0)&1,0)

    def test_unwired_native_device_state_output_and_all_prepare_failures_are_balanced(self):
        self.seed();out=C.create_string_buffer(4096);actual=C.c_uint()
        self.assertEqual(self.lib.descriptor_state(out,4096,0,C.byref(actual)),0)
        self.assertGreater(actual.value,64)
        self.assertEqual([self.lib.wire_metric(i) for i in range(4)],[1,1,0,1])
        for flags,wanted,counts in [(1,7,[1,0,0,0]),(2,5,[1,1,0,1]),(4,8,[1,1,0,1])]:
            self.assertEqual(self.lib.descriptor_state(out,4096,flags,C.byref(actual)),wanted)
            self.assertEqual([self.lib.wire_metric(i) for i in range(4)],counts)
        for flags,wanted,counts in [(1|2,0,[2,2,1,1]),(1|2|64,7,[1,0,0,0]),
                (1|2|128,7,[2,1,1,0]),(1|2|256,8,[1,1,1,0]),(1|2|512,8,[2,2,1,1])]:
            self.assertEqual(self.transform(0,bytes(range(32)),flags=flags)[0],wanted)
            self.assertEqual([self.lib.wire_metric(i) for i in range(4)],counts)

    def test_native_state_is_a_canonical_der_set_with_no_passcode_and_first_unlock(self):
        self.seed();out=C.create_string_buffer(4096);actual=C.c_uint()
        self.assertEqual(self.lib.descriptor_state(out,4096,0,C.byref(actual)),0)
        data=bytes(out)[:actual.value]
        self.assertEqual(data[:2],bytes([0x31,len(data)-2]))
        at=2;entries=[];values={}
        while at<len(data):
            self.assertEqual(data[at],0x30);end=at+2+data[at+1]
            entries.append(data[at:end]);self.assertEqual(data[at+2],0x0c)
            length=data[at+3];key=data[at+4:at+4+length].decode()
            integer=data[at+4+length:end]
            self.assertEqual(integer[:2],b'\x02\x01');self.assertEqual(len(integer),3)
            self.assertNotIn(key,values);values[key]=integer[2];at=end
        self.assertEqual(at,len(data));self.assertEqual(entries,sorted(entries))
        self.assertEqual(values,dict(sb=0,sr=0,ss=6,sas=0,sfa=0,sgs=0,sls=3,sgpe=0,srcd=0))

    def test_private_material_permissions_identity_and_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'private.json';first=material.create(path)
            self.assertEqual(material.load(path),first)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):material.create(path)
            os.chmod(path,0o644)
            with self.assertRaises(ValueError):material.load(path)
            for bad in [dict(first,serial_number='excluded'),dict(first,format_version=True),dict(first,wrapping_key_hex='0'*64)]:
                with self.assertRaises(ValueError):material.validate(bad)
            report=material.report(path,first)
            self.assertFalse(report['hardware_secure_enclave'])
            self.assertNotIn(first['wrapping_key_hex'],json.dumps(report))


if __name__=='__main__':unittest.main()
