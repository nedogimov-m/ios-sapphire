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

V2 on 2026-10-23 establishes CPU6 entry and 16K support in an authenticated,
image-matched capture (`logs/redfin/cpu-cap-v2/`): PSCI1.1 CPU_ON returns0;
MIDR0x51ff804e, MPIDR0x81000600, MMFR0x101122, CurrentEL4 (EL1),
TGran16=1. CPU6 parks outside XNU. Kernel SHA256
`e2770bcc5077056f357d00630c7df6e7c40209b0ce04912138bfb8462418b4f4`,
local build `build-20261023-002659.log`, code commit `5f34df2`.
PID1 heartbeats and automatic recovery/fastboot return succeed without panic.

## Before enabling XNU SMP

The current ADT, loader and SweetCPU restrict the profile to one CPU.
PMIC return currently arms after CPU initialization, and RAM logging masks
only local exceptions. A separate SMP profile needs return armed before
secondary startup, synchronized logging with explicit loss accounting,
topology/loader validation and positive cross-CPU/timer/progress checks.
UFS/GUI must stay gated until the isolated md0 stage succeeds. CPU suspend,
halt and hotplug remain unsupported.
