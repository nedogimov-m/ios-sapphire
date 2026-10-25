/* SPDX-License-Identifier: MIT */
/* Preferred kernel 8e611870 MiniIOMobileFramebuffer presenter/helper model,
 * adapted to SweetSurface's separate state/pixels and Redfin's cutout fit.
 * No new MDP, SMMU, scanout or GPU-memory ownership is introduced. */
#include "RedfinDisplayPacing.h"

#define REDFIN_ROW_HELPERS 3u
struct redfin_presenter;
struct redfin_row_worker {
    struct redfin_presenter *pool;
    struct redfin_display_workspace *workspace;
    unsigned index;
};
struct redfin_row_job {
    struct redfin_display_surface surface;
    uint8_t *pixels;
    uint64_t length;
    uint32_t stride;
    int32_t source[4], destination[4];
};
struct redfin_presenter {
    AppleCLCD *owner;
    IOLock *lock, *pixelsLock;
    bool async, queued;
    unsigned slices, busy, successful;
    uint64_t generation, bytes, row_calls, row_time;
    struct redfin_row_worker workers[REDFIN_ROW_HELPERS];
    struct redfin_row_job rows;
    uint8_t record[SWEET_FB_SWAP_REC_SIZE];
    SweetSurface *held[4];
    uint64_t queued_at, calls, presenting, queue_wait, last_finished;
    uint64_t period, next_tick, skipped_ticks;
    uint32_t intervals[201];
};

bool
AppleCLCD::startRedfinPresenter(void)
{
    if (!fRedfinCopyOnly || !fRedfinFit.mode || !redfin_gui_selected()) return false;
    struct redfin_presenter *p = (struct redfin_presenter *)IOMallocZeroData(sizeof(*p));
    if (!p) return false;
    p->lock = IOLockAlloc(); p->pixelsLock = IOLockAlloc();
    if (!p->lock || !p->pixelsLock) {
        if (p->lock) IOLockFree(p->lock);
        if (p->pixelsLock) IOLockFree(p->pixelsLock);
        IOFreeData(p, sizeof(*p)); return false;
    }
    p->owner = this; p->slices = 1;
    nanoseconds_to_absolutetime((uint64_t)fRedfinVsyncUS * 1000, &p->period);
    fRedfinPresenter = p;
    for (unsigned i = 0; i < REDFIN_ROW_HELPERS; ++i) {
        struct redfin_row_worker *worker = &p->workers[i];
        worker->pool = p; worker->index = i + 1;
        worker->workspace = (struct redfin_display_workspace *)IOMallocData(sizeof(*worker->workspace));
        if (!worker->workspace) break;
        thread_t thread;
        retain();
        if (kernel_thread_start(&AppleCLCD::redfinRowsMain, worker, &thread) != KERN_SUCCESS) {
            release(); IOFreeData(worker->workspace, sizeof(*worker->workspace));
            worker->workspace = NULL; break;
        }
        ++p->slices;
        thread_set_thread_name(thread, "redfin display rows"); thread_deallocate(thread);
    }
    thread_t thread;
    retain();
    if (kernel_thread_start(&AppleCLCD::redfinPresentMain, this, &thread) == KERN_SUCCESS) {
        p->async = true;
        thread_set_thread_name(thread, "redfin display presenter"); thread_deallocate(thread);
    } else release();
    IOLog("REDFIN PRESENT START: async=%u row-workers=%u absolute-timer=1 CPU-fit=1\n", p->async, p->slices);
    return true;
}

void
AppleCLCD::freeRedfinPresenter(void)
{
    struct redfin_presenter *p = fRedfinPresenter;
    if (!p) return;
    /* Every successfully started thread retains this service until reset.
     * Only a pool with no started thread can reach normal service free. */
    assert(!p->async && p->slices == 1);
    IOLockFree(p->pixelsLock); IOLockFree(p->lock);
    IOFreeData(p, sizeof(*p)); fRedfinPresenter = NULL;
}

