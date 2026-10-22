# Physical touch-rail evidence

`touch-rail-observe.patch` appends `int redfin_touch_rail_observe(void)` to
`redfin_spmi.c`; it leaves the fixed PON reader unchanged. There is no startup
hook or rail-ready API. `redfinrail=1`, `cpus=1`, verified SPMI/bootloader-return
proof and exact Redfin/Lito compatible tokens are required before hardware
access. The function uses the existing mappings and runs once per boot.

The saved Redfin FDT connects touch AVDD to `pm8150_l17` / `ldoa17`, with
min/max/init voltage **3,304,000 uV**. It supplies no physical L17 register
address. A nonzero RPMh vote or an empty ACTIVE-TCS is not a physical power
measurement.

The observer first reads SID0 REVID `0x0104/0x0105`; type `0x51`, subtype
`0x1e` must identify PM8150. It then inspects candidate SID1 pages
`0x4000..0x5100`, using only APIDs whose PPID exactly matches that SID/page.
Every transaction revalidates the arbiter version, full APID mapping and
write owner before issuing EXT_READL and after receiving its data. Owner
selection follows Linux's EE0 preference; observer reads do not require
write ownership. Missing APIDs are reported without claiming physical absence.

Every candidate gets two type/subtype reads. Only known unified LDO subtypes
`30/31/32/35/3b/3c/3d`, and the exact PM8150 subtype `7d` observed in V6,
permit the following additional reads, repeated after
100 us:

| Offset | Observed field |
| --- | --- |
| `04/05` | Type/subtype; LDO type is `04` |
| `40/41` | Little-endian 16-bit voltage in mV |
| `45/46` | Raw mode and enable control |
| `08` | Raw status; bit 7 is unified VREG_READY |

No PMIC register is written. Observer command writes encode only fixed-target
EXT_READL, one or two bytes. Error/timeout stops all transactions; the
one-shot guard prevents reuse after a late completion. Changed samples return
`EAGAIN`, APID holes `ENXIO`, wrong PMIC model `ENOTSUP`. Success means the
diagnostic completed; it does **not** authorize touch reset or SPI setup.

The `7d` raw-read permission comes from Qualcomm's explicit generic branch:
`type == LDO && subtype >= HT_N300_STEPPER (0x30)` selects the unified register
layout in `pm_ldo_driver_init`. It is not an inference from subtype-number
similarity. The observer does not authorize PMIC5 voltage/mode policy; no vote
backend or readiness decision may use the old `HT_P150 (0x35)` range for `7d`.
Linux v6.12 maps PM8150 L17 to `pmic5_pldo`, whose logical range is
`1504 + selector*8` mV, selector `0..255`, hence **1504..3544 mV**. Thus the
board's 3304 mV target is not this hardware class's maximum voltage.

V6 observations, 2026-10-22: the authenticated, boot-ID-matched RAM capture
read PM8150 REVID type `51`, subtype `1e`. All 18 SID1 candidate pages
`4000..5100` had consecutive APIDs `85..102`, write owner `4`, peripheral
type `04`, and stable repeated headers. Their subtypes in ascending page
order were `6b,7b,6c,6a,6c,6c,73,6b,6c,7d,6c,72,7b,72,73,7c,7d,6b`.
In particular, page `5000` was APID `101`, subtype `7d`. V6 correctly read no
voltage/mode/enable/status fields because that subtype was then header-only;
`unified=0` described the observer's old allowlist, not hardware incapability.
L17 indexing and physical AVDD readiness were still unproved.

The subsequent board attribution combines source and V6 runtime evidence:
Qualcomm's common LDO base is `4000`, stride `100`; ascending peripheral
discovery and the LDO driver's base-relative index formula assign `LDO1=0`,
`LDO17=16`. Linux's PM8150 table explicitly lists LDO1 through LDO18 and maps
LDO17 to `pmic5_pldo`. V6 verified all eighteen consecutive type-04 pages,
anchored by the physical PM8150 model read. This establishes SID1 page `5000`
as L17 for this observed board via peripheral ordering, not APID-number
arithmetic. Missing APIDs alone would not establish physical absence.
The observer still publishes no indexing proof or readiness API. Its next
sample must establish physical power; VREG_READY alone does not suffice.
Regulated HPM mode `7` is a conservative future requirement, and bypass must
be rejected.

