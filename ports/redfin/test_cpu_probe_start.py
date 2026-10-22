"""Compile the actual CPU probe dispatch; failures must not start other probes."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class CPUProbeDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        patch = Path(__file__).with_name('cpu-probe-start.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        actual = added.split('/* REDFIN_CPU_PROBE_DISPATCH_TEST_BEGIN */', 1)[1].split(
            '/* REDFIN_CPU_PROBE_DISPATCH_TEST_END */', 1)[0]
        prefix = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const char *args;
static int calls, legacy, error;
static const char *PE_boot_args(void) { return args; }
static int redfin_cpu_probe(void) { ++calls; return error; }
static void IOLog(const char *, ...) {}
static void dispatch(void) {
'''
        suffix = r'''
 ++legacy;
}
int main(int argc, char **argv) {
 if(argc!=3) return 2;
 args=argv[1]; error=atoi(argv[2]);
 for(int i=0;i<3;++i) dispatch();
 printf("%d %d\n",calls,legacy); return 0;
}
'''
        source = root / 'dispatch.cpp'
        source.write_text(prefix + actual + suffix)
        cls.executable = root / 'dispatch'
        subprocess.run([shutil.which('clang++') or 'c++', '-std=c++17', '-Wall',
                        '-Wextra', '-Werror', str(source), '-o', str(cls.executable)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_disabled_probe_preserves_ordinary_dispatch(self):
        for args in ('', 'cpus=1 rd=md0', 'redfincpu_extra=1'):
            with self.subTest(args=args):
                self.assertEqual(subprocess.check_output([str(self.executable), args, '0']), b'0 3\n')

    def test_probe_is_once_only_and_never_falls_through_even_on_failure(self):
        for mode, error in (('redfincpu=1', 0), ('redfincpu=1', 6),
                            ('redfincpu=2', 45), ('redfincpu=4294967296', 22),
                            ('redfincpu=garbage', 22), ('redfincpu', 45),
                            ('cpus=1 redfincpu=0', 45)):
            with self.subTest(mode=mode, error=error):
                self.assertEqual(subprocess.check_output(
                    [str(self.executable), str(mode), str(error)]), b'1 0\n')


if __name__ == '__main__':
    unittest.main()
