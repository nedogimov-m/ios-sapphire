/* Opt-in pre-loader Redfin return wrapper. Inclusion does not call it.
 * Call only after successful live redfin_fdt(), before payload/ADT checks,
 * with all other CPUs parked. The caller handles errors; no reset or watchdog
 * operation is performed here. Enable the call only after protected-UP proof
 * of this exact shared early-return.h leaf. No kernel cpus guard is changed.
 */
#ifndef REDFIN_SHIM_RETURN_H
#define REDFIN_SHIM_RETURN_H
#include "fdt.h"
#include "early-return.h"

enum { REDFIN_SHIM_ER_BUSY=8 };
enum redfin_shim_er_stage {
 REDFIN_SHIM_ER_RUNTIME, REDFIN_SHIM_ER_CLOCK, REDFIN_SHIM_ER_FIND,
 REDFIN_SHIM_ER_ARM, REDFIN_SHIM_ER_DONE
};
struct redfin_shim_er_report {
 unsigned stage;
 int error;
 struct redfin_er_target target;
 struct redfin_er_report leaf;
};
/* No exclusives against Device memory with the MMU off. Runtime checks admit
 * only CPU0 with local exceptions masked; other CPUs are parked by entry. */
static unsigned redfin_shim_er_attempted;

/* REDFIN_SHIM_RETURN_HW_BEGIN */
static inline uint64_t redfin_shim_er_mpidr(void)
{ uint64_t n; __asm__ volatile("mrs %0, mpidr_el1" : "=r"(n) :: "memory"); return n; }
static inline uint64_t redfin_shim_er_el(void)
{ uint64_t n; __asm__ volatile("mrs %0, CurrentEL" : "=r"(n) :: "memory"); return n; }
static inline uint64_t redfin_shim_er_sctlr(void)
{ uint64_t n; __asm__ volatile("mrs %0, sctlr_el1" : "=r"(n) :: "memory"); return n; }
static inline uint64_t redfin_shim_er_daif(void)
{ uint64_t n; __asm__ volatile("mrs %0, daif" : "=r"(n) :: "memory"); return n; }
/* REDFIN_SHIM_RETURN_HW_END */

static inline int
redfin_shim_prearm(const struct hardware *hw,struct redfin_shim_er_report *report)
{
 if(!report) return REDFIN_ER_INVALID;
 report->stage=REDFIN_SHIM_ER_RUNTIME;
 report->error=REDFIN_ER_INVALID;
 if(!hw || hw->redfin!=1 || hw->psci_smc!=1 || redfin_shim_er_el()!=4 ||
    (redfin_shim_er_mpidr()&0xff00ffffffULL) || (redfin_shim_er_sctlr()&5) ||
    (redfin_shim_er_daif()&0x3c0)!=0x3c0) return report->error;
 /* A rejected CPU/runtime never touches the one-shot owner or any MMIO.
  * Once the validated CPU0 consumes it, every failure is final. */
 if(redfin_shim_er_attempted) { report->error=REDFIN_SHIM_ER_BUSY; return report->error; }
 redfin_shim_er_attempted=1;
 report->target.version=report->target.mapping=0;
 report->target.apid=512; report->target.owner=0xff;
 report->leaf.stage=REDFIN_ER_PREFLIGHT;
 report->leaf.subtype=report->leaf.before=report->leaf.intended=report->leaf.after=0;
 report->leaf.imem=0; report->leaf.pon_issued=report->leaf.imem_issued=false;
 report->stage=REDFIN_SHIM_ER_CLOCK;
 if(redfin_er_frequency()!=19200000u || redfin_er_wait_us()) {
  report->error=REDFIN_ER_CLOCK; return report->error;
 }
 const struct redfin_er_io io={0x0c440000u,0x0e600000u,0x0c40a000u,0,0x146ab65cu};
 report->stage=REDFIN_SHIM_ER_FIND;
 report->error=redfin_er_find(io.core,io.config,&report->target);
 if(report->error) return report->error;
 /* APID is range/owner checked by find: this stays inside the fixed32MiB
  * write window and touches only the selected channel's0x20-byte register set. */
 struct redfin_er_io selected=io;
 selected.channel=0x0c600000u+(uintptr_t)report->target.apid*0x10000u;
 report->stage=REDFIN_SHIM_ER_ARM;
 report->error=redfin_er_arm(&selected,&report->target,&report->leaf);
 if(!report->error) report->stage=REDFIN_SHIM_ER_DONE;
 return report->error;
}
#endif /* REDFIN_SHIM_RETURN_H */
