# Pixel 5 / redfin

Source base: ios-sapphire `d7858e985c4fd2fd41c2c4300c5279cbc8eee178`,
ios-topaz `89451b811a4e6cc5cdcf734c45887163d92c599e`, XNU
`xnu-8796.141.3`. Hardware sources and live observations: [HARDWARE.md](HARDWARE.md).

Static Darwin PID1 executes from RAM through mockfs: successful exec and its
first EL0 syscall are captured. Console startup/heartbeat remain under investigation. Full iOS
16.7.16 userspace, storage, touch, USB and display acceleration still need board
drivers. The redfin overlay deliberately disables the inherited Xiaomi drivers
and fixed early framebuffer writes. It supports one CPU.

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

For autonomous boot and log recovery:

```sh
python3 ports/redfin/boot-cycle.py ports/redfin/out/xnu/redfin-xnu.img
# Capture existing logs without another boot:
python3 ports/redfin/boot-cycle.py --collect-only --timeout 5
```

The shim starts the hardware watchdog immediately before entering XNU (default:
28-second bark, 31-second reset). Android decrypts ramoops, then the host saves
`console-ramoops-0` and a manifest under `logs/redfin/`. This has been observed
recovering the Darwin startup/IOKit log. Log delivery happens after reset.
Raw access to `/dev/access-ramoops` is disabled by default because opening it can
block Android's alt-bank switch. Do not read it during automatic recovery.
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
and payload relocation bounds. They cannot prove hardware execution. A visible
`REDFIN userspace: init running as PID 1` and subsequent heartbeat are the next
success criteria. Full iOS launchd/SpringBoard have not been demonstrated on redfin.
