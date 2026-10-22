"""Actual owner C: bounded owned-bank fault reads preserve failure policy."""
import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_bypass_context as bypass
from ports.redfin import test_usb_bypass_diagnostic as diagnostic
from ports.redfin import test_usb_enumeration_start as enumeration

HERE = Path(__file__).resolve().parent


class USBFaultDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        class Fixture(enumeration.USBEnumerationStartTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        original = Path(Fixture.temp.name)
        template = (original / 'model.c').read_text()
        owned = original / 'bsd/dev/redfin_usb_owned.c'
        initial = owned.read_text()
        subprocess.run(['git', 'apply', str(HERE / 'usb-bypass-diagnostic.patch')],
                       cwd=original, check=True)
        before = owned.read_text()
        subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_usb_owned.c',
                        str(HERE / 'usb-fault-diagnostic.patch')], cwd=original, check=True)
        after = owned.read_text()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.libs = []
        for name, actual in (('base', before), ('fault', after)):
            source = template.replace(bypass.host_owned(initial), bypass.host_owned(actual))
            if source == template:
                raise AssertionError('Actual owner seam changed')
            source = source.replace('if(!valid)bad++;\n uint32_t *page=', '''
 if(region==3 && offset/0x1000==4 &&
    ((offset%0x1000)==0x60 || (offset%0x1000)==0x64 ||
     (offset%0x1000)==0x68 || (offset%0x1000)==0x6c))valid=true;
 if(region==2 && offset==0x1410)valid=true;
 if(!valid)bad++;
 uint32_t *page=''')
            work = Path(cls.tmp.name) / name
            work.mkdir()
            for header in original.glob('*.h'):
                shutil.copy2(header, work / header.name)
            model = work / 'model.c'
            wrappers = diagnostic.WRAPPERS.replace('void diag_reset(void){diag_barriers=0;}', '')
            wrappers = wrappers.replace('unsigned diag_barrier_count(void){return diag_barriers;}', '')
            model.write_text(source + wrappers)
            library = work / 'model.so'
            result = subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-O0',
                                     '-Wall', '-Wextra', '-Werror', '-I', str(work),
                                     str(model), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_int, C.c_uint]
            lib.host_set.argtypes = lib.bypass_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
            lib.host_logs.restype = C.c_char_p
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            cls.libs.append(lib)

    def reset(self, lib):
        lib.host_reset()
        lib.bypass_reset()
        lib.bypass_fixture()
        lib.enum_reset()
        lib.host_arg(b'redfinusbcontexts', 0, 1)
        lib.host_arg(b'redfinusbbypass', 1, 1)
        lib.host_arg(b'redfinusbgadget', 1, 1)
        lib.bypass_seal()
        self.assertEqual(lib.host_start(), 0)

    def compare(self, mutate, extra_reads, volatile_fault=False):
        results = []
        for lib in self.libs:
            self.reset(lib)
            mutate(lib)
            start = lib.host_stat(1)
            outcome = lib.diag_verify(0, 0)
            stats = [lib.host_stat(i) for i in range(9)]
            self.assertEqual(stats[4:6], [0, 0], 'invalid MMIO, mapping, store or lock')
            self.assertEqual(stats[2], 4)
            memory = b''.join(C.string_at(lib.host_page(i), 0x4000) for i in range(3))
            memory += C.string_at(lib.host_context_page(), bypass.CB_SIZE)
            if volatile_fault:
                # The injected asynchronous FSR change is hardware activity.
                # Compare every other byte against the unchanged baseline.
                memory = bytearray(memory)
                memory[0xc000 + 0x4058:0xc000 + 0x405c] = bytes(4)
            results.append((outcome, stats, memory, lib.host_logs().decode()))
            self.assertNotEqual(outcome, 0)
            frozen = stats[:]
            self.assertEqual(lib.diag_verify(0, 0), errno.EBUSY)
            self.assertEqual(lib.diag_verify(1, 0), errno.EBUSY)
            self.assertEqual([lib.host_stat(i) for i in range(9)], frozen)
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(results[0][2], results[1][2], 'diagnostic changed hardware bytes')
        expected = results[0][1][:]
        expected[1] += extra_reads
        self.assertEqual(expected, results[1][1], 'only bounded diagnostic reads may differ')
        return results[1][3]

    @staticmethod
    def fault(lib, fsr=2):
        for region, offset, value in ((3, 0x4058, fsr), (3, 0x4060, 0x92345000),
                                      (3, 0x4064, 1), (3, 0x4068, 0x10),
                                      (3, 0x406c, 0x2103), (2, 0x1410, 0xe0)):
            lib.bypass_set(region, offset, value)

    def test_owned_translation_fault_has_exact_address_syndromes_and_seven_reads(self):
        log = self.compare(self.fault, 7)
        self.assertIn('fault-snapshot bank=4 FSR=0x2 FAR-words=0x1:92345000 '
                      'FSYNR0=0x10 FSYNR1=0x2103 CBFRSYNRA=0xe0; diagnostic only', log)

    def test_all_real_fault_bits_keep_quarantine(self):
        for fsr in (2, 4, 8, 0x10, 0x20, 0x40, 0x80, 0x100, 0x40000000, 0x80000000):
            with self.subTest(fsr=fsr):
                self.assertIn('fault-snapshot bank=4 FSR=',
                              self.compare(lambda lib: self.fault(lib, fsr), 7))

    def test_format_bits_nonowned_fault_and_structural_drift_add_no_reads(self):
        for region, offset, value in ((3, 0x4058, 0x400), (3, 0x5058, 2),
                                      (2, 0x810, 0x800000e1), (3, 0x4000, 1)):
            with self.subTest(region=region, offset=offset):
                log = self.compare(lambda lib: lib.bypass_set(region, offset, value), 0)
                self.assertNotIn('fault-snapshot', log)

    def test_allones_cached_fault_is_incomplete_and_does_not_read_syndromes(self):
        log = self.compare(lambda lib: lib.bypass_set(3, 0x4058, 0xffffffff), 0)
        self.assertNotIn('fault-snapshot', log)
        self.assertIn('comparison skipped', log)

    def test_unavailable_words_are_never_presented_as_valid_syndromes(self):
        for region, offset in ((3, 0x4060), (3, 0x4064), (3, 0x4068),
                               (3, 0x406c), (2, 0x1410)):
            def mutate(lib):
                self.fault(lib)
                lib.bypass_set(region, offset, 0xffffffff)
            with self.subTest(region=region, offset=offset):
                log = self.compare(mutate, 7)
                self.assertIn('unavailable or changed; interpretation skipped', log)
                self.assertNotIn('FAR-words=', log)

    def test_fault_changes_during_bounded_capture_are_not_interpreted(self):
        for occurrence in (2, 3):
            def mutate(lib):
                self.fault(lib)
                lib.host_mutate(3, 0x4058, occurrence, 0x80000002)
            with self.subTest(occurrence=occurrence):
                log = self.compare(mutate, 7, volatile_fault=True)
                self.assertIn('unavailable or changed; interpretation skipped', log)
                self.assertNotIn('FAR-words=', log)


if __name__ == '__main__':
    unittest.main()
