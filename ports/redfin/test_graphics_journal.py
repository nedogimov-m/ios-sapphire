"""Only the approved internal HFS journal may reach GUI3 native replay."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from ports.redfin.test_ufs_rw import additions,section,header,PREFIX


def journal_header(start=0x1fba00,end=0x48ba00):
    data=bytearray(512)
    struct.pack_into('<IIQQQIIII',data,0,0x4a4e4c78,0x12345678,start,end,8388608,32768,0,512,1084352)
    checksum=0
    for byte in data[:44]:checksum=((checksum<<8)^(checksum+byte))&0xffffffff
    struct.pack_into('<I',data,36,(~checksum)&0xffffffff)
    return data


class GraphicsJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('host C compiler absent')
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        root=Path(cls.temp.name);board=Path(__file__).resolve().parent
        pure=section((board/'graphics-journal.inc').read_text(),'REDFIN_GRAPHICS_JOURNAL_TEST')
        wrappers='''
int heads(const uint8_t *p,const uint8_t *a){return rf_gj_headers(p,512,a,512);}
int loc(const uint8_t *p,unsigned bytes){uint64_t at=0,size=0;return rf_gj_location(p,bytes,&at,&size)&&at==532480&&size==8388608;}
int jhead(const uint8_t *p,unsigned bytes){return rf_gj_header(p,bytes,8388608);}
'''
        source=PREFIX+'#include <string.h>\n'+section(additions(),'REDFIN_RW_TEST')+pure+wrappers
        (root/'journal.c').write_text(source)
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
            root/'journal.c','-o',root/'journal.so'],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(root/'journal.so'))
        cls.lib.heads.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
        for name in ('loc','jhead'):getattr(cls.lib,name).argtypes=[ctypes.c_void_p,ctypes.c_uint]

    def test_dirty_header_only_and_no_input_bytes_are_modified(self):
        primary,alternate=header(False),header();primary[8:12]=b'HFSJ'
        p=ctypes.create_string_buffer(bytes(primary));a=ctypes.create_string_buffer(bytes(alternate))
        self.assertEqual(self.lib.heads(p,a),1)
        self.assertEqual(p.raw[:512],primary);self.assertEqual(a.raw[:512],alternate)
        for offset,value in ((4,struct.pack('>I',0x80002900)),(8,b'FSK!'),(12,struct.pack('>I',130)),
                             (40,struct.pack('>I',8192)),(44,struct.pack('>I',1))):
            bad=primary.copy();bad[offset:offset+len(value)]=value
            self.assertEqual(self.lib.heads(bytes(bad),bytes(alternate)),0)
        primary[6]|=1
        self.assertEqual(self.lib.heads(bytes(primary),bytes(alternate)),0)

    def test_external_uninitialized_or_out_of_fence_journals_are_refused(self):
        jib=bytearray(512);struct.pack_into('>I',jib,0,1);struct.pack_into('>QQ',jib,36,532480,8388608)
        self.assertEqual(self.lib.loc(bytes(jib),512),1)
        for offset,value in ((0,struct.pack('>I',2)),(0,struct.pack('>I',5)),(4,b'X'),
                            (36,struct.pack('>Q',16*1024**3-4096)),(44,struct.pack('>Q',16*1024**3))):
            bad=jib.copy();bad[offset:offset+len(value)]=value
            self.assertEqual(self.lib.loc(bytes(bad),512),0)
        self.assertEqual(self.lib.loc(bytes(jib),51),0)

    def test_empty_and_committed_rings_require_exact_native_header_checksum(self):
        for start,end in ((2079232,4766208),(2079232,2079232),(8388608,512)):
            h=journal_header(start,end);self.assertEqual(self.lib.jhead(bytes(h),512),1)
        h=journal_header()
        for offset in range(44):
            bad=h.copy();bad[offset]^=0xff
            self.assertEqual(self.lib.jhead(bytes(bad),512),0,offset)
        for start,end in ((0,512),(511,512),(512,8389120),(1025,512)):
            h=journal_header(start,end);self.assertEqual(self.lib.jhead(bytes(h),512),0)
        self.assertEqual(self.lib.jhead(bytes(journal_header()),511),0)


if __name__=='__main__':unittest.main()
