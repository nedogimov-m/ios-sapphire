# Redfin A620v2 GMU firmware and HFI — 2026-10-23

The firmware planner and HFI codec are implemented and host tested in
[`include/redfin_gmu_firmware.h`](include/redfin_gmu_firmware.h).
They do not enable a GPU driver. Physical CX power, clocks, GMU execution,
owned SMMU translations and accelerated rendering require separate tests.
Keep the inherited Sapphire `gpu=0`; its A610 wrapper is incompatible.

## Reviewed sources

The user's preferred [HackiOS kernel snapshot][hackios] at
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab` supplies the staged
reset-held TCM readback, firmware, SMMU and HFI bring-up reference in
`xnu/files/bsd/dev/redwood_adreno.c`, especially steps 5, 6, 10 and 13–17.
Its overview contains a stale GMU base of `0x03d69000`; the actual block
definition uses `0x03d6a000`. Actual ITCM/DTCM offsets match Redfin.
Its A660 image, 17-descriptor HFI table, 16KiB log, SC7280 hub clocks and
debug-clock selections require replacement with the Lito contracts below.
The paired preferred userland snapshot remains
`906425b75e02b4f99eb5d7bb1ef7c9583472d772`; this work changes no private
iOS 16.5 ABI or injected library. See [UPSTREAM.md](UPSTREAM.md).

Hardware definitions below come from Google msm commit
`500b3a2059c1eec0fec08ec56add06320ea901a8` and the Lito DT commit
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4` already pinned by
[GPU.md](GPU.md):

| Native source | Reviewed contract |
| --- | --- |
| [`adreno-gpulist.h`][gpulist], A620 entry | A620 is A650 family, GMU major/minor 2/0; `a650_sqe.fw`, `a650_gmu.bin`, `a620_zap`, 512KiB GMEM |
| [`adreno_a6xx_gmu.c`][gmuc] | Metadata, block loading, PDC/RSC, CM3 reset, version-dependent completion, HFI start |
| [`kgsl_gmu.h`][gmuh], [`kgsl_gmu.c`][gmu] | 16-byte firmware headers, memory domains, preallocation, HFI/log allocation, clock and domain order |
| [`kgsl_hfi.h`][hfih], [`kgsl_hfi.c`][hfi] | Four queue descriptors, v2 headers, 16-byte queue alignment, performance/bandwidth/feature sequence |
| [`a6xx_reg.h`][regs] | GPU-relative word indices; convert to GMU aperture byte offsets |
| [`gcc-lito.c`][gcc], [`gpucc-lito.c`][gpucc] | GPLL0 feed, GMU 200MHz source and branch registers |
| [`clk-alpha-pll.c`][pll], [`clk-rcg2.c`][rcg], [`clk-branch.c`][branch] | Lucid PLL rate/readiness, RCG safe-source update, branch completion |
| [`debugcc-lito.c`][debug] | Lito clock measurement muxes and crystal reference |
| [`subsys-pil-tz.c`][pil], [`peripheral-loader.c`][loader] | PAS and relocatable ELF/MDT loading |
| [`lito-gpu.dtsi`][dt] | GMU/PDC/RSC resources, GMU streams 4/5, A620 zap PAS ID 13 |

Downloaded sources, binary firmware and inventory manifests remain ignored
under `research/`; no firmware bytes or device log are checked in.

## Firmware records and memory

The ignored base-vendor inventory contains a 41,548-byte `a650_gmu.bin`,
31,632-byte `a650_sqe.fw`, and the A620 zap MDT/b00/b01/b02 files.
The inventory is a mixed-version base filesystem with Virtual A/B COW entries,
not a proven effective stock snapshot. Image identity and compatibility need
separate proof before loading. Parsing a file does not authenticate it.

GMU records are little-endian `{address, size, type, value}`, each four 32-bit
words. Zero-size records precede initialized data. Types 1 and 7 request
`value` bytes at `address`, with type 7 persistent across GMU starts. Known
version metadata types are 2–6. A nonzero-size record has exactly `size`
following payload bytes. Its type/value are opaque; this image uses
`0xefbeadde` in both fields, and the native loader ignores those fields.
Do not require a zero data-record type.

