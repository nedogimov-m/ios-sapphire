# Redfin guarded USB gadget experiment

`usb-gadget.patch` reuses the generated `bsd/dev/sweet_usb.c` DWC3/CDC-ECM
core and adds Redfin guards. `usb-enumeration-start.patch` connects it to the
permanent md0 owner after a dedicated bypass-context claim and strict warm
revalidation. The explicit `--usb-enumeration-probe` builder option selects
this 30-second, enumeration-only experiment; UFS and competing peripheral
writers remain disabled. The first hardware attempt passed warm route proof
but failed ACTIVE authorization. Enumeration remains unproved.

The exported API is:

```c
int redfin_usb_gadget_start(const void *caller_id,
    const struct redfin_usb_gadget_policy *policy);
```

The caller must be the same stable, trusted kernel owner used for
`redfin_usb_owned_claim_bypass`. The policy callback and its context must remain
valid throughout the experiment. Neither a boot argument nor a cached
boolean is ownership proof. Its callback returns zero only after these
phase-specific checks:

- `RF_USB_WARM`: actual sole controller/SMMU ownership, disabled competing
  writers, md0-only operation, and successful
  `redfin_usb_owned_revalidate_bypass(caller_id)` against the halted ABL handoff.
- `RF_USB_ACTIVE`: continuing sole controller ownership and live
  power/clocks, plus `redfin_usb_owned_route_retained_bypass(caller_id)`. The
  complete imported SMMU header, stream table and sampled context-bank words
  must still match. The original ring/DCTL snapshot may change during gadget
  operation.
- `RF_USB_QUIESCE`: continuing exclusive control of the powered, clocked
  DWC3 through `redfin_usb_owned_quiesce_bypass(caller_id)`, including after
  route quarantine. This phase authorizes only clearing RUN_STOP and bounded
  HALT polling. It does not authorize new DMA.

The owner manager's retained-route result alone does not authorize DMA.
The trusted integration must supply the complete callback above. If
quiescence itself cannot be authorized, the driver performs no further
controller accesses. In all outcomes the DMA slab stays permanently allocated;
an uncertain halt cannot expose freed memory to the controller.

The API additionally requires the Redfin platform contract and
`redfinusb=3`. Its finite lifetime is `redfinusbsecs=1..120`, default 30 s.
The integrated enumeration caller fixes this at 30 s and rejects network
and log streaming options.
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
configuration will enumerate.

The authenticated V1 hardware capture on 2026-10-22 leased CB4/slot4 and
completed all four route stores; claim and strict warm revalidation both
returned zero. Device soft reset then completed with GCTL `0x00112001` and
DCFG `0x0048080c`. ACTIVE proof returned `EAGAIN` (35), quarantining the
route owner. The capture subsequently logged an EP0 command `0x6` timeout;
gadget startup returned `EPERM` (1), the bounded halt reported `halted=1`,
and the DMA slab remained allocated. A 90-second host watch observed no
`1209:0001` device. These results establish the warm route and reported halt,
while DMA completion and enumeration remain unproved.

The V2 follow-up uses `usb-bypass-diagnostic.patch`. The overlay reports snapshot errors, cached headers and
the first changed stream and bank, without extra SMMU reads, writes,
delays or changes to the proof policy. Its authenticated, image-matched capture
isolates CB4 FSR changing from zero to `0x2` (translation fault), with
SCTLR/CBAR/CBA2R and sampled headers/stream table unchanged. The guard
quarantines and the controller reports halted. This is a real fault;
the reason translation faults occur with the bypass configuration is unproved.

`usb-fault-diagnostic.patch` adds seven bounded read-only accesses only after
a complete snapshot finds a real fault in the permanently owned bank:
FSR, FAR low/high, FSYNR0, FSYNR1, GR1 CBFRSYNRA, then FSR again. Changed FSR
or all-ones words cause interpretation to be skipped. FAR is explicitly a
pair of sampled words, not an atomic 64-bit snapshot. The gadget separately
prints its validated permanent DMA slab addresses before publishing them.
These diagnostics do not clear faults, resume a context, invalidate TLBs,
change authorization or retry. Six actual-C tests check exact additional
reads, unchanged stores/failure policy, other-bank/FORMAT exclusions, and
unavailable or changing syndrome data.

V3's authenticated capture identifies the exact EP0 TRB at `0x182e55000`
as the fault address, with CBFRSYNRA `0xe0`, FSYNR0 `1` and FSR `2`.
The controller faults on a USB read above 4 GiB. The cause remains unproved.

The separate `--usb-aarch64-context` option requires a bypass or enumeration
probe and emits `redfinusbrw64=1`. `usb-aarch64-context.patch` retains the
original four-store sequence when absent or zero. Opting in uses the native
AArch64 format sequence on the leased, unreferenced bank only: SCTLR=0,
CBA2R=1, CBAR=0x10000, S2CR, then SMR. Each write retains exact readback and
complete fresh state proof; the format is frozen for that lease. The flag
accepts only exact textual `0`/`1` with a numeric cross-check, avoiding XNU's
32-bit numeric truncation and bare-flag interpretation. No TLB or other-bank
state is changed. This experiment tests the high-address/format hypothesis;
it does not establish its cause or successful enumeration before a new capture.

Host validation:

```
python3 -m unittest ports.redfin.test_usb_gadget ports.redfin.test_usb_enumeration_start ports.redfin.test_usb_bypass_context ports.redfin.test_usb_bypass_diagnostic ports.redfin.test_usb_fault_diagnostic -v
```

Ten tests reconstruct the tracked upstream USB patches and Redfin probe,
apply this complete overlay, then compile the actual guarded startup,
endpoint-command path, TRB setup, finite event worker and halt routine with
virtual hardware/time. They inject policy loss, missing clocks/maps,
allocation/physical-mapping failures, reset/command/run/halt/thread failures,
all-ones MMIO/false-HALT faults, and malformed/full event queues. They check cache ordering, DMA region
bounds, default logging/network behavior and the inherited Sapphire path.
The enumeration caller and cached diagnostics have separate actual-C tests
for permanent ownership, phase authorization, quarantine/halt authority and
identical MMIO counts, order, values and images with diagnostics enabled.
The network stack and actual electrical behavior are not modeled.
