"""Exercise the actual framebuffer transmitter and UART fanout without hardware."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'research/redfin-build/dxb/xnu/pexpert/arm/pe_serial.c'


def function(source, name):
    match = re.search(r'\b' + name + r'\([^;]*?\)\s*\{', source)
    if match is None:
        raise ValueError('missing production function: ' + name)
    start, depth = match.start(), 1
    end = match.end()
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return 'static void\n' + source[start:end] + '\n'


class QuietDisplayTests(unittest.TestCase):
    def test_actual_uart_preserves_ram_and_panic_while_quiet_fb_keeps_pixels_and_cursor(self):
        compiler = shutil.which('cc')
        if not compiler or not SOURCE.is_file():
            self.skipTest('prepared source and host compiler required')
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            copy = work / 'pexpert/arm/pe_serial.c'
            copy.parent.mkdir(parents=True)
            copy.write_text(SOURCE.read_text())
            patch = HERE / 'quiet-display.patch'
            checked = subprocess.run(['git', 'apply', '--check', str(patch)], cwd=work, capture_output=True)
            if checked.returncode:
                subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)],
                               cwd=work, check=True, capture_output=True)
            else:
                subprocess.run(['git', 'apply', str(patch)], cwd=work, check=True, capture_output=True)
            actual = copy.read_text()
            bodies = '\n'.join(function(actual, name) for name in (
                'fbcon_clear_row', 'fbcon_newline', 'fbcon_transmit_data',
                'redfin_log_transmit', 'uart_putc_options_'))
            harness = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
#define FBCON_SCALE 2
#define FBCON_FG 0xffffffffu
#define FBCON_BG 0xff000000u
int sweet_console_muted;
static bool panicking,serial_do_transmit=true,uart_hibernation=false;
static uint32_t pixels[32*64],before[32*64];
static volatile uint32_t *fbcon_base=pixels;
static uint32_t fbcon_width=32,fbcon_height=64,fbcon_stride=128;
static uint32_t fbcon_cols=2,fbcon_rows=2,fbcon_col=1,fbcon_row=1;
static unsigned char iso_font[256*16],ram[16];
static unsigned ram_size;
static bool panic_active(void){return panicking;}
static void redfin_log_putc(char c){assert(ram_size<sizeof(ram));ram[ram_size++]=(uint8_t)c;}
struct pe_serial_functions { unsigned(*transmit_ready)(void);void(*transmit_data)(uint8_t);struct pe_serial_functions *next; };
static struct pe_serial_functions *gPESF;
static unsigned ready(void){return 1;}
static bool irq_available_and_ready(struct pe_serial_functions *f){(void)f;return false;}
static void serial_wait_for_interrupt(struct pe_serial_functions *f){(void)f;assert(0);}
static void serial_poll(void){assert(0);}
ACTUAL
int main(int argc,char **argv){
 assert(argc==4);sweet_console_muted=atoi(argv[1]);panicking=atoi(argv[2]);
 unsigned reverse=(unsigned)atoi(argv[3]);
 for(unsigned i=0;i<32*64;i++)pixels[i]=0x12345678u;
 memcpy(before,pixels,sizeof(pixels));memset(iso_font,0xff,sizeof(iso_font));
 struct pe_serial_functions logging={ready,redfin_log_transmit,NULL};
 struct pe_serial_functions display={ready,fbcon_transmit_data,NULL};
 if(reverse){display.next=&logging;gPESF=&display;}else{logging.next=&display;gPESF=&logging;}
 const char data[]={'A','\r','\n','B'};
 for(unsigned i=0;i<sizeof(data);i++)uart_putc_options_(data[i],true,false);
 assert(ram_size==sizeof(data) && !memcmp(ram,data,sizeof(data)));
#if defined(ARM64_BOARD_CONFIG_SWEET)
 bool allowed=!sweet_console_muted || panicking;
#else
 bool allowed=true; /* Other boards retain the existing transmitter. */
#endif
 if(allowed){assert(memcmp(before,pixels,sizeof(pixels))!=0);}
 else{assert(!memcmp(before,pixels,sizeof(pixels)) && fbcon_col==1 && fbcon_row==1);}
 (void)fbcon_height;
 return 0;
}
'''
            source = work / 'quiet.c'
            source.write_text(harness.replace('ACTUAL', bodies))
            for sweet in (False, True):
                executable = work / ('sweet' if sweet else 'other')
                command = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined']
                if sweet:
                    command += ['-DARM64_BOARD_CONFIG_SWEET=1']
                # panic_active is only referenced by the SWEET-only production gate.
                command += ['-Wno-unused-function', str(source), '-o', str(executable)]
                subprocess.run(command, check=True)
                for muted in (0, 1):
                    for panic in (0, 1):
                        for reverse in (0, 1):
                            with self.subTest(sweet=sweet, muted=muted, panic=panic, reverse=reverse):
                                result = subprocess.run([str(executable), str(muted), str(panic), str(reverse)],
                                                        capture_output=True)
                                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


if __name__ == '__main__':
    unittest.main()