| A620 GMU domain | GMU address range | Host action |
| --- | --- | --- |
| ITCM | `0x00000000 + 0x4000` | MMIO through GMU `+0x3000`, no SMMU allocation |
| Cached firmware | `0x00004000 .. 0x01000000` | Owned 4KiB-granule SMMU mappings in the GMU kernel context |
| DTCM | `0x10004000 + 0x4000` | MMIO through GMU `+0x7000`, no SMMU allocation |
| Uncached kernel | `0x60000000 .. 0x80000000` | Owned 4KiB-granule mappings in the GMU kernel context |
| Uncached user | `0x80000000 .. 0xc0000000` | Separate user context; current planner deliberately rejects it |

The observed image has nine metadata records and seven payload records.
TCM requests subdivide the existing 16KiB windows; the two DTCM requests
overlap by four bytes and must not become duplicate DMA allocations.
The non-TCM requests are:

| GMU address | Requested/mapped bytes | Lifetime |
| --- | --- | --- |
| `0x4000` | `0x8000` | Cached firmware |
| `0x144000` | `0x13000` | Cached firmware |
| `0x157000` | `0x9000` | Cached firmware |
| `0x60000000` | `0x1000` | Persistent kernel memory |

Payloads target ITCM at `0`, `0x200`, `0x400`; cached memory at `0x4000`
and `0x157000`; and DTCM at `0x10004000` and `0x10007fdc`.
Preallocation includes uninitialized memory beyond these payloads; zero
owned DMA memory before the context can fetch it. The firmware's 4KiB
translation granule is independent of XNU's 16KiB VM page size.

The five version words occupy DTCM offsets `0x3fe0..0x3ff0`. This file
describes core/power `0x20010008` and HFI `0x20000001`. For a core version
greater than `0x20010004`, native success is
`(CM3_FW_INIT_RESULT & 0x1ff) == 0x100`; older firmware uses exact
`0xbabeface`. Clear the result before a start and check fault evidence
separately. A retained stale completion word is not a fresh boot proof.

SQE loading excludes its first four-byte header: the native driver allocates
and copies `size - 4`, so this file contributes 31,628 bytes/7,907 words.
That is separate GPU firmware and requires an owned GPU context and later
command-processor initialization.

## HFI layout and initial traffic

The pinned native A620 driver allocates firmware preallocations, then HFI,
then its 4KiB log. With this image the resulting layout is:

| Object | GMU address | Size |
| --- | --- | --- |
| Persistent firmware page | `0x60000000` | `0x1000` |
| HFI | `0x60001000` | Request `0x40e8`, round to five 4KiB pages/`0x5000` |
| GMU log | `0x60006000` | `0x1000` |

The HFI table is six words followed by four 12-word queue descriptors:
216 bytes total. Header fields are `{version=0, size=54, first=6,
descriptor_size=12, queues=4, active_queues=4}`. Descriptor 3 remains disabled,
matching native code even though `active_queues` is 4. Queues 0/1/2 are
command/response/debug, IDs 0/1/2, priorities 10/10/40. Descriptor 3 has
ID 3 and priority 20. Each queue contains 1,024 words. Queue data begins
at HFI `+0xe0`, then advances by `0x1000` per queue.

HFI v2 headers encode ID in bits 7:0, message words in bits 15:8, type in
bits 19:16 and 12-bit sequence in bits 31:20. Pad command writes to four
words with `0xfafafafa`, reserve capacity for padding and avoid publishing
a full ring as `read == write`. The codec rejects zero or 256-word messages
because the wire length is eight bits. The native maximum constant of
256 words does not make a zero wire length valid.

The native start sequence is version verification when needed, performance
table (ID 4), bandwidth table (ID 3), relevant ACD/LM features, then
`CORE_FW_START` (ID 14). A620 does not use the A630/A615 legacy INIT message.
An explicit `FW_VER` (ID 1, two words, supported version `0x20000000`)
can supply fresh bounded HFI liveness before power/performance messages.
The native verifier skips that request if a core version is already known.
Do not invent ARC selectors or DDR/CNOC command data for the tables.

