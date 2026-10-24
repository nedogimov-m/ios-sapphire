"""Actual affinity, cache handoff and prepared-surface bounds used by GUI3."""
import ctypes as C
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_smp_gui import compile_shared

HERE=Path(__file__).resolve().parent


class GraphicsPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        source=(HERE/'gui-runtime.h').read_text()
        enter=re.search(r'void \*redfin_gui_worker_enter\(void\)\n\{.*?\n\}',source,re.S).group()
        leave=re.search(r'void redfin_gui_worker_leave\(void \*previous\)\n\{.*?\n\}',source,re.S).group()
        harness=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "redfin_gpu_runtime.h"
typedef void *processor_t;
#define THREAD_CONTINUE_NULL NULL
static unsigned cpu,switches;
static processor_t binding;
static unsigned rf_smp_local(void){return cpu;}
static processor_t cpu_to_processor(unsigned n){return (void *)(uintptr_t)(n+1);}
static processor_t thread_bind(processor_t p){processor_t old=binding;binding=p;return old;}
static void thread_block(void *continuation){(void)continuation;switches++;if(binding)cpu=(unsigned)(uintptr_t)binding-1;}
'''+enter+'\n'+leave+r'''
int affinity(unsigned running,int previous){
    cpu=running;switches=0;binding=previous<0?NULL:cpu_to_processor((unsigned)previous);
    void *saved=redfin_gui_worker_enter();if(cpu!=0)return -1;
    redfin_gui_worker_leave(saved);
    if(binding!=(previous<0?NULL:cpu_to_processor((unsigned)previous)))return -2;
    if(previous>=0 && cpu!=(unsigned)previous)return -3;
    return (int)switches;
}
static struct rf_gr_surface_cache cache;
void reset(void){cache=(struct rf_gr_surface_cache){0};}
int push(uint32_t seed,uint64_t now,int mapped){return rf_gr_surface_push(&cache,seed,now,4000000,mapped);}
int layout(uint64_t allocation,uint32_t offset,uint32_t delta,uint64_t descriptor,uint64_t *size,uint32_t *pixels){
    return rf_gr_surface_layout(allocation,offset,delta,descriptor,size,pixels);
}
int bo(uint32_t flags,uint64_t presumed,uint64_t address){return rf_gr_submit_bo(flags,presumed,address);}
uint64_t pte(uint64_t physical,int read_only){return rf_gr_page_entry(physical,read_only);}
'''
        cls.lib=compile_shared(Path(cls.temp.name),harness,'graphics-performance',
            flags=('-I',str(HERE/'include')))
        cls.lib.affinity.argtypes=[C.c_uint,C.c_int]
        cls.lib.push.argtypes=[C.c_uint32,C.c_uint64,C.c_int]
        cls.lib.layout.argtypes=[C.c_uint64,C.c_uint32,C.c_uint32,C.c_uint64,
                                C.POINTER(C.c_uint64),C.POINTER(C.c_uint32)]
        cls.lib.bo.argtypes=[C.c_uint32,C.c_uint64,C.c_uint64]
        cls.lib.pte.argtypes=[C.c_uint64,C.c_int];cls.lib.pte.restype=C.c_uint64

    def test_only_required_cpu_migrations_switch_the_thread(self):
        for cpu,previous,switches in ((0,-1,0),(0,0,0),(3,-1,1),(3,3,2),(0,3,1),(7,0,1)):
            self.assertEqual(self.lib.affinity(cpu,previous),switches)

    def test_surface_seed_time_and_client_mapping_preserve_visibility_handoffs(self):
        self.lib.reset()
        self.assertEqual(self.lib.push(7,0,0),1)
        self.assertEqual(self.lib.push(7,1,0),0)
        self.assertEqual(self.lib.push(8,2,0),1)
        self.assertEqual(self.lib.push(8,3999999,0),0)
        self.assertEqual(self.lib.push(8,4000002,0),1)
        self.assertEqual(self.lib.push(8,4000003,1),1)
        self.assertEqual(self.lib.push(8,4000003,1),1)
        self.assertEqual(self.lib.push(8,1,0),1)

    def test_surface_own_offset_and_wrapped_page_delta_have_different_bounds(self):
        def layout(a,o,d,md):
            size=C.c_uint64(99);pixels=C.c_uint32(77)
            ok=self.lib.layout(a,o,d,md,C.byref(size),C.byref(pixels))
            return ok,size.value,pixels.value
        self.assertEqual(layout(16384,128,0,16384),(1,16384,128))
        self.assertEqual(layout(16300,0,128,32768),(1,32768,128))
        self.assertEqual(layout(100,4,16300,32768),(1,32768,16304))
        for args in ((0,0,0,16384),(100,100,0,16384),(100,0,16384,32768),
                     (16300,0,128,16384),(128*1024**2,0,1,128*1024**2+16384),
                     (2**64-1,0,0,2**64-1)):
            self.assertEqual(layout(*args),(0,99,77))

    def test_freedreno_command_dependency_flags_keep_native_page_write_protection(self):
        # Actual captured command BO: allocation GPU_READONLY, submit flags7.
        address=0x10000000;physical=0x1f1234000
        for flags in (1,3,7,15):
            self.assertEqual(self.lib.bo(flags,0,address),1)
            self.assertEqual(self.lib.bo(flags,address,address),1)
        for flags,presumed in ((16,0),(0x80000000,0),(7,address+4096)):
            self.assertEqual(self.lib.bo(flags,presumed,address),0)
        read_only=self.lib.pte(physical,1);writable=self.lib.pte(physical,0)
        self.assertEqual(read_only&~4095,physical)
        self.assertEqual(writable&~4095,physical)
        self.assertEqual((read_only>>6)&3,3)  # Stage1 AP: read-only for EL0/EL1.
        self.assertEqual((writable>>6)&3,1)   # Stage1 AP: read/write for EL0/EL1.


if __name__=='__main__':unittest.main()
