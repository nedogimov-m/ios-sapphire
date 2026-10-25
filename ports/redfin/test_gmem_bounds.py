"""Check actual linear resolve footprint arithmetic and coherent native I/O totals."""
import ctypes as C
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class GMEMBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        p=Path(cls.temp.name);(p/'bounds.c').write_text('#include "gmem-bounds.h"\n'
            'int fits(uint64_t n,uint64_t o,uint64_t p,uint32_t r){return redfin_linear_gmem_fits(n,o,p,r);}\n')
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(HERE),
                        str(p/'bounds.c'),'-o',str(p/'bounds.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(p/'bounds.so'));cls.lib.fits.argtypes=[C.c_uint64,C.c_uint64,C.c_uint64,C.c_uint32]

    def test_actual_short_iosurface_cannot_authorize_a_four_row_gmem_store(self):
        self.assertFalse(self.lib.fits(1212416,0,4288,282))
        self.assertEqual(4288*284,1217792)
        self.assertTrue(self.lib.fits(1217792,0,4288,282))
        self.assertTrue(self.lib.fits(32768,0,256,64))
        self.assertTrue(self.lib.fits(11239424,0,4608,2436))

    def test_offsets_overflow_empty_or_truncated_backing_cannot_expand_a_dma_window(self):
        maximum=(1<<64)-1
        for values in [(0,0,1,1),(1024,1025,1,1),(1024,0,0,1),(1024,0,1,0),
                       (maximum,0,maximum,1),(maximum,maximum,1,1),(maximum,0,1<<63,4)]:
            self.assertFalse(self.lib.fits(*values),values)
        self.assertTrue(self.lib.fits(1040,16,256,4))
        self.assertFalse(self.lib.fits(1039,16,256,4))

    def test_bounded_calculation_matches_independent_unbounded_integer_model(self):
        rng=random.Random(0x620)
        for _ in range(3000):
            pitch=rng.choice([rng.randrange(1,32769),(1<<64)-1])
            rows=rng.randrange(1,1<<32);offset=rng.randrange(0,1<<48)
            padded=((rows+3)//4)*4;required=padded*pitch
            allocation=rng.choice([rng.randrange(0,1<<48),min((1<<64)-1,offset+required)])
            expected=offset<=allocation and required<=allocation-offset
            self.assertEqual(bool(self.lib.fits(allocation,offset,pitch,rows)),expected)

    def test_actual_process_counter_keeps_coherent_pairs_across_native_calling_threads(self):
        source=r'''
#include <assert.h>
#include <pthread.h>
#include "drm-profile.h"
static unsigned done;
static void *worker(void *p){
 (void)p;
 for(unsigned i=0;i<2000;++i){redfin_drm_profile_record(0x46,100);redfin_drm_profile_record(0x42,200);}
 __atomic_add_fetch(&done,1,__ATOMIC_RELEASE);return 0;
}
int main(void){
 uint64_t counts[4];redfin_drm_profile_record(0x44,999);redfin_drm_profile_snapshot(counts);
 assert(!counts[0]&&!counts[1]&&!counts[2]&&!counts[3]);
 pthread_t threads[4];for(unsigned i=0;i<4;++i)assert(!pthread_create(&threads[i],0,worker,0));
 while(__atomic_load_n(&done,__ATOMIC_ACQUIRE)!=4){
  redfin_drm_profile_snapshot(counts);assert(counts[1]==counts[0]*100&&counts[3]==counts[2]*200);
 }
 for(unsigned i=0;i<4;++i)assert(!pthread_join(threads[i],0));
 redfin_drm_profile_snapshot(counts);assert(counts[0]==8000&&counts[1]==800000&&counts[2]==8000&&counts[3]==1600000);
 return 0;
}
'''
        p=Path(self.temp.name);(p/'profile.c').write_text(source)
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-pthread','-I',str(HERE),
                        str(p/'profile.c'),'-o',str(p/'profile')],check=True,capture_output=True)
        subprocess.run([str(p/'profile')],check=True,timeout=10,capture_output=True)
