/* GUI8 starts hardware work only after the complete SMP proof and publication.
 * IRQ/HID callers use cached acquire loads, never the CPU0-only return verifier.
 * Included by redfin_smp.c after its proof and frozen-argument primitives. */
#ifndef REDFIN_GUI_RUNTIME_H
#define REDFIN_GUI_RUNTIME_H
extern int redfin_gui_publish_return(void);
int redfin_gui_selected(void);
int redfin_smp_verified(void);
int redfin_gui_ready(void);
int redfin_gui_cpu0(void);
int redfin_gui_bind_worker(void);
void *redfin_gui_worker_enter(void);
void redfin_gui_worker_leave(void *);
void redfin_smp_publish(void);
void *redfin_gui_root_enter(void);
void redfin_gui_root_leave(void *);

int redfin_gui_selected(void)
{ return __atomic_load_n(&rf_gui_selected,__ATOMIC_ACQUIRE)==1; }
int redfin_smp_verified(void)
{ return __atomic_load_n(&rf_smp_published,__ATOMIC_ACQUIRE)==1; }
int redfin_gui_ready(void)
{ return __atomic_load_n(&rf_gui_ready,__ATOMIC_ACQUIRE)==1; }
int redfin_gui_cpu0(void)
{ return redfin_gui_ready() && rf_smp_local()==0; }

void redfin_smp_publish(void)
{
 if(!__atomic_load_n(&rf_smp_proved,__ATOMIC_ACQUIRE) || !rf_smp_unchanged())
  panic("REDFIN GUI: SMP publication before successful proof");
 __atomic_store_n(&rf_smp_published,1,__ATOMIC_RELEASE);
}
static void rf_gui_wait(void)
{
 uint64_t wake;
 clock_interval_to_deadline(1,NSEC_PER_MSEC,&wake);
 if(assert_wait_deadline((event_t)&rf_smp_published,THREAD_UNINT,wake)==THREAD_WAITING)
  thread_block(THREAD_CONTINUE_NULL);
}
void *redfin_gui_root_enter(void)
{
 /* Root matching can reach this before the asynchronous CPU nubs start. */
 (void)redfin_smp_mode();
 if(!redfin_gui_selected()) return NULL;
 uint64_t deadline;
 nanoseconds_to_deadline(15*NSEC_PER_SEC,&deadline);
 while(!redfin_smp_verified()) {
  if(mach_absolute_time()>deadline) panic("REDFIN GUI: SMP completion timeout");
  rf_gui_wait();
 }
 processor_t previous=thread_bind(cpu_to_processor(0));
 thread_block(THREAD_CONTINUE_NULL);
 uint64_t nonce=0;
 if(rf_smp_count()!=8 || !rf_smp_unchanged() ||
    !redfin_gui_profile(rf_smp_frozen,rf_smp_frozen_bytes,&nonce) || nonce!=rf_smp_boot_id ||
    redfin_gui_publish_return()!=1) panic("REDFIN GUI: cached shim return unavailable");
 __atomic_store_n(&rf_gui_ready,1,__ATOMIC_RELEASE);
 kprintf("REDFIN GUI8: SMP verified; CPU0 owns root/touch; shim return cached\n");
 return (void *)previous;
}
void redfin_gui_root_leave(void *previous)
{
 if(!redfin_gui_selected()) return;
 if(!redfin_gui_cpu0()) panic("REDFIN GUI: root hardware owner changed");
 thread_bind((processor_t)previous);
 thread_block(THREAD_CONTINUE_NULL);
}
int redfin_gui_bind_worker(void)
{
 if(!redfin_gui_selected() || !redfin_gui_ready()) return 0;
 thread_bind(cpu_to_processor(0));
 thread_block(THREAD_CONTINUE_NULL);
 return redfin_gui_cpu0();
}
/* Save and restore the caller's affinity for synchronous IOKit transactions.
 * Scheduler-private declarations stay in osfmk, rather than the BSD adapter. */
void *redfin_gui_worker_enter(void)
{
 processor_t previous=thread_bind(cpu_to_processor(0));
 /* Binding to the processor we already run on needs no voluntary switch. */
 if(rf_smp_local()!=0) thread_block(THREAD_CONTINUE_NULL);
 return (void *)previous;
}
void redfin_gui_worker_leave(void *previous)
{
 /* An unbound thread can keep running here. Only a restored binding to a
  * different processor requires immediate migration before returning. */
 thread_bind((processor_t)previous);
 if(previous && previous!=(void *)cpu_to_processor(0)) thread_block(THREAD_CONTINUE_NULL);
}
#endif /* REDFIN_GUI_RUNTIME_H */
