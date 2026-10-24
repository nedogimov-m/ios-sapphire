# Redfin GPU SMMU prerequisites — 2026-10-23

[`include/redfin_gpu_smmu.h`](include/redfin_gpu_smmu.h) implements a bounded
read-only global-register snapshot. It has no write callback, reads no
context-bank page and grants no DMA/context ownership. The optional adapter
mode below requires this call's fresh held-CX and successful reset-held TCM
proof from [GMU.md](GMU.md).
The private IRQ list uses `gic-intids`; a standard `interrupts` property here
would enter IOKit's interrupt resolver before the observer can run.

Authenticated hardware capture `gpu-smmu-v3` passes: result0/stage4,
58 completed reads, stable=1 and format=1. IDR0/1/2/7 are
`0x4c017e05/0x20000005/0x5511/0x24`: five stream slots, five contexts,
4KiB register pages, 32KiB global half, 15 SID bits and 36-bit output.
CR0 is `0x220406`; global fault/syndromes are zero. All five SMRs and
GR1 CBAR/CBA2R pairs are zero; raw invalid-slot S2CR values are retained
privately. Streams4/5 have no active match and the metadata-only unreferenced
mask is `0x1f`. No context register, route write or DMA was attempted.
The same run repeats the GMU clock/counter/TCM proof, reaches PID1 and returns
to fastboot; HFS remains clean with the same write count.

The separate `--gpu-smmu-context-probe` selects `redfinsmmu=2`. It repeats
that global snapshot, then reads only CB0/1 using
[`include/redfin_gpu_context.h`](include/redfin_gpu_context.h).
Its additional exact `context-policy` is `[1,0x8000,0x4000,2,0x1000,12]`.
The 16KiB CPU mapping includes CB2/3 because of XNU's granule, but callbacks
address only the two selected low banks and twelve read-only registers each.
No TTBR dereference, fault acknowledgement, TLB operation or store exists.
All inherited exact argument/ADT/parent/source/reset/IRQ checks apply before
mapping, after breadcrumbs and before every access. Two passes must agree.
Modes0/1 do not map or access any context page.

Authenticated `gpu-context-v1` hardware passes 48 reads/stage3/stable1:
both SCTLR.M bits are clear and both FSRs zero. Other configuration registers
are nonzero; disabled does not mean blank or owned. The current stable raw
TTBR/TCR/MAIR words remain private evidence and are never followed as pointers.
The test reaches PID1 and returns to fastboot with the same clean HFS header.
This supplies the memory-manager prerequisite; that read-only profile installs no translation.
[`include/redfin_gmu_pagetables.h`](include/redfin_gmu_pagetables.h) separately
constructs CPU-only 4KiB tables from owned allocations. It installs no table
or route itself. The explicit memory profile below connects its output to CB1.

## Reset-held firmware and owned context profile — 2026-10-24

`--gpu-smmu-memory-probe --gmu-fw-file PATH --gmu-fw-sha256 HEX` selects
`redfinsmmu=3`. It requires the same isolated CPU0/md0 held-CX, clocked TCM,
global and CB0/1 prerequisites; it cannot be combined with the GUI/root profile.
The SHA256 must match the private native firmware inventory. The host uses
the actual C firmware planner before packing, and XNU verifies the complete
firmware/hash/ADT contract before any parent power write.

[`gmu-memory.inc`](gmu-memory.inc) allocates zeroed, wired, contiguous private
RAM through XNU, verifies every 4KiB physical/host pair and retains the full
allocations until platform reset. The total bound is 1MiB; the table pool is
`0x28000` bytes. It constructs native 4KiB/39-bit tables, transfers and reads
back every firmware payload in reset-held ITCM/DTCM or owned RAM, initializes
the four-queue native HFI table, then cleans data and tables to PoC.

[`include/redfin_gmu_mapping.h`](include/redfin_gmu_mapping.h) adapts the
preferred upstream's `space_on()` into a one-shot CB1 lease. Fresh snapshots
must show no fault, active stream4/5 match, CB1 reference (including invalid
slots), existing CBAR/CBA2R or enabled CB0/1. It changes only CB1 and one
invalid SMR/S2CR slot. Seventeen typed stores set native NC table walks,
TCR `0x802019`, TCR2 `0x38011`, MAIR0 `0xf404ff44`, ASID1 and SCTLR
`0x1027`, synchronize the TLB, then route stream5/mask `0x400`. Faults are
recorded without interrupts/stalls; no global reset or fault acknowledgement
is used. Readback must confirm the installed fields; complete observed
CBAR/S2CR words are retained to detect subsequent changes. FSR FORMAT is
status, separately masked from the native genuine fault bits.

