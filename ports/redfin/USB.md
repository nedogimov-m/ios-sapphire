# Redfin USB handoff probe

`usb-probe.patch` adds a separate `bsd/dev/redfin_usb.c` and calls it from
`IOKitBSDInit.cpp`, after verified bootloader return and before UFS. It also prevents
`sweet_usb_probe()` from accessing Sapphire registers on a Redfin ADT.
The Redfin builder applies it with `usb-route.patch`; both default off.

`redfinusb=1` enables the core snapshot; `redfinusb=2` additionally enables
the read-only SMMU route observer. Other values perform no MMIO. The ADT root must contain the exact compatible strings
`google,redfin` and `qcom,sm7250`. Mode 2 also requires a validated
`/redfin-usb-route` contract generated from the live FDT by `build.py`.

The probe reads GCC first. It requires GDSC power-on with software collapse
clear, deasserted core reset, and enabled/nonhalted master, config-NoC,
aggregate AXI, sleep and mock-UTMI clocks. It then reads DWC3's ID; only a
`0x5533xxxx` DWC3 reaches the global snapshot. Device registers are read only
when GCTL selects device mode. No clock/reset/PHY/SMMU/controller register is
written; no event is acknowledged and no DMA allocation or gadget is started.

## Verified hardware contract

The saved `research/redfin-root/device.dtb` agrees with these pinned sources:

- [lito-usb.dtsi](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito-usb.dtsi):
  wrapper `0x0a600000+0x100000`; DWC3 `0x0a600000+0xcd00`; SPI 240
  (GIC INTID 272); DRD, maximum SuperSpeed. Parent SMMU stream `0xe0`,
  DMA IOVA pool `0x90000000+0x60000000`; child uses the parent's DMA device.
- [lito-gdsc.dtsi](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito-gdsc.dtsi):
  USB GDSCR `0x0010f004`. Saved FDT has GCC `0x00100000+0x1f0000`.
- [gcc-lito.c](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gcc-lito.c):
  BCR `0xf000`, master CBCR `0xf010`, mock-UTMI `0xf01c`, sleep `0xf018`,
  config-NoC `0xf07c`, aggregate AXI `0xf080` relative to GCC. These are
  different from the inherited Sapphire GCC base and several offsets.
- [gdsc-regulator.c](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gdsc-regulator.c):
  `PWR_ON_MASK=BIT(31)`, `SW_COLLAPSE_MASK=BIT(0)`.
- HS PHY is Synopsys femto `0x088e3000+0x110`, with EUD enable at
  `0x088e2000`. It is not the older QUSB2 PHY. The DT names PM8150 L5/L12/L2
  supplies and RPMh CXO; the saved DT agrees. The QMP USB/DP PHY is
  `0x088e8000+0x3000`.
  [phy-msm-snps-hs.c](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/usb/phy/phy-msm-snps-hs.c)
  enables rails and clocks, resets the PHY and programs its UTMI/PLL fields.
  This patch preserves all PHY state and does not claim cold initialization.

Linux recovery reported `a600000.dwc3` configured at high speed, with
`usb_dwc3_msm`, `phy_msm_snps_hs`, `phy_msm_ssusb_qmp` and `arm_smmu`
loaded (`research/redfin-peripherals-v1/usb.txt`). This establishes the Linux
path; it does not establish the state left by ABL during `fastboot boot`.

## DMA and handoff still to establish

The inherited CDC-ECM implementation in `sweet_usb.c` has a 16 KiB contiguous,
page-aligned slab containing its 4 KiB event ring, TRBs and packet buffers.
Its allocation and offsets fit XNU's 16 KiB page size. It uses `pmap_find_phys`
and writes the physical address directly to DWC3; there is no USB SMMU setup.
Its explicit cache maintenance must remain in a future Redfin port. The
4 KiB event ring does not require 4 KiB CPU translation pages.

The Redfin FDT identifies `apps-smmu@15000000` as `qcom,qsmmu-v500`, with
`qcom,skip-init`. In
[arm-smmu.c](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/iommu/arm-smmu.c),
that option preserves stream mapping groups and context-bank setup. It does
not prove that USB stream `0xe0` bypasses translation. Before starting any
event or endpoint DMA, establish its actual SMR/S2CR/context mapping and
prove reachability of the new slab. Do not globally reset or bypass SMMU:
other masters, including the active filesystem, share it.

XNU RAM starts above 4 GiB. `GHWPARAMS0.AWIDTH` is therefore recorded as the
controller's address-width capability; `MDWIDTH` is its data bus width and
does not prove 64-bit addressing. A Linux 32-bit fallback or an inherited
IOVA mapping cannot be assumed to cover XNU memory. CPU and SMMU translation
granules are separate contracts; the CPU's 16 KiB mapping is not an SMMU table.

The authenticated V3 snapshot reached DWC3: `GSNPSID=0x5533330a`, device
mode, `AWIDTH=64`, `DCTL=0x10f00000` (RUN_STOP clear), event-ring address
`0xa2448000`, size `0x80001000`, count zero. All five USB clocks and GDSC
passed the observer gates. This is a useful warm handoff, with no DMA or
PHY writes. Halt/quiescence, PHY/VBUS state and the SMMU route still need
verification before a CDC-ECM reset/start sequence can be enabled.

The V4 RAM diagnostic read the standard SMMU configuration successfully:
`ID0=0x4c017e51`, `ID1=0x6000003e`, `ID2=0x5111`, `CR0=0x2c0406`.
All 81 SMRs were stable; none matched SID `0xe0`. `CLIENTPD=0` and
`USFCFG=1` select an unmatched-stream fault, so the inherited ring address
does not establish reachability. No context bank or table was read. The
observer requires halted DWC3 and its masked 4 KiB event ring, rechecks
every SMR and each matching S2CR, and never writes SMMU registers.

`ID2` advertises 4 KiB/64 KiB table support, without 16 KiB support. A
native USB backend needs its own proven stream route and DMA memory; XNU's
16 KiB allocations can contain separate 4 KiB tables. Globally clearing
`USFCFG` would also change policy for other devices and is not an ownership
mechanism. With no match, selecting or walking an arbitrary context bank
cannot supply the missing route. V4 evidence is AES-GCM authenticated;
its collector did not capture a pre-boot baseline, so freshness alone was
not established by authentication. Local capture: `logs/redfin/peripherals-v4-ram/`.

Validation: `python3 -m unittest ports/redfin/test_usb_probe.py -v` executes
the actual added C against fake MMIO, checks every clock mask, platform/mode
rejection, mapping failures, core ID/device-mode fences and unchanged MMIO.
`git apply --check ports/redfin/usb-probe.patch` must run in the prepared XNU
tree using the patch's absolute path. No device boot or kernel build was
performed while preparing this overlay.
