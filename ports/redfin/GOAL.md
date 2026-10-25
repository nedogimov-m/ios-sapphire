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

- Device is idle in verified unmounted recovery, with its return timer
  stopped. Fresh private V8 snapshot is clean/consistent, write_count761257,
  empty journal: `research/redfin-graphics/root-update-v8/`.
  Only its read phase has run. Its stage/apply still need adapting for the
  complete next bundle; do not run the old new-files-only stage unchanged.
- Native Photos helper executes with platform/signature/entitlements admitted
  and512MiB. It refuses its system-library URL guard before creation. Inspect
  actual20H392 PHPhotoLibrary/PLPhotoLibraryPathManager URL semantics; do not
  invent a library ID/schema or bypass the Photos UI assertion. Fresh V8
  crash reports and directory metadata still need collecting read-only.
- Actual recovery reports this unit's hardware SKU as G5NZ6 and model Pixel5,
  saved privately in V8/physical-model-evidence.json. Use the actual model
  number; retain the separate iPhone10,3 compatibility identity required by
  the installed userland. A model number is not an Apple factory part number.
- Actual securityd asks AppleKeyStore selector10 with2scalars/32input bytes,
  expecting1scalar/40output bytes, and receives Unsupported0xe00002c7.
  SweetKeyStore implements neither key wrapping nor unwrapping. Preferred
  MiniAppleKeyStore provides the ABI and missing operations, but uses a fixed
  nonsecret mixing pattern. Adapt the ABI with a persistent private software
  wrapping key and the existing portable AES provider; keep secrets out of
  git/logs/accessible IORegistry properties. Verify persistence across boots.
- Remaining mixed render/presentation audits average3240us per submission.
  Panel GPU work averages7805us; total presenter13162us includes other work.
  Inspect duplicated immutable firmware comparisons/parent checks and memory
  ordering before optimizing. Their exact contribution is still a hypothesis.
  Keep complete ownership/fault/completion checks. Consider removing the
  staging/packing bandwidth with direct scaled interleaved rows only after
  a bounded native comparison to the already proved GPU path.
- Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and userland
  906425b75e02b4f99eb5d7bb1ef7c9583472d772 contain no identified cutout-layout
  override. Review current UIKit20H392 class/selector ABI before implementing
  the clock/status-bar adaptation. Keep the native logical1125x2436 canvas
  while using the full1080x2340panel and matching inverse touch geometry.
  Actual UIKitCore1242978a2c2c37818d6c9777edce2804 has _UIStatusBar
  setAvoidanceFrame:, setAvoidanceFrame:animationSettings:options:,
  layoutSubviews and native region/layout APIs; _UIStatusBarTimeItem has
  timeView/shortTimeView/pillTimeView/viewForIdentifier:/applyUpdate. Exact
  types/RVAs are in research/redfin-photos/native-path-and-statusbar-methods.json.
  Investigate the native avoidance/layout mechanism before moving leaf views.
- Exact Google panel DTS is downloaded privately under
  `research/redfin-display/panel90-source/`, commit
  500b3a2059c1eec0fec08ec56add06320ea901a8, SHA256
  5a42f5ebeb27708068f0406fc98625cdbeb199dd45af65031702fad4547d0e4d.
  Its60/90Hz modes both specify554MHz DSI clock and different timing-switch
  commands. The attempted old in-kernel DSI/SDE source paths returned404;
  locate their actual matching display repository before adapting writes.

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
Do not reuse V7 or the pre-boot data-repair snapshot. V8 is the current clean
generation. No new iOS boot has followed the gpu-panel-v1 combined run.
