"""A damaged private system bootstrap fails spawn before launchd's exec event."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.gui_profile import REQUIRED

HERE = Path(__file__).resolve().parent


class PhotosExecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root / 'arm64').mkdir()
        shutil.copy2(HERE / 'gui-profile.h', root / 'arm64/redfin_gui_profile.h')
        (root / 'guard.c').write_text('#include "photos-exec.h"\n'
            'int selected(const char *a,unsigned n,const char *p){return redfin_photos_exec_selected(a,n,p);}\n'
            'int admit(unsigned flags,int platform){return redfin_photos_exec_signature(flags,platform);}\n')
        subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
            '-I', root, '-I', HERE, root / 'guard.c', '-o', root / 'guard.so'],
            check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(root / 'guard.so'))
        cls.lib.selected.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_char_p]
        cls.lib.admit.argtypes = [ctypes.c_uint, ctypes.c_int]

    def test_guard_selects_only_the_complete_gui3_and_exact_saved_native_path(self):
        for mode in (1, 2, 3):
            args = (' '.join(sorted(REQUIRED)).replace('redfingui=1', f'redfingui={mode}') +
                    ' redfinbootid=0x73a9959b7d8084af').encode()
            for path in (b'executable_path=/redfin/bin/photos-init',
                         b'executable_path=/redfin/bin/gui-check',b'executable_path=/redfin/bin/metal-check',
                         b'/redfin/bin/photos-init', b'executable_path=/tmp/photos-init',
                         b'executable_path=/tmp/metal-check',b'executable_path=/redfin/bin/metal-check-other',
                         b'executable_path=/redfin/bin/photos-init-other', None):
                self.assertEqual(self.lib.selected(args, len(args)+1, path),
                    int(mode == 3 and path in (b'executable_path=/redfin/bin/photos-init',
                        b'executable_path=/redfin/bin/gui-check',b'executable_path=/redfin/bin/metal-check')))
            self.assertEqual(self.lib.selected(args, len(args), b'executable_path=/redfin/bin/photos-init'), 0)

    def test_only_actual_valid_signed_platform_and_validated_entitlements_are_admitted(self):
        required = 0x20005201
        self.assertEqual(self.lib.admit(required, 1), 1)
        self.assertEqual(self.lib.admit(required | 2 | 0x4000000, 1), 1)
        for bit in (1, 0x200, 0x1000, 0x4000, 0x20000000):
            self.assertEqual(self.lib.admit(required & ~bit, 1), 0)
        self.assertEqual(self.lib.admit(required, 0), 0)


if __name__ == '__main__':
    unittest.main()
