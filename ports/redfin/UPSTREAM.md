# HackiOS upstream review — 2026-10-22

## Complete presentation pipeline and native process identity — 2026-10-25

Re-reviewed preferred kernel 8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
MiniIOMobileFramebuffer presenterMain/presenter/show, helperMain/drawRows/
drawLayer and frame-interval reporting. Redfin adopts one separate presenter
and three row helpers, retaining its own bounded SweetSurface descriptors,
pixel/state separation, camera exclusion and inverse touch mapping. One
queued swap retains its actual in-use references; a busy slot leaves the
latest pending swap intact. Each helper has its own blend workspace and
disjoint full rows; source lifetime extends through the complete join.
Pixel writes, including power-off clearing, remain serialized. Source holds
can retire after the CPU copy because Redfin's preserved panel framebuffer
does not DMA-fetch the copied source surfaces. No upstream display/SMMU
private layout or direct scanout is imported.

The notification timer advances an absolute phase independently of the
presenter; a late callback skips elapsed periods without accumulating copy
time or generating a catch-up burst. Started threads retain the service for
the boot lifetime, as the preferred persistent worker model requires. A
failed helper/presenter start retains the complete scalar/synchronous path.
Bounded aggregate timing distinguishes copy work, queue delay and intervals;
none alone establishes measured hardware vblank or stable 60fps.

The actual assetsd crash states "requires TCCPhotosService access", although
its stock signature requests com.apple.private.tcc.allow/Photos. Its native
report has flags0x22000001/category0: the current root-volume platform policy
does not appear in that process metadata. Re-reviewed preferred miniamfi's
signature entitlement ownership and actual8796 MAC/CS_OPS_STATUS/category
interfaces. Redfin accepts the actual root vnode's pinned mount as well as
MNT_ROOTFS, sets CS_ENTITLEMENTS_VALIDATED only for its existing root policy
with a native hash-checked parsed XML object, and publishes the corresponding
platform validation category through the native setter. Other categories,
non-root signatures and the entitlement dictionary are preserved. Scoped
native logs identify assetsd/Photos/tccd's effective flags and Photos key.
No TCC database edit, invented entitlement or Apple binary patch is used.
Whether this resolves the observed TCC denial remains a hardware question.
Paired userland 906425b75e02b4f99eb5d7bb1ef7c9583472d772 is unchanged.

## Native MobileCheckpoint cache and bracketed snapshot reads — 2026-10-25

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and paired
userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 remain the graphics baseline.
Re-reviewed the latter's mkjobs.py CommCenter findings: even the selected
noncellular job eventually crashes on absent AppleIPAppender/AppleBasebandPCI.
Keep it disabled rather than introducing that known loop to answer Phone's
voicemail worker. Phone's sampled main thread is in its normal run loop.

Actual20H392 libMobileCheckpoint's MCCopyCheckpoint path returns its native
NSDictionary cache directly when stat mtime seconds AND nanoseconds match
the installed Checkpoint.xml. A missing cache sends synchronous command0 to
checkpointd; that is Photos' observed main-thread wait. Redfin seeds the
verbatim installed XML dictionary, with mobile ownership and its destination
filesystem timestamp. The offline HFS helper copies contentModDate through
updateCatalog; it does not convert a host extraction date or invent image
capabilities. Checkpointd itself already starts. Its own underlying wait is
not yet observed; a bounded sample now targets it in place of callservicesd.

Redfin retains complete twice-read global/CB0/CB1 snapshots and the original
foreign-state comparisons on every submission. Only nested read callbacks
lose their redundant CX/GX power reads: the serialized caller/context lease
stays mandatory, full parent/source/power checks bracket the snapshot, and
the outer audit now closes with another full guard and payload check after
its final TTBR reads. All hardware-write guards and DMA bounds remain.
Paired graphics userland is unchanged; Metal remains separate work.

## Runtime caller ownership, final fence reads and GPU timestamps — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
RedwoodGPU synchronous mutex ownership and redwood_adreno.c ring_time/
redwood_gpu_submit. Native runtime I/O does not migrate each caller to one
CPU. Redfin now retains CPU0 for every hardware startup/claim, then permits
only the GPU mutex's current-thread lease on one of the eight proved GUI
CPUs. Parent args/power/firmware and complete foreign SMMU audits remain;
the scoped caller lease is required for each non-CPU0 parent check. An
unproved CPU, changed caller or overlapping lease cannot activate hardware.

The previous wait loop could skip reading a completed fence after being
descheduled beyond its wall deadline. The new common wait helper observes
actual completion first and once again at timeout; a missing fence/fault
still retires the queue and retains DMA memory. Failure logs now contain
the actual fence/rptr/status/poll/time values. Preferred CP_REG_TO_MEM of
the19.2MHz CP_ALWAYS_ON_COUNTER brackets each IB batch, with WAIT_FOR_IDLE
before its end timestamp and the existing real cache-flush fence last.
This separates GPU execution from host scheduling delay without a fake
completion or GPU reset/recovery path.

The observed backboardd restart also closes its HID client; the existing
worker exited withEPIPE. Bounded reconnection retains that same verified
SPI/hardware lease, releases old contact state, waits for a real consumer
and discards stale queue data before new DOWNs. No sensing/rail restart is
introduced, and the original session deadline and fatal hardware errors
remain in force. Hardware stability/performance still needs the next run.

## msm dependency flags are distinct from page permissions — 2026-10-25

The975c644bc72f03ae integrated run rejects every submit withEINVAL22;
there is no runtime fence or shader pixel pass, despite EAGL's queued-frame
counters. The new readonly-allocation/submit-WRITE cross-check was wrong.
Reviewed Mesa25.0.7 freedreno_priv.h RING_FLAGS, msm_bo.c and
msm_ringbuffer_sp.c: command BOs are GPU_READONLY and dependency flags can
still include READ|WRITE|DUMP. Preferred kernel8e611870 RedwoodGPU::submit
likewise does not reject that combination. The correction retains metadata
bounds/presumed-address checks and actual readonly SMMU AP bits. Native
client-bound completed-fence lines distinguish backboardd's work from the
standalone shader process; queued GL frame counters alone are insufficient.

## Complete graphics/boot performance batch — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
RedwoodGPU::submit seed/4ms surface-cache policy, client-mapping treatment
and prepared surface retention. Redfin adopts that push policy, invalidates
only GPU-written surfaces after real synchronous completion, and permits
native prepared wrapped ranges with SweetSurface's wrapDelta rather than
MiniIOSurface's leading state page. Read-only wrapped pages retain read-only
GPU permissions. No asynchronous
completion or foreign fault recovery is introduced.

The runtime still makes complete stable global/CB0/CB1 snapshots before and
after each submission and compares every foreign word. Their read-only
callbacks use a bracketed CPU0/fixed-power epoch to avoid recursively
revalidating every parent on each register read. Table construction batches
cache-line publication before the same native ASID0 TLB synchronization;
ring publication cleans only the changed spans. Hardware writes keep their
full guards. CPU affinity switches occur only when actual migration is
required. GPU retirement moves after normal process exit.

The latest native capture's firmware copy alone costs20243ms. Redfin's
serialized GUI firmware worker now caches traversal of its pinned immutable
boot ADT; the existing value comparisons and source/owner/CPU/epoch guards
still run against live bytes. A bounded cache miss uses the original native
lookup. Native PAS4/MPSS copy/readback/GLINK/WLFW ordering and all aperture
fences stay unchanged. New phase timestamps make firmware/station delay
measurable. Hardware timing, wrapped-surface results and60fps remain pending
the complete combined run. Paired userland906425b75e02b4f99eb5d7bb1ef7c9583472d772
remains byte-identical.

## Saved exec path and bounded native graphics memory admission — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
RedwoodGPUUserClient::initWithTask and gemNew. Redfin now borrows the owning
task during synchronous init/start in the same way; its kernel/shared/WC
BO allocation flags already match. No change to GPU memory ownership or
allocation accounting is inferred from the diagnostic's per-process kill.
Actual XNU8796 exec_save_path stores executable_path= before the pathname;
the scoped insertion predicate must consume this native prefix.

Actual8796 memorystatus_set_memlimit_properties and its ledger update are
reviewed. GUI3's two graphics clients set512MiB fatal active/inactive limits
through that native setter and require the effective limit before allocation.
The helper remains in the setter's translation unit, outside DEVELOPMENT,
and cannot operate on another task. No global Jetsam bypass is introduced.
The existing userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 stays installed.
Hardware shader/system drawing/Metal still require actual evidence.

## Stock launchd filtering and graphics bootstrap correction — 2026-10-25

Reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
`redwood.patch` exec_inject_env/exec_extract_strings path. The current
20H392 launchd file log explicitly filters DYLD_INSERT_LIBRARIES from jobs;
AMFI permission alone does not supply the variable. Redfin now adapts the
native argument insertion point to one fixed loader, exact GUI3 and the
absolute /usr/libexec/backboardd path plus its basename. It keeps ordinary
NCARGS/string/pointer accounting and adds no configurable/global injection.
The earlier job EnvironmentVariables insertion is removed.

The same native file log proves backboardd's posix_spawn EACCES with its
new console redirections, and gpu-render's Jetsam per-process-limit kill.
The final bootstrap uses precreated501-owned logs and the actual launchd
ActiveHardMemoryLimit/InactiveHardMemoryLimit keys (512MiB each), rather
than its deprecated JetsamMemoryLimit key. Original Apple job properties,
all other jobs, kernel global memory policy and the full graphics block
remain retained. Hardware EAGL/shader results still require the next full
integrated capture; native HFS replay/clean shutdown are now observed.

## First system graphics panic: preserve high physical address bits — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab,
`xnu/redwood.patch`'s `pmap_sync_page_attributes_phys` hunk. The first
integrated20H392 graphics run reaches GPU BO creation in gpu-render, then
panics when a cache-mode change truncates1fc598000 tofc598000. Actual
frozen-kernel disassembly shows `lsl w0,w20,#14` before flush_dcache;
source casts the result of a32-bit ppnum_t shift. The preferred exact fix
casts pp to vm_offset_t before shifting. The Redfin overlay preserves
cache maintenance, WIMG changes and physical-aperture validation. It does
not change GPU mappings or reduce the installed EAGL/system graphics block.

## Complete system EAGL integration for 20H392 — 2026-10-25

Reviewed preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772:
`userland/src/eagl.c`, `gl_osmesa.c`, `redwood_gl.h`, `eagl_slots.txt`,
`userland/mkeagl.py` and the function-uniform hook in `src/inject.c`.
The MIT shader/IOSurface adaptations are kept together in the private build;
`eagl_userland.py` records and applies the Redfin source adaptations, with
the upstream license included. None of inject.c's 20F66 addresses, input
replacement or prototype Metal device is copied.

The initial interpretation of the 32-byte dispatch difference is superseded:
actual20H392 `getMacroContextPrivate` returns native-context+32. All457 GL
wrappers use the native context, with their first argument at+32; QuartzCore
uses the macro table with its context at+0. Subtracting that prefix gives
the preferred macro offsets. The adapter derives every stub, both ObjC
method signatures and the QuartzCore uniform vtable entry from this root's
paired arm64 cache/local symbols. It checks image UUIDs, exact method RVAs
and signatures before installing11methods. Its native prefix also supports
the reserved OpenGLES TLS key and class current-context methods. A private
copy of the actual QuartzCore uniform data page supplies the preferred
shader-less function parameters; the original function is still called.

Reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
`xnu/files/bsd/kern/kern_minimac.c`, AMFI request0x5a. Our previous policy
has no handler namedAMFI. The adaptation admits that native dyld query
only for backboardd in the exact GUI3 profile; other callers/requests retain
ENOPOLICY. The only inserted library is a minimal loader in backboardd's
existing job. It requires the published native A620/runtime ABI before
opening the Mesa bridge. GUI1/2 retain the existing graphics path.

The rendering diagnostic migrates its exact known cache key from Library
to System/Library/LaunchDaemons, matching the actual stock bootstrap scan.
The complete block is implemented before its combined build/verification;
system drawing and Metal remain unproved until actual hardware evidence.

## A620 persistent GUI3 / Mesa / IOSurface bridge — 2026-10-24

Reviewed kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab again, now
`iokit/Kernel/RedwoodGPU.cpp`, the retained-buffer/IB/fence/parameter methods
in `redwood_adreno.c`, and the native msm1.7 ABI. New service uses that
userspace interface with Redfin's proven native CB0/SID0/ASID0 owner.
Its first implementation serializes submissions and waits for the actual
GPU-written cache-flush fence. Mapping or completion loss pins backing
descriptors until reset. It omits the upstream optional reset/recovery path.
The kernel-side adaptation retains APSL2.0 attribution.

Reviewed paired graphics userland906425b75e02b4f99eb5d7bb1ef7c9583472d772:
`tools/mk-mesa.sh`, `tools/mesa/freedreno-darwin.patch`, the ES profile and
three IR3 fixes, `redwood-drm`, and `userland/src/gl_osmesa.c`. Mesa25.0.7
source archive is SHA256592272df3cf01e85e7db300c449df5061092574d099da275d19e97ef0510f8a6.
Build targets arm64/iOS16 and keeps all binaries under ignored research.
The newer a79ff077 userland review remains the general source pin; the
paired906425b graphics source is explicitly selected for this interface.

20H392's SweetSurface keeps state and pixels in separate descriptors, unlike
the preferred MiniIOSurface's page prefix. Import adapts that difference and
holds the original surface reference. A standalone iOS ES shader diagnostic
imports an actual IOSurface, draws twice with boot-bound colors and validates
both GL readback and the surface's CPU view; software rendering is refused.
The system's original OpenGLES/Metal libraries are not replaced by this batch.
Host checks and native builds pass; GUI3/rendering hardware evidence is pending.

First GUI3 capture reaches the GMU/global-SMMU boundary, then native XNU
`arm/io_map.c` exhausts its fixed8MiB permanent `io_submap` at a16KiB CB
mapping. It panics with KERN_NO_SPACE/NOFAIL, before any GPU DMA. Reviewed
`ml_io_map_unmappable` in `arm64/machine_routines.c`: it selects general
kernel-map DATA VA and the caller's exact IO7/NC6 attributes. All retained
GPU/GMU MMIO, CMD-DB and host DMA-alias mappings now use this native API;
no VM pool size, protected-bank access or device memory attribute is weakened.

## Complete A620 GPU command-chain adaptation — 2026-10-24

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`,
`redwood_adreno.c` steps17–21, allocations/streams/ring/SQE/zap/commands.
The complete opt-in mode5 adapts those interfaces to A620 with native msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`. Newly reviewed native references
include `msm_bus_arb_rpmh.c`, `msm_bus_fabric_rpmh.c`, `msm_kgsl.h`, and
the PIL relocation/allocation/authentication path. Captured FDT is checked
against DT pin `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`.

A620 uses275MHz/64, native DDR case5 and all13bandwidth rows, UBWC3,
FIFO10000/TSE-skip disable and hang3ffff. It has the native user SID0/mask401
route. The initial A642L split-mask400 adaptation is superseded after Redfin
HYP rejects it: schema3 uses the exact native single SID0/mask401 group.
CB0 is allocated independently
of the proven GMU CB1; foreign/secure state is audited. The native generic
PAS13 node has no memory-region, so its relocatable ELF receives an owned
1MiB-aligned allocation/4KiB span. This replaces the unsafe assumption that
the unaligned bootloader reservation is a writable zap destination. Both
SCM transport and PAS result must succeed; the upstream inherited-zap fallback
is deliberately not used. Native crypto BCM proxy floors are retained.

The same review now follows preferred native ordering as a complete profile:
reserve SMR0 for GPU, select SMR1 for GMU, obtain GX/OOB, mask local GPU
interrupts, then bind the GPU group before the native single CP start.
Standalone GMU modes keep their proven first-free choice. Runtime audits
use the unchanged GMU lease before GPU mapping, then the joint exact lease.

The v6 capture obtains all performance/BW/core/start ACKs and fresh GX/OOB,
then stalls before any logged GPU route or command. Re-review of native
`adreno.c:_adreno_start()` reveals a separate CPU→GPU_CFG HIGH request before
wakeup. The captured Redfin FDT binds APPS1→598 through SH4/SN10/CN0;
the initial adaptation only supplied GPU-initiated traffic votes. Schema4
adds the exact native CPU configuration client and both SN10/CN0 in the GMU
CNOC table. After GX/OOB, native fence ALLOW and exact access breadcrumbs
precede the first GPU CSR access. The v6 cause is not proven until validated.

The v7 capture validates CPU CFG votes and real RBBM CSR read/write, then
stalls precisely storing SQE_CNTL3. Native `adreno_a6xx.c:a6xx_rb_start()`
and preferred step20 only release SQE with CNTL1 after core/ring/SQE setup.
Schema5 removes the extra HALT3 request, retains fresh cold-domain ownership,
and admits exactly one native start after complete mapping/configuration.

