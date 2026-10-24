/* Opt-in GUI8 diagnostics: inspect only nonrunnable waiting threads.
 * Hold the scheduler lock while copying their PCB and resident frames;
 * never print, allocate, fault or wait for another lock in that section.
 */
#define REDFIN_WAIT_FRAMES 16

/* REDFIN_WAIT_COPY_TEST_BEGIN */
struct redfin_wait_copy {
    uint64_t pc, lr, sp, fp, wait, continuation, callers[REDFIN_WAIT_FRAMES];
    unsigned state, frames, stop;
};

static bool
redfin_wait_copy(thread_t thread, vm_map_t map, uint64_t deadline,
                 struct redfin_wait_copy *out)
{
    bzero(out, sizeof(*out));
    out->stop = 1;
    if (map == VM_MAP_NULL || mach_absolute_time() >= deadline) return false;
    spl_t level = splsched();
    if (!simple_lock_try(&thread->sched_lock, &thread_lck_grp)) {
        splx(level);
        return false;
    }
    bool valid = false;
    out->state = thread->state;
    out->stop = 2;
    if (!(out->state & TH_WAIT) ||
        (out->state & (TH_RUN | TH_WAKING | TH_TERMINATE | TH_TERMINATE2))) goto done;
    out->wait = thread->wait_event;
    out->continuation = (uint64_t)(uintptr_t)thread->continuation;
    arm_saved_state_t *ss = find_user_regs(thread);
    out->stop = 3;
    if (!ss || !is_saved_state64(ss)) goto done;
    out->pc = get_saved_state_pc(ss); out->lr = get_saved_state_lr(ss);
    out->sp = get_saved_state_sp(ss); out->fp = get_saved_state_fp(ss);
    valid = true;
    uint64_t fp = out->fp, base = fp;
    out->stop = 0;
    while (fp && out->frames < REDFIN_WAIT_FRAMES) {
        if (mach_absolute_time() >= deadline) { out->stop = 4; break; }
        if ((fp & 15) || fp < base || fp - base > (8ULL << 20)) { out->stop = 5; break; }
        uint64_t frame[2] __attribute__((aligned(16)));
        if (!redfin_user_frame_read(vm_map_pmap(map), fp, frame)) { out->stop = 6; break; }
        out->callers[out->frames++] = frame[1];
        if (frame[0] && (frame[0] <= fp || frame[0] - fp > (1ULL << 20))) { out->stop = 5; break; }
        fp = frame[0];
    }
    if (fp && out->frames == REDFIN_WAIT_FRAMES) out->stop = 7;
done:
    thread_unlock(thread);
    splx(level);
    return valid;
}
/* REDFIN_WAIT_COPY_TEST_END */

void redfin_wait_task(const char *name, int pid, task_t task, uint64_t deadline);
void
redfin_wait_task(const char *name, int pid, task_t task, uint64_t deadline)
{
    thread_t threads[16];
    unsigned count = 0;
    vm_map_t map = VM_MAP_NULL;
    if (task == TASK_NULL || task == kernel_task || mach_absolute_time() >= deadline) return;
    task_reference(task);
    if (!task_lock_try(task)) { task_deallocate(task); return; }
    uint64_t slide = task->task_shared_region_slide, mh = task->mach_header_vm_address;
    if (task->active && (map = get_task_map(task)) != VM_MAP_NULL) {
        vm_map_reference(map);
        thread_t thread;
        queue_iterate(&task->threads, thread, thread_t, task_threads) {
            if (count == 16) break;
            thread_reference(thread);
            threads[count++] = thread;
        }
    }
    task_unlock(task);
    printf("RWSTACK TASK name=%s pid=%d slide=0x%llx mh=0x%llx threads=%u\n", name, pid, slide, mh, count);
    for (unsigned t = 0; t < count && mach_absolute_time() < deadline; ++t) {
        struct redfin_wait_copy copy;
        bool valid = redfin_wait_copy(threads[t], map, deadline, &copy);
        uint64_t tid = thread_tid(threads[t]);
        if (!valid) {
            printf("RWSTACK SKIP name=%s pid=%d tid=0x%llx state=0x%x reason=%u\n", name, pid, tid, copy.state, copy.stop);
            continue;
        }
        printf("RWSTACK THREAD name=%s pid=%d tid=0x%llx state=0x%x wait=0x%llx continuation=0x%llx pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx frames=%u stop=%u\n",
               name, pid, tid, copy.state, copy.wait, copy.continuation, copy.pc, copy.lr, copy.sp, copy.fp, copy.frames, copy.stop);
        for (unsigned i = 0; i < copy.frames; ++i)
            printf("RWSTACK FRAME name=%s pid=%d tid=0x%llx index=%u lr=0x%llx\n", name, pid, tid, i, copy.callers[i]);
    }
    for (unsigned t = 0; t < count; ++t) thread_deallocate(threads[t]);
    if (map != VM_MAP_NULL) vm_map_deallocate(map);
    task_deallocate(task);
}
