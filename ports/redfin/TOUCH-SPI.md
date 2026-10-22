# Stage 2 draft: SEC SPI identity

`touch-spi.patch` adds an ID-only transport, with no startup hook of its own.
The initial md0 caller now invokes it after verified power and cold setup.
In the authenticated `touch-id-v3` run (2026-10-22), physical L17 power and
every setup phase passed, but the ID exchange timed out with errno 60 and
host cancel/abort also timed out. SEC identity remains unknown.

The exchange begins with an 8-byte TX-only command; V3 did not log which
opcode was pending on failure. Zero ID bytes do not prove that RX was never
issued: the output is copied only after the complete response validates.
The following diagnostic run must distinguish TX failure from RX failure.

Before connecting `redfin_touch_spi_probe(se, verified_speed_hz, gic_irq_masked)`, prove the
stage 1 ADT contract, all five clock branches, AP pin ownership, SEC reset
deassertion, SPI firmware protocol 1 and a clock rate no higher than 10 MHz.
The current routine does not derive source frequency from a GENI divider;
the caller must supply a separately verified rate. A nonzero divider alone
does not establish that rate. No GCC, TLMM or PMIC writes are implemented.
The caller must read GICD `0x17a00000+0x14c` (ISENABLER19), verify bit 25 is
zero (INTID 633), and retain exclusive ownership while probing. Pass that
proof as `gic_irq_masked=true`; a CPU IRQ mask does not substitute for it.
The draft performs no GIC configuration writes.

The GCC RCG supports DFS. Read `0x17024` first: bit 0 enables DFS and bits
4:1 report its current level. With DFS enabled, use the selected level's
CFG/M/N at `0x17010 + 0x1c/0x5c/0x9c + 4*level`; also record GENI clock
selection `0x7c`. Otherwise use ordinary RCG CFG/M/N at `0x17014/18/1c`.
From `clk-rcg2.c`, source selector is CFG bits 10:8, HID is bits 4:0,
fractional mode is bits 13:12, `m=M&0xffff`,
`n=((~N)&0xffff)+m`. Source frequency is divided by `(HID+1)/2` when HID
is nonzero, then multiplied by `m/n` in fractional mode. Source selector 0
is the 19.2 MHz oscillator; selector 1/6 uses GPLL0/main or even output and
needs separate PLL frequency proof. GENI's serial divider is bits 15:4 of
`0x48`. Wrapper version 1.0 additionally has SPI oversampling 2; record
the wrapper HW version at `0x8c0000+4` before interpreting the wire rate.

Captured DT power facts: `avdd-supply` resolves to PM8150 L17, RPMh resource
`ldoa17`, exactly 3.304 V, `regulator-always-on`. The SEC Linux driver only
enables that supply; it does not upload firmware to obtain the observed
device ID. V3 proved an owned ACTIVE vote and fresh physical configured/VALID
3304 mV, HPM7, enable `80`, STATUS `87`; this was not an enabled ABL handoff.

The transport preflight requires the existing SE state to match the Linux
configuration: idle, empty FIFOs, SPI mode 3, CS0 active low, 8-bit words,
MSB-first packing, 16x32-bit FIFOs, FIFO interface available, DMA and GSI off,
GENI output control enabled and serial clock enabled. If anything differs,
it returns before writing. Configuration is supplied by the separately
guarded setup described in [TOUCH-SETUP.md](TOUCH-SETUP.md).

Only GENI host registers are written: local interrupt gating/status,
watermarks, CS-toggle configuration, transfer lengths, command and FIFO.
Local `SE_IRQ_EN=0xf` routing and master DONE/WM/error enables are necessary
for the polled status, following Linux FIFO setup and the upstream Goodix
driver. The GIC interrupt remains masked separately. Local routes and
master enables are disabled on every exit after setup, including failure.
The request is a single 8-byte TX command, no FRAGMENTATION parameter;
the response is a new 16-byte RX command after 100 us with CS deasserted.
The controller sees only SEC read-register request `0x22`, length 5.
The expected identity is `53 45 37 91 00`. The response must pass sync,
register echo and checksum validation before identity is accepted.

Every transfer is bounded to 10,000 polling iterations, with 1 us delays.
On failure, stop all further SEC requests; if GENI remains active, attempt
host-command cancel for at most 1,000 iterations, then abort for at most
1,000. No IC reset, GPIO toggle, firmware, NVM, calibration, flash operation,
event clear or retry is encoded. A host cancel/abort timeout leaves the
transport unavailable. This is not a proven physical CS recovery mechanism.
Cancel and abort require a command issued by this transport; unexpected
busy state before its command stops without cancelling someone else's work.

