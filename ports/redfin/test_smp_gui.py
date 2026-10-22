"""GUI8 policy, real loader and SMP/CPU0 publication barriers; no device I/O."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import gui_profile
from test_cycle import cycle
from test_smp_topology import module

HERE = Path(__file__).resolve().parent
ARGS = ' '.join(sorted(gui_profile.REQUIRED)) + ' redfinbootid=0x0123456789abcdef'


def patched_source(name):
    """Reconstruct a new source file from the real ordered board overlays."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        patches = re.findall(r"['\"]([^'\"]+\.patch)['\"]", (HERE / 'prepare-xnu.py').read_text())
        seen = set()
        for entry in patches:
            path = HERE / Path(entry).name
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if '+++ b/' + name + '\n' not in path.read_text():
                continue
            subprocess.run(['git', 'apply', '--include=' + name, str(path)],
                           cwd=root, check=True, capture_output=True)
        return (root / name).read_text()


def compile_shared(directory, text, name='gui', flags=()):
    source = directory / (name + '.c')
    source.write_text(text)
    library = directory / (name + '.so')
    result = subprocess.run([shutil.which('cc') or 'cc', '-std=c11', '-O2', '-shared', '-fPIC',
        '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
        '-I', str(directory), '-I', str(HERE), *flags, str(source), '-o', str(library)],
        capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return C.CDLL(str(library))


class GUIProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.lib = compile_shared(Path(cls.temp.name), '#include "gui-profile.h"\n'
            'int profile(const char *a,unsigned n){return redfin_gui_profile(a,n,0);}\n')
        cls.lib.profile.argtypes = [C.c_char_p, C.c_uint]

    def check(self, args, expected):
        self.assertEqual(self.lib.profile(args.encode(), len(args) + 1), expected, args)

    def test_python_and_c_contracts_match_including_optional_trace(self):
        self.assertEqual(patched_source('osfmk/arm64/redfin_gui_profile.h'), (HERE / 'gui-profile.h').read_text())
        self.assertEqual(patched_source('osfmk/arm64/redfin_gui_runtime.h'), (HERE / 'gui-runtime.h').read_text())
        for trace in ('', ' -enable_kprintf_spam'):
            args = ARGS + trace
            self.check(args, 1)
            self.assertEqual(gui_profile.validate(args), '0123456789abcdef')

    def test_missing_duplicate_unknown_and_changed_required_arguments_fail(self):
        for token in ARGS.split():
            for args in (ARGS.replace(token, '', 1), ARGS + ' ' + token,
                         ARGS.replace(token, token + 'x', 1)):
                self.check(args, 0)
                with self.assertRaises(ValueError):
                    gui_profile.validate(args)
        for extra in ('redfincpu=0', 'redfinusb=0', 'redfinearlyreturn=1', 'redfinfuture=0'):
            self.check(ARGS + ' ' + extra, 0)

    def test_hidden_tail_controls_unterminated_field_and_invalid_nonce_fail(self):
        for args in (ARGS + '\0hidden=1', ARGS.replace(' ', '\t', 1), ARGS + '\n',
                     ARGS.replace('0123456789abcdef', '0000000000000000'),
                     ARGS.replace('0123456789abcdef', '0123456789abcdeF')):
            self.check(args, 0)
        self.assertEqual(self.lib.profile(ARGS.encode(), len(ARGS)), 0)
        padded = ARGS.encode().ljust(608, b'\0')
        self.assertEqual(self.lib.profile(padded, len(padded)), 1)
        self.assertEqual(self.lib.profile(padded[:-1] + b'x', 608), 0)


class GUICycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'redfin-xnu.img'
        self.image.write_bytes(b'synthetic image; no device')
        self.config = self.root / 'config.h'
        self.config.write_text('#define SHIM_EARLY_RETURN 1\n#define REDFIN_SMP_PROBE 0\n'
                               '#define REDFIN_SMP_GUI 1\n#define REDFIN_SMP_CPUS 8\n')
        self.manifest = dict(smp_gui=True, smp_cpus=8, shim_early_return=True,
            root_writable=True, cpu_copy_display=True, splash_reservation_assumption=True,
            touch_events=True, capture_screen=False, userspace_stacks=False,
            syscall_tracing=False, shutdown_seconds=180, display_hz=10,
            boot_args=ARGS, root_device='ufsroot0', sha256={
                'redfin-xnu.img': hashlib.sha256(self.image.read_bytes()).hexdigest(),
                'config.h': hashlib.sha256(self.config.read_bytes()).hexdigest()})

    def verify(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        return cycle.xnu_return_proof(self.image)

    def test_gui8_return_and_manifest_mutations(self):
        self.assertEqual(self.verify()['cpus'], 8)
        self.assertEqual(self.verify()['armed_by'], 'shim')
        for key, value in (('smp_gui', False), ('smp_probe', True), ('smp_cpus', 2),
                           ('root_writable', False), ('touch_events', False),
                           ('root_device', 'md0'), ('shutdown_seconds', 120),
                           ('display_hz', 60), ('shim_early_return', 1)):
            old = self.manifest.copy()
            self.manifest[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
            self.manifest = old
        self.config.write_bytes(self.config.read_bytes().replace(b'GUI 1', b'GUI 0'))
        with self.assertRaises(ValueError):
            self.verify()


class GUILoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.libs = {}
        wrapper = ('#include "loader.c"\n'
            'int command(const char *p){return smp_command(p);}\n'
            'int tree(const void *p,unsigned n){return adt_valid_smp_mode(p,n,1);}\n'
            'int md0tree(const void *p,unsigned n){return adt_valid_smp(p,n);}\n')
        # fdt.c supplies only the real loader's link dependencies.
        for name, shim, gui, probe, count in (('gui', 1, 1, 0, 8), ('md0', 1, 0, 1, 8),
                ('no_shim', 0, 1, 0, 8), ('two', 1, 1, 0, 2), ('both', 1, 1, 1, 8)):
            (cls.directory / 'config.h').write_text(f'#define XNU_PAYLOAD_SIZE 65536\n'
                f'#define SHIM_EARLY_RETURN {shim}\n#define REDFIN_SMP_PROBE {probe}\n'
                f'#define REDFIN_SMP_GUI {gui}\n#define REDFIN_SMP_CPUS {count}\n')
            lib = compile_shared(cls.directory, wrapper, name,
                                 ('-DREDFIN_LOADER_TEST', str(HERE / 'fdt.c')))
            lib.command.argtypes = [C.c_char_p]
            lib.tree.argtypes = lib.md0tree.argtypes = [C.c_void_p, C.c_uint]
            cls.libs[name] = lib
        sys.path.insert(0, str(HERE.parents[1] / 'tools'))
        import adt
        cls.adt = adt
        cls.mk = module(HERE / 'mkadt.py', 'gui_mkadt')

    def gui_tree(self):
        mk = self.mk
        tree = mk.build(0x180000000, 0x80000000, seed=bytes(64), smp=True, smp_cpus=8)
        # The same production display builder and fixed FDT-derived touch contract.
        mk.add_linear_display(tree, 0xa0000000, 0x02300000, 0xa0000000, 1080, 2340, 4320)
        tree.children += [mk.node('redfin-touch', [
            ('compatible', mk.cstr('redfin,sec-touch')),
            ('reg', mk.u64(0x100000, 0x1f0000, 0x880000, 0x4000, 0xf000000, 0x1000000)),
            ('spi-mode', mk.u32(3)), ('chip-select', mk.u32(0)), ('spi-max-frequency', mk.u32(10000000)),
            ('touch-gpios', mk.u32(8, 9, 35)), ('touch-size', mk.u32(1080, 2340))]),
            mk.node('redfin-spmi', [('reg', mk.u64(0xc440000, 0x1100, 0xe600000, 0x100000, 0xc40a000, 0x26000)), ('ee', mk.u32(0))]),
            mk.node('redfin-return', [('reg', mk.u64(0xc600000, 0x2000000, 0x146ab65c, 4))]),
            mk.node('redfin-ufs', [('reg', mk.u64(0x1d84000, 0x3000))])]
        tree.children.append(mk.node('sweet-fbcon', [('reg', mk.u64(0xa0000000, 0x02300000)),
            ('width', mk.u32(1080)), ('height', mk.u32(2340)), ('stride', mk.u32(4320))]))
        tree.children += [mk.node(name, []) for name in ('product', 'redfin-log', 'redfin-watchdog', 'pram')]
        return tree

    def test_compiled_gui_gate_is_independent_of_md0(self):
        for name, lib in self.libs.items():
            self.assertEqual(lib.command(ARGS.encode().ljust(608, b'\0')), name == 'gui', name)

    def test_gui_tree_requires_all_eight_cpus_and_exact_hardware_leaves(self):
        lib = self.libs['gui']
        raw = self.adt.serialize(self.gui_tree())
        self.assertEqual(lib.tree(raw, len(raw)), 1)
        self.assertEqual(lib.md0tree(raw, len(raw)), 0)
        for node_name in ('redfin-touch', 'redfin-ufs', 'sweet-fbcon', 'cpus', 'arm-io'):
            tree = self.gui_tree()
            tree.children = [node for node in tree.children if node.name != node_name]
            raw = self.adt.serialize(tree)
            self.assertEqual(lib.tree(raw, len(raw)), 0, node_name)
        for node in self.gui_tree().children:
            targets = node.children if node.name == 'arm-io' else [node]
            for target in targets:
                if target.name not in ('disp0', 'redfin-touch', 'redfin-ufs', 'sweet-fbcon'):
                    continue
                for key, flag, value in target.props[1:]:
                    tree = self.gui_tree()
                    parent = next(n for n in tree.children if n.name == node.name)
                    victim = next(n for n in parent.children if n.name == target.name) if node.name == 'arm-io' else parent
                    victim.props = [(k, f, bytes([v[0] ^ 1]) + v[1:] if k == key else v) for k, f, v in victim.props]
                    raw = self.adt.serialize(tree)
                    self.assertEqual(lib.tree(raw, len(raw)), 0, (target.name, key))


class GUIRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        core = patched_source('osfmk/arm64/redfin_smp.c')
        proof = re.search(r'int redfin_smp_prove\(void\)\n\{.*?\n\}', core, re.S).group()
        text = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <setjmp.h>
#include <string.h>
#include "gui-profile.h"
typedef void *processor_t;
typedef void *event_t;
#define NSEC_PER_MSEC 1000000ULL
#define NSEC_PER_SEC 1000000000ULL
#define THREAD_UNINT 0
#define THREAD_WAITING 1
#define THREAD_CONTINUE_NULL NULL
static uint32_t rf_gui_selected,rf_smp_proved,rf_smp_published,rf_gui_ready;
static unsigned cpu,publish_calls,clock_ticks,publish_at,bad_binding,bad_frozen,return_error;
static int proof_error;
static processor_t binding;
static uint64_t rf_smp_boot_id=0x0123456789abcdefULL;
static char rf_smp_frozen[608];
static unsigned rf_smp_frozen_bytes;
static jmp_buf failed;
static int rf_smp_local(void){return (int)cpu;}
static unsigned rf_smp_count(void){return 8;}
static bool rf_smp_unchanged(void){return cpu==0&&!bad_frozen;}
static void panic(const char *fmt,...){(void)fmt;longjmp(failed,1);}
static void kprintf(const char *fmt,...){(void)fmt;}
static processor_t cpu_to_processor(int n){return (void *)(uintptr_t)(n+1);}
static processor_t thread_bind(processor_t p){processor_t old=binding;binding=p;cpu=bad_binding?4:(p?(unsigned)((uintptr_t)p-1):6);return old;}
static void thread_block(void *p){(void)p;}
static uint64_t mach_absolute_time(void){return (uint64_t)clock_ticks++*100000000ULL;}
static void nanoseconds_to_deadline(uint64_t n,uint64_t *p){*p=mach_absolute_time()+n;}
static void clock_interval_to_deadline(unsigned n,uint64_t d,uint64_t *p){*p=mach_absolute_time()+n*d;}
static int assert_wait_deadline(event_t e,unsigned f,uint64_t t){(void)e;(void)f;(void)t;if(publish_at&&clock_ticks>=publish_at)rf_smp_published=1;return THREAD_WAITING;}
int redfin_gui_publish_return(void){publish_calls++;return !return_error;}
static int rf_smp_prove_all(void){return proof_error;}
''' + proof + '\n#include "gui-runtime.h"\n' + r'''
int run(unsigned scenario,const char *args){
 rf_gui_selected=1;rf_smp_proved=rf_smp_published=rf_gui_ready=0;
 cpu=6;binding=NULL;publish_calls=clock_ticks=publish_at=bad_binding=bad_frozen=return_error=0;
 proof_error=0;strcpy(rf_smp_frozen,args);rf_smp_frozen_bytes=(unsigned)strlen(args)+1;
 if(scenario==0){cpu=0;proof_error=-210;if(redfin_smp_prove()!=-210)return -1;
  if(setjmp(failed))return rf_smp_published||rf_gui_ready||publish_calls?-2:0;
  redfin_smp_publish();return -3;}
 if(scenario==1){if(setjmp(failed))return !rf_gui_ready&&!publish_calls?0:-1;
  redfin_gui_root_enter();return -2;}
 if(scenario==2){rf_smp_published=1;return_error=1;
  if(setjmp(failed))return !rf_gui_ready&&publish_calls==1?0:-1;
  redfin_gui_root_enter();return -2;}
 if(scenario==3){rf_smp_published=1;bad_binding=1;
  if(setjmp(failed))return !rf_gui_ready&&!publish_calls?0:-1;
  redfin_gui_root_enter();return -2;}
 if(scenario==4){cpu=0;if(redfin_smp_prove())return -1;redfin_smp_publish();cpu=6;}
 else if(scenario==5)publish_at=3;
 else if(scenario==6){rf_smp_published=1;bad_frozen=1;}
 if(setjmp(failed))return scenario==6&&!rf_gui_ready&&!publish_calls?0:-9;
 void *old=redfin_gui_root_enter();
 if(!redfin_gui_cpu0()||cpu||publish_calls!=1||old!=NULL)return -4;
 redfin_gui_root_leave(old);
 if(cpu!=6||binding||!redfin_gui_ready()||redfin_gui_cpu0()||publish_calls!=1)return -5;
 if(!redfin_gui_bind_worker()||cpu||publish_calls!=1)return -6;
 return 0;
}
'''
        cls.lib = compile_shared(Path(cls.temp.name), text, 'runtime')
        cls.lib.run.argtypes = [C.c_uint, C.c_char_p]

    def test_failed_proof_timeout_failed_return_wrong_cpu_and_binding_restore(self):
        for scenario in range(7):
            self.assertEqual(self.lib.run(scenario, ARGS.encode()), 0, scenario)


if __name__ == '__main__':
    unittest.main()
