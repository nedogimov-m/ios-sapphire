"""Execute actual setup + SPI, comparing a bounded RO platform overlay to baseline."""
import ast
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch import added_file
from ports.redfin.test_touch_events import function

HERE = Path(__file__).resolve().parent
GCC = [0x52008, 0x17004, 0x17008, 0x1700c, 0x23000, 0x23008,
       0x17010, 0x17014, 0x17018, 0x1701c, 0x17020, 0x17024]
PINS = [(4, 0), (4, 0x1000), (5, 0x3000), (6, 0x2000),
        (6, 0x3000), (7, 0), (7, 0x1000)]
ADDRESSES = [(1, offset) for offset in GCC] + [
    (page, offset + delta) for page, offset in PINS for delta in (0, 4)] + [(2, 0x84)]


def literal(filename, name):
    values = [ast.literal_eval(node.value) for node in ast.walk(ast.parse((HERE / filename).read_text()))
              if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name
                                                     for target in node.targets)]
    assert len(values) == 1
    return values[0]


EXTRA = r'''
#include <stdarg.h>
static unsigned kind,commands,cancels,aborts,data_reads,rx_cursor,tx_count,status_reads,seen_irq;
static unsigned in_platform,platform_reads,platform_lines,core_off,branch_off,sahb,inject_report;
static unsigned platforms[64],offsets[64],log_cancel[2],log_routes[2],log_commands[2];
static uint8_t tx_bytes[8],response[16];
static uint32_t write_trace,delay_trace;
#ifdef TEST_PLATFORM_OVERLAY
void redfin_touch_platform_diag_report(unsigned phase);
#endif
static int model_printf(const char *f,...) __attribute__((format(__printf__,1,2)));
static int model_printf(const char *f,...){
 if(strstr(f,"REDFIN TOUCH PLATFORM:")){
  platform_lines++;
  if(strstr(f,"VOTE=")){
   va_list args;va_start(args,f);const char *phase=va_arg(args,const char *);
   unsigned index=!strcmp(phase,"before-first-tx")?0:1;
   log_cancel[index]=cancels;log_routes[index]=se[0xe1c/4];log_commands[index]=commands;va_end(args);
  }
 }
 return 0;
}
'''

RESET = r'''
    kind=transport;commands=cancels=aborts=data_reads=rx_cursor=tx_count=status_reads=seen_irq=0;
    in_platform=platform_reads=platform_lines=core_off=branch_off=0;sahb=0x80000002u;inject_report=1;
    memset(platforms,0,sizeof(platforms));memset(offsets,0,sizeof(offsets));
    memset(tx_bytes,0,sizeof(tx_bytes));memset(response,0,sizeof(response));
    memset(log_cancel,0,sizeof(log_cancel));memset(log_routes,0,sizeof(log_routes));
    memset(log_commands,0,sizeof(log_commands));
    write_trace=delay_trace=2166136261u;
    redfin_spi_attempted=redfin_spi_event_open=false;
    redfin_spi_verified_se=0;redfin_spi_verified_hz=0;
    memset(&redfin_spi_event_context,0,sizeof(redfin_spi_event_context));
    redfin_spi_diag_command_logged=false;redfin_spi_diag_failures=0;
#ifdef RF_TOUCH_PLATFORM_DIAG
    redfin_platform_diag_published=false;
    memset(&redfin_platform_diag_maps,0,sizeof(redfin_platform_diag_maps));
    memset(redfin_platform_snapshots,0,sizeof(redfin_platform_snapshots));
    memset(redfin_platform_claimed,0,sizeof(redfin_platform_claimed));
    memset(redfin_platform_ready,0,sizeof(redfin_platform_ready));
    memset(redfin_platform_reported,0,sizeof(redfin_platform_reported));
#endif
'''

