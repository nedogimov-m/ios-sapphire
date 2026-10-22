"""Apply the staged SMP topology patch in a temporary tree; test actual C.

No shared sources, device operations or kernel artifacts are changed. Both
before and after integration, reconstruct the old/new loader to check UP
equivalence using synthetic Mach-O, FDT and ADT data only.
"""
import copy
import ctypes
import importlib.util
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest
import warnings

from test_fdt import Hardware, tree
from test_loader import mock_kernel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAGE = 0x4000
BASE, MEMORY = 0x180000000, 0x80000000
TOKENS = (
    'debug=0xc serial=3 cpus=2 keepsyms=1 -noprogress rd=md0 '
    'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
    'modem=0 wifi=0 gpu=0 redfinsmp=1 redfinshim=1 redfinspmi=0 '
    'redfinreturn=0 redfinbootid=0x123456789abcdef0'
).split()
COMMAND = ' '.join(TOKENS)


def child(root, name):
    return next(node for node in root.children if node.name == name)


def prop(node, name, value):
    node.props = [(key, flag, value if key == name else old)
                  for key, flag, old in node.props]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class SMPTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang') or shutil.which('cc')
        patch = shutil.which('patch')
        if not cls.compiler or not patch:
            raise unittest.SkipTest('host compiler and patch required')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        staging = cls.directory / 'stage' / 'ports' / 'redfin'
        staging.mkdir(parents=True)
        files = ('mkadt.py', 'loader.c')
        for name in files:
            shutil.copyfile(HERE / name, staging / name)
        args = [patch, '-p1', '-f', '-s', '-i', str(HERE / 'smp-topology.patch')]
        result = subprocess.run(args, cwd=staging.parents[1], capture_output=True)
        if result.returncode:
            # The root may already have integrated this exact patch.
            for name in files:
                shutil.copyfile(HERE / name, staging / name)
            subprocess.run([*args, '-R'], cwd=staging.parents[1],
                           check=True, capture_output=True)
            old = {name: (staging / name).read_text() for name in files}
            subprocess.run(args, cwd=staging.parents[1], check=True, capture_output=True)
        else:
            old = {name: (HERE / name).read_text() for name in files}
        cls.old = cls.directory / 'old'
        cls.old.mkdir()
        for name, contents in old.items():
            (cls.old / name).write_text(contents)
        cls.new = staging
        cls.mk = module(staging / 'mkadt.py', 'smp_patched_mkadt')
        cls.before = module(cls.old / 'mkadt.py', 'smp_baseline_mkadt')
        cls.libraries = {}
        for label, source, shim, smp in (
            ('old', cls.old, None, None), ('both', staging, 1, 1),
            ('neither', staging, None, None), ('shim', staging, 1, None),
            ('smp', staging, None, 1), ('shim_zero', staging, 0, 1),
            ('smp_zero', staging, 1, 0), ('wrong_values', staging, 2, 2),
        ):
            build = cls.directory / ('build_' + label)
            build.mkdir()
            config = '#define XNU_PAYLOAD_SIZE 65536\n#define WATCHDOG_SECONDS 30\n'
            if shim is not None:
                config += f'#define SHIM_EARLY_RETURN {shim}\n'
            if smp is not None:
                config += f'#define REDFIN_SMP_PROBE {smp}\n'
            (build / 'config.h').write_text(config)
            wrapper = '#include "loader.c"\n'
            if label != 'old':
                wrapper += '''
int profile(const char *p) { return smp_command(p); }
int requested(const char *p) { return smp_requested(p); }
int adt_profile(const void *p, uint64_t n) { return adt_valid_smp(p,n); }
'''
            (build / 'wrapper.c').write_text(wrapper)
            library = build / 'loader.so'
            subprocess.run([cls.compiler, '-std=c11', '-O2', '-shared', '-fPIC',
                            '-Wall', '-Wextra', '-Werror', '-DREDFIN_LOADER_TEST',
                            '-I', str(build), '-I', str(source), '-I', str(HERE),
                            str(build / 'wrapper.c'), str(HERE / 'fdt.c'), '-o', str(library)],
                           check=True, capture_output=True)
            lib = ctypes.CDLL(str(library))
            lib.redfin_validate.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64,
                                            ctypes.c_uint64, ctypes.c_uint64,
                                            ctypes.POINTER(Hardware), ctypes.c_uint64]
            lib.redfin_validate.restype = ctypes.c_char_p
            lib.redfin_fdt.argtypes = [ctypes.c_void_p, ctypes.POINTER(Hardware)]
            lib.redfin_fdt.restype = ctypes.c_int
            if label != 'old':
                lib.profile.argtypes = [ctypes.c_char_p]
                lib.profile.restype = ctypes.c_int
                lib.requested.argtypes = [ctypes.c_char_p]
                lib.requested.restype = ctypes.c_int
                lib.adt_profile.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
                lib.adt_profile.restype = ctypes.c_int
            cls.libraries[label] = lib
        cls.kernel = cls.directory / 'kernel'
        cls.kernel.write_bytes(mock_kernel())
        cls.ramdisk = cls.directory / 'init'
        cls.ramdisk.write_bytes(b'static Darwin PID1 placeholder')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.fdt = ctypes.create_string_buffer(tree(banks=[(BASE, MEMORY)]))
        self.hw = Hardware()
        self.assertEqual(self.libraries['both'].redfin_fdt(self.fdt, ctypes.byref(self.hw)), 0)

    def root(self, smp=True, **kwargs):
        return self.mk.build(BASE, MEMORY, seed=bytes(64), smp=smp, **kwargs)

    def payload(self, root=None, command=COMMAND):
        from tools import mkpayload
        path = self.directory / 'input.adt'
        path.write_bytes(self.mk.adt.serialize(self.root() if root is None else root))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            return mkpayload.build(self.kernel, path, command, self.ramdisk)[0]

    def check(self, payload=None, label='both', mpidr=0):
        data = self.payload() if payload is None else payload
        storage = ctypes.create_string_buffer(len(data) + PAGE)
        source = (ctypes.addressof(storage) + PAGE - 1) & ~(PAGE - 1)
        ctypes.memmove(source, data, len(data))
        return self.libraries[label].redfin_validate(
            source, len(data), source - PAGE, source + len(data),
            ctypes.addressof(self.fdt), ctypes.byref(self.hw), mpidr)

    def direct(self, root):
        blob = self.mk.adt.serialize(root)
        return self.libraries['both'].adt_profile(blob, len(blob))

    def profile(self, command, label='both'):
        raw = command.encode() if isinstance(command, str) else command
        self.assertLessEqual(len(raw), 608)
        return self.libraries[label].profile(raw.ljust(608, b'\0'))

    def test_frozen_topology_and_up_bytes_unchanged(self):
        for mpidr in range(0, 0x800, 0x100):
            for base, size in ((BASE, MEMORY), (0x200000000, 0x40000000)):
                for seed in (bytes(64), bytes(range(64))):
                    with self.subTest(mpidr=mpidr, base=base, seed=seed[:2]):
                        old = self.before.build(base, size, mpidr, seed)
                        implicit = self.mk.build(base, size, mpidr, seed)
                        explicit = self.mk.build(base, size, mpidr, seed, smp=False)
                        self.assertEqual(self.mk.adt.serialize(old), self.mk.adt.serialize(implicit))
                        self.assertEqual(self.mk.adt.serialize(old), self.mk.adt.serialize(explicit))
        cpus = child(self.root(), 'cpus').children
        self.assertEqual([cpu.name for cpu in cpus], ['cpu0', 'cpu1'])
        for index, cpu in enumerate(cpus):
            for key, expected in {'reg': index * 0x600, 'cpu-id': index,
                                  'cluster-id': 0, 'cluster-type': 0, 'die-cluster-id': 0,
                                  'cluster-core-id': index, 'l2-cache-id': index,
                                  'l3-cache-id': 0, 'l2-cache-size': 0, 'l3-cache-size': 0}.items():
                self.assertEqual(cpu.prop(key), self.mk.u32(expected))
            self.assertEqual(cpu.prop('state'), self.mk.cstr('stopped' if index else 'running'))
        self.assertEqual(self.direct(self.root()), 1)

    def test_smp_generator_rejects_noncanonical_ram_boot_cpu_and_bool(self):
        for base, size, boot in ((BASE + PAGE, MEMORY, 0), (BASE, MEMORY - PAGE, 0),
                                  (BASE, MEMORY, 0x600), (0x200000000, MEMORY, 0)):
            with self.subTest(base=base, size=size, boot=boot), self.assertRaises(ValueError):
                self.mk.build(base, size, boot, bytes(64), smp=True)
        for smp in (None, 0, 1, 'true'):
            with self.subTest(smp=smp), self.assertRaises(ValueError):
                self.mk.build(BASE, MEMORY, seed=bytes(64), smp=smp)

    def test_smp_requires_both_exact_compiled_gates(self):
        self.assertIsNone(self.check())
        for label in ('old', 'neither', 'shim', 'smp', 'shim_zero', 'smp_zero', 'wrong_values'):
            with self.subTest(label=label):
                self.assertIsNotNone(self.check(label=label))
                if label != 'old':
                    self.assertEqual(self.profile(COMMAND, label), 0)

    def test_profile_requires_every_frozen_token_and_forbids_duplicates(self):
        self.assertEqual(self.profile(COMMAND), 1)
        self.assertEqual(self.profile(COMMAND + ' -enable_kprintf_spam'), 1)
        self.assertEqual(self.profile(' '.join(reversed(TOKENS))), 1)
        for index, token in enumerate(TOKENS):
            with self.subTest(missing=token):
                self.assertEqual(self.profile(' '.join(TOKENS[:index] + TOKENS[index + 1:])), 0)
            with self.subTest(duplicate=token):
                self.assertEqual(self.profile(COMMAND + ' ' + token), 0)
            with self.subTest(changed=token):
                self.assertEqual(self.profile(' '.join(TOKENS[:index] + [token + '0'] + TOKENS[index + 1:])), 0)
        self.assertEqual(self.profile(COMMAND + ' -enable_kprintf_spam -enable_kprintf_spam'), 0)

    def test_profile_rejects_other_writers_parsing_aliases_and_hidden_tail(self):
        for bad in ('redfincpu=0', 'redfinearlyreturn=0', 'redfinufs=0', 'redfinfb=0',
                    'redfintouch=0', 'redfinshutdown=0', 'redfinusb=0', 'ufsrw=0',
                    'rootrw=0', 'sweetlog=0', 'sweetsample=-', 'redfinspmi=1',
                    'redfinreturn=1', 'unknown=0'):
            with self.subTest(token=bad):
                self.assertEqual(self.profile(COMMAND + ' ' + bad), 0)
                self.assertIsNotNone(self.check(self.payload(command=COMMAND + ' ' + bad)))
        for replacement in ('redfinsmp', 'redfinsmp=0', 'redfinsmp=01', 'redfinsmp=4294967297',
                            'redfinsmp=garbage', 'redfinsmp=1=1'):
            command = COMMAND.replace('redfinsmp=1', replacement)
            self.assertEqual(self.profile(command), 0)
            self.assertEqual(self.libraries['both'].requested(command.encode().ljust(608, b'\0')), 1)
            self.assertIsNotNone(self.check(self.payload(command=command)))
        for separator in ('\n', '\r', '\t', '\x1f', '\x7f'):
            self.assertEqual(self.profile(COMMAND.replace(' ', separator, 1)), 0)
        self.assertEqual(self.profile(COMMAND.encode() + b'\0redfinufs=3'), 0)
        self.assertEqual(self.profile(b'x' * 608), 0)

    def test_boot_id_is_exact_nonzero_u64(self):
        for value in ('0x0000000000000000', '0x1', '0x0123456789abcdeff',
                      '0X123456789abcdef0', '123456789abcdef0', '0x123456789abcdeg0',
                      '0xABCDEF0123456789', '0x123456789abcdeF0'):
            with self.subTest(value=value):
                self.assertEqual(self.profile(COMMAND.replace('0x123456789abcdef0', value)), 0)
        for value in ('0x0000000000000001', '0xffffffffffffffff'):
            self.assertEqual(self.profile(COMMAND.replace('0x123456789abcdef0', value)), 1)

    def test_every_cpu_property_is_required_unique_and_exact(self):
        original = self.root()
        for cpu_index in (0, 1):
            for index, (key, flag, value) in enumerate(child(original, 'cpus').children[cpu_index].props):
                for operation in ('remove', 'duplicate', 'wrong', 'flag', 'length'):
                    root = copy.deepcopy(original)
                    cpu = child(root, 'cpus').children[cpu_index]
                    if operation == 'remove':
                        del cpu.props[index]
                    elif operation == 'duplicate':
                        cpu.props.append(cpu.props[index])
                    elif operation == 'wrong':
                        changed = (bytes(4) if key == 'AAPL,phandle' else
                                   bytes([value[0] ^ 0x80]) + value[1:])
                        cpu.props[index] = key, flag, changed
                    elif operation == 'flag':
                        cpu.props[index] = key, 1, value
                    else:
                        cpu.props[index] = key, flag, value + b'\0'
                    with self.subTest(cpu=cpu_index, key=key, operation=operation):
                        self.assertEqual(self.direct(root), 0)
                        self.assertIsNotNone(self.check(self.payload(root=root)))

    def test_shape_state_affinity_logical_cache_and_handle_uniqueness(self):
        for mutation in ('one', 'three', 'swapped', 'duplicate_cpu', 'nested_cpu',
                         'both_running', 'both_stopped', 'physical_duplicate', 'logical_duplicate',
                         'l2_duplicate', 'different_l3', 'same_handle', 'unknown_cpu_property'):
            root = self.root()
            cpus = child(root, 'cpus')
            a, b = cpus.children
            if mutation == 'one':
                cpus.children.pop()
            elif mutation == 'three':
                cpus.children.append(copy.deepcopy(b))
            elif mutation == 'swapped':
                cpus.children.reverse()
            elif mutation == 'duplicate_cpu':
                cpus.children[1] = copy.deepcopy(a)
            elif mutation == 'nested_cpu':
                b.children.append(copy.deepcopy(a))
            elif mutation == 'both_running':
                prop(b, 'state', b'running\0')
            elif mutation == 'both_stopped':
                prop(a, 'state', b'stopped\0')
            elif mutation == 'physical_duplicate':
                prop(b, 'reg', self.mk.u32(0))
            elif mutation == 'logical_duplicate':
                prop(b, 'cpu-id', self.mk.u32(0))
            elif mutation == 'l2_duplicate':
                prop(b, 'l2-cache-id', self.mk.u32(0))
            elif mutation == 'different_l3':
                prop(b, 'l3-cache-id', self.mk.u32(1))
            elif mutation == 'same_handle':
                prop(b, 'AAPL,phandle', a.prop('AAPL,phandle'))
            else:
                b.props.append(('unproven-property', 0, self.mk.u32(0)))
            with self.subTest(mutation=mutation):
                self.assertEqual(self.direct(root), 0)
                self.assertIsNotNone(self.check(self.payload(root=root)))

    def test_cpu_container_shape_root_uniqueness_and_extra_driver_nodes(self):
        for key in ('#address-cells', '#size-cells', 'AAPL,phandle'):
            for operation in ('remove', 'duplicate', 'bad'):
                root = self.root()
                cpus = child(root, 'cpus')
                if operation == 'remove':
                    cpus.props = [entry for entry in cpus.props if entry[0] != key]
                elif operation == 'duplicate':
                    cpus.props.append(next(entry for entry in cpus.props if entry[0] == key))
                else:
                    prop(cpus, key, b'')
                with self.subTest(key=key, operation=operation):
                    self.assertEqual(self.direct(root), 0)
        for name in ('cpus', 'chosen', 'defaults', 'arm-io'):
            root = self.root()
            root.children.append(copy.deepcopy(child(root, name)))
            self.assertEqual(self.direct(root), 0)
            root = self.root()
            root.children = [node for node in root.children if node.name != name]
            self.assertEqual(self.direct(root), 0)
        for name in ('redfin-ufs', 'sweet-fbcon', 'redfin-touch', 'gpu', 'wifi'):
            root = self.root()
            root.children.append(self.mk.node(name))
            self.assertEqual(self.direct(root), 0)
            root = self.root()
            child(root, 'arm-io').children.append(self.mk.node(name))
            self.assertEqual(self.direct(root), 0)

    def test_ram_cpu_command_topology_cannot_be_downgraded_to_up(self):
        smp = self.payload()
        for command in ('cpus=2 rd=md0', COMMAND.replace('redfinsmp=1', ''),
                        COMMAND.replace('redfinsmp=1', 'redfinsmp_extra=1')):
            self.assertIsNotNone(self.check(self.payload(command=command)))
        self.assertIsNotNone(self.check(self.payload(root=self.root(smp=False))))
        for mpidr in (1, 0x100, 0x600, 0x800, 1 << 32):
            self.assertIsNotNone(self.check(smp, mpidr=mpidr))
        for offset, value in ((56, BASE + PAGE), (64, MEMORY - PAGE), (64, PAGE)):
            changed = bytearray(smp)
            struct.pack_into('<Q', changed, offset, value)
            self.assertIsNotNone(self.check(bytes(changed)))
        for key in ('dram-base', 'dram-size'):
            root = self.root()
            prop(child(root, 'chosen'), key, self.mk.u64(0))
            self.assertEqual(self.direct(root), 0)

    def test_up_validator_results_match_baseline_for_valid_and_mutated_payloads(self):
        for mpidr in range(0, 0x800, 0x100):
            root = self.mk.build(BASE, MEMORY, mpidr, bytes(64))
            valid = self.payload(root, 'cpus=1 rd=md0')
            self.assertIsNone(self.check(valid, label='old', mpidr=mpidr))
            self.assertEqual(self.check(valid, label='old', mpidr=mpidr),
                             self.check(valid, mpidr=mpidr))
        valid = self.payload(self.root(smp=False), 'cpus=1 rd=md0')
        rng = random.Random(0x52454446)
        for _ in range(160):
            mutated = bytearray(valid)
            index = rng.randrange(len(mutated))
            mutated[index] ^= 1 << rng.randrange(8)
            payload = bytes(mutated)
            self.assertEqual(self.check(payload, label='old'), self.check(payload))

    def test_bounded_adt_parser_rejects_truncation_counts_flags_and_trailing_data(self):
        blob = self.mk.adt.serialize(self.root())
        validate = self.libraries['both'].adt_profile
        for size in range(len(blob)):
            self.assertEqual(validate(blob, size), 0)
        for offset, value in ((0, 0), (0, 0xffffffff), (4, 0xffffffff), (40, 0x80000004)):
            changed = bytearray(blob)
            struct.pack_into('<I', changed, offset, value)
            self.assertEqual(validate(bytes(changed), len(changed)), 0)
        self.assertEqual(validate(blob + b'\0' * 4, len(blob) + 4), 0)

    def test_freestanding_arm64_production_loader_compiles(self):
        clang = shutil.which('clang')
        if not clang:
            self.skipTest('clang required for ARM64 compile')
        build = self.directory / 'build_both'
        result = subprocess.run([clang, '-target', 'aarch64-none-elf', '-mcpu=cortex-a55',
                        '-ffreestanding', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(build), '-I', str(HERE), '-c', str(self.new / 'loader.c'),
                        '-o', str(self.directory / 'loader-arm64.o')],
                       capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_shim_gcc_objects_are_relocatable(self):
        gcc, readelf = shutil.which('aarch64-elf-gcc'), shutil.which('aarch64-elf-readelf')
        if not gcc or not readelf:
            self.skipTest('shim AArch64 GCC/readelf required')
        target = self.directory / 'loader-gcc.o'
        result = subprocess.run([gcc, '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
            '-fno-pic', '-mgeneral-regs-only', '-mstrict-align', '-fno-stack-protector',
            '-fno-tree-loop-distribute-patterns', '-Wall', '-Wextra', '-Werror',
            '-I', str(self.directory / 'build_both'), '-I', str(HERE),
            '-c', str(self.new / 'loader.c'), '-o', str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        relocations = subprocess.check_output([readelf, '-r', str(target)], text=True)
        self.assertNotIn('R_AARCH64_ABS', relocations)


if __name__ == '__main__':
    unittest.main()
