# USB logger before a GPU diagnostic — offline contract, 2026-10-23

The combined profile is **not enabled or wired**. The existing md0 USB test
and separate GPU/GMU tests retain their existing gates. Device access was
unavailable during this work; no image was booted or device operation issued.

`usb-log-worker-check.patch` fixes the observed source defect where failure
to create the requested Redfin log worker silently succeeded. Apply it after
`usb-network-worker.patch`. It records a sticky gadget error and uses the
existing outer owned-quiesce path. The event worker may already own active
DMA, so the permanent slab, route and caller lease remain retained even if
halt cannot be proved. It does not claim host readiness. Four tests execute
the actual startup/outer halt with injected failure and preserve legacy
optional-log behavior. Root reports native build `051524` linked this fix.

## Existing boundaries and reusable functions

- `IOKitBSDInit.cpp:redfin_peripherals_observe()` dispatches GPU mode 2 before
  reaching USB startup. Adding USB flags to a GPU image cannot order the work.
- `redfin_usb_start.c:redfin_initial_usb_gates()` requires native GPU/RPMh
  selectors to remain zero on every WARM/ACTIVE/QUIESCE policy call. Its fixed
  caller/context and permanent lease are essential; replacing them with a
  boot-argument boolean would invalidate the ownership proof.
- `redfin_gpu_power.c:gp_flags()` and `redfin_gmu_args_select()` reject USB
  tokens. Do not strip USB words before calling either parser. A future
  coordinator needs an exact combined parser and explicit owned child entry.
- USB startup is `redfin_usb_start_initial()` → owned route claim/revalidation
  → `redfin_usb_gadget_start()`. The event worker polls every 1 ms; the log
  worker copies the console ring to nonblocking UDP5140 every 100 ms.
  Successful thread creation or `ud.configured` is not listener readiness.
- The reusable CPU engines are `rf_gp_run()` and `rf_gt_run()`. Their MMIO
  adapters must continue to check the complete frozen child DT/argument,
  held-parent, interrupt, clock and return contracts. This work adds no GPU
  adapter or callback and does not relax those contracts.

The proven USB V7 image uses SID `e0`, a leased APPS-SMMU context with the
five-store AArch64 format, fixed MAC/IP peers, a 30-second gadget lease and
md0. Host `usb-native.py` verifies the physical USB location/ECM ancestry,
solicited boot-nonce ICMP and UDP log freshness. It currently exposes that
evidence only to the host, with no kernel ACK/control receive API.

## Resource audit

| Resource | USB logger | GPU/GMU diagnostic | Required boundary |
| --- | --- | --- | --- |
| Controller | DWC3 `0x0a600000`, inherited PHY/VBUS | GPUCC `0x03d90000`, GMU `0x03d6a000` | No overlapping controller/PHY writes |
| GIC interrupts | DWC3 INTID272, event ring polled | RPMh RSC INTID37; GMU336/337 | Distinct bits; preserve masked/pending/active checks |
| SMMU | APPS `0x15000000`, SID `e0`, leased CB/slot | Dedicated GPU `0x03da0000`, streams4/5 | GPU must not change APPS routes, CBs or global policy |
| RSC | Warm USB path issues no RSC transaction | `0x18220000`, one held CX request | Retain the one audited RSC owner; no competing touch/Wi-Fi votes |
| GCC/PLL | USB `0xf010/18/1c/7c/80`, master source `0xf020` | GPLL0 vote `0x52010` bit0; GPU feed `0x52000` bit16; GPU branches `0x71154/7100c/71018` | Shared GPLL0: preserve its rate/configuration and other vote/feed bits |
| CX | USB warm power/clocks retained | Source-backed highest legal CX selector7/416, held until reset | No unvote, domain collapse or shared clock reset |
| CPU/RAM | One CPU, owned permanent 16 KiB DMA slab | Requires physical CPU0; reset-held TCM, no DMA | Freeze CPU0 and `0x180000000+0x80000000` RAM; no UFS/display/touch/radio |

The optional GPU-SMMU observer checks INTIDs705 and710–717 and reads only
the dedicated GPU global window; it does not share USB's APPS context.
These source distinctions do not prove combined hardware operation. In UP,
a stalled MMIO load can stop every CPU worker; USB cannot promise continuing
logs after that stall. The critical marker must reach the host first.

## Independent protocol implemented here

`usb-log-ready.c/.h` contain only a bounded CPU codec/state machine.
`usb-log-ready.py` contains a pure host packet protocol, importing the
existing wire helpers without opening a device or changing baseline tools.
They are not in a kernel build list, startup hook, builder profile or GPU path.

The fixed 48-byte, network-order control payload uses UDP5141 in both
directions: magic/version `RFLGv001`, kind, sequence, boot nonce, per-lease
cookie, physical marker address, operation and value. HELLO/HELLO_ACK use
sequence1 and zero marker fields. MARKER/MARKER_ACK use sequences2–17 and
bind the exact read32/write32 description. One caller owns one outstanding
request; the interface, nonce and cookie cannot be replaced or reinitialized.

