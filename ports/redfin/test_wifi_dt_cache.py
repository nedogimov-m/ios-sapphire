"""Cache ADT traversal only: live values, caller isolation and bounded misses."""
import ctypes as C
from pathlib import Path
import tempfile
import unittest

from test_smp_gui import compile_shared

HERE=Path(__file__).resolve().parent


class WifiDTCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        source=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
typedef uintptr_t DTEntry;
typedef void *thread_t;
#define kSuccess 0
static uintptr_t owner;
static unsigned node_reads,property_reads;
static uint32_t live_value;
static thread_t current_thread(void){return (void *)owner;}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
    (void)root;node_reads++;if(!path || !out || !strcmp(path,"/missing"))return 19;
    *out=1;return 0;
}
static int SecureDTGetProperty(DTEntry node,const char *key,const void **value,unsigned *bytes){
    property_reads++;if(!node || !key || !value || !bytes || !strcmp(key,"missing"))return 23;
    *value=&live_value;*bytes=4;return 0;
}
'''+(HERE/'wifi_dt_cache.inc').read_text()+r'''
void reset(void){owner=1;fw_dt_owner=NULL;node_reads=property_reads=0;live_value=7;}
void begin(void){fw_dt_begin();}
void caller(unsigned n){owner=n;}
void mutate(uint32_t value){live_value=value;}
int read_value(const char *path,const char *key,unsigned expected){
    DTEntry node;const void *raw=NULL;unsigned bytes=0;
    int result=fw_dt_lookup(path,&node);if(result)return -result;
    result=fw_dt_property(node,key,&raw,&bytes);if(result)return -result;
    if(!raw || bytes!=expected)return -99;
    return *(const uint32_t *)raw;
}
unsigned reads(unsigned property){return property?property_reads:node_reads;}
int capacity(void){
    char path[96],key[64];
    for(unsigned i=0;i<160;i++){
        snprintf(path,sizeof(path),"/node%u",i);snprintf(key,sizeof(key),"key%u",i);
        if(read_value(path,key,4)!=(int)live_value)return 0;
    }
    return 1;
}
'''
        cls.lib=compile_shared(Path(cls.temp.name),source,'wifi-dt')
        cls.lib.read_value.argtypes=[C.c_char_p,C.c_char_p,C.c_uint]

    def setUp(self):self.lib.reset()

    def read(self,path=b'/chosen',key=b'policy',expected=4):
        return self.lib.read_value(path,key,expected)

    def test_cached_traversal_rereads_the_original_live_bytes(self):
        self.lib.begin()
        self.assertEqual(self.read(),7)
        self.assertEqual(self.read(),7)
        self.assertEqual((self.lib.reads(0),self.lib.reads(1)),(1,1))
        self.lib.mutate(9)
        self.assertEqual(self.read(),9)
        self.assertEqual(self.read(expected=8),-99)

    def test_other_threads_missing_entries_and_capacity_keep_native_lookup_behavior(self):
        self.lib.begin();self.assertEqual(self.read(),7)
        self.lib.caller(2);self.assertEqual(self.read(),7);self.assertEqual(self.read(),7)
        self.assertEqual((self.lib.reads(0),self.lib.reads(1)),(3,3))
        self.assertEqual(self.read(path=b'/missing'),-19)
        self.assertEqual(self.read(key=b'missing'),-23)
        self.lib.caller(1);self.assertEqual(self.lib.capacity(),1)
        self.assertEqual(self.read(path=b'/'*100,key=b'k'*80),7)


if __name__=='__main__':unittest.main()
