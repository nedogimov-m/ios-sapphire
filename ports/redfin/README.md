# Pixel 5 / redfin

Source base: ios-sapphire `d7858e985c4fd2fd41c2c4300c5279cbc8eee178`,
ios-topaz `89451b811a4e6cc5cdcf734c45887163d92c599e`, XNU
`xnu-8796.141.3`. Hardware sources and live observations: [HARDWARE.md](HARDWARE.md).

Pixel 5 executes XNU 8796 and Apple's iOS 16.7.16 launchd, backboardd and
SpringBoard from a journaled HFSX root installed in the approved first 16 GiB
of userdata. Bounded UFS read/write and timed clean shutdown are observed;
static Darwin PID1 console I/O, getpid=1 and heartbeats are also verified.
The opt-in AppleCLCD CPU-copy backend produces CRC-checked framebuffer
captures of the Apple logo and lock screen. The MobileGestalt Wi-Fi identity
fix is validated on the device. The user confirms visible iOS and UI response
to physical taps/swipes; a fresh log records 41 SEC contacts and HID dispatch.
Bounded md0 USB tests pass ARP, ICMP and fresh UDP logging through native
macOS CDC-ECM. USB with UFS/GUI, multitouch, the home screen, Wi-Fi and GPU
acceleration remain unverified. The overlay disables inherited Xiaomi
hardware drivers and supports one CPU; rendering remains slow.

`--touch-probe --usb-probe --wifi-probe --gpu-probe` adds read-only peripheral
observers. Common startup requires confirmed PMIC/IMEM bootloader return
before dispatch; ordinary boot keeps them disabled. V3 hardware logs verified
the GPIO/SPI state, warm DWC3 controller, reserved SMEM and collapsed GPU
clock state, then iOS rendered its lock screen and cleanly unmounted HFS.
These options do not enable functional touch, Wi-Fi, USB networking or GPU
acceleration. Hardware contracts and next steps: [CPU](CPU.md), [touch](TOUCH.md),
[USB](USB.md), [Wi-Fi](WiFi.md), [GPU](GPU.md), [new upstream](UPSTREAM.md).

## Reproduce

Capture from rooted Android; dumps remain ignored:

```sh
adb root
python3 ports/redfin/collect-device.py --out research/redfin-root
```

Save the active-slot `boot`, `vendor_boot` and `dtbo` before any boot experiment.
This workspace has verified copies in `backup/redfin/` from slot `_b`; determine
the active slot again on another device/session. The builder uses saved boot
metadata and never writes to a device.

Build XNU with the selected Xcode, privately extracted KDK, pinned dependencies
and the redfin overlays:

```sh
python3 ports/redfin/build-xnu.py
```

Successful local build on Xcode 27.1:
`research/redfin-build/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet`.
Initial kernel SHA256:
`3d33adecd4dda69ad1c8a1a6ed72759bd2cce94c672b5f29c25e8239289cef71`.
Subsequent diagnostic kernels include RAM logging and tracing; their hashes are
recorded in `research/redfin-build/result.json`.
For source preparation alone, use `prepare-xnu.py --output research/new-xnu`.

The opt-in `--display --splash` build enables AppleCLCD with a CPU-copy
backend for the observed Redfin ABL buffer: 1080×2340, 4320-byte pitch, BGRA,
inside the live continuous-splash reservation. It requires `--apple-adt` and
does not initialize the inherited Xiaomi display, modem or GPU controllers.
The iOS canvas is 1125×2436; copies default to 5 Hz. `--display-hz 1..10`
overrides the software copy cadence and requires `--display`. Copy cost and
rendering add latency, so this does not guarantee the requested animation FPS.
`--touch-events` enables the validated SEC/HID path for UFS/CPU-display tests.

`--capture-screen` also requires `--display` and enables up to three 120×260 RGB
thumbnails in the authenticated RAM log, only after a positive CPU copy. It
does not write image files on the phone. Decode the captured log on the host:

```sh
python3 ports/redfin/decode-screen.py logs/redfin/RUN/xnu-console.txt \
  --out logs/redfin/RUN/screens
```

