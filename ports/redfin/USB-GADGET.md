# Redfin unhooked USB gadget draft

`usb-gadget.patch` reuses the generated `bsd/dev/sweet_usb.c` DWC3/CDC-ECM
core and adds Redfin guards. Apply it after the existing USB probe overlay.
It adds no startup hook and no caller. This draft has not enabled DMA or
enumerated a host on the device. The initial owned-route experiment remains
claim plus strict revalidation only.

The exported API is:

```c
int redfin_usb_gadget_start(const void *caller_id,
    const struct redfin_usb_gadget_policy *policy);
```

The caller must be the same stable, trusted kernel owner used for
`redfin_usb_owned_claim`. The policy callback and its context must remain
valid throughout the experiment. Neither a boot argument nor a cached
boolean is ownership proof. Its callback returns zero only after these
phase-specific checks:

- `RF_USB_WARM`: actual sole controller/SMMU ownership, disabled competing
  writers, md0-only operation, and successful
  `redfin_usb_owned_revalidate(caller_id)` against the halted ABL handoff.
- `RF_USB_ACTIVE`: continuing sole controller ownership and live
  power/clocks, plus `redfin_usb_owned_route_retained(caller_id)`. The original
  ring/DCTL snapshot is expected to change during gadget operation.
- `RF_USB_QUIESCE`: continuing exclusive control of the powered, clocked
  DWC3, even if the SMMU route proof failed. This phase authorizes only
  clearing RUN_STOP and polling HALT. It does not authorize new DMA.

The owner manager's retained-route result alone does not authorize DMA.
The trusted integration must supply the complete callback above. If
quiescence itself cannot be authorized, the driver performs no further
controller accesses. In all outcomes the DMA slab stays permanently allocated;
an uncertain halt cannot expose freed memory to the controller.

The API additionally requires the Redfin platform contract and
`redfinusb=3`. Its finite lifetime is `redfinusbsecs=1..120`, default 30 s.
`redfinusbnet=0` is the default: only EP0 is configured, CDC data alternate
setting 1 stalls, no network interface is created, and log streaming is off.
`redfinusbnet=1` separately opts into the inherited ECM network path.
`redfinusblog=1` additionally opts into log streaming only with that network
path; Redfin log and event workers obey the same finite lease. Sapphire's
existing addresses and log defaults are preserved.

Before controller writes the bridge checks the warm USB GDSC, reset and
five branch clocks; exact DWC3 ID `0x5533330a`, address width 64, device mode,
no global core reset, RUN_STOP/CSFTRST/LSFTRST clear and HALT asserted. MMIO maps
are limited to three 16 KiB pages: GCC `0x10c000`, DWC3 global/device registers
`0xa60c000`, and QSCRATCH page `0xa6f8000`. Existing DWC3 offsets still use their
`0xc000` origin; the logical base is adjusted without accessing unmapped space.

The DMA area is one 16 KiB contiguous, zeroed, permanent allocation. Both
virtual/physical alignment, XNU page size 16 KiB, first/last physical-page
mapping, 36-bit address bounds and containment within the ADT DRAM extent
are required. Event/TRB/data buffers are cleaned before publishing DMA
addresses; received events/data use the existing physical cache maintenance.
Every TRB and buffer offset is checked against its assigned region before
CPU stores, cache operations or STARTTRANSFER. The controller write allowlist
excludes PHY/global-reset/clock/SMMU registers.

The endpoint commands have a 1000 us completion budget and propagate status
or timeout into a sticky failure. Device soft reset, run and halt each have
a 500 ms budget. The event count must be a multiple of 4 and at most 4096 bytes;
event position must be aligned and inside the ring. One pass processes at
most 1024 events. Any failed proof, malformed count, command failure, run
timeout or thread-creation failure stops new commands and attempts the
independently authorized halt. All-ones DWC3 reads latch failure before an
RMW store; QSCRATCH refuses all-ones source values. Quiescence refuses an
all-ones DCTL/DSTS read or an already asserted CSFTRST/LSFTRST, so an uncertain read
cannot become a reset write or false HALT evidence. No automatic retry,
slab free or SMMU rollback
is performed.

The session override follows pinned native Linux
`500b3a2059c1eec0fec08ec56add06320ea901a8`,
`drivers/usb/dwc3/dwc3-msm.c:76,94..99,4575..4588`:
QSCRATCH is core + `0xf8800`; HS PHY control + `0x10` has OTG_VBUS_VALID bit 20;
SS PHY control + `0x30` has LANE0_PWR_PRESENT bit 24, which native code changes
only for SuperSpeed. This high-speed Redfin draft sets only HS bit 20 and
preserves SW_SESSVLD_SEL bit 28, the complete SS control register, PHY setup,
clocks and reset/power rails. It does not prove that the retained PHY/session
configuration will enumerate; hardware validation is still required.

Host validation:

```
python3 -m unittest ports/redfin/test_usb_gadget.py -v
```

Ten tests reconstruct the tracked upstream USB patches and Redfin probe,
apply this complete overlay, then compile the actual guarded startup,
endpoint-command path, TRB setup, finite event worker and halt routine with
virtual hardware/time. They inject policy loss, missing clocks/maps,
allocation/physical-mapping failures, reset/command/run/halt/thread failures,
all-ones MMIO/false-HALT faults, and malformed/full event queues. They check cache ordering, DMA region
bounds, default logging/network behavior and the inherited Sapphire path.
The network stack and actual electrical behavior are not modeled. Actual
ARM compilation and independent review are required before integration.
