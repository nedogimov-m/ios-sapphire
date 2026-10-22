"""Run the existing actual-C probe contract against the selectable target overlay."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_cpu_probe as base

HERE = Path(__file__).parent


class CPUTargetTests(base.CPUProbeTests):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        directory = Path(cls.temp.name)
        relative = Path('bsd/dev/redfin_cpu_probe.c')
        source = base.added_file(base.PATCH.read_text(), str(relative))
        (directory / relative).parent.mkdir(parents=True)
        (directory / relative).write_text(source)
        assembly = base.PATCH.read_text().split('diff --git a/osfmk/arm64/start.s', 1)[1].split('\ndiff --git ', 1)[0]
        entry = '\n'.join(line[1:] for line in assembly.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        # Context around the added entry is copied from its original patch.
        initial = '\tmsr\t\tSPSel, #1\n\tb\t\tEXT(LowResetVectorBase)\n' + entry + '\n#endif /* SWEET */\n'
        (directory / 'osfmk/arm64').mkdir(parents=True)
        (directory / 'osfmk/arm64/start.s').write_text(initial)
        subprocess.run(['git', 'apply', '--whitespace=nowarn', str((HERE / 'cpu-target.patch').resolve())],
                       cwd=directory, check=True, capture_output=True)
        cls.production = (directory / relative).read_text()
        cls.assembly = (directory / 'osfmk/arm64/start.s').read_text()
        source = re.sub(r'^#include .*$', '', cls.production, flags=re.M)
        source = re.sub(r'/\* RF_CPU_HW_BEGIN:.*?/\* RF_CPU_HW_END \*/', '', source, flags=re.S)
        source = re.sub(r'^extern unsigned char redfin_cpu_probe_entry\[\],redfin_cpu_probe_entry_end\[\];$', '', source, flags=re.M)
        source = source.replace('static unsigned char rf_cpu_storage[2*RF_CPU_PAGE];',
            'static unsigned char rf_cpu_fixture_storage[4*RF_CPU_PAGE];\n'
            '#define rf_cpu_storage (*(unsigned char (*)[2*RF_CPU_PAGE])'
            '(((((uintptr_t)rf_cpu_fixture_storage+RF_CPU_PAGE-1)&~((uintptr_t)RF_CPU_PAGE-1)))+4096))')
        suffix = base.SUFFIX.replace('RF_CPU_TARGET', 'rf_cpu_target')
        suffix = suffix.replace('ready_fault==3?0x51d0805e:0x51f0804e',
            'ready_fault==3?(rf_cpu_target<0x600?0x51f0804e:0x51d0805e):'
            '(rf_cpu_target<0x600?0x51d0805e:0x51f0804e)')
        suffix = suffix.replace('ready_fault==9?0x100000600ULL:0x600',
                                'ready_fault==9?(0x100000000ULL|rf_cpu_target):rf_cpu_target')
        (directory / 'target.c').write_text(base.PREFIX + source + suffix)
        library = directory / ('target.dylib' if sys.platform == 'darwin' else 'target.so')
        subprocess.run([shutil.which('cc') or 'cc', '-shared', '-fPIC', '-std=c11', '-Wall',
                        '-Wextra', '-Werror', str(directory / 'target.c'), '-o', str(library)],
                       check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.reset.argtypes = [C.c_char_p]
        cls.lib.set_fault.argtypes = [C.c_uint, C.c_uint]
        cls.lib.stat.argtypes = [C.c_uint]
        cls.lib.stat.restype = C.c_uint
        cls.lib.change_args.argtypes = [C.c_char_p]
        cls.lib.select_mailbox.argtypes = [C.c_size_t, C.c_size_t]
        cls.lib.select_mailbox.restype = C.c_size_t
        cls.lib.redfin_cpu_probe.restype = C.c_int

    def test_each_secondary_has_its_actual_affinity_and_expected_part(self):
        for cpu in range(1, 8):
            with self.subTest(cpu=cpu):
                self.lib.reset((base.ARGS + f' redfincputarget=0x{cpu}00').encode())
                self.assertEqual(self.lib.redfin_cpu_probe(), 0)
                self.assertEqual(self.lib.stat(1), 1)
                self.assertEqual(self.lib.stat(6), 0)
                self.assertEqual(self.lib.redfin_cpu_probe(), errno.EBUSY)

    def test_target_is_canonical_unique_and_never_cpu0(self):
        for value in ('', '0', '0x0', '0x000', '0x800', '0x6000', '0X600', '1536',
                      '0x0600', '0x601', '0x100000600', '0x-100', '0x900'):
            self.lib.reset((base.ARGS + ' redfincputarget=' + value).encode())
            self.assertEqual(self.lib.redfin_cpu_probe(), errno.ENOTSUP)
            self.assertEqual(self.lib.stat(0), 0)
        for extra in ('redfincputarget', 'redfincputarget=0x100 redfincputarget=0x600'):
            self.lib.reset((base.ARGS + ' ' + extra).encode())
            self.assertEqual(self.lib.redfin_cpu_probe(), errno.ENOTSUP)
            self.assertEqual(self.lib.stat(0), 0)

    def test_wrong_part_and_foreign_high_affinity_rejected_for_every_target(self):
        for cpu in range(1, 8):
            for fault in (3, 9):
                self.lib.reset((base.ARGS + f' redfincputarget=0x{cpu}00').encode())
                self.lib.set_fault(4, fault)
                self.assertEqual(self.lib.redfin_cpu_probe(), errno.ENOTSUP)
                self.assertEqual(self.lib.stat(1), 1)

    def test_final_entry_keeps_stackless_bounded_stores_and_compiles(self):
        entry = self.assembly.split('/* Secondary capability PSCI entry:', 1)[1].split('#endif', 1)[0]
        entry = '/* Secondary capability PSCI entry:' + entry
        self.assertIn('cmp x3, #0x100\n b.lo Lrf_cpu_probe_park', entry)
        self.assertIn('cmp x3, #0x700\n b.hi Lrf_cpu_probe_park', entry)
        self.assertIn('tst x3, #0xff', entry)
        self.assertNotRegex(entry, r'(?m)^\s*(?:bl|blr|ret|smc)\b')
        self.assertEqual(re.findall(r'^ str x\d+, \[x0, #(\d+)\]', entry, re.M),
                         ['64', '72', '80', '88', '96', '104', '120'])
        if sys.platform != 'darwin':
            return
        macros = '''#define EXT(x) _ ## x
#define LEXT(x) _ ## x ## :
.text
.macro MOV64
 movk $0, #((($1) >> 48) & 0xffff), lsl #48
 movk $0, #((($1) >> 32) & 0xffff), lsl #32
 movk $0, #((($1) >> 16) & 0xffff), lsl #16
 movk $0, #((($1) >> 0) & 0xffff), lsl #0
.endmacro
'''
        directory = Path(self.temp.name)
        source = directory / 'final-entry.S'
        source.write_text(macros + entry)
        subprocess.run([shutil.which('cc') or 'cc', '-arch', 'arm64', '-c', str(source),
                        '-o', str(directory / 'final-entry.o')], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