The host returns an ACK only after the existing ARP proof, an actually
injected and answered nonce echo, and exactly one matching boot-ID log line.
It records the request before returning the ACK frame. Stale cookies,
sequence gaps, noncanonical/checksum-invalid packets and failed recording
produce no ACK. Retransmitted requests receive at most three ACKs; normal
ARP/ICMP/UDP5140 traffic passes to the existing protocol. No additional RX
hook or packet filter is enabled by these files.

The C core additionally requires an exact DWC3 completion receipt before
accepting the ACK. A queued marker or early ACK cannot make it ready. A
marker is consumed once, only while its deadline and original gadget lease
remain valid. The core caps readiness at 10 seconds, each critical marker at
500 ms, markers at16, and malformed ACKs at16. All clocks are monotonic with
overflow-safe deadlines. ACK readiness is delivery evidence; it does not
authorize a GPU address or invoke a hardware operation. The UDP nonce is
freshness evidence, not cryptographic authentication.

## Concrete future flush API and lock budget

The transport adapter remains unimplemented. Its required service contract is:

```c
int redfin_usb_log_flush_critical(const void *fixed_owner,
    struct rf_ulr_session *session, uint64_t address, uint32_t operation,
    uint32_t value, uint64_t absolute_deadline_ns);
```

It returns zero only after `rf_ulr_marker()`, an exact successful DWC3 TX
receipt, the matching host ACK, and `rf_ulr_take_marker()`. It performs no GPU
MMIO. The caller must recheck live USB/return and child GPU ownership before
the described access; timeout means no new diagnostic access and no lease
release or in-flight free.

`sock_send()` success and `ud.tx_frames` do not provide the needed receipt:
the counter increments at TRB submission. Current `ud_event()` clears
`tx_busy` on EP_TX XferComplete without checking its status/TRB residual.
A future adapter must privately tag the exact 90-byte control frame before
mbuf release, retain its identity while in flight, and acknowledge completion
only after matching EP_TX success, HWO clear, successful TRB status and zero
remaining length. It must not reuse the completion of a different log frame.

Budget a marker's complete TX within250 ms and host ACK within500 ms total,
always clipped to the original gadget lease. Initial HELLO may use10 seconds
including ARP/host setup. The C core enforces the total deadlines; the
250 ms TX subdeadline belongs to the missing transport adapter. Reserve one
control slot or fail with ENOBUFS; do not overwrite the existing 32-entry queue.
The binary marker carries the critical register description directly: this
API does not claim to drain every earlier `printf` byte. `sweet_log_copy()`
currently advances its cursor before a failed UDP send, so generic console
ring-drain guarantees would require separate acknowledged byte accounting.

Keep `ud.lock` only for short queue/identity updates. Release it before socket
send, any wait, or GPU work. Existing TX takes `ud.lock` then the route
manager's lock through proof checks; never introduce the reverse lock order.
Serialize pure readiness state with a separate short lock or a bounded
receipt queue, and post/wake completions without waiting in event/log workers.
Wait with interrupts/preemption enabled and an absolute deadline, rather than
spinning or executing the GPU stage on either USB worker. Revalidate the
verified ECM binding before each host injection as the native tool already
does. RX metadata passed to `rf_ulr_ack()` uses the actual owned ifindex and
host-order IPv4/port values from checksum-validated traffic.

## Minimal later integration, intentionally not performed

A dedicated, exact `redfinusbgpulog=1` CPU0/md0 profile could select the proven
USB AArch64 ECM/log flags plus the held-CX/optional reset-held GMU leaf.
Its proposed complete argument list fits in403 bytes including NUL before
optional tracing. It must keep legacy modem/Wi-Fi/GPU, UFS/root writers,
display, touch and SMP disabled; use compiled shim prearm and fresh boot ID;
and retain all existing return/watchdog checks. Existing standalone selectors
remain unchanged. Builder, frozen C/Python profile, loader/prearm and manifest
proof must all recognize this profile explicitly before it can be admitted.

Its ADT is the union of existing validated USB-route/NS-context-allocator,
GPU-power and optional GMU contracts, with the same chosen RAM and return
nodes. No new physical reservation, context grant, reset or global SMMU mode
is needed. Dispatch must enter this coordinator before generic GPU startup
and return exclusively from it. Start USB first, verify both worker launches,
wait for HELLO completion/ACK, flush a critical marker before the first GPU
MMIO, then execute the existing synchronous child while USB remains owned.
Further critical-region markers use the same flush API. Failure never falls
through into another probe. All of this integration is still outstanding.

Native linkage for the pure C core requires only `memcpy`/`memcmp`, integer
types and `<sys/errno.h>`; its header provides C++ linkage declarations. It has
no socket, USB, GPU, thread or allocator symbols. The host codec requires only
Python's standard library and the existing `usb-host.py`. Native core linking,
transport receipt hooks, combined ownership/gates and hardware coexistence
have not been tested or enabled by this milestone.

Focused validation:

```sh
python3 -m unittest ports.redfin.test_usb_log_worker_check ports.redfin.test_usb_log_ready -v
```

Four startup-injection tests and13 pure core/host tests pass, including C/Python
wire equality, no readiness from queued TX/early ACK, replay/peer/deadline
negatives, preserved ordinary UDP, record-before-ACK and bounded duplicates.
ASan/UBSan cover4096 malformed codec scenarios and a full16-marker lifecycle.
