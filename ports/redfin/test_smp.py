"""Actual-C isolated SMP2 policy, IRQ and concurrent worker proof; no device I/O."""
from pathlib import Path
import ctypes
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VALID = ('debug=0xc serial=3 cpus=2 keepsyms=1 -noprogress rd=md0 '
         'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
         'modem=0 wifi=0 gpu=0 redfinsmp=1 redfinshim=1 redfinspmi=0 '
         'redfinreturn=0 redfinbootid=0x0123456789abcdef')


def added_file(name):
    patch = (HERE / 'smp.patch').read_text()
    section = patch.split('diff --git a/' + name + ' b/' + name + '\n', 1)[1]
    section = section.split('diff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+') and not line.startswith('+++')) + '\n'


def body():
    text = added_file('osfmk/arm64/redfin_smp.c')
    text = re.sub(r'^#include .*\n', '', text, flags=re.M)
    return text


TYPES = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#define SWEET 1
#define PAGE_SIZE 16384
#define CPU_TOPOLOGY_VERSION 1
#define CLUSTER_TYPE_SMP 0
#define KERN_SUCCESS 0
#define THREAD_NULL ((thread_t)0)
#define THREAD_CONTINUE_NULL ((void *)0)
#define NSEC_PER_SEC 1000000000ULL
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define DSB_SY 15
#define DSB_ISHST 10
#define ISB_SY 15
typedef uintptr_t vm_offset_t;
typedef int wait_result_t;
typedef int kern_return_t;
typedef int processor_t;
typedef struct test_thread *thread_t;
typedef struct { unsigned cpu_id;uint32_t phys_id;unsigned cluster_id,die_id,cluster_type;
 uint32_t l2_access_penalty,l2_cache_size,l2_cache_id,l3_cache_size,l3_cache_id;
 unsigned die_cluster_id,cluster_core_id; } ml_topology_cpu_t;
typedef struct { unsigned cluster_id,cluster_type,num_cpus,first_cpu_id;uint64_t cpu_mask; } ml_topology_cluster_t;
typedef struct { unsigned version,num_cpus,max_cpu_id,num_clusters,max_cluster_id,max_die_id;
 ml_topology_cpu_t *cpus;ml_topology_cluster_t *clusters;ml_topology_cpu_t *boot_cpu;
 ml_topology_cluster_t *boot_cluster; } ml_topology_info_t;
extern const char *PE_boot_args(void);
extern const ml_topology_info_t *ml_get_topology_info(void);
extern void panic(const char *,...) __attribute__((noreturn));
extern processor_t thread_bind(processor_t);
extern processor_t cpu_to_processor(int);
extern void thread_block(void *);
extern uint64_t mach_absolute_time(void);
extern void nanoseconds_to_deadline(uint64_t,uint64_t *);
extern int kernel_thread_start(void (*)(void *,int),void *,thread_t *);
extern void thread_deallocate(thread_t);
extern int thread_is_active(thread_t);
extern thread_t current_thread(void);
extern void thread_terminate(thread_t);
extern void delay(unsigned);
extern void kprintf(const char *,...);
'''

HOST_PREFIX = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <unistd.h>
struct test_thread { pthread_t native;int active;void (*entry)(void *,int);void *arg; };
static _Thread_local unsigned test_cpu;
static _Thread_local thread_t test_thread;
static char test_args[608];
static ml_topology_cpu_t test_cpus[2];
static ml_topology_cluster_t test_cluster;
static ml_topology_info_t test_topology;
static unsigned test_scenario,test_pending[2],test_sends[2],test_pauses[2];
static unsigned test_psci_calls,test_on_calls,test_return_calls,test_log_calls,test_feed[2],test_verdict_calls;
static uint32_t test_trace[16];
static uint64_t test_time;
static thread_t test_worker;
const char *PE_boot_args(void) { return test_args; }
const ml_topology_info_t *ml_get_topology_info(void) { return &test_topology; }
void panic(const char *s,...) { fprintf(stderr,"unexpected panic: %s\n",s);abort(); }
processor_t cpu_to_processor(int n) { return n; }
processor_t thread_bind(processor_t n) {
 test_cpu=(n==1 && test_scenario==12)?2:(unsigned)n;return 0;
}
void thread_block(void *p) { (void)p; }
uint64_t mach_absolute_time(void) { return __atomic_load_n(&test_time,__ATOMIC_RELAXED); }
void nanoseconds_to_deadline(uint64_t n,uint64_t *d) { *d=mach_absolute_time()+n; }
static void *test_worker_main(void *p) {
 test_thread=(thread_t)p;test_thread->entry(test_thread->arg,0);
 __atomic_store_n(&test_thread->active,0,__ATOMIC_RELEASE);return NULL;
}
int kernel_thread_start(void (*f)(void *,int),void *arg,thread_t *out) {
 if(test_scenario==11) return 5;
 test_worker=calloc(1,sizeof(*test_worker));assert(test_worker);
 test_worker->entry=f;test_worker->arg=arg;test_worker->active=1;*out=test_worker;
 return pthread_create(&test_worker->native,NULL,test_worker_main,test_worker);
}
void thread_deallocate(thread_t t) { assert(t==test_worker); }
int thread_is_active(thread_t t) { return __atomic_load_n(&t->active,__ATOMIC_ACQUIRE); }
thread_t current_thread(void) { return test_thread; }
void thread_terminate(thread_t t) { assert(t==test_thread);__atomic_store_n(&t->active,0,__ATOMIC_RELEASE);pthread_exit(NULL); }
void redfin_shutdown_watchdog_tick(unsigned final) { assert(!final);assert(test_cpu==0);test_feed[0]++; }
static uint64_t rf_smp_reg(unsigned);
static int32_t rf_smp_psci(uint32_t,uint64_t,uint64_t,uint64_t);
static void rf_smp_send(unsigned);
static bool rf_smp_entry_ok(vm_offset_t);
static void rf_smp_barrier(void);
static void rf_smp_pause(void);
static void rf_smp_round_delay(void);
'''

