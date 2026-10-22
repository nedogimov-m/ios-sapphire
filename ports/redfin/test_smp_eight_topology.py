"""Validate the exact eight-core ADT and count-specific loader with actual C."""
import copy
import ctypes
from pathlib import Path
import shutil
import subprocess
import unittest

import test_smp_topology as base

HERE = Path(__file__).parent.resolve()
COMMAND = base.COMMAND.replace('cpus=2', 'cpus=8')


class EightTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.SMPTopologyTests.setUpClass.__func__(cls)
        build = cls.directory / 'eight'
        build.mkdir()
        (build / 'config.h').write_text('#define XNU_PAYLOAD_SIZE 65536\n'
            '#define WATCHDOG_SECONDS 28\n#define SHIM_EARLY_RETURN 1\n'
            '#define REDFIN_SMP_PROBE 1\n#define REDFIN_SMP_CPUS 8\n')
        (build / 'wrapper.c').write_text('#include "loader.c"\n'
            'int profile(const char *s){return smp_command(s);}\n'
            'int adt_profile(const void *p,uint64_t n){return adt_valid_smp(p,n);}\n')
        library = build / 'eight.so'
        result = subprocess.run([cls.compiler, '-shared', '-fPIC', '-std=c11', '-O2',
            '-Wall', '-Wextra', '-Werror', '-DREDFIN_LOADER_TEST', '-I', str(build),
            '-I', str(cls.new), '-I', str(HERE), str(build / 'wrapper.c'), str(HERE / 'fdt.c'),
            '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.profile.argtypes = [ctypes.c_char_p]
        cls.lib.adt_profile.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cls.lib.redfin_validate.argtypes = cls.libraries['both'].redfin_validate.argtypes
        cls.lib.redfin_validate.restype = ctypes.c_char_p
        cls.lib.redfin_fdt.argtypes = cls.libraries['both'].redfin_fdt.argtypes
        cls.lib.redfin_fdt.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def root(self):
        return self.mk.build(base.BASE, base.MEMORY, seed=bytes(64), smp=True, smp_cpus=8)

    def valid(self, root):
        blob = self.mk.adt.serialize(root)
        return self.lib.adt_profile(blob, len(blob))

    def test_all_eight_cpu_properties_and_cache_ids(self):
        root = self.root()
        cpus = base.child(root, 'cpus').children
        self.assertEqual([cpu.name for cpu in cpus], [f'cpu{i}' for i in range(8)])
        for index, cpu in enumerate(cpus):
            self.assertEqual(cpu.prop('reg'), self.mk.u32(index << 8))
            self.assertEqual(cpu.prop('cpu-id'), self.mk.u32(index))
            self.assertEqual(cpu.prop('l2-cache-id'), self.mk.u32(index))
            self.assertEqual(cpu.prop('l3-cache-id'), self.mk.u32(0))
            self.assertEqual(cpu.prop('state'), self.mk.cstr('stopped' if index else 'running'))
        self.assertEqual(self.valid(root), 1)

    def test_every_cpu_field_is_required_unique_and_exact(self):
        original = self.root()
        for cpu in range(8):
            props = base.child(original, 'cpus').children[cpu].props
            for index, (key, flag, value) in enumerate(props):
                for mode in ('remove', 'duplicate', 'change'):
                    root = copy.deepcopy(original)
                    target = base.child(root, 'cpus').children[cpu]
                    if mode == 'remove':
                        del target.props[index]
                    elif mode == 'duplicate':
                        target.props.append((key, flag, value))
                    else:
                        changed = bytes(len(value)) if key == 'AAPL,phandle' else bytes([value[0] ^ 0x80]) + value[1:]
                        target.props[index] = (key, flag, changed)
                    with self.subTest(cpu=cpu, key=key, mode=mode):
                        self.assertEqual(self.valid(root), 0)

    def test_cpu_count_order_and_handles_are_not_interchangeable(self):
        for count in (0, 1, 2, 6, 7, 9):
            root = self.root()
            cpus = base.child(root, 'cpus')
            if count < 8:
                cpus.children = cpus.children[:count]
            else:
                cpus.children.append(copy.deepcopy(cpus.children[-1]))
            self.assertEqual(self.valid(root), 0)
        root = self.root()
        cpus = base.child(root, 'cpus').children
        cpus[1], cpus[6] = cpus[6], cpus[1]
        self.assertEqual(self.valid(root), 0)
        for first in range(8):
            for second in range(first):
                root = self.root()
                cpus = base.child(root, 'cpus').children
                base.prop(cpus[first], 'AAPL,phandle', cpus[second].prop('AAPL,phandle'))
                self.assertEqual(self.valid(root), 0)

    def test_count_specific_command_and_adt_gates(self):
        self.assertEqual(self.lib.profile(COMMAND.encode().ljust(608, b'\0')), 1)
        self.assertEqual(self.lib.profile(base.COMMAND.encode().ljust(608, b'\0')), 0)
        self.assertEqual(self.libraries['both'].profile(COMMAND.encode().ljust(608, b'\0')), 0)
        two = self.mk.build(base.BASE, base.MEMORY, seed=bytes(64), smp=True)
        self.assertEqual(self.valid(two), 0)
        eight = self.mk.adt.serialize(self.root())
        self.assertEqual(self.libraries['both'].adt_profile(eight, len(eight)), 0)

    def test_actual_gcc_eight_core_loader_contains_no_absolute_relocations(self):
        gcc, readelf = shutil.which('aarch64-elf-gcc'), shutil.which('aarch64-elf-readelf')
        if not gcc or not readelf:
            self.skipTest('shim GCC/readelf required')
        target = self.directory / 'eight-gcc.o'
        result = subprocess.run([gcc, '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
            '-fno-pic', '-mgeneral-regs-only', '-mstrict-align', '-fno-stack-protector',
            '-fno-tree-loop-distribute-patterns', '-Wall', '-Wextra', '-Werror',
            '-I', str(self.directory / 'eight'), '-I', str(HERE), '-c', str(self.new / 'loader.c'),
            '-o', str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('R_AARCH64_ABS', subprocess.check_output([readelf, '-r', str(target)], text=True))


if __name__ == '__main__':
    unittest.main()
