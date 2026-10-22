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

Eight host tests pass, including actual patched presentation/HID methods,
independent bilinear pixels, immutable guarded source memory, clipping,
malformed extents, margin gestures and ASan/UBSan. Physical alignment,
rounded corners and on-device scaling throughput remain unverified;
[DISPLAY.md](DISPLAY.md) records the exact contract and next bounded test.

[kernel]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[userland]: https://github.com/oosexgang/hackios-xnu-userland/tree/906425b75e02b4f99eb5d7bb1ef7c9583472d772
