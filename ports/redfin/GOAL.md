# Redfin user goal — 2026-10-25

The same objective is active in `/goal`. Continue autonomously. Implement a
complete coherent block, then run combined checks and an integrated hardware
test. Do not boot/test between its individual implementation subtasks.

The user explicitly authorizes doing and testing everything independently;
the phone stays connected. Implement every requested feature, including
features whose final physical/manual checks need the user. Defer only those
human-dependent actions/checks, and keep progressing on the rest. Do not wait
for manual GUI feedback before continuing independent implementation/tests.

## Requested results

- Preserve working GUI, touch, Phone, Wi-Fi and internet.
- Make system GPU rendering smooth and responsive; remove remaining driver
  and presentation overhead. Integrate actual Adreno620 Metal support.
- Fix Photos and related application failures, avoiding window-server resets,
  loss of touch/GPU, black screens and kernel panics.
- Reduce the roughly minute-long Wi-Fi startup. Persist network credentials
  through native Keychain and reconnect automatically after reboot.
- Use the complete physical screen. Account for the real camera cutout in
  status-bar/time placement, without shrinking the entire UI below a top strip.
- Switch the physical display to90Hz and verify actual refresh separately
  from rendering FPS. A faster software notification timer alone is insufficient.
- Keep the persistent real serial; add the correct model-number row. Complete
  and verify the requirements for App Store/Apple ID with real authorization.
- Fix power: real battery level/state, charging indication, cable/source
  changes, actual charging and supported power/charging modes.
- Fix thermald/thermalmonitord with real temperature inputs, thermal control
  and overheating protection.
- Support every actual Redfin sensor: accelerometer, gyroscope, compass/
  magnetometer, proximity, ambient light, barometer and remaining sensors
  established by the physical hardware inventory.

## Confirmed checkpoint

Source13e151f; results7938e0b. Local kernel build20261025-050146/noCI;
known stable image `ports/redfin/out/gpu-panel-v1/redfin-xnu.img`.
Authenticated boot026ce38e14155367 proves system Mesa/EAGL composition,
over2400completed native A620 panel presentations, full private2527200pixel
and guard checks, four64pixel physical-panel comparisons, no GPU retirement,
submit failure, kernel panic or backboardd restart. Touch104/104, no errors.
User confirms Phone works, Photos aborts, and estimates30–40fps with modest
improvement but persistent judder/input delay. Stable60/90fps is not proved.

Serial appears in About and MobileGestalt; its private digest matches the
actual Pixel serial. A serial does not itself supply Apple activation.
Metal, model-number publication, true90Hz, proper cutout layout, charging/
thermal/sensor support and credential persistence remain unfinished.

## Current independent work and evidence

Source a07a2ce, integrated gui-platform-v3 authenticated boot24640daa371b61c8.
Kernel local20261025-062535/noCI (4c26d9c2...), unchanged from descriptorV2.
Fresh V9 complete update has all25ranges/83blocks/339968bytes backed up and
readback-verified; native readonly fsckPASS, one new block/zero freed.
V9 is applied and must never be reused. Capture ends with clean root,
write_count783850 and verified Fastboot. Exact args/builds/results are in
newest NOTES. Private wrapping material must persist unchanged.

Confirmed in this combined autonomous run: physical90Hz (TE16677->11120us,
INTF21->32frames/350ms), complete1080x2340viewport/inverse touch, current
90Hz-compatible EAGL installation, native shader/IOSurface and backboardd
completed rendering/fences without GPU fault/Mesa submit failure or panic.
Phone opens through native async LaunchServices and survives5/17s with
stable SpringBoard. SecItem existing1/read0/exact1 proves reboot persistence.
Time moves from x30 to53.35points outside the physical camera; measured
repeated layouts show no cumulative drift. Actual serial/model publication
remains valid. No human smoothness/cable/motion/account check is required yet.

Outstanding linked userland work: Photos and assetsd abort, native creation
now reaches the ordinary URL instance API but returns PhotosXPC4103 because
the native assets service is unavailable. Symbolicate actual crashes and fix
the service. UIKit still reports60maxFPS while panel TE proves90; publish the
verified physical rate through the native app/display path. Check native
MobileWiFi password persistence/autojoin and reduce radio startup latency.
The synthetic SecItem proof alone does not prove an actual saved Wi-Fi key.

Implement the next complete block before combined testing/new boot. Native
power inventory is PM7250B/QG/ADC5/SMB5 and TSENS26xx, plus three standard
OSM cpufreq-hw domains. Adapt these real interfaces and the preferred
IOPMPowerSource/thermal notification model; do not substitute the mismatched
Redwood PMIC/EPSS or generic RRADC/tsens-v2 layouts. Preferred new kernelHEAD
d82c64a3a31cd27a0a0afbf6e213e467e44b1b4c and userlandHEADa79ff077... have
been read-only reviewed; existing graphics references remain8e611870/906425b.
Power/charging/thermals, all actual sensors, native Metal and real Apple
account authorization remain mandatory. Defer only human-dependent actions.

The next full source block is implemented and host-built: native Redfin
QG/ADC5/SMB5 battery/charging, TSENS26xx/OSM temperature/frequency control,
retained-RTC/UTC mapping, native thermal notifications and verified90Hz
CADisplay periods/UIScreen caps. Native MobileWiFi password/readiness/TLS
checks use a synthetic unjoined marker only. Actual assetsd TCC rejection
is confirmed; native SecTask/TCC and daemon logging are added without a
permission override. Do not claim Photos repaired until a real run proves it.
All47distinct selected host casesPASS; local kernel20261025-072951/noCI,
e3ae1202... is frozen. Complete signed/actual-import bundles and V10 private
stage pass native readonly fsck. V10 has not been applied or booted yet;
31ranges/234blocks/958464bytes,55new/zero freed. Only this complete V10 set
may be applied. Next physical results, full Metal, every actual sensor and
real account authorization remain unfinished; see newest NOTES.

## Operating constraints

Follow AGENTS.md, README.md and latest NOTES.md. Prefer the user's two
HackiOS upstreams, adapt hardware/20H392 ABI and record reviewed commits in
UPSTREAM.md. Commit completed work and record exact builds, args and results.
Only temporary fastboot boot; preserve boot/recovery, modem/persist/EFS,
userdata and backups. Confirm destructive operations separately.

Private serial/config is `backup/redfin/ios-device-identity.json`; never print
its value. Keep dumps, logs, secrets and Apple artifacts ignored. The V7
new-zero-block installer bug was fixed: write ALL newly allocated blocks,
including zeros, and verify complete files through their actual extents.
Do not reuse V7, the pre-boot data-repair snapshot or applied V8. Use a fresh
root generation for the next update; assess the current combined run first.
