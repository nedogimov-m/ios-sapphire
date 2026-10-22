"""Compile the real muted-console writer and preserve binary/newline records."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class MutedLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('cc')
        if not cc: raise unittest.SkipTest('host C compiler unavailable')
        cls.temp=tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        folder=Path(cls.temp.name)
        patch=Path(__file__).with_name('muted-log.patch').read_text()
        added='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        helper=added.split('/* REDFIN_MUTED_LOG_TEST_BEGIN:',1)[1].split('*/',1)[1]
        helper=helper.split('/* REDFIN_MUTED_LOG_TEST_END */',1)[0]
        source=folder/'capture.c'; library=folder/'capture.so'
        source.write_text('''#include <string.h>
static char saved[4096]; static int count;
static void redfin_log_putc(char c) { if(count < (int)sizeof(saved)) saved[count++]=c; }
'''+helper+'''
int capture(const char *data, int size, char *out) {
 count=0; redfin_log_muted_console(data,size); memcpy(out,saved,count); return count;
}
''')
        subprocess.run([cc,'-shared','-fPIC','-Wall','-Wextra','-Werror',str(source),'-o',str(library)],check=True,capture_output=True)
        cls.library=ctypes.CDLL(str(library))
        cls.library.capture.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        cls.library.capture.restype=ctypes.c_int

    def capture(self,data,size=None):
        output=ctypes.create_string_buffer(4096)
        length=self.library.capture(data,len(data) if size is None else size,output)
        return output.raw[:length]

    def test_gui_mute_keeps_diagnostic_and_screen_records(self):
        data=b'REDFIN FB: copied 10108800 bytes\n[REDFIN SCREEN]\nAAECAw==\n'
        self.assertEqual(self.capture(data),data.replace(b'\n',b'\r\n'))

    def test_size_not_nul_controls_copy(self):
        self.assertEqual(self.capture(b'abc\x00\xffrest',5),b'abc\x00\xff')

    def test_empty_or_negative_length_reads_nothing(self):
        self.assertEqual(self.capture(None,0),b'')
        self.assertEqual(self.capture(None,-1),b'')


if __name__=='__main__': unittest.main()