The decoder verifies sequence numbers, fixed dimensions, Base64 and CRC32
before writing PNG files. Missing or truncated records fail validation.

For writable-root tests, add `--shutdown-seconds 120` together with
`--ufs-root --return-bootloader`. A kernel thread requests ordinary process
shutdown, sync and unmount after that interval. Watchdog feeding is bounded
and requires confirmed PMIC/IMEM bootloader-return state. Check the persisted
HFS volume header in recovery after each test; an abrupt reset may still leave
a dirty journal. Repair and verify an offline snapshot before another RW boot;
never just change the clean-unmount bit. The original watchdog-only behavior
remains when the option is absent. PID1 pathname/syscall diagnostics now require
`--trace-syscalls`; ordinary console and authenticated RAM logs remain enabled.

Build the diagnostic stage:

```sh
brew install aarch64-elf-gcc lz4
python3 ports/redfin/build.py --stock-boot backup/redfin/boot_b.img --splash
```

`--splash` draws at the live FDT splash reservation with 1080×2340 pixels and
4320-byte pitch. This was observed working on this Pixel. Diagnostic mode resets
through PSCI after 30 seconds. Without `--splash`, the stage is silent.

Build XNU plus PID1 with the validated RAM window from this device:

```sh
python3 ports/redfin/build.py \
  --stock-boot backup/redfin/boot_b.img --splash \
  --kernel research/redfin-build/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet \
  --dtb research/redfin-root/device.dtb \
  --memory-base 0x180000000 --memory-size 0x80000000 \
  --out ports/redfin/out/xnu
```

The builder checks the window against every fixed reservation and the loader
checks it again against the DTB supplied by ABL. This is a device-specific choice,
not a memory default for other phones. Payload, ADT, Linux Image and boot arguments
are validated before any destination writes.

