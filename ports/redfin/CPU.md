# Redfin CPU bring-up

The working iOS profile uses one Cortex-A55 CPU. Physical display and
single-finger UI interaction work, but the user reports about 1 FPS and
slow app opening. A 10 Hz software-copy cadence with screenshots and verbose
kprintf disabled did not noticeably improve responsiveness.

## CPU6 capability probe

`--cpu-capability-probe` is a separate md0/CPU1 test. It requires
`--kernel --dtb --return-bootloader`, boot MPIDR0, the canonical RAM window,
and all other peripheral probes/writers disabled. The kernel must include
`cpu-probe.patch` and `cpu-probe-start.patch`.

After verified PMIC/IMEM bootloader return, CPU0 checks PSCI version,
features and CPU6 affinity OFF. A single CPU_ON64 targets MPIDR0x600.
The secondary entry records MIDR, MPIDR, MMFR0, CurrentEL, SCTLR and CTR in
a permanent, physically checked mailbox, then parks in WFE with exceptions
masked. It does not enter XNU or configure MMU/GIC/timers. CPU0 performs
bounded polling with invalidate-only reads and retains the page/core until
reset. No retry, CPU_OFF or device DMA is performed.

CPU6 is the Gold core according to pinned Lito DT and captured Android
CPU identity. Its 16K capability must be read on the device; other boards'
granule support does not establish Redfin support. A successful probe
establishes firmware entry, architectural capability and mailbox visibility.
It does not prove secondary XNU startup, coherency under SMP load, IRQs,
cross-IPIs, timers or scheduling.

## Before enabling XNU SMP

The current ADT, loader and SweetCPU restrict the profile to one CPU.
PMIC return currently arms after CPU initialization, and RAM logging masks
only local exceptions. A separate SMP profile needs return armed before
secondary startup, synchronized logging with explicit loss accounting,
topology/loader validation and positive cross-CPU/timer/progress checks.
UFS/GUI must stay gated until the isolated md0 stage succeeds. CPU suspend,
halt and hotplug remain unsupported.
