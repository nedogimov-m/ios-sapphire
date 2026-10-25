"""Exercise the actual final logger and decode its immutable prefix/rolling tail."""
import ctypes as C
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_cycle import cycle
from test_display_geometry import function

HERE=Path(__file__).resolve().parent


class PrefixLoggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native=HERE.parents[1]/'research/redfin-build/dxb/xnu/pexpert/arm/pe_serial.c'
        if not native.is_file():raise unittest.SkipTest('prepared native logger required')
        text=native.read_text()
        body=function(text,'void\nredfin_log_putc(')
        initialize=re.search(r'  redfin_log_prefix\[i\]=.*?;',text).group()
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);p=Path(cls.tmp.name)
        source=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
struct redfin_ramlog {volatile uint32_t signature,start,size;volatile unsigned char data[];};
static struct redfin_ramlog *redfin_logs[2];
static uint32_t redfin_log_capacity[2],redfin_log_prefix[2];
static unsigned redfin_log_count=2;
static volatile uint32_t *redfin_watchdog_reset;
static uint64_t redfin_watchdog_deadline,redfin_watchdog_last,redfin_watchdog_frequency;
static bool redfin_log_enter(uint64_t *saved,bool all,bool c){(void)all;(void)c;*saved=0;return true;}
static void redfin_log_leave(uint64_t saved){(void)saved;}
static void redfin_log_barrier(void){__atomic_thread_fence(__ATOMIC_SEQ_CST);}
static unsigned redfin_log_cpu(void){return 1;}
static uint64_t redfin_log_counter(void){return 1;}
'''+body+r'''
void initialize(unsigned capacity0,unsigned capacity1){
 uint32_t capacity[2]={capacity0,capacity1};
 for(unsigned i=0;i<2;i++){
  free(redfin_logs[i]);redfin_logs[i]=calloc(1,capacity[i]+12);
  redfin_log_capacity[i]=capacity[i];
'''+initialize+r'''
  redfin_logs[i]->signature=redfin_log_prefix[i]?0x32484652:0x43474244;
 }
}
void append(const char *bytes,unsigned length){for(unsigned i=0;i<length;i++)redfin_log_putc(bytes[i]);}
void dump(unsigned i,void *out){memcpy(out,redfin_logs[i],redfin_log_capacity[i]+12);}
void corrupt_cursor(unsigned i,unsigned start,unsigned size){redfin_logs[i]->start=start;redfin_logs[i]->size=size;}
'''
        (p/'logger.c').write_text(source)
        result=subprocess.run(['cc','-O2','-std=c11','-shared','-fPIC','-Wall','-Wextra','-Werror',
            str(p/'logger.c'),'-o',str(p/'logger.so')],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        cls.lib=C.CDLL(str(p/'logger.so'));cls.lib.append.argtypes=[C.c_char_p,C.c_uint]
        cls.lib.dump.argtypes=[C.c_uint,C.c_void_p]

    def raw(self,i,capacity):
        raw=C.create_string_buffer(capacity+12);self.lib.dump(i,raw);return bytes(raw)

    def test_native_writes_preserve_startup_and_exact_latest_tail_after_many_wraps(self):
        banner=b'[REDFIN RAMLOG v1: serial and console]\nREDFIN BOOT ID: 0123456789abcdef\n'
        for capacity in [64,256,512,4096,1048564]:
            prefix=min(0x40000,capacity//4)
            for length in [0,1,prefix,capacity-1,capacity,capacity+1,capacity*3+17]:
                self.lib.initialize(capacity,capacity)
                history=(banner+bytes(range(256))*((length+255)//256))[:length]
                self.lib.append(history,len(history))
                legacy=cycle.extract_ring(self.raw(0,capacity),0,capacity+12)
                actual=cycle.extract_ring(self.raw(1,capacity),0,capacity+12)
                self.assertEqual(legacy,history[-capacity:])
                expected=history if length<capacity else history[:prefix]+b'\n[REDFIN RAMLOG GAP: startup prefix followed by recent tail]\n'+history[-(capacity-prefix):]
                self.assertEqual(actual,expected,(capacity,length))
                if prefix>=len(banner) and length>=capacity:
                    proof=cycle.boot_id_freshness(actual,'0123456789abcdef',True)
                    self.assertEqual(proof['status'],'boot-id-matched')

    def test_corrupt_prefix_cursor_is_neither_written_nor_accepted(self):
        self.lib.initialize(256,256);self.lib.corrupt_cursor(1,0,256)
        before=self.raw(1,256);self.lib.append(b'x',1)
        self.assertEqual(self.raw(1,256),before)
        with self.assertRaises(ValueError):cycle.extract_ring(before,0,268)
        self.lib.corrupt_cursor(1,256,100)
        before=self.raw(1,256);self.lib.append(b'x',1)
        self.assertEqual(self.raw(1,256),before)
        with self.assertRaises(ValueError):cycle.extract_ring(before,0,268)


if __name__=='__main__':unittest.main()