Reviewed again for the first CB0 run: preferred `space_on()` verifies S2CR
type/context with mask300ff and preserves HYP control of other fields.
The GPU mapping now follows that readback mask and keeps the full observed
word in later audits. Native `arm_smmu_context_asid()` uses CB+1 while the
preferred standalone owner uses CB. The completed mapping review aligns our
standalone CB0 to preferred ASID0, distinct from proven GMU ASID1; schema2
binds it explicitly. This source alignment is not evidence of the earlier
unidentified readback failure's cause. Typed-map diagnostics record the step.

Actual source now includes the complete HFI/performance/bandwidth/GX/SQE/
signed-zap/ME_INIT/unsecure/memory-write chain before its integrated tests.
An early HFI-ready bit is accepted after reset release, matching the already
observed A650 firmware behavior. Current preferred userland pins remain
`a79ff0772a3454fd1ef127e181e5b3bce6c9ce18` and paired graphics-ABI reference
`906425b75e02b4f99eb5d7bb1ef7c9583472d772`; this batch installs no graphics
userland and makes no Metal-capability claim. Details: [GPU-COMMANDS.md](GPU-COMMANDS.md).

## A620 CM3/PDC/RSC/HFI start adaptation — 2026-10-24

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`,
`redwood_adreno.c` steps15/16, `block_uncached()` and HFI receive/send.
The separate explicit `--gmu-firmware-start`/redfinsmmu4 profile now adapts
that complete bring-up to A620 using native msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`: `adreno_a6xx_gmu.c`,
`kgsl_hfi.c/.h`, `a6xx_reg.h`, `kgsl_gmu.c` and newly reviewed `adreno.c`
local interrupt masking. DT remains pinned at
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`; actual captured FDT is validated.

A620 programs its own PDC instruction memory and TCS1/TCS3 commands using
runtime-validated CMD-DB xo/cx/mx and optional vrm.soc. RSC uses native
A650-family code and hidden TCS data80000000. These replace upstream's
AOP-programmed PDC and80000021 assumptions. The native RSC aperture is
4KiB: only contained TCS0/1 status/control are inspected; generic helper's
TCS2/3 outside the range are not touched. Inherited RSC sleep, if observed,
uses the native wake handshake before programming, with no retry.

HFI and log gain a verified contiguous uncached host view as upstream;
cached aliases are cleaned/invalidated before use and not accessed after
CM3 can write. Native HFI has4descriptors, not upstream's17. Version request
uses v2 header/16-byte padding; ACK checks full original header, status,
bounds and native2.0 version compatibility. No dependency on deprecated
v1 ACK ID126. Initial IRQ masks follow native `adreno_gmu_mask_and_clear_irqs`;
GIC remains disabled and host queues are polled. Lifecycle checks distinguish
held reset, fresh firmware completion and HFI startup; all owned SMMU/foreign
state is audited at transitions. Only one reset release is provided.

This profile sends no performance/bandwidth table, CORE_FW_START, GX request,
GPU CP command or PAS call and publishes no graphics/Metal capability. No
preferred userland ABI was changed; source snapshots remain those reviewed
below. Hardware CM3/HFI evidence is pending; host tests/build are not DMA proof.

First17464e8 hardware run reaches hidden RSC CMD0_ADDR: native zero write
reads back82204514. Native/upstream do not require zero destination readback;
the local protocol now preserves that behavior for the three hidden ADDR
registers while still checking data/uCode, actual PDC resource destinations
and control fields. No reset release or permission bypass was attempted.

Start-v2 validates RSC/PDC instruction words and native RSC data/control.
PDC MSGID10108 reads10100: command length byte is fixed/RAZ; native does
not require its echo. The local checker now requires native WRITEbit16 and
RESP_REQbit8, preserving all ARC destination/data and control verification.
RSC idle preflight also uses both native AMC_ENABLE16 and TRIGGER24 bits.

Project upstream preference, 2026-10-23: the user designates
[oosexgang/hackios-xnu-kernel][kernel] and
[oosexgang/hackios-xnu-userland][userland] as the most stable source repositories.
These are the primary references for ongoing GPU, display geometry/camera-cutout
and userland work. The review below identifies the exact snapshots already read.

Read-only review of two release snapshots, kept under ignored
`research/hackios-upstream/`. No upstream patch, prebuilt library or Apple
artifact was installed by this review.

| Repository | Pinned HEAD | History |
| --- | --- | --- |
| [hackios-xnu-kernel][kernel] | `8e61187098f2c26c5daee8f9f72b6416aa64b9ab` | Initial release `4ab189d`, then license; both 2026-10-22 |
| [hackios-xnu-userland][userland] | `906425b75e02b4f99eb5d7bb1ef7c9583472d772` | Initial release `89779df`, then license; both 2026-10-22 |

These are source snapshots, not a series of independently validated fixes.
The kernel contains XNU changes, platform drivers, a UEFI/loader path and
LinuxKPI/ath11k support. Userland contains its own init/APFS image builder,
injection libraries, job/test scenarios, an EAGL/Mesa bridge, a prototype
Metal implementation and shader-analysis tools. Its README declares Apple
files absent. Preserve per-file licenses and dependency notices when porting;
the userland's own code is MIT, while external dependencies have their own
licenses.

## Compatibility boundary

Reviewed 2026-10-24: preferred userland commit
`906425b75e02b4f99eb5d7bb1ef7c9583472d772`, `userland/mkjobs.py:287` removes
`_LimitLoadToDeviceTree` from selected jobs, explicitly explaining wifid's
absent `wlan` node. Redfin's real 20H392 cache retains the wifid gate
`[wlan, marconi-wifi]`, while the validated native GUI ADT has neither node.
The manual capture executes Preferences but never wifid; the user reports
a gray Wi-Fi switch with working touch. `wifi_userland.py` adapts this
upstream policy to **com.apple.wifid only**, preserves all other jobs and
properties, validates the stock program/startup/Mach-service identity, and
keeps the binary cache's exact length with offset-table padding. The fresh
Redfin root builder applies it after the generic root tweaks. No invented
Apple DT node or legacy `wifi=1`/modem path is introduced. The existing-root
update was backed up, bounded to its freshly resolved file allocation and
verified by full readback. The subsequent authenticated capture confirms
wifid executes once, discovers en0 and issues Apple80211 capability, power
and channel queries before the GUI cap. Manual Settings connection and
actual network data remain unverified.

After the user reports the same gray switch, the manual capture confirms
88 contacts/releases, two Preferences executions and the same ten initial
wifid driver queries, without a scan/power-set/join request before shutdown.
The next diagnostic adapts the same upstream `mkjobs.py` stdout/stderr and
`OS_ACTIVITY_DT_MODE=YES` policy to wifid alone. It is an explicit opt-in;
fresh-root preparation retains the normal logging policy. Equal binary
plist containers are shared to fit the additional keys within the current
file size, with full decoded-tree verification and preserved unrelated jobs.
This adds evidence, not speculative replies for optional Apple80211 ioctls.

Reviewed 2026-10-24: pinned Google SEC source
`0701b191882dc408104ad8af9e2f5eb2bf34c297`, `sec_ts.c:330..430`, retries
completed reads with bad sync/echo/checksum; `:2337..2350` clears a lost
event queue. Redfin's event session now distinguishes a malformed completed
reply from a GENI fault. It releases held contacts, drops the uncertain
queue with the existing bounded clear, and requires a validated empty reply.
It never replays consumed events. Hardware errors, ownership loss, failed
clear and a bad resynchronization reply remain final. This adapts native SEC
semantics; the preferred kernel's Goodix IC protocol is not substituted.

Reviewed 2026-10-23: the same pinned kernel's `redwood_adreno.c` step9
reads CB0, while step13 prepares a separate GMU context1. Redfin's new
explicit read-only CB0/1 observer uses native Lito's 64KiB resource, global
offset0x8000 and 4KiB context pages. It reads two stable passes, never follows
inherited TTBRs and introduces no context writes, firmware or iOS ABI change.
Hardware observes both translations disabled, faults zero and nonzero
residual configuration. This is observation, not a context-ownership grant.

Rechecked 2026-10-23: kernel HEAD remains `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`.
Userland now has HEAD `a79ff0772a3454fd1ef127e181e5b3bce6c9ce18`; its two
functional additions are `fcc3214` (thermald/bootok) and `a79ff07`
(standalone thermal probe). Reviewed changes cover thermal polling/sysctl,
pressure notifications, the launchd job and boot guard; they do not add an
A620 backend or update the private iOS16.5 graphics ABI. They depend on
`kern.redwood.thermal` and the upstream custom root/var-store, so they are not
installed into Redfin's Apple launchd/HFS root. The older paired source pin
below remains the graphics-ABI reference. The existing `redwood_adreno.c`
steps5/6 confirm clocks are enabled before GMU CSR inspection; step11 compares
PAS_SUPPORTED for known images and warns that all-zero responses alone can
be inconclusive. Redfin's raw4/13 query responses remain zero, not a successful
firmware-authentication result.

| | Upstream snapshot | Redfin |
| --- | --- | --- |
| Platform | POCO X5 Pro/redwood, SM7325, Adreno 642L, WCN6750 | Pixel 5, SM7250, Adreno 620v2, legacy ICNSS/MPSS WLAN path |
| Apple userland | iOS 16.5, 20F66, iPhone10,3 | iOS 16.7.16, 20H392, iPhone10,3 |
| XNU base | 8796.121.2 | 8796.141.3 |
| Root setup | Custom stage0/init, APFS volumes and recreated `/var` | Apple launchd, persistent journaled HFSX |

`inject.c`, `inject_sb.c` and `inject_media.c` contain 20F66 shared-cache
addresses; `eagl_slots.txt`, HID callbacks and Apple80211 structures also
describe private 16.5 interfaces. A matching model identifier does not prove
ABI compatibility. No injection, private-ABI replacement or prebuilt dylib
should be enabled before a separate 20H392 ABI proof. Their injection also
depends on `kern.exec_inject` and permissive dyld/AMFI policy; accepting an
unsigned executable does not grant its entitlements.

The root builder and daemon deny list are not suitable replacements for our
working boot. LaunchServices already passed Redfin's observed MobileGestalt
Wi-Fi identity wait; upstream provides no demonstrated additional fix or
LS database seed for that problem. Its job tools are useful as read-only
Mach-service/provider and OS/App-cryptex availability audits.

Reviewed 2026-10-24 against the actual 20H392 userland: MobileGestalt's
Bluetooth address data helper at `0x19c56883c` reads
`IODeviceTree:/chosen/mac-address-bluetooth0` through the CFData-checked
property helper `0x19c55b368`. Without it, it tries the IOService name
`bluetooth` and the factory `BMac` path, then repeats while neither exists.
The IOServiceMatching/IOServiceNameMatching/GetMatchingService calls were
resolved against the same cache's IOKit exports. The user's newly reported
About/Wi-Fi pane freezes are consistent with that missing identity; an
actual blocked Settings stack has not yet been captured. The existing
Wi-Fi chosen-property policy is extended with a separate stable six-byte
local-unicast Bluetooth identity, without importing Apple hardware nodes or
publishing a BT driver. The preferred upstream snapshots remain the source
reference, but no matching 20H392 identity-wait fix was found there. This
is a local ABI adaptation, not proof of functional Bluetooth or GUI Wi-Fi.
The subsequent manual test still freezes both panes; the identity fallback
is not established as their active blocker. The next local diagnostic uses
XNU's existing resident-only frame reader and scheduler lock to copy only
nonrunnable waiting threads, with a 200ms total budget. It does not import
upstream's single-core sampling assumptions into the eight-core GUI.

Reviewed again 2026-10-24 at preferred kernel
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`:
`xnu/files/iokit/Kernel/MiniIONetworkStack.cpp` documents and implements
the exact newly observed block. Actual Redfin waiting stacks show
`SCNetworkInterfaceCopyAll` → `__wait_for_IOKit_to_quiesce` →
`SCDynamicStoreNotifyWait` in wifid, while Preferences waits in
`MobileWiFi::_wifi_manager_open`. Apple's configd tag1241.140.6, commit
`3e58490132f08916564af041ed1c818514a01a46`, independently confirms
InterfaceNamer's stackCallback opens IONetworkStack before quietCallback
can publish the ready network state. Redfin now adapts upstream's minimal
IONetworkStack and user client under IOResources, in its existing WLAN
registry translation unit. It starts before the native WLAN interface is
published. Native BSD KPI already assigns en0, so unsupported naming writes
are refused as in upstream; no synthetic dynamic-store ready key or
userland binary patch bypasses the real InterfaceNamer flow. Runtime
validation succeeds: configd opens the service, both waiting snapshots
contain no IOKit-quiescence wait, wifid issues scan/join requests, and the
native station completes WPA2 association/four-way exchange and bidirectional
Ethernet traffic. The user confirms Settings connection and actual internet.

