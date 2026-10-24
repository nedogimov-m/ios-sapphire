# A620 command backend

`--gpu-command-start --gpu-assets-inventory PRIVATE/host-inventory.json`
selects one complete CPU0/md0 run, `redfinsmmu=5`. It includes owned GMU
memory/firmware, PDC/RSC/CM3, fresh HFI version exchange, performance and
bandwidth tables, GX/OOB, GPU memory/context, SQE, signed PAS13 zap and
command completion with four actual GPU-written words. The original root
and the working GUI/Wi-Fi image are not needed by this RAM-only profile.
The existing temporary-boot return contract is mandatory.

The preferred kernel reference is HackiOS
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`, `redwood_adreno.c` steps17–21.
Hardware details come from Google msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`, `adreno_a6xx.c`,
`adreno_a6xx_gmu.c`, `adreno-gpulist.h`, `a6xx_reg.h`, `kgsl_gmu.c`,
`kgsl_hfi.c/.h`, `peripheral-loader.c`, `subsys-pil-tz.c` and
`msm_bus_{arb,fabric}_rpmh.c`. DT reference remains
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`; the builder validates the
actual captured Redfin FDT. No userland graphics ABI is published here.

## One complete native chain

GMU firmware may set HFI-ready before the host's CTRL_INIT. Zero HFI is
therefore required while reset-held, followed by fresh INIT0→100, the explicit
native CTRL_INIT write, and a matched version ACK. Subsequent messages use
the same variable-length, padded, wrapping queues, unique sequences and full
request echoes. An ACK additionally requires actual command-consumer progress.
Stale/malformed responses, firmware errors and timeouts stop the whole run.

Only off/275MHz are advertised in the GPU performance table. The 275MHz/64
OPP occurs in every captured speed bin, with bus use case5. Native ARC votes
are computed from the real gfx/cx/mx CMD-DB level arrays; the GMU remains
at200MHz/CX minimum-SVS. The full13-entry native DDR use-case table is
converted through SH0/MC0/ACV, and CNOC's two native entries through CN0.
CMD-DB supplies addresses, units, widths and VCDs. Rounding upward avoids
under-voting fractional units. VCD order determines command order/commit/wait
bits. GX requests275MHz with DDR case5, not upstream's A642L frequencies.

The native CORE_FW_START transition can change GX state. Only that explicit
mode5 phase admits it; core access additionally requires a fresh OOB grant,
SPTPRAC accessible status and live GX GDSCR. There is no direct GX GDSC/PLL
override. The OOB request and all resources remain held until platform reset.

Private contiguous wired ring/SQE/scratch/table objects have proven host/PA
ownership in XNU's validated RAM window. A separate CB0 is claimed only if
disabled and unreferenced, with fresh exact global/CB0/CB1 audits before each
store. Two unused slots encode SID0 and SID1 with mask400, equivalent to
native SID0/mask401; this also avoids upstream's observed combined-mask HYP
behavior. CB1/GMU, SID2 secure routing and every foreign raw word stay audited.
CB0 uses39-bit/4KiB/36-bit LPAE, ASID2, native HUPCF, with no stall/IRQ.
Ring at01000000 is32KiB; SQE at01100000 is read-only and skips the firmware's
first header word. Scratch at01200000 has an uncached CPU view before DMA.
Only the required pages are mapped; adjacent scratch pages stay unmapped.

The signed zap is **dynamically allocated**, as the native generic PIL
binding. The actual kgsl-hyp node has no memory-region. The ELF's one loadable
relocatable b02 has base5000, filesz/memsz68c, alignment1MiB; native PIL uses
a1MiB allocation and4KiB load span. Its metadata/hash headers are not load
segments. The unrelated unaligned8bc15400 reservation is neither rounded
outward nor written. Metadata initially occupies the owned allocation, as
native PIL. Only successful PAS13 INIT_IMAGE and MEM_SETUP authorize the
segment copy/zero. AUTH_AND_RESET must succeed in both SCM transport and
secure return value. All calls use the proven native SCM64 `420002xx`
encoding, bounded interrupted continuations/cookies and busy handling.
An initialization failure never means an inherited zap is acceptable.

PAS authentication gets the native crypto125→EBI512 BCM floor requests
CE0/SN6/SN0/SH0/MC0/ACV. DRV2 ACTIVE0 is reused only after the CX owner
has returned it idle; other TCSs and inherited floors/ACV bits are preserved.
No modem vote or PAS4 operation is included.

Core initialization uses the native A620 register values/protection spans,
UBWC3/bank14/min-access32, FIFO threshold10000 plus native TSE-skip disable,
hang cycles3ffff, native APRIV and a valid RPTR shadow address. HWCG,
preemption and IFPC are not enabled in this bounded polling owner; no
A642L LPAC or UBWC4 workaround is imported. CP_ME_INIT uses native11-word
layout with optional register-list ordinal8 omitted instead of pointing at
unmapped memory. After signed zap load, CP_SET_SECURE_MODE0 precedes two
CP_MEM_WRITE submissions with four boot-ID-derived values. Queue completion
alone is insufficient: uncached scratch words must match, with no SMMU/CP
fault and complete foreign-state audit.

All resources remain allocated on success **and failure** until the already
armed reset. No global SMMU reset, foreign fault W1C, secure SID change,
firmware retry, PAS shutdown or guessed rollback is provided. Successful
host tests/build establish protocol behavior, not actual hardware execution.
Hardware results and exact image/boot identities are recorded in NOTES.md.

The iOS graphics/Mesa/Metal bridge is subsequent work. A command backend
does not itself provide Metal or accelerate SpringBoard.
