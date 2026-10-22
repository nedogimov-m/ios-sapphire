"""Execute draft GENI transport against a bounded host FIFO/MMIO model."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch import added_file


class TouchSPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host C compiler unavailable")
        path = Path(__file__).parent
        header = added_file((path / "touch.patch").read_text(), "bsd/dev/redfin_touch_protocol.h")
        patch = (path / "touch-spi.patch").read_text()
        source = added_file(patch, "bsd/dev/redfin_touch_spi.c")
        source = re.sub(r"^#include.*\n", "", source, flags=re.M)
        source = source.replace('*(volatile const uint32_t *)(s->se + offset)', 'model_read(offset)')
        source = source.replace('*(volatile uint32_t *)(s->se + offset) = value;', 'model_write(offset, value);')
        source = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', source)
        source = source.replace('static uint32_t\nredfin_spi_rd(struct redfin_spi *s, unsigned offset)\n{',
                                'static uint32_t\nredfin_spi_rd(struct redfin_spi *s, unsigned offset)\n{\n(void)s;')
        source = source.replace('static void\nredfin_spi_wr(struct redfin_spi *s, unsigned offset, uint32_t value)\n{',
                                'static void\nredfin_spi_wr(struct redfin_spi *s, unsigned offset, uint32_t value)\n{\n(void)s;')
        stub = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define printf model_printf
typedef uintptr_t vm_offset_t;
static int model_printf(const char *format,...) {(void)format;return 0;}
static unsigned mode,kind,registers[0x1000/4],rx_cursor,tx_count;
static unsigned writes,commands,cancels,aborts,violations,wait_us,data_reads,status_reads,seen_irq;
static uint8_t tx_bytes[8],response[16];
static int PE_parse_boot_argn(const char *name,void *out,int size){
    (void)name;(void)size;*(uint32_t *)out=mode;return 1;
}
static void delay(unsigned us){wait_us+=us;}
static uint32_t model_read(unsigned offset){
    if(offset%4 || offset>=sizeof(registers)){violations++;return 0;}
    if(offset==0x40 && ++status_reads==2 && kind==12)registers[0x40/4]=1;
    if(offset==0x610){
        /* Production semantics: local SE route and M enables gate polled status. */
        uint32_t routed=(registers[0xe1c/4]&4) ? registers[offset/4]&registers[0x614/4] : 0;
        seen_irq|=routed;return routed;
    }
    if(offset==0x780){
        data_reads++;
        if(rx_cursor>=16){violations++;return 0;}
        unsigned word=0;
        for(unsigned b=0;b<4;b++)word|=(unsigned)response[rx_cursor++]<<(8*b);
        unsigned remaining=registers[0x804/4]&0x01ffffff;
        registers[0x804/4]=remaining>1 ? 0x80000000|(remaining-1) : 0;
        if(kind==13 && rx_cursor==8){
            registers[0x804/4]=0x80000002;registers[0x610/4]|=(1u<<27)|1;
        }
        return word;
    }
    return registers[offset/4];
}
static void model_write(unsigned offset,uint32_t value){
    writes++;
    static const unsigned allowed[]={0xe1c,0x618,0x614,0x80c,0x810,0x814,0x25c,0x26c,0x270,0x600,0x700,0x604};
    bool found=false;
    for(unsigned i=0;i<sizeof(allowed)/sizeof(allowed[0]);i++)if(offset==allowed[i])found=true;
    if(!found){violations++;return;}
    if(offset==0x618){registers[0x610/4]&=~value;return;}
    registers[offset/4]=value;
    if(offset==0xe1c && value!=0 && value!=0xf)violations++;
    if(offset==0x600){
        commands++;
        if(value==1u<<27){
            if(commands!=1 || registers[0x26c/4]!=8)violations++;
            registers[0x40/4]=1;
        } else if(value==2u<<27){
            if(commands!=2 || registers[0x270/4]!=16)violations++;
            const uint8_t base[]={0xaa,0,1,0,5,0x22,0,0x53,0x45,0x37,0x91,0,0,0,0,0};
            memcpy(response,base,sizeof(response));
            if(kind==6)response[5]^=1;
            if(kind==9)response[7]^=1;
            for(unsigned i=0;i<12;i++)response[12]=(uint8_t)(response[12]+response[i]);
            if(kind==5)response[12]^=1;
            registers[0x804/4]=0x80000004;
            if(kind==7)registers[0x804/4]=0x80000011;
            if(kind==8)registers[0x804/4]=0x80000003;
            if(kind==11)registers[0x804/4]=0x90000004;
            registers[0x40/4]=0;registers[0x610/4]=1;
            if(kind==13){registers[0x804/4]=2;registers[0x610/4]=1u<<26;}
        } else violations++; /* No fragmented message or other command. */
    }
    if(offset==0x700){
        if(tx_count>=8){violations++;return;}
        for(unsigned i=0;i<4;i++)tx_bytes[tx_count++]=(uint8_t)(value>>(8*i));
        if(tx_count==8){
            if(kind>=1 && kind<=3)return; /* Timeout; keep host active. */
            if(kind==4){registers[0x610/4]=8;return;}
            registers[0x40/4]=0;registers[0x610/4]=1;
            if(kind==10)registers[0x804/4]=4;
        }
    }
    if(offset==0x604){
        if(value==4)cancels++;
        else if(value==2)aborts++;
        else violations++;
        if(kind==3 || (kind==2 && value==4))return;
        registers[0x40/4]=0;registers[0x610/4]=value==4 ? 16 : 32;
    }
}
'''
        wrapper = r'''
int run(unsigned selected,unsigned fault,unsigned speed,bool gic_masked){
    mode=selected;kind=fault;
    writes=commands=cancels=aborts=violations=wait_us=data_reads=rx_cursor=tx_count=status_reads=seen_irq=0;
    memset(registers,0,sizeof(registers));memset(tx_bytes,0,sizeof(tx_bytes));
    redfin_spi_attempted=false;
    registers[0xe24/4]=registers[0xe28/4]=(32u<<24)|(16u<<16);
    registers[0x68/4]=0x101;registers[0x224/4]=1;registers[0x230/4]=4;
    registers[0x268/4]=4;registers[0x260/4]=registers[0x284/4]=RF_SPI_PACK0;
    registers[0x264/4]=registers[0x288/4]=RF_SPI_PACK1;
    registers[0x24/4]=127;registers[0x48/4]=0x21;
    if(fault==100)registers[0x68/4]=0;
    if(fault==101)registers[0x258/4]=1;
    if(fault==102)registers[0xe18/4]=1;
    if(fault==103)registers[0x800/4]=1;
    if(fault==104)registers[0x260/4]=0;
    if(fault==105)registers[0x224/4]=0;
    if(fault==106)registers[0x24/4]=0;
    if(fault==107)registers[0x40/4]=1;
    if(fault==108)registers[0xe24/4]=(16u<<24)|(16u<<16);
    return redfin_touch_spi_probe(1,speed,gic_masked);
}
unsigned stat(unsigned n){
    const unsigned values[]={writes,commands,cancels,aborts,violations,wait_us,data_reads,tx_count,
        registers[0xe1c/4],registers[0x614/4],seen_irq};
    return n<11 ? values[n] : 0;
}
unsigned request_byte(unsigned n){return n<8 ? tx_bytes[n] : 0;}
'''
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        (directory / "redfin_touch_protocol.h").write_text(header)
        (directory / "transport.c").write_text(stub + '#include "redfin_touch_protocol.h"\n' + source + wrapper)
        library = directory / "transport.so"
        subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(directory / "transport.c"), "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint] * 3 + [C.c_bool]

    def run_probe(self, fault=0, mode=2, speed=9600000, gic_masked=True):
        result = self.lib.run(mode, fault, speed, gic_masked)
        self.assertEqual(self.lib.stat(4), 0, "unexpected MMIO write, CS framing or FIFO access")
        self.assertLessEqual(self.lib.stat(5), 12100)
        self.assertEqual(self.lib.stat(8), 0, "local IRQ routes must be disabled on exit")
        self.assertEqual(self.lib.stat(9), 0, "local M event enables must be disabled on exit")
        return result

    def test_default_and_unverified_speed_never_write(self):
        for mode in (0, 1, 3, 0xffffffff):
            self.assertEqual(self.run_probe(mode=mode), errno.ENOTSUP)
            self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual(self.run_probe(gic_masked=False), errno.ENOTSUP)
        self.assertEqual(self.lib.stat(0), 0)
        for speed in (0, 10000001):
            self.assertEqual(self.run_probe(speed=speed), errno.ENOTSUP)
            self.assertEqual(self.lib.stat(0), 0)

    def test_preflight_rejects_unconfigured_or_owned_host_without_writes(self):
        for fault in range(100, 109):
            self.assertEqual(self.run_probe(fault), errno.ENOTSUP)
            self.assertEqual(self.lib.stat(0), 0)

    def test_actual_id_request_two_cs_phases_and_verified_response(self):
        self.assertEqual(self.run_probe(), 0)
        self.assertEqual(self.lib.stat(1), 2)
        self.assertEqual(self.lib.stat(6), 4)
        self.assertEqual(self.lib.stat(5), 100)
        self.assertEqual(bytes(self.lib.request_byte(i) for i in range(8)),
                         bytes.fromhex("aa0001000522d200"))

    def test_watermark_then_last_done_require_local_status_routing(self):
        self.assertEqual(self.run_probe(13), 0)
        self.assertEqual(self.lib.stat(1), 2)
        self.assertEqual(self.lib.stat(6), 4)
        self.assertEqual(self.lib.stat(10) & ((1 << 26) | (1 << 27) | 1),
                         (1 << 26) | (1 << 27) | 1)

    def test_timeout_cancel_then_abort_are_bounded_and_never_retry(self):
        for fault, cancels, aborts in ((1, 1, 0), (2, 1, 1), (3, 1, 1)):
            self.assertEqual(self.run_probe(fault), errno.ETIMEDOUT)
            self.assertEqual(self.lib.stat(1), 1)
            self.assertEqual(self.lib.stat(2), cancels)
            self.assertEqual(self.lib.stat(3), aborts)

    def test_command_failure_stops_before_read_phase(self):
        self.assertEqual(self.run_probe(4), errno.EIO)
        self.assertEqual(self.lib.stat(1), 1)
        self.assertEqual(self.lib.stat(2), 1)

    def test_busy_before_our_command_never_cancels_foreign_work(self):
        self.assertEqual(self.run_probe(12), errno.EBUSY)
        self.assertEqual(self.lib.stat(1), 0)
        self.assertEqual(self.lib.stat(2), 0)
        self.assertEqual(self.lib.stat(3), 0)

    def test_bad_frames_fifo_bounds_and_short_done_fail_without_retry(self):
        for fault in (5, 6, 7, 8, 10, 11):
            self.assertEqual(self.run_probe(fault), errno.EIO)
            self.assertLessEqual(self.lib.stat(1), 2)
        self.assertEqual(self.run_probe(9), errno.ENXIO)


if __name__ == "__main__":
    unittest.main()