## Five porting targets

Kernel source references below are relative to `xnu/files/`; userland C
sources are under `userland/src/` in the respective pinned repository.

1. **GENI FIFO transport reference for SEC touch.**
   Kernel `bsd/dev/redwood_goodix.c:263` provides clock/DFS/GENI sequencing,
   and `:507` bounds FIFO operations. Local `SE_IRQ_EN` status enables at
   `:437` are needed even when polling with the GIC IRQ masked. Re-derive
   Lito SE0 clocks, pins, SPI mode 3 and SEC framing from [TOUCH.md](TOUCH.md)
   and [TOUCH-SPI.md](TOUCH-SPI.md); do not copy Goodix firmware, reset or
   power operations. The normalized input queue (`redwood_input.c:113`)
   and `rwtouch` can inform later replay tests, but the userland HID bridge
   needs its own ABI proof. Do not import the loader-return escape gesture
   or the hardware-starting `redwood_input_init()` wholesale.

2. **IOSurface allocation fallback, after observing a required format.**
   Kernel `iokit/Kernel/MiniIOSurface.cpp:460` substitutes BGRA when allocating
   `w30r`, `l10r`, `w30R` surfaces, and one-plane BGRA for `b3a8`; it does not
   convert existing packed pixel bytes. These names are absent from SweetSurface.
   First capture the actual 20H392 request, prove callers honor the reported
   format, and verify layout/stride/bounds before extracting this fallback. This is
   not evidence that our current BGRA path needs changing, nor permission
   to replace the existing IOSurface ABI.

3. **BSD networking and a serialized station boundary.**
   Kernel `bsd/sys/redwood_net.h`, `bsd/dev/redwood_net.c:292` and
   `bsd/sys/redwood_sta.h` separate Ethernet frames/ifnet from radio work.
   `iokit/Kernel/RedwoodWLAN.cpp` publishes the properties configd and wifid
   use for Wi-Fi discovery and DHCP. Adapt these only after Redfin firmware,
   association, keys and the frame path work; the WCN6750/ath11k backend is
   not Redfin's ICNSS/MPSS backend. Re-derive Apple80211 ioctl layouts for
   20H392 and remove the one-link/fixed-`en0` assumption before USB coexistence.
   The bounded QMI codec (`redwood_qmi.c:388`, `:526`, `:844`) is a separate
   candidate behind a Redfin QRTR transport; upstream host checks do not
   prove that transport. Userland `net_test.m`, `keychain_test.c` and
   `wifipw_test.c` provide layered validation. Verify the handwritten
   IPConfiguration MIG ABI; let configd own DHCP when its service exists.

4. **Mesa/freedreno's Darwin GPU contract, after an A620 backend.**
   Kernel `iokit/Kernel/RedwoodGPU.cpp:733`/`:930` and userland
   `tools/mesa/redwood-drm/` describe buffer allocation/mapping, submission
   and fences for Mesa. They require a working **Redfin Adreno 620 backend**:
   source-proven power/GMU/firmware sequencing, owned SMMU mappings, bounded
   submission and verified RAM output; see [GPU.md](GPU.md). Upstream's
   SC7280/642L `redwood_adreno.c` and a660 firmware are incompatible with
   A620 bring-up. This custom msm-DRM-like bridge is not an implementation
   of Apple's IOGPU ABI. Keep inherited `gpu=0` until the separate hardware
   contract is proved.

5. **A separate CPU OSMesa experiment, planned only.**
   `gl_osmesa.c:95` recognizes softpipe/llvmpipe and declines GPU surface
   import; `eagl.c:674`/`:795` demonstrate ordinary IOSurface CPU upload and
   BGRA readback. This path has **no A620 prerequisite**. The first proposed
   contract is our own standalone `libGL` wrapper and executable drawing a
   coloured quad into an owned CPU buffer with checked pixel output.
   No wrapper or experiment has been implemented or installed. It does not
   require Apple filesystem writes, daemon injection or renderer changes.
   Adapting the private EAGL table and our SweetSurface/display path would
   be later, separately proved work; no performance improvement is assumed.

