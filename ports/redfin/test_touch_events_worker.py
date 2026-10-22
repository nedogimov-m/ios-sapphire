"""Execute the actual worker with a virtual scheduler and scripted SEC queue."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_touch import added_file


class TouchEventWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host C compiler unavailable")
        base = Path(__file__).parent
        patch = (base / "touch-events.patch").read_text()
        protocol = added_file((base / "touch.patch").read_text(), "bsd/dev/redfin_touch_protocol.h")
        header = added_file(patch, "bsd/dev/redfin_touch_events.h")
        source = added_file(patch, "bsd/dev/redfin_touch_events.c")
        source = re.sub(r"^#include.*\n", "", source, flags=re.M)
        source = source.replace('*(volatile const uint32_t *)(base + offset)', 'model_read(base, offset)')
        source = source.replace('__asm__ volatile("dmb oshld" ::: "memory");', '(void)0;')
        stub = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
#include <setjmp.h>
#define ARM64_BOARD_CONFIG_SWEET 1
#define kSuccess 0
#define KERN_SUCCESS 0
#define THREAD_UNINT 0
#define THREAD_WAITING 1
#define THREAD_CONTINUE_NULL NULL
#define NSEC_PER_MSEC 1000000ull
#define NSEC_PER_SEC 1000000000ull
#define printf model_printf
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
typedef void *event_t;
typedef int thread_t;
typedef int kern_return_t;
typedef int wait_result_t;
static jmp_buf finished;
static uint64_t now,wake;
static unsigned fault,enabled,duration,maps,starts,deallocs,reads,read60,read61,begins,closes,emits,violations;
static int worker_error;
static unsigned output[40][4];
static unsigned hid_down;
static int model_printf(const char *format,...){
    if(strstr(format,"stopped error=")){va_list list;va_start(list,format);worker_error=va_arg(list,int);va_end(list);}
    return 0;
}
static uint64_t mach_absolute_time(void){return now;}
static void clock_interval_to_deadline(unsigned interval,uint64_t scale,uint64_t *out){*out=now+interval*scale;}
static int assert_wait_deadline(event_t event,int mode,uint64_t value){(void)event;(void)mode;wake=value;return THREAD_WAITING;}
static void thread_block(void *continuation){(void)continuation;now=wake;}
static thread_t current_thread(void){return 1;}
kern_return_t thread_terminate(thread_t thread){(void)thread;longjmp(finished,1);return 0;}
static int kernel_thread_start(void (*body)(void *,wait_result_t),void *argument,thread_t *out){
    starts++;if(fault==9)return 1;*out=1;
    if(!setjmp(finished))body(argument,0);
    return 0;
}
static void thread_deallocate(thread_t thread){(void)thread;deallocs++;}
static int PE_parse_boot_argn(const char *name,void *out,int bytes){
    (void)bytes;*(uint32_t *)out=!strcmp(name,"redfintouchevents") ? enabled : duration;return 1;
}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){(void)root;(void)path;*out=(void *)1;return 0;}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *n){
    (void)node;static const uint32_t size[]={1080,2340},gpio[]={8,9,35};
    if(!strcmp(name,"compatible")){*out=fault==10 ? NULL : "redfin,sec-touch";*n=sizeof("redfin,sec-touch");}
    else if(!strcmp(name,"touch-size")){*out=size;*n=fault==18 ? 7 : 8;}
    else if(!strcmp(name,"touch-gpios")){*out=gpio;*n=12;}
    else return -1;
    return 0;
}
vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t size){
    maps++;if(pa==0xf508000 && size==0x4000)return 1;
    if(pa==0x17a00000 && size==0x10000)return 2;
    violations++;return 0;
}
static uint32_t model_read(vm_offset_t base,unsigned offset){
    if(base==1 && offset==0x1000)return fault==11 ? 4 : 0;
    if(base==1 && offset==0x1004)return 0; /* level-low IRQ: bounded polling, not edge timing. */
    if(base==2 && offset==0x14c)return fault==16 || (fault==5 && read60>=3) ? 1u<<25 : 0;
    violations++;return 0;
}
bool redfin_touch_spi_identity_ready(void){return fault!=17;}
bool sweet_hid_redfin_touch_ready(void){return fault!=1 && now>=500000000ull &&
    !(fault==4 && read60>=3) && !(fault==19 && emits>=1);}
int redfin_touch_spi_events_begin(bool mask){begins++;if(!mask)violations++;return fault==12 ? EBUSY : 0;}
void redfin_touch_spi_events_close(void){closes++;}
static void contact(uint8_t *out,unsigned finger,unsigned action,unsigned remaining){
    unsigned x=500,y=action==1 ? 2300 : 1000;
    memset(out,0,8);out[0]=(uint8_t)((action<<6)|((finger+1)<<2));out[1]=(uint8_t)(x>>4);out[2]=(uint8_t)(y>>4);
    out[3]=(uint8_t)(((x&15)<<4)|(y&15));out[7]=(uint8_t)remaining;
}
int redfin_touch_spi_event_read(unsigned reg,unsigned count,uint8_t *out){
    reads++;if(!sweet_hid_redfin_touch_ready())violations++;
    memset(out,0,count);
    if(reg==0x55 && count==1){out[0]=fault==13 ? 0x10 : 0x20;return 0;}
    if(reg==0x60 && count==8){
        read60++;
        if(fault==6){contact(out,0,1,0);return 0;}
        if(read60==1){out[0]=9;out[2]=0x10;return 0;}
        if(read60==2)return 0;
        if(read60==3){contact(out,0,1,fault==14 ? 9 : fault==15 ? 1 : fault==7 ? 32 : 0);return 0;}
        if(read60==4){
            if(fault==3 || fault==14)return EIO;
            if(fault==8){out[0]=5;out[1]=1;return 0;}
            contact(out,0,2,0);return 0;
        }
        if(read60==5){contact(out,0,3,0);return 0;}
        return 0;
    }
    if(reg==0x61 && count%8==0 && count<=248){
        read61++;if(fault==15)return EIO;
        for(unsigned i=0;i<count/8;i++)contact(out+i*8,i+1,1,count/8-1-i);
        return 0;
    }
    violations++;return EINVAL;
}
void sweet_hid_touch(int finger,int down,int x,int y){
    if(down && !sweet_hid_redfin_touch_ready())violations++;
    if(!down && !(hid_down&(1u<<finger)))return; /* SweetHID drops a redundant UP. */
    if(down)hid_down|=1u<<finger;else hid_down&=~(1u<<finger);
    if(emits<40){output[emits][0]=(unsigned)finger;output[emits][1]=(unsigned)down;output[emits][2]=(unsigned)x;output[emits][3]=(unsigned)y;}
    emits++;
}
'''
        wrapper = r'''
int run(unsigned issue,unsigned flag,unsigned seconds){
    fault=issue;enabled=flag;duration=seconds;now=wake=0;worker_error=0;
    maps=starts=deallocs=reads=read60=read61=begins=closes=emits=violations=hid_down=0;
    redfin_events_attempted=false;
    return redfin_touch_events_start();
}
unsigned stat(unsigned n){const unsigned values[]={maps,starts,deallocs,reads,read60,read61,begins,closes,emits,violations,
    (unsigned)worker_error,(unsigned)(now/1000000)};return n<12 ? values[n] : 0;}
unsigned emitted_value(unsigned i,unsigned field){return i<emits && i<40 && field<4 ? output[i][field] : 0;}
'''
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        directory = Path(cls.tmp.name)
        (directory / "redfin_touch_protocol.h").write_text(protocol)
        (directory / "redfin_touch_events.h").write_text(header)
        translation = stub + '#include "redfin_touch_events.h"\n' + source + wrapper
        (directory / "worker.c").write_text(translation)
        library = directory / "worker.so"
        subprocess.run([cc, "-std=c11", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(directory / "worker.c"), "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint] * 3

    def run_worker(self, issue=0, enabled=1, seconds=1):
        result = self.lib.run(issue, enabled, seconds)
        self.assertEqual(self.lib.stat(9), 0, "bad MMIO/read, event before consumer, or invalid SPI request")
        self.assertLessEqual(self.lib.stat(11), max(seconds * 1000 + 100, 1100))
        return result

    def test_disabled_missing_identity_or_bad_lifetime_before_mapping(self):
        self.assertEqual(self.run_worker(enabled=0), errno.ENOTSUP)
        self.assertEqual(self.lib.stat(0), 0)
        self.assertEqual(self.run_worker(17), errno.ENOTSUP)
        self.assertEqual(self.lib.stat(0), 0)
        for seconds in (0, 301):
            self.assertEqual(self.run_worker(seconds=seconds), errno.EINVAL)
            self.assertEqual(self.lib.stat(0), 0)

    def test_bad_contract_or_initial_gpio_gic_ownership_never_opens_session(self):
        for issue in (10, 11, 16, 18):
            self.assertNotEqual(self.run_worker(issue), 0)
            self.assertEqual(self.lib.stat(6), 0)
            self.assertEqual(self.lib.stat(3), 0)

    def test_never_consumes_events_before_hid_callback_registration(self):
        self.assertEqual(self.run_worker(1), 0)
        self.assertEqual(self.lib.stat(10), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(3), 0)
        self.assertEqual(self.lib.stat(6), 0)
        self.assertEqual(self.lib.stat(8), 0)
        self.assertEqual(self.lib.stat(11), 1000)

    def test_press_move_release_then_expiry_closes_and_releases_reference(self):
        self.assertEqual(self.run_worker(), 0)
        self.assertEqual(self.lib.stat(10), 0)
        self.assertEqual(self.lib.stat(6), 1)
        self.assertEqual(self.lib.stat(7), 1)
        self.assertEqual(self.lib.stat(2), 1)
        self.assertEqual(self.lib.stat(8), 3)
        self.assertEqual([self.lib.emitted_value(i, 1) for i in range(3)], [1, 1, 0])

    def test_transport_consumer_or_gic_loss_releases_down_and_stops(self):
        for issue, error in ((3, errno.EIO), (19, errno.EPIPE), (5, errno.EBUSY), (8, errno.EIO)):
            self.assertEqual(self.run_worker(issue), 0)
            self.assertEqual(self.lib.stat(10), error)
            self.assertEqual(self.lib.stat(7), 1)
            self.assertEqual([self.lib.emitted_value(i, 1) for i in range(self.lib.stat(8))], [1, 0])
        self.assertEqual(self.run_worker(4), 0)  # Consumer closes during the SPI read, before DOWN.
        self.assertEqual(self.lib.stat(10), errno.EPIPE)
        self.assertEqual(self.lib.stat(8), 0)

    def test_startup_drain_bound_boot_mode_and_corruption_fail_without_downs(self):
        for issue, error in ((6, errno.EBUSY), (7, errno.EOVERFLOW), (12, errno.EBUSY),
                             (13, errno.ENOTSUP), (15, errno.EIO)):
            self.assertEqual(self.run_worker(issue), 0)
            self.assertEqual(self.lib.stat(10), error)
            self.assertEqual(self.lib.stat(8), 0)
            self.assertEqual(self.lib.stat(7), 1)
        self.assertEqual(self.run_worker(6), 0)
        self.assertEqual(self.lib.stat(4), 4)

    def test_all_ten_active_contacts_release_on_first_error(self):
        self.assertEqual(self.run_worker(14), 0)
        self.assertEqual(self.lib.stat(10), errno.EIO)
        self.assertEqual(self.lib.stat(8), 20)
        self.assertEqual([self.lib.emitted_value(i, 1) for i in range(20)], [1] * 10 + [0] * 10)

    def test_failed_thread_start_does_not_open_transport(self):
        self.assertEqual(self.run_worker(9), errno.EIO)
        self.assertEqual(self.lib.stat(6), 0)
        self.assertEqual(self.lib.stat(3), 0)


if __name__ == "__main__":
    unittest.main()