void
AppleCLCD::armRedfinVsync(IOTimerEventSource *sender)
{
    struct redfin_presenter *p = fRedfinPresenter;
    if (!p) { sender->setTimeoutUS(fRedfinVsyncUS); return; }
    uint64_t skipped = 0;
    uint64_t next = redfin_display_next_tick(p->next_tick, mach_absolute_time(), p->period, &skipped);
    if (!next) { sender->setTimeoutUS(fRedfinVsyncUS); return; }
    p->next_tick = next;
    __atomic_fetch_add(&p->skipped_ticks, skipped, __ATOMIC_RELAXED);
    sender->wakeAtTime(next);
}

bool
AppleCLCD::queueRedfinPresent(const uint8_t *record, SweetSurface **held)
{
    struct redfin_presenter *p = fRedfinPresenter;
    if (!p || !p->async) return false;
    /* Caller holds fLock: take the pending swap and its existing in-use
     * references together. A full slot leaves the newer pending swap intact. */
    IOLockLock(p->lock);
    if (p->queued) { IOLockUnlock(p->lock); return false; }
    memcpy(p->record, record, sizeof(p->record));
    memcpy(p->held, held, sizeof(p->held)); bzero(held, sizeof(p->held));
    p->queued_at = mach_absolute_time(); p->queued = true;
    IOLockWakeup(p->lock, &p->queued, true);
    IOLockUnlock(p->lock); return true;
}

void
AppleCLCD::redfinPresentMain(void *argument, wait_result_t result __unused)
{
    AppleCLCD *fb = (AppleCLCD *)argument;
    struct redfin_presenter *p = fb->fRedfinPresenter;
    for (;;) {
        uint8_t record[SWEET_FB_SWAP_REC_SIZE];
        SweetSurface *held[4], *old[4], *retired[4];
        uint64_t queued;
        IOLockLock(p->lock);
        while (!p->queued) IOLockSleep(p->lock, &p->queued, THREAD_UNINT);
        memcpy(record, p->record, sizeof(record));
        memcpy(held, p->held, sizeof(held)); bzero(p->held, sizeof(p->held));
        queued = p->queued_at; p->queued = false;
        IOLockUnlock(p->lock);
        IOLockLock(p->pixelsLock);
        IOLockLock(fb->fLock); bool off = fb->fPowerOff; IOLockUnlock(fb->fLock);
        if (off || !redfin_smp_verified()) {
            IOLockUnlock(p->pixelsLock); sweet_hold_set(held, false); continue;
        }
        uint64_t began = mach_absolute_time();
        fb->present(record);
        uint64_t finished = mach_absolute_time(), elapsed;
        IOLockUnlock(p->pixelsLock);
        /* Redfin copies into the preserved boot framebuffer. The panel never
         * DMA-fetches these source surfaces. Release the previous sources only
         * after this complete CPU copy and every row helper has finished. */
        IOLockLock(fb->fLock);
        memcpy(old, fb->fShowHold, sizeof(old)); memcpy(retired, fb->fRetireHold, sizeof(retired));
        memcpy(fb->fShowHold, held, sizeof(held)); bzero(fb->fRetireHold, sizeof(retired));
        IOLockUnlock(fb->fLock);
        sweet_hold_set(old, false); sweet_hold_set(retired, false);
        ++p->calls; p->presenting += finished - began; p->queue_wait += began - queued;
        if (p->last_finished && finished >= p->last_finished) {
            absolutetime_to_nanoseconds(finished - p->last_finished, &elapsed);
            uint64_t ms = elapsed / 1000000;
            if (ms <= 200) ++p->intervals[ms];
        }
        p->last_finished = finished;
        if (p->calls <= 4 || !(p->calls % 120)) {
            uint64_t total, wait, rows, last;
            absolutetime_to_nanoseconds(p->presenting, &total);
            absolutetime_to_nanoseconds(p->queue_wait, &wait);
            absolutetime_to_nanoseconds(p->row_time, &rows);
            absolutetime_to_nanoseconds(finished - began, &last);
            unsigned count = 0, under18 = 0, under35 = 0;
            for (unsigned ms = 0; ms <= 200; ++ms) {
                count += p->intervals[ms];
                if (ms < 18) under18 += p->intervals[ms];
                if (ms < 35) under35 += p->intervals[ms];
            }
            IOLog("REDFIN PRESENT TIMING: calls=%llu copy-us=%llu last-us=%llu queue-us=%llu row-us=%llu workers=%u intervals=%u under18=%u under35=%u skipped-ticks=%llu\n",
                p->calls, total / 1000 / p->calls, last / 1000, wait / 1000 / p->calls,
                p->row_calls ? rows / 1000 / p->row_calls : 0, p->slices, count, under18, under35,
                __atomic_load_n(&p->skipped_ticks, __ATOMIC_RELAXED));
        }
    }
}

