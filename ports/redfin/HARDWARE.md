# Pixel 5 / redfin hardware evidence

Source and live FDT evidence; not proof of a working XNU boot. The RAM map is
captured; framebuffer scanout is still unknown. Values: `hardware.json`.

Pinned Google Android 14 QPR3 sources:

- [Lito DTS](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito.dtsi), commit `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`: CPU affinities `0x000..0x700` in steps of `0x100`, domains **6+1+1**, PSCI 1.0 **SMC**; GICv3 distributor `0x17a00000`, redistributors `0x17a60000`, stride `0x20000`.
- Same DTS: timer **19.2 MHz**, PPI indices **1/2/3/0** = INTIDs **17/18/19/16** (secure physical / nonsecure physical / virtual / hypervisor), level-low. Validate against the bootloader FDT before enabling IRQs.
- [UFS board configuration](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/arch/arm64/boot/dts/google/lito-redbull-common.dtsi), commit `500b3a2059c1eec0fec08ec56add06320ea901a8`: QMP v4 Lito PHY; UFS host `0x01d84000`, PHY `0x01d87000`, ICE `0x01d90000`, SPI 265. It needs Lito clocks, reset and PM8150 supplies; changing the MMIO base alone does not implement cold initialization. [GCC source](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gcc-lito.c) places UFS reset at GCC `0x00100000 + 0x77000`.
- [USB DTS](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito-usb.dtsi): DWC3 `0x0a600000`, SPI 240, SMMU stream `0xe0`. A working USB controller driver still needs PHY, clock and SMMU handoff.
- [Display reservation](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito.dtsi): continuous-splash pool `0xa0000000 + 0x02300000`. [Redfin panel](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/arch/arm64/boot/dts/google/dsi-panel-s6e3hc2-dvt-dsc-1080p-cmd.dtsi): **1080×2340**, command mode, DSC, 24-bit panel input, 60/90 Hz. This does **not** establish the scanout address, pitch or memory pixel format. [SDE DTS](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito-sde.dtsi) uses display SMMU and `qcom,iommu-earlymap`; a source address read from an SSPP may be an IOVA.
- [BoardConfig](https://android.googlesource.com/device/google/redbull/+/3595d0b214eeeddf87e2c37477e3e74f831eca82/BoardConfig-common.mk), commit `3595d0b214eeeddf87e2c37477e3e74f831eca82`: boot header **v3**, pagesize **4096**, kernel base `0`, vendor_boot support; stock command line identifies `soc/1d84000.ufshc` and `a600000.dwc3`.

`/memory/reg` is a zero placeholder in the source DTS, populated by ABL.
[Google memory overrides](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/arch/arm64/boot/dts/google/lito-redbull-memory.dtsi)
add firmware and debug carveouts. Live root ADB captures (2026-10-21), stored
outside git under `research/redfin-root/`, establish these banks:

| Base | Size | Exclusive end |
| --- | --- | --- |
| `0x80000000` | `0x3bb00000` | `0xbbb00000` |
| `0xc0000000` | `0xc0000000` | `0x180000000` |
| `0x180000000` | `0x100000000` | `0x280000000` |

All live `/reserved-memory` nodes and Linux `iomem` reserved ranges are recorded
in `hardware.json`; the FDT header reservation map is empty. The splash reserve
is confirmed at `0xa0000000 + 0x2300000`; DFPS adds `0xa2300000 + 0x100000`.
The kernel registry carveout is `0xc8000000 + 0x10000`. Dynamic FDT pools allocate
below 4 GiB. Linux also reserves `0xedc00000..0xffbfffff` and ranges at/above
`0x275db8000`. Do not infer free memory from the bank list alone.

Candidate XNU window: **`0x180000000 + 0x80000000` (2 GiB)**, exclusive end
`0x200000000`. It is inside one live RAM bank, aligned for 16 KiB pages and
2 MiB blocks, and intersects no fixed FDT, header or Linux `iomem` reservation.
Revalidate the incoming ABL FDT and shim/payload/initrd/ADT overlap at handoff.
This is a temporary-boot allocation candidate, not permission to write into
RAM while Android is running.

Bring-up blockers: inherited Sapphire framebuffer `0x5c000000` and UFS
`0x04804000` are wrong for Redfin; inherited GIC, interrupt numbers and CPU
selection also require replacement. Establish RAM ownership and an observable
early diagnostic channel before any framebuffer writes or payload relocation.
Use temporary boot images; preserve stock boot, vendor_boot and DTBO.

Local observations (2026-10-21): Android is accessible over ADB, reports Redfin,
8 GB RAM and an unlocked bootloader. **Root ADB succeeded**: FDT and `iomem`
were captured. Live CPU affinities, GIC, timer, UFS and DWC3 match the values
above. Panel scanout and UFS HCE/HCS registers have not been captured.
ABL must read storage before entering the shim, so preserving its initialized
UFS PHY/clocks/host is a possible first probe; verify HCE/HCS and outstanding
transfers before takeover, and avoid an unconditional reset. Android's current
UFS state does not establish the later ABL handoff state.
No device identifiers or raw dumps belong in this directory.

Temporary diagnostic boot (2026-10-21): **fastboot returned OKAY** after the
ARM64 Image `text_offset` at byte 8 changed from `0` to **`0x80000`**, keeping
the otherwise identical LZ4 image. Stock Image uses `text_offset=0x80000` and
flags `0xa`. The accepted packaging is boot v3 with a standard LZ4 kernel frame
and a trailing four-byte little-endian uncompressed length. Raw Image with
offset zero failed `Unsupported`; adding an unsigned AVB footer did not fix it.
LZ4 with offset zero also failed; the controlled offset change fixed acceptance.
Raw Image with offset `0x80000` has not been tested, so compression has not been
shown to be required. Subsequent execution was confirmed by the user seeing
REDFIN DIAGNOSTICS. XNU then reached BSD and executed the static PID1; RAMLOG
captured its first syscall. The splash reservation start with 4320-byte pitch
and 1080x2340 pixels is therefore observed working on this unit.
