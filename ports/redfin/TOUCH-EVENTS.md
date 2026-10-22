# SEC sensing, events and Redfin HID

`touch-events.patch`, `touch-sensing.patch` and `touch-event-start.patch`
are included by both kernel builders. The startup caller owns DRV2/SE0 for
the entire boot and selects one explicit mode:

| Image-builder flag | Boot mode | Result |
| --- | --- | --- |
| `--touch-id-probe` | `rd=md0`, no scan/events | Power, cold setup and SEC ID only |
| `--touch-scan-probe` | `rd=md0 redfintouchscan=1` | ID, volatile sensing init and at most four raw queue batches; no HID |
| `--touch-events` | UFS GUI, `redfintouchevents=1` | ID, then an asynchronous HID worker |

ID/scan require `--return-bootloader` and no UFS. Add
`--touch-events --ufs-root --display --return-bootloader` to an existing GUI image build;
the builder supplies the touch/rail/SPMI flags. The kernel requires
`rd=ufsroot0 redfinroot=1 redfinufs=3 ufsroot=userdata`, explicit equal
`ufsrw/rootrw` values of 0 or 1, `sweetlog=0`, `redfinfb=1`, UP and verified
return. USB, modem, WLAN, GPU and competing legacy paths remain disabled.
The display contract is exact: framebuffer `0xa0000000+0x02300000`,
1080x2340, stride 4320, BGRA, canvas 1125x2436 and the ABL-copy marker.
Screen capture (`redfinscreen=1`) is optional. Scan and events are mutually
exclusive; an old initial-md0 lease boolean cannot authorize either mode.

`redfintouchsecs` defaults to 120 (180 in strict GUI8) and accepts 1..300 seconds. Start returning
zero means the worker was created. The boot thread never waits for HID.
The permanent owner has no release or retry after a power/SPI failure; see
[TOUCH-RAIL.md](TOUCH-RAIL.md) for its typed callback contract.

GUI8 uses the separately verified eight-core/root/display contract and pins
the touch worker to CPU0. The old UP profiles remain available. Hardware on
2026-10-23 confirms Apple GUI and native HID on all eight CPUs. At 60 Hz CPU
copy cadence the parser stopped with `EOVERFLOW` after 381 batches/12 contacts;
the kernel/rendering continued and the root unmounted cleanly.

`touch-overflow.patch` implements the pinned SEC driver's queue recovery
(`sec_ts.c:2337` count above 31, `sec_ts.h:244` register `0x62`). A complete
validated packet reporting overflow, including queue-full status ID 1, releases
all active fingers before an exact eight-byte CLEAR_EVENT_STACK command.
Only an open, successfully sensed SPI session can clear, at most eight times
per boot. The worker rechecks its permanent lease, GIC/GPIO and HID before
the command and every following read. It discards at most four bounded batches
and requires an actual empty reply before delivering new contacts. Unknown
MOVE cannot create a new finger; stale held contacts remain suppressed until UP.
The raw triggering event and recovery result are logged. A failed command,
lost ownership/consumer, malformed response, persistent overflow, reset or other
IC error still stops the worker and closes the session. No IC reset, firmware,
calibration or persistent storage operation is added.

Hardware, 2026-10-22: SEC ID `53:45:37:91:00` and the md0 scan both passed.
Scan read APP boot `0x20`, STATUS `00:03:01:00`, functions `0x61` with exact
`0x61` readback, then STATUS `00:02:01:02`. It consumed boot/vendor status
events followed by an empty queue and returned zero. This proves the bounded
sensing/queue path. Later authenticated UFS/HID captures and user gestures
confirm GUI input; the all-eight-core result is recorded above.

The overlay extends the generated SPI source, without changing the frozen
earlier patch files. Successful ID comparison stores this boot's SE address
and clock bound. The new event-session API requires that proof and a fresh
GIC-mask proof. The SPI read allowlist covers ID `0x22/5`, boot `0x55/1`, status
`0xaf/4`, functions `0x30/2`, and FIFO `0x60/8`, `0x61/8..248` bytes.
Requests and responses use the existing
bounded SPI transport and SEC sync/register/checksum validation. Any read
failure closes local IRQ routes, invalidates the session and identity proof,
and prevents retries. Event reads consume the controller queue.

The worker validates the Redfin touch ADT node, maps only the IRQ9 16 KiB
GPIO page and GICD, and continuously requires GICD `+0x14c` bit 25 to remain
zero (INTID 633) and IRQ9 to remain a GPIO input. It writes no GIC or GPIO
register. GPIO9 is polled every 8 ms; active contacts are also polled, with
an idle read approximately every 104 ms. Every batch has at most 32 events:
one `0x60` read followed by at most one `0x61` read for the stated remainder.
The complete batch is read and checked before it emits any new DOWN.

