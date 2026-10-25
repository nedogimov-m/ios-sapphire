"""Readback diagnostics must reject corrupt pixels and mixed boot records."""
import base64
import ctypes
import importlib.util
from pathlib import Path
import random
import re
import subprocess
import tempfile
import unittest
import zlib

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('metal_draw_decoder',HERE/'decode-metal-draws.py')
decoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(decoder)


class MetalTraceTests(unittest.TestCase):
    def record(self,boot='0123456789abcdef',frame=1):
        rgb=bytes(range(48))
        return (f'REDFIN METAL DRAW IMAGE: boot={boot} frame={frame} draw=2 role=OUTPUT slot=0 '
            f'surface=7 format=80 source=16x16 width=4 height=4 raw=48 crc32={zlib.crc32(rgb)&0xffffffff:08x} data='.encode()+
            base64.b64encode(rgb)+b'\n')

    def test_decoder_keeps_actual_pixels_and_only_the_selected_boot(self):
        records=decoder.decode(self.record('fedcba9876543210')+self.record(),'0123456789abcdef')
        self.assertEqual(len(records),1);self.assertEqual(records[0][1],bytes(range(48)))
        self.assertTrue(decoder.png(records[0][1],4,4).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_corruption_dimensions_duplicate_and_out_of_order_frames_are_refused(self):
        valid=self.record()
        for data in [valid.replace(b'raw=48',b'raw=49'),valid.replace(b'width=4',b'width=81'),
            valid.replace(b'data=A',b'data=B'),valid+valid,self.record(frame=2),valid[:-2],valid.replace(b'draw=2 ',b'draw=8193 ')]:
            with self.assertRaises(ValueError):decoder.decode(data,'0123456789abcdef')

    def test_completed_command_image_keeps_its_real_role_and_later_draw_number(self):
        record=self.record().replace(b'role=OUTPUT',b'role=FINAL').replace(b'draw=2 ',b'draw=1724 ')
        result=decoder.decode(record,'0123456789abcdef')
        self.assertEqual(result[0][0]['role'],'FINAL');self.assertEqual(result[0][0]['draw'],1724)

    def test_actual_native_crc_matches_independent_zlib_for_readback_lengths(self):
        native=(HERE/'metal-composition-trace.inc').read_text()
        function=re.search(r'static uint32_t\nrwa_redfin_trace_crc\(.*?\n\}',native,re.S).group()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'crc.c'
            source.write_text('#include <stdint.h>\n#include <stddef.h>\n'+function+
                '\nuint32_t checked(const uint8_t *p,size_t n){return rwa_redfin_trace_crc(p,n);}\n')
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                str(source),'-o',str(root/'crc.so')],check=True,capture_output=True)
            lib=ctypes.CDLL(str(root/'crc.so'));lib.checked.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
            lib.checked.restype=ctypes.c_uint32;rng=random.Random(0x620)
            for n in [0,1,3,48,512,80*65*3,80*174*3]:
                raw=rng.randbytes(n);self.assertEqual(lib.checked(raw,len(raw)),zlib.crc32(raw)&0xffffffff)


if __name__=='__main__':unittest.main()