## Source-backed clock and reset-held TCM stage

This stage can examine and exercise local TCM without releasing CM3 or
enabling a DMA context. It needs the separately proved, held CX floor in
[GPU.md](GPU.md), exclusive GPU ownership and fresh CX power completion.
The preferred upstream's reset-held two-word test precedes SMMU/firmware
loading; that is a useful sequence reference, not Redfin hardware evidence.
There is no explicit DDR bandwidth request in that upstream test. The
bounded next stage must keep all GPU/GMU masters stopped, so a TCM readback
does not itself require an invented external DDR bandwidth floor.

| Clock operation | Lito register contract |
| --- | --- |
| Existing GPU configuration path | GCC `+0x71004`, enabled/not halted; retain |
| GPLL0 local vote | GCC `+0x52010`, OR bit 0; preserve other votes |
| Divided GPLL0 feed to GPU | GCC `+0x52000`, OR bit 16; preserve other feeds |
| Inherited GPLL0 identity | GCC MODE `+0`, L `+4`, USER_CTL `+0xc`, ALPHA `+0x40`; Lucid 16-bit fraction |
| Fixed 600MHz source | At 19.2MHz crystal, `L=31`, `ALPHA=0x4000`; require inherited locked/active FSM mode and `/2` USER_CTL bits 11:8 = 1 |
| GMU 200MHz source | GPUCC RCG `+0x1120`, CFG `+0x1124`; source 6 and HID divisor 2 (`300MHz / 1.5`), CFG mask `0x10371f`, value `0x602` |
| RCG update | Preserve initial root-force bit 1; force root during safe configuration, set update bit 0; bound each readiness/update poll to 500us |
| GMU branch | GPUCC `+0x1098`, OR enable bit 0 and native wake/sleep fields `0xff0` |
| Crystal and AHB branches | GPUCC `+0x109c`, `+0x1078`, enable bit 0; AHB uses native 10us delay completion |
| Native bus clocks | GCC `+0x71154` DDRSS GPU AXI, `+0x7100c` GPU MEMNOC, `+0x71018` GPU SNOC DVM; enable bit 0 |
| Native SMMU clock vote | GPUCC `+0x5000`, enable bit 0; does not configure a translation |
| Native GCC handoff setup | GPU MISC `+0x71028` bits 1:0 = 3 disables the GPLL0 active inputs; verify rather than silently changing an unknown handoff |

The native GMU clock list also contains the AOP QDSS/APB clock. Full GMU
boot adds CNOC and a DT-selected minimum DDR bandwidth vote. Its source
uses the native bus client/BCM tables, not a universal scalar selector.
TCM accessibility cannot establish those full-boot prerequisites.

No GPU PLL1 or GX clock setup is needed to derive 200MHz from the inherited
fixed GPLL0. Do not copy the SC7280 150MHz hub RCG/branches or change GPLL0
L/ALPHA/postdivision. Source-register identity proves the programmed rate;
direct measurement supplies a separate clock observation.

The optional Lito debug measurement contract differs from Redwood:
GCC mux/divider/CBCR `0x62000/0x62004/0x62008`, GPUCC selection **`0x129`**;
measurement control/status `0x62038/0x6203c`, XO/4 gate **`0x4300c`**.
GPUCC mux/divider/CBCR `0x1568/0x10fc/0x1100`, divider mask **3**, and
AHB/CX_GMU/CXO selections **`0x10/0x18/0x19`**. An exclusive debug-mux
lease and saved complete state are required before any such measurement.

GMU CSRs are native GPU-relative word indices, converted by
`(word_index - 0x1a800) * 4` for the Redfin GMU mapping:

| CSR | GMU byte offset |
| --- | --- |
| ITCM / DTCM | `0x3000` / `0x7000` |
| CM3_SYSRESET / BOOT_CONFIG | `0x14000` / `0x14004` |
| CM3_FW_INIT_RESULT / CM3_CFG | `0x14070` / `0x140b4` |
| Always-on crystal counter low/high | `0x14220` / `0x14224` |
| HFI_CTRL_STATUS / HFI_SFR_ADDR | `0x14600` / `0x14608` |
| HFI_QTBL_INFO / QTBL_ADDR / CTRL_INIT | `0x14610` / `0x14614` / `0x14618` |

