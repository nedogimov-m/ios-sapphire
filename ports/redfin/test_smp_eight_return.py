"""The generalized read-only return verifier retains UP fences and checks eight CPUs."""
import ctypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_smp_return as base

HERE = Path(__file__).parent.resolve()
ARGS = base.ARGS.replace('cpus=2', 'cpus=8')


def backend():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'bsd/dev/redfin_spmi.c'
        source.parent.mkdir(parents=True)
        source.write_text(base.backend() + '\n/* REDFIN_SMP_RETURN_END */\n')
        subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_spmi.c',
            str(HERE / 'smp-eight.patch')], cwd=root, check=True, capture_output=True)
        return source.read_text()


class EightReturnTwoCoreRegression(base.SMPReturnTests):
    @classmethod
    def setUpClass(cls):
        original = base.backend
        # Capture the extension before replacing the original source loader.
        actual = backend()
        try:
            base.backend = lambda: actual
            base.SMPReturnTests.setUpClass.__func__(cls)
        finally:
            base.backend = original

    def test_closed_exact_whitelist_and_optional_trace(self):
        # The final mode parser admits both reviewed counts. Actual readiness
        # additionally checks the selected count against the complete topology.
        for count in (2, 8):
            text = base.ARGS.replace('cpus=2', f'cpus={count}').encode()
            self.assertEqual(self.lib.flags(text, len(text) + 1), 1)
        for value in ('1', '3', '7', '9', '02', '0x8'):
            text = base.ARGS.replace('cpus=2', 'cpus=' + value).encode()
            self.assertEqual(self.lib.flags(text, len(text) + 1), 0)


class EightReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        prefix = base.PREFIX.replace('static ml_topology_cpu_t cpus[2];', 'static ml_topology_cpu_t cpus[8];')
        needle = ' (void)root;if(dt_fault==1)return 1;'
        assert prefix.count(needle) == 1
        prefix = prefix.replace(needle, needle + r'''
 if(!strncmp(path,"/cpus/cpu",9) && path[9]>='2' && path[9]<='7' && !path[10]) {
  if(dt_fault==21 && path[9]=='5')return 1;
  *out=(void *)(uintptr_t)(100+path[9]-'0');return 0;
 }
''')
        prefix = prefix.replace('values[0]=dt_fault==8?0x100:0x600;',
                                'values[0]=dt_fault==8?0x600:0x100;')
        needle = ' if(n==2 && !strcmp(name,"dram-base"))'
        assert prefix.count(needle) == 1
        prefix = prefix.replace(needle, ''' if(n>=102 && n<=107 && !strcmp(name,"reg")){values[0]=(n-100)<<8;*bytes=4;}
 else if(n==2 && !strcmp(name,"dram-base"))''')
        suffix = base.SUFFIX.replace('memset(cpus,0,sizeof(cpus));cpus[1].cpu_id=1;cpus[1].phys_id=0x600;cpus[1].l2_cache_id=1;',
            'memset(cpus,0,sizeof(cpus));for(unsigned i=0;i<8;i++){cpus[i].cpu_id=i;cpus[i].phys_id=i<<8;cpus[i].l2_cache_id=i;}')
        suffix = suffix.replace('cluster.num_cpus=2;cluster.cpu_mask=3;',
                                'cluster.num_cpus=8;cluster.cpu_mask=255;')
        suffix = suffix.replace('topology.num_cpus=2;topology.max_cpu_id=1;',
                                'topology.num_cpus=8;topology.max_cpu_id=7;')
        extra = r'''
void bad_eight(unsigned fault){
 switch(fault){case 1:topology.num_cpus=7;break;case 2:topology.max_cpu_id=6;break;
 case 3:cpus[7].phys_id=0x600;break;case 4:cpus[7].cpu_id=0;break;
 case 5:cpus[5].l2_cache_id=1;break;case 6:cpus[6].l3_cache_id=1;break;
 case 7:cluster.cpu_mask=127;break;case 8:cluster.num_cpus=7;break;
 case 9:cpus[0].l2_cache_size=64;break;case 10:cpus[7].die_id=1;break;
 default:violations++;}
}
'''
        header = re.sub(r'/\* REDFIN_EARLY_RETURN_HW_BEGIN \*/.*?/\* REDFIN_EARLY_RETURN_HW_END \*/',
                        '', (HERE / 'early-return.h').read_text(), flags=re.S)
        actual = re.sub(r'/\* RF_SMR_RUNTIME_HW_BEGIN \*/.*?/\* RF_SMR_RUNTIME_HW_END \*/', '', backend(), flags=re.S)
        source = root / 'return-eight.c'
        source.write_text(prefix + header + actual + suffix + extra)
        library = root / 'return-eight.so'
        result = subprocess.run([shutil.which('cc') or 'cc', '-shared', '-fPIC', '-O2', '-std=c11',
            '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-misleading-indentation',
            str(source), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.reset.argtypes = cls.lib.change_args.argtypes = [ctypes.c_char_p]
        cls.lib.set.argtypes = [ctypes.c_uint, ctypes.c_uint64]
        cls.lib.stat.argtypes = cls.lib.bad_eight.argtypes = [ctypes.c_uint]

    def setUp(self):
        self.lib.reset(ARGS.encode())

    def test_eight_core_proof_maps_only_four_read_windows_and_caches_success(self):
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        self.assertEqual(self.lib.stat(2), 4)
        self.assertEqual(self.lib.stat(5), 0)
        self.assertEqual(self.lib.stat(9), 3)
        self.assertEqual(self.lib.stat(11), 0)
        self.assertEqual(self.lib.stat(12), 0)
        counts = [self.lib.stat(i) for i in range(17)]
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        self.assertEqual([self.lib.stat(i) for i in range(17)], counts)

    def test_every_later_cpu_and_cluster_is_checked_before_hardware(self):
        for fault in range(1, 11):
            self.lib.reset(ARGS.encode())
            self.lib.bad_eight(fault)
            self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
            self.assertEqual(self.lib.stat(2), 0)
        self.lib.reset(ARGS.encode())
        self.lib.set(1, 21)
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.assertEqual(self.lib.stat(2), 0)

    def test_cached_success_rechecks_all_cpus_and_exact_frozen_args(self):
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        counts = self.lib.stat(0)
        self.lib.bad_eight(3)
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)
        self.assertEqual(self.lib.stat(0), counts)
        self.lib.reset(ARGS.encode())
        self.assertEqual(self.lib.redfin_smp_return_ready(), 1)
        self.lib.change_args(ARGS.replace('cpus=8', 'cpus=2').encode())
        self.assertEqual(self.lib.redfin_smp_return_ready(), 0)


if __name__ == '__main__':
    unittest.main()
