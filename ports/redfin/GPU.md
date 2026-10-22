# Redfin Adreno 620

The saved live FDT identifies chip `0x06020001`, GPU registers at
`0x03d00000`, GPUCC at `0x03d90000`, GPU SMMU at `0x03da0000` and a real
GMU at `0x03d6a000`. Native Linux recovery reports **Adreno620v2**, with
275/400/500/625 MHz operating points. Sapphire's Adreno 610 GMU-wrapper
initialization is incompatible; keep inherited `gpu=0`.

`--gpu-probe` adds `redfingpu=1` and an exact, validated `/redfin-gpu` ADT
contract. It first reads GCC configuration/memory clocks. GPUCC is read
only when GCC's GPU configuration AHB branch is enabled and not halted.
The observer reads clock-control registers; it neither accesses GPU/GMU/
SMMU registers nor changes clocks, power domains or firmware. Other modes
are rejected. This observer provides no rendering acceleration.

Authenticated V3 observation: configuration AHB is active, while CX/GX
GDSC software-collapse bits are set, power-on bits clear, and GMU/GX/SMMU
clock branches halted. GPU power/firmware initialization is required.

Pinned sources:

- Google msm `500b3a2059c1eec0fec08ec56add06320ea901a8`,
  `drivers/clk/qcom/gcc-lito.c`: config AHB `0x71004`, memory NOC `0x7100c`,
  SNOC DVM `0x71018`.
- Same commit, `drivers/clk/qcom/gpucc-lito.c`: AHB `0x1078`, CX APB `0x1088`,
  CX GMU `0x1098`, SNOC DVM `0x108c`, CXO `0x109c`, GX GMU `0x1064`,
  GMU RCG `0x1120`, SMMU vote `0x5000`.
- Google devicetree `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`,
  `qcom/lito-gpu.dtsi`: GMU, context-bank streams and firmware region;
  `qcom/lito-gdsc.dtsi`: CX/GX GDSC `0x106c`/`0x100c`.
- Google msm at the same pin, `drivers/gpu/msm/adreno-gpulist.h`, A620:
  `a650_sqe.fw`, `a650_gmu.bin`, signed `a620_zap`, GMU interface 2.0.

Hardware acceleration first needs RPMh/regulator/GMU power sequencing,
signed firmware loading, a bounded SMMU/DMA allocation and a completed GPU
command with verified RAM output. Rendering then requires command/shader
support and an iOS graphics interface. Existing CPU framebuffer capture
proves lock-screen rendering only; it does not prove any GPU command.

