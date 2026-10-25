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

Whole native platform/display block source is df42261, with its standalone
builder import correction. Local kernel20261025-061234/noCI PASS; SHA256
522ea9fd7ded64cd6b327ddc16a100721feae172e576bdecc45651ce7521b042.
All138distinct selected host cases PASS. Native Photos/UI/app checker are
signed and every nonweak import resolves through installed20H392 (52libs).

Implemented; actual verification status follows below: persistent private AES256/RFC3394
AKS wrap/unwrap, synthetic SecItem reboot probe, actual model publication,
canonical native Photos URL guard, full1080x2340viewport/inverse touch,
UUID/type-guarded native status-bar camera avoidance, physical90Hz FIFO/TE
transaction, native display mode metadata/current IDs and corrected native
time/time/counter callback ABI. Nested immutable-payload comparisons are
removed while the complete outer GPU audit still checks every payload once.
The opt-in native checker opens Phone/Photos and records process/SpringBoard
survival without calls/messages/account actions.

Image ports/redfin/out/gui-platform-v1/redfin-xnu.img has preflightPASS;
nonce3635d632d4fbfca8, SHA256
dfcf8cdcfa402d32bac0888ed0df5b166fa913172f5f3c6856d53a1b930d45ae.
Exact pending full-panel90Hz capture args are in the newest NOTES entry.
Capture excludes the separate userspace-wait payload by the existing policy.

V8 installation is complete:22backed-up/readback-verified ranges,195blocks/
798720bytes,38new blocks, zero freed; all signed files match completely,
native readonly fsckPASS, root clean/write_count761257, empty journal/JIB
unchanged, verified Fastboot. Do not reuse V8 for another update. The next
fresh V9 read phase must include the newly installed UI/GUI checker files.
Private backups/preimages stay under research/redfin-graphics/root-update-v8.

Authenticated V1/V2 boots prove actual panel90Hz: TE about16683->11124us
and INTF21->31frames/350ms, native FIFO completion and90Hz mode publication.
Full display/HID viewport and authenticated lock-screen RAM capture pass.
V2's AKS descriptor preparation fix eliminates the panic; native SecItem
add/read succeeds exactly. Model/serial MobileGestalt digests match actual
hardware. Root is clean/write_count770135; eight file logs captured read-only;
device is verified Fastboot. V2 kernel/build/image/nonce are in NOTES.

Remaining linked corrections before the next combined/persistence run:
rebuild the installed loader/EAGL bridge with the current90Hz profile (the
old compiled profile silently skips system acceleration); use the actual
PHPhotoLibrary instance URL/create-or-upgrade API because system Media is
identifier0 and is not a well-known library; improve native app launch
checks with async errors/foreground options. Status-bar library installs,
but correct time placement and system smoothness are not yet observed.
No Phone/Photos UI success is inferred from rejected legacy LS opens.

Next fresh V9 read must include installed UI/gui-check files and bridge
updates. Never reuse V8. Keep backup/redfin/ios-keychain-material.json
unchanged and private; future saved keys depend on it. Complete the linked
source fixes, then combined build/preflight/integrated test and native
Keychain persistence. Continue power/charging, thermals/all actual sensors
and Metal implementation; defer only human-dependent checks/authorization.

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