Keep the prototype Metal plugin unadvertised. It lacks major operations,
and publishing Metal capability changes CoreAnimation's renderer choice.
Upstream's workaround for missing system metallibs modifies a 16.5 static
device array; it is not a portable Redfin fix. There is no new XNU DWC3
driver in these snapshots: loader/UEFI USB transport does not replace the
Redfin PHY, clock and DMA work in [USB.md](USB.md).

## A620 GMU memory/context adaptation — 2026-10-24

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`,
`redwood_adreno.c` step13 and `space_on()`: clean owned tables, program a
disabled context, synchronize TLB, publish S2CR then valid SMR, and verify
hypervisor-mediated readback. Redfin now adapts this sequence to the native
64KiB aperture, CB1, stream5/mask `0x400`, A620 firmware memory map and
native noncached page attributes. Global controls and foreign routes stay
outside the write interface; initial faults are refused rather than cleared.

Native Google msm `500b3a2059c1eec0fec08ec56add06320ea901a8` was rechecked
for `arm-smmu.c` context setup, mandatory atomic ATS1PR writes and PAR
interpretation, `arm-smmu-regs.h` FSR fault/FORMAT separation, and
`io-pgtable-arm.c` 39-bit/4KiB/36-bit-PA NC walks. The Lito DT remains pinned
at `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`. XNU supplies wired zeroed
contiguous allocations and verified physical pairs; no bootloader TTBR or
upstream A660 firmware is reused. The private inventory's A650-family GMU
image is bound by recorded SHA256 before power writes.

The preferred userland snapshots remain `a79ff0772a3454fd1ef127e181e5b3bce6c9ce18`
and `906425b75e02b4f99eb5d7bb1ef7c9583472d772`; this stage does not change
their ABI or publish graphics capability. CM3/GX stay stopped while the
memory profile verifies every payload and owned ATS translation. Native
firmware execution/HFI, GPU command output and the actual20H392 graphics
bridge remain unfinished; see [GPU-SMMU.md](GPU-SMMU.md).

After memory-v1's TCM readback refusal, rechecked native
`adreno_a6xx_gmu.c:a6xx_gmu_fw_start`: cold boot writes `GENERAL_7=1` before
loading TCM. Redfin schema2 includes that retained-memory prerequisite and
keeps the preferred upstream step13 mapping/ATS before step14 TCM transfer.
Upstream step16's AOP-programmed PDC must still not be copied: A620's native
`pdc_in_aop` is false, and native RSC hidden TCS data is `0x80000000`, unlike
upstream's `0x80000021`. Those differences are review findings for the later
CM3 startup, not hardware changes in this memory profile.

The v1/v2 failures exposed a local adaptation error, not an upstream defect:
`space_on()` uses a single-instruction `wr()` asm, whereas the local combined
barrier/store string incorrectly used semicolon separators. Darwin dropped
everything after the first semicolon. Word and atomic ATS helpers now use
newlines; actual Darwin ARM64 opcode checks cover both widths and zero
values, including the separate native XNU object. Readback ownership guards
remain unchanged; no HYP permission or register-mask bypass was added.

Memory-v3 confirms real CB1 stores but TCR2 retains reserved bits6:5.
Schema3 now compares native active TCR2/TCR/SCTLR fields and retains full
observed words for later exact audits. Native `arm-smmu.c` only programs
CONTEXTIDR for AArch32 short descriptors; that unused store is removed from
the AArch64 sequence. The inherited snapshot value stays audited. Tests
include the captured reserved-bit behavior and refusal of altered PASIZE,
walk cacheability, TTBR1 ASID selection, stall and memory-type override.

Native hardware memory-v4 also reports SCTLR.ASIDPNE RAZ (`0x1027→0x27`),
with all other active controls accepted. Schema4 records that readback and
continues requiring TCR2.AS, TTBR0 ASID1 and TCR.A1=0. The preferred
upstream checks SCTLR.M rather than whole-word ASIDPNE equality; the local
fault/IRQ/stall/endian/memory-type checks remain more explicit.

Memory-v5 accepts the full owned context/route sequence but generic ATS
returns PAR0. Rechecked the native `arm_smmu_device_cfg_probe()` condition:
SMMUv2 ID0.ATOSNS bit26 disables generic translation operations; Redfin's
captured `0x4c017e05` sets it. Native `qsmmuv500_iova_to_phys_hard` uses
the separate TBU ECATS path. Schema5 therefore skips unsupported generic
ATS, preserving explicit unavailability rather than inventing a successful
translation or accessing a new TBU debug range. DMA proof remains for
actual CM3/HFI traffic or a separately adapted native ECATS implementation.

Authenticated source54e9dbe/memory-v6 now passes owned memory/context/route
and all7firmware payload readbacks with CM3 reset held. No new upstream
commit or userland ABI was imported. The next adaptation remains native
A620 PDC/RSC (not the AOP-programmed upstream variant), CM3 completion and
fresh HFI traffic; readback alone is not claimed as DMA/Metal support.

## Display fit and camera geometry review — 2026-10-23

Rechecked both pinned HEADs in the table above. Kernel
`iokit/Kernel/MiniIOMobileFramebuffer.cpp:583`, `:603` and `:723` implement
pixel-center bilinear sampling, checked source rectangles and projection of
the complete logical canvas onto the physical panel. Redfin's older CPU path
instead cropped at source 20,48 and ignored source rectangle dimensions.
`display-fit.patch` now applies the reviewed scaling policy to Redfin's
existing SweetSurface and 20H392 swap record. It does not import the upstream
MiniIOSurface/IOFramebuffer ABI, injection code or a different device identity.

A case-insensitive search for `notch`, `cutout` and `safe.?area` in the pinned
kernel's `xnu/files` and userland's `userland/src` found no dedicated override.
The full-canvas scaler is published; a dedicated camera-cutout fix has not
been identified in these public snapshots.

The physical front-camera exclusion is independently source-backed by
Google's [Redfin Android overlay](https://android.googlesource.com/device/google/redfin/+/62df7438508565dfc05fab923e84f0704f5a0f07/redfin/overlay/frameworks/base/core/res/res/values/config.xml#208),
reviewed at commit `62df7438508565dfc05fab923e84f0704f5a0f07`.
The Apache-2.0 resource specifies a radius-40 circle centered at 81,77 and
the conservative rectangle `[0,145) × [0,136)`, anchored to the left edge.
Its portrait status-bar height is also 136px. `redfinfit=2` therefore fits the
complete 1125×2436 iPhone X canvas into 1017×2204 pixels at 31,136 and paints
the margins black. `redfinfit=1` fits into the complete panel without the
camera exclusion. Both modes inverse-map SEC touch through the same checked
viewport. The default remains the legacy crop.

Nine host tests pass, including actual patched presentation/HID methods,
independent bilinear pixels, immutable guarded source memory, clipping,
malformed extents, margin gestures and ASan/UBSan. Physical alignment,
rounded corners and on-device scaling throughput remain unverified;
[DISPLAY.md](DISPLAY.md) records the exact contract and next bounded test.

## Native GPU and Wi-Fi firmware boundaries — 2026-10-23

The preferred HackiOS snapshots remain unchanged. Their GPU/Mesa and network
interfaces are the later integration targets, while native Lito dependencies
are derived from the pinned Google sources above. Commits `de80451` and
`13f403b` add the A620 GMU firmware/HFI planner and reset-held 200MHz
clock/counter/TCM helper; `52137f3` corrects its CX proof to use the live-DT
separate hardware-status register. These helpers have host validation;
GMU firmware execution, GPU commands and rendering are not established.

Commit `05f371f` validates Redfin's native MPSS firmware layout and PAS4
lifecycle. The private base-vendor inventory has 35 program headers/33 load
segments/31 assets and a 0x8c000000+0x11800000 reserved span. Its endpoint
0x9d800000 does not overlap Redfin's actual 0xa0000000 splash reservation.
This adapts native ICNSS/MPSS dependencies; upstream Redwood WPSS/PAS6 and
ath11k are different hardware. See [WiFi.md](WiFi.md) and [GMU.md](GMU.md).

Reviewed again, 2026-10-23: kernel
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`, `redwood_image.c` and
`redwood_wifi.c` step6. Their resident plain-firmware mechanism informs the
separate Redfin MPSS source probe. Redfin keeps its bounded flat segment,
native PAS4 layout, original PHDR indices, complete live exclusions and
read-only source lease; it does not import Redwood's APFS dependency,
WPSS/PAS6 destinations or WCN6750 radio backend. Local build144832 and host
preflight establish the new source-only profile; hardware results belong
in NOTES.md, independently of upstream's stage descriptions.

## Native PIL integration review — 2026-10-23