Sources:

- Google msm `500b3a2059c1eec0fec08ec56add06320ea901a8`,
  `drivers/spmi/spmi-pmic-arb.c`, `drivers/mfd/qcom-spmi-pmic.c`,
  `drivers/platform/msm/qpnp-revid.c`, `include/linux/qpnp/qpnp-revid.h`.
- [Qualcomm firmware `20bb8ae`](https://github.com/Rivko/android-firmware-qti-sdm670/tree/20bb8ae36c93fc16bbadda0e0a83f930c0c8a271/boot_images/QcomPkg):
  `Settings/PMIC/pm_config_common.c` gives common base/stride and register offsets;
  `Library/PmicLib/drivers/ldo/src/pm_ldo_driver.c` defines unified mV layout;
  `drivers/pwr/src/pm_pwr_alg.c` defines VREG_READY and mode interpretation.
  This firmware targets another PMIC; its common layout is not a PM8150 table.
- Same firmware: `Include/api/pmic/pm/pm_ldo.h:53,69,99` defines zero-based
  LDO indexing and `LDO17=16`; `Library/PmicLib/framework/src/pm_resource_manager.c:139..159`
  discovers peripherals in ascending order, with `base=index*0x100` at line 153;
  `drivers/ldo/src/pm_ldo_driver.c:94,116` saves the first base and computes the
  base-relative index. The V6 header observations supply the runtime anchor.
- [Linux v6.12 `qcom_spmi-regulator.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/regulator/qcom_spmi-regulator.c)
  provides the explicit known-subtype allowlist and matching unified voltage layout.
- [Linux v6.12 `qcom-rpmh-regulator.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/regulator/qcom-rpmh-regulator.c#L991)
  lists PM8150 LDO1..18; LDO17 uses `pmic5_pldo` at line 1018. Its range is
  defined at line 705, and its PMIC5 LDO HPM vote is raw value 7.

# Prospective owned ACTIVE vote

V5 observed `ldoa17=0x41300`, DRV2 `0x18220000`, major 2, NCPT 16, eight normal
TCS slots, ACTIVE0/1 empty, RSC IRQ enable `1`, status `0`, and GIC INTID37
masked with no pending/active bit. Recheck every fact immediately before a
future write. Use one software owner and keep every other RPMh client disabled.
An empty TCS does not reveal votes retained by VRM after older transactions.

The pinned Linux `rpmh-rsc.c` supplies the protocol: TCS base `+d00`, stride
`2a0`, commands `+30 + 14*c`; waited write MSGID `0x10108`; WAIT and ENABLE
bits `7`; clear trigger, set AMC enable bit 16, then trigger bit 24. A candidate
batch is voltage `0x41300=3304`, HPM `0x41308=7`, enable-last `0x41304=1`.
The pinned `rpmh-regulator.c` defines those VRM offsets and PMIC5 HPM value.

Prefer ACTIVE0 only while its local IRQ source is already enabled, as V5
observed. Keep GIC37 masked. Require a fresh owned RSC completion bit, idle
status and ISSUED/COMPLETE bits 8/16 on all three commands; stale command status
alone is insufficient. Preserve unrelated IRQ bits and every other TCS.
Cleanup after proven completion may clear only this slot/control/command-enable
and its completion bit; it must not send an unvote. Uncertain write/timeout
quarantines the slot and owner for this boot without cleanup, reset or retry.

Before implementation, establish the inherited floor and fresh physical state.
Do not replace an unknown retained vote with 3304 mV merely because no enabled
TCS payload mentions it. Retain the maximum authorized inherited voltage,
enable and mode requirement; refuse incompatible or unknown state. TCS ACK
must be followed by fresh, stable physical VSET/mode/enable/VREG_READY evidence
before any future `redfin_touch_rail_ready()` can return true. No write backend
or startup call is included here.