ACCESSORS = r'''
unsigned transport_stat(unsigned n){
 const unsigned v[]={commands,cancels,aborts,data_reads,tx_count,seen_irq,write_trace,delay_trace,
  se[0xe1c/4],se[0x614/4],redfin_touch_spi_identity_ready()};
 return n<sizeof(v)/sizeof(v[0])?v[n]:0;
}
unsigned platform_stat(unsigned n){
 const unsigned v[]={platform_reads,platform_lines,in_platform,log_cancel[0],log_cancel[1],log_routes[1],
  log_commands[0],log_commands[1]};
 return n<sizeof(v)/sizeof(v[0])?v[n]:0;
}
unsigned address(unsigned n,unsigned field){return n<platform_reads && n<64?(field?offsets[n]:platforms[n]):0;}
unsigned state(unsigned n){
 if(n<sizeof(se)/sizeof(se[0]))return se[n];
 n-=sizeof(se)/sizeof(se[0]);if(n<14)return pins[n/2][n%2];
 n-=14;const unsigned v[]={vote,cfg,cmd,dfs};return n<4?v[n]:0;
}
unsigned request_byte(unsigned n){return n<8?tx_bytes[n]:0;}
unsigned evidence(unsigned phase,unsigned field){
#ifdef RF_TOUCH_PLATFORM_DIAG
 if(phase>1)return 0;
 const struct redfin_platform_snapshot *d=&redfin_platform_snapshots[phase];
 if(field<12)return d->gcc[field];field-=12;
 if(field<14)return d->pins[field/2][field%2];field-=14;
 return field==0?d->seq_read:field==1?d->seq_start:redfin_platform_ready[phase];
#else
 (void)phase;(void)field;return 0;
#endif
}
void repeat(unsigned phase){
#ifdef RF_TOUCH_PLATFORM_DIAG
 for(unsigned n=0;n<100;n++){
  redfin_touch_platform_diag_capture(phase);redfin_touch_platform_diag_report(phase);
 }
#else
 (void)phase;
#endif
}
void manual_capture(unsigned guard){
 /* Only synthetic model state changes; the production helper remains read-only. */
 if(guard==1)vote&=~0x40u;
 if(guard==2)core_off=1;
 if(guard==3)cmd|=0x80000000u;
 if(guard==4)sahb=0x80000000u;
 if(guard==5)sahb=0;
 if(guard==6)branch_off=0x17004;
 if(guard==7)branch_off=0x23000;
 if(guard==8)branch_off=0x23008;
 repeat(1);
}
'''


class TouchPlatformDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.libs = []
        for overlay in (False, True):
            work = root / str(overlay)
            directory = work / 'bsd/dev'
            directory.mkdir(parents=True)
            for name, patch in [('setup', 'touch-setup.patch'), ('spi', 'touch-spi.patch')]:
                (directory / f'redfin_touch_{name}.c').write_text(added_file(
                    (HERE / patch).read_text(), f'bsd/dev/redfin_touch_{name}.c'))
            for patch in ['touch-events.patch', 'touch-spi-diag.patch'] + (['touch-platform-diag.patch'] if overlay else []):
                subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_touch_spi.c',
                                '--include=bsd/dev/redfin_touch_setup.c', str(HERE / patch)], cwd=work, check=True)
            setup, spi = [(directory / f'redfin_touch_{name}.c').read_text() for name in ('setup', 'spi')]
            if overlay:
                setup = setup.replace(' return redfin_setup_rd(base,offset);',
                                      ' in_platform++;uint32_t value=redfin_setup_rd(base,offset);in_platform--;return value;')
            for old, new in [('*(volatile const uint32_t *)(base + offset)', 'model_read(base,offset)'),
                             ('*(volatile uint32_t *)(base + offset) = value;', 'model_write(base,offset,value);')]:
                setup = setup.replace(old, new)
            for old, new in [('*(volatile const uint32_t *)(s->se + offset)', 'model_read(s->se,offset)'),
                             ('*(volatile uint32_t *)(s->se + offset) = value;', 'model_write(s->se,offset,value);')]:
                spi = spi.replace(old, new)
            spi = spi.replace('redfin_touch_spi_probe(vm_offset_t se, unsigned verified_speed_hz, bool gic_irq_masked)\n{',
                              'redfin_touch_spi_probe(vm_offset_t se, unsigned verified_speed_hz, bool gic_irq_masked)\n{\n id_calls++;')
            setup, spi = [re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', re.sub(r'^#include.*\n', '', s, flags=re.M))
                          for s in (setup, spi)]
            stub = literal('test_touch_setup.py', 'stub')
            stub = stub.replace(function(stub, 'int redfin_touch_spi_probe('), '')
            stub = stub.replace('static int model_printf(const char *f,...) {(void)f;return 0;}', '')
            point = 'static const uint64_t ranges[]='
            stub = stub.replace(point, EXTRA + point)
            spi_stub = literal('test_touch_spi.py', 'stub')
            read = function(spi_stub, 'static uint32_t model_read(').replace('model_read(', 'spi_read(').replace('registers', 'se')
            # Read count drift is irrelevant to the physical snapshot and does not trigger synthetic busy work.
            read = read.replace('if(offset==0x40 && ++status_reads==2 && kind==12)',
                                'if(offset==0x40 && ++status_reads==2 && kind==12 && id_calls)')
            write = function(spi_stub, 'static void model_write(').replace('model_write(', 'spi_write(').replace('registers', 'se')
            start, end = write.index('    writes++;'), write.index('    if(offset==0x618)')
            write = write[:start] + write[end:]
            write = write.replace('if(kind>=1 && kind<=3)return;', r'''
            if(kind==31){cmd|=0x80000000u;return;}
            if(kind==32){core_off=1;return;}
            if(kind==33){cfg^=0x100u;pins[3][0]^=0x40u;return;}
            if(kind>=1 && kind<=3)return;''')
            stub = stub.replace('static uint32_t model_read(vm_offset_t base,unsigned offset){', read + write + r'''
static uint32_t model_read(vm_offset_t base,unsigned offset){
 if(in_platform){
  bool allowed=false;
  const unsigned gcc[]={0x52008,0x17004,0x17008,0x1700c,0x23000,0x23008,
    0x17010,0x17014,0x17018,0x1701c,0x17020,0x17024};
  if(base==1)for(unsigned i=0;i<12;i++)if(offset==gcc[i])allowed=true;
  if(base==2 && offset==0x84)allowed=true;
  if(pin_index((unsigned)base,offset)>=0)allowed=true;
  if(!allowed)violations++;
  if(platform_reads<64){platforms[platform_reads]=(unsigned)base;offsets[platform_reads]=offset;}
  platform_reads++;
#ifdef TEST_PLATFORM_OVERLAY
  /* A preempting reporter must not see the claimed but incomplete snapshot. */
  if(inject_report && platform_reads==1){redfin_touch_platform_diag_report(0);if(platform_lines)violations++;}
#endif
 }
''')
            stub = stub.replace('if(offset==0x17008)return 0x80000002;', 'if(offset==0x17008)return sahb;')
            stub = stub.replace('if(offset==0x17024)return dfs;',
                                'if(offset==0x17024)return dfs;\n        if(offset==0x17018 || offset==0x1701c || offset==0x17020)return 0;')
            stub = stub.replace('if(mask){if(offset==0x1700c)',
                                'if(mask){if((core_off && mask==0x400) || offset==branch_off)return 0x80000000u;if(offset==0x1700c)')
            stub = stub.replace('if(offset<sizeof(se) && offset%4==0)return se[offset/4];',
                                'if(offset<sizeof(se) && offset%4==0)return spi_read(offset);')
            stub = stub.replace('    writes++;',
                                '    writes++;write_trace=(write_trace^(uint32_t)base)*16777619u;\n'
                                '    write_trace=(write_trace^offset)*16777619u;write_trace=(write_trace^value)*16777619u;')
            stub = stub.replace('cmd=fault==10 ? value|1 : value&~1u;',
                                'cmd=fault==10 ? value|1 : value&~0x80000001u;')
            stub = stub.replace('0x254,0x24,0x20,0x618,0x648};',
                                '0x254,0x24,0x20,0x618,0x648,0x80c,0x810,0x814,0x26c,0x270,0x600,0x700,0x604};')
            stub = stub.replace('se[offset/4]=value;return;', 'spi_write(offset,value);return;')
            stub = stub.replace('wait_us+=us;', 'wait_us+=us;delay_trace=(delay_trace^us)*16777619u;')
            wrapper = literal('test_touch_setup.py', 'wrapper')
            wrapper = wrapper.replace('unsigned issue,bool rail,bool exclusive)',
                                      'unsigned issue,bool rail,bool exclusive,unsigned transport)')
            wrapper = wrapper.replace('    mode=selected;enabled=setup;fault=issue;',
                                      '    mode=selected;enabled=setup;fault=issue;\n' + RESET)
            wrapper = wrapper.replace('se[0x48/4]=0x11;', 'se[0x48/4]=0x11;se[0x84/4]=0x12345678;')
            header = added_file((HERE / 'touch.patch').read_text(), 'bsd/dev/redfin_touch_protocol.h')
            (work / 'redfin_touch_protocol.h').write_text(header)
            (work / 'model.c').write_text(('#define TEST_PLATFORM_OVERLAY 1\n' if overlay else '') + stub +
                                         '#include "redfin_touch_protocol.h"\n' + setup + spi + wrapper + ACCESSORS)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.run.argtypes = [C.c_uint] * 3 + [C.c_bool] * 2 + [C.c_uint]
            for name in ('stat', 'transport_stat', 'platform_stat', 'address', 'state',
                         'request_byte', 'evidence'):
                getattr(lib, name).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.diag = cls.libs

    def pair(self, transport=0, issue=0, mode=2, enabled=1, rail=True, exclusive=True):
        results = [lib.run(mode, enabled, issue, rail, exclusive, transport) for lib in self.libs]
        self.assertEqual(results[0], results[1])
        for index in (0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
            self.assertEqual(self.baseline.stat(index), self.diag.stat(index), f'setup stat {index}')
        self.assertEqual(self.diag.stat(8), 0, 'Unexpected MMIO/map, unclocked SE or GPIO ordering')
        self.assertEqual([self.baseline.transport_stat(i) for i in range(11)],
                         [self.diag.transport_stat(i) for i in range(11)], 'Transport, writes or delays changed')
        self.assertEqual([self.baseline.state(i) for i in range(1024 + 18)],
                         [self.diag.state(i) for i in range(1024 + 18)], 'Final register/pad state changed')
        self.assertEqual([self.baseline.request_byte(i) for i in range(8)],
                         [self.diag.request_byte(i) for i in range(8)])
        self.assertLessEqual(self.diag.platform_stat(0), 54)
        self.assertLessEqual(self.diag.platform_stat(1), 10)
        self.assertEqual(self.diag.platform_stat(2), 0)
        return results[1]

    def test_success_reads_exact_allowlist_after_proof_and_before_first_tx(self):
        self.assertEqual(self.pair(), 0)
        self.assertEqual([self.diag.platform_stat(i) for i in range(3)], [27, 5, 0])
        self.assertEqual([(self.diag.address(i, 0), self.diag.address(i, 1)) for i in range(27)], ADDRESSES)
        self.assertEqual(self.diag.evidence(0, 26), 1)
        self.assertEqual(self.diag.evidence(0, 27), 0x12345678)
        self.assertEqual(self.diag.platform_stat(3), 0)
        self.assertEqual(self.diag.platform_stat(6), 0)
        self.assertEqual(self.diag.stat(0), 7)
        self.assertEqual(self.diag.transport_stat(0), 2)
        self.assertEqual(self.diag.transport_stat(3), 4)
        self.assertEqual(bytes(self.diag.request_byte(i) for i in range(8)), bytes.fromhex('aa0001000522d200'))

    def test_timeout_recovery_and_bad_frames_keep_baseline_writes_delays_and_fifo(self):
        for fault in range(1, 14):
            with self.subTest(fault=fault):
                self.pair(fault)
                if fault in (1, 2, 3):
                    self.assertEqual([self.diag.platform_stat(i) for i in range(2)], [54, 10])
                    self.assertEqual(self.diag.platform_stat(4), 1, 'Failure report must follow cancel')
                    self.assertEqual(self.diag.platform_stat(5), 0, 'Report must follow route disable')
                    self.assertEqual(self.diag.platform_stat(7), 1)

    def test_only_pending_clock_or_pad_drift_is_captured_without_policy_change(self):
        for fault in (31, 32, 33):
            with self.subTest(fault=fault):
                self.assertEqual(self.pair(fault), errno.ETIMEDOUT)
                self.assertEqual(self.diag.evidence(0, 26), 1)
                self.assertEqual(self.diag.evidence(1, 26), int(fault == 33))
                self.assertEqual(self.diag.platform_stat(0), 54 if fault == 33 else 53)
                if fault == 31:
                    self.assertEqual(self.diag.evidence(1, 6) & 0x80000000, 0x80000000)
                if fault == 32:
                    self.assertEqual(self.diag.evidence(1, 3), 0x80000000)
                if fault == 33:
                    self.assertEqual(self.diag.evidence(0, 7) ^ self.diag.evidence(1, 7), 0x100)
                    self.assertEqual(self.diag.evidence(0, 18) ^ self.diag.evidence(1, 18), 0x40)

    def test_failed_setup_or_missing_proof_has_no_platform_capture(self):
        for issue in list(range(1, 20)) + [22, 30, 31, 32, 33, 34, 35, 36]:
            with self.subTest(issue=issue):
                self.assertNotEqual(self.pair(issue=issue), 0)
                self.assertEqual(self.diag.platform_stat(0), 0)
        for args in ({'mode': 0}, {'mode': 1}, {'mode': 3}, {'enabled': 0},
                     {'rail': False}, {'exclusive': False}):
            self.assertEqual(self.pair(**args), errno.ENOTSUP)
            self.assertEqual(self.diag.platform_stat(0), 0)

    def test_captures_reports_and_invalid_phases_are_bounded(self):
        self.pair(3)
        before = [self.diag.transport_stat(i) for i in range(11)]
        for phase in (0, 1, 2, 0xffffffff):
            self.diag.repeat(phase)
        self.assertEqual([self.diag.platform_stat(i) for i in range(2)], [54, 10])
        self.assertEqual([self.diag.transport_stat(i) for i in range(11)], before)

    def test_seq_read_obeys_each_physical_clock_guard_and_native_hwcg_exception(self):
        for guard in range(9):
            with self.subTest(guard=guard):
                self.pair()
                before = [self.diag.transport_stat(i) for i in range(11)]
                self.diag.manual_capture(guard)
                permitted = guard in (0, 5)
                self.assertEqual(self.diag.evidence(1, 26), int(permitted))
                self.assertEqual(self.diag.platform_stat(0), 54 if permitted else 53)
                self.assertEqual(self.diag.platform_stat(1), 10)
                self.assertEqual([self.diag.transport_stat(i) for i in range(11)], before)


if __name__ == '__main__':
    unittest.main()
