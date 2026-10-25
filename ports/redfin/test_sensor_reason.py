"""Native SMEM423 failure capture is bounded, stable and strictly readonly."""
import ctypes as C
import errno
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from test_wifi_smem import fixture,TOC,SIZE,PART

HERE=Path(__file__).resolve().parent
GLOBAL=0x1000
GLOBAL_BYTES=PART-GLOBAL


def reason_fixture(reason=b'actual DSP failure\0',duplicate=False):
    data=fixture(False)
    struct.pack_into('<I',data,TOC+8,2)
    struct.pack_into('<IIIHHI',data,TOC+80,GLOBAL,GLOBAL_BYTES,0,0xfffe,0xfffe,32)
    size=(len(reason)+7)&~7;cursor=32
    for _ in range(2 if duplicate else 1):
        struct.pack_into('<HHIHHI',data,GLOBAL+cursor,0xa5a5,423,size,0,0,0)
        data[GLOBAL+cursor+16:GLOBAL+cursor+16+len(reason)]=reason
        cursor+=16+size
    struct.pack_into('<4sHHIII',data,GLOBAL,b'$PRT',0xfffe,0xfffe,GLOBAL_BYTES,cursor,GLOBAL_BYTES)
    return data


class SensorReasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        p=Path(cls.temp.name);(p/'reason.c').write_text('#include "wifi_smem.h"\n#include "sensor-reason.h"\n'
            'int capture(const uint8_t *p,size_t n,char *out){return rf_sensor_reason(p,n,out);}\n')
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                        '-I',str(HERE),str(p/'reason.c'),'-o',str(p/'reason.so')],check=True,capture_output=True)
        cls.lib=C.CDLL(str(p/'reason.so'));cls.lib.capture.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p]

    def capture(self,data,size=None):
        before=bytes(data);memory=C.create_string_buffer(before);output=C.create_string_buffer(256)
        result=self.lib.capture(memory,len(data) if size is None else size,output)
        self.assertEqual(memory.raw[:-1],before,'capture must not clear the reason or change allocator state')
        return result,output.value

    def test_actual_global_failure_reason_is_returned_without_touching_dsp_memory(self):
        self.assertEqual(self.capture(reason_fixture()),(0,b'actual DSP failure'))

    def test_missing_empty_wrong_item_or_private_only_reason_is_not_manufactured(self):
        self.assertEqual(self.capture(fixture(False))[0],errno.ENOENT)
        self.assertEqual(self.capture(reason_fixture(b'\0'))[0],errno.ENOENT)
        data=reason_fixture();struct.pack_into('<H',data,GLOBAL+34,422)
        self.assertEqual(self.capture(data)[0],errno.ENOENT)
        data=reason_fixture();struct.pack_into('<HH',data,TOC+92,0,1)
        self.assertNotEqual(self.capture(data)[0],0)

    def test_truncation_and_control_characters_cannot_escape_the_native_output_bound(self):
        self.assertEqual(self.capture(reason_fixture(b'a'*1024))[1],b'a'*255)
        self.assertEqual(self.capture(reason_fixture(b'line1\nline2\t\xff\0')),(0,b'line1 line2  '))

    def test_duplicate_items_or_global_partitions_are_rejected(self):
        self.assertEqual(self.capture(reason_fixture(duplicate=True))[0],errno.EINVAL)
        data=reason_fixture();struct.pack_into('<I',data,TOC+8,3)
        data[TOC+128:TOC+176]=data[TOC+80:TOC+128]
        self.assertNotEqual(self.capture(data)[0],0)

    def test_invalid_sizes_allocator_headers_and_payload_ranges_never_read_a_reason(self):
        for offset,value in [(TOC+80,SIZE-16),(GLOBAL+8,GLOBAL_BYTES-1),(GLOBAL+12,31),
                             (GLOBAL+12,GLOBAL_BYTES+1),(GLOBAL+16,32),(GLOBAL+36,0xffffffff)]:
            data=reason_fixture();struct.pack_into('<I',data,offset,value)
            self.assertNotEqual(self.capture(data)[0],0)
        self.assertEqual(self.capture(reason_fixture(),SIZE-1)[0],errno.EINVAL)
