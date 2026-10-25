# Redfin user goal — 2026-10-25

The complete objective remains active in `/goal`. Work autonomously while
the user sleeps; the phone stays connected. Implement a coherent complete
block first, then combined checks and one integrated hardware run. Do not
boot/test between individual implementation subtasks. Implement even the
features whose final physical/manual checks need the user; defer only those
human-dependent actions, and continue independent work.

## Latest checkpoint

Source889e7d0; local kernel20261025-095649/noCI6ce92eff...;
V10/b199fc38b7166150 passes authenticated image/launchd/userspace proof,
clean root836288 and verified Fastboot. V14 is applied/stale; never reuse.
Real Metal192compute commands, BGRA/RG8 and three alpha-blended draws/pixels/
guards PASS. System Metal is active. Warmed automatic six-layer animation
measures13.899completed physical GPU fps and60.000callback Hz. Stable60/90fps
is unfinished. Phone survives; window server stable; no GPU fault/panic.

Photos/assetsd still fail. Native self/audit Security and TCCD's own actual
DER/signing-ID/token checks succeed; native Photos preflight0/access assertion
remains. Resolve actual policy/attribution without replacing native answers.
WLAN starts late and guarded4KiB firmware copy takes15.03s; next implement
its complete timing/copy improvement with the linked native sensor transport.
SSC protocol codecs are in progress. ADSP/SSC/HID, remaining render/display
throughput, real credential/autojoin and account authorization remain.
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
