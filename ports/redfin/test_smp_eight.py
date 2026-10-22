"""Execute the eight-core extension and retain the working two-core contract."""
import ctypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_smp as base

HERE = Path(__file__).parent.resolve()
VALID = base.VALID.replace('cpus=2', 'cpus=8')


def extended_source():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'osfmk/arm64/redfin_smp.c'
        source.parent.mkdir(parents=True)
        source.write_text(base.added_file('osfmk/arm64/redfin_smp.c'))
        subprocess.run(['git', 'apply', '--include=osfmk/arm64/redfin_smp.c',
            '--include=osfmk/arm64/redfin_smp_eight.h', str(HERE / 'smp-eight.patch')],
            cwd=root, check=True, capture_output=True)
        header = source.with_name('redfin_smp_eight.h').read_text()
        assert header == (HERE / 'smp-eight.h').read_text()
        return source.read_text().replace('#include "redfin_smp_eight.h"', header)


def body():
    return re.sub(r'^#include .*\n', '', extended_source(), flags=re.M)


class EightExtensionTwoCoreRegression(base.SMPTests):
    @classmethod
    def setUpClass(cls):
        old_body, old_suffix = base.body, base.HOST_SUFFIX
        try:
            base.body = body
            base.HOST_SUFFIX = old_suffix.replace('test_cpu=0;test_thread=NULL;',
                'rf_smp_cpu_count=2;rf_eight_turn=0;memset(rf_eight_started,0,sizeof(rf_eight_started));'
                'memset(rf_eight_replies,0,sizeof(rf_eight_replies));test_cpu=0;test_thread=NULL;')
            base.SMPTests.setUpClass.__func__(cls)
        finally:
            base.body, base.HOST_SUFFIX = old_body, old_suffix

    def test_reject_writers_and_malformed_values(self):
        self.assertEqual(self.lib.test_flags(VALID.encode()), 1)
        for token in ('redfincpu=0', 'redfinfuture=0', 'redfinufs=0', 'rootrw=0', 'unknown=0'):
            self.assertEqual(self.lib.test_flags((VALID + ' ' + token).encode()), 0)
        for value in ('0', '1', '02', '4', '7', '9', '16', '0x8', '4294967304'):
            self.assertEqual(self.lib.test_flags(VALID.replace('cpus=8', 'cpus=' + value).encode()), 0)
        for before, after in (('rd=md0', 'rd=ufsroot0'), ('redfinreturn=0', 'redfinreturn=1'),
                              ('0123456789abcdef', '0000000000000000'), ('gpu=0', 'gpu=1')):
            self.assertEqual(self.lib.test_flags(VALID.replace(before, after).encode()), 0)