Read the CM3 reset and completion state before a TCM write. A running or
ambiguous inherited GMU is not an idle SRAM owner. In a proved idle/reset
session, assert/retain reset 1, save two DTCM words, write two non-executable
patterns, read both back, restore both and verify restoration. Never release
reset in this stage. Recheck the caller's lifetime/power/clock lease before
every access. A lost lease or failed MMIO stops access immediately; keep
reset held and return through the bounded platform-reset path. The 19.2MHz
counter is a crystal/bus liveness observation, not proof of the GMU core rate.

## Remaining full-boot and secure-GPU contracts

The native A620 path programs the GPU PDC at `0x0b290000`/`0x0b490000`
and RSC at `0x03de0000`. A620 does **not** set A650's `pdc_in_aop` flag.
PDC commands use source-discovered `xo.lvl`, `cx.lvl`, `mx.lvl` and,
for A620 when present, `vrm.soc + 4`. Do not reuse RSC/PDC values from
an A650 or A642L board without checking the A620 branch and CMD-DB.

Before CM3 starts, every planned DMA range, HFI, log and page-table page must
be owned, zeroed/initialized, cache published, retained and mapped. Native
GMU kernel/user streams are 5/4 with mask `0x400`; these are stream IDs,
not context-bank numbers. The native driver allocates context banks and
sets no-stall fault behavior (`SCTLR.CFCFG=0`, default `HUPCF=0`). Upstream's
chosen context bank 1 is not a Redfin ownership proof. The live FDT's HYP
protection and secure-global-write ABI require independent validation.

The zap node selects PAS **13**, distinct from modem PAS 4. Native order is
`INIT_IMAGE(13, metadata_pa)` with `SCM_ARGS(2, SCM_VAL, SCM_RW)`,
`MEM_SETUP(13, region_pa, region_bytes)`, load the permitted ELF segments,
then `AUTH_AND_RESET(13)`. Check transport and secure return status
separately. Never treat MDT program addresses as host physical addresses.
The observed zap has a relocatable PT_LOAD payload `.b02`; `.b00` and the
hash `.b01` are not ordinary load segments. Bit 27 selects relocation,
hash type is flags bits 26:24 == 2, and the payload's alignment is 1MiB.
It needs a separately reserved physical region and a proved PAS lifetime.
No SCM call is implemented or issued by the planner.

`redfin_gmu_fw_load()` is a bounded callback transfer helper. It reparses the
whole immutable blob before calling the adapter, obtains one complete
read-only preflight, guards every write/read, publishes once and verifies
each payload. It does not start CM3. Invalid files reach no adapter callback.
After an attempted transfer fails, a caller must keep reset asserted and
retain all backing memory until a proved context shutdown or platform reset.
The helper reports attempted/completed/verified payload counts so a partial
MMIO failure is distinguishable from a refusal before writes.

Run `python3 -m unittest ports/redfin/test_gmu_firmware.py`. The 22 host
tests compile this header on ARM64 and cover the generated 41,548-byte
shape, every truncation, all 2,048 header-bit mutations, plan bounds,
HFI buffer fences/ring padding, complete transfer/readback and terminal
preflight/ownership/partial-write/publish/verification failures. These are
software tests; no device result or kernel build is claimed.

[hackios]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[gpulist]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/adreno-gpulist.h
[gmuc]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/adreno_a6xx_gmu.c
[gmuh]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/kgsl_gmu.h
[gmu]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/kgsl_gmu.c
[hfih]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/kgsl_hfi.h
[hfi]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/kgsl_hfi.c
[regs]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/gpu/msm/a6xx_reg.h
[gcc]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gcc-lito.c
[gpucc]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gpucc-lito.c
[pll]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/clk-alpha-pll.c
[rcg]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/clk-rcg2.c
[branch]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/clk-branch.c
[debug]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/debugcc-lito.c
[pil]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/soc/qcom/subsys-pil-tz.c
[loader]: https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/soc/qcom/peripheral-loader.c
[dt]: https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito-gpu.dtsi
