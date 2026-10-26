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
            checked=b'redfin-probe-v1:12345678abcdef01:animate-checked\n'
            self.assertEqual(library.parse(passive,len(passive),nonce),1)
            self.assertEqual(library.parse(animate,len(animate),nonce),2)
            self.assertEqual(library.parse(checked,len(checked),nonce),3)
            for value in (b'',animate[:-1],animate+b'\0',animate+b'\n',animate.replace(b'abcdef',b'ABCDEF'),
                          animate.replace(b'animate',b'forever'),animate.replace(b':123',b':\x00123')):
                self.assertEqual(library.parse(value,len(value),nonce),0)
            self.assertEqual(library.parse(animate,len(animate),0),0)
            self.assertEqual(library.parse(animate,len(animate),nonce+1),0)
            self.assertEqual(library.parse(None,len(animate),nonce),0)

    def test_combined_measurement_requires_both_success_markers_in_the_current_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);here=Path(__file__).resolve().parent
            (root/'ready.c').write_text('''
#include "display-benchmark.h"
unsigned ready(const char *m,size_t mb,const char *g,size_t gb,uint64_t n){
 return redfin_display_probe_checks(m,mb,g,gb,n);}
''')
            subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                '-I'+str(here),str(root/'ready.c'),'-o',str(root/'ready.so')],capture_output=True,check=True)
            lib=C.CDLL(str(root/'ready.so'))
            lib.ready.argtypes=[C.c_char_p,C.c_size_t,C.c_char_p,C.c_size_t,C.c_uint64]
            nonce=0x12345678abcdef01
            metal=b'REDFIN GRAPHICS MEMORY: boot=12345678abcdef01 pid=67 phase=checker-after ordinal=0 status=0 words=86\\n'.replace(b'\\n',b'\n')
            gpu=b'REDFIN GPU RENDER BOOT: 12345678abcdef01\nREDFIN GPU RENDER RESULT: result=0 hardware=1 draws=2\n'
            call=lambda m,g,n=nonce:lib.ready(m,len(m),g,len(g),n)
            self.assertEqual(call(metal,gpu),1)
            for m,g in ((b'',gpu),(metal,b''),(metal.replace(b'abcdef01',b'abcdef02'),gpu),
                        (metal,gpu.replace(b'abcdef01',b'abcdef02')),(metal,gpu.split(b'REDFIN GPU RENDER RESULT:')[0])):
                self.assertEqual(call(m,g),0)
            self.assertEqual(call(metal,gpu,nonce+1),0)
            for m,g in ((metal.replace(b'status=0',b'status=1'),gpu),
                        (metal,gpu.replace(b'result=0',b'result=1')),
                        (metal,gpu.replace(b'draws=2',b'draws=20')),
                        (metal,gpu+b'REDFIN GPU RENDER FAIL: bad pixels\n')):
                self.assertEqual(call(m,g),2)


if __name__=='__main__':unittest.main()