The bounded host `super_inventory.py` can identify base vendor_b extents from
checksummed liblp metadata; see [vendor inventory](WiFi.md#bounded-base-vendor-inventory).
The observed Virtual A/B COW entries leave the effective snapshot unproved.
Inventory of a650 SQE/GMU and signed a620 zap assets is separate from GPU
power-up or firmware loading, and all captured bytes remain private.

The targeted base-vendor pass now has a650 SQE31,632 bytes, GMU41,548 bytes
and a620 zap MDT plus original b00/b01/b02 blobs. Host hashes and filesystem
read coverage are retained privately; no GPU power, SCM/PAS or firmware load
was attempted. The source remains explicitly the raw vendor base view.

## CX power prerequisite: ARC parent vote

The captured Redfin FDT adds a dependency absent from the base
`lito-gdsc.dtsi` fragment. The complete live chain is:

| Node | Relevant contract |
| --- | --- |
| `/soc/qcom,gdsc@3d9106c` | `gpu_cx_gdsc`, register `0x03d9106c+4`; both `parent-supply` and `vdd_parent-supply` reference the regulator below |
| `/soc/rsc@18200000/rpmh-regulator-cxlvl/regulator-pm8150-s1-level` | `pm8150_s1_level`, `qcom,set=3` (active and sleep); minimum consumer level16, maximum65535; no boot-on/always-on property |
| `/soc/rsc@18200000/rpmh-regulator-cxlvl` | `qcom,rpmh-arc-regulator`, resource `cx.lvl` |

The CX node also references `/soc/syscon@3d91540` as `hw-ctrl-addr`, has a
500us GDSC timeout and `qcom,clk-dis-wait-val=8`. The existing `/redfin-gpu`
GCC/GPUCC ranges and chip ID do **not** describe or prove this parent supply.

At Google msm pin `500b3a2059c1eec0fec08ec56add06320ea901a8`,
[`gdsc-regulator.c:220`](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gdsc-regulator.c#220)
requests `RPMH_REGULATOR_LEVEL_LOW_SVS` on `vdd_parent` before clearing
`SW_COLLAPSE`. Its DT parser resolves both supply properties. The pinned
`qcom,rpmh-regulator-levels.h` defines LOW_SVS as **64**, a consumer corner
number, not microvolts or millivolts. Therefore a bare CX collapse-bit write
does not reproduce the Redfin power sequence. The isolated CX power
experiment described below supplies a bounded parent request before that
write. Firmware, GMU, GX, SMMU, reset and DMA writes remain disabled there.

The authenticated earlier RPMh observation found `cx.lvl` as ARC type3,
address `0x30000`, aux version `0x1000`, 32 auxiliary bytes. Its raw
little-endian level table was
`[0,16,64,128,192,256,384,416,0,0,0,0,0,0,0,0]`.
The pinned
[`rpmh-regulator.c:1317`](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/regulator/rpmh-regulator.c#1317)
ends the table at the first zero after index0. Hardware selectors0..7
therefore map to consumer corners0,16,64,128,192,256,384,416. LOW_SVS64
requires **selector2**, never a raw command value64. This table must be
looked up and validated freshly; it is metadata, not a physical voltage
measurement or a current-vote readback.
The resource address is carried inside an RPMh command; it is not a
physical MMIO address to pass to `ml_io_map`.

The existing `redfin_rpmh.h` reader already bounds and validates CMD-DB ARC
metadata, and the observer snapshots DRV2 ACTIVE/SLEEP/WAKE TCS state.
That is useful for a separate read-only parent-supply audit. It does not
prove the currently latched `cx.lvl` floor. A completed ACTIVE transaction
can leave its vote latched after its command slots become empty; sleep/wake
templates describe future requests. A free TCS is a transport resource,
not an independent ARC voter. Writing selector2 through another DRV2 TCS
can replace a higher existing DRV2 vote. Preserving other masters' votes
does not by itself preserve this master's inherited floor.

The inspected HLOS driver offers no proven hardware readback of that
latched or aggregate ARC value:
[`rpmh_regulator_arc_get_voltage_sel`](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/regulator/rpmh-regulator.c#1186)
returns its software request cache. RSC command data, status and response
registers are not an established aggregate-voltage interface. No new ARC
MMIO address or read transaction is authorized by the current contract.
Physical S1 VSET alone would also need a validated CPR/corner mapping.
Even an aggregate level above LOW_SVS would need a held-floor argument:
another master's temporary vote may disappear while CX is enabled.

The touch backend is deliberately different: it votes a fixed PLDO VRM
voltage/mode/enable triplet and verifies physical L17 state through SPMI.
Its numeric values and physical proof cannot be reused for ARC.

### Isolated held CX experiment

`--gpu-power-probe --return-bootloader` selects a separate CPU0/md0 test.
It rejects GUI, UFS, splash, touch, USB, SMP and other diagnostic profiles.
The live FDT parent/status phandles, regulator bounds and timeout must match
before the builder emits a separate `/redfin-gpu-power` contract. The kernel
checks that contract, the exact boot arguments, EL1/CPU0 and verified PMIC
return before mapping the fixed GCC/GPUCC/RSC/GIC/CMD-DB ranges.

`gpu-power.h` validates the complete table above and requests its **highest
legal selector7/corner416**. This bounds the unknown inherited DRV2 request:
no legal selector in the frozen table exceeds7, so the held request cannot
lower that master's inherited level. This is deliberately above LOW_SVS;
it is a short reset-bounded bring-up setting, not a runtime voltage policy.
Every inherited enabled `cx.lvl` command must also have a legal selector.

Both ACTIVE TCS slots must be idle/empty, all eight TCS snapshots stable and
RSC IRQ37 masked/inactive. Only ACTIVE0 is written. Fresh local completion,
command status and idle are required, then its transient registers/IRQ are
cleared and all inherited templates rechecked. The ARC vote stays held until
platform reset. Only then may the single CX `SW_COLLAPSE` clear occur; the
separate live-DT hardware-status register `GPUCC+0x1540` must report power-on
within the bounded poll. No vote-down or rollback of an uncertain transaction
is attempted. GX, GMU, GPU core, SMMU, firmware and DMA remain untouched.

Five host tests execute the actual leaf with malformed metadata, ownership,
handoff, changed-template, write, IRQ/status/idle and domain-timeout faults.
Native ARM64 build040531 succeeds. Device results are recorded in `NOTES.md`;
this CX experiment by itself provides no graphics acceleration. The next
stage is a separate reset-held GMU clock/counter/TCM test in [GMU.md](GMU.md).