HOST_HARDWARE = r'''
/* Same C policy/IRQ/proof; replace only architectural registers, SMC and time pacing. */
static uint64_t rf_smp_reg(unsigned n) {
 switch(n) {
 case RF_SMP_MPIDR:return test_cpu==0?0x80000000ULL:(test_cpu==1?0x81000600ULL:0x81000700ULL);
 case RF_SMP_EL:return test_scenario==30?8:4;
 case RF_SMP_MIDR:return test_cpu==0?0x51ff805eULL:0x51ff804eULL;
 case RF_SMP_MMFR0:return test_scenario==31?0:0x101122;
 case RF_SMP_CTR:return test_scenario==32?0x9444c003:0x9444c004;
 default:return test_scenario==33?0:0x30501805;
 }
}
static int32_t rf_smp_psci(uint32_t fn,uint64_t a,uint64_t b,uint64_t c) {
 assert(test_cpu==0);assert(test_psci_calls<16);test_trace[test_psci_calls++]=fn;
 if(fn==0x84000000u) { assert(!a&&!b&&!c);return test_scenario==1?0x10000:0x10001; }
 if(fn==0x8400000au) { assert(!b&&!c);return (test_scenario==2&&a==RF_SMP_ON)||(test_scenario==3&&a==RF_SMP_AFFINITY)?-1:0; }
 if(fn==RF_SMP_AFFINITY) { assert(a==0x600&&!b&&!c);return test_scenario==4?0:(test_scenario==5?2:1); }
 assert(fn==RF_SMP_ON && a==0x600 && b==0x180100000ULL && c==1);
 test_on_calls++;assert(test_return_calls==1);return test_scenario==8?-3:0;
}
int redfin_smp_return_ready(void) {
 assert(test_cpu==0);test_return_calls++;
 if(test_scenario==6) return 0;
 if(test_scenario==7) return 2;
 if(test_scenario==9) test_args[0]='X';
 return 1;
}
int redfin_log_smp_quiescent(void) {
 test_log_calls++;
 return (test_scenario==16 || (test_scenario==17&&test_log_calls==2))?0:1;
}
static void rf_smp_send(unsigned target) {
 assert(target<2);unsigned cpu=test_cpu;assert(cpu<2);
 __atomic_add_fetch(&test_sends[cpu],1,__ATOMIC_RELAXED);
 uint64_t req=__atomic_load_n(&rf_smp_request[target],__ATOMIC_ACQUIRE);
 if((test_scenario==13&&target==1&&req==1) ||
    (test_scenario==14&&target==1&&req>1) ||
    (test_scenario==15&&target==0&&req>1) ||
    (test_scenario==18&&__atomic_load_n(&rf_smp_phase,__ATOMIC_ACQUIRE)==RF_SMP_DRAIN)) return;
 /* A real PE still handles IRQs after its proof thread terminates. */
 if(target==1 && test_worker && !thread_is_active(test_worker)) {
  unsigned previous=test_cpu;test_cpu=1;redfin_smp_irq(1);test_cpu=previous;return;
 }
 __atomic_store_n(&test_pending[target],1,__ATOMIC_RELEASE);
}
static bool rf_smp_entry_ok(vm_offset_t entry) { return entry==0x180100000ULL; }
static void rf_smp_barrier(void) { __atomic_thread_fence(__ATOMIC_SEQ_CST); }
static void rf_smp_pause(void) {
 unsigned cpu=test_cpu;
 if(cpu>1) return;
 /* A PE keeps handling IRQs after its proof thread exits. A send may have
  * observed the thread active just before termination, so also deliver that
  * last queued IRQ from the host's coordinator/idle simulation. */
 if(!cpu && test_worker && !thread_is_active(test_worker) &&
    __atomic_exchange_n(&test_pending[1],0,__ATOMIC_ACQ_REL)) {
  test_cpu=1;redfin_smp_irq(1);test_cpu=0;
 }
 test_pauses[cpu]++;
 __atomic_add_fetch(&test_time,test_scenario==19?100000000ULL:50000,__ATOMIC_RELAXED);
 if(__atomic_exchange_n(&test_pending[cpu],0,__ATOMIC_ACQ_REL)) redfin_smp_irq(1);
 if(test_scenario!=20 && !(test_scenario==21&&cpu==1)) redfin_smp_irq(0);
 struct timespec ts={0,1000};nanosleep(&ts,NULL);sched_yield();
}
static void rf_smp_round_delay(void) { for(unsigned i=0;i<20;i++)rf_smp_pause(); }
'''

