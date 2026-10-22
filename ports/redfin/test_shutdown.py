"""Compile the actual shutdown patch helpers with a host scheduler/MMIO model."""
import ctypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


class Report(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in
                ('starts', 'deallocs', 'blocks', 'reboots', 'howto', 'terminated', 'violation', 'irq_restored')]
    _fields_ += [(name, ctypes.c_uint64) for name in ('now', 'last', 'deadline')]


class ShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        base = Path(cls.temporary.name)
        patch = Path(__file__).with_name('shutdown.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        watchdog = added.split('/* REDFIN_SHUTDOWN_WATCHDOG_TEST_BEGIN', 1)[1]
        watchdog = watchdog.split('*/', 1)[1].split('/* REDFIN_SHUTDOWN_WATCHDOG_TEST_END */', 1)[0]
        worker = added.split('/* REDFIN_SHUTDOWN_THREAD_TEST_BEGIN', 1)[1]
        worker = worker.split('*/', 1)[1].split('/* REDFIN_SHUTDOWN_THREAD_TEST_END */', 1)[0]
        latch = added.split('/* REDFIN_SHUTDOWN_RETURN_TEST_BEGIN', 1)[1]
        latch = latch.split('*/', 1)[1].split('/* REDFIN_SHUTDOWN_RETURN_TEST_END */', 1)[0]
        watchdog = re.sub(r'__asm__ volatile\("dsb sy" ::: "memory"\);', '(void)0;', watchdog)
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define NSEC_PER_SEC 1000ULL
#define PROC_NULL NULL
#define NULLVP NULL
#define KERN_SUCCESS 0
#define THREAD_UNINT 0
#define THREAD_WAITING 1
#define THREAD_CONTINUE_NULL NULL
typedef int wait_result_t;
typedef int kern_return_t;
typedef uintptr_t thread_t;
typedef void *event_t;
typedef void (*continuation_t)(void *,wait_result_t);
struct report { int starts,deallocs,blocks,reboots,howto,terminated,violation,irq_restored;
    uint64_t now,last,deadline; };
static struct report report;
static unsigned configured_seconds;
static int mode,thread_context;
static void *initproc,*rootvnode;
static uint64_t now,pending,daif;
static jmp_buf termination;
static continuation_t continuation;
static uint32_t reset_word;
static volatile uint32_t *redfin_watchdog_reset;
static uint64_t redfin_watchdog_deadline,redfin_watchdog_last,redfin_watchdog_frequency;
static uint64_t read_register(const char *name) { return !strcmp(name,"DAIF") ? daif : now; }
static void write_register(const char *name,uint64_t value) {
    if (strcmp(name,"DAIF")) report.violation++; else daif=value;
}
#define __builtin_arm_rsr64(name) read_register(name)
#define __builtin_arm_wsr64(name,value) write_register(name,value)
static uint64_t mach_absolute_time(void) { return now; }
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *value) { *value=n; }
static int PE_parse_boot_argn(const char *name,void *value,int size) {
    (void)size;
    if (!strcmp(name,"redfinshutdown")) {
        *(uint32_t *)value=configured_seconds; return mode!=1;
    }
    if (!strcmp(name,"cpus")) *(uint32_t *)value=mode==2 ? 2 : 1;
    else if (!strcmp(name,"redfinreturn")) *(uint32_t *)value=mode==3 ? 0 : 1;
    else return 0;
    return 1;
}
static int kernel_thread_start(continuation_t function,void *arg,thread_t *thread) {
    (void)arg; report.starts++; continuation=function; *thread=1;
    return mode==6 ? 9 : KERN_SUCCESS;
}
static void thread_deallocate(thread_t thread) { (void)thread; report.deallocs++; }
static int assert_wait_deadline(event_t event,int type,uint64_t deadline) {
    (void)event; (void)type; pending=deadline; return THREAD_WAITING;
}
static void thread_block(void *function) {
    (void)function; report.blocks++;
    if (!thread_context || daif!=0x40 || pending<=now) report.violation++;
    now=pending;
}
static int reboot_kernel(int howto,char *message) {
    report.reboots++; report.howto=howto;
    if (!thread_context || daif!=0x40 || message) report.violation++;
    return 16;
}
static thread_t current_thread(void) { return 1; }
static kern_return_t thread_terminate(thread_t thread) {
    if (thread!=current_thread()) report.violation++;
    report.terminated++; longjmp(termination,1);
}
'''
        suffix = r'''
