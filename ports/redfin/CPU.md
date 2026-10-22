# Redfin CPU bring-up

The working iOS profile uses one Cortex-A55 CPU. Physical display and
single-finger UI interaction work, but the user reports about 1 FPS and
slow app opening. A 10 Hz software-copy cadence with screenshots and verbose
kprintf disabled did not noticeably improve responsiveness.

Source audit on 2026-10-23 found two unmeasured costs: the guarded Redfin
UFS path forces `su.cache=false; su.wait=false` and busy-polls command
completion, while each full display present copies 10,108,800 bytes and
rearms the timer after copying. Neither establishes the dominant bottleneck.
The legacy `ufswait`/`ufscache` parser, process sampler and `sweetbusy`
initialization are bypassed by Redfin's early-return paths; adding their
boot arguments alone does not enable them. V3's continuing presents,
touch-worker exit and scheduled clean unmount exclude a whole-kernel
lockup for that capture, but do not identify the About UI wait chain.

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

`--cpu-capability-target 0x100..0x700` selects one secondary in that
separate profile; CPU0 cannot be selected. The default remains CPU6.
CPU1..5 and CPU7 each pass fresh authenticated EL1/16K/mailbox tests on
2026-10-23 (`logs/redfin/cpuN-cap-v1/`, build `build-20261023-011946.log`).
CPU1..5 identify as part0x805; CPU6..7 as0x804. Thus all8cores support
the required granule. The target is all8in XNU; CPU0+CPU6 is the first
concurrent proof stage, not a limit on the final port.

## Before enabling XNU SMP

`--early-return-probe` rehearses a freestanding PMIC/IMEM return helper
after the current kernel's verified return has armed. It is an exclusive
md0/CPU0 profile requiring `--kernel --dtb --return-bootloader` and the
`early-return.patch`/`early-return-start.patch` overlays. It never starts a
secondary CPU. A successful protected rehearsal must precede using the
same helper in the shim before kernel or topology validation.
`--shim-early-return` opts into that second rehearsal and currently requires
`--early-return-probe`; it keeps all UP, md0 and peripheral exclusions.
V2 on 2026-10-23 succeeds with the same kernel9a2d87a5: initial kernel
observer already reads PON4 before the existing arm, fresh authenticated
logs match boot-ID `de5ac7f14c6e3052`, PID1 heartbeats and fastboot return
complete. The shim uses the shared leaf before payload validation; watchdog
programming stays in the existing loader immediately before kernel entry.

The current ADT, loader and SweetCPU restrict the profile to one CPU.
PMIC return currently arms after CPU initialization, and RAM logging masks
only local exceptions. A separate SMP profile needs return armed before
secondary startup, synchronized logging with explicit loss accounting,
topology/loader validation and positive cross-CPU/timer/progress checks.
UFS/GUI must stay gated until the isolated md0 stage succeeds. CPU suspend,
halt and hotplug remain unsupported.

The isolated `--smp-probe --shim-early-return --return-bootloader` profile
admits CPU0+CPU6 by default, or all8 with `--smp-cpus 8`, canonical RAM and md0. It disables
legacy SPMI/return writers with `redfinspmi=0 redfinreturn=0`; the shim
prearms PMIC/IMEM and a separate read-only kernel verifier checks that
hardware state before CPU_ON. Loader and kernel independently reject other
profiles. `smp-log.patch`, `smp-return.patch`, `smp.patch` and
`early-bootid.patch` are required; host recovery verifies both compiled
configuration gates and image hashes. The proof exercises dedicated SGI2,
per-core timers, bound worker progress and zero logger drops before CPU
publication. TLB shootdowns and GUI/UFS SMP need separate validation.

The first hardware SMP2 test passes on 2026-10-23 (`logs/redfin/smp2-v1/`):
CPU0/CPU6 each finish32steps, actual timer IRQ counts66/65, self/cross SGIs
complete, logger drops0, worker inactive and IRQ observers drained. XNU
publishes2/2CPUs and md0 PID1 runs11heartbeats before automatic fastboot
return. Capture is authenticated and image-matched. All8cores have separate
EL1/16K capability proof.

The eight-core test also passes (`logs/redfin/smp8-v1/`, 2026-10-23):
XNU publishes8/8, CPU0 finishes224steps and CPU1..7 each32; all8timers,
selfSGIs and bidirectional CPU0↔secondary exchanges complete. Workers exit,
observers drain, logger drops0, md0 PID1 runs11heartbeats and fastboot return
is verified in authenticated/image-matched capture. Kernel44b38fd5,
full local build020056. UFS/GUI integration and TLB-specific workload remain
separate work; the user requests the next iOS session on all8cores.
