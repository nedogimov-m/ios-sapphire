Redfin AppleCLCD bring-up
========================

The first Apple userspace boot passed keybag and launchd boot tasks, started
backboardd and SpringBoard, then SpringBoard trapped with `failed to find the
main CADisplay` (apple-root-rw-keybag/xnu-console.txt:11952,16161).

`display.patch` adds an opt-in CPU-copy backend to the existing AppleCLCD and
IOMobileFramebuffer user-client ABI. Apply it after `redfin.patch`; it does not
depend on the UFS, trace or shutdown overlays. Both `redfinfb=1` and the explicit
`disp0` contract from `mkadt.add_linear_display()` are required. The default
Redfin display path stays disabled.

The only accepted physical contract is the splash buffer observed working in
REDFIN DIAGNOSTICS: PA `0xa0000000`, reservation `0x02300000`, 1080×2340 BGRA,
4320-byte stride. The rounded IOSurface mapping stays inside that reservation.
Provider properties use absolute addresses, without arm-io address translation.
The canonical 1125×2436 iPhone X canvas uses the legacy centered crop unless
one of the GUI8 fit modes below is explicitly selected.

The backend publishes the default IOSurface, software vsync notifications, and
an empty IOAcceleratorES service so CoreAnimation can select its CPU renderer.
It performs no modem/GPU initialization, MDP/DSI register mapping, hardware
scanout address changes, backlight commands, or panic-console retargeting.
Use `sweetfb_noconsole=1` for GUI boots; RAMLOG still receives kernel output.
CPU copies default to 5 Hz (`sweetfb_hz` accepts 1–10); the strict GUI8 profile
additionally accepts 30/60. This is a copy limit and does not measure frames
per second or switch the panel to its 90 Hz mode.

The live tree selects `s6e3hc2_dsc_1080p_cmd` / `dsi_cmd_mode`. The observed
diagnostic screen proves the buffer works on this unit; it does not establish
continuous refresh, hardware vblank, or display power management. Next runtime
evidence is `REDFIN FB: AppleCLCD CPU-copy`, backboardd opening
IOMobileFramebufferUserClient, `CPU present ... copied ... bytes`, and a visible Apple frame.
Kernel publication alone does not prove visible GUI output.

Full canvas and front camera — 2026-10-23
---------------------------------------

`display-fit.patch`, applied after `smp-gui.patch` and `touch-overflow.patch`,
adds the checked CPU scaler in `display-geometry.h`. The kernel copy is
`iokit/Kernel/arm/RedfinDisplayGeometry.h`; host tests require byte equality.
Both display and HID require the exact GUI8 profile and the existing observed
display/touch geometry. Apple's reported canvas, iPhone identity, MobileGestalt
configuration and 20H392 swap/HID ABIs stay the same.

| Builder option | Boot argument | Physical viewport | Behavior |
| --- | --- | --- | --- |
| Omitted | Omitted | 1080×2340, source offset 20,48 | Existing centered crop |
| `--display-fit full` | `redfinfit=1` | 1080×2338 at 0,1 | Scale the complete 1125×2436 canvas; one black row above and below |
| `--display-fit cutout` | `redfinfit=2` | 1017×2204 at 31,136 | Scale the complete canvas below the front camera; black top and side margins |

Add `--display-fit cutout` to the established bounded
[GUI8 build command](README.md). An explicit `redfinfit=0`, unknown mode,
duplicate flag or a fit flag outside GUI8 is rejected. Omitting the option
retains the prior image contract.

The scaler follows the full source/destination rectangle policy and bilinear
pixel-center filtering reviewed in HackiOS's
[MiniIOMobileFramebuffer.cpp](https://github.com/oosexgang/hackios-xnu-kernel/blob/8e61187098f2c26c5daee8f9f72b6416aa64b9ab/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp#L723).
Each layer uses its actual source rectangle, stride and allocation offset.
It accepts only observed BGRA, four-byte, one-element pixels; checks the
complete accessible allocation and both rectangles with wide arithmetic;
clips output to the viewport; and leaves source surfaces untouched.
Source dimensions are bounded to 16384 per axis. The row/column workspace
lives in the heap-owned AppleCLCD object, never on the kernel stack.

The 136-pixel exclusion comes from Google's
[Redfin resource overlay at commit 62df7438508565dfc05fab923e84f0704f5a0f07](https://android.googlesource.com/device/google/redfin/+/62df7438508565dfc05fab923e84f0704f5a0f07/redfin/overlay/frameworks/base/core/res/res/values/config.xml#208).
Its `config_mainBuiltInDisplayCutout` describes a radius-40 circle centered
at physical 81,77, anchored at the left edge. The conservative rectangle
approximation is `[0,145) × [0,136)` and portrait status-bar height is 136px.
Mode 2 uses this complete top exclusion instead of guessing a UIKit inset.
The pinned public HackiOS kernel/userland sources have no identified dedicated
notch/cutout/safe-area override. Existing iPhone X userland layout remains;
this mode positions the whole canvas below the camera, without changing
private UIKit layout data. Rounded-corner layout has not been separately
validated on the panel.

Touch applies the inverse viewport transform. A new contact in a black
margin is ignored until release, so it cannot turn into a tap when moved
inside. A contact that began in the viewport continues to its edge and
retains its release when dragged into a margin. Edge gestures use viewport
edges rather than panel edges.

`python3 -m unittest ports.redfin.test_display_geometry -v` passes eight host
tests. They reconstruct production sources from ordered patches, execute
the actual display/HID methods, check bilinear pixels against an independent
reference, exercise subrectangles and clipped/extreme coordinates, preserve
padded source allocations, test malformed extents/formats and legacy crop,
and validate touch suppression/releases. C11 AddressSanitizer and
UndefinedBehaviorSanitizer also exercise 200 deterministic cases with read-only
source mappings immediately before guard pages. These checks do not establish
device copy performance or physical camera alignment. The next device test
is a temporary GUI8 `redfinfit=2` image with the existing 180-second graceful
shutdown and authenticated framebuffer/touch capture.
