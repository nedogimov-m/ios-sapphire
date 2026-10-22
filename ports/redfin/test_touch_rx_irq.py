"""Actual setup/SPI: accept latched M_RX_IRQ without enabling its hardware IRQ."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_touch_dfs_disable as disable_model
from ports.redfin.test_touch import added_file

HERE = Path(__file__).resolve().parent

ACK = r'''
    if(offset==0x618){
        se[0x610/4]&=~value;
        if(kind==40 && commands==2){
            if(rx_irq_stage==0 && (value&0x80)){
                rx_irq_stage=1;se[0x804/4]=0x80000002;se[0x610/4]=1u<<26;
            }else if(rx_irq_stage==1 && (value&(1u<<26))){
                rx_irq_stage=2;se[0x804/4]=0x80000002;se[0x610/4]=(1u<<27)|1;se[0x40/4]=0;
            }
        }
        if(kind==50 && commands==1 && (value&1))se[0x610/4]=0x80;
        if(kind==51 && commands==2 && (value&0x80)){
            se[0x804/4]=0x80000001;se[0x610/4]=(1u<<27)|1;se[0x40/4]=0;
        }
        return;
    }
'''
RX = r'''
            if((kind>=40 && kind<=48) || kind==51){
                se[0x610/4]=0x80;se[0x40/4]=1;se[0x804/4]=0;
                if(kind==42 || kind==48){se[0x610/4]|=1;se[0x40/4]=0;se[0x804/4]=0x80000004;}
                if(kind==43)se[0x610/4]|=8;
                if(kind==44)se[0x610/4]|=1u<<8;
                if(kind==45){se[0x610/4]|=1u<<26;se[0x804/4]=0x80000011;}
                if(kind==46){se[0x610/4]|=1;se[0x40/4]=0;se[0x804/4]=0x80000003;}
                if(kind==47){se[0x610/4]|=1;se[0x40/4]=0;se[0x804/4]=0x90000004;}
                if(kind==48)response[12]^=1;
                if(kind==51)se[0x804/4]=0x80000003;
            }
'''
WRAPPER = r'''
void rx_reset(void){rx_irq_stage=0;}
unsigned masks(unsigned which){
 if(which==0)return RF_SPI_EVENTS;
 if(which==1)return RF_SPI_ERRORS;
#ifdef RF_SPI_STATUS_EVENTS
 return RF_SPI_STATUS_EVENTS;
#else
 return RF_SPI_EVENTS;
#endif
}
'''


def host_spi(source):
    source = source.replace('*(volatile const uint32_t *)(s->se + offset)', 'model_read(s->se,offset)')
    source = source.replace('*(volatile uint32_t *)(s->se + offset) = value;', 'model_write(s->se,offset,value);')
    source = source.replace('redfin_touch_spi_probe(vm_offset_t se, unsigned verified_speed_hz, bool gic_irq_masked)\n{',
                            'redfin_touch_spi_probe(vm_offset_t se, unsigned verified_speed_hz, bool gic_irq_masked)\n{\n id_calls++;')
    source = re.sub(r'^#include.*\n', '', source, flags=re.M)
    return re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', source)


class TouchRXIRQTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        class Fixture(disable_model.TouchDFSDisableTests):
            pass
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        template = (Path(Fixture.temp.name) / 'True/model.c').read_text()
        header = (Path(Fixture.temp.name) / 'True/redfin_touch_protocol.h').read_text()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        tree = root / 'patches'
        dev = tree / 'bsd/dev'
        dev.mkdir(parents=True)
        for name, patch in (('setup', 'touch-setup.patch'), ('spi', 'touch-spi.patch')):
            (dev / f'redfin_touch_{name}.c').write_text(added_file(
                (HERE / patch).read_text(), f'bsd/dev/redfin_touch_{name}.c'))
        for patch in ('touch-events.patch', 'touch-spi-diag.patch', 'touch-platform-diag.patch',
                      'touch-dfs-diag.patch', 'touch-dfs-disable.patch'):
            subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_touch_setup.c',
                            '--include=bsd/dev/redfin_touch_spi.c', str(HERE / patch)], cwd=tree, check=True)
        target = dev / 'redfin_touch_spi.c'
        before = target.read_text()
        subprocess.run(['git', 'apply', str(HERE / 'touch-rx-irq.patch')], cwd=tree, check=True)
        after = target.read_text()
        cls.libs = []
        for source_spi in (before, after):
            source = template
            original = host_spi(before)
            assert source.count(original) == 1, 'Frozen actual SPI model seam changed'
            source = source.replace(original, host_spi(source_spi))
            source = source.replace('static unsigned kind,commands,cancels,aborts,data_reads,rx_cursor,tx_count,status_reads,seen_irq;',
                                    'static unsigned kind,commands,cancels,aborts,data_reads,rx_cursor,tx_count,status_reads,seen_irq,rx_irq_stage;\n'
                                    'static void rx_preflight(void){if(kind==49)se[0x610/4]=0x80;}')
            # V7 proves bit7 can latch independently of M_IRQ_EN.bit7. Inject raw new statuses.
            source = source.replace('uint32_t routed=(se[0xe1c/4]&4) ? se[offset/4]&se[0x614/4] : 0;',
                                    'uint32_t routed=kind>=40 ? se[offset/4] : ((se[0xe1c/4]&4) ? se[offset/4]&se[0x614/4] : 0);')
            source = source.replace('    if(offset==0x618){se[0x610/4]&=~value;return;}', ACK)
            source = source.replace('if(kind==13){se[0x804/4]=2;se[0x610/4]=1u<<26;}',
                                    'if(kind==13){se[0x804/4]=2;se[0x610/4]=1u<<26;}\n' + RX)
            source = source.replace('se[0x40/4]=0;se[0x610/4]=value==4 ? 16 : 32;',
                                    'se[0x40/4]=0;se[0x610/4]=(value==4 ? 16 : 32)|(kind>=40 ? 0x80 : 0);')
            source = source.replace(' id_calls++;', ' id_calls++;rx_preflight();')
            work = root / str(len(cls.libs))
            work.mkdir()
            (work / 'redfin_touch_protocol.h').write_text(header)
            (work / 'model.c').write_text(source + WRAPPER)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.run.argtypes = [C.c_uint] * 3 + [C.c_bool] * 2 + [C.c_uint]
            for name in ('stat', 'transport_stat', 'state', 'disable_stat', 'trace', 'masks'):
                getattr(lib, name).restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.fixed = cls.libs

    def run_probe(self, fault=0, fixed=True):
        lib = self.fixed if fixed else self.baseline
        lib.dfs_reset()
        lib.disable_config(0x301, 0)
        lib.rx_reset()
        result = lib.run(2, 1, 0, True, True, fault)
        self.assertEqual(lib.stat(8), 0)
        self.assertLessEqual(lib.transport_stat(0), 2, 'No retry or additional command')
        self.assertEqual(lib.transport_stat(8), 0)
        self.assertEqual(lib.transport_stat(9), 0)
        return result

    def trace(self, lib=None):
        lib = lib or self.fixed
        return [tuple(lib.trace(index, field) for field in range(3)) for index in range(lib.disable_stat(2))]

    def test_rx_irq_before_watermark_and_last_done_succeeds_without_enabling_bit7(self):
        self.assertEqual(self.run_probe(40, fixed=False), errno.EIO)
        self.assertEqual(self.run_probe(40), 0)
        self.assertEqual([self.fixed.transport_stat(i) for i in (0, 1, 2, 3, 10)], [2, 0, 0, 4, 1])
        self.assertIn((2, 0x618, 0x80), self.trace())
        self.assertEqual(self.fixed.masks(0), self.baseline.masks(0))
        self.assertEqual(self.fixed.masks(1), self.baseline.masks(1))
        self.assertEqual(self.fixed.masks(2), self.baseline.masks(0) | 0x80)
        self.assertTrue(all(not (value & 0x80) for base, offset, value in self.trace() if base == 2 and offset == 0x614))

    def test_standalone_rx_irq_is_not_completion_and_has_bounded_no_retry_timeout(self):
        self.assertEqual(self.run_probe(41), errno.ETIMEDOUT)
        self.assertEqual([self.fixed.transport_stat(i) for i in (0, 1, 2, 3, 10)], [2, 1, 0, 0, 0])
        self.assertEqual(self.fixed.stat(6), 80100)
        self.assertIn((2, 0x618, 0x90), self.trace(), 'Recovery must ack the allowed RX status too')

    def test_rx_irq_with_done_preflight_or_between_commands_remains_nonfatal(self):
        for fault in (42, 49, 50, 51):
            with self.subTest(fault=fault):
                self.assertEqual(self.run_probe(fault), 0)
                self.assertEqual(self.fixed.transport_stat(3), 4)
                self.assertEqual(self.fixed.transport_stat(10), 1)
                self.assertIn((2, 0x618, 0x80 if fault != 42 else 0x81), self.trace())

    def test_mixed_fatal_or_unknown_status_keeps_fail_closed_recovery(self):
        for fault in (43, 44):
            with self.subTest(fault=fault):
                self.assertEqual(self.run_probe(fault), errno.EIO)
                self.assertEqual([self.fixed.transport_stat(i) for i in (0, 1, 2, 3, 10)], [2, 1, 0, 0, 0])
                self.assertIn((2, 0x618, 0x90), self.trace())

    def test_fifo_bounds_valid_bytes_checksum_and_short_done_are_still_enforced(self):
        for fault, reads in ((45, 0), (46, 3), (47, 0), (48, 4)):
            with self.subTest(fault=fault):
                self.assertEqual(self.run_probe(fault), errno.EIO)
                self.assertEqual(self.fixed.transport_stat(3), reads)
                self.assertEqual(self.fixed.transport_stat(10), 0)

    def test_existing_success_and_failures_keep_exact_mmio_delay_and_fifo_behavior(self):
        for fault in range(14):
            with self.subTest(fault=fault):
                results = [self.run_probe(fault, fixed=fixed) for fixed in (False, True)]
                self.assertEqual(results[0], results[1])
                self.assertEqual(self.trace(self.baseline), self.trace(self.fixed))
                self.assertEqual([self.baseline.transport_stat(i) for i in range(11)],
                                 [self.fixed.transport_stat(i) for i in range(11)])
                self.assertEqual([self.baseline.state(i) for i in range(1042)],
                                 [self.fixed.state(i) for i in range(1042)])


if __name__ == '__main__':
    unittest.main()
