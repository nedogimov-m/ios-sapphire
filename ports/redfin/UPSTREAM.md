# HackiOS upstream review — 2026-10-22

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

[kernel]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[userland]: https://github.com/oosexgang/hackios-xnu-userland/tree/906425b75e02b4f99eb5d7bb1ef7c9583472d772