const struct report *test_run(unsigned seconds,int test_mode) {
    memset(&report,0,sizeof(report)); mode=test_mode; configured_seconds=seconds;
    now=100000; pending=0; daif=0x40; thread_context=0; continuation=NULL;
    initproc=mode==5 ? NULL : (void *)1; rootvnode=mode==4 ? NULL : (void *)1;
    redfin_watchdog_reset=mode==7 ? NULL : &reset_word;
    redfin_watchdog_frequency=1000; redfin_watchdog_deadline=160000;
    redfin_watchdog_last=100000; reset_word=0;
    redfin_spmi_return_confirmed=mode!=9;
    if (mode==8) now=UINT64_MAX-100;
    redfin_shutdown_start();
    if (report.reboots) report.violation++;
    if (report.starts && mode!=6) {
        thread_context=1;
        if (!setjmp(termination)) continuation(NULL,0);
    }
    report.now=now; report.last=redfin_watchdog_last; report.deadline=redfin_watchdog_deadline;
    report.irq_restored=daif==0x40;
    return &report;
}
int test_watchdog(unsigned seconds,int variant) {
    now=100000; daif=0x40; reset_word=0; redfin_watchdog_reset=&reset_word;
    redfin_watchdog_frequency=1000; redfin_watchdog_deadline=0; redfin_watchdog_last=0;
    if (variant==1) redfin_watchdog_reset=NULL;
    if (variant==2) redfin_watchdog_frequency=0;
    if (variant==3) redfin_watchdog_frequency=1000000000ULL;
    if (variant==4) now=UINT64_MAX-1;
    int result=redfin_shutdown_watchdog_start(seconds);
    if (!result) return 0;
    if (redfin_watchdog_deadline!=100000+1000ULL*seconds || reset_word!=1 || daif!=0x40) return -1;
    reset_word=0; now+=999; redfin_shutdown_watchdog_tick(0);
    if (reset_word) return -2;
    now++; redfin_shutdown_watchdog_tick(0);
    if (reset_word!=1) return -3;
    reset_word=0; now=redfin_watchdog_deadline; redfin_shutdown_watchdog_tick(0);
    if (reset_word) return -4;
    redfin_shutdown_watchdog_tick(1);
    if (redfin_watchdog_deadline || reset_word) return -5;
    now+=100000; redfin_shutdown_watchdog_tick(0);
    return reset_word ? -6 : 1;
}
'''
        source = base/'shutdown.c'
        source.write_text(prefix + latch + watchdog + worker + suffix)
        library = base/'shutdown.so'
        result = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                                 str(source), '-o', str(library)], capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode(errors='replace'))
        cls.library = ctypes.CDLL(str(library))
        cls.library.test_run.argtypes = [ctypes.c_uint, ctypes.c_int]
        cls.library.test_run.restype = ctypes.POINTER(Report)
        cls.library.test_watchdog.argtypes = [ctypes.c_uint, ctypes.c_int]
        cls.library.test_watchdog.restype = ctypes.c_int

    def test_valid_worker_blocks_and_reboots_with_sync_in_thread_context(self):
        result = self.library.test_run(10, 0).contents
        self.assertEqual((result.starts, result.deallocs, result.blocks, result.reboots), (1, 1, 10, 1))
        self.assertEqual((result.howto, result.terminated, result.violation, result.irq_restored), (0, 1, 0, 1))
        self.assertEqual(result.now, 110000)
        self.assertEqual(result.deadline, 0)
        self.assertEqual(result.last, 109000)

    def test_absent_invalid_or_unready_policy_creates_no_worker(self):
        for seconds, mode in ((10,1), (0,0), (4,0), (301,0), (0xffffffff,0),
                              (10,2), (10,3), (10,4), (10,5)):
            with self.subTest(seconds=seconds, mode=mode):
                result = self.library.test_run(seconds, mode).contents
                self.assertEqual((result.starts, result.reboots, result.blocks), (0, 0, 0))
                self.assertEqual(result.deadline, 160000)

    def test_failed_worker_or_watchdog_proof_cannot_reboot_or_extend_feed(self):
        for mode in (6,7,8,9):
            with self.subTest(mode=mode):
                result = self.library.test_run(10, mode).contents
                self.assertEqual((result.reboots, result.blocks), (0, 0))
                self.assertEqual(result.deadline, 160000)
                self.assertEqual(result.deallocs, 0 if mode==6 else 1)

    def test_watchdog_cap_frequency_overflow_and_no_feed_at_or_after_deadline(self):
        for seconds in (5,10,300):
            self.assertEqual(self.library.test_watchdog(seconds,0), 1)
        for seconds, variant in ((0,0),(4,0),(301,0),(10,1),(10,2),(10,3),(10,4)):
            with self.subTest(seconds=seconds, variant=variant):
                self.assertEqual(self.library.test_watchdog(seconds,variant), 0)


if __name__ == '__main__':
    unittest.main()
