# SEC events and Redfin HID draft

`touch-events.patch` is an unapplied overlay after `touch.patch`,
`touch-spi.patch` and `touch-setup.patch`. It adds no startup hook. The root
caller may later invoke `redfin_touch_events_start()` only after the same
boot's successful ID-only probe, while retaining the proven rail, clocks,
GPIO, GENI and GIC interrupt ownership for the whole session.

The explicit event switch is `redfintouchevents=1`; the existing ID path
still requires `redfintouch=2`. `redfintouchsecs` defaults to 120 and accepts
1..300 seconds. The switch alone does not call the start function.
Start returning zero means the worker was created, not that physical input
or an iOS gesture has been demonstrated. No controller scan/wake command,
firmware upload, flash, NVM, reset, calibration or event-clear is added.

The overlay extends the generated SPI source, without changing the frozen
earlier patch files. Successful ID comparison stores this boot's SE address
and clock bound. The new event-session API requires that proof and a fresh
GIC-mask proof; only reads `0x55/1 byte`, `0x60/8 bytes`, and
`0x61/8..248 bytes` are accepted. Requests and responses use the existing
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
After readiness it verifies boot status `0x55 == 0x20`, then drains at most
four startup batches until the queue is empty. Those queued contacts are
discarded. A previously held contact remains suppressed until UP; an
unknown MOVE cannot start a new gesture. One initial queued hardware/software
reset notification is accepted during this drain. Watchdog reset, later
reset, error/queue-full/ESD status, malformed data, loss of consumer, loss of
ownership or transport failure stops the worker and releases every active
contact. DOWN rechecks readiness immediately before HID injection; UP still
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
python3 -m unittest ports/redfin/test_touch_events.py ports/redfin/test_touch_events_worker.py -v
```

The tests compile the actual event state/session functions, geometry/profile
and readiness helpers, the actual SweetHID touch method with allocation
failure injection, and the worker with a virtual scheduler and scripted SEC
queue. The 17 tests cover ten contacts, startup suppression, trailing corruption,
oversized batches, status errors, unsupported contacts, ID/session gates,
registration timing, consumer loss during a read, finite lifetime/drain,
release of all contacts on failure (including collection/child allocation
failure without later resurrection), and the corrected bottom-edge mapping.
The full overlay applies to a temporary earlier-stage source tree. ARM
kernel compilation, live identity/events and a physical unlock gesture
remain unproved; this draft is not wired into the current kernel.