The authoritative vendor wrapper implementation is
[`drivers/platform/msm/qcom-geni-se.c`](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/platform/msm/qcom-geni-se.c),
not the different mainline implementation under `drivers/soc/qcom`.
The host SPI source is linked in `TOUCH.md`. The draft follows
`setup_fifo_xfer`, `geni_spi_handle_tx`, `geni_spi_handle_rx`,
`geni_setup_m_cmd` and the SEC `sec_ts_read_internal` framing.

`touch-spi-diag.patch`, applied after `touch-events.patch`, adds read-only
evidence before the first command and before/after bounded error recovery.
Each snapshot reads 41 fixed GENI configuration/status registers; the boot
budget is at most 369 additional reads and 45 log lines. No FIFO data or
IRQ-clear register is read, and no transport writes, explicit delays or
polling budgets change. Failure snapshots are printed after recovery.
The source audit preserves `GENI_CGC_CTRL` bits 8/9
(`PROG_RAM_HCLK_OFF`/`PROG_RAM_SCLK_OFF`) as native `se_io_init` does;
diagnostics observe them without speculative clock changes.

After a live ID succeeds, events can use read `0x60` for one 8-byte event,
then `0x61` for remaining events (`500 us` request-to-response delay for
`0x61`). Both consume the controller queue. Add bounded polling in a kernel
thread, never an unbounded loop in `IOFindBSDRoot`; release all active HID
contacts on the first transport fault and stop. Interpret status/reset
events separately before accepting coordinates. Do not invent SENSE_ON or
power-state writes if reads show that the controller is asleep.
The SEC source identifies status events by `event[0]&3 == 1`, status type
`(event[0]>>2)&15`, and status ID `event[1]`. Boot-complete ID 0 with INFO
type reports hardware/software/watchdog reset in `event[2]` values
`0x10/0x40/0x20`; release contacts and stop for review on these events.
ERROR-type queue-full ID 1 and ESD ID 2 also require releasing contacts.

Existing `SweetHIDTouch` matches `IOResources`, with C entry point
`sweet_hid_touch(finger, down, x, y)`. It silently drops events until its
service has registered. SEC fingers are `(event[0] >> 2 & 15) - 1`;
actions 1/2/3 mean press/move/release. Track each contact until an explicit
release; a single event is not a complete all-finger frame. Palm/grip and
unsupported contact types must not become ordinary finger presses.

HID geometry needs a Redfin override before live event delivery. The
framebuffer crops a 1125x2436 canvas onto the 1080x2340 panel with offsets
`20,48`; inherited HID assumes panel height 2400 and vertical offset 18.
Change HID panel bounds and edge detection to 1080x2340 and use raw SEC
pixels with those same offsets. Merely adding 30 to input Y aligns position
but breaks top/bottom edge classification, which iOS uses for home gestures.
Keep the inherited geometry for other boards.

Host verification: `python3 -m unittest ports/redfin/test_touch.py ports/redfin/test_touch_spi.py -v`.
The model checks disabled/preflight zero-write paths, exact SEC request,
two CS commands, corrupted responses, FIFO bounds, early completion,
fatal commands and bounded cancel/abort without retry. Its status model
gates DONE/WM behind both local routing and master enables, with a response
delivered in a watermark batch followed by a last/done batch. An unproved
GIC mask returns before MMIO; cleanup must leave both local enables zero.
`test_touch_spi_diag.py` additionally compares actual-C baseline/diagnostic
write and delay traces, return values and FIFO consumption across success,
preflight, timeout, cancel/abort, malformed-response and identity failures.

V4's authenticated snapshot subsequently proves the first TX_ONLY opcode
0x08000000 remains active, before RX: M_IRQ0, STATUS31, FIFO word count0.
V5 adds unchanged physical GCC/RCG/DFS and GPIO evidence before/failing TX.
AHBs2 to80000002 has HWCG enabled and does not by itself prove lost power.
Word length, packing, mode3, master clock141 and the separate INIT8/FW101
fields are consistent with pinned drivers; SCLK0 is not itself an omission.
The reason the sequencer does not finish remains unresolved.

`touch-platform-diag.patch` adds bounded snapshots from existing setup maps;
`touch-dfs-diag.patch` additionally reads protection70/74/78, SE DFS_IF80,
DMA_GENERALe30, sampling2b0/2b4 and wrapper version/AHB/common4/118/120.
The latter maps only the source-pinned wrapper8c0000+2000 after final proof,
with complete rounded-map RAM exclusion; map failure only skips evidence.
It adds at most20 RO reads/six lines and no hardware writes/delays. This
tests whether disabling GCC DFS left the separate SE DFS interface enabled.
Readback evidence is required before changing either interface or firmware.

V6 authenticated evidence confirms SE_DFS_IF80=301 (enabled1) while GCC
DFS=20 (enabled0), unchanged across the TX timeout. Protection readbacks are0;
wrapper version20070000/AHB1/COMMON7. A minimal source-backed correction must
disable only the SE DFS enable before the existing manual XO configuration,
preserve other bits and stop on failed readback. Its effect is still untested.
