"""Execute the actual read-only USB probe against host-backed fake registers."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def probe_source():
    patch = (HERE / 'usb-probe.patch').read_text()
    section = patch.split('+++ b/bsd/dev/redfin_usb.c\n', 1)[1]
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+')) + '\n'


class UsbProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        cls.temporary = tempfile.TemporaryDirectory()
        work = Path(cls.temporary.name)
        actual = probe_source()
        actual = '\n'.join(line for line in actual.splitlines()
                           if not line.startswith('#include'))
        barrier = '__asm__ volatile ("dmb oshld" ::: "memory");'
        assert actual.count(barrier) == 1
        actual = actual.replace(barrier, '__asm__ volatile ("" ::: "memory");')
        harness = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <assert.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef uintptr_t DTEntry;
static uint32_t gcc[0x4000],dwc[0x4000],before_gcc[0x4000],before_dwc[0x4000];
static unsigned selected_mode,board,fail_map,map_count;
static char output[8192];
static unsigned output_size;
static const char good[]="D22AP\0iPhone10,3\0google,redfin\0xiaomi,sweet\0qcom,sm7250";
static int SecureDTLookupEntry(void *ignored,const char *path,DTEntry *root)
{(void)ignored;assert(!strcmp(path,"/"));*root=1;return board==4 ? -1 : 0;}
static int SecureDTGetProperty(DTEntry root,const char *key,const void **data,unsigned *size)
{
 assert(root==1 && !strcmp(key,"compatible"));
 const char *value=good;unsigned n=sizeof(good);
 if(board==1){value="google,redfin-clone\0qcom,sm7250";n=sizeof("google,redfin-clone\0qcom,sm7250");}
 if(board==2){value="google,redfin\0qcom,sm72500";n=sizeof("google,redfin\0qcom,sm72500");}
 if(board==3)n--;
 if(board==5){value="google,redfin\0\0qcom,sm7250";n=sizeof("google,redfin\0\0qcom,sm7250");}
 if(board==6)n=257;
 if(board==8)value=NULL;
 *data=value;*size=n;return board==7 ? -1 : 0;
}
static bool PE_parse_boot_argn(const char *key,void *out,int size)
{assert(!strcmp(key,"redfinusb") && size==sizeof(uint32_t));memcpy(out,&selected_mode,size);return selected_mode!=0;}
vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t size)
{
 map_count++;
 if(map_count==fail_map)return 0;
 if(pa==0x100000 && size==0x10000)return (vm_offset_t)gcc;
 assert(pa==0xa600000 && size==0xcd00);return (vm_offset_t)dwc;
}
static int test_log(const char *format,...)
{
 va_list ap;va_start(ap,format);
 int n=vsnprintf(output+output_size,sizeof(output)-output_size,format,ap);
 va_end(ap);assert(n>=0 && (unsigned)n<sizeof(output)-output_size);output_size+=(unsigned)n;return n;
}
#define printf test_log
ACTUAL
unsigned run_probe(unsigned mode,unsigned which_board,unsigned failed_map,uint32_t gdsc,
 uint32_t reset,unsigned disabled,unsigned halted,uint32_t id,uint32_t gctl)
{
 selected_mode=mode;board=which_board;fail_map=failed_map;map_count=0;output_size=0;output[0]=0;
 memset(gcc,0,sizeof(gcc));memset(dwc,0,sizeof(dwc));
 gcc[0xf004/4]=gdsc;gcc[0xf000/4]=reset;
 const unsigned offsets[]={0xf010,0xf07c,0xf080,0xf018,0xf01c};
 for(unsigned i=0;i<5;i++)gcc[offsets[i]/4]=((disabled>>i)&1 ? 0 : 1)|((halted>>i)&1 ? 0x80000000u : 0);
 dwc[0xc120/4]=id;dwc[0xc110/4]=gctl;dwc[0xc140/4]=(40u<<24)|(64u<<8);
 memcpy(before_gcc,gcc,sizeof(gcc));memcpy(before_dwc,dwc,sizeof(dwc));
 redfin_usb_probe();
 assert(!memcmp(before_gcc,gcc,sizeof(gcc)) && !memcmp(before_dwc,dwc,sizeof(dwc)));
 return map_count;
}
const char *probe_log(void){return output;}
'''
        source = work / 'probe.c'
        source.write_text(harness.replace('ACTUAL', actual))
        library = work / 'probe.so'
        subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra',
                        '-Werror', str(source), '-o', str(library)], check=True,
                       capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.run_probe.argtypes = [ctypes.c_uint32] * 9
        cls.library.run_probe.restype = ctypes.c_uint
        cls.library.probe_log.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, **overrides):
        values = dict(mode=1, board=0, fail_map=0, gdsc=0x80000000,
                      reset=0, disabled=0, halted=0, core=0x5533330a, gctl=2 << 12)
        values.update(overrides)
        count = self.library.run_probe(*values.values())
        return count, self.library.probe_log().decode()

    def test_only_exact_mode_one_and_bounded_redfin_compatible_allow_mmio(self):
        for mode in (0, 2, 3, 0xffffffff):
            self.assertEqual(self.run_case(mode=mode)[0], 0)
        for board in range(1, 9):
            with self.subTest(board=board):
                self.assertEqual(self.run_case(board=board)[0], 0)

    def test_every_missing_or_halted_clock_prevents_controller_mapping(self):
        for mask in range(1, 32):
            for kind in ('disabled', 'halted'):
                with self.subTest(mask=mask, kind=kind):
                    count, log = self.run_case(**{kind: mask})
                    self.assertEqual(count, 1)
                    self.assertIn('DWC3 not mapped', log)
        for gdsc in (0, 1, 0xffffffff, 0x80000001):
            self.assertEqual(self.run_case(gdsc=gdsc)[0], 1)
        self.assertEqual(self.run_case(reset=1)[0], 1)

    def test_mapping_failure_and_unsupported_core_stop_snapshot(self):
        for failed_map in (1, 2):
            count, log = self.run_case(fail_map=failed_map)
            self.assertEqual(count, failed_map)
            self.assertIn('map failed', log)
        for core in (0, 0xffffffff, 0x33310000):
            count, log = self.run_case(core=core)
            self.assertEqual(count, 2)
            self.assertIn('unsupported core ID', log)
            self.assertNotIn('DCFG=', log)

    def test_device_snapshot_is_read_only_and_host_or_drd_stops_before_device_bank(self):
        count, log = self.run_case()
        self.assertEqual(count, 2)
        for expected in ('MDWIDTH=64', 'AWIDTH=40', 'DCFG=', 'GEVNTADR=', 'PHY/SMMU/DMA untouched'):
            self.assertIn(expected, log)
        for direction in (0, 1, 3):
            _, log = self.run_case(gctl=direction << 12)
            self.assertIn('not device mode', log)
            self.assertNotIn('DCFG=', log)


if __name__ == '__main__':
    unittest.main()
