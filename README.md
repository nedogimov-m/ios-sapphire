# ios-redfin — Pixel 5 bring-up

Primary stable upstream sources, selected by the user:
[oosexgang/hackios-xnu-kernel](https://github.com/oosexgang/hackios-xnu-kernel) and
[oosexgang/hackios-xnu-userland](https://github.com/oosexgang/hackios-xnu-userland).

Current Redfin GUI composition and panel scaling/packing run on Adreno620.
`redfinfb=1` publishes the framebuffer interface used by that GPU display path.
Latest V99 (kernel Actions40422287650/run24/sourcee90b110) passes complete
independent native GMEM/sysmem and app Metal contracts, all four full private
output cases and four exact physical-panel references. Actual fused GPU output
exceeds1080frames. Its finite system-window animation completes611GPU frames
in10.011138physical seconds:61.032FPS, with58.005..62.012FPS second samples,
90Hz callbacks, zero contacts and one stable backboardd. This proves working
physical output and this workload's measured rate; sustained60/90FPS throughout
interactive use remains unfinished. The cold native output checks now have a
separate finite startup wait, preserving the ordinary frame deadline. Phone/
Photos automatic launches remain off. Current next work is physical buttons,
native display brightness/wake and the other remaining items in GOAL.md.
The preferred upstream GLES bridge now composes the GUI while native Metal
remains available to applications. V85 proves both paths in one boot, including
native Metal/IOSurface pixels and actual kernel publication without a GPU wait
in the window server. Exact-binary ordinary V86 measures548completed GPU frames
in10.011360physical seconds:54.738FPS at90Hz callbacks, one server and zero GL
errors/copy-back records. This is above ordinary V84's43.151FPS and Metal V81's
34.462FPS. The touch startup recovery kernel (Actions40394810408/run19) now
passes V87 with157real contacts/releases, zero driver errors and user-confirmed
working input. Its interactive system animation measures76.290FPS, varying
54.382..85.922FPS with a160.575ms maximum callback pause; this is not a matched
quiet comparison or stable60/90render FPS. GLES4800frames/shared surfaces/
copy0/errors0 and one window server are observed. Phone/Photos automatic
launches remain disabled.
After bounding immutable Metal constant uploads by their actual shader reads,
V57 measured52.699FPS in a finite ordinary system animation. Correct native
Metal scheduling now also passes all A620 pixel/error/callback/lifetime checks;
V59 measures523completed GPU frames in10.000094physical seconds:52.300FPS,
with startup diagnostics and captures OFF. That change preserves the ordinary
performance level rather than demonstrating another FPS increase.
The panel and native CoreAnimation clock now independently run at90Hz. V60's
unmodified period getters report1/90second and actual callbacks average89.201Hz;
its user-confirmed interactive workload renders31.665FPS. That observation is
not a matched quiet comparison to V59. Sustained60/90render FPS is unfinished.
The V61 output block removes redundant fullscreen GPU clears and passes both
full/margin native pixel and guard checks. Complete owner/output budgets now
validate; output costs5.699ms median. Its observed300GPU frames/10.011191s are
29.966FPS at90Hz callbacks, with51logged contacts. This is not a controlled quiet
comparison or a measured FPS gain; render execution and queue latency remain.
Owned odd-height IOSurfaces now provide the actual GMEM transfer footprint.
V63 passes the complete native Metal pixel, source/tail guard, alias and
CPU-rewrite restoration checks. V65 also passes bounded dynamic constant
uploads and explicitly supported buffer residency reuse on the real GPU.
Its checks-gated animation measures34.361FPS. V66 with the same binaries and
startup checks OFF completes356GPU frames in10.010942physical seconds:
35.561FPS, with90Hz callbacks, no contacts or window-server replacements,
and a clean shutdown. Smooth60/90render FPS remains unfinished.
V67's complete GPU-ordered large-constant snapshot and repeated raster
checks also pass on A620. Ordinary V68 measures30.967FPS, below V66, so that
unconditional copy policy is being corrected: CPU-owned constants keep the
uploader; large GPU-written sources may snapshot without a CPU dependency wait.
V69's corrected native A620 contract passes both CPU/GPU producer modes;
actual compositor groups preserve CPU uploads. Its checked animation measures
32.564FPS. Ordinary V70 completes329GPU frames/10.011390physical seconds:
32.863FPS at90Hz callbacks, one server, no fault and a clean shutdown. Whole
physical render/output queue costs remain; smooth60/90FPS is unfinished.
V71's physical-publication/FIFO-retirement kernel passes the full native Metal
and output contract. Its checked animation measures37.558FPS at90Hz callbacks;
V73 also proves actual two-pending publication and successful completion of
three bounded compute pairs, with every value/guard and the full native
contract passing in the same boot. Its checked animation measures37.458FPS;
V75's coherent diagnostics-OFF run measures391completed GPU frames in
10.011177physical seconds:39.056FPS at90Hz callbacks. Full CPU-cache
maintenance of imported display surfaces remains a measured cost. The next
complete block gives fresh owned BGRA images consistent WC CPU mappings;
V76 passes the full native contract and exercises WC CPU/GPU access, but
system output remains on the cached route. Corrected selection separates
cache attributes from GMEM padding and honors explicit WC requests. Its
three-mode native contract passes in V77. Actual system buffers request
Apple realtime cache0x700; that request is now adapted to Redfin's proven
WC mappings. V78 passes all four native CPU/GPU cache-mode contracts and
actual system output selects WC600/cached0. Source synchronization falls to
1us median; its checked animation is34.262FPS, so a whole-frame speedup is
not established. Ordinary V79 with the same binaries and startup checks OFF
measures335GPU frames/10.011182s:33.463FPS at90Hz callbacks, below V75's39.056FPS.
V80 passes the complete native contract with explicit critical GPU deadlines
and separate hardware/host/cache partitions. Actual100us polls have sampled
per-wait maximum pauses of120us median/192us maximum. Sampled9-IB+WFI GPU
groups cost17.13ms median, excluding the final cache-flush fence. Its checked
animation is32.564FPS. Exact-binary ordinary V81 measures345GPU frames in
10.011147physical seconds:34.462FPS,90Hz callbacks, zero contacts and one server.
Actual18-IB+WFI groups cost14.908ms median; output1-IB groups3.3165ms. These
sampled spans exclude the final fence and are not an additive full-frame budget.
Smooth60/90render FPS remains unfinished; precise timer correctness is proved,
but a material whole-frame gain is not.
Phone and Photos work according to the
user, and their automatic launch checks are retired. Current evidence and next
work are recorded at the top of [NOTES.md](NOTES.md). V88 also passes the full
direct-to-IOSurface GLES, framebuffer-fetch/pixel/tail and app Metal contract,
but unbounded frame admission initially regresses to5..7FPS. V90 corrects
that queue pressure with a two-frame real-fence limit, passing the full native
direct/budget/app Metal contract and measuring50.942FPS at90Hz callbacks.
That restores throughput; an improvement over the54.738FPS mirror baseline
and sustained60/90render FPS are not established.

Pixel 5 boots XNU 8796 and Apple's iOS 16.7.16 launchd, backboardd and
SpringBoard from a journaled HFSX root in the approved first 16 GiB of
userdata. CPU0, IRQ/SGI, BSD, static Darwin PID1 heartbeats, bounded
UFS read/write, Apple mount phases and FIPS checks are observed. Launchd
passes keybag initialization and cache loading, starts system daemons, and
backboardd makes IOKit calls. The opt-in CPU framebuffer publishes AppleCLCD;
backboardd opens it, allocates an iPhone X canvas and submits swaps. The earlier
SpringBoard `main CADisplay` trap is absent in that test. Authenticated RAM
captures show the Apple logo and lock screen rendered into the framebuffer.
All eight redfin CPUs pass XNU scheduling, timers and cross-IPIs and run Apple's
userspace with touch. The user reports a large speed improvement over one core.
The user confirms physical iOS display and touch-driven UI response. A fresh
eight-core capture records 72 physical SEC contacts and 72 releases;
multitouch remains unverified. CPU copies are capped at 10 Hz in that run;
the user reports smoother UI at a 60 Hz copy limit. A repeat with queue
recovery runs114 contacts/releases without a stop; the hardware clear itself
is covered by host tests. Full-canvas scaling below Redfin's front camera
passes an autonomous eight-core run and authenticated lock-screen captures.
Timed
process shutdown leaves HFS clean; the
recovery collector records its volume-header state automatically.
The minimal MobileGestalt Wi-Fi identity fix is validated on the device.
Authenticated peripheral observers now cover SEC SPI/GPIO, warm DWC3,
SMEM and Adreno 620 clocks. Guarded DWC3 DMA, high-speed USB enumeration,
ARP, nonce-bearing ICMP and fresh UDP kernel logs are observed through
macOS's native CDC-ECM driver with the opt-in AArch64 context profile.
USB is validated in bounded md0 tests; integration with UFS/GUI remains
unverified. Native MPSS/PAS4, GLINK/QRTR/RMTFS and WLAN firmware readiness
are now observed in a bounded md0 run: a separate DMON client transfers
the captured Redfin BDF, gets all acknowledgements and completes CAL_REPORT;
the kernel receives a real FW_READY indication. The latest combined GUI8
run also validates the owned WLAN context, bidirectional CE/HTC/WMI/HTT
control traffic, en0/Apple80211 publication and three passive scans with
25 observed access points. Radio ownership/DMA checks stay healthy for
about125 seconds until the planned GUI shutdown. The latest SEC event
session finishes without errors after correcting blocking SPI waits. The
latest manual session records 115 contacts/releases, and the user confirms
working GUI touch. Settings' Wi-Fi switch remained gray: wifid never
executed while its stock launchd job required absent Apple DeviceTree
nodes. The upstream job-gate fix is applied to Redfin's existing root and
fresh-root builder. The next authenticated capture confirms wifid starts,
finds en0 and reads radio capabilities, power and supported channels.
Manual Settings freezes are traced to wifid waiting in SystemConfiguration
for InterfaceNamer's IOKit readiness. Adapting the preferred upstream's
minimal IONetworkStack releases that wait. The user now confirms Wi-Fi
connection from Settings and working internet; About also opens after a
delay. The authenticated capture proves successful WPA2 authentication,
association and four-way exchange, link-up and 14,026 received/10,712 sent
Ethernet frames. Touch completes 103 contacts/releases without errors.
An isolated DHCP transcript and reconnect/suspend behavior remain untested.
The known working image is `ports/redfin/out/wifi-gui8-network-stack-v1/redfin-xnu.img`.
GPU/Metal acceleration is the next priority. The isolated A620 memory-v6
capture now proves owned wired RAM, native CB1/stream5 readback and all
seven GMU firmware payloads loaded and verified, with CM3 still reset-held.
The subsequent capture observes fresh GMU firmware completion and HFI-ready;
a fresh version request now receives its matching HFI ACK with actual queue
consumer progress, proving GMU DMA. The complete native GPU command chain
now passes an authenticated hardware run: native CB0/SID0 routing, SQE,
ME_INIT, signed PAS13 zap, exit from secure mode and four boot-bound values
actually written by the GPU and read back uncached. GPU/SMMU faults remain
clear. The complete GUI3 integration now proves actual Mesa/FD620 ES3.2
shader draws, both IOSurface pixel checks and backboardd's EAGL composition
into shared display surfaces. The latest complete run proves over4096
backboardd submissions and900system frames without a window-server crash,
plus87touch contacts/releases without errors. The user observes restored
shadows and fewer artifacts. Simple warm frame samples reach14–26ms;
complex samples still cost40–100ms or more. The next run proves over5120 submissions and1200frames without a window-server
restart. The user confirms Phone works. Seeding the native MobileCheckpoint
cache removes Photos' synchronous service wait; its next blocker is a photo-
library assertion. Stable60fps, Metal and working Photos remain unfinished.
Adreno draws and composes the system UI, then scales and packs its frames
into the panel buffer using the native A620 2D engine. An authenticated run
proves over2400 completed GPU presentations, private full-frame/guard checks
and matching physical-panel samples, with the CPU path retained for
unsupported swaps. The user reports a modest improvement, estimating
30–40fps; stable60fps remains unfinished. Phone works and Photos still aborts.
The latest stable GPU image is
`ports/redfin/out/gpu-panel-v1/redfin-xnu.img`.
[Upstream assessment](ports/redfin/UPSTREAM.md).

The latest authenticated platform capture also proves real Metal on A620:
192compute commands across two queues and4096IOSurface pixels pass. The next
capture also selects system Metal, builds actual CoreAnimation pipelines,
completes backboardd GPU submissions and preserves a visible physical home
screen. Sustained UI FPS remains unmeasured. All
three CPU domains now reach their native normal frequencies with observed
thermal throttling/restoration; Photos still fails in its native assetsd/TCC
path. Physical90Hz and credential persistence are independently observed.

The user confirms Phone and Photos now work normally; their automatic launch
checks are retired. V32 repairs half-precision vertex-to-fragment transport and
passes actual A620 half storage, MRT, fetch, vertex/varying/sampler pixel and
guard probes. The user now confirms normal system colours and no checkerboard,
but reports severe lag. The earlier window-server memory-limit restarts are
also removed. Heavy diagnostic readbacks materially perturb this run; ordinary
composition performance is the next priority. Stable60/90render FPS remains
unproved.

A complete shader-preparation block now adds bounded per-device translation
templates, reference-counted Gallium stage reuse and one shared immutable quad
buffer. AIR folds defined state during scratch promotion rather than repeatedly
walking dead branches. Host real-NIR ownership/eviction checks and all19captured
parameter variants pass. V35 also passes all70actual A620 cache variants and
retained-pipeline pixels/guards after eviction. Actual backboardd reuses66stage
states by pipeline64; one repeated pipeline takes329us versus12738us initially.
First-time complex shaders and whole-command latency remain substantial; this
does not establish smooth system FPS.
The subsequent ordinary V36 capture proves both graphics probes and heavy
capture inactive, working template/stage hits, one live backboardd and no panic.
Repeated pipeline preparation is323us; cold complex pipelines still cost
378..955ms and the sampled38-draw command costs205ms. Remaining CPU preparation
and waits are the next performance blocker.

Persistent AIR/Adreno code now also passes actual fresh-context pixels and a
complete ordinary reboot. At pipeline32, V38 reads36AIR templates and39GPU
programs from disk with no compilation; sampled cached complex pipelines take
about5..6ms. New variants still take hundreds of milliseconds and command/queue
waits remain, so smooth system60/90FPS is still unfinished.

GPU transfers and converted buffer views now also pass mixed native ordering:
27GPU operations across three changing compute/render/copy alias chains share
one final CPU wait, with correct pixels/guards. GPU-written indices and unaligned
uniforms retain their required CPU synchronization and bounds checks. All prior
native graphics contracts still pass; ordinary UI FPS remains unmeasured.

Command-local resource and graphics binding reuse also passes real A620 pixels,
changed CPU data, sparse high-to-low slots and error cleanup after encoded work.
An eight-draw command skips14descriptor/70graphics/7vertex updates and releases
all cached references at scope exit. System UI rendering FPS remains unfinished.

Retained kernel GPU submission and separate Metal completion now pass the full
native A620 contract: two commands before waiting, shared writes and snapshots,
reentrant callbacks, partial errors, CPU dependencies, per-write epochs and
deferred device lifetime. V44 preserves one backboardd and a clean shutdown;
all earlier pixels/guards and192compute commands pass. Ordinary warm UI latency
remains substantial. Native shared-surface batch merging now also passes all
A620 correctness checks and actual multi-IB retirement. Its ordinary animation
with persisted caches measures200actual GPU presentations in10.000127physical
seconds (20FPS), versus17.3FPS before merging, with one backboardd and no panic.
The independently verified panel runs at90Hz; CADisplayLink callbacks remain
60Hz. Smooth system60/90render FPS remains unfinished.

Kernel logs are collected automatically through temporary Linux recovery and
authenticated host decryption. The original Android userdata and metadata
have complete, independently verified local backups. Android userdata has
been replaced; restore the backup before booting Android. Boot partitions,
GPT, modem, persist and EFS are preserved. Device images, backups and logs
remain local and ignored by git.

Before erasing Android userdata, save its credential-encrypted ramoops keypair
on the host. Recovery receives only the public key, primes the next boot's
RAM metadata, and returns to bootloader. The [recovery workflow](ports/redfin/README.md#offline-recovery)
uses `--ramoops-key-dir`, `--recovery-image`, `--from-bootloader` and
`--leave-bootloader`; the private key stays off the device.

Build and temporary boot instructions: [ports/redfin/README.md](ports/redfin/README.md).
The original Sapphire documentation follows as reference.

# ios-sapphire

**Apple's iOS 16 running on a Redmi Note 13 4G.**

A port of [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) (itself a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)) to the Xiaomi **Redmi Note 13 4G** (`sapphire` / `sapphiren`, Qualcomm **SM6225 "khaje"** / Snapdragon 685). Apple's open-source XNU kernel (xnu-8796) boots from RAM through a small boot shim, and on top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd and SpringBoard.

The Redmi Note 12 4G (topaz) and the Redmi Note 13 4G share the SoC, the memory carve-outs and most of the board, so this fork follows the topaz branch and adds what differs on sapphire (patches 0140–0144, the shim's DDR handling and the tools below).

> Experimental bring-up, not a usable phone OS. Many things are missing or stubbed, and Apple's security model is mostly switched off. It installs into the `userdata` partition and so **erases Android's user data**. The kernel is started from RAM with `fastboot boot`; boot partitions do not need to be flashed.

## What works on sapphire

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi ABL (unlocked) → `fastboot boot` of the shim (boot image v4) → XNU on the four Gold cores. The shim fits the RAM to the DDR bank ABL reports |
| Storage | UFS host driver; the iOS root is a journaled HFS+ volume in `userdata`, read/write. Shutdown from Settings unmounts it cleanly |
| GUI | Apple logo, lock screen, home screen, Settings, notification and control centers; rendered by the CPU (no GPU) |
| Touch | FocalTech FT3519T (chip id `54:52`) on QUP0 SE2, calibrated for sapphire by boot args (patch 0140) |
| USB | DWC3 in device mode as a CDC-ECM network card (patch 0142): `192.168.7.2` on the phone, live kernel log over UDP |
| Modem | Firmware read from the stock `modem_a`, authenticated by TrustZone, modem up with its QMI services (patch 0143) |
| Wi-Fi | WCN3988 firmware in mission mode and passive scan (2.4 and 5 GHz networks listed in the kernel log). No association yet |

## What does not work (yet)

- **Wi-Fi connection**: no association/WPA2, no data path, no network interface for iOS yet; the Wi-Fi switch in Settings does nothing.
- **No GPU yet**: everything is drawn by the CPU, so it lags; wallpapers and Metal effects stay black. Patch 0145 starts the Adreno 610 bring-up (see below); the upstream project has the GPU drawing on topaz with patches it has not published.
- **SSH**: a Procursus rootless bootstrap with sshd can be installed (`tools/sapphire-ssh-install.sh`), but iOS does not resolve `root` for it yet ("Invalid user root").
- **No Bluetooth, cellular data, audio, camera, sensors, GPS, SEP**; no real-time clock (the date starts at 31 December).
- **Only 4 of 8 cores** (the Silver cores have no 16K translation granule).
- **Security is off**: permissive AMFI and sandbox, stub AppleKeyStore, no data protection.

## How it boots

```
ABL (stock Xiaomi bootloader, unlocked)
  -> fastboot boot sapphire-boot.img     (boot image v4, RAM only)
     -> shim on Silver CPU0: wakes Gold CPU 0x100, parks
        -> shim on Gold: GIC setup, DDR bank from ABL's DTB, payload behind _end
           -> XNU Mach-O + Apple Device Tree (ADT) + boot-args
              -> XNU -> UFS driver -> HFS+ root in userdata
                 -> dyld + shared cache -> launchd -> backboardd + SpringBoard
```

There is no serial console. The kernel keeps a persistent log ring at the end of `userdata` (read it from recovery with `tools/sweet-log-pull.sh`) and, with `sweetusb=2`, streams its console over USB. With `--console`, `tools/sapphire-boot.sh` also draws it over the GUI.

## How to do it yourself

You need a Redmi Note 13 4G (`sapphire`/`sapphiren`) with an **unlocked bootloader**, a recovery with a root adb shell (OrangeFox), a Linux machine (or WSL2) and a way to build the kernel on macOS. **Everything on `userdata` is lost.**

### 1. Build the kernel

XNU only builds with Apple's toolchain. Two ways:

- **Codemagic** (`codemagic.yaml`, free personal tier: 500 macOS minutes a month, a build takes a few minutes): add this repository as an application, start the `xnu` workflow on `sapphire`, download `xnu-kernel.zip`. It uses Xcode 16; patch 0141 makes the kernel build with it.
- **GitHub Actions** (`.github/workflows/xnu.yml`, macos-14 / Xcode 15):

  ```sh
  gh workflow run xnu.yml -R YOU/ios-sapphire --ref sapphire
  gh run download RUN_ID -R YOU/ios-sapphire -n xnu-kernel -D xnu/out
  ```

### 2. Build the iOS root image

Download the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW from Apple and extract the D22AP Erase identity's OS, Cryptex1 SystemOS and AppOS disk images (with `apfs-fuse`/`ipsw`). Then, on Linux or WSL2 as root (WSL2 needs an `hfsplus.ko` built for its kernel):

```sh
sudo tools/sapphire-root.sh OS.dmg SystemOS.dmg AppOS.dmg OUTDIR [hfsplus.ko]
# -> OUTDIR/ios16-root.img (16 GB) and ios16-root.simg
```

The device tree builder copies `/product` from the real iPhone X device tree: take `Firmware/all_flash/DeviceTree.d22ap.im4p` from the IPSW, decompress it (`ipsw img4 im4p extract`) and save it as `research/ipsw-x/d22ap.adt`.

### 3. Build the boot image

Needs `aarch64-linux-gnu-gcc` and AOSP `mkbootimg.py` (`MKBOOTIMG=...`).

```sh
tools/sapphire-boot.sh xnu/out/kernel.development.sweet sapphire-boot.img            # GUI
tools/sapphire-boot.sh xnu/out/kernel.development.sweet sapphire-usb.img "sweetusb=2" # + USB network
tools/sapphire-boot.sh xnu/out/kernel.development.sweet sapphire-wifi.img "sweetusb=2 modem=1 wifi=1"
```

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsrw=1 rootrw=1` | Root on `userdata`, writable (`--readonly` drops the last two) |
| `cpus=4` | The four Gold cores |
| `sweetfb_noconsole=1` | No kernel text over the GUI (default; `--console` keeps it) |
| `sweetfb_hz=60` | Panel refresh rate of the CPU frame copy |
| `sweettouch_rx=8640 sweettouch_ry=9600` | sapphire's raw touch range (X 0..2159, Y 0..2399, 2 fraction bits) |
| `sweetusb=1` / `sweetusb=2` | USB: report the controller state / start the CDC-ECM device |
| `modem=1 wifi=1` | Boot the modem from `modem_a` and bring up the WLAN firmware (read-only on the phone's partitions) |
| `gpu=1` / `2` / `3` | Adreno 610: log the clock tree / also power it up and read it / also run a command on it (see "GPU bring-up") |
| `launchd_unsecure_cache=1`, `wdt=-1 wdt_test=no_user_checkin` | launchd without AMFI; no hardware watchdog |

### 4. Put the root on the phone and boot

`fastboot flash userdata` of a sparse image wrote the upper part of `userdata` incorrectly on sapphire's ABL, so copy the raw image from recovery instead (root shell, `userdata` = `/dev/block/by-name/userdata`):

```sh
adb shell 'dd of=/dev/block/by-name/userdata bs=1M' < ios16-root.img    # Linux adb; verify with md5sum
adb reboot bootloader
fastboot boot sapphire-boot.img
```

Use the Linux `adb` for this: piping binary data into Windows' `adb.exe shell` corrupts it. From Windows, `adb push` the image in pieces and `dd` them on the phone. Check the result by comparing md5 sums of 1 MB blocks on both sides.

Always use `fastboot boot`, not `fastboot flash boot`: on sapphire the recovery runs with the kernel in `boot`, so an iOS image in `boot` takes the recovery away (see `RECOVERY.md`). The first boot spends a while on the Apple logo; the lock screen follows after a few minutes. To leave iOS cleanly use Settings → General → Shut Down (the HFS+ journal stays clean), then Power + Volume down.

### USB network and live log

With `sweetusb=2` the phone appears as "Sweet iOS (USB Ethernet)". Windows has no CDC-ECM driver; pass it to WSL2 with [usbipd-win](https://github.com/dorssel/usbipd-win) (`usbipd bind --busid X` once, `usbipd attach --wsl --busid X` per boot), then in Linux:

```sh
sudo ip addr add 192.168.7.1/24 dev enx02005e77ee01 && sudo ip link set enx02005e77ee01 up
ping 192.168.7.2
nc -ukl 5140          # live kernel console
```

### Changing files on the phone without a full copy

`tools/hfs-push-ranges.py` and `tools/sapphire-ssh-install.sh` edit the root without rewriting 16 GB: copy the phone's HFS+ metadata ranges (volume headers, journal header, catalog, extents, attributes, bitmap) into the image on the PC, change files there (new files only, replace through new file + rename), and write back only the newly allocated blocks plus the metadata, with `adb push` + `dd` on the phone. The journal must be clean first (shut down from Settings). `tools/bplist-same-size.py` drops launchd jobs from `launchd.plist` in place.

## sapphire patches and tools

| # / file | What |
| --- | --- |
| 0140 | Focaltech raw format and range from boot args, first raw contacts logged, out-of-range positions clamped instead of dropped |
| 0141 | `IORPC.kernelContent` backport so the kernel builds with Xcode 16's `iig` |
| 0142 | sweet's DWC3/CDC-ECM USB device on the SM6225 addresses; opt-in with `sweetusb` |
| 0143 | sapphire's modem_a tables (modem image for PAS, all files for the tftp server and WLAN board data), picked by the `modem.mdt` CRC so topaz keeps working |
| 0144 | Join the network named by boot args `wifi_ssid=` / `wifi_pass=` through upstream's WLAN station (0129/0130), for testing |
| 0145 | Adreno 610 bring-up staged by boot-arg `gpu=N`: clock tree, power-up, zap shader through TrustZone, identity SMMU bank, SQE microcode and a command the GPU executes (**not yet run on the phone**) |
| `shim/` | DDR bank end from ABL's `/memory` node; RAM size clamped to it |
| `tools/mkadt.py` | sapphire identity in the ADT |
| `tools/sapphire-boot.sh`, `sapphire-root.sh` | Boot image and root image for sapphire |
| `tools/fwtable-modem.py` | Generates the modem_a tables from a dump of the partition |
| `tools/fwtable-file.py` | Where a file lies inside a partition, for a driver that reads it directly (the GPU firmware table) |
| `tools/sapphire-touch-kpatch.sh`, `kpatch.py` | Binary fix of the touch scaling in a built kernel (used before a build was possible) |

## GPU bring-up (patch 0145, in progress)

The Adreno 610 v2 in this phone (`chip id 0x06010001`, registers at `0x5900000`) has no GMU, so
the host powers it up itself, as Linux does through its "GMU wrapper". Patch 0145 follows what
[topaz-woa](https://github.com/MakrSas/topaz-woa) `docs/P8_gpu.md` established on the same SoC
under Windows, on this kernel and with the pieces `TopazModem` already brings: TrustZone calls,
an identity SMMU bank and RAM below 4 GB that the kernel does not manage.

Reading a GPU register while its power domain or its clocks are off hangs the bus, so the work is
staged by `gpu=N` and each stage is meant to be read in the kernel log before going further:

| Stage | What it does | What to look for |
| --- | --- | --- |
| `gpu=1` | Maps GCC and the GPU CC and logs the clock tree. Never touches `0x5900000` | the bootloader leaves everything collapsed and off |
| `gpu=2` | Powers up (GPLL0 vote, CX GDSC, cxo/ahb, GMU RCG, SMMU vote, GX GDSC, core clock at 300 MHz), then reads the GPU | `RBBM_STATUS`, and `CP_ALWAYS_ON_COUNTER` growing by ~192000 in 10 ms (19.2 MHz) |
| `gpu=3` | Zap shader through TrustZone (PAS 13, region `0x55A15000` from the device tree), identity SMMU bank for the GPU's stream (SID 0 mask 1, as `gfx3d_user` in the device tree), SQE microcode, 32 KB ring, `CP_ME_INIT`, `CP_SET_SECURE_MODE 0`, `CP_MEM_WRITE` | `*** the GPU executes commands ***`, with `c0ffee00` read back from RAM |
| `gpu=4` | The same without the zap shader: leaves secure mode by writing `RBBM_SECVID_TRUST_CNTL`, as Linux does for a device that has no zap firmware. A first test with only the open microcode, and a gamble Linux warns about: if the bootloader left the GPU secure, that write is refused | the same, or a permissions violation |

Both `gpu=3` and `gpu=4` need the microcode `a630_sqe.fw` (it is in
[linux-firmware](https://gitlab.com/kernel-firmware/linux-firmware) as `qcom/a630_sqe.fw`, and the
phone has its own copy); `gpu=3` also needs this phone's signed `a610_zap` shader, which exists
only on the device. Neither is in this repository. The simplest way to give them to the driver is
to put them in the boot image's device tree:

```sh
tools/sapphire-boot.sh --gpu-fw ~/gpu-fw xnu/out/kernel.development.sweet sapphire-gpu.img "gpu=4"
```

where `~/gpu-fw` holds `a630_sqe.fw` (and `a610_zap.mdt` / `a610_zap.b02` for `gpu=3`). Otherwise
the driver reads them from a stock partition: fill `gpu_fw[]` in `SapphireGpu.cpp` with
`tools/fwtable-file.py`, pointing it at the files in a mounted copy of that partition.

After that come the interrupt, a real draw from a freedreno command stream, and a user space
driver (Mesa freedreno) behind CoreAnimation.

## Repository layout

| Path | What |
| --- | --- |
| `shim/` | Bare-metal boot shim (C + asm), boot image v4, Gold hand-off, GIC setup, payload loader |
| `xnu/patches/` | XNU patch series, applied in order: sweet's 0001–0079, topaz's 0080–0139, sapphire's 0140+ |
| `codemagic.yaml`, `.github/workflows/xnu.yml` | Kernel builds |
| `tools/` | ADT, payload, root image, boot image, log, modem and HFS+ tools |
| `NOTES.md` | Engineering log (sweet, topaz, sapphire) |
| `RECOVERY.md` | Getting back to recovery / Android on sapphire |

Not in git: partition dumps, live device trees, Apple firmware and root images, boot logs, build trees.

## Key hardware facts (sapphire)

- SoC SM6225 "khaje": 4× Kryo 260 Silver (A53 class, MPIDR `0x0`–`0x3`) + 4× Kryo 260 Gold (A73 class, `0x100`–`0x103`). Only Gold has the 16K granule.
- DDR banks of the tested phone (from ABL's DTB): `0x40000000`+`0x3cc00000`, `0x80000000`+1 GiB, `0xc0000000`+4 GiB. XNU gets 2 GiB at `0x1_40000000`.
- GICv3 at `0xf200000` (redistributors `0xf300000`), UFS at `0x4804000`, splash framebuffer at `0x5c000000` (1080×2400, DSI video mode with DSC).
- Touch: FocalTech FT3519T at `0x38` on QUP0 SE2 (IRQ GPIO80, reset GPIO86), raw range 2160×2400.
- USB: DWC3 at `0x4e00000` (QSCRATCH `+0xf8800`), Synopsys femto HS PHY at `0x1613000`, USB30_PRIM GDSC at GCC `0x1400000` + `0x1a004`.
- Modem carve-out `0x4ab00000`+`0x6900000`, WLAN MSA `0x51900000`+`0x100000`, SMEM `0x46000000`; WCN3988 (`chip_id 150`) behind the modem.

## Credits

Based on [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) and [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet), which did the hard part: XNU on a Qualcomm phone with the iPhone X userland, the topaz port of the same SoC, its modem and Wi-Fi work. Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs), [BearSSL](https://bearssl.org), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), [Procursus](https://github.com/ProcursusTeam/Procursus), Qualcomm/Xiaomi's published Linux kernel sources, and the hardware work in [MakrSas/topaz-woa](https://github.com/MakrSas/topaz-woa). sapphire port by [Angelpro09xd](https://github.com/Angelpro09xd). iOS itself is Apple's and is not distributed here.
