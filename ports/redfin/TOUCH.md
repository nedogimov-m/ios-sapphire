# Redfin touch bring-up

`touch.patch` is an opt-in host observer, not a working touch driver.
`redfintouch=1` runs once from `IOFindBSDRoot`, before the UFS root path exits.
Common dispatch requires verified bootloader return before invoking it.
Other values perform no MMIO. It never starts a SPI command or reads FIFO
data, and never changes clocks, pinmux, GPIOs, interrupts or regulators.
The five GCC clock branches must report `CLK_OFF=0` before SE0 is mapped.

The actual live Redfin DT and recovery input registration identify Samsung
SEC S6SY79x (`sec,sec_ts`) on QUPv3 wrapper 0 SE0, SPI0 CS0, mode 3, 10 MHz.
This differs from the inherited Xiaomi FocalTech I2C transport.
Recovery observes device ID `53 45 37 91 00`, application status `20`,
1080x2340 coordinates and a functioning `sec_touchscreen` input device.
The external `s6sy79x.bin` file is absent during recovery's deferred update;
the controller already responds without that upload.
These observations do not prove ABL leaves the same power/bus state for XNU.

The `/redfin-touch` ADT contract uses native little-endian cells:

| Property | Exact value |
| --- | --- |
| `compatible` | NUL-terminated `redfin,sec-touch` |
| `reg` | u64 pairs: `0x100000,0x1f0000`, `0x880000,0x4000`, `0xf000000,0x1000000` |
| `spi-mode` | u32 `3` |
| `chip-select` | u32 `0` |
| `spi-max-frequency` | u32 `10000000` |
| `touch-gpios` | u32 reset/IRQ/bus-switch: `8,9,35` |
| `touch-size` | u32 `1080,2340` |

GCC QUP0 clock branches are master AHB `0x17004`, slave AHB `0x17008`,
SE0 `0x1700c`, wrapper core `0x23000`, wrapper core2x `0x23008`.
Vote register `0x52008` has corresponding bits 6/7/10/8/9; stage 1 only reads it.
SE0 RCG starts `0x17010`. TLMM GPIO8/9 use WEST tile `+0x500000`;
GPIO35/42/43/44/45 use EAST `+0x900000`, register stride `0x1000`.
SPI pins 42..45 mux to `qup00`; reset 8 is output-high, IRQ 9 input,
bus-switch 35 output-low for AP ownership in the Linux active state.
These are source facts, not permission to program the pins.

Pinned source references:

- [SEC driver `sec_ts.c`](https://android.googlesource.com/kernel/msm-modules/sec_touch/+/0701b191882dc408104ad8af9e2f5eb2bf34c297/sec_ts.c):
  `sec_ts_read_internal`, `sec_ts_spi_delay`, `sec_ts_handle_coord_event`.
- [SEC definitions `sec_ts.h`](https://android.googlesource.com/kernel/msm-modules/sec_touch/+/0701b191882dc408104ad8af9e2f5eb2bf34c297/sec_ts.h).
- [GENI SPI host](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/spi/spi-geni-qcom.c),
  [GENI registers](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/include/linux/qcom-geni-se.h),
  [GCC clocks](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/clk/qcom/gcc-lito.c),
  [TLMM](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/pinctrl/qcom/pinctrl-lito.c).

The included pure protocol helpers are tested but not connected to MMIO.
A read request is eight bytes: `AA 00 01 len_hi len_lo register checksum 00`.
Deassert CS between the request and response; wait 100 us for ID/boot/one-event,
500 us for all-event. Response length is `roundup4(7+payload+1)`, payload
starts at byte 7; verify sync, echoed register and additive checksum.
Only ID 0x22/5 bytes, boot 0x55/1 byte, one-event 0x60/8 bytes and all-event 0x61/8..248 bytes
are representable. Event reads consume the event queue.

V3 authenticated observation: reset8 and bus-switch35 remain inputs/low;
SPI pins are not muxed to QUP. The SE0 and slave-AHB clocks report off, so
no SE0 register was read. TLMM uses four 16 KiB mappings, rather than the
16 MiB controller extent: `0xf508000`, `0xf920000`, `0xf928000`, `0xf92c000`.
This avoids the early I/O allocator limit observed in V2.

Next stage requires reviewing the authenticated stage 1 snapshot: clock
state, SPI firmware protocol 1, FIFO availability, SE idle status and pin
ownership. If clocks or firmware are absent, stop and implement only the
source-proven missing setup. No firmware upload/reset/power sequence is
implemented. A future polling transport must bound every wait, stop after
the first failed transfer and verify controller identity before events.
HID mapping also needs to account for the physical 1080x2340 panel: inherited
`SweetHIDTouch` assumes 1080x2400 and has not been connected here.

Host verification: `python3 -m unittest ports/redfin/test_touch.py -v`.