Continued the preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
`redwood_wifi.c` review for its serialized worker and later GLINK/QRTR stages.
Redfin's actual MPSS boot remains derived from Google msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`: `peripheral-loader.c`,
`subsys-pil-tz.c`, `scm.c`, `msm_bus_arb_rpmh.c` and
`msm_bus_fabric_rpmh.c`. Reviewed Lito bus definitions at DT commit
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`, `qcom/lito-bus.dtsi`,
and verified every selected route/member against the saved live Redfin FDT.

The native peripheral loader passes region_start to PAS metadata init;
metadata-at-MPSS-base is therefore source-backed. The two PIL bandwidth
clients require six APPS BCMs (CE0/SN6/SN0/SH0/MC0/ACV), with native CMD-DB
geometry and the APPS ACV bit. Redfin now implements these before its
PAS4/SMP2P boot sequence; Redwood's PAS6/RF backend is not substituted.
Software/native-build results and pending device execution are recorded
separately in NOTES.md. Upstream's WLAN/ifnet remains a later consumer.

The subsequent hardware run proves all native bandwidth/AOP prerequisites
but stops on transition to an extra initial PAS shutdown. Re-reviewing the
same Google's native cold PIL confirms INIT/MEM_SETUP is first. Redfin's
corrected caller therefore stages metadata in an explicitly reserved high-RAM
scratch page and requires SMC64; it grants MPSS write authority only after
successful same-session INIT/MEM_SETUP. This adapts metadata storage to
Redfin's high-only XNU RAM and removes the unneeded cold shutdown. The scratch
pointer's acceptance by TrustZone is still a device question; native code and
the preferred HackiOS PAS6 result cannot establish it for MPSS4.

The corrected high metadata route is now verified by Redfin PAS4 INIT,
MEM_SETUP, complete copy/readback, AUTH and a new SMP2P ready/handover0x6.
For the following transport work, re-reviewed the same preferred kernel's
`redwood_wifi.c` GLINK/QRTR frame and worker interfaces alongside Google's
native `qcom_glink_smem.c`. Redfin binds its own live PID1, IPCC2/signal0,
SMEM478/479/480 and IPCRTR, using bounded allocation/rings and a continued
native ready lease. No Redwood WPSS geometry is imported. The first stage
discovers QRTR/WLFW services; its hardware evidence is recorded separately.

Native GLINK/IPCRTR/QRTR is now observed on Redfin, including bidirectional
HELLO and remote servreg/sysmon announcements. Legacy ICNSS additionally
needs APPS pd-mapper/TFTP, which the preferred WCN6750/WPSS backend does not
provide. Reviewed Sapphire's host-service wire contracts in0121 and the
captured native `modemuw.jsn`, retaining only bounded servreg/TFTP logic and
the actual Redfin WLAN domain. Partition tables, UFS/EFS/RMTFS, pool addresses
and assignment code are excluded. The captured WLAN files stay private and
read-only; base-vendor compatibility remains a live firmware question. The
preferred kernel's WLFW/QMI framing and native `icnss_qmi.c` inform the next
CAP0x24 query, without importing ath11k/WCN6750 hardware or radio settings.

After the first host-service hardware run, reviewed native IPA's
`drivers/platform/msm/ipa/ipa_v3/{ipa.c,ipa_i.h}` at the same Google pin.
Its SMP2P response uses complete bit0/APPS clock-vote bit1. Redfin's absent
APPS IPA vote can be acknowledged once through the owned outbound entry,
without asserting an aggregate power reading or touching IPA registers.
The live FDT's IPA entry/consumer-bit route is bound explicitly. The saved
modemr.jsn root_pd metadata adds only its actual servreg/GPS services; absent
PDR/dump services are preserved. The previous root metadata and the reviewed
Sapphire IPA wire behavior are cross-checks, not replacement hardware IDs.

RMTFS review, 2026-10-23: Google pin's
`drivers/uio/msm_sharedmem/msm_sharedmem.c` and `secure_buffer.c`, plus
[linux-msm/rmtfs b30a3eb38f9af283f18dbd3c7755653efc52c094](https://github.com/linux-msm/rmtfs/tree/b30a3eb38f9af283f18dbd3c7755653efc52c094)
`qmi_rmtfs.{h,c}`, `rmtfs.c`, `sharedmem.c`. Redfin's UIO client1 allocates
0x280000bytes dynamically, then shares HLOS/MSS permissions; its reg0 is not
an MMIO/RAM address to reuse. Allocation replies are64bit, IOVEC physical
fields32bit. The next observer returns explicit unavailability only: it
cannot grant a handle, DMA buffer or storage access. No upstream partition
table, EFS writer, ignored assignment failure or guessed pool is imported.
The extra captured base-vendor JSONs contain no PDR-enable/dump-disable
service; those absent responses remain grounded in the actual inventories.

RMTFS implementation review after hardware OPEN demand, 2026-10-23: the same
Google `msm_sharedmem.c` chooses HLOS3/MSS_MSA15, permissions6, for Redfin's
client1 without `qcom,vm-nav-path`. Its `secure_buffer.c`, `secure_buffer.h`
and `scm.c` establish two 24-byte destination records, seven arguments and
the ARM64 extended-argument buffer for MP0x0c/ASSIGN0x16. No NAV permission
or inherited Sapphire pool is used. The linux-msm/rmtfs pin above supplies
the OPEN/CLOSE/ALLOC/IOVEC/GET_DEV_ERROR wire contracts and read-only shadow
semantics. Their partition contents and storage writer are not imported.
Four native Redfin partitions are captured twice through verified offline
recovery; only private, hash-bound snapshots and volatile shadows enter the
temporary image. A top-down free-DRAM allocation is checked against the
actual live FDT, Image, DTB and XNU RAM by the shim before zeroing/claiming
the guarded low buffer. Assignment failures remain failures; buffers and
mappings remain retained until the platform resets. Hardware results are
recorded separately in NOTES.md.

Legacy WLFW setup review, 2026-10-23: Google pin
`500b3a2059c1eec0fec08ec56add06320ea901a8`, `icnss.c`, `icnss_qmi.c`,
`wlan_firmware_service_v01.{c,h}` and `include/linux/soc/qcom/qmi.h`.
The observed CAP error90 is `QMI_ERR_INCOMPATIBLE_STATE_V01`. Native order
is IND_REGISTER0x20 (client0x4b4e454c), MSA_INFO0x2d, MSA_READY0x2e,
then CAP0x24. MSA_INFO has at most two13-byte wire records. Redfin's
captured live ICNSS references `pil_wlan_fw_region@8ba00000`,2MiB,
`removed-dma-pool`/`no-map`; `qcom,hyp_enabled` is absent. The native driver
therefore skips `hyp_assign_phys` for this fixed MSA. The new optional QMI
handshake preserves that behavior, validates every returned subregion, and
does not map/zero MSA on the CPU or enable WLAN clocks, supplies or mission
mode. The shim independently requires that exact fixed reservation in its
actual FDT hardware view before validating the handoff. Reviewed preferred
kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`, `redwood_wlfw.c`:
its WCN6750 indication/HOST_CAP/CAP order is useful protocol context, but
does not replace Redfin's legacy MSA exchange or native client/instance IDs.

ICNSS supply review after CAP succeeds, 2026-10-23: the same pinned
`icnss_get_vreg_info`, `icnss_vreg_on`, `icnss_get_clk_info` and
`rpmh-regulator.c` establish the consumer/provider split. Actual Redfin
overrides `vdd-cx-mx-config` to0/0 (provider init voltage352mV) and both
3.3V-chain requests to3000..3312mV. XO/RFA use native1800/1304mV defaults.
All five providers are PMIC5 LDO VRM resources with native LPM selector4;
the optional XO pin clock has no live DT binding. CAP TLV0x1b is the optional
signed32-bit chain capability; native ICNSS skips chain1 for value1.
The observer binds these exact DT inputs and reads the five named VRM
records twice through the already-owned read-only CMD-DB mapping. Queued
inherited TCS entries retain their enabled/idle metadata; they are not a
measurement of current aggregate regulator outputs. No WLAN VRM/PMIC/clock
write is added in this observation stage.

The subsequent native observer confirms VRM addresses40800/42100/41d00/
41a00/41900 for ldoa1/ldoa14/ldoc2/ldoc11/ldoc10, aux0x100/4bytes and
zero priorities. The optional power profile pins these exact records and
the reviewed PMIC5 provider/consumer sequence: final352/1800/1304/3000/
3000mV requests, native LPM mode4, then enable1 for each selected supply.
CX352mV emulates its provider initialization, which native ICNSS's0/0
consumer override preserves. Missing chain capability retains native two
chains; reported1x1 omits chain1. Only the already-owned DRV2 ACTIVE slot is
used, with the base ARC/BCM/AOP ledger retained and the same live MPSS child
checking every write/poll. Uncertain requests remain held until reset.

