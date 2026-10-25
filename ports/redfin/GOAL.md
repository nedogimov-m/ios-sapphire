# Redfin user goal — 2026-10-25

The complete objective remains active in `/goal`. Work autonomously while
the user sleeps; the phone stays connected. Implement a coherent complete
block first, then combined checks and one integrated hardware run. Do not
boot/test between individual implementation subtasks. Implement even the
features whose final physical/manual checks need the user; defer only those
human-dependent actions, and continue independent work.

## Latest checkpoint

V12 recovery boot b2113da1ed6dead5 is clean/not inconsistent861710, file logs
captured, verified Fastboot. V16 applied/stale. Actual GMEM5/sysmem0 and all
native Metal dependency/pixel/guard probes PASS; real animation13.500fps versus
60callback Hz, no sustained speed improvement. Phone survives, Photos fails.
Photos cause is native TCC error6: Sandbox extension issuance fails; inherited
0050 returns ENOENT for issue5/consume6. Implement real bounded process-bound
capabilities, preserving TCC decisions. Cold ADSP order fixed in working tree
and local115006kernel built (unbooted); direct VD6281/GENI/SLG51000 remains.

V12 observed: V16 applied once/stale. Actual ADSP source, LCX/LMX votes and
AOP on pass, then the WLAN owner stalls before any PAS reply (cold PAS shutdown
is the first candidate). Other CPUs/GPU/thermal keep running, no recorded panic.
Root852658 is NOT clean, no user-file extraction/Photos/FPS conclusion. An
ordinary temporary boot without optional ADSP is collecting logs and replaying
the native HFS journal before any further offline update. Adapt preferred
upstream's owned-metadata-page -> INIT -> MEM_SETUP -> firmware copy -> AUTH
cold order; never issue inactive-DSP shutdown or touch its RAM before setup.
V12 sensor/CoreMotion and new GPU throughput remain unproved.

V12 implementation/build milestone: native GMEM routing/dependency probe,
actual TCC reply observation and complete PAS1/host2/SSC/registry/HID path
are built. Kernel local20261025-113137/bffe7c0d...; V12/d15ba0e2...;
nonce ecd67b63b06f7279 passes the complete real-image preflight. V16 is freshly
staged against845261 with full readback/signatures/readonly fsck,5315new/zero
freed blocks; not yet applied or booted. Next one integrated capture. All
physical sensor/CoreMotion, new FPS/Photos results and direct VD6281 remain
unproved/unfinished. Previous observed baseline follows.

Source1c510c9; local kernel20261025-102326/noCI00fa3c57...;
V11/7dca6c09263e4ae3 passes authenticated image/launchd/userspace proof,
clean root845261 and verified Fastboot. V15 applied/stale, never reuse.
Native async Metal192compute/BGRA/RG8/three-blend pixels+guards PASS, Phone
survives, window server stable, no GPU fault/panic. Warmed six-layer workload
12.500physical GPU fps versus60.000callback Hz: stable60/90fps unfinished.
Native64KiB firmware copy improves15.034s->6.247s with all readback/contracts;
FW_READY32.346s/station35.947s after worker, real credential/autojoin unproved.

Native TCCD actually permits the Photos entitlement and its audit check;
SecTask and native pidpath also succeed. Assetsd/preflight still fail, so
trace the native authorization record/error reply, not another permission
bypass. Sensor SSC codecs and host2 SMEM/SMP2P/GLINK selection are in progress,
not integrated/built/proven. Actual115persist registry/calibration files are
privately captured read-only. Complete ADSP/power/SSC/HID, remaining GPU
throughput and Photos reply cause before the next integrated test.
Exact source/builds/boot args and results are in newest NOTES.md.

## Required results

- Preserve working GUI, touch, Phone, Wi-Fi and internet.
- Finish true system GPU/Metal acceleration with smooth responsive UI and
  verified completed frames; eliminate remaining submit/presentation costs,
  kernel panics, black screens and loss of touch/GPU.
- Repair Photos and related application/service failures without window-
  server resets. Actual native assetsd/TCC failure remains under diagnosis.
- Shorten roughly minute-long Wi-Fi startup; persist actual credentials in
  native Keychain and reconnect after reboot. Native SecItem and synthetic
  MobileWiFi markers already persist across boots; a real saved credential/
  autojoin is not proved by those markers.
- Fill the complete1080x2340panel and put the clock/status bar outside the
  physical camera cutout. Full panel/inverse touch and repeated nondrifting
  clock placement x53.35points are already observed.
- Use true physical90Hz, separately from rendering FPS. TE11120us and native
  DPU frame count already establish90Hz; app callback/render cadence still
  requires the new native-period and batching capture.
- Keep the permanent real serial and correct model row. Native serial/model
  publication is observed. Finish App Store/Apple ID prerequisites with real
  authorization/activation; a serial alone is not Apple activation.
- Finish native QG/ADC5/SMB5 battery/charging/cable/source/power behavior.
  Real readings/native full state are observed; actual charging/cable changes
  remain to be confirmed when conditions permit.
- Finish thermald/thermalmonitord from real TSENS26xx inputs and native OSM
  control/overheat protection. All three domains reach1804.8/2208/2400MHz;
  actual thermal pressure lowers/restores them. No fake temperatures.
- Support every actual Redfin sensor: accelerometer, gyro, magnetometer/
  compass, proximity, ambient light, barometer and remaining physical or
  firmware-derived sensors established by inventory. Captured vendor-base
  configs name LSM6DSR/LIS2MDL/BMP380/TCS3701; live DT also has VD6281.
  ADSP PAS1/remote2, native SSC/registry and HID/CoreMotion integration remain
  to implement and verify; raw configs do not prove runtime identity.

## Constraints and private state

Follow AGENTS.md, README.md and newest NOTES.md. Prefer the user's two
HackiOS upstreams, adapt native Redfin hardware/20H392 ABI, and record exact
reviewed pins in UPSTREAM.md. Commit completed changes and record builds,
exact boot args, results and unfinished work at every milestone.

Only temporary `fastboot boot`; preserve boot/recovery, modem, persist, EFS,
userdata and backups. Destructive operations need separate confirmation.
Existing root updates are reversible, preimage-backed, fully readback-
verified and require clean HFSX/native readonly fsck. Never reuse any applied
stage or old root-generation snapshot. Write every newly allocated block,
including zero blocks. Keep actual credentials, serials, raw logs, dumps and
Apple artifacts outside git.

Private identity is `backup/redfin/ios-device-identity.json`; persistent
wrapping material is `backup/redfin/ios-keychain-material.json` and must not
change. Native retained-RTC epoch mapping is
`backup/redfin/ios-rtc-anchor.json`. Do not print their secret values.
Manual smoothness, cable/motion and real account login stay deferred while
independent implementation and hardware checks continue.