void
AppleCLCD::redfinRowsMain(void *argument, wait_result_t result __unused)
{
    struct redfin_row_worker *worker = (struct redfin_row_worker *)argument;
    struct redfin_presenter *p = worker->pool;
    uint64_t done = 0;
    for (;;) {
        IOLockLock(p->lock);
        while (p->generation == done) IOLockSleep(p->lock, &p->generation, THREAD_UNINT);
        done = p->generation;
        IOLockUnlock(p->lock);
        const struct redfin_row_job *job = &p->rows;
        uint64_t bytes = 0;
        bool ok = redfin_smp_verified() && redfin_display_draw_slice(&p->owner->fRedfinFit,
            worker->workspace, job->pixels, job->length, job->stride, &job->surface,
            job->source, job->destination, worker->index, p->slices, &bytes);
        IOLockLock(p->lock);
        if (ok) p->successful |= 1u << worker->index;
        p->bytes += bytes;
        assert(p->busy != 0); --p->busy;
        if (!p->busy) IOLockWakeup(p->lock, &p->busy, true);
        IOLockUnlock(p->lock);
    }
}

bool
AppleCLCD::drawRedfinLayer(uint8_t *pixels, uint64_t length, uint32_t stride,
    const struct redfin_display_surface *surface, const int32_t *source,
    const int32_t *destination, uint64_t *copied)
{
    if (copied) *copied = 0;
    if (!surface || !source || !destination || !fRedfinFitWorkspace) return false;
    struct redfin_presenter *p = fRedfinPresenter;
    if (!p || p->slices == 1) return redfin_display_draw(&fRedfinFit, fRedfinFitWorkspace,
        pixels, length, stride, surface, source, destination, copied);
    if (!redfin_smp_verified()) return false;
    uint64_t began = mach_absolute_time();
    IOLockLock(p->lock);
    assert(!p->busy);
    p->rows.surface = *surface; p->rows.pixels = pixels; p->rows.length = length; p->rows.stride = stride;
    memcpy(p->rows.source, source, sizeof(p->rows.source));
    memcpy(p->rows.destination, destination, sizeof(p->rows.destination));
    p->successful = 0; p->bytes = 0; p->busy = p->slices - 1; ++p->generation;
    IOLockWakeup(p->lock, &p->generation, false);
    IOLockUnlock(p->lock);
    uint64_t bytes = 0;
    bool ok = redfin_display_draw_slice(&fRedfinFit, fRedfinFitWorkspace,
        pixels, length, stride, surface, source, destination, 0, p->slices, &bytes);
    IOLockLock(p->lock);
    if (ok) p->successful |= 1;
    p->bytes += bytes;
    /* The descriptor and job cannot be released or replaced before all CPU
     * helpers leave it. A timeout must never expose freed source pixels. */
    while (p->busy) IOLockSleep(p->lock, &p->busy, THREAD_UNINT);
    ok = p->successful == ((1u << p->slices) - 1);
    if (copied) *copied = p->bytes;
    IOLockUnlock(p->lock);
    ++p->row_calls; p->row_time += mach_absolute_time() - began;
    return ok;
}