After the first power run accepted all15 requests without FW_READY,
reviewed the same native `wlfw_dynamic_feature_mask_send_sync_msg` and
generated codec. Native defaults register rejuvenation TLV0x19/u32=1 and,
after power, send message0x3b/TLV0x10/u64 mask1. Response previous/current
masks are independent optional u64 fields. The power-only profile now
performs that exchange; valid QMI errors remain recorded without changing
the separately successful CAP identity. Native rejuvenation indication0x39
quarantines this bounded epoch until platform reset instead of claiming an
unperformed recovery. Pin-result indications preserve their actual fields.

## Physical WLAN PMIC observation review — 2026-10-24

Rechecked Google's native ICNSS post-CAP order at
`500b3a2059c1eec0fec08ec56add06320ea901a8`: supplies/optional clock, then
dynamic feature mask. Those requests already succeed on Redfin; their ACKs
do not establish physical regulator outputs. At the same pin,
`spmi-pmic-arb.c` supplies v5 EE0 observer offsets, duplicate-APID selection
and EXT_READL encoding; `qpnp-revid.h` identifies PM8150/PM8150L subtypes
`1e/1f`. Rechecked `pm8150.dtsi`/`pm8150l.dtsi` at DT pin
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4` against the saved live SIDs0/1/4/5.

Re-reviewed Qualcomm firmware
`20bb8ae36c93fc16bbadda0e0a83f930c0c8a271`:
`pm_config_common.c`, `pm_ldo_driver.c` and `pm_pwr_alg.c`. Its explicit
type-LDO/subtype>=30 branch establishes the unified raw register layout,
including configured40/41 and VALID42/43 mV, mode45, enable46 and status08.
The common4000/stride100 map and already observed SID1 ordering support the
PM8150 candidates. SID5's WLAN supply pages remain candidate attribution;
this firmware is not a Redfin target table or authorization for a regulator
write. The new optional observer reuses the existing SPMI mappings and
checks the live native MPSS child before every read command/poll. It adds
no PMIC/GPIO/clock write, RSC vote, memory assignment or readiness policy.

The first authenticated physical run reads SID4 `0x2751`, so its `pm8150l`
live-DT label does not establish the PM8150L identity `0x1f51`. Rechecked
the Google pin's `qpnp-revid.c` and Linux v6.12 commit
`adc218676eef25575469234709c2d87185ca223a`
`include/soc/qcom/qcom-spmi-pmic.h`; neither names subtype27. The revised
raw observer pins the authenticated `0x2751` identity without assigning an
unverified model name. The per-peripheral type/subtype check still controls
the generic unified read layout; neither model matching nor a DT label
grants power policy or new PMIC write authority.

After all PMIC snapshots succeed without FW_READY, rechecked native ICNSS
`register_fw_error_notifications`/`register_early_crash_notifications` at
the same Google pin. The actual FDT maps inbound SMP2P entry `wlan` bit0
to force-error-fatal and bit1 to early-crash. The bounded peer parser already
reads/validates both complete stable snapshots, including this entry; it now
retains its raw presence/index/value for diagnostics. No additional SMEM or
MMIO read, interrupt registration, acknowledgement, recovery or readiness
decision is added. A zero value remains distinct from an absent entry.

MSA diagnostic review, 2026-10-24: the same native `icnss_qmi.c`
`msa_ready_ind_cb` preserves optional hang-data offset/length, caps it at
400 bytes and maps that firmware-announced window. `icnss.c` copies it on
an early crash. Redfin now retains the optional fields and has a separate
opt-in timeout observer. Its pure planner requires successful MSA/CAP and
an accepted nonsecure region covering every whole16KiB mapped page, while
the fixed reservation remains shim verified. It rejects secure, missing,
overlapping, oversized, partial-page or unaccepted windows. The native
adapter maps only that bounded read-only Normal-NC alias, takes two samples,
and releases only its local alias. It introduces no MSA clearing, permission
assignment, DMA grant, power write or readiness decision. Default setup and
PMIC profiles do not perform this MSA CPU read.

Reviewed Linux v6.12 `adc218676eef25575469234709c2d87185ca223a`
`drivers/net/wireless/ath/ath10k/{qmi.c,snoc.c}` after the zero hang result.
For WCN3990, this client sends HOST_CAP daemon_support0 and, after MSA,
downloads the selected BDF and sends CAL_REPORT before firmware readiness.
Native Google's kernel ICNSS flow does not contain those transfers, so its
Android userspace host service and actual Redfin board selection are the
next references. No generic ath10k BDF, CRC-error workaround, permission
assignment or hardware geometry has been imported by this comparison.

## Redfin DMON/BDF reference review — 2026-10-24

Google redbull `3595d0b214eeeddf87e2c37477e3e74f831eca82`
`init.hardware.rc` starts `/vendor/bin/cnss-daemon -n -l`. Statically
reviewed that Redfin binary from TheMuppets' pinned
`proprietary_vendor_google_redfin` commit
`30c82c83bc03b0dfc83dd6d6a041f51fc35ebfab`, SHA256
`9d38f1d7cf6b1b34e6f03fefbfd87135eb5938f1573e65fefeb3dad905318af7`.
It remains private/ignored and was never executed or installed. Its embedded
mini-debug symbols identify `wlfw_adrastea_init`, registration, CAP,
BDF_DOWNLOAD and CAL_REPORT, permitting a bounded disassembly review.

The daemon registers a distinct DMON client `444d4f4e`, waits for MSA,
queries CAP and sends BIN BDF before its calibration report. Its
`wlfw_send_bdf_download_req` at f590 selects prefix `bdwlan-u` for the
actually observed chip4320. With absent-board fallbackff it tries hardware,
revision/radio variants then `bdwlan-u-redfin.bin`; only that canonical
fallback and the separate non-u file exist in the captured base listing.
The new profile binds the canonical26328-byte u file and its captured SHA256,
without claiming the unproved active Android/COW or OTA-config view.
Native BIN messages use file_id0, full original total_size, sequential
segments, type0 and a final end flag. The empty calibration list explicitly
reports no cache; cal_remove_supported0 matches the native default.

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
`redwood_wlfw.c`'s resident-file/QMI transfer interface. Redfin uses its own
legacy BIN ABI and full total_size rather than Redwood's ath11k remaining-
size/ELF convention or board IDs. Chunks2048 fit the established Redfin
QRTR queue and are within the native6144-byte variable-data limit.
The bounded DMON profile subscribes to FW/MSA only (the mainline notification
subset) and promises no calibration download/update or persistent cache.
Every ACK must succeed, including final CRC; no CRC-error exemption, retry,
mission mode, new memory assignment, DMA or partition writer is added.

## Native SNOC data-plane entry review — 2026-10-24

Reviewed Linux v6.12 `adc218676eef25575469234709c2d87185ca223a`
`ath10k/snoc.c:932..1105`, `qmi.c:380..505`, and native Google msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`
`icnss.c:2372..2394`/`icnss_qmi.c:1358..1437`. The source order is
power, WLAN_CFG, acknowledged WLAN_MODE mission, optional read-index
memory, CE initialization, then interrupt/RX servicing. Firmware readiness
alone is not permission to access WLAN registers or use inherited rings.

Re-reviewed the preferred kernel snapshot
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
`wifi/lx/src/lx_bus.c` and `lx_80211.c`: retain its separation between
bus servicing, station/WPA2 and Ethernet/iOS layers, adapting the ath10k
SNOC backend instead of its WCN6750 ath11k windows, MSI or ring ABI.
The station layer remains a later consumer of a proven packet path.

The captured native ICNSS binding is WLAN `18800000+800000`, APPS SMMU
SIDc0/mask1, host IOVA `a0000000+10000000`, and12 CE SPIs. Its named
IPA IOVA aperture `b0000000+10000` is separate; neither it nor the retained
RMTFS allocation grants CE RAM. APPS SMMU has no optional clock/static-CB
binding in this capture and is independently readable in the bounded USB
profile. The new post-readiness observer pins that established layout,
double-reads every SMR/S2CR and each CB's SCTLR/CBAR/CBA2R/FSR, and counts
latent references even when the SMR is invalid. It never reserves a CB,
changes routes, acknowledges faults, touches TCU/TBU/CE or authorizes DMA.

