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
