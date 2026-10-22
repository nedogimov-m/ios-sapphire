/* Included after the shared SMP primitives. All eight physical cores have
 * independent EL1/16K proof. CPU0 serializes the star exchange, so every
 * mailbox has one sender at a time. No device, storage or GPU operations. */
#ifndef REDFIN_SMP_EIGHT_H
#define REDFIN_SMP_EIGHT_H
static uint32_t rf_eight_started[8],rf_eight_turn;
static uint64_t rf_eight_replies[8];

static int rf_smp_start_eight(unsigned logical,vm_offset_t entry)
{
 if(logical<1 || logical>=8) return -200;
 bool owned=false;
 for(unsigned attempt=0;attempt<256;attempt++) {
  uint32_t expected=0;
  if(__atomic_compare_exchange_n(&rf_eight_started[logical],&expected,1,true,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) {
   owned=true;break;
  }
  if(expected) return -201;
 }
 if(!owned || rf_smp_count()!=8 || !__atomic_load_n(&rf_smp_prepared,__ATOMIC_ACQUIRE) ||
    !rf_smp_unchanged() || entry<0x180000000ULL || entry>=0x200000000ULL ||
    (entry&3) || !rf_smp_entry_ok(entry)) return -202;
 uint64_t target=(uint64_t)logical<<8;
 int32_t version=rf_smp_psci(0x84000000u,0,0,0);
 if(((uint32_t)version>>16)!=1 || ((uint32_t)version&0xffff)<1 ||
    rf_smp_psci(0x8400000au,RF_SMP_ON,0,0)!=0 ||
    rf_smp_psci(0x8400000au,RF_SMP_AFFINITY,0,0)!=0 ||
    rf_smp_psci(RF_SMP_AFFINITY,target,0,0)!=1) return -203;
 if(redfin_smp_return_ready()!=1 || !rf_smp_unchanged()) return -204;
 rf_smp_barrier();
 int32_t result=rf_smp_psci(RF_SMP_ON,target,entry,logical);
 if(!result) __atomic_store_n(&rf_eight_started[logical],2,__ATOMIC_RELEASE);
 return result;
}

static void rf_smp_irq_eight(unsigned kind,uint32_t phase,unsigned cpu)
{
 if(cpu>=8) { __atomic_store_n(&rf_smp_fault,1,__ATOMIC_RELEASE);return; }
 if(phase==RF_SMP_DRAIN) {
  if(kind==1) __atomic_store_n(&rf_smp_drained[cpu],1,__ATOMIC_RELEASE);
  return;
 }
 if(kind==0) {
  uint64_t n=__atomic_load_n(&rf_smp_timers[cpu],__ATOMIC_RELAXED);
  if(n==UINT64_MAX) __atomic_store_n(&rf_smp_fault,1,__ATOMIC_RELEASE);
  else __atomic_store_n(&rf_smp_timers[cpu],n+1,__ATOMIC_RELEASE);
 } else if(kind==1) {
  uint64_t n=__atomic_load_n(&rf_smp_request[cpu],__ATOMIC_ACQUIRE);
  uint64_t previous=__atomic_load_n(&rf_smp_ack[cpu],__ATOMIC_RELAXED);
  unsigned turn=__atomic_load_n(&rf_eight_turn,__ATOMIC_ACQUIRE);
  uint64_t round=n>>4,origin=n&15;
  bool cross=turn>=1 && turn<8 && round>(turn-1)*RF_SMP_ROUNDS && round<=turn*RF_SMP_ROUNDS &&
   (cpu==0?origin==(uint64_t)turn+1:(turn==cpu && origin==1));
  if((n==1 || cross) && n>previous) __atomic_store_n(&rf_smp_ack[cpu],n,__ATOMIC_RELEASE);
 }
}

static void rf_smp_eight_worker(void *arg,wait_result_t result __unused)
{
 unsigned cpu=(unsigned)(uintptr_t)arg;
 bool ok=cpu>=1 && cpu<8;
 if(ok) {
  thread_bind(cpu_to_processor(cpu));thread_block(THREAD_CONTINUE_NULL);
  ok=rf_smp_alive(cpu);
 }
 if(ok) {
  __atomic_store_n(&rf_smp_request[cpu],1,__ATOMIC_RELEASE);rf_smp_send(cpu);
  ok=rf_smp_wait64(&rf_smp_ack[cpu],1,cpu);
 }
 if(ok) {
  __atomic_store_n(&rf_smp_ready[cpu],1,__ATOMIC_RELEASE);
  ok=rf_smp_wait32(&rf_eight_turn,cpu,cpu);
 }
 for(unsigned round=1;ok && round<=RF_SMP_ROUNDS;round++) {
  uint64_t serial=(cpu-1)*RF_SMP_ROUNDS+round;
  uint64_t request=(serial<<4)|1;
  if(!rf_smp_wait64(&rf_smp_ack[cpu],request,cpu)) { ok=false;break; }
  uint64_t reply=(serial<<4)|(cpu+1);
  __atomic_store_n(&rf_smp_request[0],reply,__ATOMIC_RELEASE);rf_smp_send(0);
  if(!rf_smp_wait64(&rf_smp_ack[0],reply,cpu)) { ok=false;break; }
  rf_smp_round_delay();
  if(!rf_smp_alive(cpu)) { ok=false;break; }
  __atomic_store_n(&rf_smp_progress[cpu],round,__ATOMIC_RELEASE);
 }
 if(ok) __atomic_store_n(&rf_smp_finished[cpu],1,__ATOMIC_RELEASE);
 else __atomic_store_n(&rf_smp_fault,1,__ATOMIC_RELEASE);
 thread_terminate(current_thread());
}

static int rf_smp_prove_eight(void)
{
 if(rf_smp_count()!=8 || !rf_smp_unchanged() ||
    __atomic_load_n(&rf_smp_phase,__ATOMIC_ACQUIRE)!=RF_SMP_IDLE) return -210;
 for(unsigned cpu=1;cpu<8;cpu++)
  if(__atomic_load_n(&rf_eight_started[cpu],__ATOMIC_ACQUIRE)!=2) return -211;
 thread_t workers[8]={THREAD_NULL};
 int error=-212;
 nanoseconds_to_deadline(5*NSEC_PER_SEC,&rf_smp_deadline);
 __atomic_store_n(&rf_smp_phase,RF_SMP_ACTIVE,__ATOMIC_RELEASE);
 __atomic_store_n(&rf_smp_request[0],1,__ATOMIC_RELEASE);rf_smp_send(0);
 if(!rf_smp_wait64(&rf_smp_ack[0],1,0)) goto fail;
 __atomic_store_n(&rf_smp_ready[0],1,__ATOMIC_RELEASE);
 for(unsigned cpu=1;cpu<8;cpu++) {
  if(kernel_thread_start(rf_smp_eight_worker,(void *)(uintptr_t)cpu,&workers[cpu])!=KERN_SUCCESS) {
   error=-213;goto fail;
  }
 }
 for(unsigned cpu=1;cpu<8;cpu++) {
  if(!rf_smp_wait32(&rf_smp_ready[cpu],1,0)) { error=-214;goto fail; }
 }
 for(unsigned cpu=1;cpu<8;cpu++) {
  __atomic_store_n(&rf_eight_turn,cpu,__ATOMIC_RELEASE);
  for(unsigned round=1;round<=RF_SMP_ROUNDS;round++) {
   uint64_t serial=(cpu-1)*RF_SMP_ROUNDS+round;
   uint64_t request=(serial<<4)|1,reply=(serial<<4)|(cpu+1);
   __atomic_store_n(&rf_smp_request[cpu],request,__ATOMIC_RELEASE);rf_smp_send(cpu);
   if(!rf_smp_wait64(&rf_smp_ack[cpu],request,0) || !rf_smp_wait64(&rf_smp_ack[0],reply,0) ||
      !rf_smp_wait64(&rf_smp_progress[cpu],round,0)) { error=-215;goto fail; }
   rf_eight_replies[cpu]=__atomic_load_n(&rf_smp_ack[0],__ATOMIC_ACQUIRE);
   __atomic_store_n(&rf_smp_progress[0],(cpu-1)*RF_SMP_ROUNDS+round,__ATOMIC_RELEASE);
  }
  if(!rf_smp_wait32(&rf_smp_finished[cpu],1,0)) { error=-216;goto fail; }
 }
 for(unsigned cpu=1;cpu<8;cpu++) {
  bool exited=false;
  for(unsigned poll=0;poll<RF_SMP_POLLS;poll++) {
   if(!rf_smp_alive(0)) break;
   if(!thread_is_active(workers[cpu])) { exited=true;break; }
   rf_smp_pause();
  }
  if(!exited) { error=-217;goto fail; }
  thread_deallocate(workers[cpu]);workers[cpu]=THREAD_NULL;
 }
 __atomic_store_n(&rf_smp_phase,RF_SMP_DRAIN,__ATOMIC_RELEASE);
 for(unsigned cpu=0;cpu<8;cpu++) rf_smp_send(cpu);
 for(unsigned cpu=0;cpu<8;cpu++) {
  if(!rf_smp_wait32(&rf_smp_drained[cpu],1,0)) { error=-218;goto fail; }
 }
 __atomic_store_n(&rf_smp_phase,RF_SMP_DONE,__ATOMIC_RELEASE);
 if(__atomic_load_n(&rf_smp_fault,__ATOMIC_ACQUIRE)) { error=-219;goto fail; }
 for(unsigned cpu=0;cpu<8;cpu++) {
  uint64_t expected=cpu?RF_SMP_ROUNDS:7*RF_SMP_ROUNDS;
  if(__atomic_load_n(&rf_smp_timers[cpu],__ATOMIC_ACQUIRE)<2 ||
     __atomic_load_n(&rf_smp_progress[cpu],__ATOMIC_ACQUIRE)!=expected ||
     __atomic_load_n(&rf_smp_ready[cpu],__ATOMIC_ACQUIRE)!=1 ||
     (cpu && (__atomic_load_n(&rf_smp_ack[cpu],__ATOMIC_ACQUIRE)!=((cpu*RF_SMP_ROUNDS<<4)|1) ||
              rf_eight_replies[cpu]!=((cpu*RF_SMP_ROUNDS<<4)|(cpu+1))))) { error=-220;goto fail; }
 }
 if(redfin_log_smp_quiescent()!=1) { error=-221;goto fail; }
 rf_smp_pause();
 if(redfin_log_smp_quiescent()!=1 || !rf_smp_unchanged()) { error=-222;goto fail; }
 for(unsigned cpu=0;cpu<8;cpu++)
  kprintf("REDFIN SMP8: bootid=%#llx cpu=%u mpidr=%#x timer=%llu progress=%llu self=%u cross_ack=%llu reply=%llu log_busy=0 log_reentrant=0 workers_exited=1 irq_drained=1 tlb=untested\n",
   rf_smp_boot_id,cpu,cpu<<8,__atomic_load_n(&rf_smp_timers[cpu],__ATOMIC_ACQUIRE),
   __atomic_load_n(&rf_smp_progress[cpu],__ATOMIC_ACQUIRE),
   __atomic_load_n(&rf_smp_ready[cpu],__ATOMIC_ACQUIRE),
   __atomic_load_n(&rf_smp_ack[cpu],__ATOMIC_ACQUIRE),rf_eight_replies[cpu]);
 return 0;
fail:
 __atomic_store_n(&rf_smp_fault,1,__ATOMIC_RELEASE);
 for(unsigned cpu=1;cpu<8;cpu++) if(workers[cpu]!=THREAD_NULL) thread_deallocate(workers[cpu]);
 return error;
}
#endif /* REDFIN_SMP_EIGHT_H */
