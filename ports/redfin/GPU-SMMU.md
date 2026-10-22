# Redfin GPU SMMU prerequisites — 2026-10-23

[`include/redfin_gpu_smmu.h`](include/redfin_gpu_smmu.h) implements a bounded
read-only global-register snapshot. It has no write callback, reads no
context-bank page and grants no DMA/context ownership. Its new code is not
connected to the current TCM kernel startup. The held-CX/clock/reset proofs
in [GMU.md](GMU.md) must precede a separately selected hardware experiment.

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
`str wN` instruction forms. A future read-only adapter should use an explicit
scalar `ldr` plus the normal Device read-completion barrier. This snapshot
does not issue a store of any kind to the hardware. HYP-mediated globals and
physical context-bank pages are separate access boundaries.

The native SMMU clock list is GPU MEMNOC, GPU SNOC DVM, GPUCC AHB and the
GPUCC HLOS1 SMMU clock vote. The existing TCM stage enables those branches,
but a new snapshot must revalidate its held power/clock and CM3/GX-reset
lifetime before each register read. Native global/context interrupt SPIs
673 and 678–685 correspond to GIC INTIDs 705 and 710–717. A future exact-mode
adapter must prove those interrupts unowned/masked, not pending and inactive;
it must not mask or acknowledge an inherited owner as part of observation.

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
4KiB table pages while retaining the remaining allocator-owned slack.

Every descriptor-pool and DMA allocation needs a verified host-view/physical
pair, complete allocator-owned extent, unique ownership/lifetime token and
proof that it does not alias another extent, existing tables, kernel image,
framebuffer or reservation. Zero and publish complete owned buffers before
making them reachable; retain them until the context is proved stopped or
the platform resets. A stable global snapshot cannot supply those proofs.
Do not generate a TTBR from an ordinary virtual address or treat a protected
context's apparent zero as free space.

## Validation and next experiment

`python3 -m unittest ports/redfin/test_gpu_smmu.py` compiles the actual
snapshot header. The 13 tests cover complete double snapshots, every
read/lease failure and every second-pass register change, the native-size
boundary, latent references, stream aliases/ambiguity, malformed fields,
fault preservation and an allowlist excluding all context/TCU/TBU/TLB access.
These results are host observations. No GPU-SMMU hardware read or new kernel
startup is enabled by this milestone.

Next: after physical reset-held TCM success, bind a separate exact read-only
GPU-SMMU mode to that same successful lifetime and collect native IDs/routes.
Only then decide whether any candidate bank/SME can receive an independent
software/hypervisor ownership grant and validated 4KiB page tables.

[hackios]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[smmu]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/arm-smmu.c
[regs]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/arm-smmu-regs.h
[tables]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/io-pgtable-arm.c
[kgsl]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/kgsl_iommu.c
