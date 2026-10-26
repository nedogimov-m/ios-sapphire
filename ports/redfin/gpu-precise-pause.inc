/* SPDX-License-Identifier: MIT */
/* Native short device waits. SYS_CRITICAL suppresses intentional timer
 * coalescing; it does not change thread priority or fabricate completion.
 * Keep XNU's early-boot/IRQ/preemption/platform spin decisions unchanged.
 * Internal callers request100us polls or1000us late-admission intervals. */
#include <kern/clock.h>
#include <kern/sched_prim.h>
#include <kern/spl.h>
#include <kern/thread.h>
#include <machine/machine_routines.h>
#include <arm/cpu_data.h>

void redfin_gpu_precise_pause(unsigned microseconds)
{
    uint64_t interval=0;
    clock_interval_to_absolutetime_interval(microseconds,NSEC_PER_USEC,&interval);
    if(!interval)return;
    uint64_t deadline=mach_absolute_time()+interval;
    if(ml_delay_should_spin(interval)||get_preemption_level()!=0||!ml_get_interrupts_enabled()) {
        machine_delay_until(interval,deadline);return;
    }
    wait_result_t result=assert_wait_deadline_with_leeway(
        (event_t)&redfin_gpu_precise_pause,THREAD_UNINT,TIMEOUT_URGENCY_SYS_CRITICAL,deadline,0);
    if(result==THREAD_WAITING)thread_block(THREAD_CONTINUE_NULL);
}
