"""Actual WLAN context lease with native FORMAT status and foreign/fault loss."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

HARNESS = r'''
#include "wifi_snoc.h"
#include "wifi_snoc_lease.h"
static struct rf_snoc_lease lease;
static struct rf_snoc_snapshot image,initial;
static unsigned writes,scenario,fail_write,foreign_after,violations;
static int check(void *ctx){return ctx==&image?0:EPERM;}
static int sample(void *ctx,struct rf_snoc_snapshot *out){if(check(ctx))return EPERM;*out=image;return 0;}
static int read(void *ctx,unsigned block,uint32_t at,uint32_t *out){
 if(check(ctx))return EPERM;
 if(block==1 && at==0x4000)*out=image.bank[4].sctlr;
 else if(!block && at==0x1810)*out=image.bank[4].cba2r;
 else if(!block && at==0x1010)*out=image.bank[4].cbar;
 else if(!block && at==0xc10)*out=image.s2cr[4];
 else if(!block && at==0x810)*out=image.smr[4];
 else {violations++;return EINVAL;}
 return 0;
}
static int write(void *ctx,unsigned block,uint32_t at,uint32_t value){
 unsigned expected_block=0;uint32_t expected_at=0,expected_value=0;
 writes++;
 if(check(ctx) || rf_snoc_lease_step(&lease,writes-1,&expected_block,&expected_at,&expected_value) ||
    block!=expected_block || at!=expected_at || value!=expected_value){violations++;return EINVAL;}
 if(block==1)image.bank[4].sctlr=value;
 else if(at==0x1810){
  image.bank[4].cba2r=value;image.bank[4].fault=(image.bank[4].fault&~0x600u)|0x400u;
  if(scenario==1)image.bank[4].fault|=2;  /* Real translation fault stays fatal. */
  if(scenario==2)image.bank[7].fault|=0x400; /* Foreign FORMAT is not our transition. */
  if(scenario==3)image.bank[4].sctlr|=0x10;
 } else if(at==0x1010)image.bank[4].cbar=value;
 else if(at==0xc10)image.s2cr[4]=value;
 else if(at==0x810)image.smr[4]=value;
 else {violations++;return EINVAL;}
 if(foreign_after==writes)image.smr[12]^=0x80000000u;
 return fail_write==writes?EIO:0;
}
static int delay_us(void *ctx,unsigned us){return !check(ctx) && us==1?0:EINVAL;}
static const struct rf_snoc_lease_ops ops={&image,check,sample,read,write,delay_us};
#ifdef __cplusplus
extern "C" {
#endif
int run(unsigned fault,unsigned write_failure,unsigned change_after){
 scenario=fault;fail_write=write_failure;foreign_after=change_after;writes=violations=0;
 memset(&image,0,sizeof(image));memset(&lease,0,sizeof(lease));
 image.stage=4;image.stable=true;image.control=0x290406;
 image.id[0]=0x4c017e51;image.id[1]=0x6000003e;image.id[2]=0x5111;
 for(unsigned i=0;i<RF_SNOC_STREAMS;i++)image.s2cr[i]=0x10300;
 for(unsigned i=0;i<4;i++){image.smr[i]=0x80000200u+i;image.s2cr[i]=i<3?i:0;}
 image.s2cr[80]=0; /* Latent invalid-SMR reference must remain reserved. */
 for(unsigned i=0;i<RF_SNOC_CONTEXTS;i++)image.bank[i].sctlr=0x12340000u+2*i;
 for(unsigned i=0;i<3;i++)image.bank[i].sctlr|=1;
 image.bank[3].cbar=0x100ff;image.bank[3].cba2r=1;image.bank[3].fault=0x400;
 initial=image;
 return rf_snoc_lease_claim(&lease,&ops,&initial);
}
unsigned metric(unsigned n){const unsigned v[]={writes,violations,lease.bank,lease.slot,lease.stores,lease.active,
 lease.poisoned,image.bank[4].fault,image.bank[4].sctlr,image.bank[4].cba2r,image.bank[4].cbar,
 image.smr[4],image.s2cr[4]};return n<13?v[n]:0;}
int retry(void){return rf_snoc_lease_claim(&lease,&ops,&initial);}
int preserved(void){
 struct rf_snoc_snapshot copy=image;copy.bank[4]=initial.bank[4];copy.smr[4]=initial.smr[4];copy.s2cr[4]=initial.s2cr[4];
 return !memcmp(&copy,&initial,sizeof(copy));
}
unsigned difference(unsigned which){
 unsigned block=0;uint32_t at=0,expected=0,observed=0;
 if(!rf_snoc_lease_difference(&lease,&block,&at,&expected,&observed))return 0;
 const unsigned v[]={1,block,at,expected,observed};return which<5?v[which]:0;
}
#ifdef __cplusplus
}
#endif
'''


class SnocLeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        cls.libs = []
        for compiler, suffix, standard in (('cc', 'c', 'c11'), ('c++', 'cpp', 'c++17')):
            if not shutil.which(compiler):
                raise unittest.SkipTest('host C/C++ compilers unavailable')
            source = root / ('lease.' + suffix)
            source.write_text(HARNESS)
            library = root / ('lease-' + suffix + '.so')
            result = subprocess.run([compiler, '-std=' + standard, '-shared', '-fPIC', '-O2',
                '-Wall', '-Wextra', '-Werror', '-I', str(HERE), str(source), '-o', str(library)],
                capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.run.argtypes = [C.c_uint] * 3
            lib.metric.restype = lib.difference.restype = C.c_uint
            cls.libs.append(lib)

    def test_native_aarch64_format_transition_completes_five_stores_preserving_other_contexts(self):
        for lib in self.libs:
            self.assertEqual(lib.run(0, 0, 0), 0)
            self.assertEqual([lib.metric(i) for i in range(13)],
                [5, 0, 4, 4, 5, 1, 0, 0x400, 0, 1, 0x10000, 0x800100c0, 0x304])
            self.assertEqual(lib.preserved(), 1)

    def test_real_fault_foreign_format_and_unexpected_owned_sctlr_are_not_accepted(self):
        for lib in self.libs:
            for scenario, block, at, observed in ((1, 1, 0x4058, 0x402),
                    (2, 1, 0x7058, 0x400), (3, 1, 0x4000, 0x10)):
                self.assertEqual(lib.run(scenario, 0, 0), errno.EAGAIN)
                self.assertEqual(lib.metric(0), 2)
                self.assertEqual(lib.metric(5), 0)
                self.assertEqual([lib.difference(i) for i in (0, 1, 2, 4)], [1, block, at, observed])

    def test_each_uncertain_write_or_foreign_change_stops_without_releasing_or_retrying(self):
        for lib in self.libs:
            for position in range(1, 6):
                for write_error in (False, True):
                    self.assertEqual(lib.run(0, position if write_error else 0,
                        0 if write_error else position), errno.EIO if write_error else errno.EAGAIN)
                    self.assertEqual(lib.metric(0), position)
                    self.assertEqual(lib.metric(5), 0)
                    self.assertEqual(lib.metric(6), 1)
                    self.assertNotEqual(lib.retry(), 0)
                    self.assertEqual(lib.metric(0), position)
                    self.assertEqual(lib.metric(1), 0)


if __name__ == '__main__':
    unittest.main()