The shim starts the hardware watchdog before entering XNU (default: 28-second
bark, 31-second reset). Console progress can pet it for up to 60 seconds; allow
at least 120 seconds for return (collector default: 300). Logs arrive after reset.
The [offline recovery workflow](#offline-recovery)
captures encrypted ramoops and decrypts it on the host, without Android.
The Android pstore path remains available before userdata replacement; opening
`/dev/access-ramoops` during Android's decrypt service can block its bank switch.
Add `--trace` to `build.py` for verbose DEVELOPMENT kprintf diagnostics. Default
boot arguments disable the unported SM6225 battery and cpufreq code as well;
the kernel overlay also disables that autostart driver.

Temporary boot only:

```sh
adb reboot bootloader
fastboot boot ports/redfin/out/redfin-diag.img
# Or the XNU payload:
fastboot boot ports/redfin/out/xnu/redfin-xnu.img
```

Pixel ABL requires the Linux Image `text_offset` to be `0x80000`: a controlled
test with `0` failed and the corrected image booted. Packaging matches the stock
LZ4 frame plus a trailing LE32 uncompressed size. No AVB footer is necessary for
this unlocked device. The bootloader's “missing cmdline or OS version” message
also appears with the working stock image and is not a reliable failure cause.

## Validation

```sh
python3 -m unittest discover -s ports/redfin -p 'test_*.py' -q
```

Host tests cover malformed FDTs, memory reservations, ADB failures, ADT generation
and payload relocation bounds. They cannot prove hardware execution. PID1 success
is confirmed by console output, getpid=1 and repeated heartbeats. The collector
recognizes banners split by syscall tracing. Full iOS launchd/SpringBoard have
not been demonstrated on redfin.

## UFS diagnostics

Add `--ufs-probe` to `build.py` for standard UFSHCI register reads, or
`--ufs-read-probe` for a private DMA queue and bounded read commands. These
continue to boot `rd=md0`; the inherited UFS filesystem driver stays disabled.
Mode 2 permits TUR, standard INQUIRY, READ CAPACITY and one GPT-header read
at LUN0/LBA1. That read requires a successful 4096-byte-block capacity result.
The separate Query path only reads current power mode and the device-init flag.
No disk writes, vendor commands, clock/PHY resets or SMMU changes are allowed.
`--ufs-wake-probe` selects mode 3: REQUEST SENSE on Device WLUN `0xd0`, then
the exact Linux active-power START STOP UNIT command, followed by the same read
checks. This changes device power state and still prohibits all media writes.
Mode 3 has read LUN0 successfully on this Pixel: 31211520 blocks of 4096 bytes
and 19 GPT entries. `--ufs-root-probe` additionally validates GPT CRCs, capacity,
partition bounds and overlaps, exposes `userdata` read-only, and runs a PID1 raw
read. A 4096-byte read and `EROFS` for write-open are confirmed. The character
device uses `uiomove`: raw `physio` buffers are user addresses, so copying them
with plain `memcpy` faults with PAN enabled.

Compare captured primary GPT metadata with:

```sh
python3 ports/redfin/gpt.py backup/redfin/sda-gpt-before.bin backup/redfin/sda-gpt-after-read.bin
```

This checks both CRCs and hashes the exact header and entry array, excluding
bootloader padding. Device captures remain ignored by git.

## Prepare Apple userspace locally

The pinned official iPhone X IPSW is iOS 16.7.16 (20H392), SHA256
`ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb`.

```sh
python3 ports/redfin/fetch-userspace.py
python3 ports/redfin/prepare-userspace.py --mount-readonly
```

Preparation verifies the D22AP erase identity, extracts OS/SystemOS/AppOS and
the Apple device tree, and mounts the images read-only on macOS. Its manifest
records detach commands. Repeated preparation reuses the same image attachments.

`build-root.py` builds a local HFSX image with cryptex links. Original owners
and modes are collected before copying and restored offline by catalog ID via
the pinned HFS library. `sweet-root-tweaks.py` supports deferred ownership for
this staging flow. A filesystem check is required before the image is accepted.
Preparing an image does not install it on the phone or demonstrate Apple launchd.
For Apple userspace boot images, add
`--apple-adt research/ipsw-redfin/extracted/d22ap.adt`. This imports public D22AP
product properties and the upstream development boot policy, with a synthetic
device identity; CPU, RAM and peripherals continue to use the Redfin descriptions.

The prepared 16 GiB image is under ignored
`research/ipsw-redfin/root-image-redfin-fast/`, SHA256
`1c7ab7f21b4075d23ed70f9f2a418f7ae2993d7857c844e7854d3cc076de7478`.
The catalog pass restored 283630 distinct CNIDs in 6 seconds and fsck passed.
Native mounts verified owners/modes, 43 cache hardlinks, and source SHA256/size
for launchd, dyld and every runtime shared-cache file. Future `build-root.py`
runs use the pinned HFS library's existing catalog leaves directly; keys,
Unicode names, file types, flags and hardlink counts remain intact.

`build.py --ufs-root --apple-adt ...` prepares a read-only Apple-root boot image.
Android's current encrypted F2FS userdata is not an HFS root. Installing the
prepared root there destroys Android user data and requires explicit approval.

## Offline recovery

`build-recovery.py` builds a temporary ADB-only Linux image from the verified
boot/vendor_boot backups. Its root ADB, recovery marker, unmounted userdata and
read-only disk access have been verified. It disables the recovery UI and starts
a 120-second return timer. Build the bootloader-return variant:

```sh
python3 ports/redfin/build-recovery.py \
  --boot backup/redfin/boot_b.img --vendor-boot backup/redfin/vendor_boot_b.img \
  --return-target bootloader --out research/redfin-recovery-adb-safe
```

Before erasing userdata, save `/data/vendor_ce/0/ramoops/priv.pem` and `pub.pem`
from unlocked Android user 0 to the ignored host directory
`backup/redfin/ramoops-private/` (directory `0700`, PEM files `0600`). These keys
live in credential-encrypted userdata and disappear when it is replaced. Keep
the matching `/vendor/bin/ramoops` executable in that directory as `ramoops`.
The collector pins its SHA256 to
`7d80a3a0cf6a6050beb6baa95ae5808107f2d70a8ca11d4b61d225caf930d3d2`
([public Redfin binary](https://github.com/TheMuppets/proprietary_vendor_google_redfin/blob/30c82c83bc03b0dfc83dd6d6a041f51fc35ebfab/proprietary/vendor/bin/ramoops)).
Never commit keys, device captures or downloaded artifacts.

From hardware fastboot, first collect existing logs and prime the next boot:

```sh
python3 ports/redfin/boot-cycle.py --collect-only --from-bootloader \
  --recovery-image research/redfin-recovery-adb-safe/recovery-adb-only.img \
  --ramoops-key-dir backup/redfin/ramoops-private --leave-bootloader \
  --out logs/redfin/recovery-prime
```

The collector saves the current 4 MiB raw bank and metadata before priming.
Encrypted captures must authenticate successfully before that metadata changes.
Decryption uses the host private key; only `pub.pem` and the verified executable
are copied to recovery RAM. `ramoops -l -c` loads public-key metadata for the next
boot and clears the old AES block. It does not write a storage partition.

Build the XNU image with `--return-bootloader`, which enables the required SPMI
probe and PMIC return path. An ordinary `out/xnu` image does not enable it:

```sh
python3 ports/redfin/build.py \
  --stock-boot backup/redfin/boot_b.img \
  --kernel research/redfin-build/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet \
  --dtb research/redfin-root/device.dtb \
  --memory-base 0x180000000 --memory-size 0x80000000 \
  --ufs-root-probe --apple-adt research/ipsw-redfin/extracted/d22ap.adt \
  --return-bootloader --out ports/redfin/out/log-autonomous
```

Then run the XNU/log cycle without Android:

```sh
python3 ports/redfin/boot-cycle.py ports/redfin/out/log-autonomous/redfin-xnu.img \
  --from-bootloader --leave-bootloader \
  --recovery-image research/redfin-recovery-adb-safe/recovery-adb-only.img \
  --ramoops-key-dir backup/redfin/ramoops-private
```

Starting from fastboot has no pre-boot log baseline, so `log_freshness` remains
`unproven`: status describes saved observations, not proof of this boot's logs.

Before the first XNU boot after replacing userdata, prime through this recovery
and leave the phone in bootloader. Continue using recovery for subsequent logs;
there must be no Android fallback after an HFS installation. The collector stops
and verifies the recovery timer while working, then `--leave-bootloader` returns
to verified hardware fastboot.

For a saved capture, standalone host decryption uses `openssl` and `libcrypto`
(`brew install openssl@3`), with no Python crypto packages:

```sh
python3 ports/redfin/decrypt-ramoops.py \
  --metadata logs/redfin/recovery-prime/after/alt-ramoops.metadata \
  --raw logs/redfin/recovery-prime/after/alt-ramoops.raw \
  --private-key backup/redfin/ramoops-private/priv.pem \
  --out research/redfin-ramoops-decrypted.raw
```

The helper verifies metadata CRC, RSA unwrap and AES-GCM authentication before
creating plaintext with mode `0600`. It refuses existing output files.

Before installation, keep the phone in verified offline recovery with its return
timer stopped and save a complete rollback copy:

```sh
python3 ports/redfin/backup-userdata.py \
  --expected-gpt backup/redfin/sda-gpt-before.bin \
  --out backup/redfin/pre-ios-full-20261022
```

This reads all userdata bytes, including the final partial MiB, and metadata
containing Android encryption context. It flushes private host files to disk and
requires matching host/device SHA256, unchanged GPT and unmounted filesystems.
Only a successful `backup.json` establishes a verified backup.

`install-root.py` defaults to checking the image, recovery state, both GPT headers
and partition geometry. It records the exact proposed write. Writing requires
the separate `--erase-userdata` flag and prior approval; it first stops and
verifies the recovery timer, rechecks the state, then verifies the entire written
image and unchanged GPT captures. This Pixel's secondary header references the
primary entry array; the independent backup array has not been demonstrated.
The checker preserves and hashes the full secondary capture without rewriting it.
