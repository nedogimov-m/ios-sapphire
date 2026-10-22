"""Requested protected return tests never fall through to other writers."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class EarlyReturnDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        patch = Path(__file__).with_name('early-return-start.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        actual = added.split('/* REDFIN_EARLY_RETURN_DISPATCH_BEGIN */', 1)[1].split(
            '/* REDFIN_EARLY_RETURN_DISPATCH_END */', 1)[0]
        prefix = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const char *args;
static int calls,legacy,error;
static const char *PE_boot_args(void){return args;}
static int redfin_early_return_probe(void){calls++;return error;}
static void IOLog(const char *,...){}
static void dispatch(void){
'''
        suffix = r'''
 legacy++;
}
int main(int argc,char **argv){
 if(argc!=3)return 2;
 args=argv[1];error=atoi(argv[2]);
 for(int i=0;i<3;i++)dispatch();
 printf("%d %d\n",calls,legacy);return 0;
}
'''
        source = root / 'dispatch.cpp'
        source.write_text(prefix + actual + suffix)
        cls.exe = root / 'dispatch'
        subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17', '-Wall', '-Wextra',
                        '-Werror', str(source), '-o', str(cls.exe)], check=True, capture_output=True)

    def test_absent_mode_preserves_dispatch(self):
        for text in ('', 'cpus=1 rd=md0', 'redfinearlyreturn_extra=1', 'redfinearlyretur=1'):
            self.assertEqual(subprocess.check_output([str(self.exe), text, '0']), b'0 3\n')

    def test_malformed_or_failed_mode_is_exclusive_and_once_only(self):
        for mode, error in (('redfinearlyreturn=1', 0), ('redfinearlyreturn=1', 5),
                            ('redfinearlyreturn', 45), ('redfinearlyreturn=0', 45),
                            ('redfinearlyreturn=2', 45), ('redfinearlyreturn=4294967296', 45),
                            ('redfinearlyreturn=garbage', 45), ('redfinearlyreturn=1 redfincpu=1', 45)):
            with self.subTest(mode=mode, error=error):
                self.assertEqual(subprocess.check_output([str(self.exe), mode, str(error)]), b'1 0\n')


if __name__ == '__main__':
    unittest.main()
