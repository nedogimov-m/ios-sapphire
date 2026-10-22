# Isolated USB stream ownership draft

`usb-owned-route.patch` adds an unhooked kernel manager for the first Redfin
`md0` USB routing experiment. It can retain exactly one SID `0xe0` bypass
route, then check that the route and its imported surroundings remain intact.
It does not start or authorize USB DMA. The first hardware experiment is
claim followed by strict warm-state revalidation only.

The patch currently adds `bsd/dev/redfin_usb_owned.{h,c}` only. It has no
startup call, `bsd/conf/files` entry, preparation-script entry, or production
policy implementation. Integration must provide those deliberately after
review. Neither these host tests nor this draft have built or booted a kernel.

## Ownership premise and caller contract

An invalid SMR does not establish software ownership. The manager instead
requires an audited kernel callback through
`redfin_usb_owned_register(caller_id, &policy)`. The callback must prove that
this is the sole nonsecure APPS kernel after ABL exits, with no Linux or EFI
runtime and with all competing Qualcomm/SMMU write paths disabled for the
actual `md0` experiment. The callback must also establish that UFS is not in
use. This is the same trust in secure firmware preserving nonsecure routing
that an ordinary nonsecure SMMU driver requires.

The stable opaque caller ID identifies the sole registered owner. The manager
copies the callback and context. Registration never maps or accesses MMIO;
missing or false policy is refused. The callback is pure and non-reentrant,
its code and context must remain valid, and it must remain true for the entire
lease. During claim and revalidation it runs under the manager mutex. It may
not call back into this manager. A boot argument or an unconditional true
callback cannot supply the ownership premise.

The mutex serializes all manager transactions. Independent hardware writers
must be excluded by the trusted policy; a local mutex alone cannot exclude
firmware or another driver. Repeated register snapshots additionally detect
observed changes. They cannot prove that another writer never acted between
reads. The initial configuration requires one CPU, and the manager cannot
recover from a failed claim without rebooting.

The runtime gates require `redfinusb=3 cpus=1 redfinreturn=1 rd=md0` and a true
`redfin_spmi_return_ready()`. `sweetusb`, `modem`, `wifi`, `gpu`, `redfinufs`,
`redfinroot`, `ufsrw`, and `rootrw` must be absent or zero, and `ufsroot` must
be absent. The actual policy callback remains necessary even when these gates
pass. The root DT must identify both `google,redfin` and `qcom,sm7250`; the
chosen DRAM range must be nonzero, 16 KiB aligned, within 36 physical address
bits, and exclude the three mapped register pages.

## Claim transaction

The manager maps three 16 KiB pages: GCC `0x0010c000`, DWC3 `0x0a60c000`,
and APPS SMMU `0x15000000`. No RAM, context-bank, page-table, or PHY mapping is
created. GCC registers are read only. DWC3 must have the observed controller
ID `0x5533330a`, 64-bit address width, device port mode, no reset, a halted
device, a nonzero 4 KiB aligned event ring, an exact masked size of
`0x80001000`, and zero pending events. USB power and all five required clocks
must be enabled and out of reset. This warm state is freshly read before
publication, between the two writes, and after publication.

SMMU IDs must equal the observed `ID0=0x4c017e51`, `ID1=0x6000003e`, and
`ID2=0x5111`. These describe 81 stream groups and the observed register
format. `CR0.CLIENTPD` and extended-stream-ID mode must be clear;
`CR0.USFCFG` must be set so unmatched streams fault. The complete initial
CR0 value is imported and preserved rather than replaced with an observed
constant. Every SMR and S2CR is imported, including stale data in invalid
slots. All-ones read values are refused.

Claim fails if any existing exact or masked SMR matches SID `0xe0`, or if no
invalid slot exists. The first invalid slot is leased. After rechecking policy,
platform, warm state, IDs, CR0, and every imported pair, the only permitted
writes are:

1. Its S2CR receives `0x00010300`: bypass type, non-shareable, default privilege.
   Its SMR is still invalid. Readback is bounded to 1000 one-microsecond polls.
2. All proofs are repeated, then its SMR receives `0x800000e0`: valid, exact
   SID `0xe0`, zero mask. Readback and all proofs are repeated again.

All other SMRs/S2CRs remain byte-identical, including invalid slots. There
are no global-control, context-bank, table, TLB, clock, reset, controller,
PHY, event-ring, or DMA writes. In particular, bypass refusal has no
context-bank or global-bypass fallback.

