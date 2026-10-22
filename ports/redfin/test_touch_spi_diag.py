"""Actual GENI diagnostic overlay: bounded RO snapshots and unchanged transport traces."""
import ast
import ctypes as C
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from ports.redfin.test_touch import added_file
from ports.redfin.test_touch_events import function

HERE = Path(__file__).resolve().parent


def literal(name):
    tree = ast.parse((HERE / 'test_touch_spi.py').read_text())
    values = [ast.literal_eval(node.value) for node in ast.walk(tree)
              if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name
                                                     for target in node.targets)]
    assert len(values) == 1
    return values[0]


EXTRA = r'''
#include <stdarg.h>
static unsigned in_diagnostic,diag_reads,diag_lines,diag_snapshots;
static unsigned diag_addresses[1024],phase[32],phase_error[32],phase_owned[32],phase_dead[32],phase_command[32];
static uint32_t write_trace,delay_trace;
static const unsigned safe_offsets[]={
 0x000,0x004,0x040,0x068,0x06c,0x600,0x604,0x610,0x614,0x640,0x644,
 0x800,0x804,0x908,0x048,0x04c,0x060,0x07c,0x028,0x064,0x258,0xe18,0xe1c,
 0x80c,0x810,0x814,0x26c,0x270,0x268,0x224,0x230,0x25c,0x250,
 0x260,0x264,0x284,0x288,0xe24,0xe28,0x024,0x020
};
'''
PRINTF = r'''
static int model_printf(const char *format,...) __attribute__((format(__printf__,1,2)));
static int model_printf(const char *format,...){
 if(!strstr(format,"REDFIN TOUCH SPI DIAG:"))return 0;
 diag_lines++;
 if(strstr(format,"error=%d")){
  va_list args;va_start(args,format);const char *label=va_arg(args,const char *);
  unsigned index=diag_snapshots++;
  if(index<32){
   phase[index]=!strcmp(label,"before-first-tx")?1:!strcmp(label,"before-first-rx")?2:
     !strcmp(label,"failure-before-recovery")?3:!strcmp(label,"failure-after-recovery")?4:
     !strcmp(label,"identity-error")?6:5;
   phase_error[index]=(unsigned)va_arg(args,int);phase_owned[index]=(unsigned)va_arg(args,int);
   phase_dead[index]=(unsigned)va_arg(args,int);
  }
  va_end(args);
 }
 return 0;
}
'''
ACCESSORS = r'''
unsigned diagnostic(unsigned n){
 const unsigned values[]={diag_reads,diag_lines,diag_snapshots,write_trace,delay_trace,in_diagnostic};
 return n<6?values[n]:0;
}
unsigned address(unsigned n){return n<diag_reads && n<1024?diag_addresses[n]:0xffffffffu;}
unsigned evidence(unsigned n,unsigned field){
 if(n>=diag_snapshots || n>=32)return 0;
 return field==0?phase[n]:field==1?phase_error[n]:field==2?phase_owned[n]:field==3?phase_dead[n]:phase_command[n];
}
unsigned saturate(void){
#ifdef RF_SPI_DIAG_MAX_FAILURES
 struct redfin_spi context={1,16,16,false,false};
 for(unsigned i=0;i<100;i++)redfin_spi_diag_error(&context,"repeated-error",EIO);
 return redfin_spi_diag_failures;
#else
 return 0;
#endif
}
'''


class TouchSPIDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.libs = []
        header = added_file((HERE / 'touch.patch').read_text(), 'bsd/dev/redfin_touch_protocol.h')
        for instrumented in (False, True):
            work = root / str(instrumented)
            target = work / 'bsd/dev/redfin_touch_spi.c'
            target.parent.mkdir(parents=True)
            target.write_text(added_file((HERE / 'touch-spi.patch').read_text(), 'bsd/dev/redfin_touch_spi.c'))
            for patch in ('touch-events.patch', 'touch-spi-diag.patch') if instrumented else ('touch-events.patch',):
                subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_touch_spi.c', str(HERE / patch)], cwd=work, check=True)
            source = target.read_text()
            if instrumented:
                original = function(source, 'static void\nredfin_spi_diag_capture(')
                capture = original.replace('{', '{\n in_diagnostic++;', 1)
                end = capture.rfind('}')
                capture = capture[:end] + ' in_diagnostic--;\n' + capture[end:]
                source = source.replace(original, capture)
            source = re.sub(r'^#include.*\n', '', source, flags=re.M)
            source = source.replace('*(volatile const uint32_t *)(s->se + offset)', 'model_read(offset)')
            source = source.replace('*(volatile uint32_t *)(s->se + offset) = value;', 'model_write(offset,value);')
            source = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', source)
            source = source.replace('redfin_spi_rd(struct redfin_spi *s, unsigned offset)\n{',
                                    'redfin_spi_rd(struct redfin_spi *s, unsigned offset)\n{\n(void)s;')
            source = source.replace('redfin_spi_wr(struct redfin_spi *s, unsigned offset, uint32_t value)\n{',
                                    'redfin_spi_wr(struct redfin_spi *s, unsigned offset, uint32_t value)\n{\n(void)s;')
            stub = literal('stub')
            stub = stub.replace('static int model_printf(const char *format,...) {(void)format;return 0;}', EXTRA + PRINTF)
            stub = stub.replace('static void delay(unsigned us){wait_us+=us;}',
                                'static void delay(unsigned us){wait_us+=us;delay_trace=(delay_trace^us)*16777619u;}')
            stub = stub.replace('static uint32_t model_read(unsigned offset){', r'''
static uint32_t model_read(unsigned offset){
 if(in_diagnostic){
  bool allowed=false;
  for(unsigned i=0;i<sizeof(safe_offsets)/sizeof(safe_offsets[0]);i++)if(offset==safe_offsets[i])allowed=true;
  if(!allowed || offset==0x700 || offset==0x780)violations++;
  if(diag_reads<1024)diag_addresses[diag_reads]=offset;diag_reads++;
 }
''')
            stub = stub.replace('if(offset==0x40 && ++status_reads==2 && kind==12)',
                                'if(!in_diagnostic && offset==0x40 && ++status_reads==2 && kind==12)')
            stub = stub.replace('    writes++;',
                                '    writes++;write_trace=(write_trace^offset)*16777619u;write_trace=(write_trace^value)*16777619u;')
            wrapper = literal('wrapper')
            wrapper = wrapper.replace('    mode=selected;kind=fault;', r'''
    mode=selected;kind=fault;
    in_diagnostic=diag_reads=diag_lines=diag_snapshots=0;
    write_trace=delay_trace=2166136261u;
    memset(phase,0,sizeof(phase));memset(phase_error,0,sizeof(phase_error));
    memset(phase_owned,0,sizeof(phase_owned));memset(phase_dead,0,sizeof(phase_dead));
#ifdef RF_SPI_DIAG_MAX_FAILURES
    redfin_spi_diag_command_logged=false;redfin_spi_diag_failures=0;
#endif
''')
            (work / 'redfin_touch_protocol.h').write_text(header)
            (work / 'model.c').write_text(stub + '#include "redfin_touch_protocol.h"\n' + source + wrapper + ACCESSORS)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.run.argtypes = [C.c_uint, C.c_uint, C.c_uint, C.c_bool]
            lib.diagnostic.restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.diag = cls.libs

    def pair(self, fault=0, mode=2, speed=960000, gic=True):
        results = [lib.run(mode, fault, speed, gic) for lib in self.libs]
        self.assertEqual(results[0], results[1])
        self.assertEqual([self.baseline.stat(i) for i in range(11)], [self.diag.stat(i) for i in range(11)])
        self.assertEqual(self.baseline.diagnostic(3), self.diag.diagnostic(3), 'MMIO write offset/value/order changed')
        self.assertEqual(self.baseline.diagnostic(4), self.diag.diagnostic(4), 'Explicit delay schedule changed')
        self.assertEqual(self.diag.stat(4), 0, 'Unexpected diagnostic read or transport access')
        self.assertEqual(self.diag.diagnostic(5), 0)
        self.assertLessEqual(self.diag.diagnostic(0), 9*41)
        return results[1]

    def test_success_captures_first_tx_once_without_fifo_consumption(self):
        self.assertEqual(self.pair(), 0)
        self.assertEqual([self.diag.diagnostic(i) for i in range(3)], [41, 5, 1])
        self.assertEqual([self.diag.evidence(0, i) for i in range(4)], [1, 0, 0, 0])
        self.assertEqual([self.diag.address(i) for i in range(41)],
                         [0x000,0x004,0x040,0x068,0x06c,0x600,0x604,0x610,0x614,0x640,0x644,
                          0x800,0x804,0x908,0x048,0x04c,0x060,0x07c,0x028,0x064,0x258,0xe18,0xe1c,
                          0x80c,0x810,0x814,0x26c,0x270,0x268,0x224,0x230,0x25c,0x250,
                          0x260,0x264,0x284,0x288,0xe24,0xe28,0x024,0x020])

    def test_realistic_tx_timeout_and_cancel_abort_failures_keep_identical_recovery(self):
        for fault in (1, 2, 3):
            with self.subTest(fault=fault):
                self.assertNotEqual(self.pair(fault), 0)
                self.assertEqual([self.diag.diagnostic(i) for i in range(3)], [123, 15, 3])
                self.assertEqual([self.diag.evidence(i, 0) for i in range(3)], [1, 3, 4])
                self.assertEqual([self.diag.evidence(1, i) for i in (2, 3)], [1, 0])
                self.assertEqual([self.diag.evidence(2, i) for i in (2, 3)], [1, 1])

    def test_error_checksum_partial_fifo_and_identity_outcomes_are_unchanged(self):
        for fault in range(4, 14):
            with self.subTest(fault=fault):
                self.pair(fault)

    def test_unsafe_or_unverified_entry_never_runs_diagnostics(self):
        for mode, speed, gic in ((0, 960000, True), (1, 960000, True),
                                 (2, 0, True), (2, 10000001, True), (2, 960000, False)):
            self.pair(mode=mode, speed=speed, gic=gic)
            self.assertEqual(self.diag.diagnostic(0), 0)
            self.assertEqual(self.diag.diagnostic(1), 0)

    def test_prepare_failures_add_only_one_readonly_snapshot(self):
        for fault in range(100, 109):
            with self.subTest(fault=fault):
                self.pair(fault)
                self.assertEqual(self.diag.stat(0), 0)
                self.assertEqual([self.diag.diagnostic(i) for i in range(3)], [41, 5, 1])

    def test_error_snapshot_budget_is_saturating_and_adds_no_writes_or_delays(self):
        self.pair()
        before = [self.diag.stat(i) for i in range(11)]
        traces = [self.diag.diagnostic(i) for i in (3, 4)]
        self.assertEqual(self.diag.saturate(), 4)
        self.assertEqual([self.diag.diagnostic(i) for i in range(3)], [205, 25, 5])
        self.assertEqual([self.diag.stat(i) for i in range(11)], before)
        self.assertEqual([self.diag.diagnostic(i) for i in (3, 4)], traces)
        self.assertEqual(self.diag.saturate(), 4)
        self.assertEqual(self.diag.diagnostic(0), 205)


if __name__ == '__main__':
    unittest.main()
