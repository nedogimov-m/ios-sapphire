"""Run the actual patched pmap helper against low and Redfin high RAM pages."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PhysicalGraphicsTests(unittest.TestCase):
    def test_patched_cache_mode_change_keeps_every_high_address_bit(self):
        if not shutil.which('cc'):self.skipTest('host C compiler absent')
        patch=Path(__file__).with_name('graphics-physical.patch').read_text()
        additions='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        # Compile the changed statement itself, rather than a second address model.
        statement=next(line for line in additions.splitlines() if 'flush_dcache(' in line)
        source='''
#include <stdint.h>
typedef uint64_t vm_offset_t;
typedef uint32_t ppnum_t;
#define PAGE_SHIFT 14
#define PAGE_SIZE 16384
#define TRUE 1
static uint64_t captured;
static void flush_dcache(vm_offset_t address,unsigned bytes,int physical){
    captured=(bytes==PAGE_SIZE && physical==TRUE)?address:0;
}
uint64_t cache_change(ppnum_t pp){
'''+statement+'''
    return captured;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'address.c').write_text(source)
            subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                root/'address.c','-o',root/'address.so'],check=True,capture_output=True)
            lib=ctypes.CDLL(str(root/'address.so'))
            lib.cache_change.argtypes=[ctypes.c_uint32];lib.cache_change.restype=ctypes.c_uint64
            # The exact observed faultfc598000 was the low32 bits of1fc598000.
            for address in (0,0x80000000,0xffffc000,0x100000000,0x180000000,
                            0x1fc598000,0x1ffffc000,0x3fffffffc000):
                self.assertEqual(lib.cache_change(address>>14),address)
            for address in range(0x180000000,0x200000000,0x4000):
                self.assertEqual(lib.cache_change(address>>14),address)
            # The old cast-after-shift form aliases every Redfin page below4GiB.
            self.assertNotEqual(((0x1fc598000>>14)<<14)&0xffffffff,0x1fc598000)


if __name__=='__main__':unittest.main()