## Revalidation and quarantine

`redfin_usb_owned_revalidate(caller_id)` checks the complete proof, including
the original warm-halted controller/ring snapshot, with zero stores. This is
the API for the first hardware experiment.

`redfin_usb_owned_route_retained(caller_id)` is a separate zero-store check for
a future active gadget. It requires a successfully published route and keeps
the owner, policy, runtime, platform, all global SMMU IDs/CR0, and every
SMR/S2CR check. It omits the original DWC3/GCC warm-state check because an
active gadget changes its controller and event ring. It supplies route
evidence only; a caller needs its own trusted controller/DMA policy.

Any failed claim or lost proof permanently quarantines the manager. There
is no rollback, release, cleanup, retry, or later write. A route written before
failure can remain physically active. Quarantine prevents further manager
authorization; it does not revoke that hardware route or stop existing DMA.
A future active caller must quiesce DWC3 when proof is lost and must never
release or reuse a route while DMA is running. This manager intentionally
does not implement controller quiescence.

## Evidence and validation

Register encodings and Linux's software allocation/locking model are pinned
to Google msm commit `500b3a2059c1eec0fec08ec56add06320ea901a8`,
`drivers/iommu/arm-smmu.c` and `arm-smmu-regs.h`. The Redfin DT routing source
is pinned to `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`: APPS SMMU
`0x15000000`, USB wrapper `0x0a600000`, and USB SID `0xe0`. The read-only
observations are in `usb-probe.patch` and `usb-route.patch`. The old event
ring address alone is not evidence that DMA works. A 16 KiB CPU page size
does not imply a 16 KiB SMMU translation granule; bypass creates no tables.

Run `python3 ports/redfin/test_usb_owned_route.py`. The test extracts the
actual C/header additions and compiles them with stub kernel APIs. Only the
MMIO loads/stores and ARM barriers are replaced with model calls. The model
rejects accesses outside the fixed maps and register allowlist and checks that
all MMIO occurs under the manager lock. It verifies ordered two-store success,
preservation of all other registers, caller/runtime/platform gates, exact and
masked conflicts, bounded readback refusal, changing imports, lost halt or
policy, retained-route semantics, permanent quarantine, and zero-store
revalidation. The mutation hooks represent external changes between snapshots.

The 26 host tests pass. They validate the C transaction logic, not real MMIO
ordering, kernel lock initialization, hardware bypass acceptance, isolation
policy correctness, DMA addressing/cache behavior, or USB enumeration.

## First hardware claim and cached diagnostics — 2026-10-22

The initial md0-only caller is built in the actual ARM64 kernel. Its first
hardware run (`logs/redfin/usb-owned-v1/`) authenticated and matched the
image ID, reached PID1 and returned to verified fastboot without panic.
Registration succeeded, but the claim quarantined with EIO5. That log
cannot distinguish an all-ones imported SMR/S2CR from a store/readback
failure, or establish whether any store happened. Earlier observers read
S2CR only for matching SMRs; zero matches did not verify the full S2CR bank.
No gadget or DMA was invoked.

`usb-owned-diag.patch` therefore records the snapshot phase, attempted store
count, failing index and already-read SMR/S2CR/header, or the final existing
readback value after1000 polls. The selected pair is logged before the first
store. These are cached diagnostics: no additional MMIO reads, writes,
barriers, delays or retries; policy and quarantine behavior are unchanged.
Six actual-C baseline-versus-overlay tests verify identical read/write/delay
traces and outcomes for both EIO sources, every snapshot phase, strict and
retained-route checks, and repeated calls after quarantine. All42 focused
owner/caller/diagnostic tests and independent review passed. Hardware route
acceptance and USB enumeration remain unproved.

V2 (`logs/redfin/usb-owned-v2/`) authenticated and matched its image, reached
PID1 and returned to verified fastboot. Full import/pre-store verification
passed. Slot4 initially had SMR0/S2CR0; the only store requested S2CR10300
(TYPE BYPASS1) at offsetc10, but readback was20300 (TYPE FAULT2) after1000
polls. The guard quarantined before any SMR publication. This is evidence of
hardware/firmware bypass coercion; it is not a working route. Do not relax
readback acceptance or retry it. Next is a source-backed Qualcomm bypass
quirk and context-bank ownership audit. Gadget and DMA remain uninvoked.
