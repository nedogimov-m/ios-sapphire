"""An installed observer stays inactive without the exact one-boot request."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest


class DisplayBenchmarkTests(unittest.TestCase):
    def test_transient_windows_restart_a_fresh_interval_with_bounded_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);here=Path(__file__).resolve().parent
            source=root/'windows.c'
            source.write_text('''
#include <assert.h>
#include "display-benchmark.h"
int main(void) {
 struct redfin_display_window_state s={0};bool reset=false;
 assert(redfin_display_probe_window(&s,11,0,&reset)==RF_DISPLAY_WINDOW_PENDING&&!reset);
 assert(redfin_display_probe_window(&s,11,1,&reset)==RF_DISPLAY_WINDOW_PENDING);
 assert(redfin_display_probe_window(&s,11,2,&reset)==RF_DISPLAY_WINDOW_READY);
 assert(redfin_display_probe_window(&s,11,2.1,&reset)==RF_DISPLAY_WINDOW_ACTIVE&&!reset);
 assert(redfin_display_probe_window(&s,0,2.2,&reset)==RF_DISPLAY_WINDOW_PENDING&&reset&&s.restarts==1);
 for(unsigned i=0;i<100;++i)assert(redfin_display_probe_window(&s,0,2.3+i/100.,&reset)==RF_DISPLAY_WINDOW_PENDING&&!reset&&s.restarts==1);
 assert(redfin_display_probe_window(&s,22,4,&reset)==RF_DISPLAY_WINDOW_PENDING);
 assert(redfin_display_probe_window(&s,33,5,&reset)==RF_DISPLAY_WINDOW_PENDING);
 assert(redfin_display_probe_window(&s,33,6,&reset)==RF_DISPLAY_WINDOW_PENDING);
 assert(redfin_display_probe_window(&s,33,7,&reset)==RF_DISPLAY_WINDOW_READY&&!reset);
 for(unsigned restart=2;restart<=RF_DISPLAY_PROBE_WINDOW_RESTARTS;++restart) {
  double now=restart*10;
  assert(redfin_display_probe_window(&s,0,now,&reset)==RF_DISPLAY_WINDOW_PENDING&&reset&&s.restarts==restart);
  assert(redfin_display_probe_window(&s,restart+100,now+1,&reset)==RF_DISPLAY_WINDOW_PENDING&&!reset);
  assert(redfin_display_probe_window(&s,restart+100,now+3,&reset)==RF_DISPLAY_WINDOW_READY);
 }
 assert(redfin_display_probe_window(&s,0,100,&reset)==RF_DISPLAY_WINDOW_REFUSED&&reset);
 assert(redfin_display_probe_window(&s,99,200,&reset)==RF_DISPLAY_WINDOW_REFUSED&&!reset);
 return 0;
}
''')
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(here),str(source),'-o',str(root/'windows')],capture_output=True,check=True)
            subprocess.run([str(root/'windows')],capture_output=True,check=True)

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
            controls=b'redfin-probe-v1:12345678abcdef01:controls-checked\n'
            self.assertEqual(library.parse(passive,len(passive),nonce),1)
            self.assertEqual(library.parse(animate,len(animate),nonce),2)
            self.assertEqual(library.parse(checked,len(checked),nonce),3)
            self.assertEqual(library.parse(controls,len(controls),nonce),4)
            for value in (b'',animate[:-1],animate+b'\0',animate+b'\n',animate.replace(b'abcdef',b'ABCDEF'),
                          animate.replace(b'animate',b'forever'),animate.replace(b':123',b':\x00123')):
                self.assertEqual(library.parse(value,len(value),nonce),0)
            for value in (controls[:-1],controls+b'\n',controls.replace(b'checked',b'forever')):
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
            metal=b'REDFIN METAL CHECK EXIT: boot=12345678abcdef01 result=0 full-contract=1\n'
            memory=b'REDFIN GRAPHICS MEMORY: boot=12345678abcdef01 pid=67 phase=checker-after ordinal=1 status=0 words=86\n'
            gpu=b'REDFIN GPU RENDER BOOT: 12345678abcdef01\nREDFIN GPU RENDER RESULT: result=0 hardware=1 draws=2\n'
            call=lambda m,g,n=nonce:lib.ready(m,len(m),g,len(g),n)
            self.assertEqual(call(metal,gpu),1)
            for m,g in ((b'',gpu),(metal,b''),(metal.replace(b'abcdef01',b'abcdef02'),gpu),
                        (metal,gpu.replace(b'abcdef01',b'abcdef02')),(metal,gpu.split(b'REDFIN GPU RENDER RESULT:')[0]),
                        (memory,gpu),(memory.replace(b'ordinal=1',b'ordinal=0'),gpu),
                        (metal[:-1],gpu),(metal,gpu[:-1]),
                        (metal,gpu+b'REDFIN GPU RENDER BOOT: 12345678abcdef02\n')):
                self.assertEqual(call(m,g),0)
            self.assertEqual(call(metal,gpu,nonce+1),0)
            self.assertEqual(call(memory+metal,gpu),1)
            # Another boot's result must never finish our pending GPU job.
            self.assertEqual(call(metal,gpu.split(b'REDFIN GPU RENDER RESULT:')[0]+
                b'REDFIN GPU RENDER BOOT: 12345678abcdef02\n'+gpu.split(b'\n',1)[1]),0)
            for m,g in ((metal.replace(b'result=0',b'result=1'),gpu),
                        (metal.replace(b'full-contract=1',b'full-contract=0'),gpu),
                        (metal.replace(b'result=0',b'result=00'),gpu),
                        (metal+metal.replace(b'result=0',b'result=1'),gpu),
                        (metal,gpu.replace(b'result=0',b'result=1')),
                        (metal,gpu.replace(b'draws=2',b'draws=20')),
                        (metal,gpu+b'REDFIN GPU RENDER FAIL: bad pixels\n')):
                self.assertEqual(call(m,g),2)

            begin=lambda mode:b'REDFIN GLES MODE: boot=12345678abcdef01 mode='+mode+b' hardware-required=1\n'
            end=lambda mode:b'REDFIN GLES MODE RESULT: boot=12345678abcdef01 mode='+mode+b' result=0 hardware=1\n'
            start=gpu.split(b'REDFIN GPU RENDER RESULT:')[0]
            terminal=b'REDFIN GPU RENDER RESULT: result=0 hardware=1 draws=4 modes=gmem,sysmem\n'
            gmem=begin(b'gmem')+end(b'gmem');sysmem=begin(b'sysmem')+end(b'sysmem')
            dual=start+gmem+sysmem+terminal
            self.assertEqual(call(metal,dual),1)
            self.assertEqual(call(metal,start+gmem+sysmem),0)
            self.assertEqual(call(metal,dual[:-1]),0)
            self.assertEqual(call(metal,dual.replace(b'abcdef01',b'abcdef02')),0)
            for value in (start+terminal,start+gmem+terminal,start+sysmem+gmem+terminal,
                          start+gmem+gmem+sysmem+terminal,start+begin(b'gmem')+sysmem+terminal,
                          start+end(b'gmem')+sysmem+terminal,dual+terminal,
                          dual.replace(b'mode=sysmem result=0',b'mode=sysmem result=1'),
                          dual.replace(b'mode=sysmem hardware-required=1',b'mode=sysmem hardware-required=0'),
                          dual.replace(b'draws=4 modes=gmem,sysmem',b'draws=2'),
                          dual.replace(b'draws=4',b'draws=40'),
                          dual+begin(b'gmem')):
                with self.subTest(transcript=value):self.assertEqual(call(metal,value),2)


if __name__=='__main__':unittest.main()