HOST_SUFFIX = r'''
void kprintf(const char *fmt,...) {
 assert(test_cpu==0 && rf_smp_phase==RF_SMP_DONE);assert(strstr(fmt,"tlb=untested"));
 test_verdict_calls++;
}
static const char *valid_args="VALID_ARGS";
static void test_reset(unsigned scenario) {
 test_cpu=0;test_thread=NULL;test_scenario=scenario;test_time=1;
 strcpy(test_args,valid_args);memset(test_cpus,0,sizeof(test_cpus));memset(&test_cluster,0,sizeof(test_cluster));
 memset(&test_topology,0,sizeof(test_topology));
 test_cpus[0].cpu_id=0;test_cpus[0].phys_id=0;
 test_cpus[1].cpu_id=1;test_cpus[1].phys_id=0x600;test_cpus[1].cluster_core_id=1;test_cpus[1].l2_cache_id=1;
 test_cluster.num_cpus=2;test_cluster.cpu_mask=3;
 test_topology.version=1;test_topology.num_cpus=2;test_topology.max_cpu_id=1;test_topology.num_clusters=1;
 test_topology.cpus=test_cpus;test_topology.clusters=&test_cluster;
 test_topology.boot_cpu=test_cpus;test_topology.boot_cluster=&test_cluster;
 memset(rf_smp_frozen,0,sizeof(rf_smp_frozen));rf_smp_frozen_bytes=0;
 rf_smp_prepared=rf_smp_started=rf_smp_selected=rf_smp_phase=rf_smp_fault=0;rf_smp_deadline=0;
 memset(rf_smp_request,0,sizeof(rf_smp_request));memset(rf_smp_ack,0,sizeof(rf_smp_ack));
 memset(rf_smp_timers,0,sizeof(rf_smp_timers));memset(rf_smp_progress,0,sizeof(rf_smp_progress));
 memset(rf_smp_ready,0,sizeof(rf_smp_ready));memset(rf_smp_finished,0,sizeof(rf_smp_finished));
 memset(rf_smp_drained,0,sizeof(rf_smp_drained));memset(test_pending,0,sizeof(test_pending));
 memset(test_sends,0,sizeof(test_sends));memset(test_pauses,0,sizeof(test_pauses));
 memset(test_feed,0,sizeof(test_feed));memset(test_trace,0,sizeof(test_trace));
 test_psci_calls=test_on_calls=test_return_calls=test_log_calls=test_verdict_calls=0;test_worker=NULL;
}
int test_flags(const char *s) { return rf_smp_flags(s,(unsigned)strlen(s)+1,NULL); }
int test_runtime(unsigned n) {
 test_reset(n);return rf_smp_boot_cpu();
}
int test_up_mode(void) {
 test_reset(0);strcpy(test_args,"cpus=1 existingfuturewriter=1 redfinspmi=1");
 return redfin_smp_mode()==0 && !rf_smp_selected && !rf_smp_prepared && !test_psci_calls;
}
int test_presence(const char *s) { return rf_smp_present(s,(unsigned)strlen(s)+1); }
int test_topology_case(unsigned n) {
 test_reset(0);
 switch(n) {
 case 1:test_topology.num_cpus=1;break;
 case 2:test_cpus[1].phys_id=1;break;
 case 3:test_cpus[1].cpu_id=6;break;
 case 4:test_cpus[1].cluster_core_id=6;break;
 case 5:test_cpus[1].l2_cache_id=0;break;
 case 6:test_cpus[1].l3_cache_id=1;break;
 case 7:test_cpus[1].l2_cache_size=262144;break;
 case 8:test_cpus[1].cluster_type=1;break;
 case 9:test_topology.boot_cpu=&test_cpus[1];break;
 case 10:test_cluster.cpu_mask=0x41;break;
 case 11:test_topology.version=2;break;
 case 12:test_cluster.num_cpus=1;break;
 }
 return redfin_smp_topology_valid();
}
int test_start(unsigned scenario,unsigned logical,uint64_t entry) {
 test_reset(scenario);redfin_smp_prepare();
 return redfin_smp_start(logical,(vm_offset_t)entry);
}
int test_retry(void) { return redfin_smp_start(1,0x180100000ULL); }
unsigned test_on_count(void) { return test_on_calls; }
unsigned test_return_count(void) { return test_return_calls; }
unsigned test_trace_at(unsigned n) { return n<test_psci_calls?test_trace[n]:0; }
unsigned test_num_calls(void) { return test_psci_calls; }
int test_run(unsigned scenario) {
 test_reset(scenario);redfin_smp_prepare();
 int rc=redfin_smp_start(1,0x180100000ULL);assert(!rc);
 rc=redfin_smp_prove();
 __atomic_store_n(&rf_smp_fault,1,__ATOMIC_RELEASE);
 if(test_worker) { pthread_join(test_worker->native,NULL);free(test_worker);test_worker=NULL; }
 return rc;
}
uint64_t test_fact(unsigned kind,unsigned cpu) {
 assert(cpu<2);
 switch(kind) { case 0:return rf_smp_progress[cpu];case 1:return rf_smp_timers[cpu];
 case 2:return rf_smp_ack[cpu];case 3:return rf_smp_drained[cpu];case 4:return test_feed[cpu];
 case 5:return test_log_calls;case 6:return test_verdict_calls;default:return rf_smp_phase; }
}
int test_irq_case(unsigned n) {
 test_reset(0);rf_smp_phase=RF_SMP_ACTIVE;test_cpu=1;rf_smp_request[1]=6;
 if(n==1)test_cpu=2;
 if(n==2)rf_smp_request[1]=7;
 if(n==3)rf_smp_request[1]=(RF_SMP_ROUNDS+1)*4+2;
 if(n==4)rf_smp_phase=RF_SMP_IDLE;
 if(n==5)rf_smp_phase=RF_SMP_DRAIN;
 if(n==6)rf_smp_timers[1]=UINT64_MAX;
 if(n==7)rf_smp_ack[1]=10;
 redfin_smp_irq(n==6?0:1);
 if(n==1||n==6)return rf_smp_fault==1;
 if(n==5)return rf_smp_drained[1]==1&&rf_smp_ack[1]==0;
 if(n==7)return rf_smp_ack[1]==10;
 return rf_smp_ack[1]==(n==0?6:0);
}
'''.replace('VALID_ARGS', VALID)


class SMPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        source = body()
        start = source.index('/* REDFIN_SMP_HW_BEGIN */')
        end = source.index('/* REDFIN_SMP_HW_END */') + len('/* REDFIN_SMP_HW_END */')
        # Hardware mocks need global state, so their definitions follow the real body.
        source = source[:start] + source[end:]
        path = cls.directory / 'host.c'
        path.write_text(TYPES + HOST_PREFIX + source + HOST_HARDWARE + HOST_SUFFIX)
        library = cls.directory / 'smp.so'
        result = subprocess.run(['clang', '-std=c11', '-D_DARWIN_C_SOURCE', '-O2', '-Wall', '-Wextra',
                        '-Werror', '-fPIC', '-shared', '-pthread', str(path), '-o', str(library)],
                       capture_output=True, text=True)
        if result.returncode: raise RuntimeError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.test_flags.argtypes = [ctypes.c_char_p]
        cls.lib.test_presence.argtypes = [ctypes.c_char_p]
        cls.lib.test_start.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint64]
        cls.lib.test_fact.restype = ctypes.c_uint64
        cls.lib.test_trace_at.restype = ctypes.c_uint32
        patch = (HERE / 'smp.patch').read_text()
        section = patch.split('diff --git a/pexpert/arm/pe_serial.c ', 1)[1].split('diff --git ', 1)[0]
        revised = '\n'.join(line[1:] for line in section.splitlines()
                            if (line.startswith('+') and not line.startswith('+++')) or line.startswith(' '))
        helper = revised[revised.index('/* Acquire snapshots'):revised.index('/* REDFIN_SMP_LOG_OWNER_END */')]
        wrapper = r"""
static uint64_t redfin_log_owner,redfin_log_busy_drops,redfin_log_reentrant_drops;
static uint32_t redfin_log_counts_uncertain;
"""
        wrapper = '#include <stdint.h>\n' + wrapper + helper + r"""
int test_quiescent(unsigned n) {
 redfin_log_owner=n==1?0x601:0;redfin_log_busy_drops=n==2?1:0;
 redfin_log_reentrant_drops=n==3?1:0;redfin_log_counts_uncertain=n==4;
 int result=redfin_log_smp_quiescent();
 return result==(n==0) && redfin_log_owner==(n==1?0x601:0) &&
 redfin_log_busy_drops==(n==2?1:0) && redfin_log_reentrant_drops==(n==3?1:0) &&
 redfin_log_counts_uncertain==(n==4);
}
"""
        helper_path = cls.directory / 'quiescent.c'
        helper_path.write_text(wrapper)
        helper_library = cls.directory / 'quiescent.so'
        helper_result = subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',
                        str(helper_path),'-o',str(helper_library)],capture_output=True,text=True)
        if helper_result.returncode: raise RuntimeError(helper_result.stderr)
        cls.quiescent = ctypes.CDLL(str(helper_library))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_closed_flags(self):
        self.assertEqual(self.lib.test_flags(VALID.encode()), 1)
        self.assertEqual(self.lib.test_flags((VALID+' -enable_kprintf_spam').encode()), 1)
        for token in VALID.split():
            with self.subTest(missing=token):
                self.assertEqual(self.lib.test_flags(VALID.replace(token, '').encode()), 0)
            with self.subTest(duplicate=token):
                self.assertEqual(self.lib.test_flags((VALID+' '+token).encode()), 0)

    def test_reject_writers_and_malformed_values(self):
        for token in ['redfincpu=0','redfincpu=1','redfinfuture=0','redfinufs=0','redfinfb=0',
                      'rootrw=0','cpumask=0x41','unknown=0','-enable_kprintf_spam -enable_kprintf_spam']:
            with self.subTest(token=token):
                self.assertEqual(self.lib.test_flags((VALID+' '+token).encode()), 0)
        for before, after in [('cpus=2','cpus=02'),('cpus=2','cpus=8'),('rd=md0','rd=ufsroot0'),
                              ('redfinspmi=0','redfinspmi=1'),('redfinreturn=0','redfinreturn=1'),
                              ('0123456789abcdef','0000000000000000'),
                              ('0123456789abcdef','0123456789ABCDEF'),
                              ('0123456789abcdef','1234'),('gpu=0','gpu=1')]:
            self.assertEqual(self.lib.test_flags(VALID.replace(before,after).encode()), 0)

    def test_exact_dispatch_presence(self):
        for arg in ['redfinsmp','redfinsmp=0','redfinsmp=1','redfinsmp=18446744073709551616']:
            self.assertEqual(self.lib.test_presence(('x=0 '+arg+' y=0').encode()), 1)
        for arg in ['redfinsmpx=1','xredfinsmp=1','foo=redfinsmp=1']:
            self.assertEqual(self.lib.test_presence(arg.encode()), 0)

    def test_up_mode_is_inert(self):
        self.assertEqual(self.lib.test_up_mode(), 1)

    def test_runtime_guards(self):
        self.assertEqual(self.lib.test_runtime(0), 1)
        for scenario in [30,31,32,33]:
            self.assertEqual(self.lib.test_runtime(scenario), 0)

    def test_read_only_logger_quiescence(self):
        for scenario in range(5):
            self.assertEqual(self.quiescent.test_quiescent(scenario), 1)

    def test_exact_topology(self):
        self.assertEqual(self.lib.test_topology_case(0), 1)
        for case in range(1,13):
            with self.subTest(case=case):self.assertEqual(self.lib.test_topology_case(case), 0)

    def test_single_cpu_on_after_fresh_proof(self):
        self.assertEqual(self.lib.test_start(0,1,0x180100000), 0)
        self.assertEqual(self.lib.test_on_count(), 1)
        self.assertEqual(self.lib.test_return_count(), 1)
        self.assertEqual([self.lib.test_trace_at(i) for i in range(5)],
                         [0x84000000,0x8400000a,0x8400000a,0xc4000004,0xc4000003])
        self.assertEqual(self.lib.test_retry(), -100)
        self.assertEqual(self.lib.test_on_count(), 1)

    def test_failed_gates_never_wake_or_retry(self):
        for scenario in range(1,10):
            with self.subTest(scenario=scenario):
                self.assertLess(self.lib.test_start(scenario,1,0x180100000), 0)
                self.assertEqual(self.lib.test_on_count(), int(scenario==8))
                self.assertEqual(self.lib.test_retry(), -100)
        for logical,entry in [(0,0x180100000),(6,0x180100000),(1,0),(1,0x180100001),(1,0x180200000),(1,0x200000000)]:
            with self.subTest(logical=logical,entry=entry):
                self.assertEqual(self.lib.test_start(0,logical,entry), -101)
                self.assertEqual(self.lib.test_num_calls(), 0)

    def test_irq_guards_and_monotonic_ack(self):
        for case in range(8):self.assertEqual(self.lib.test_irq_case(case), 1)

    def test_real_two_thread_proof(self):
        self.assertEqual(self.lib.test_run(0), 0)
        for cpu in range(2):
            self.assertEqual(self.lib.test_fact(0,cpu), 32)
            self.assertGreaterEqual(self.lib.test_fact(1,cpu), 2)
            self.assertEqual(self.lib.test_fact(2,cpu), (32<<2)|(3-cpu))
            self.assertEqual(self.lib.test_fact(3,cpu), 1)
        self.assertGreater(self.lib.test_fact(4,0), 0)
        self.assertEqual(self.lib.test_fact(4,1), 0)
        self.assertEqual(self.lib.test_fact(5,0), 2)
        self.assertEqual(self.lib.test_fact(6,0), 1)

    def test_proof_refuses_missing_facts(self):
        expected = {11:-111,12:-112,13:-112,14:-112,15:-112,16:-117,17:-118,
                    18:-114,19:-112,20:-116,21:-116}
        for scenario, code in expected.items():
            with self.subTest(scenario=scenario):self.assertEqual(self.lib.test_run(scenario), code)

    def test_actual_aarch64_backend(self):
        source = body()
        # Declare libc APIs; no host platform headers or hardware substitution.
        declarations = ('extern size_t strlen(const char *);\n'
                        'extern int memcmp(const void *,const void *,size_t);\n'
                        'extern void *memcpy(void *,const void *,size_t);\n')
        path = self.directory / 'arm.c'
        path.write_text(TYPES + declarations + source)
        result = subprocess.run(['clang','-target','aarch64-none-elf','-mcpu=cortex-a53',
                                 '-mno-outline-atomics','-ffreestanding','-std=c11','-O2',
                                 '-Wall','-Wextra','-Werror','-c',str(path),
                                 '-o',str(self.directory/'arm.o')], capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_actual_el1_only_trampoline_assembles(self):
        patch = (HERE/'smp.patch').read_text()
        section = patch.split('diff --git a/osfmk/arm64/start.s ',1)[1].split('diff --git ',1)[0]
        assembly = '\n'.join(line[1:] for line in section.splitlines()
                             if line.startswith('+') and not line.startswith('+++'))
        assembly = re.sub(r'LEXT\(([^)]+)\)',r'_\1:',assembly)
        assembly = re.sub(r'EXT\(([^)]+)\)',r'_\1',assembly)
        assembly = assembly.replace('MOV64\tx2, 0xff00ffffff',
                                    'movz x2, #0xffff\n movk x2, #0xff, lsl #16\n movk x2, #0xff, lsl #32')
        path=self.directory/'entry.s';path.write_text(assembly+'\n')
        result=subprocess.run(['clang','-target','arm64-apple-macos11','-c',str(path),
                               '-o',str(self.directory/'entry.o')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('HCR_EL2',assembly)
        self.assertIn('SCTLR_EL1',assembly)


if __name__ == '__main__':
    unittest.main()
