"""Actual staging allocator hint refuses fragmented-only/unbounded bitmap data."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class OfflineContiguousTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);root=Path(cls.tmp.name)
        body=function((HERE/'offline-stage-files.c').read_text(),'static int stage_contiguous(')
        prefix='''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
struct header {uint32_t totalBlocks,nextAllocation;};
typedef struct {struct header *volumeHeader;void *allocationFile;} Volume;
static unsigned char bitmap[4194304/8];static unsigned short_read;
static int bitmap_read(void *file,uint64_t at,size_t n,void *out){(void)file;if(short_read || at || n!=sizeof(bitmap))return 0;memcpy(out,bitmap,n);return 1;}
#define READ bitmap_read
'''
        suffix='''
unsigned run(unsigned scenario,unsigned needed){
 memset(bitmap,255,sizeof(bitmap));short_read=scenario==3;
 struct header h={4194304,1234};Volume volume={&h,bitmap};
 if(scenario==2)h.totalBlocks--;
 for(unsigned b=300;b<(scenario==4?10000u:600u);b++)if(scenario!=1 || !(b%2))bitmap[b/8]&=(unsigned char)~(0x80u>>(b%8));
 if(!stage_contiguous(&volume,needed))return h.nextAllocation==1234?0:999;
 return h.nextAllocation;
}
'''
        (root/'hint.c').write_text(prefix+body+suffix)
        subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(root/'hint.c'),'-o',str(root/'hint.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(root/'hint.so'));cls.lib.run.argtypes=[C.c_uint,C.c_uint];cls.lib.run.restype=C.c_uint

    def test_complete_run_is_selected_and_short_fragmented_or_unbounded_inputs_preserve_hint(self):
        self.assertEqual(self.lib.run(0,18),300)
        self.assertEqual(self.lib.run(4,2500),300)
        self.assertEqual(self.lib.run(4,4096),300)
        for scenario,needed in [(1,18),(2,18),(3,18),(0,0),(0,1025),(0,300),(4,4097)]:
            self.assertEqual(self.lib.run(scenario,needed),0)


if __name__=='__main__':unittest.main()
