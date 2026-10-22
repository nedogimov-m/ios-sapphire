# Cold SEC setup

`touch-setup.patch` has no startup hook of its own. It adds
`int redfin_touch_setup(bool rail_ready, bool host_exclusive)` on top of
`touch.patch` and `touch-spi.patch`. The permanent startup owner invokes it
for initial md0 ID, bounded md0 scan or explicitly selected UFS/HID mode;
see [TOUCH-EVENTS.md](TOUCH-EVENTS.md) for image flags and root/display gates.
The call requires `redfintouch=2 redfintouchsetup=1` and runs at most once
per boot. Missing power/exclusivity proof returns before mapping hardware.

Hardware, 2026-10-22: power and cold preparation passed in V3; later DFS and
RX-notification corrections produced exact SEC ID `53:45:37:91:00` in V8.
The subsequent md0 scan passed volatile sensing initialization and bounded
queue reads. Physical contacts in the UFS GUI remain unverified pending
capture; setup success alone does not prove HID delivery.

`rail_ready` must represent the power backend's fresh, successful preparation
of PM8150 L17 / `ldoa17` at the DT's exact 3,304,000 uV (`0x326a40`,
3.304 V, often rounded to 3.3 V) for this boot, including its settling
requirements. The DT's `regulator-always-on` policy is insufficient.
`host_exclusive` requires a single owner of this GENI engine and interrupt,
and serialized changes to the shared GCC vote register during setup. Neither
proof is accepted from an extra boot argument. The setup itself writes no
RPMh/SPMI/PMIC resource.

The function validates the exact stage 1 `/redfin-touch` ADT contract. It
maps GCC/SE0 and GICD, plus only four 16 KiB GPIO pages:

| Pins | Physical page | Register offsets within page |
| --- | --- | --- |
| reset 8, IRQ 9 | `0x0f508000` | `0`, `0x1000` |
| switch 35 | `0x0f920000` | `0x3000` |
| SPI 42, 43 | `0x0f928000` | `0x2000`, `0x3000` |
| SPI 44, 45 | `0x0f92c000` | `0`, `0x1000` |

Each pin's IO register is its configuration register plus 4. No 16 MiB
TLMM mapping is made. GICD `0x17a00000+0x14c` bit 25 must read zero for
INTID 633, checked before writes, again after the host is clocked, and before
the ID request. CPU interrupt masking is insufficient. No GIC registers are
written.

The cold preflight requires reset 8, IRQ 9 and switch 35 in GPIO input mode,
physical reset and bus-switch levels low, no existing AP SE0 vote, and no
foreign function/output on the SPI pins. Thus it does not switch a live
SLPI route, pulse a running controller or seize a GPIO bit-bang owner.

The implemented sequence is:

1. Preserve every unrelated GCC vote. Add wrapper core/core2x bits 8/9,
   master AHB bit 6, slave AHB bit 7, then SE0 bit 10 at GCC `+0x52008`.
   Poll clock status for at most 200 us. Follow Linux's S_AHB hardware
   clock-gating exception when CBCR bit 1 is set. No SE register is read
   until the complete clock sequence succeeds.
2. Require idle master and slave, empty FIFOs, DMA/GSI disabled, SPI firmware
   protocol 1 and 16x32-bit FIFO geometry. On failure, do not cancel, reset
   or configure that host. Only the preceding clock votes have changed.
3. Gate local GENI interrupts. Disable generated serial clock, clear only
   DFS enable bit 0 at SE `+0x80` and GCC `+0x17024`, with exact readback and
   preservation of other bits, then configure XO source 0 / HID 1 /
   integer mode / software clock control with CFG mask `0x10371f`, value 1.
   Poll UPDATE bit 0 at `+0x17010` for at most 500 us and verify readback.
   Set GENI clock selection 0 and MCLK `0x141`: 19.2 MHz divided by 20,
   a maximum wire clock of 960 kHz, safely below the DT's 10 MHz limit.
4. Apply the source-defined GENI IO clock/default-output initialization,
   8-bit MSB-first packing and SPI mode 3, CS0 active low. No firmware RAM
   is written, no DMA is started, and no host command is issued here.
   The `GENI_CGC_CTRL` mask is only `0x7f`, preserving bits 8/9
   (`PROG_RAM_HCLK_OFF`/`PROG_RAM_SCLK_OFF`) like native `se_io_init`.
5. Set switch 35's LOW latch before enabling GPIO output. Leave IRQ 9 an
   input. Configure SPI pins 42..45 as `qup00` function index 1, drive 6 mA,
   bias disabled, preserving GPIO OE and unrelated fields as pinctrl does.
6. Set reset 8's HIGH latch before enabling GPIO output, with 2 mA drive and
   bias disabled. This is one release of the already-low reset. The vendor
   driver's additional high/low/high pulse is deliberately absent. Wait
   at most 1,000 us for the physical high level, then the source's bounded
   70 ms power-on readiness interval. Recheck GIC mask and host state.
7. Call the existing ID-only SPI probe once with the verified clock bound
   and GIC-mask proof. It sends only SEC register-read `0x22`, length 5,
   and independently checks framing/checksum/identity.

`GENI_FORCE_DEFAULT=1` selects the source-defined SPI default IO levels; it
is not the touch controller reset GPIO or a firmware command. GPIO reset is
never written low. No firmware upload, flash, NVM, selftest, calibration,
event-clear or SENSE_ON command is issued by cold setup. An ID failure stops
here. The separately selected scan/event path can perform the two volatile
sensing writes described in [TOUCH-EVENTS.md](TOUCH-EVENTS.md).
Failure leaves this boot's added clock votes and any completed setup in
place; it does not turn off clocks that another client may also need.

Source pins are documented in [TOUCH.md](TOUCH.md). The SEC driver commit is
`0701b191882dc408104ad8af9e2f5eb2bf34c297`: `sec_ts.c` at 3135..3180 proves
AP switch low and reset output-high, and 3857..3863 supplies the 70 ms delay.
Host register masks/order come from pinned kernel
`500b3a2059c1eec0fec08ec56add06320ea901a8`, `gcc-lito.c`, `clk-branch.c`,
`clk-rcg2.c`, `pinctrl-lito.c`, `pinctrl-msm.c`, `spi-geni-qcom.c` and the
vendor `drivers/platform/msm/qcom-geni-se.c`.

Host validation: `python3 -m unittest ports/redfin/test_touch_setup.py -v`.
The actual C is compiled with MMIO/DT models. Tests cover missing proofs,
exact mappings, GPIO ownership, foreign active/DMA/GSI state, no unclocked SE
reads, preservation of unrelated votes, finite clock/DFS/reset timeouts,
latch-before-OE, absence of reset pulses, GIC becoming enabled mid-setup and
exactly one ID call after settling. [TOUCH-SPI.md](TOUCH-SPI.md) records the
transport diagnostics and corrections that led to successful V8 identity.
