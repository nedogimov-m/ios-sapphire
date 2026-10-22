"""Compile old/new actual RAM loggers; exercise real concurrent publication."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def bodies():
    text = (HERE / 'smp-log.patch').read_text()
    old = '\n'.join(line[1:] for line in text.splitlines() if line.startswith('-') and not line.startswith('---'))
    new = '\n'.join(line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++'))
    return old, new


def source(old=False):
    text = bodies()[0 if old else 1]
    if old:
        for register, replacement in [('DAIF', 'test_daif'), ('CNTPCT_EL0', 'test_now'),
                                      ('CNTFRQ_EL0', 'test_frequency')]:
            text = text.replace('__builtin_arm_rsr64("' + register + '")', replacement)
        text = re.sub(r'__builtin_arm_wsr64\("DAIF",\s*([^)]*)\)', r'(test_daif=(\1))', text)
        text = text.replace('__asm__ volatile("msr daifset, #3" ::: "memory");', 'test_daif|=0xc0;')
        return text.replace('__asm__ volatile("dsb sy" ::: "memory");',
                            '__atomic_thread_fence(__ATOMIC_SEQ_CST);')
    start = text.index('/* REDFIN_SMP_LOG_HW_BEGIN */')
    end = text.index('/* REDFIN_SMP_LOG_HW_END */') + len('/* REDFIN_SMP_LOG_HW_END */')
    return text[:start] + HARDWARE + text[end:]


PREFIX = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#define SWEET 1
#define kSuccess 0
#define SECURITY_READ_ONLY_LATE(x) x
#define SERIAL_SWEET_FBCON 1
#define HOST_CAP 131072
static _Thread_local uint64_t test_cpu,test_daif;
static _Thread_local unsigned test_relaxes;
static _Thread_local unsigned test_spurious_owner,test_spurious_counter,test_owner_cas,test_counter_cas;
static uint64_t test_now=100,test_frequency=1000;
static unsigned mapping_failure,map_calls,register_calls,dt_failure,bad_map_owner;
static unsigned char backing[2][HOST_CAP+12];
static uint32_t wd[0x1000/4];
static uint64_t reg[4]={0x10000000,0x1000,0x10002000,0x1000};
static uint64_t watchdog_reg[2]={0x17c10000,0x1000};
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
typedef void *DTEntry;
struct pe_serial_functions {
 void (*init)(void);
 unsigned (*transmit_ready)(void);
 void (*transmit_data)(uint8_t);
 unsigned (*receive_ready)(void);
 uint8_t (*receive_data)(void);
 unsigned device;
};
static void register_serial_functions(struct pe_serial_functions *p) { assert(p);++register_calls; }
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *entry) {
 (void)root;
 if(!strcmp(path,"/redfin-log")) { if(dt_failure==1)return -1;*entry=(void*)1;return 0; }
 if(!strcmp(path,"/redfin-watchdog")) { *entry=(void*)2;return 0; }
 abort();
}
static int SecureDTGetProperty(DTEntry entry,const char *key,const void **out,unsigned *bytes) {
 assert(!strcmp(key,"reg"));
 if(entry==(void*)1) { *out=reg;*bytes=dt_failure==2?24:sizeof(reg);return 0; }
 if(entry==(void*)2) { *out=watchdog_reg;*bytes=sizeof(watchdog_reg);return 0; }
 abort();
}
vm_offset_t ml_io_map(vm_offset_t,vm_size_t);
'''

CAS_INJECTION = r'''
#define TEST_CAS_INJECT 1
static bool test_compare_exchange(uint64_t *,uint64_t *,uint64_t,bool,int,int);
#define __atomic_compare_exchange_n test_compare_exchange
'''

HARDWARE = r'''
static uint64_t redfin_log_cpu(void) { return test_cpu+1; }
static uint64_t redfin_log_counter(void) { return test_now; }
static uint64_t redfin_log_frequency(void) { return test_frequency; }
static uint64_t redfin_log_irq_save(bool all) {
 uint64_t old=test_daif;test_daif|=all?0x3c0:0xc0;return old;
}
static void redfin_log_irq_restore(uint64_t value) { test_daif=value; }
static void redfin_log_barrier(void) { __atomic_thread_fence(__ATOMIC_SEQ_CST); }
static void redfin_log_relax(void) { ++test_relaxes;__atomic_signal_fence(__ATOMIC_SEQ_CST); }
'''

SUFFIX = r'''
#ifdef TEST_CAS_INJECT
#undef __atomic_compare_exchange_n
static bool test_compare_exchange(uint64_t *object,uint64_t *expected,uint64_t desired,
 bool weak,int success,int failure) {
 assert(weak && failure==__ATOMIC_RELAXED);
 unsigned *spurious;
 if(object==&redfin_log_owner) { ++test_owner_cas;spurious=&test_spurious_owner; }
 else { ++test_counter_cas;spurious=&test_spurious_counter; }
 if(*spurious) { --*spurious;*expected=__atomic_load_n(object,__ATOMIC_RELAXED);return false; }
 if(success==__ATOMIC_ACQUIRE)
  return __atomic_compare_exchange_n(object,expected,desired,true,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED);
 assert(success==__ATOMIC_RELAXED);
 return __atomic_compare_exchange_n(object,expected,desired,true,__ATOMIC_RELAXED,__ATOMIC_RELAXED);
}
#endif
vm_offset_t ml_io_map(vm_offset_t base,vm_size_t size) {
 assert(size==0x1000);
 ++map_calls;
#ifdef TEST_NEW
 if(__atomic_load_n(&redfin_log_owner,__ATOMIC_RELAXED))++bad_map_owner;
#endif
 if(mapping_failure==map_calls)return 0;
 if(base==reg[0])return (uintptr_t)backing[0];
 if(base==reg[2])return (uintptr_t)backing[1];
 if(base==watchdog_reg[0])return (uintptr_t)wd;
 abort();
}
static void reset(unsigned capacity) {
 memset(backing,0,sizeof(backing));memset(wd,0,sizeof(wd));
 redfin_log_count=2;redfin_watchdog_reset=wd+1;
 redfin_watchdog_deadline=10000;redfin_watchdog_last=100;redfin_watchdog_frequency=1000;
 test_cpu=0;test_daif=0x200;test_relaxes=0;test_now=100;test_frequency=1000;
 test_spurious_owner=test_spurious_counter=test_owner_cas=test_counter_cas=0;
 mapping_failure=map_calls=register_calls=dt_failure=bad_map_owner=0;
 for(unsigned i=0;i<2;i++) {
  redfin_logs[i]=(struct redfin_ramlog*)backing[i];redfin_log_capacity[i]=capacity;
  redfin_logs[i]->signature=0x43474244;
 }
#ifdef TEST_NEW
 redfin_log_owner=redfin_log_busy_drops=redfin_log_reentrant_drops=0;
 redfin_log_counts_uncertain=0;
 redfin_log_init_attempted=0;
#endif
}
static void reference_output(void) {
 reset(17);
 const char *message="line one\nline two\nline three\n";
 for(const char *p=message;*p;p++) { test_now+=180;redfin_log_putc(*p);assert(test_daif==0x200); }
 assert(redfin_shutdown_watchdog_start(120)==1);
 test_now+=1001;redfin_shutdown_watchdog_tick(0);test_now+=1001;redfin_shutdown_watchdog_tick(1);
 redfin_log_putc('\n');
 fwrite(backing[0],1,29,stdout);fwrite(backing[1],1,29,stdout);
 uint64_t state[]={redfin_watchdog_deadline,redfin_watchdog_last,redfin_watchdog_frequency,wd[1],test_daif};
 fwrite(state,sizeof(state),1,stdout);
}
static void init_reference_output(void) {
 reset(17);redfin_log_count=0;redfin_watchdog_reset=NULL;memset(backing,0xa5,sizeof(backing));
 redfin_log_probe();
 fwrite(backing[0],1,0x1000,stdout);fwrite(backing[1],1,0x1000,stdout);
 uint64_t state[]={redfin_log_count,redfin_watchdog_deadline,redfin_watchdog_last,
  redfin_watchdog_frequency,register_calls,map_calls,test_daif};
 fwrite(state,sizeof(state),1,stdout);
}
#ifdef TEST_NEW
static unsigned operations=10000;
static unsigned threads_count=8;
static pthread_barrier_t barrier;
static void *writer(void *arg) {
 unsigned id=(unsigned)(uintptr_t)arg;test_cpu=id*0x100;test_daif=0x200;
 pthread_barrier_wait(&barrier);
 for(unsigned n=0;n<operations;n++) { redfin_log_putc((char)('A'+id));assert(test_daif==0x200); }
 return NULL;
}
static void concurrent(void) {
 unsigned total=operations*threads_count;
 reset(total);
 pthread_t threads[8];pthread_barrier_init(&barrier,NULL,threads_count);
 for(unsigned i=0;i<threads_count;i++)assert(!pthread_create(threads+i,NULL,writer,(void*)(uintptr_t)i));
 for(unsigned i=0;i<threads_count;i++)assert(!pthread_join(threads[i],NULL));
 pthread_barrier_destroy(&barrier);
 uint64_t busy,reentry;redfin_log_smp_stats(&busy,&reentry);
 unsigned written=redfin_logs[0]->size;
 assert(written>0 && written<=total && busy==total-written && !reentry);
 assert(redfin_logs[0]->start==written%total);
 assert(!memcmp(backing[0],backing[1],12+total));
 unsigned seen[8]={0};
 for(unsigned i=0;i<written;i++) {
  unsigned c=backing[0][12+i];assert(c>='A' && c<'A'+threads_count);seen[c-'A']++;
 }
 for(unsigned i=0;i<threads_count;i++)assert(seen[i]<=operations);
 assert(redfin_watchdog_last==100 && !wd[1]);
 printf("accepted=%u dropped=%llu\n",written,(unsigned long long)busy);
}
static void *ticker(void *unused) {
 (void)unused;test_cpu=0;test_daif=0x200;
 pthread_barrier_wait(&barrier);
 for(unsigned n=0;n<operations;n++) {
  test_now=101+n;redfin_shutdown_watchdog_tick(0);
  if(!(n%1000))redfin_log_putc('\n');
  assert(test_daif==0x200);
 }
 return NULL;
}
static void mixed(void) {
 reset(80000);assert(redfin_shutdown_watchdog_start(120));
 pthread_t threads[8];pthread_barrier_init(&barrier,NULL,8);
 assert(!pthread_create(threads,NULL,ticker,NULL));
 for(unsigned i=1;i<8;i++)assert(!pthread_create(threads+i,NULL,writer,(void*)(uintptr_t)i));
 for(unsigned i=0;i<8;i++)assert(!pthread_join(threads[i],NULL));
 pthread_barrier_destroy(&barrier);
 uint64_t busy,reentry;redfin_log_smp_stats(&busy,&reentry);
 assert(!reentry && redfin_logs[0]->size+busy==7*operations+operations/1000);
 assert(!memcmp(backing[0],backing[1],12+80000));
 assert(redfin_watchdog_deadline==120100 && redfin_watchdog_last>=100 && redfin_watchdog_last<=test_now);
 test_cpu=0;wd[1]=0;test_now=15000;redfin_shutdown_watchdog_tick(0);
 assert(wd[1]==1 && redfin_watchdog_last==15000);
 redfin_shutdown_watchdog_tick(1);wd[1]=0;test_now=16000;
 redfin_log_putc('\n');redfin_shutdown_watchdog_tick(0);assert(!wd[1] && !redfin_watchdog_deadline);
}
static void bounded(void) {
 reset(17);uint64_t daif;
 assert(redfin_log_enter(&daif,false,false));
 redfin_log_putc('R');assert(test_daif==0x2c0);
 assert(redfin_log_reentrant_drops==1 && redfin_logs[0]->size==0 && !test_relaxes);
 redfin_log_leave(daif);assert(test_daif==0x200);
 redfin_log_owner=0x701;test_relaxes=0;
 redfin_log_putc('B');assert(test_relaxes==REDFIN_LOG_OWNER_TRIES && test_daif==0x200);
 assert(redfin_log_owner==0x701 && redfin_log_busy_drops==1 && redfin_logs[0]->size==0);
 uint64_t busy,reentry;unsigned before=test_relaxes;
 redfin_log_smp_stats(&busy,&reentry);redfin_log_smp_stats(NULL,NULL);
 assert(busy==1 && reentry==1 && test_relaxes==before && redfin_log_owner==0x701);
 assert(redfin_shutdown_watchdog_start(120)==0);
 redfin_shutdown_watchdog_tick(1);assert(redfin_watchdog_deadline==10000);
 redfin_log_owner=0;redfin_log_putc('K');assert(redfin_logs[0]->size==1);
}
static void watchdog(void) {
 reset(17);test_cpu=0x600;test_now=5000;
 redfin_log_putc('\n');redfin_shutdown_watchdog_tick(1);
 assert(!redfin_shutdown_watchdog_start(120));
 assert(!wd[1] && redfin_watchdog_last==100 && redfin_watchdog_deadline==10000);
 test_cpu=0;redfin_log_putc('\n');assert(wd[1]==1 && redfin_watchdog_last==5000);
 wd[1]=0;test_now=10000;redfin_shutdown_watchdog_tick(0);assert(!wd[1]);
 assert(!redfin_shutdown_watchdog_start(4));assert(redfin_shutdown_watchdog_start(120));
 wd[1]=0;redfin_shutdown_watchdog_tick(1);test_now+=100000;
 redfin_log_putc('\n');redfin_shutdown_watchdog_tick(0);assert(!wd[1] && !redfin_watchdog_deadline);
 assert(test_daif==0x200);
}
static void initialize(unsigned failure,unsigned secondary) {
 reset(17);redfin_log_count=0;redfin_watchdog_reset=NULL;
 memset(backing,0xa5,sizeof(backing));
 mapping_failure=failure;test_cpu=secondary?0x600:0;
 redfin_log_probe();
 if(failure || secondary) {
  assert(!redfin_log_count && !register_calls);
  for(unsigned i=0;i<sizeof(backing);i++)assert(((unsigned char*)backing)[i]==0xa5);
 } else {
  assert(redfin_log_count==2 && register_calls==1 && !bad_map_owner);
  assert(redfin_logs[0]->signature==0x43474244 && redfin_log_capacity[0]==0x1000-12);
  assert(redfin_logs[0]->size && !memcmp(backing[0],backing[1],0x1000));
  assert(redfin_watchdog_reset==wd+1 && redfin_watchdog_deadline==60100);
  unsigned before=map_calls;redfin_log_probe();assert(map_calls==before && register_calls==1);
 }
 assert(test_daif==0x200);
}
static void corrupt(void) {
 reset(17);redfin_logs[0]->start=17;redfin_log_putc('x');
 assert(redfin_logs[0]->start==17 && !redfin_logs[0]->size && redfin_logs[1]->size==1);
 assert(backing[0][12]==0 && backing[1][12]=='x');
}
#ifdef TEST_CAS_INJECT
static void spurious(void) {
 reset(17);test_spurious_owner=REDFIN_LOG_OWNER_TRIES;
 redfin_log_putc('d');
 assert(test_owner_cas==REDFIN_LOG_OWNER_TRIES && !test_spurious_owner);
 assert(!redfin_log_owner && !redfin_logs[0]->size && redfin_log_busy_drops==1);
 assert(test_counter_cas==1 && !redfin_log_counts_uncertain && test_daif==0x200);
 redfin_log_putc('k');assert(redfin_logs[0]->size==1);
}
static void uncertain(void) {
 reset(17);redfin_log_owner=0x701;test_spurious_counter=REDFIN_LOG_OWNER_TRIES;
 redfin_log_putc('d');
 assert(test_counter_cas==REDFIN_LOG_OWNER_TRIES && !test_spurious_counter);
 assert(redfin_log_counts_uncertain && !redfin_log_busy_drops && !redfin_logs[0]->size);
 uint64_t busy,reentry;redfin_log_smp_stats(&busy,&reentry);
 assert(busy==UINT64_MAX && reentry==UINT64_MAX && test_daif==0x200 && redfin_log_owner==0x701);
 reset(17);redfin_log_owner=0x701;redfin_log_busy_drops=UINT64_MAX;
 redfin_log_putc('d');redfin_log_smp_stats(&busy,&reentry);
 assert(busy==UINT64_MAX && !reentry && !test_counter_cas);
}
#endif
#endif
int main(int argc,char **argv) {
 if(argc<2)return 2;
 if(!strcmp(argv[1],"up"))reference_output();
 else if(!strcmp(argv[1],"init-up"))init_reference_output();
#ifdef TEST_NEW
 else if(!strcmp(argv[1],"concurrent"))concurrent();
 else if(!strcmp(argv[1],"mixed"))mixed();
 else if(!strcmp(argv[1],"bounded"))bounded();
 else if(!strcmp(argv[1],"watchdog"))watchdog();
 else if(!strcmp(argv[1],"init"))initialize(argc>2?(unsigned)atoi(argv[2]):0,argc>3?(unsigned)atoi(argv[3]):0);
 else if(!strcmp(argv[1],"corrupt"))corrupt();
#ifdef TEST_CAS_INJECT
 else if(!strcmp(argv[1],"spurious"))spurious();
 else if(!strcmp(argv[1],"uncertain"))uncertain();
#endif
#endif
 else return 3;
 return 0;
}
'''

# macOS has pthread mutexes/conditions, but no pthread_barrier_t.
BARRIER = r'''
typedef struct { pthread_mutex_t mutex;pthread_cond_t condition;unsigned count,total,generation; } host_barrier;
#define pthread_barrier_t host_barrier
static int host_barrier_init(host_barrier *b,void *attr,unsigned total) {
 (void)attr;memset(b,0,sizeof(*b));b->total=total;
 return pthread_mutex_init(&b->mutex,NULL) || pthread_cond_init(&b->condition,NULL);
}
static int host_barrier_wait(host_barrier *b) {
 pthread_mutex_lock(&b->mutex);unsigned generation=b->generation;
 if(++b->count==b->total) { b->count=0;++b->generation;pthread_cond_broadcast(&b->condition); }
 else while(generation==b->generation)pthread_cond_wait(&b->condition,&b->mutex);
 pthread_mutex_unlock(&b->mutex);return 0;
}
static int host_barrier_destroy(host_barrier *b) {
 return pthread_mutex_destroy(&b->mutex) || pthread_cond_destroy(&b->condition);
}
#define pthread_barrier_init host_barrier_init
#define pthread_barrier_wait host_barrier_wait
#define pthread_barrier_destroy host_barrier_destroy
'''


class SMPLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.old, cls.new = root / 'old', root / 'new'
        compiler = shutil.which('clang') or 'cc'
        for old, executable in ((True, cls.old), (False, cls.new)):
            path = root / (executable.name + '.c')
            path.write_text(PREFIX + ('\n#define TEST_NEW 1\n' + BARRIER + CAS_INJECTION if not old else '') + source(old) + SUFFIX)
            result = subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                     '-Wno-unused-function', '-pthread', str(path), '-o', str(executable)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, *args):
        return subprocess.check_output([str(self.new), *args], timeout=15)

    def test_actual_prepared_logger_baseline_matches_patch(self):
        prepared = HERE.parents[1] / 'research/redfin-build/dxb/xnu/pexpert/arm/pe_serial.c'
        if prepared.exists():
            text = prepared.read_text()
            # Later overlays add a read-only proof helper and move the nonce
            # into this logger. Reverse just those file hunks before comparing
            # the exact logger body, independent of its integration stage.
            if 'REDFIN_EARLY_BOOT_ID_BEGIN' in text or 'redfin_log_smp_quiescent' in text:
                with tempfile.TemporaryDirectory() as temporary:
                    target = Path(temporary) / 'pexpert/arm/pe_serial.c'
                    target.parent.mkdir(parents=True)
                    target.write_text(text)
                    for marker, overlay in (('REDFIN_EARLY_BOOT_ID_BEGIN', 'early-bootid.patch'),
                                            ('redfin_log_smp_quiescent', 'smp.patch')):
                        if marker in target.read_text():
                            subprocess.run(['git', 'apply', '--reverse',
                                '--include=pexpert/arm/pe_serial.c', str(HERE / overlay)],
                                cwd=temporary, check=True, capture_output=True)
                    text = target.read_text()
            a = text.index('/* Linux persistent_ram console ABI')
            b = text.index('#endif /* SWEET */', a) + len('#endif /* SWEET */')
            self.assertIn(text[a:b], bodies())

    def test_up_ring_bytes_wrap_and_watchdog_behavior_match_actual_previous_logger(self):
        self.assertEqual(self.run_case('up'), subprocess.check_output([str(self.old), 'up'], timeout=5))

    def test_up_initial_ring_abi_banner_watchdog_and_registration_match_previous_logger(self):
        self.assertEqual(self.run_case('init-up'),
                         subprocess.check_output([str(self.old), 'init-up'], timeout=5))

    def test_real_eight_thread_writes_preserve_mirrors_metadata_and_exact_drop_accounting(self):
        result = self.run_case('concurrent').decode()
        self.assertRegex(result, r'^accepted=[1-9][0-9]* dropped=[0-9]+\n$')

    def test_reentry_and_stuck_foreign_owner_are_bounded_never_stolen_and_restore_daif(self):
        self.run_case('bounded')

    def test_boot_watchdog_and_seven_secondary_writers_share_one_owner(self):
        self.run_case('mixed')

    def test_spurious_owner_failures_exhaust_exact_budget_then_count_one_drop(self):
        self.run_case('spurious')

    def test_counter_failure_is_bounded_and_cannot_report_false_zero_or_wrap(self):
        self.run_case('uncertain')

    def test_real_arm64_hardware_helpers_compile_without_stub_replacement(self):
        if sys.platform != 'darwin':
            self.skipTest('Darwin SDK ARM64 compile smoke only')
        root = Path(self.temporary.name)
        path = root / 'native.c'
        path.write_text(PREFIX + '\n#define TEST_NEW 1\n' + BARRIER + bodies()[1] + SUFFIX)
        result = subprocess.run([shutil.which('clang') or 'cc', '-target', 'arm64-apple-macos',
                                 '-mcpu=cortex-a53', '-mno-outline-atomics',
                                 '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-Wno-unused-function', '-pthread', '-c', str(path),
                                 '-o', str(root / 'native.o')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_boot_cpu_zero_can_feed_reconfigure_or_cancel_watchdog_cap(self):
        self.run_case('watchdog')

    def test_initialization_publishes_both_rings_together_and_maps_without_owner_held(self):
        self.run_case('init')

    def test_mapping_failures_never_modify_or_publish_either_ring(self):
        for failure in ('1', '2'):
            with self.subTest(failure=failure):
                self.run_case('init', failure)

    def test_secondary_cannot_initialize_ring_or_watchdog(self):
        self.run_case('init', '0', '1')

    def test_corrupt_ring_is_skipped_without_writing_outside_its_capacity(self):
        self.run_case('corrupt')


if __name__ == '__main__':
    unittest.main()
