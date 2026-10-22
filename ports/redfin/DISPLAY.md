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
The canonical 1125×2436 iPhone X canvas is cropped to the physical panel.

The backend publishes the default IOSurface, software vsync notifications, and
an empty IOAcceleratorES service so CoreAnimation can select its CPU renderer.
It performs no modem/GPU initialization, MDP/DSI register mapping, hardware
scanout address changes, backlight commands, or panic-console retargeting.
Use `sweetfb_noconsole=1` for GUI boots; RAMLOG still receives kernel output.
CPU copies default to 5 Hz (`sweetfb_hz` accepts 1–10).

The live tree selects `s6e3hc2_dsc_1080p_cmd` / `dsi_cmd_mode`. The observed
diagnostic screen proves the buffer works on this unit; it does not establish
continuous refresh, hardware vblank, or display power management. Next runtime
evidence is `REDFIN FB: AppleCLCD CPU-copy`, backboardd opening
IOMobileFramebufferUserClient, `CPU present ... copied ... bytes`, and a visible Apple frame.
Kernel publication alone does not prove visible GUI output.