The follow-on explicit mission profile uses native WLFW WLAN_CFG23 and
WLAN_MODE22 with successful matching ACKs, transaction6/7 on the existing
kernel port. The12 target-pipe,21 service-pipe (including native sentinel)
and12 legacy shadow-register entries match Linux's WCN3990 tables and the
inherited `xnu/patches/0122` layout. Reviewed native QMI descriptors confirm
one-byte array counts, five serialized u32 fields per target entry, and
u16 CE/offset pairs; host-only reserved fields are not on the wire.
Mission0/hw_debug0 follow native ICNSS. Unknown/failed ACKs never grant CE
access. Fresh complete SMMU snapshots retain WLAN unmatched and preserve
the foreign routes/contexts before/after both requests.

Reviewed ath10k `hw.c:190..337`/`ce.c` at the same pinned Linux commit and
inherited `0123`'s mission-before-CE entry. Only after mission ACK and a
100ms settling interval, serviced by the same GLINK worker, may the adapter
double-read the12 CE banks at WLAN+240000 and the wrapper. This is still
a read-only register observation, with no ring/RRI programming, buffers,
host route, DMA or station registration. The preferred upstream's bus/
station separation remains the software reference for the packet stage.

[kernel]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[userland]: https://github.com/oosexgang/hackios-xnu-userland/tree/906425b75e02b4f99eb5d7bb1ef7c9583472d772

## Complete native packet/station/GUI composition — 2026-10-24

Reused the preferred kernel's pinned `bsd/dev/redwood_{net,sta,apple80211}.c`,
`bsd/sys/redwood_{net,sta}.h`, `iokit/Kernel/RedwoodWLAN.cpp` and
`wifi/lx/src/lx_wpa.{c,h}`. The adapted Redfin sources retain the serialized
station requests, BSD Ethernet boundary, Apple80211 events/ioctls and
SystemConfiguration registry discovery. Interface units/names are selected
from free BSD names instead of assuming en0. The IOCTL layouts originate
from upstream's iOS16.5 review; their actual20H392 behavior is still a device
validation item. No Apple binary or daemon from another release is copied.

The inherited `TopazModem.cpp` already contains ath10k-compatible
CE/HTC/WMI/HTT, scan, management, association and Ethernet code from
patches0122/0123/0129/0130. A narrow native callback boundary reuses those
software layers while Redfin owns PAS4, GLINK, power, MMIO and memory.
The legacy modem startup, fixed E0000000 pool, SM6225 SMMU/WLAN addresses
and filesystem firmware/EFS paths remain disabled by modem0/wifi0.
Redfin WMI uses the actual service-ready RF-chain count (at most two).
The preferred WPA2 engine adds its checked lengths, MIC/nonce/replay/key
unwrap and group-key path; duplicate message3 retransmits message4 without
reinstalling keys. Join names/keys are not printed by the native join path.

The WLAN-only context adapts the reviewed native non-static allocator and
the proven USB AArch64 bypass sequence: retain all latent references,
claim one disabled unreferenced NS bank and one invalid stream slot, then
disable SCTLR, set CBA2R1/CBAR10000, publish TRANS and finally SIDc0/mask1.
Each uncertain write or foreign-state change stops without retry/release.
Reviewed again2026-10-24 after the actual WLAN refusal: native FSR
FORMAT[10:9] reports AArch642 (`0x400`) immediately after CBA2R.RW64=1.
The already validated `usb-context-format-status.patch` accounts for this
read-only status. WLAN now predicts that same field only in its owned bank;
all fault bits, other owned fields and foreign contexts remain exact. No
FSR acknowledgement or new store is introduced. The actual-C/C++ lease
model now emulates this hardware side effect, rather than a plain RAM bank.
The separate16MiB DMA32 buffer has two16KiB guards; its complete proposed
range is checked against the actual Image/DTB, XNU, all live reservations
and retained RMTFS before the shim initializes it. RMTFS is never spare CE
RAM. Native callbacks admit only the host CE fields, owned ring addresses
and three reviewed TX shadows; firmware-side ring geometry stays intact.

Reviewed again2026-10-24: Linuxv6.12 `ce.h` defines WCN3990's
`CE_DESC_ADDR_MASK=GENMASK_ULL(34,0)`; `ce.c` posts masked addresses and
returns RX through the saved transfer context. The native Redfin receive
guard now compares those address bits to its exact posted buffer while
retaining the actual2048-byte bound. The CPU uses only its own buffer
pointer. Upper completion control/metadata is not a new DMA pointer.
The completion barrier precedes remaining descriptor/payload loads; rejected
descriptors log length, raw address/flags and the expected posted address.

Reviewed again2026-10-24 after real HTC/WMI/HTT, ifnet publication and scan:
native `snoc.c:host_ce_config_wlan` distinguishes the host side of each CE
from its live firmware side. Runtime audits now protect only the host's
source/destination base/size and the owned CTRL1 subfields, plus the separate
host RRI address. Firmware-owned ring configuration and indices remain live;
CTRL1 writes must preserve the current unowned bits. Whole APPS SMMU and
DMA guards stay exact. Refusals identify the responsible SMMU/CE/RRI field.
Native `wmi-tlv.h:wmi_tlv_rdy_ev` confirms the24-byte ABI/MAC/status layout;
the observed zero firmware MAC is not a private-ABI offset fix. One local
unicast address is chosen for this boot when firmware supplies no usable
address, consistently before vdev/station/ifnet publication. A nonzero READY
status never grants native readiness.

Read-only userland review2026-10-24 at `906425b75e02b4f99eb5d7bb1ef7c9583472d772`:
`userland/src/net_test.m` supplies getifaddrs/SystemConfiguration, DNS/TCP/TLS
checks and a bounded interface wait. Its `wifi` job keys off legacy `wifi=1`
and uses a handwritten IPConfiguration MIG20011 fallback only when configd
has no service. Redfin GUI deliberately keeps legacy wifi0; the companion
job/prebuilt is therefore not imported as-is. Stock service discovery must
be assessed before introducing that optional fallback, and its20H392 Mach
layout remains a separate validation item. No helper/job or Apple binary
is installed by this review.

Reviewed again2026-10-24 after station-v7: QMI's native target table declares
CE5 PIPEDIR_OUT (target destination, HTT/IPA); live firmware changes its
destination base to MSA after HTT setup. Redfin's APPS/IPA-disabled profile
therefore leaves both CE5 rings to firmware, neither posts nor polls host RX
there, and uses one shared host-ring table in the software and hardware owner.
Native CE5/6 without APPS queues receive no CTRL1/RRI-enable writes either.
Station-v8b also observes firmware installing CE8's destination in MSA.
Native target comments identify CE8 as target-to-uMC and CE11 as autonomous
qcache; this profile requests no pktlog/diagnostic consumers. APPS now owns
only HTC/WMI/HTT queues0..4 and HTT receive9/10, leaving5/6/7/8/11 entirely
untouched. The readonly audit reports all mismatched owned fields together
before refusing, while retaining resources and issuing no additional DMA
doorbells. These native files are pinned at Linuxv6.12
`adc218676eef25575469234709c2d87185ca223a`.
The generic host_ce_config_wlan CE5 receive entry is not suitable authority
for this observed mission profile. The exact-source CE model now checks
that CE5's firmware registers are preserved, plus real RX and TX code paths.
Native `ce.c:shadow_sr_wr_ind_addr` independently confirms the existing
0/3/4 shadow addresses32000/3200c/32010; QMI array order is not their index.

The pinned SEC source's IO_RETRY_CNT3 and1ms retry wait now apply only to
discarded queue-resynchronization reads, after releasing held contacts.
Live coordinate batches are never replayed. The two-CS open HID-session read
keeps preemption disabled with CPU IRQs enabled and existing bounded GENI
loops. A measured gap accompanies invalid replies; scheduling latency is
still a candidate, not a proven Wi-Fi cause.
XNU8796 `clock.c:_clock_delay_until_deadline_with_leeway` confirms that
`delay()` can block; preemption-disabled callers select `machine_delay_until`.
This applies to sensing initialization as well as subsequent event reads.

GUI2 composes these resources with the existing GUI8 root/display/touch
profile. It uses the same bounded boot-argument length, frozen CPU/root
checks and cached shim return. Touch completes its DRV2 power setup first;
then a permanently bound CPU0 WLAN worker imports that stable handoff,
retains the established votes and services GLINK/RMTFS and packet rings
throughout the GUI run. Other CPUs submit queued station/frame requests.
The existing ordinary GUI1 and diagnostic profiles keep their own gates.
No GPU/Metal work is moved ahead of working GUI Wi-Fi.
