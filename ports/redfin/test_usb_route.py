"""Exercise the actual bounded route observer without hardware or writes."""
import ctypes as C
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class USBRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        patch = Path(__file__).with_name('usb-route.patch').read_text()
        additions = '\n'.join(s[1:] for s in patch.splitlines()
                              if s.startswith('+') and not s.startswith('+++'))
        start = additions.index('/* Standard SMMUv2')
        stop = additions.index('\n if ((mode', start) if '\n if ((mode' in additions[start:] else -1
        code = additions[start:] if stop < 0 else additions[start:stop]
        opening = code.index('{', code.index('redfin_usb_route_snapshot('))
        depth = 0
        for end in range(opening, len(code)):
            depth += (code[end] == '{') - (code[end] == '}')
            if depth == 0:
                code = code[:end+1]
                break
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdarg.h>
typedef uintptr_t vm_offset_t;
typedef void *DTEntry;
#define kSuccess 0
static uint32_t regs[0x10000/4],sid;
static uint64_t ranges[2];
static int variant,maps,reads,bad,matches,stable,selected_reads,other_reads;
static int model_printf(const char *s,...) {
 if(strstr(s,"matches=%u stable=%u")){
  va_list a;va_start(a,s);matches=(int)va_arg(a,unsigned);stable=(int)va_arg(a,unsigned);va_end(a);
 }
 return 0;
}
#define printf model_printf
static int SecureDTLookupEntry(void *r,const char *s,DTEntry *e){
 (void)r;if(strcmp(s,"/redfin-usb-route")||variant==1)return -1;*e=(void*)1;return 0;
}
static int SecureDTGetProperty(DTEntry e,const char *s,const void **v,unsigned *n){
 if(e!=(void*)1){bad++;return -1;}
 if(!strcmp(s,"reg")){*v=ranges;*n=sizeof(ranges);return 0;}
 if(!strcmp(s,"stream-id")){*v=&sid;*n=4;return 0;}return -1;
}
static vm_offset_t ml_io_map(uint64_t pa,unsigned size){
 maps++;if(pa!=0x15000000||size!=0x10000){bad++;return 0;}
 return variant==4?0:1;
}
static uint32_t redfin_usb_rd(vm_offset_t base,unsigned off){
 reads++;if(base!=1||off>=0x10000||(off&3)){bad++;return 0;}
 if(!(off==0||off==0x20||off==0x24||off==0x28||
   (off>=0x800&&off<0xa00)||(off>=0xc00&&off<0xe00))){bad++;return 0;}
 if(off==0x804&&variant==11&&++selected_reads>1)return regs[off/4]^1;
 if(off==0x800&&variant==12&&++other_reads>1)return 0x800000e0u;
 return regs[off/4];
}
'''
        suffix = r'''
int host_run(uint32_t dctl,uint32_t dsts,uint32_t size,int v){
 variant=v;maps=reads=bad=selected_reads=other_reads=0;matches=stable=-1;
 memset(regs,0,sizeof(regs));ranges[0]=0x15000000;ranges[1]=0x100000;sid=0xe0;
 regs[0x20/4]=(1u<<30)|(1u<<27)|4;regs[0x24/4]=8;regs[0x28/4]=1u<<13;
 regs[0x804/4]=0x800100e0u;regs[0xc04/4]=0x10000;
 if(v==2)ranges[0]=0x3da0000;if(v==3)sid=0x1a0;
 if(v==5)regs[0x20/4]&=~(1u<<27);if(v==6)regs[0x20/4]|=1u<<8;
 if(v==7)regs[0]|=1u<<3;if(v==8)regs[0x20/4]=(1u<<30)|(1u<<27)|129;
 if(v==9)regs[0x804/4]=0x800100e2u;
 if(v==10){regs[0x808/4]=0x800000e0u;regs[0xc08/4]=0x10000;}
 redfin_usb_route_snapshot(dctl,dsts,size);return bad;
}
int host_stats(unsigned i){return i==0?maps:i==1?reads:i==2?matches:stable;}
'''
        (root/'route.c').write_text(prefix+code+suffix)
        subprocess.run([shutil.which('clang') or 'cc', '-std=c11', '-Wall', '-Wextra',
                        '-Werror', '-shared', '-fPIC', str(root/'route.c'), '-o', str(root/'route.so')],
                       check=True, capture_output=True)
        cls.lib = C.CDLL(str(root/'route.so'))
        cls.lib.host_run.argtypes = [C.c_uint32, C.c_uint32, C.c_uint32, C.c_int]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_case(self, variant=0, dctl=0, dsts=0x400000, size=0x80001000):
        self.assertEqual(self.lib.host_run(dctl, dsts, size, variant), 0)
        return tuple(self.lib.host_stats(i) for i in range(4))

    def test_busy_or_unmasked_controller_never_maps_smmu(self):
        for kw in ({'dctl': 0x80000000}, {'dsts': 0}, {'size': 0x1000}):
            self.assertEqual(self.run_case(**kw)[:2], (0, 0))

    def test_wrong_fdt_rejected_before_mapping(self):
        for variant in (1, 2, 3):
            self.assertEqual(self.run_case(variant)[:2], (0, 0))

    def test_unsupported_layout_never_reads_stream_arrays(self):
        self.assertEqual(self.run_case(4)[:2], (1, 0))
        for variant in (5, 6, 7, 8):
            self.assertEqual(self.run_case(variant)[1], 4)

    def test_unique_missing_and_ambiguous_matches_are_distinct(self):
        self.assertEqual(self.run_case()[2:], (1, 1))
        self.assertEqual(self.run_case(9)[2:], (0, 1))
        self.assertEqual(self.run_case(10)[2:], (2, 1))

    def test_detects_changed_selected_route(self):
        self.assertEqual(self.run_case(11)[2:], (1, 0))

    def test_new_match_invalidates_previously_unique_snapshot(self):
        self.assertEqual(self.run_case(12)[2:], (1, 0))


if __name__ == '__main__':
    unittest.main()
