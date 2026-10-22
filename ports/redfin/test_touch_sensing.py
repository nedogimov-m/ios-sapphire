"""Actual GENI SPI sensing initialization with a framed SEC controller model."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch import added_file

HERE = Path(__file__).resolve().parent
MODEL = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define printf model_printf
typedef uintptr_t vm_offset_t;
static unsigned mode=2,event_enable=1,kind,fail_command,fail_style,commands,cancels,aborts,wait_us,bad;
static unsigned tx_cursor,rx_cursor,request_reg,request_count,frame_count,functions_writes,sense_writes;
static unsigned data_reads,write_count,log_size,read_count[256],frame_size[64],trace[20000][2];
static uint32_t registers[0x1000/4];
static uint16_t functions,initial_functions;
static uint8_t tx[12],frames[64][12],response[256];
static char logs[32768];
static int model_printf(const char *f,...) __attribute__((format(__printf__,1,2)));
static int model_printf(const char *f,...){
 va_list args;va_start(args,f);int n=vsnprintf(logs+log_size,sizeof(logs)-log_size,f,args);va_end(args);
 if(n<0 || (unsigned)n>=sizeof(logs)-log_size){bad++;return -1;}log_size+=(unsigned)n;return n;
}
static int PE_parse_boot_argn(const char *name,void *out,int bytes){
 (void)bytes;*(uint32_t *)out=!strcmp(name,"redfintouchevents")?event_enable:mode;return 1;
}
static void delay(unsigned us){wait_us+=us;}
void redfin_touch_platform_diag_capture(unsigned phase){(void)phase;}
void redfin_touch_platform_diag_report(unsigned phase){(void)phase;}
static uint32_t model_read(unsigned offset){
 if(offset>=sizeof(registers) || (offset&3)){bad++;return 0;}
 if(offset==0x804 && !registers[offset/4] && registers[0x600/4]==(2u<<27) &&
    registers[0x270/4]>64 && rx_cursor<registers[0x270/4]){
  unsigned words=(registers[0x270/4]-rx_cursor)/4;if(words>16)words=16;
  bool last=rx_cursor+words*4==registers[0x270/4];
  registers[offset/4]=(last?0x80000000u:0)|words;
  registers[0x610/4]=0x80|(last?(1u<<27)|1:1u<<26);registers[0x40/4]=last?0:1;
 }
 if(offset==0x780){
  unsigned bytes=registers[0x270/4];if(rx_cursor+4>bytes){bad++;return 0;}
  uint32_t word=0;for(unsigned i=0;i<4;i++)word|=(uint32_t)response[rx_cursor++]<<(i*8);
  unsigned left=registers[0x804/4]&0x1ffffff;registers[0x804/4]=left>1?0x80000000u|(left-1):0;
  data_reads++;return word;
 }
 return registers[offset/4];
}
static void make_event(uint8_t *p,unsigned remaining){
 p[0]=0x44;p[1]=31;p[2]=62;p[3]=0x48;p[7]=(uint8_t)remaining;
}
static void make_response(void){
 memset(response,0,sizeof(response));unsigned reg=request_reg,count=request_count;read_count[reg]++;
 response[0]=0xaa;response[2]=1;response[3]=(uint8_t)(count>>8);response[4]=(uint8_t)count;response[5]=(uint8_t)reg;
 if(reg==0x22){const uint8_t id[]={0x53,0x45,0x37,0x91,0};memcpy(response+7,id,5);}
 if(reg==0x55)response[7]=kind==1?0x10:0x20;
 if(reg==0xaf){response[7]=1;response[8]=(kind==2 || (kind==4 && read_count[reg]>1))?4:2;response[9]=2;}
 if(reg==0x30){uint16_t value=functions;if(kind==3 && read_count[reg]>1)value^=0x100u;response[7]=(uint8_t)value;response[8]=(uint8_t)(value>>8);}
 if(reg==0x60 && kind>=10){
  make_event(response+7,kind==11?31:kind==12?32:kind==15?1:0);
  if(kind==13){response[7]=5;response[8]=1;}
  if(kind==14){response[7]=9;response[8]=0;response[9]=0x20;}
 }
 if(reg==0x61)for(unsigned i=0;i<count/8;i++)make_event(response+7+i*8,count/8-i-1);
 if(kind==15 && reg==0x61)response[7]=0;
 for(unsigned i=0;i<7+count;i++)response[7+count]=(uint8_t)(response[7+count]+response[i]);
 if(commands==fail_command && fail_style==3)response[7+count]^=1;
 if(commands==fail_command && fail_style==4)response[5]^=1;
}
static void model_write(unsigned offset,uint32_t value){
 const unsigned allowed[]={0xe1c,0x618,0x614,0x80c,0x810,0x814,0x25c,0x26c,0x270,0x600,0x700,0x604};
 bool ok=false;for(unsigned i=0;i<sizeof(allowed)/sizeof(allowed[0]);i++)if(offset==allowed[i])ok=true;
 if(!ok){bad++;return;}
 if(write_count<20000){trace[write_count][0]=offset;trace[write_count][1]=value;}else bad++;write_count++;
 if(offset==0x618){registers[0x610/4]&=~value;return;}
 registers[offset/4]=value;
 if(offset==0x600){
  commands++;tx_cursor=rx_cursor=0;
  if(value==1u<<27){memset(tx,0,sizeof(tx));registers[0x40/4]=1;registers[0x610/4]=0;}
  else if(value==2u<<27){
   make_response();registers[0x40/4]=0;registers[0x610/4]=0x81;
   registers[0x804/4]=0x80000000u|(registers[0x270/4]/4);
   if(registers[0x270/4]>64){registers[0x804/4]=16;registers[0x610/4]=0x80|(1u<<26);registers[0x40/4]=1;}
   if(commands==fail_command){
    if(fail_style==1 || fail_style==2){registers[0x40/4]=1;registers[0x610/4]=0;registers[0x804/4]=0;}
    if(fail_style==5){registers[0x40/4]=1;registers[0x610/4]=8;registers[0x804/4]=0;}
    if(fail_style==6)registers[0x804/4]=0x80000011;
    if(fail_style==7)registers[0x804/4]--;
   }
  }else bad++;
 }
 if(offset==0x700){
  unsigned bytes=registers[0x26c/4];if((bytes!=8 && bytes!=12) || tx_cursor+4>bytes){bad++;return;}
  for(unsigned i=0;i<4;i++)tx[tx_cursor++]=(uint8_t)(value>>(i*8));
  if(tx_cursor==bytes){
   if(frame_count>=64){bad++;return;}memcpy(frames[frame_count],tx,bytes);frame_size[frame_count++]=bytes;
   if(commands==fail_command && (fail_style==1 || fail_style==2 || fail_style==5)){
    if(fail_style==5)registers[0x610/4]=8;return;
   }
   if(bytes==12 && tx[5]==0x30){functions_writes++;functions=(uint16_t)(tx[6]|((uint16_t)tx[7]<<8));}
   else if(bytes==8 && tx[5]==0x10 && !tx[4])sense_writes++;
   else{request_reg=tx[5];request_count=((unsigned)tx[3]<<8)|tx[4];}
   registers[0x40/4]=0;registers[0x610/4]=1;
  }
 }
 if(offset==0x604){
  if(value==4)cancels++;else if(value==2)aborts++;else bad++;
  if(fail_style==2 && commands==fail_command)return;
  registers[0x40/4]=0;registers[0x610/4]=value==4?16:32;
 }
}
'''
WRAPPER = r'''
void reset(void){
 memset(registers,0,sizeof(registers));memset(frames,0,sizeof(frames));memset(frame_size,0,sizeof(frame_size));
 memset(read_count,0,sizeof(read_count));memset(logs,0,sizeof(logs));memset(trace,0,sizeof(trace));
 mode=2;event_enable=1;kind=fail_command=fail_style=commands=cancels=aborts=wait_us=bad=0;
 tx_cursor=rx_cursor=request_reg=request_count=frame_count=functions_writes=sense_writes=data_reads=write_count=log_size=0;
 functions=initial_functions=0x1802;
 redfin_spi_attempted=redfin_spi_event_open=false;redfin_spi_verified_se=0;redfin_spi_verified_hz=0;
 memset(&redfin_spi_event_context,0,sizeof(redfin_spi_event_context));
 redfin_spi_diag_command_logged=false;redfin_spi_diag_failures=0;
#ifdef TEST_SENSING
 redfin_spi_scan_attempted=redfin_spi_scan_active=redfin_spi_sense_attempted=false;
#endif
 registers[0xe24/4]=registers[0xe28/4]=(32u<<24)|(16u<<16);
 registers[0x68/4]=0x101;registers[0x224/4]=1;registers[0x230/4]=4;registers[0x268/4]=4;
 registers[0x260/4]=registers[0x284/4]=RF_SPI_PACK0;registers[0x264/4]=registers[0x288/4]=RF_SPI_PACK1;
 registers[0x24/4]=127;registers[0x48/4]=0x141;
}
int prime(void){return redfin_touch_spi_probe(1,960000,true);}
void configure(unsigned issue,unsigned failed,unsigned style,unsigned feature){
 kind=issue;fail_command=failed;fail_style=style;functions=initial_functions=(uint16_t)feature;
 commands=cancels=aborts=wait_us=tx_cursor=rx_cursor=frame_count=functions_writes=sense_writes=data_reads=write_count=log_size=0;
 memset(read_count,0,sizeof(read_count));memset(logs,0,sizeof(logs));
 if(issue==20)registers[0x40/4]=1;
}
int scan(bool mask,unsigned batches){
#ifdef TEST_SENSING
 return redfin_touch_spi_scan_probe(mask,batches);
#else
 (void)mask;(void)batches;return ENOTSUP;
#endif
}
int event_open(void){return redfin_touch_spi_events_begin(true);}
int event_sense(void){
#ifdef TEST_SENSING
 return redfin_touch_spi_events_sense_init();
#else
 return ENOTSUP;
#endif
}
void event_close(void){redfin_touch_spi_events_close();}
unsigned stat(unsigned n){
 const unsigned v[]={commands,cancels,aborts,wait_us,bad,frame_count,functions_writes,sense_writes,
  data_reads,write_count,registers[0xe1c/4],registers[0x614/4],redfin_touch_spi_identity_ready(),functions};
 return n<14?v[n]:0;
}
unsigned frame(unsigned n,unsigned byte){return n<frame_count && byte<12?frames[n][byte]:0;}
unsigned length(unsigned n){return n<frame_count?frame_size[n]:0;}
unsigned read_reg(unsigned reg){return reg<256?read_count[reg]:0;}
unsigned write_trace(unsigned n,unsigned field){return n<write_count && n<20000 && field<2?trace[n][field]:0;}
const char *log_text(void){return logs;}
unsigned protocol_valid(const uint8_t *p,unsigned bytes){
#ifdef TEST_SENSING
 return redfin_touch_tx_valid(p,bytes);
#else
 (void)p;(void)bytes;return 0;
#endif
}
unsigned response_delay(unsigned reg){return redfin_touch_read_delay(reg);}
'''


class TouchSensingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        dev = root / 'bsd/dev'
        dev.mkdir(parents=True)
        for name, patch in (('setup', 'touch-setup.patch'), ('spi', 'touch-spi.patch')):
            (dev / f'redfin_touch_{name}.c').write_text(added_file((HERE / patch).read_text(), f'bsd/dev/redfin_touch_{name}.c'))
        (dev / 'redfin_touch_protocol.h').write_text(added_file((HERE / 'touch.patch').read_text(), 'bsd/dev/redfin_touch_protocol.h'))
        for patch in ('touch-events.patch', 'touch-spi-diag.patch', 'touch-platform-diag.patch',
                      'touch-dfs-diag.patch', 'touch-dfs-disable.patch', 'touch-rx-irq.patch'):
            subprocess.run(['git', 'apply', '--include=bsd/dev/redfin_touch_spi.c', '--include=bsd/dev/redfin_touch_setup.c',
                            str(HERE / patch)], cwd=root, check=True)
        before = (dev / 'redfin_touch_spi.c').read_text()
        subprocess.run(['git', 'apply', str(HERE / 'touch-sensing.patch')], cwd=root, check=True)
        after = (dev / 'redfin_touch_spi.c').read_text()
        cls.libs = []
        for fixed, source in ((False, before), (True, after)):
            work = root / str(fixed)
            work.mkdir()
            for name in ('redfin_touch_protocol.h', 'redfin_touch_sensing.h'):
                (work / name).write_text((dev / name).read_text())
            (work / 'redfin_touch_events.h').write_text(added_file((HERE / 'touch-events.patch').read_text(), 'bsd/dev/redfin_touch_events.h'))
            source = re.sub(r'^#include.*\n', '', source, flags=re.M)
            source = source.replace('*(volatile const uint32_t *)(s->se + offset)', 'model_read(offset)')
            source = source.replace('*(volatile uint32_t *)(s->se + offset) = value;', 'model_write(offset,value);')
            source = source.replace('redfin_spi_rd(struct redfin_spi *s, unsigned offset)\n{',
                                    'redfin_spi_rd(struct redfin_spi *s, unsigned offset)\n{\n(void)s;')
            source = source.replace('redfin_spi_wr(struct redfin_spi *s, unsigned offset, uint32_t value)\n{',
                                    'redfin_spi_wr(struct redfin_spi *s, unsigned offset, uint32_t value)\n{\n(void)s;')
            source = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', source)
            translation = ('#define TEST_SENSING 1\n' if fixed else '') + MODEL + \
                '#include "redfin_touch_protocol.h"\n#include "redfin_touch_sensing.h"\n#include "redfin_touch_events.h"\n' + source + WRAPPER
            (work / 'model.c').write_text(translation)
            library = work / 'model.so'
            subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                            str(work / 'model.c'), '-o', str(library)], check=True)
            lib = C.CDLL(str(library))
            lib.scan.argtypes = [C.c_bool, C.c_uint]
            lib.log_text.restype = C.c_char_p
            cls.libs.append(lib)
        cls.baseline, cls.fixed = cls.libs

    def prepare(self, issue=0, failed=0, style=0, features=0x1802):
        self.fixed.reset()
        self.assertEqual(self.fixed.prime(), 0)
        self.fixed.configure(issue, failed, style, features)

    def frames(self):
        return [bytes(self.fixed.frame(n, byte) for byte in range(self.fixed.length(n))) for n in range(self.fixed.stat(5))]

    def clean(self):
        self.assertEqual(self.fixed.stat(4), 0)
        self.assertEqual(self.fixed.stat(10), 0)
        self.assertEqual(self.fixed.stat(11), 0)

    def test_native_init_exact_frames_preserve_features_verify_before_sense_on(self):
        self.prepare()
        self.assertEqual(self.fixed.scan(True, 0), 0)
        frames = self.frames()
        self.assertEqual([p[5] for p in frames], [0x55, 0xaf, 0x30, 0x30, 0x30, 0x10, 0xaf])
        self.assertEqual([len(p) for p in frames], [8, 8, 8, 12, 8, 8, 8])
        self.assertEqual(frames[3], bytes.fromhex('aa0003000030631858000000'))
        self.assertEqual(frames[5], bytes.fromhex('aa0001000010bb00'))
        self.assertEqual([self.fixed.stat(n) for n in (0, 6, 7, 12, 13)], [12, 1, 1, 1, 0x1863])
        self.assertEqual(self.fixed.stat(3), 500)
        for reg in (0x55, 0xaf, 0x30):
            self.assertEqual(self.fixed.response_delay(reg), 100)
        before = self.fixed.stat(9)
        self.assertEqual(self.fixed.scan(True, 0), errno.ENOTSUP)
        self.assertEqual(self.fixed.stat(9), before)
        self.clean()

    def test_boot_flash_and_readback_guards_stop_before_next_device_write(self):
        for issue, commands, writes, sense, error in ((1, 2, 0, 0, errno.ENOTSUP),
                (2, 4, 0, 0, errno.ENOTSUP), (3, 9, 1, 0, errno.EIO), (4, 12, 1, 1, errno.EIO)):
            with self.subTest(issue=issue):
                self.prepare(issue)
                self.assertEqual(self.fixed.scan(True, 0), error)
                self.assertEqual([self.fixed.stat(i) for i in (0, 6, 7, 12)], [commands, writes, sense, 0])
                self.assertEqual(self.fixed.scan(True, 0), errno.ENOTSUP)
                self.clean()

    def test_each_command_failure_stops_without_controller_retry_or_reset(self):
        for command in range(1, 13):
            for style in (1, 2, 5):
                with self.subTest(command=command, style=style):
                    self.prepare(failed=command, style=style)
                    self.assertNotEqual(self.fixed.scan(True, 0), 0)
                    self.assertEqual(self.fixed.stat(0), command)
                    self.assertEqual(self.fixed.stat(12), 0)
                    self.assertLessEqual(self.fixed.stat(1), 1)
                    self.assertLessEqual(self.fixed.stat(2), 1)
                    self.assertLessEqual(self.fixed.stat(3), 12500)
                    self.clean()
        for command in (2, 4, 6, 9, 12):
            for style in (3, 4, 6, 7):
                self.prepare(failed=command, style=style)
                self.assertEqual(self.fixed.scan(True, 0), errno.EIO)
                self.assertEqual(self.fixed.stat(0), command)
                self.clean()

    def test_bounded_raw_queue_probe_checks_counts_status_and_never_injects_hid(self):
        for issue, batches, expected_reads in ((0, 4, 1), (10, 4, 4), (11, 4, 4)):
            self.prepare(issue)
            self.assertEqual(self.fixed.scan(True, batches), 0)
            self.assertEqual(self.fixed.read_reg(0x60), expected_reads)
            self.assertEqual(self.fixed.read_reg(0x61), 4 if issue == 11 else 0)
            self.assertLessEqual(self.fixed.log_text().count(b'raw='), 128)
            self.clean()
        for issue in (12, 13, 14, 15):
            self.prepare(issue)
            self.assertNotEqual(self.fixed.scan(True, 4), 0)
            self.assertEqual(self.fixed.read_reg(0x60), 1)
            self.clean()

    def test_missing_identity_mask_bad_batch_or_foreign_host_never_configures_controller(self):
        self.fixed.reset()
        self.assertEqual(self.fixed.scan(True, 0), errno.ENOTSUP)
        self.assertEqual(self.fixed.stat(9), 0)
        for mask, batches in ((False, 0), (True, 5), (True, 0xffffffff)):
            self.prepare()
            self.assertEqual(self.fixed.scan(mask, batches), errno.ENOTSUP)
            self.assertEqual(self.fixed.stat(9), 0)
        self.prepare(20)
        self.assertEqual(self.fixed.scan(True, 0), errno.ENOTSUP)
        self.assertEqual(self.fixed.stat(9), 0)

    def test_event_session_reuses_init_and_stuck_failure_has_one_cancel_abort_pair(self):
        self.prepare()
        self.assertEqual(self.fixed.event_sense(), errno.ENOTSUP)
        self.assertEqual(self.fixed.event_open(), 0)
        self.assertEqual(self.fixed.event_sense(), 0)
        self.assertEqual(self.fixed.stat(6), 1)
        self.assertEqual(self.fixed.stat(7), 1)
        commands = self.fixed.stat(0)
        self.assertEqual(self.fixed.event_sense(), errno.EBUSY)
        self.assertEqual(self.fixed.stat(0), commands)
        self.clean()
        self.prepare(failed=2, style=2)
        self.assertEqual(self.fixed.event_open(), 0)
        self.assertEqual(self.fixed.event_sense(), errno.ETIMEDOUT)
        self.assertEqual([self.fixed.stat(i) for i in (1, 2)], [1, 1])
        self.fixed.event_close()
        self.assertEqual([self.fixed.stat(i) for i in (1, 2)], [1, 1])
        self.clean()

    def test_frame_validator_rejects_arbitrary_commands_sizes_or_corruption(self):
        valid = [bytes.fromhex('aa0001000010bb00'), bytes.fromhex('aa000300003061003e000000'),
                 bytes.fromhex('aa0001000230dd00')]
        for frame in valid:
            self.assertEqual(self.fixed.protocol_valid(C.c_char_p(frame), len(frame)), 1)
            for offset in range(len(frame)):
                mutated = bytearray(frame)
                mutated[offset] ^= 1
                self.assertEqual(self.fixed.protocol_valid(C.c_char_p(bytes(mutated)), len(frame)), 0)
        for reg in (0x11, 0x12, 0x13, 0x14, 0xe4, 0x57, 0xa4):
            frame = bytes([0xaa, 0, 1, 0, 0, reg, (0xab+reg)&255, 0])
            self.assertEqual(self.fixed.protocol_valid(C.c_char_p(frame), len(frame)), 0)

    def test_original_id_path_has_identical_register_write_trace(self):
        snapshots = []
        for lib in self.libs:
            lib.reset()
            self.assertEqual(lib.prime(), 0)
            snapshots.append(([lib.stat(i) for i in range(14)],
                              [(lib.write_trace(i, 0), lib.write_trace(i, 1)) for i in range(lib.stat(9))]))
        self.assertEqual(snapshots[0], snapshots[1])


if __name__ == '__main__':
    unittest.main()