HOST = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <sched.h>
struct test_thread { pthread_t native;int active;void (*entry)(void *,int);void *arg; };
static _Thread_local unsigned test_cpu;
static _Thread_local thread_t test_thread;
static ml_topology_cpu_t cpus[8];
static ml_topology_cluster_t cluster;
static ml_topology_info_t topology;
static thread_t workers[8];
static char args[608];
static unsigned scenario,pending[8],on[8],queries,return_checks,verdicts,log_checks,feeds;
const char *PE_boot_args(void){return args;}
const ml_topology_info_t *ml_get_topology_info(void){return &topology;}
void panic(const char *s,...) { fprintf(stderr,"unexpected panic %s\n",s);abort(); }
processor_t cpu_to_processor(int cpu){assert(cpu>=0&&cpu<8);return cpu;}
processor_t thread_bind(processor_t cpu){test_cpu=scenario==8&&cpu==3?4:(unsigned)cpu;return 0;}
void thread_block(void *continuation){(void)continuation;}
uint64_t mach_absolute_time(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
void nanoseconds_to_deadline(uint64_t n,uint64_t *d){*d=mach_absolute_time()+n;}
static void *worker_main(void *p){test_thread=p;test_thread->entry(test_thread->arg,0);__atomic_store_n(&test_thread->active,0,__ATOMIC_RELEASE);return NULL;}
int kernel_thread_start(void (*entry)(void *,int),void *arg,thread_t *out){
 unsigned cpu=(unsigned)(uintptr_t)arg;assert(cpu>=1&&cpu<8&&!workers[cpu]);
 if(scenario==9&&cpu==4)return 5;
 thread_t t=calloc(1,sizeof(*t));assert(t);t->entry=entry;t->arg=arg;t->active=1;
 workers[cpu]=t;*out=t;return pthread_create(&t->native,NULL,worker_main,t);
}
void thread_deallocate(thread_t t){assert(t);}
int thread_is_active(thread_t t){return __atomic_load_n(&t->active,__ATOMIC_ACQUIRE);}
thread_t current_thread(void){return test_thread;}
void thread_terminate(thread_t t){assert(t==test_thread);__atomic_store_n(&t->active,0,__ATOMIC_RELEASE);pthread_exit(NULL);}
void redfin_shutdown_watchdog_tick(unsigned final){assert(test_cpu==0&&!final);feeds++;}
static uint64_t rf_smp_reg(unsigned);
static int32_t rf_smp_psci(uint32_t,uint64_t,uint64_t,uint64_t);
static void rf_smp_send(unsigned);
static bool rf_smp_entry_ok(vm_offset_t);
static void rf_smp_barrier(void);
static void rf_smp_pause(void);
static void rf_smp_round_delay(void);
'''

HARDWARE = r'''
static uint64_t rf_smp_reg(unsigned n){
 switch(n){
 case RF_SMP_MPIDR:return 0x81000000ULL|((uint64_t)test_cpu<<8);
 case RF_SMP_EL:return 4;
 case RF_SMP_MIDR:return test_cpu<6?0x51df805e:0x51ff804e;
 case RF_SMP_MMFR0:return 0x101122;
 case RF_SMP_CTR:return test_cpu<6?0x84448004:0x9444c004;
 default:return 0x30501805;
 }
}
static int32_t rf_smp_psci(uint32_t fn,uint64_t a,uint64_t b,uint64_t c){
 assert(test_cpu==0);queries++;
 if(fn==0x84000000u){assert(!a&&!b&&!c);return 0x10001;}
 if(fn==0x8400000au){assert(!b&&!c&&(a==RF_SMP_ON||a==RF_SMP_AFFINITY));return 0;}
 unsigned cpu=(unsigned)(a>>8);assert(cpu>=1&&cpu<8&&a==((uint64_t)cpu<<8));
 if(fn==RF_SMP_AFFINITY){assert(!b&&!c);return scenario==1&&cpu==5?0:1;}
 assert(fn==RF_SMP_ON&&b==0x180100000ULL&&c==cpu);assert(++on[cpu]==1);return 0;
}
int redfin_smp_return_ready(void){assert(test_cpu==0);return_checks++;return scenario==2&&return_checks==3?0:1;}
int redfin_log_smp_quiescent(void){log_checks++;return scenario==7&&log_checks==2?0:1;}
static bool rf_smp_entry_ok(vm_offset_t entry){return entry==0x180100000ULL;}
static void rf_smp_barrier(void){__atomic_thread_fence(__ATOMIC_SEQ_CST);}
static void rf_smp_send(unsigned target){
 assert(target<8);
 uint32_t phase=__atomic_load_n(&rf_smp_phase,__ATOMIC_ACQUIRE);
 uint64_t req=__atomic_load_n(&rf_smp_request[target],__ATOMIC_ACQUIRE);
 if((scenario==3&&target==4&&req>1&&phase==RF_SMP_ACTIVE)||
    (scenario==4&&test_cpu==5&&target==0&&req>1&&phase==RF_SMP_ACTIVE)||
    (scenario==6&&target==7&&phase==RF_SMP_DRAIN))return;
 __atomic_store_n(&pending[target],1,__ATOMIC_RELEASE);
}
static void pump(unsigned cpu){
 unsigned previous=test_cpu;test_cpu=cpu;
 if(__atomic_exchange_n(&pending[cpu],0,__ATOMIC_ACQ_REL))redfin_smp_irq(1);
 if(!(scenario==5&&cpu==6))redfin_smp_irq(0);
 test_cpu=previous;
}
static void rf_smp_pause(void){
 unsigned cpu=test_cpu;assert(cpu<8);pump(cpu);
 if(!cpu)for(unsigned other=1;other<8;other++)
  if(!workers[other]||!thread_is_active(workers[other]))pump(other);
 struct timespec t={0,10000};nanosleep(&t,NULL);sched_yield();
}
static void rf_smp_round_delay(void){
 for(unsigned i=0;i<10;i++)rf_smp_pause();
}
void delay(unsigned microseconds){(void)microseconds;}
void kprintf(const char *fmt,...){assert(test_cpu==0&&rf_smp_phase==RF_SMP_DONE&&strstr(fmt,"REDFIN SMP8:")&&strstr(fmt,"tlb=untested"));verdicts++;}
'''

SUFFIX = r'''
static void reset(unsigned kind){
 test_cpu=0;test_thread=NULL;scenario=kind;strcpy(args,"VALID_ARGS");
 memset(cpus,0,sizeof(cpus));memset(&cluster,0,sizeof(cluster));memset(&topology,0,sizeof(topology));
 for(unsigned i=0;i<8;i++){cpus[i].cpu_id=i;cpus[i].phys_id=i<<8;cpus[i].cluster_core_id=i;cpus[i].l2_cache_id=i;assert(!workers[i]);}
 cluster.num_cpus=8;cluster.cpu_mask=255;
 topology.version=1;topology.num_cpus=8;topology.max_cpu_id=7;topology.num_clusters=1;
 topology.cpus=topology.boot_cpu=cpus;topology.clusters=topology.boot_cluster=&cluster;
 rf_smp_prepared=rf_smp_started=rf_smp_selected=rf_smp_phase=rf_smp_fault=0;rf_smp_frozen_bytes=0;rf_smp_cpu_count=2;
 memset(rf_smp_request,0,sizeof(rf_smp_request));memset(rf_smp_ack,0,sizeof(rf_smp_ack));
 memset(rf_smp_timers,0,sizeof(rf_smp_timers));memset(rf_smp_progress,0,sizeof(rf_smp_progress));
 memset(rf_smp_ready,0,sizeof(rf_smp_ready));memset(rf_smp_finished,0,sizeof(rf_smp_finished));memset(rf_smp_drained,0,sizeof(rf_smp_drained));
 memset(rf_eight_started,0,sizeof(rf_eight_started));memset(rf_eight_replies,0,sizeof(rf_eight_replies));rf_eight_turn=0;
 memset(pending,0,sizeof(pending));memset(on,0,sizeof(on));queries=return_checks=verdicts=log_checks=feeds=0;
}
int run(unsigned kind){
 reset(kind);redfin_smp_prepare();if(kind==10)cpus[7].phys_id=0x600;
 int error=0;
 for(unsigned cpu=1;cpu<8;cpu++){error=redfin_smp_start(cpu,0x180100000ULL);if(error)break;}
 if(!error)error=redfin_smp_prove();
 __atomic_store_n(&rf_smp_fault,1,__ATOMIC_RELEASE);
 for(unsigned cpu=1;cpu<8;cpu++)if(workers[cpu]){pthread_join(workers[cpu]->native,NULL);free(workers[cpu]);workers[cpu]=NULL;}
 return error;
}
uint64_t fact(unsigned kind,unsigned cpu){
 assert(cpu<8);switch(kind){case 0:return rf_smp_progress[cpu];case 1:return rf_smp_timers[cpu];
 case 2:return rf_smp_ready[cpu];case 3:return rf_smp_drained[cpu];case 4:return rf_eight_replies[cpu];
 case 5:return on[cpu];case 6:return verdicts;case 7:return feeds;case 8:return log_checks;default:return rf_smp_ack[cpu];}
}
int retry(unsigned cpu){return redfin_smp_start(cpu,0x180100000ULL);}
'''.replace('VALID_ARGS', VALID)


class EightCoreProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        directory = Path(cls.temp.name)
        source = body()
        start = source.index('/* REDFIN_SMP_HW_BEGIN */')
        end = source.index('/* REDFIN_SMP_HW_END */') + len('/* REDFIN_SMP_HW_END */')
        source = source[:start] + source[end:]
        path = directory / 'eight.c'
        path.write_text(base.TYPES + HOST + source + HARDWARE + SUFFIX)
        library = directory / 'eight.so'
        result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-shared', '-fPIC', '-pthread', str(path), '-o', str(library)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.run.argtypes = [ctypes.c_uint]
        cls.lib.fact.argtypes = [ctypes.c_uint, ctypes.c_uint]
        cls.lib.fact.restype = ctypes.c_uint64
        cls.lib.retry.argtypes = [ctypes.c_uint]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_eight_cpus_have_real_self_star_timer_and_thread_progress(self):
        self.assertEqual(self.lib.run(0), 0)
        for cpu in range(8):
            self.assertEqual(self.lib.fact(0, cpu), 224 if cpu == 0 else 32)
            self.assertGreaterEqual(self.lib.fact(1, cpu), 2)
            self.assertEqual(self.lib.fact(2, cpu), 1)
            self.assertEqual(self.lib.fact(3, cpu), 1)
            if cpu:
                self.assertEqual(self.lib.fact(4, cpu), (cpu * 32 << 4) | (cpu + 1))
                self.assertEqual(self.lib.fact(5, cpu), 1)
                self.assertEqual(self.lib.retry(cpu), -201)
        self.assertEqual(self.lib.fact(6, 0), 8)
        self.assertGreater(self.lib.fact(7, 0), 0)
        self.assertEqual(self.lib.fact(8, 0), 2)

    def test_missing_firmware_return_irq_timer_binding_and_logger_never_pass(self):
        for kind in range(1, 11):
            with self.subTest(kind=kind):
                self.assertNotEqual(self.lib.run(kind), 0)
                self.assertEqual(self.lib.fact(6, 0), 0)
                for cpu in range(1, 8):
                    self.assertLessEqual(self.lib.fact(5, cpu), 1)

    def test_native_backend_and_stackless_el1_entry_compile(self):
        directory = Path(self.temp.name)
        source = directory / 'native.c'
        source.write_text(base.TYPES + 'extern size_t strlen(const char *);\n'
            'extern int memcmp(const void *,const void *,size_t);\n'
            'extern void *memcpy(void *,const void *,size_t);\n' + body())
        result = subprocess.run(['clang', '-target', 'aarch64-none-elf', '-mcpu=cortex-a55',
            '-mno-outline-atomics', '-ffreestanding', '-O2', '-Wall', '-Wextra', '-Werror',
            '-c', str(source), '-o', str(directory / 'native.o')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        section = (HERE / 'smp-eight.patch').read_text().split(
            'diff --git a/osfmk/arm64/start.s', 1)[1].split('diff --git ', 1)[0]
        assembly = '\n'.join(line[1:] for line in section.splitlines()
                             if line.startswith('+') and not line.startswith('+++'))
        self.assertNotRegex(assembly, r'(?m)^\s*(?:bl|blr|ret|smc|ldr|str|stp)\b')
        self.assertNotIn('HCR_EL2', assembly)
        self.assertIn('lsl x2, x0, #8', assembly)
        self.assertIn('cmp x0, #7', assembly)
        macros = '''#define EXT(x) _ ## x
#define LEXT(x) _ ## x ## :
.text
.macro MOV64
 movk $0, #((($1) >> 48) & 0xffff), lsl #48
 movk $0, #((($1) >> 32) & 0xffff), lsl #32
 movk $0, #((($1) >> 16) & 0xffff), lsl #16
 movk $0, #((($1) >> 0) & 0xffff), lsl #0
.endmacro
'''
        path = directory / 'eight-entry.S'
        path.write_text(macros + assembly + '\n')
        result = subprocess.run(['clang', '-target', 'arm64-apple-macos11', '-c', str(path),
            '-o', str(directory / 'eight-entry.o')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
