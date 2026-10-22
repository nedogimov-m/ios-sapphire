"""Actual md0 caller C: typed, frozen USB modes retain complete route proof."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_context_format_status as fmt
from ports.redfin import test_usb_aarch64_context as a64
from ports.redfin.test_touch_events import function
from ports.redfin.test_usb_owned_route import added_file

HERE = Path(__file__).resolve().parent
PARSER = r'''
static bool net_raw_override[2];static char net_raw[2][128];
static bool PE_parse_boot_arg_str(const char *name,char *out,int size){
 int index=!strcmp(name,"redfinusbnet")?0:!strcmp(name,"redfinusblog")?1:-1;
 if(index<0)return net_r64_parse(name,out,size);
 if(size<=0){bad++;return false;}
 for(unsigned i=0;i<sizeof(args)/sizeof(args[0]);i++)if(!strcmp(args[i].name,name)){
  if(!args[i].present)return false;
  char rendered[32];snprintf(rendered,sizeof(rendered),"%u",args[i].value);
  const char *text=net_raw_override[index]?net_raw[index]:rendered;
  size_t n=strlen(text);if(n>=(size_t)size)n=(size_t)size-1;
  memcpy(out,text,n);out[n]=0;return true;
 }
 bad++;return false;
}
'''
WRAPPERS = r'''
void net_reset(void){
 memset(net_raw_override,0,sizeof(net_raw_override));memset(net_raw,0,sizeof(net_raw));
#ifdef TEST_NETWORK_START
 __atomic_store_n(&redfin_initial_usb_network_lease,0,__ATOMIC_RELEASE);
#endif
}
void net_text(unsigned index,const char *text){
 if(index>1){bad++;return;}net_raw_override[index]=true;
 snprintf(net_raw[index],sizeof(net_raw[index]),"%s",text);
}
unsigned net_mode(void){
#ifdef TEST_NETWORK_START
 return redfin_initial_usb_mode();
#else
 return 0;
#endif
}
unsigned net_frozen(void){
#ifdef TEST_NETWORK_START
 return __atomic_load_n(&redfin_initial_usb_network_lease,__ATOMIC_ACQUIRE);
#else
 return 0;
#endif
}
'''


class USBNetworkStartTests(unittest.TestCase):
    reset_owner = a64.USBAArch64ContextTests.reset
    snapshot = a64.USBAArch64ContextTests.snapshot
    trace = a64.USBAArch64ContextTests.trace
    memory = a64.USBAArch64ContextTests.memory

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        class Fixture(fmt.USBContextFormatStatusTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        original = Path(Fixture.tmp.name) / 'format'
        template = (original / 'model.c').read_text()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        start = root / 'bsd/dev/redfin_usb_start.c'
        start.parent.mkdir(parents=True)
        start.write_text(added_file((HERE / 'usb-start.patch').read_text(), 'bsd/dev/redfin_usb_start.c'))
        for patch in ('usb-context-probe.patch', 'usb-bypass-context.patch',
                      'usb-enumeration-start.patch', 'usb-aarch64-context.patch'):
            subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_usb_start.c',
                            str(HERE / patch)], cwd=root, check=True)
        before = start.read_text()
        subprocess.run(['git', 'apply', str(HERE / 'usb-network-start.patch')], cwd=root, check=True)
        after = start.read_text()
        cls.libs = []
        for name, actual in (('base', before), ('network', after)):
            old = re.sub(r'^#include.*\n', '', before, flags=re.M)
            if template.count(old) != 1:
                raise AssertionError('Actual caller seam changed')
            source = template.replace(old, re.sub(r'^#include.*\n', '', actual, flags=re.M))
            parser = function(source, 'static __attribute__((unused)) bool PE_parse_boot_arg_str')
            source = source.replace(parser, parser.replace('PE_parse_boot_arg_str', 'net_r64_parse') + PARSER)
            work = root / name
            work.mkdir()
            for header in original.glob('*.h'):
                shutil.copy2(header, work / header.name)
            model = work / 'model.c'
            model.write_text(('#define TEST_NETWORK_START 1\n' if name == 'network' else '') + source + WRAPPERS)
            library = work / 'model.so'
            result = subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-O0',
                                     '-Wall', '-Wextra', '-Werror', '-I', str(work),
                                     str(model), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.host_arg.argtypes = [C.c_char_p, C.c_uint32, C.c_int]
            lib.bypass_set.argtypes = [C.c_uint, C.c_uint, C.c_uint32]
            lib.net_text.argtypes = [C.c_uint, C.c_char_p]
            lib.host_page.restype = lib.host_context_page.restype = C.c_void_p
            lib.host_logs.restype = C.c_char_p
            for symbol in ('host_hash', 'bypass_trace', 'bypass_stat', 'net_mode', 'net_frozen'):
                getattr(lib, symbol).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.lib = cls.libs

    def reset(self, lib=None, network=0, log=0, **kwargs):
        lib = self.reset_owner(lib, gadget=1, **kwargs)
        lib.format_reset()
        lib.net_reset()
        lib.host_arg(b'redfinusbnet', network, 1)
        lib.host_arg(b'redfinusblog', log, 1)
        lib.bypass_seal()
        return lib

    def test_three_modes_keep_exact_route_writes_and_phase_ownership(self):
        for network, log, mode in ((0, 0, 0), (1, 0, 1), (1, 1, 2)):
            with self.subTest(mode=mode):
                lib = self.reset(network=network, log=log)
                self.assertEqual(lib.host_start(), 0)
                self.assertEqual(lib.net_mode(), mode)
                self.assertEqual(lib.net_frozen(), mode+1)
                self.assertEqual(self.trace(), a64.FIVE)
                self.assertEqual([lib.enum_stat(i) for i in range(4)], [1, 0, 0, 0])
                self.assertEqual(lib.enum_authorize(1, 1), errno.EPERM)
                self.assertEqual(lib.enum_authorize(1, 2), errno.EPERM)
                self.snapshot()

    def test_enum_default_and_zero_keep_previous_four_and_five_store_io(self):
        for value in (0, 1):
            snapshots = []
            for lib in self.libs:
                self.reset(lib, value=value)
                self.assertEqual(lib.host_start(), 0)
                snapshots.append(self.snapshot(lib))
            self.assertEqual(snapshots[0], snapshots[1])

    def test_log_without_network_and_malformed_flags_refuse_before_mapping(self):
        for network, log in ((0, 1), (2, 0), (1, 2), (0xffffffff, 0)):
            lib = self.reset(network=network, log=log)
            self.assertEqual(lib.host_start(), errno.ENOTSUP)
            self.assertEqual(lib.host_stat(0), 0)
            self.assertEqual(lib.host_stat(2), 0)
        for index in (0, 1):
            for text in (b'', b'4294967297', b'0x1', b'01', b'1suffix', b'1' * 100):
                lib = self.reset(network=1, log=1)
                lib.net_text(index, text)
                self.assertEqual(lib.host_start(), errno.ENOTSUP)
                self.assertEqual(lib.host_stat(0), 0)

    def test_network_requires_validated_aarch64_gadget_and_return_profile(self):
        for arg, value in ((b'redfinusbrw64', 0), (b'redfinusbgadget', 0),
                           (b'redfinusbbypass', 0), (b'redfinusbsecs', 31),
                           (b'redfinreturn', 0), (b'redfinufs', 3), (b'cpus', 2)):
            lib = self.reset(network=1)
            lib.host_arg(arg, value, 1)
            self.assertEqual(lib.host_start(), errno.ENOTSUP)
            self.assertEqual(lib.host_stat(0), 0)

    def test_mode_change_revokes_every_phase_without_releasing_or_reconfiguring(self):
        for network, log in ((0, 0), (1, 0), (1, 1)):
            lib = self.reset(network=network, log=log)
            self.assertEqual(lib.host_start(), 0)
            frozen = self.snapshot()
            lib.host_arg(b'redfinusbnet', 1-network, 1)
            for phase in (0, 1, 2):
                self.assertEqual(lib.enum_authorize(phase, 0), errno.EPERM)
            self.assertEqual(lib.host_start(), errno.ENOTSUP)
            self.assertEqual(self.snapshot(), frozen)
            self.assertEqual(lib.net_frozen(), 1+network+log)

    def test_real_smmu_fault_quarantines_and_allows_only_owned_halt(self):
        lib = self.reset(network=1, log=1)
        self.assertEqual(lib.host_start(), 0)
        lib.enum_bad_route()
        before = self.memory()
        self.assertEqual(lib.enum_authorize(1, 0), errno.EAGAIN)
        self.assertEqual(lib.enum_authorize(1, 0), errno.EBUSY)
        self.assertEqual(lib.enum_authorize(2, 0), 0)
        self.assertEqual(self.memory(), before)
        self.assertEqual(self.trace(), a64.FIVE)
        self.snapshot()


if __name__ == '__main__':
    unittest.main()
