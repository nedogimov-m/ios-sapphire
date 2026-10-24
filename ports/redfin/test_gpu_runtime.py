"""Owned runtime arena/guard pages, native command publication and exact GUI3."""
import ctypes as C
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import gui_profile

HERE=Path(__file__).resolve().parent
HARNESS=r'''
#include <string.h>
#include "redfin_gpu_runtime.h"
#include "gui-profile.h"
#include "gmu-probe.h"
static struct rf_gr_arena arena;
static uint32_t stream[RF_GR_PACKET_WORDS];
void reset(void){memset(&arena,0,sizeof(arena));memset(stream,0xa5,sizeof(stream));}
uint64_t allocate(uint64_t size){return rf_gr_allocate(&arena,size);}
int release_object(uint64_t at,uint64_t bytes){return rf_gr_release(&arena,at,bytes);}
int contains(uint64_t at,uint64_t bytes){return rf_gr_find(&arena,at,bytes)!=0;}
uint64_t used(void){return arena.bytes;}
unsigned packet(uint64_t at,uint32_t words,uint32_t fence,unsigned room){return rf_gr_submit_words(&arena,&at,&words,1,fence,stream,room);}
uint32_t word(unsigned i){return i<RF_GR_PACKET_WORDS?stream[i]:0;}
int gui(const char *s,unsigned n){return redfin_gui_profile(s,n,0);}
int gpu(const char *s,unsigned n){return redfin_gpu_gui_profile(s,n,0);}
int wifi(const char *s,unsigned n){return redfin_wifi_gui_profile(s,n,0);}
int standalone(const char *s,unsigned n){return redfin_gmu_args_mode(s,n,0);}
'''


class GPURuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name);source=root/'runtime.c';source.write_text(HARNESS)
        subprocess.run([shutil.which('cc') or 'cc','-std=c11','-O2','-shared','-fPIC',
            '-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(HERE),
            '-I',str(HERE/'include'),str(source),'-o',str(root/'runtime.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(root/'runtime.so'))
        cls.lib.allocate.argtypes=[C.c_uint64];cls.lib.allocate.restype=C.c_uint64
        cls.lib.release_object.argtypes=[C.c_uint64,C.c_uint64]
        cls.lib.contains.argtypes=[C.c_uint64,C.c_uint64]
        cls.lib.used.restype=C.c_uint64
        cls.lib.packet.argtypes=[C.c_uint64,C.c_uint32,C.c_uint32,C.c_uint]
        for name in ('gui','gpu','wifi','standalone'):getattr(cls.lib,name).argtypes=[C.c_char_p,C.c_uint]

    def setUp(self):self.lib.reset()

    def test_guarded_first_fit_matches_independent_interval_model_through_fragmentation(self):
        rng=random.Random(0xa620);live={};base=0x10000000;limit=0x30000000
        for _ in range(2500):
            if live and rng.randrange(3)==0:
                at=rng.choice(list(live));size=live.pop(at)
                self.assertEqual(self.lib.release_object(at,size),1)
                self.assertEqual(self.lib.release_object(at,size),0)
            else:
                size=rng.randint(1,64)*0x4000;span=((size+0xffff)&~0xffff)+0x10000
                expected=base
                for start,old_size in sorted(live.items()):
                    if expected+span<=start:break
                    expected=start+((old_size+0xffff)&~0xffff)+0x10000
                if expected+span>limit or len(live)==1024:expected=0
                actual=self.lib.allocate(size);self.assertEqual(actual,expected)
                if actual:
                    live[actual]=size
                    self.assertTrue(self.lib.contains(actual,size))
                    self.assertFalse(self.lib.contains(actual+size,1))
                    self.assertFalse(self.lib.contains(actual-1,1))
            self.assertEqual(self.lib.used(),sum(live.values()))

    def test_invalid_sizes_and_returned_subranges_cannot_change_allocations(self):
        for size in (0,128*1024**2+1,2**64-1):self.assertEqual(self.lib.allocate(size),0)
        at=self.lib.allocate(0x8000);self.assertEqual(at,0x10000000)
        self.assertEqual(self.lib.release_object(at,0x4000),0)
        self.assertEqual(self.lib.release_object(at+0x4000,0x4000),0)
        self.assertEqual(self.lib.used(),0x8000)
        self.assertFalse(self.lib.contains(2**64-2,4))
        self.assertFalse(self.lib.contains(0x1000000,4)) # Bootstrap ring is never a client object.

    def test_native_indirect_buffer_and_actual_cache_flush_fence_are_required(self):
        at=self.lib.allocate(0x4000)
        self.assertEqual(self.lib.packet(at,16,7,64),14)
        words=[self.lib.word(i) for i in range(14)]
        def decode(header,opcode,count):
            self.assertEqual(header>>28,7)
            self.assertEqual((header>>16)&0x7f,opcode)
            self.assertEqual(header&0x7fff,count)
            self.assertEqual(((header>>23)&1)^(opcode.bit_count()&1),1)
            self.assertEqual(((header>>15)&1)^(count.bit_count()&1),1)
        decode(words[0],0x46,1);decode(words[2],0x46,1)
        decode(words[4],0x3f,3);self.assertEqual(words[5:8],[at,0,16])
        decode(words[8],0x26,0);decode(words[9],0x46,4)
        self.assertEqual(words[10:],[4,0x1200200,0,7])
        before=[self.lib.word(i) for i in range(32)]
        for address,count,fence,room in ((at-4,1,8,64),(at+0x4000,1,8,64),
                (at,0,8,64),(at,0x100000,8,64),(at,1,0,64),(at,1,8,13),
                (at+1,1,8,64),(0x1000000,1,8,64)):
            self.assertEqual(self.lib.packet(address,count,fence,room),0)
            self.assertEqual([self.lib.word(i) for i in range(32)],before)

    def test_only_complete_gui3_composes_gpu_with_existing_gui2_wifi_contract(self):
        args=' '.join(sorted(gui_profile.REQUIRED))+' redfinbootid=0x1234567890abcdef'
        for mode in (1,2,3):
            s=args.replace('redfingui=1',f'redfingui={mode}')
            self.assertEqual(self.lib.gui(s.encode(),len(s)+1),1)
            self.assertEqual(self.lib.gpu(s.encode(),len(s)+1),mode==3)
            self.assertEqual(self.lib.wifi(s.encode(),len(s)+1),mode>=2)
            self.assertEqual(gui_profile.gpu(s),mode==3)
            self.assertEqual(gui_profile.wifi(s),mode>=2)
            self.assertEqual(self.lib.standalone(s.encode(),len(s)+1),0)
        s=args.replace('redfingui=1','redfingui=3')
        for changed in (s.replace('cpus=8','cpus=1'),s.replace('redfinshutdown=180','redfinshutdown=0'),
                s+' redfinsmmu=6',s+' redfingui=2',s.replace('gpu=0','gpu=1'),s.replace('ufsrw=1','ufsrw=0')):
            self.assertEqual(self.lib.gpu(changed.encode(),len(changed)+1),0)
            with self.assertRaises(ValueError):gui_profile.gpu(changed)


if __name__=='__main__':unittest.main()