HID readiness requires all of the following:

- The strict Redfin display/touch geometry profile has been accepted.
- `SweetHIDTouch::registerService()` has returned and publication is visible
  through acquire/release atomics.
- The existing event-service client list has a nonnull event callback,
  checked under its client lock. A service pointer or empty open is not enough.

Before this readiness, the worker consumes no events and emits no contacts.
After readiness and a verified open SPI session, the worker performs the
same one-shot sensing sequence used by md0 scan: require boot `0x55 == 0x20`,
read `0xaf` and reject FLASH status, read current functions `0x30`, write
`current | 0x61` (TOUCH/PALM/WET), require exact readback, send SENSE_ON `0x10`,
and reread `0xaf`. Only these two volatile writes are allowed, with native
checksums and 12/8-byte padded frames. There is no firmware upload, flash,
NVM, reset or calibration in this sensing routine, and no retry. Runtime
overflow recovery may separately issue the exact event-clear command above.

Lease, HID and GIC/GPIO guards run before the whole bounded sensing routine;
the SPI transport retains its own hardware checks for each phase. The lease
callback is also checked during HID wait, before opening SPI, before every
event read and before DOWN. It does not run between every sensing command.
The worker then drains at most four startup batches until the queue is empty.
Those queued contacts are discarded. A previously held contact remains
suppressed until UP; an unknown MOVE cannot start a new gesture. One initial queued hardware/software
reset notification is accepted during this drain. Watchdog reset, later
reset, non-queue-full error/ESD status, malformed data, loss of consumer, loss of
ownership or transport failure stops the worker and releases every active
contact. DOWN rechecks readiness and ownership before HID injection; UP still
clears SweetHID's state after its consumer disappears. The saved transition
is retained for the event mask, while local UP state is cleared under its
lock before collection allocation; an allocation failure cannot retain a
local DOWN. Callback delivery itself still requires an allocated event.
Expiry also releases all contacts and closes the SPI session.

Coordinates use the SEC source's ten contact IDs and press/move/release
actions. Normal, glove and wet types may become fingers; palm, grip and
unsupported types stay suppressed for their contact lifetime. A single
event updates its own contact, rather than treating every report as a full
all-finger frame.

The geometry override validates `/arm-io/disp0`'s Redfin marker, physical
1080x2340 dimensions and 1125x2436 canvas, plus the SEC node's matching
`touch-size` and compatible string. It uses physical bounds 1080x2340,
canvas offsets 20/48 and the same raw-coordinate mapping as the framebuffer
crop. Clamp and edge classification use the physical height 2340; merely
adding 30 to inherited Y would misclassify the home-gesture edge. Other
boards keep their inherited geometry. This reuses the existing SweetHID
event service and imports no upstream userspace injection or private ABI.

Source: Google SEC commit `0701b191882dc408104ad8af9e2f5eb2bf34c297`,
`sec_ts.c` at `sec_ts_read_event` (`MAX_EVENT_COUNT = 32`, reads `0x60/0x61`), status
handling and `sec_ts_handle_coord_event`; `sec_ts.h` event bit fields,
types and application boot status. Transport references are in
[TOUCH-SPI.md](TOUCH-SPI.md); setup/power prerequisites are in
[TOUCH-SETUP.md](TOUCH-SETUP.md).

Host validation:

```
python3 -m unittest ports.redfin.test_touch_events ports.redfin.test_touch_events_worker \
  ports.redfin.test_touch_sensing ports.redfin.test_touch_event_start -v
```

The tests compile the actual event state/session functions, geometry/profile
and readiness helpers, the actual SweetHID touch method with allocation
failure injection, and the worker with a virtual scheduler and scripted SEC
queue. Tests cover ten contacts, startup suppression, trailing corruption,
oversized batches, status errors, unsupported contacts, ID/session gates,
registration timing, consumer loss during a read, finite lifetime/drain,
release of all contacts on failure (including collection/child allocation
failure without later resurrection), and the corrected bottom-edge mapping.
The startup tests also execute the patched RPMh backend and worker: all three
lease modes, exact root/display gates, reentrancy, loss of lease at each power
boundary and after one or ten DOWNs, and sensing failure before FIFO access.
ARM kernel compilation, md0 sensing and physical GUI input have passed.
Queue recovery hardware validation is tracked in `NOTES.md`.
