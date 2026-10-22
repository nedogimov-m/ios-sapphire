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
readback acceptance or retry it. Gadget and DMA remain uninvoked.

## Qualcomm bypass quirk and read-only context probe — 2026-10-22

Linux v6.12's
[Qualcomm SMMU driver](https://github.com/torvalds/linux/blob/v6.12/drivers/iommu/arm/arm-smmu/arm-smmu-qcom.c#L313)
describes this exact firmware behavior: FAULT writes may be ignored, while
BYPASS writes become FAULT. Its workaround reserves a context bank, writes
SCTLR=0 and CBAR type S1_TRANS_S2_BYPASS, then substitutes TRANS to that bank
for a BYPASS stream. Pinned Lito `arm-smmu.c:2363` likewise implements
`DOMAIN_ATTR_S1_BYPASS` with SCTLR.M clear; its context allocator preserves
bootloader handoff banks. The upstream last-bank reservation is not permission
to seize an inherited Redfin bank.

`usb-context-probe.patch` adds only observation. With explicit
`redfinusb=3 redfinusbowned=1 redfinusbcontexts=1`, the trusted initial caller
registers its owner, observes contexts and returns before claim. Observation
consumes the owner once; subsequent claim/revalidation cannot activate a route.
No route/CB stores, fault clears, TLB/ATS/RESUME operations, IRQ enables or DMA
occur. Normal absent/zero selector behavior is unchanged.

Exact DT primary-reg and full-range RAM exclusion checks precede mapping.
Observed ID1 `0x6000003e` gives 4 KiB SMMU register pages, 62 banks and zero
stage-2-only banks. GR1 is `base+0x1000`; CBAR/CBA2R are `GR1+4*n` and
`GR1+0x800+4*n`. Context banks start at `base+0x80000`, with 4 KiB stride;
bank 61 is `0x150bd000`. SCTLR/FSR offsets are `0/0x58`. Only the existing
`0x4000` global span and derived `0x15080000+0x3e000` bank span are mapped,
inside the verified `0x15000000+0x100000` primary range.

Two complete, identity-bracketed snapshots must agree on all 81 SMR/S2CR pairs
and all four fields of every bank; all-ones, layout, policy and stability
failures stop the probe. S2CR type uses bits 17:16, bank index bits 7:0, and
SMR validity bit 31. Logs distinguish active TRANS references from all TRANS
references, including invalid-SMR entries. Unknown type/index blocks blank
classification. A bank is labelled `blank-unreferenced` only with no references
and all four raw fields zero; every line explicitly reports `ownership=0`.
This is evidence for a future allocator audit, not a CB lease or DMA authority.

Ten actual-C probe tests cover these guards, derived bounds, reference counts,
one-shot behavior, zero writes/delays and unchanged legacy behavior. All 52
focused context/owner/caller/diagnostic tests pass. The subsequent context
capture and controlled implementation are described below.

## Controlled dedicated NS context implementation — 2026-10-22

The authenticated context capture found stable banks 0–2 referenced by TRANS
streams and bank 3 configured despite no references. Banks 4–61 had M clear,
CBAR/CBA2R/FSR zero and varying nonzero SCTLR fields. FSR `0x400` on banks
0–3 is the FORMAT field, outside the native fault mask `0xc00001fe`.

The actual DT selects ordinary non-static NS allocation: `qcom,qsmmu-v500`
with `qcom,skip-init`, no static/secure-alias property, USB SID `0xe0`/mask 0,
`qcom,iommu-dma="atomic"` and no secure VMID. Pinned `arm-smmu.c:4988`
allocates the first clear software bitmap bit in `[NUMS2CB, NUMCB)` after
handoff import. It does not require whole SCTLR zero or an additional secure
grant. Consequently raw-zero classification from the observer is not the
allocation contract, and no interpretation of every other SCTLR bit as
reset-UNKNOWN is needed.

`usb-bypass-context.patch` requires explicit `redfinusbbypass=1` and exact
`ns-context-allocator=1` DT attestation, mutually exclusive with context
observation. Its permanent bitmap additionally excludes latent TRANS
references, GR1 configuration, M set and actual FSR faults. First-fit bank 4
is available in the observed fixture after preserving banks 0–3. Two fresh
imports precede its software lease. The only four hardware stores are owned
SCTLR=0, CBAR=`0x10000`, S2CR=NSH/TRANS/selected bank (`0x304` for bank 4),
then SMR=`0x800000e0`. Each has strict readback; complete core/global/stream/CB
proof is repeated at every boundary. Failure permanently quarantines the
lease without rollback, reset or retry. No gadget or DMA starts.

The new route state and CB-aware revalidation are separate from the original
direct BYPASS API. A reproduced shared warm-proof bug now explicitly rejects
DSTS all-ones using its existing read. The zero-value MMIO store forces a GPR
because pinned Qualcomm code documents a WZR trap defect; ARM64 assembly
shows `mov w8,#0; dmb oshst; str w8,[x0]; dsb osh`. All 62 focused USB tests
and independent source review pass. The actual built kernel additionally
disassembles to `dmb/add/str w2,[x8]/dsb/ret`, with no WZR store.

The authenticated image-matched `usb-bypass-v1` hardware cycle reached PID1
and returned automatically to verified fastboot. First-fit bank4 and slot4
were leased, all four exact stores accepted, and both claim and strict
revalidation returned0. The dedicated warm identity route for SIDe0 is now
proved. Device DMA, gadget/controller writes and USB enumeration were not
invoked; the next stage needs an active route proof and guarded gadget hook.
