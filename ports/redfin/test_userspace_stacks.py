"""Host fault injection against actual resident-read/snapshot patch functions."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class UserspaceStacksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc:
            raise unittest.SkipTest('host compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        base = Path(cls.temporary.name)
        patch = Path(__file__).with_name('userspace-stacks.patch').read_text()
        added = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        def section(name):
            return added.split('/* '+name+'_BEGIN',1)[1].split('*/',1)[1].split('/* '+name+'_END */',1)[0]
        resident = section('REDFIN_STACK_RESIDENT_TEST')
        task = section('REDFIN_STACK_TASK_TEST')
        proc = section('REDFIN_STACK_PROC_TEST')
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#define PAGE_SIZE 4096ULL
#define PAGE_MASK (PAGE_SIZE-1)
#define MACH_VM_MAX_ADDRESS 0x1000000000ULL
#define PMAP_LOCK_SHARED 1
#define VM_WIMG_MASK 0xf
#define VM_WIMG_DEFAULT 0
#define NSEC_PER_SEC 1000ULL
#define TASK_NULL NULL
#define VM_MAP_NULL NULL
#define PROC_NULL NULL
#define atop(x) ((x)>>12)
typedef uintptr_t pmap_paddr_t;
typedef uintptr_t vm_offset_t;
typedef unsigned ppnum_t;
typedef struct pmap { int unused; } *pmap_t;
static struct pmap target_pmap,kernel_storage;
static pmap_t kernel_pmap=&kernel_storage;
struct map { pmap_t pmap; };
typedef struct map *vm_map_t;
typedef struct arm_saved_state { uint64_t pc,lr,sp,fp; } arm_saved_state_t;
typedef struct thread { struct thread *next; unsigned state; uint64_t wait_event;
    void (*continuation)(void); unsigned id; arm_saved_state_t regs; } *thread_t;
typedef struct task { int active; thread_t threads; vm_map_t map;
    uint32_t task_shared_region_slide; uint64_t mach_header_vm_address; } *task_t;
static struct task kernel_task_storage;
static task_t kernel_task=&kernel_task_storage;
typedef struct proc { struct proc *next; char p_comm[17]; int pid; task_t task; unsigned bits; } *proc_t;
static proc_t procs;
static int proc_list_mlock;
static int mode,locks,unlocks,copies,violations,preemption,taskrefs,maprefs,threadrefs,procrefs,proc_locked;
static uint64_t now,current_source;
static uint64_t *destination;
static char output[200000];
static size_t used;
static int capture_printf(const char *format,...) {
    if (locks || preemption || proc_locked) violations++;
    va_list ap; va_start(ap,format);
    int result=vsnprintf(output+used,sizeof(output)-used,format,ap); va_end(ap);
    if (result>0 && (size_t)result<sizeof(output)-used) used+=(size_t)result;
    return result;
}
#define printf capture_printf
static int pmap_try_lock(pmap_t pmap,int kind) {
    (void)pmap;(void)kind; if (mode==1) return 0; locks++;preemption++; return 1;
}
static void pmap_unlock(pmap_t pmap,int kind) { (void)pmap;(void)kind; locks--;preemption--;unlocks++; }
static pmap_paddr_t pmap_vtophys(pmap_t pmap,uint64_t addr) {
    (void)pmap; current_source=addr; return mode==2 ? 0 : 0x2000;
}
static pmap_paddr_t kvtophys(vm_offset_t address) { destination=(uint64_t *)address; return mode==3 ? 0 : 0x3000; }
static int pmap_valid_address(pmap_paddr_t address) {
    return !(mode==4 && address==0x2000) && !(mode==5 && address==0x3000);
}
static unsigned pmap_cache_attributes(ppnum_t page) {
    return (mode==6 && page==2) || (mode==7 && page==3) ? 1 : 0;
}
static void bcopy_phys(pmap_paddr_t source,pmap_paddr_t target,unsigned size) {
    if (source!=0x2000 || target!=0x3000 || size!=16 || locks!=1 || preemption!=1) violations++;
    copies++; destination[0]=mode==8 ? current_source : current_source+16;
    destination[1]=0x180001000ULL+copies;
}
static uint64_t mach_absolute_time(void) { if (mode==9) now+=500; return now; }
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *out) { *out=n; }
static void task_reference(task_t t) { (void)t;taskrefs++; }
static void task_deallocate(task_t t) { (void)t;taskrefs--; }
static int task_lock_try(task_t t) { (void)t;return mode!=10; }
static void task_unlock(task_t t) { (void)t; }
static vm_map_t get_task_map(task_t t) { return t->map; }
static void vm_map_reference(vm_map_t m) { (void)m;maprefs++; }
static void vm_map_deallocate(vm_map_t m) { (void)m;maprefs--; }
static pmap_t vm_map_pmap(vm_map_t m) { return m->pmap; }
static void thread_reference(thread_t t) { (void)t;threadrefs++; }
static void thread_deallocate(thread_t t) { (void)t;threadrefs--; }
#define queue_iterate(head,thread,type,link) for ((thread)=*(head);(thread);(thread)=(thread)->next)
static void disable_preemption(void) { preemption++; }
static void enable_preemption(void) { preemption--; }
static arm_saved_state_t *find_user_regs(thread_t t) { return mode==11 ? NULL : &t->regs; }
static int is_saved_state64(arm_saved_state_t *s) { (void)s;return 1; }
static uint64_t get_saved_state_pc(arm_saved_state_t *s) { return s->pc; }
static uint64_t get_saved_state_lr(arm_saved_state_t *s) { return s->lr; }
static uint64_t get_saved_state_sp(arm_saved_state_t *s) { return s->sp; }
static uint64_t get_saved_state_fp(arm_saved_state_t *s) { return s->fp; }
static uint64_t thread_tid(thread_t t) { return 100+t->id; }
static int PE_parse_boot_argn(const char *name,void *out,int size) {
    (void)size;
    *(uint32_t *)out=!strcmp(name,"cpus") ? (mode==22 ? 2 : 1) : (mode==21 ? 0 : 1);
    return mode!=20;
}
static int lck_mtx_try_lock(int *lock) { (void)lock;if (mode==23) return 0;proc_locked=1;return 1; }
static void proc_list_unlock(void) { proc_locked=0; }
#define ALLPROC_FOREACH(p) for ((p)=procs;(p);(p)=(p)->next)
static uint32_t proc_ref_try_fast(proc_t p) { if (!p->bits)return 0;procrefs++;return p->bits; }
static int proc_ref_needs_wait_for_exec(uint32_t bits) { return bits==2; }
static void proc_rele(proc_t p) { (void)p;procrefs--; }
static int proc_pid(proc_t p) { return p->pid; }
static task_t proc_task(proc_t p) { if (!procrefs)violations++;return p->task; }
'''
        suffix = r'''
static void reset(int m) {
    mode=m;locks=unlocks=copies=violations=preemption=taskrefs=maprefs=threadrefs=procrefs=proc_locked=0;
    now=100000;used=0;output[0]=0;
}
int test_read(int m,uint64_t source,int kernel,int unaligned) {
    reset(m); uint64_t frame[4] __attribute__((aligned(16)))={0};
    int result=redfin_user_frame_read(kernel ? kernel_pmap : &target_pmap,source,frame+unaligned);
    if (locks || preemption || violations) return -99;
    return result*100+copies*10+unlocks;
}
const char *test_snapshot(int m,unsigned count,int with_proc) {
    reset(m); static struct thread threads[40]; static struct map map={&target_pmap};
    static struct task task; memset(threads,0,sizeof(threads));
    for (unsigned i=0;i<count && i<40;i++) {
        threads[i].id=i;threads[i].next=i+1<count ? &threads[i+1] : NULL;
        threads[i].state=2;threads[i].wait_event=0xabcdef;threads[i].regs.pc=0x180001000;
        threads[i].regs.lr=0x180002000;threads[i].regs.sp=0x100000;threads[i].regs.fp=0x1000+i*0x10000;
    }
    task=(struct task){1,count ? threads : NULL,&map,0x30000000,0x100000000};
    if (with_proc) {
        static struct proc processes[3];memset(processes,0,sizeof(processes));
        const char *names[]={"SpringBoard","backboardd","launchd"};
        for (unsigned i=0;i<3;i++) {
            strcpy(processes[i].p_comm,names[i]);processes[i].pid=26+i;
            processes[i].task=&task;processes[i].bits=mode==24 ? 2 : 1;
            processes[i].next=i<2 ? &processes[i+1] : NULL;
        }
        procs=processes;redfin_userspace_stacks();
    } else redfin_stack_task("SpringBoard",26,&task,102000);
    return output;
}
int test_balanced(void) { return !(locks || preemption || taskrefs || maprefs || threadrefs || procrefs || proc_locked || violations); }
int test_copies(void) { return copies; }
'''
        source = base/'snapshot.c'
        source.write_text(prefix + resident + task + proc + suffix)
        library = base/'snapshot.so'
        result = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                                 str(source), '-o', str(library)], capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode())
        cls.library = ctypes.CDLL(str(library))
        cls.library.test_read.argtypes = [ctypes.c_int,ctypes.c_uint64,ctypes.c_int,ctypes.c_int]
        cls.library.test_snapshot.argtypes = [ctypes.c_int,ctypes.c_uint,ctypes.c_int]
        cls.library.test_snapshot.restype = ctypes.c_char_p

    def test_resident_frame_requires_lock_normal_memory_and_default_cache(self):
        self.assertEqual(self.library.test_read(0,0x1000,0,0),111)
        for mode in range(1,8):
            result = self.library.test_read(mode,0x1000,0,0)
            self.assertEqual(result,0 if mode==1 else 1)
        for address,kernel,unaligned in ((0,0,0),(0x1008,0,0),(0x1000000000,0,0),
                                         (0x1000,1,0),(0x1000,0,1)):
            self.assertEqual(self.library.test_read(0,address,kernel,unaligned),0)

    def test_snapshot_has_real_slide_registers_and_bounded_ordered_frames(self):
        log = self.library.test_snapshot(0,40,0).decode()
        self.assertIn('slide=0x30000000 slide_valid=1',log)
        self.assertEqual(log.count('RSTACK THREAD'),16)
        self.assertEqual(log.count('RSTACK FRAME'),16*8)
        self.assertIn('index=0 fp=0x1000 lr=0x180001001 next_fp=0x1010',log)
        self.assertIn('pc=0x180001000 lr=0x180002000',log)
        self.assertEqual(self.library.test_balanced(),1)

    def test_busy_nonresident_bad_chain_and_budget_release_every_reference(self):
        for mode,stop in ((1,'unmapped-or-busy'),(2,'unmapped-or-busy'),(8,'invalid-fp'),
                          (9,'budget'),(10,'task-busy'),(11,'end')):
            with self.subTest(mode=mode):
                log = self.library.test_snapshot(mode,16,0).decode()
                self.assertIn(stop,log)
                self.assertEqual(self.library.test_balanced(),1)
                if mode in (1,2,10,11):
                    self.assertEqual(self.library.test_copies(),0)
                if mode==8:
                    self.assertEqual(log.count('RSTACK FRAME'),16)

    def test_default_off_up_gate_exec_skip_and_three_fixed_targets(self):
        for mode in (20,21,22):
            self.assertEqual(self.library.test_snapshot(mode,1,1),b'')
            self.assertEqual(self.library.test_balanced(),1)
        for mode in (23,24):
            log=self.library.test_snapshot(mode,1,1).decode()
            self.assertNotIn('RSTACK TASK',log)
            self.assertEqual(self.library.test_balanced(),1)
        log=self.library.test_snapshot(0,1,1).decode()
        self.assertEqual(log.count('RSTACK TASK'),3)
        for name in ('SpringBoard','backboardd','launchd'):
            self.assertIn('TASK name='+name,log)
        self.assertEqual(self.library.test_balanced(),1)


if __name__ == '__main__':
    unittest.main()