The adapter requests positive hardware ATS translations for the first and
last page of every owned extent and checks PAR against the independently
known physical allocation. ATS writes are atomic 64-bit stores as required
by native `arm-smmu.c`. Explicit scalar stores also avoid the known HYP
WZR-store issue. CM3 remains reset-held and GX collapsed throughout. A
failed or partial install never frees its backing memory or retries.

Host validation: 192 focused firmware/table/context/adapter/return tests pass;
the new lease covers foreign changes, denied ownership/publication, each
failed store, wrong readback, timeout and revocation. Local native build
`build-20261024-142257.log` links successfully. The packed memory-v1 image
passes the real loader/live FDT/Image-window, bound-firmware and compiled
shim-return preflight. Hardware mapping/ATS success is pending; this source
milestone does not establish GMU execution, GPU commands or Metal.

## Native resource and access boundary

The preferred [HackiOS kernel][hackios] at
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`, `redwood_adreno.c` steps 8/9/13,
provides the global snapshot and later owned-map reference. Its **128KiB**
GPU SMMU aperture must not be copied to Redfin. Native source references are
Google msm `500b3a2059c1eec0fec08ec56add06320ea901a8`, especially
[`arm-smmu.c`][smmu], [`arm-smmu-regs.h`][regs], [`io-pgtable-arm.c`][tables]
and [`kgsl_iommu.c`][kgsl]. Native DT and the locally captured FDT distinguish
two descriptions of the same block:

| Node | Verified native properties |
| --- | --- |
| `/soc/kgsl-smmu@3da0000` | `qcom,qsmmu-v500`, base `0x03da0000+0x10000`, separate TCU `0x03dc2000+0x20`, `qcom,skip-init`, `qcom,use-3-lvl-tables` |
| `/soc/qcom,kgsl-iommu@3da0000` | Legacy KGSL wrapper, `qcom,kgsl-smmu-v2`, base `0x03da0000+0x10000`, `qcom,protect=<0xa0000 0xc000>`, retention |
| GMU `gmu_user` / `gmu_kernel` children | Verified SMMU phandle, stream IDs 4 / 5, mask `0x400`; `qcom,iommu-dma="disabled"` |

The legacy `qcom,protect` range is not a declaration that all SMMU context
banks are accessible or free. It does not authorize a CPU read of a secure
context. The snapshot avoids **every** context-bank page, including bank 0.
It also avoids TCU/TBU implementation registers, address-translation tests,
TLB invalidation/sync, fault acknowledgements and table-memory dereferences.

Native `arm-smmu.c:78` explicitly documents hypervisor interception of global
register accesses, including a deployed bug involving stores sourced from
WZR/XZR. The preferred upstream therefore uses explicit scalar `ldr wN` and
`str wN` instruction forms. The adapter uses an explicit scalar `ldr wN`
plus `dmb oshld`, confirmed in a native ARM64 object. This snapshot does not
issue a store of any kind to the hardware. HYP-mediated globals and
physical context-bank pages are separate access boundaries.

The native SMMU clock list is GPU MEMNOC, GPU SNOC DVM, GPUCC AHB and the
GPUCC HLOS1 SMMU clock vote. The existing TCM stage enables those branches,
and the adapter revalidates its held power/clock and CM3/GX-reset lifetime
before each register read. Native global/context interrupt SPIs 673 and
678–685 correspond to GIC INTIDs 705 and 710–717. The selected adapter requires
all of them disabled, not pending and inactive. It never masks or acknowledges
an inherited interrupt owner as part of observation.

## Snapshot interface and interpretation

Call `rf_gs_snapshot_run(ops, 0x06020001, snapshot)`. `ops` contains only
`context`, `valid` and ordered `read(offset, value_out)` callbacks. Wrong
chip/missing callbacks perform no MMIO. Every register read requires the
caller's current lease. A lost lease/read error stops immediately.

| Global register class | Byte offsets from `0x03da0000` |
| --- | --- |
| IDR0 / IDR1 / IDR2 / IDR7 | `0x20 / 0x24 / 0x28 / 0x3c` |
| CR0, global fault and syndromes | `0 / 0x48 / 0x50 / 0x54 / 0x58` |
| SMR and S2CR arrays | `0x800+4*i`, `0xc00+4*i`, bounded by decoded group count, maximum 128 |
| GR1 CBAR and CBA2R metadata | `0x1000+4*i`, `0x1800+4*i`, bounded by decoded context count, maximum 8 |

IDR-derived register geometry must exactly fit the native 64KiB resource:
4KiB register pages, 32KiB global half and at most eight context pages.
Unsupported 128KiB/64KiB-page geometries, EXIDS namespace, absent S1/stream
matching or invalid counts stop after the four ID reads. No context register
is accessed to discover that geometry. Format capability additionally
requires AArch64 4KiB tables, at least 36 output address bits, at least 39 VA
bits, sufficient SID width for the native `0x400` mask and valid route fields.

The entire accepted snapshot is read twice, including **all** S2CRs even
where SMR.VALID is clear, and all GR1 metadata. First difference returns
`EAGAIN` with its offset and `stable=false`; failed reads/leases never create
a reusable stable snapshot. Existing global faults are observed without
clearing them. The interface records raw bytes and explicit malformed-route
counts instead of assuming an all-zero/nonmatching entry is an ownership
grant.

Matches for streams 4 and 5 use the native 15-bit SMR mask. A mask `0x400`
intentionally includes aliases `0x404`/`0x405`; it does not merge streams 4
and 5. Duplicate or broad matches remain explicit. `gmu_slot` is valid only
when a stream has exactly one match. The helper does not change that route.

Context reference counts include latent TRANS references in invalid SMR
slots. `unreferenced_mask` describes only the global routing metadata. It
does not prove disabled SCTLR, blank tables, a nonsecure context, software
ownership, a safe route/IRQ lease or permission to modify a HYP-owned bank.
All of those are still required before a translation context can be enabled.
The native `qcom,skip-init` path preserves bootloader handoff; do not reset
the global SMMU or replace another stream's route to acquire a context.

## Exact optional kernel mode

The existing synchronous `redfin_gmu_probe_contract()` / `redfin_gmu_probe()`
API is unchanged. The exact isolated GMU1 profile from [GMU.md](GMU.md) admits
one optional `redfinsmmu=1`; no other value or duplicate is accepted.
`redfin_gmu_args_select(args, bytes_including_NUL, &smmu_requested)` reports
the selection only on a fully valid profile. Invalid args leave the selection
output unchanged. No flag means the original TCM hardware-write sequence and
no SMMU mapping, access or SMMU IRQ check, even if an unused ADT node exists.

The parent calls `redfin_gmu_probe_contract()` before its first ARC/GDSC
write. In the selected mode this validates both exact ADT leaves, so a missing,
malformed or incompatible SMMU policy cannot first be discovered after parent
power writes. The common builder supplies the new leaf through
`gmu_probe.add_contract(tree, native_nodes, smmu=True)` after the existing
matching CX contract. The default call still emits only the old GMU leaf.
Both additions are atomic: a failed native input leaves the tree unchanged.

Native validation checks the full modern SMMU/TCU resource tuple, native
64KiB legacy wrapper and protection metadata, skip-init/three-level flags,
both descriptions' four clock phandles/IDs/names, CX supply and GIC parent,
all nine native IRQ triples, and the GMU children's verified SMMU phandle,
stream IDs 4/5, mask `0x400` and disabled generic DMA. GCC MEMNOC/SNOC-DVM
are IDs 35/36 at `0x7100c/0x71018`. GMU AXI's ID 13 at `0x71154` is a
separate DDRSS clock. A mismatched 128KiB upstream aperture is rejected.

The little-endian `/redfin-gpu-smmu` contract is:

| Property | Exact values |
| --- | --- |
| `reg` (64-bit pair) | `[0x03da0000,0x10000]` |
| `chip-id` | `0x06020001` |
| `stream-map` | `[4,0x400,5,0x400]` |
| `format-policy` | `[0x1000,0x8000,128,8,39,36]`: register page, global half, stream/context bounds, minimum prospective-map VA/PA bits |
| `clock-policy` | Four `[unit,offset,mask,expected]` rows below; unit 0 GCC, 1 GPUCC |
| `interrupts` | `[705,710,711,712,713,714,715,716,717]` |

| Clock | Policy row |
| --- | --- |
| MEMNOC | `[0,0x7100c,0x80000001,1]` |
| SNOC DVM | `[0,0x71018,0x80000001,1]` |
| GPUCC AHB | `[1,0x1078,1,1]`; native HALT_DELAY does not promise a HALT status bit |
| HLOS1 SMMU vote | `[1,0x5000,0x80000001,1]` |

GICD `+0x158/+0x258/+0x358` mask `0x3fc2` must stay clear. These checks
join the existing GMU IRQ and parent/CPU0/EL1/return/argument/ADT lifetime.
The adapter binds all 14 GMU/SMMU/chosen properties and rechecks their bytes.

SMMU entry requires this call's `RF_GT_DONE`, zero error, held reset, verified
200MHz source, live counter and fully restored clean DTCM. The first GMU
summary is printed before attempting the new stage. Before mapping globals
and before each snapshot read, the adapter checks the current parent lease,
native PLL/source/votes, collapsed GX, all four SMMU clocks and GPU_MISC,
CM3 reset 1 and idle INIT/HFI state. Only `0x03da0000+0x8000` is CPU-mapped;
every context-bank page remains unmapped. The read callback accepts only the
global allowlist and issues one explicit scalar `LDR` with its read barrier.
The snapshot's interface still has no write callback.

First-access breadcrumbs precede critical GPLL0/feed/clock and GMU CSR/TCM
accesses. Each register/direction logs once; restoration has one bounded
marker. SMMU breadcrumbs mark IDs, globals, routing, GR1 metadata and the
second pass. Logging is followed by fresh lease validation before MMIO.
Polling iterations do not emit a log stream, and counter-window timing is
not extended by a first-access log. After capture, bounded CPU-only dumps
print raw IDs, routes and CBAR/CBA2R; route/GR1 dumps require a complete first
pass. Partial ID readiness is explicit, and derived route analysis appears
only for a stable snapshot. Unreferenced contexts are explicitly not owned.

Failure never releases the held ARC floor, clears faults/IRQs, changes a
route, reads a CB page, installs a table or starts firmware. The public call
returns the new snapshot result when selected, and the original TCM result
otherwise. Its one-shot entry remains consumed after success or refusal.

## Memory-map plan after ownership proof

The GMU firmware parser in [GMU.md](GMU.md) supplies explicit mapped ranges.
The current base-vendor image needs six non-TCM extents, 43 mapped 4KiB pages,
including the native five-page HFI region. ITCM/DTCM are local MMIO memory
and must not appear in an SMMU table.

Native `kgsl_gmu.c:gmu_prealloc_req()` maps preallocations as
`IOMMU_READ | IOMMU_WRITE | IOMMU_PRIV`. The HFI allocation omits PRIV, and
the log adds PRIV. No mapping here requests `IOMMU_CACHE`. Consequently the
native LPAE page descriptors use:

| Memory | Page attributes, excluding physical address |
| --- | --- |
| Firmware/persistent/log | `0xe03`: page type 3, outer-shareable, AF, nG, privileged RW, AttrIndx 0 |
| HFI | `0xe43`: same, with unprivileged RW permitted |

MAIR AttrIndx 0 is normal noncached `0x44`, not Device memory. The GMU's
"CACHE" virtual domain name does not itself select write-back SMMU memory.
Native MAIR0 is `0xf404ff44`. It remains separate from host CPU cacheability
and the CM3's own I/D caches. The native preallocation flags do not request
NOEXEC; inventing XN on firmware code would prevent execution.

For 39-bit VA, 36-bit PA and a 4KiB granule, this image needs five table pages:
the root, an L2/L3 pair for low cached firmware, and an L2/L3 pair for the
`0x60000000` uncached kernel region. XNU's 16KiB VM page size does not change
this SMMU granule. Allocating two 16KiB-owned pages can back five distinct
4KiB table pages only when the host and physical views form one contiguous
32KiB extent; the remaining allocator-owned slack stays retained.

Every descriptor-pool and DMA allocation needs a verified host-view/physical
pair, complete allocator-owned extent, unique ownership/lifetime token and
proof that it does not alias another extent, existing tables, kernel image,
framebuffer or reservation. Initialize every range that a descriptor can
expose and publish its cache changes before making it reachable; retain the
complete allocations until the context is proved stopped or the platform
resets. A stable global snapshot cannot supply those proofs.
Do not generate a TTBR from an ordinary virtual address or treat a protected
context's apparent zero as free space.

## CPU-only table constructor

`rf_gm_pt_build(snapshot, chip, image, image_bytes, backing, backing_count,
table_pool, owner, output)` reparses the immutable firmware and accepts only
a successful, stable snapshot with consistent raw/decoded native geometry
and supported table format. It uses the snapshot to select a table format;
it does not select or acquire a context.

Each `rf_gm_memory` supplies a contiguous host view, physical base, complete
allocator-owned size, unique nonzero token and the corresponding firmware
GMU address. `table_pool.gmu_address` is zero; the root is reached by physical
address. Data allocations are matched by GMU address, independent of caller
array order. The owner must prove that all allocations are exclusive and
unreachable by DMA. Its `owns(context, memory, usage)` callback receives the
full extent, including 16KiB allocator slack, and its `valid(context)`
callback must cover their complete lifetime and immutable callback state.
Callback state must remain outside the writable pool.

This first constructor accepts only the approved XNU RAM window
`0x180000000+0x80000000`, aligned physical bases and sizes, and at most 2MiB
per owned extent. Full physical/host extents and ownership tokens must be
distinct. Firmware, input metadata and output cannot alias the writable
pool; output also cannot overwrite firmware, input metadata or DMA memory.
All malformed inputs, insufficient table storage and denied ownership fail
before the first pool store. Firmware-parser errors propagate unchanged.

The constructor emits only table and page descriptors: no blocks, TCM
entries or mappings of allocator slack. It bounds storage to 40 table pages
and 18 DMA extents, retains the full pool/data ownership metadata in the
result, and reports `table_bytes` separately from the owned pool size. For
the current image, only `0x5000` of a `0x8000` pool is zeroed and populated;
the unused `0x3000` is preserved and remains unreachable.

Lifetime validation precedes every bounded page zero, descriptor store and
final output publication. Revocation stops further stores and leaves output
unchanged. The CPU pool can then contain incomplete tables and must not be
installed. Even successful construction still requires separate data/HFI
initialization, cache publication, context/route ownership, context
programming and TLB synchronization. No such hardware operation, allocation,
firmware load or reset release is part of this interface.

## Validation and next experiment

`python3 -m unittest ports/redfin/test_gpu_smmu.py` compiles the actual
snapshot header. The 13 tests cover complete double snapshots, every
read/lease failure and every second-pass register change, the native-size
boundary, latent references, stream aliases/ambiguity, malformed fields,
fault preservation and an allowlist excluding all context/TCU/TBU/TLB access.
These results are host observations; they do not establish GPU-SMMU hardware
access or context ownership.

`python3 -m unittest ports/redfin/test_gmu_probe.py` now passes 42 adapter/FDT
tests. They cover native contracts and atomicity, all 2,560 GMU/SMMU ADT bits,
all 9,963 selected-parent lifetime edges, every one of 114 SMMU read lifetime
revocations and all 57 second-pass register changes. Fresh source/reset/bus/
GX/args/binding failures, inherited and late IRQs, first-access logging
revocations, geometry refusal, first-pass log completeness and original-mode
hardware-write parity are exercised. The locally captured native FDT also
passes the selected generator. A private standalone ASan+UBSan run passes
13,558 scenarios; a private native object built with actual XNU
`DEVELOPMENT_ARM64_SWEET` BSD compiler flags and `-Werror` confirms scalar
`LDR` followed by `dmb oshld`. No prepared build tree or device is changed
by these checks.

`python3 -m unittest ports/redfin/test_gmu_pagetables.py` adds 19 host tests.
An independent three-level descriptor walker checks every emitted entry,
exact physical mappings, HFI privilege, unmapped gaps and TCM exclusion.
Other cases cover 16KiB allocator slack/canaries, unordered backing arrays,
2MiB boundaries, the maximum 18 extents and a sparse 34-table layout,
unsupported/inconsistent snapshots, range/alias/token/ownership failures,
and every lifetime-revocation point. A private standalone ASan+UBSan run
passes 403 scenarios across the current, sparse and boundary layouts,
including all 219 lease edges, 31 allocation denials and 150 malformed/alias
cases. The private header copy also passes the actual XNU
`DEVELOPMENT_ARM64_SWEET` BSD compiler flags with `-Werror`.
These are CPU-memory results; no table is installed or firmware started.

TCM, globals and read-only CB0/1 now have authenticated hardware results as
recorded above and in NOTES.md. Next: collect memory-v1's firmware readback,
native context readback and positive ATS results. Only successful hardware
translation can support the later PDC/RSC/CM3/HFI start; GPU commands and iOS
graphics integration follow separately.

[hackios]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[smmu]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/arm-smmu.c
[regs]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/arm-smmu-regs.h
[tables]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/io-pgtable-arm.c
[kgsl]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/kgsl_iommu.c
