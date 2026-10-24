"""Execute the actual SMP wait-copy code against scheduler/resident-read faults."""
import ctypes
from pathlib import Path
import tempfile
import unittest

from test_smp_gui import compile_shared, patched_source

HERE = Path(__file__).resolve().parent


class WaitingThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        source = (HERE / 'userspace_waits_task.inc').read_text()
        body = source.split('/* REDFIN_WAIT_COPY_TEST_BEGIN */')[1].split('/* REDFIN_WAIT_COPY_TEST_END */')[0]
        prefix = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define REDFIN_WAIT_FRAMES 16
#define VM_MAP_NULL NULL
#define TH_WAIT 1
#define TH_RUN 4
#define TH_WAKING 256
#define TH_TERMINATE 16
#define TH_TERMINATE2 32
#undef bzero
#define bzero(p,n) memset(p,0,n)
typedef int spl_t;
typedef struct {uint64_t pc,lr,sp,fp;} arm_saved_state_t;
struct thread {int sched_lock;unsigned state;uint64_t wait_event;void *continuation;arm_saved_state_t regs;};
typedef struct thread *thread_t;
typedef void *vm_map_t;
static int thread_lck_grp,mode,irq,held,reads,violations;
static unsigned saved_state;
static uint64_t now;
static uint64_t mach_absolute_time(void){if(mode==10)now+=100;return now;}
static spl_t splsched(void){if(irq)violations++;irq=1;return 0;}
static void splx(spl_t level){(void)level;if(held || !irq)violations++;irq=0;}
static int simple_lock_try(int *lock,int *group){(void)lock;(void)group;
 if(!irq || held)violations++;if(mode==1)return 0;held=1;return 1;}
static void thread_unlock(thread_t t){if(!held || !irq || t->state!=saved_state)violations++;held=0;}
static arm_saved_state_t *find_user_regs(thread_t t){if(!held || !irq)violations++;return mode==5?NULL:&t->regs;}
static int is_saved_state64(arm_saved_state_t *ss){(void)ss;return mode!=6;}
static uint64_t get_saved_state_pc(arm_saved_state_t *s){return s->pc;}
static uint64_t get_saved_state_lr(arm_saved_state_t *s){return s->lr;}
static uint64_t get_saved_state_sp(arm_saved_state_t *s){return s->sp;}
static uint64_t get_saved_state_fp(arm_saved_state_t *s){return s->fp;}
static void *vm_map_pmap(vm_map_t map){return map;}
static int redfin_user_frame_read(void *pmap,uint64_t fp,uint64_t frame[2]){
 if(!pmap || !held || !irq || ((uintptr_t)frame&15))violations++;
 reads++;if(mode==7)return 0;
 frame[0]=mode==9?fp:fp+16;frame[1]=0x180001000+reads;return 1;
}
'''
        suffix = r'''
int run_wait_copy(int issue,unsigned state,int null_map,int expired){
 mode=issue;irq=held=reads=violations=0;now=0;saved_state=state;
 struct thread thread={.state=state,.regs={.pc=0x180010000,.lr=0x180020000,.sp=0x1000,
  .fp=issue==8?0x1008:issue==11?0:0x1000}};
 struct redfin_wait_copy out;
 int ok=redfin_wait_copy(&thread,null_map?NULL:(void*)1,expired?0:1000,&out);
 if(irq || held || violations || out.frames>16)return -999;
 return ok*10000+out.frames*100+out.stop;
}
int frames_read(void){return reads;}
'''
        cls.lib = compile_shared(Path(cls.temporary.name), prefix + body + suffix, 'waitcopy')
        cls.lib.run_wait_copy.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_int]

    def test_waiting_thread_is_unchanged_and_frame_walk_is_capped(self):
        self.assertEqual(self.lib.run_wait_copy(0, 1, 0, 0), 11607)
        self.assertEqual(self.lib.frames_read(), 16)
        self.assertEqual(self.lib.run_wait_copy(11, 1, 0, 0), 10000)

    def test_running_waking_and_terminating_threads_are_never_read(self):
        for state in (0, 4, 5, 257, 17, 33):
            self.assertEqual(self.lib.run_wait_copy(0, state, 0, 0), 2)
            self.assertEqual(self.lib.frames_read(), 0)

    def test_busy_scheduler_invalid_saved_state_and_unmapped_frames_release_locks(self):
        for issue, expected in ((1, 1), (5, 3), (6, 3), (7, 10006), (8, 10005), (9, 10105)):
            self.assertEqual(self.lib.run_wait_copy(issue, 1, 0, 0), expected)
        self.assertEqual(self.lib.run_wait_copy(0, 1, 1, 0), 1)
        self.assertEqual(self.lib.run_wait_copy(0, 1, 0, 1), 1)

    def test_deadline_stops_copying_with_scheduler_and_interrupt_state_restored(self):
        result = self.lib.run_wait_copy(10, 1, 0, 0)
        self.assertGreaterEqual(result, 10004)
        self.assertLess(result, 11604)
        self.assertEqual(result % 100, 4)

    def test_committed_overlay_contains_exact_task_and_process_implementations(self):
        for source, destination in [('userspace_waits_task.inc', 'osfmk/kern/redfin_userspace_waits_task.inc'),
                                    ('userspace_waits_proc.inc', 'bsd/kern/redfin_userspace_waits_proc.inc')]:
            self.assertEqual((HERE / source).read_text(), patched_source(destination))


if __name__ == '__main__':
    unittest.main()
