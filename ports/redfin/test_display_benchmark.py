"""An installed observer stays inactive without the exact one-boot request."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest


class DisplayBenchmarkTests(unittest.TestCase):
    def test_bounded_request_modes_require_a_complete_matching_boot_nonce(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);here=Path(__file__).resolve().parent
            (root/'request.c').write_text('''
#include "display-benchmark.h"
unsigned parse(const char *data,size_t bytes,uint64_t nonce){return redfin_display_probe_request(data,bytes,nonce);}
''')
            compiled=subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                '-I'+str(here),str(root/'request.c'),'-o',str(root/'request.so')],capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr.decode(errors='replace'))
            library=C.CDLL(str(root/'request.so'));library.parse.argtypes=[C.c_char_p,C.c_size_t,C.c_uint64]
            nonce=0x12345678abcdef01
            passive=b'redfin-probe-v1:12345678abcdef01:passive\n'
            animate=b'redfin-probe-v1:12345678abcdef01:animate\n'
            self.assertEqual(library.parse(passive,len(passive),nonce),1)
            self.assertEqual(library.parse(animate,len(animate),nonce),2)
            for value in (b'',animate[:-1],animate+b'\0',animate+b'\n',animate.replace(b'abcdef',b'ABCDEF'),
                          animate.replace(b'animate',b'forever'),animate.replace(b':123',b':\x00123')):
                self.assertEqual(library.parse(value,len(value),nonce),0)
            self.assertEqual(library.parse(animate,len(animate),0),0)
            self.assertEqual(library.parse(animate,len(animate),nonce+1),0)
            self.assertEqual(library.parse(None,len(animate),nonce),0)


if __name__=='__main__':unittest.main()
