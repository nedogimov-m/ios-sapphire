"""Compile actual Redfin gadget guards/startup/commands/worker with fake hardware."""
import ctypes as C
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from ports.redfin.test_usb_owned_route import added_file
from ports.redfin.test_touch_events import function


def patched_source(directory):
    root = Path(__file__).resolve().parents[2]
    target = directory / 'bsd/dev/sweet_usb.c'
    target.parent.mkdir(parents=True)
    target.write_text(added_file((root / 'xnu/patches/0072-sweet-usb-probe.patch').read_text(), 'bsd/dev/sweet_usb.c'))
    for pattern in ('0073-*usb*.patch', '0074-*usb*.patch', '0075-*usb*.patch',
                    '0076-*usb*.patch', '0077-*usb*.patch', '0142-*usb*.patch'):
        patch = next((root / 'xnu/patches').glob(pattern))
        subprocess.run(['git', 'apply', '--include=bsd/dev/sweet_usb.c', str(patch)], cwd=directory, check=True)
    for name in ('usb-probe.patch', 'usb-gadget.patch'):
        subprocess.run(['git', 'apply', '--include=bsd/dev/sweet_usb.c', str(root / 'ports/redfin' / name)],
                       cwd=directory, check=True)
    return target.read_text()


STUB = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <setjmp.h>
#include <stdarg.h>
#include "redfin_usb_gadget_guard.h"
#define printf fake_printf
static unsigned stop_report;
static int fake_printf(const char *format,...){
 if(strstr(format,"error=%d halted=%u")){
  va_list args;va_start(args,format);(void)va_arg(args,int);stop_report=(unsigned)va_arg(args,int);va_end(args);
 }
 return 0;
}
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define TRUE 1
#define KERN_SUCCESS 0
#define KMA_DATA 1
#define KMA_ZERO 2
#define KMA_PERMANENT 4
#define VM_KERN_MEMORY_IOKIT 1
#define PAGE_SIZE 0x4000
#define PAGE_MASK 0x3fff
#define NSEC_PER_MSEC 1000000ull
#define NSEC_PER_SEC 1000000000ull
#define kSuccess 0
#define ptoa_64(n) ((uint64_t)(n)<<14)
typedef uintptr_t vm_offset_t;
typedef uint64_t addr64_t;
typedef unsigned long ppnum_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
typedef int thread_t;
typedef int kern_return_t;
typedef int wait_result_t;
static void *kernel_map,*kernel_pmap;
static uint32_t core_regs[0x1000],gcc_regs[0x1000],qs_regs[0x1000];
static uint8_t dma_memory[0x4000] __attribute__((aligned(0x4000)));
static uint64_t now,physical;
static unsigned issue,mode,seconds,network,logflag,maps,reads,stores,cache_ops,allocs,threads,netifs,logs;
static unsigned delays,event_calls,violations,warm_calls,active_calls,quiesce_calls,core_reads,cmd_reads;
static unsigned in_worker,halted,run_seen,alloc_flags;
static unsigned last_phase;
static bool attempted;
static int token,context_token;
static jmp_buf finished;
static void (*worker_body)(void *,wait_result_t);
static struct {
 struct rf_usb_gadget_guard guard;
 vm_offset_t redfin_qs,dwc,dma;
 uint64_t dma_pa;uint32_t evt_pos;int sleep_chan,state;
 unsigned events;bool configured;void *ifp,*lock;uint64_t rx_frames,tx_frames;
} ud;
enum {EP0_SETUP};
static int authorize(const void *caller,void *context,enum redfin_usb_gadget_phase phase){
 last_phase=(unsigned)phase;
 if(caller!=&token || context!=&context_token){violations++;return EPERM;}
 if(phase==RF_USB_WARM){warm_calls++;return issue==1 ? EPERM : 0;}
 if(phase==RF_USB_ACTIVE){active_calls++;return ((issue==2 || issue==3) && stores>=3) ? EPERM : 0;}
 quiesce_calls++;return issue==3 ? EPERM : 0;
}
static uint64_t mach_absolute_time(void){return now;}
static void delay(unsigned us){delays++;now+=(uint64_t)us*1000;}
static void clock_interval_to_deadline(unsigned n,uint64_t unit,uint64_t *out){*out=now+n*unit;}
static void ud_sleep_ms(unsigned ms){now+=(uint64_t)ms*1000000;}
static int current_thread(void){return 1;}
kern_return_t thread_terminate(thread_t thread){(void)thread;longjmp(finished,1);return 0;}
static void thread_deallocate(int thread){(void)thread;}
static void ud_if_create(void){netifs++;ud.ifp=(void *)1;ud.lock=(void *)1;}
static void ud_log_thread(void *arg,int result){(void)arg;(void)result;logs++;}
static void ud_event(uint32_t event){(void)event;event_calls++;}
static int kernel_thread_start(void (*body)(void *,int),void *arg,int *out){
 (void)arg;threads++;*out=1;
 if(issue==12)return 1;
 if(body==ud_log_thread)logs++;else worker_body=body;
 return 0;
}
static int PE_parse_boot_argn(const char *name,void *out,int bytes){
 (void)bytes;unsigned *value=out;
 if(!strcmp(name,"redfinusb"))*value=mode;
 else if(!strcmp(name,"redfinusbsecs"))*value=seconds;
 else if(!strcmp(name,"redfinusbnet"))*value=network;
 else if(!strcmp(name,"redfinusblog"))*value=logflag;
 else return 0;
 return 1;
}
bool redfin_usb_platform(void){return issue!=4;}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out){
 (void)root;(void)path;*out=(void *)1;return 0;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **out,unsigned *size){
 (void)node;static uint64_t base=0x80000000,size_bytes=0x200000000;
 *out=!strcmp(name,"dram-base") ? &base : &size_bytes;*size=issue==5 ? 7 : 8;return 0;
}
vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t size){
 maps++;
 if(pa==0x04ef8800 && size==0x100)return (uintptr_t)qs_regs+0x800;
 if(size!=0x4000)violations++;
 if(issue==6 && maps==3)return 0;
 if(pa==0x10c000)return (uintptr_t)gcc_regs;
 if(pa==0xa60c000)return (uintptr_t)core_regs;
 if(pa==0xa6f8000)return (uintptr_t)qs_regs;
 violations++;return 0;
}
static int kmem_alloc_contig(void *map,vm_offset_t *out,unsigned size,unsigned mask,unsigned a,unsigned b,unsigned flags,unsigned tag){
 (void)map;(void)a;(void)b;(void)tag;allocs++;alloc_flags=flags;
 if(size!=0x4000 || mask!=0x3fff)violations++;
 if(issue==8)return 1;
 *out=(uintptr_t)dma_memory;return 0;
}
ppnum_t pmap_find_phys(void *map,addr64_t va){
 (void)map;if(issue==9 && va==(uintptr_t)dma_memory+0x3fff)return 0;
 return (ppnum_t)(physical>>14);
}
static void flush_dcache64(addr64_t pa,unsigned len,bool phys){
 cache_ops++;if(!phys || pa<physical || pa+len>physical+0x4000)violations++;
}
static uint32_t usb_rd(vm_offset_t base,unsigned offset){
 reads++;
 if(base==ud.dwc){
  core_reads++;
  if(offset<0xc000 || offset>=0x10000 || (offset&3)){violations++;return 0;}
  if(offset==0xc704 && issue==20 && ud.guard.active)return 0xffffffffu;
  if(offset==0xc704 && (issue==23 || issue==25) && last_phase==RF_USB_QUIESCE)return core_regs[0x704/4]|(1u<<(issue==23?30:29));
  if(offset==0xc704 && issue==26 && !ud.guard.active)return core_regs[0x704/4]|(1u<<29);
  if(offset==0xc70c && issue==22 && last_phase==RF_USB_QUIESCE)return 0xffffffffu;
  if(offset>=0xc800 && offset<=0xc85c && (offset&15)==12 && issue==24)return 0xffffffffu;
  if(offset>=0xc800 && offset<=0xc85c && (offset&15)==12)cmd_reads++;
  if(offset==0xc40c && in_worker){
   if(issue==14)return 0x1004;
   if(issue==15)return 3;
   if(issue==16 && event_calls==0)return 0x1000;
  }
  return core_regs[(offset-0xc000)/4];
 }
 if(base==(uintptr_t)gcc_regs && offset<0x4000)return gcc_regs[offset/4];
 if(base==(uintptr_t)qs_regs+0x800 && offset<0x100)return issue==21 ? 0xffffffffu : qs_regs[(offset+0x800)/4];
 violations++;return 0;
}
static void model_write(vm_offset_t base,unsigned offset,uint32_t value){
 stores++;
 if(base==ud.dwc){
  if(ud.guard.redfin && (offset==0xc400 || offset==0xc404) && cache_ops==0)violations++;
  if(ud.guard.redfin && offset>=0xc800 && offset<=0xc85c && (offset&15)==12 &&
     (value&15)==6 && cache_ops<3)violations++;
  uint32_t *reg=&core_regs[(offset-0xc000)/4];*reg=offset==0xc40c ? 0 : value;
  if(offset==0xc704){
   if((value&(1u<<30)) && issue!=10)*reg&=~(1u<<30);
   if(value&(1u<<31)){run_seen=1;if(issue!=11){halted=0;core_regs[0x70c/4]=0;}}
   else if(run_seen && issue!=13){halted=1;core_regs[0x70c/4]=1u<<22;}
  }
  if(offset>=0xc800 && offset<=0xc85c && (offset&15)==12 && issue!=17){
   *reg&=~(1u<<10);if(issue==18)*reg|=1u<<12;
  }
  return;
 }
 if(base==(uintptr_t)qs_regs+0x800 && offset==0x10){
  uint32_t old=qs_regs[0x810/4];
  if(value!=(old|(1u<<20)))violations++;
  qs_regs[0x810/4]=value;return;
 }
 violations++;
}
'''

HARNESS = r'''
unsigned run(unsigned fault,unsigned enable,unsigned lifetime,unsigned net,unsigned log){
 issue=fault;mode=enable;seconds=lifetime;network=net;logflag=log;now=0;physical=fault==19?0x1000000000ull:0xb3000000;
 maps=reads=stores=cache_ops=allocs=threads=netifs=logs=delays=event_calls=violations=0;
 warm_calls=active_calls=quiesce_calls=core_reads=cmd_reads=in_worker=run_seen=alloc_flags=0;
 halted=1;stop_report=99;last_phase=RF_USB_WARM;attempted=false;worker_body=NULL;memset(&ud,0,sizeof(ud));
 memset(core_regs,0,sizeof(core_regs));memset(gcc_regs,0,sizeof(gcc_regs));memset(qs_regs,0,sizeof(qs_regs));
 memset(dma_memory,0,sizeof(dma_memory));
 core_regs[0x120/4]=0x5533330a;core_regs[0x140/4]=64u<<24;core_regs[0x110/4]=2u<<12;
 core_regs[0x70c/4]=1u<<22;
 gcc_regs[0x3004/4]=1u<<31;
 const unsigned clocks[]={0x3010,0x307c,0x3080,0x3018,0x301c};
 for(unsigned i=0;i<5;i++)gcc_regs[clocks[i]/4]=fault==7 ? 0 : 1;
 qs_regs[0x810/4]=0xa0010042;qs_regs[0x830/4]=0x12345678;
 struct redfin_usb_gadget_policy policy={authorize,&context_token};
 int result=redfin_usb_gadget_start(&token,&policy);
 if(!result && worker_body){
  in_worker=1;if(!setjmp(finished))worker_body(NULL,0);
  result=ud.guard.error;
 }
 return (unsigned)result;
}
unsigned stat(unsigned n){
 const unsigned values[]={maps,reads,stores,cache_ops,allocs,threads,netifs,logs,event_calls,violations,
  warm_calls,active_calls,quiesce_calls,halted,(unsigned)(now/1000000),alloc_flags,core_reads,cmd_reads,
  qs_regs[0x810/4],qs_regs[0x830/4],stop_report};return n<21?values[n]:0;
}
unsigned run_legacy(void){
 (void)run(4,2,1,0,0);ud.guard.redfin=false;ud.dwc=(uintptr_t)core_regs-0xc000;
 sweet_usb_gadget_start(ud.dwc);return 0;
}
unsigned check_event(unsigned raw,unsigned position){unsigned count=0;return rf_usb_gadget_events(raw,position,&count)?count+1:0;}
unsigned check_dma(uint64_t va,uint64_t pa,uint64_t size,uint64_t pages,uint64_t ram,uint64_t bytes){return rf_usb_gadget_dma(va,pa,size,pages,ram,bytes);}
unsigned check_trb(unsigned ep,unsigned trb,unsigned buf,unsigned len){return rf_usb_gadget_trb(ep,trb,buf,len);}
unsigned check_write(unsigned offset,unsigned value,uint64_t pa){return rf_usb_gadget_write(offset,value,pa);}
'''


class USBGadgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = patched_source(directory)
        patch = Path(__file__).with_name('usb-gadget.patch').read_text()
        for name in ('redfin_usb_gadget.h', 'redfin_usb_gadget_guard.h'):
            (directory / name).write_text(added_file(patch, 'bsd/dev/' + name))
        signatures = ('static bool\nud_redfin_proof(', 'static inline void\ndwc_wr(',
                      'static inline uint32_t\ndwc_rd(', 'static void\nud_sync(',
                      'static int\nud_epcmd(', 'static void\nud_start_trb(',
                      'static void\nud_start(', 'static void\nud_start_setup(',
                      'static bool\nud_redfin_stop(', 'static void\nud_thread(',
                      'static void\nsweet_usb_gadget_start(', 'int\nredfin_usb_gadget_start(')
        actual = '\n'.join(function(source, signature) for signature in signatures)
        actual = re.sub(r'__asm__ volatile\s*\([^;]*;', '(void)0;', actual)
        actual = actual.replace('*(volatile uint32_t *)(ud.dwc + off) = v;', 'model_write(ud.dwc,off,v);')
        actual = actual.replace('*(volatile uint32_t *)(ud.dwc+DCTL)=control&~DCTL_RUN_STOP;', 'model_write(ud.dwc,DCTL,control&~DCTL_RUN_STOP);')
        actual = actual.replace('*(volatile uint32_t *)(qs+QSCRATCH_HS_PHY_CTRL)=hs|UTMI_OTG_VBUS_VALID;', 'model_write(qs,QSCRATCH_HS_PHY_CTRL,hs|UTMI_OTG_VBUS_VALID);')
        actual = actual.replace('static bool attempted;', '')
        macros = '\n'.join(line for line in source.splitlines() if line.startswith(('#define', 'extern kern_return_t thread_terminate('))) + '\n'
        (directory / 'model.c').write_text(STUB + macros + actual + HARNESS)
        library = directory / 'model.so'
        subprocess.run([cc, '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(directory / 'model.c'), '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_uint] * 5
        cls.lib.stat.restype = C.c_uint
        cls.lib.check_dma.argtypes = [C.c_uint64] * 6
        cls.lib.check_write.argtypes = [C.c_uint, C.c_uint, C.c_uint64]

    def run_model(self, fault=0, mode=3, seconds=1, network=0, log=0):
        result = self.lib.run(fault, mode, seconds, network, log)
        self.assertEqual(self.lib.stat(9), 0, 'Unexpected MMIO, cache range, mapping, or identity')
        self.assertLessEqual(self.lib.stat(14), 1600)
        return result

    def test_warm_callback_platform_and_boot_args_gate_all_mmio(self):
        import errno
        for fault, mode, seconds in ((1, 3, 1), (4, 3, 1), (0, 2, 1), (0, 3, 0), (0, 3, 121), (5, 3, 1)):
            self.assertNotEqual(self.run_model(fault, mode, seconds), 0)
            self.assertEqual((self.lib.stat(0), self.lib.stat(1), self.lib.stat(2)), (0, 0, 0))
        self.assertEqual(self.run_model(6), errno.ENOMEM)
        self.assertEqual(self.lib.stat(2), 0)
        self.assertNotEqual(self.run_model(7), 0)
        self.assertEqual((self.lib.stat(2), self.lib.stat(16)), (0, 0))

    def test_default_enumeration_is_finite_halts_and_has_no_network_or_log(self):
        import errno
        self.assertEqual(self.run_model(), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(0), 3)
        self.assertGreater(self.lib.stat(2), 0)
        self.assertGreater(self.lib.stat(3), 0)
        self.assertEqual((self.lib.stat(6), self.lib.stat(7)), (0, 0))
        self.assertEqual(self.lib.stat(13), 1)
        self.assertEqual(self.lib.stat(18), 0xa0110042)
        self.assertEqual(self.lib.stat(19), 0x12345678)
        self.assertEqual(self.lib.stat(15), 7)

    def test_sapphire_legacy_address_override_and_log_defaults_are_preserved(self):
        self.assertEqual(self.lib.run_legacy(), 0)
        self.assertEqual(self.lib.stat(9), 0)
        self.assertEqual((self.lib.stat(0), self.lib.stat(6), self.lib.stat(7)), (1, 1, 1))
        self.assertEqual(self.lib.stat(18), 0xb0110042)
        self.assertEqual(self.lib.stat(19), 0x13345678)
        self.assertEqual((self.lib.stat(10), self.lib.stat(11), self.lib.stat(12)), (0, 0, 0))

    def test_redfin_logging_requires_separate_network_opt_in(self):
        import errno
        self.assertEqual(self.run_model(log=1), errno.ETIMEDOUT)
        self.assertEqual((self.lib.stat(6), self.lib.stat(7)), (0, 0))
        self.assertEqual(self.run_model(network=1), errno.ETIMEDOUT)
        self.assertEqual((self.lib.stat(6), self.lib.stat(7)), (1, 0))

    def test_dma_allocation_contiguity_and_physical_bounds_fail_before_core_writes(self):
        for fault in (8, 9, 19):
            self.assertNotEqual(self.run_model(fault), 0)
            # Only the controller-only QUIESCE write is allowed after a failed allocation.
            self.assertLessEqual(self.lib.stat(2), 1)
            self.assertEqual(self.lib.stat(3), 0)
        good = (0x10000, 0xb3000000, 0x4000, 0x4000, 0x80000000, 0x200000000)
        self.assertTrue(self.lib.check_dma(*good))
        for index, value in ((0, 0x10001), (1, 0xb3001000), (1, 0x1000000000),
                             (2, 0x8000), (3, 0x1000), (4, 0xb4000000), (5, 1)):
            args = list(good)
            args[index] = value
            self.assertFalse(self.lib.check_dma(*args))

    def test_command_status_timeout_reset_run_and_thread_failures_stop(self):
        for fault in (10, 11, 12, 17, 18):
            self.assertNotEqual(self.run_model(fault), 0)
            self.assertEqual(self.lib.stat(13), 1)
        self.assertNotEqual(self.run_model(13), 0)
        self.assertEqual(self.lib.stat(13), 0)
        self.assertGreaterEqual(self.lib.stat(14), 1500)

    def test_active_proof_loss_stops_commands_and_attempts_authorized_halt(self):
        import errno
        for fault in (2, 3):
            self.assertEqual(self.run_model(fault), errno.EPERM)
            self.assertLessEqual(self.lib.stat(2), 4)
            self.assertEqual(self.lib.stat(5), 0)
            self.assertGreater(self.lib.stat(12), 0)

    def test_all_ones_rmw_and_halt_reads_never_become_writes_or_success(self):
        import errno
        self.assertEqual(self.run_model(20), errno.EIO)
        self.assertEqual(self.lib.stat(2), 0)
        self.assertEqual(self.lib.stat(20), 0)
        self.assertEqual(self.run_model(21), errno.EIO)
        self.assertEqual(self.lib.stat(18), 0xa0010042)
        self.assertEqual(self.lib.stat(20), 1)
        self.assertEqual(self.run_model(24), errno.EIO)
        self.assertEqual(self.lib.stat(2), 12)  # First command group, then halt only.
        self.assertEqual(self.run_model(26), errno.EBUSY)
        self.assertEqual(self.lib.stat(2), 0)
        for fault in (22, 23, 25):
            self.assertEqual(self.run_model(fault), errno.ETIMEDOUT)
            self.assertEqual(self.lib.stat(20), 0)

    def test_event_count_is_bounded_aligned_and_never_reads_oversized_queue(self):
        import errno
        for fault in (14, 15):
            self.assertEqual(self.run_model(fault), errno.EOVERFLOW)
            self.assertEqual(self.lib.stat(8), 0)
            self.assertEqual(self.lib.stat(13), 1)
        self.assertEqual(self.run_model(16), errno.ETIMEDOUT)
        self.assertEqual(self.lib.stat(8), 1024)
        for raw, pos in ((0x1004, 0), (3, 0), (4, 4096), (4, 2)):
            self.assertEqual(self.lib.check_event(raw, pos), 0)
        self.assertEqual(self.lib.check_event(4096, 4092), 4097)

    def test_descriptor_and_endpoint_dma_regions_cannot_escape_slab(self):
        self.assertTrue(self.lib.check_trb(0, 0x1000, 0x1040, 8))
        self.assertTrue(self.lib.check_trb(1, 0x1010, 0x1100, 512))
        self.assertTrue(self.lib.check_trb(2, 0x1020, 0x2000, 2048))
        for args in ((4, 0x1040, 0x2000, 1), (0, 0x1001, 0x1040, 8),
                     (1, 0x1010, 0x1100, 513), (3, 0x1030, 0x3fff, 2)):
            self.assertFalse(self.lib.check_trb(*args))
        self.assertTrue(self.lib.check_write(0xc400, 0xb3000000, 0xb3000000))
        for offset, value in ((0xc110, 0), (0xc200, 0), (0xc408, 4096), (0xc40c, 65532), (0xc840, 0)):
            self.assertFalse(self.lib.check_write(offset, value, 0xb3000000))


if __name__ == '__main__':
    unittest.main()
