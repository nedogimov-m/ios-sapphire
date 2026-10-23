# iOS 16 on sweet (Redmi Note 10 Pro, SM7150) - working notes

## REDFIN resident MPSS source hardware PASS — 2026-10-23

Source f46c2e5; local native build `build-20261023-144832.log` (no new CI run).
Fresh authenticated/image/nonce-matched capture
`wifi-fw-source-v1-20261023-145215` reports result0/stage2/pinned1,
99,395,632 source bytes, 35 PHDRs, 33 loads and 31 assets. The native hashes
and parser accept 99,384,626 payload bytes and 191,553,563 planned BSS bytes.
These are validated source/plan counts: no payload was copied to MPSS and
no BSS was zeroed on the device. ABL accepted this larger compressed image
and XNU reached the real source mapping, hashing and parsing code.

Observation: the physical IOMemoryDescriptor emits a managed-page
diagnostic/backtrace for the reserved kernel-RAM source. Execution continues
through source result0 to md0/PID1 and 11 heartbeats; no panic is observed.
This warning is retained in the private capture rather than hidden. The
temporary collector authenticates/decrypts the capture, matches boot ID
575a9e2c5c4caf1c and the exact image, verifies recovery with no disk mounts,
and leaves verified fastboot. HFSX remains clean/unmounted, inconsistent=false,
write_count462335. No partition flash or media write occurred.

Kernel `04a1e8d7d3aa0536153fe078d8fedafb68c21f1dd5301c43760afb0417c653c7`;
image `7ff5c88f4ab24347f9d7e924a6bd5f78d904d9e417f0f723454a01ed63b98d2a`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinwififw=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x575a9e2c5c4caf1c`.

Unfinished: connect the proven resident source and retained power/AOP path
to a complete native PIL lease (metadata storage/cache ownership, PAS4,
proxy/bandwidth, fresh SMP2P ready/stop), then GLINK/QRTR/WLFW, association,
frames and the iOS interface. The native Google `subsys-pil-tz.c` uses PAS
INIT/MEM_SETUP/AUTH directly and does not gate on PAS_SUPPORTED; the earlier
zero capability query alone is not proof that native PIL cannot work. No
firmware authentication, radio startup or functional Wi-Fi is claimed.

## REDFIN native resident MPSS source probe built; hardware run next — 2026-10-23

Resumed the unfinished Wi-Fi work from source parent d0ac432. The separate
`--wifi-fw-source-probe` requires the recorded private bundle/SHA256, native
CPU0/md0 profile and shim plus kernel bootloader return. It adds the native
live exclusion list to the firmware ADT, maps only the resident source
read-only, checks its whole-bundle/per-asset hashes and parses the existing
MPSS plan, then releases the source. No destination mapping, PAS, modem
startup, AOP/power, SMEM write or media access is added. Canonical source,
kernel overlays and the verified prepared native tree are synchronized.
Fixed the unfinished C++ plan-name collision and bound the source selector
to the host return policy, including rejection of mixed source/power modes.

Observation: 93 focused firmware/native-power/build/return checks pass
(3 private-artifact cases skipped; `source-probe-host-tests.txt`). Native
local build `build-20261023-144832.log` succeeds; no new Codemagic/Actions ID.
The preceding sandboxed build compiled/linked but failed at the dSYM shell's
`/dev/fd` access; the completed build reran with that access allowed.
Actual full Image/payload/live-FDT C-loader and shim-return preflight pass.
The boot image is 79,335,424 bytes; fastboot reports max-download-size
0x10000000. Decompressed Image is 117,103,408 bytes. These host checks do
not yet establish ABL placement or source access on the phone.

Kernel `04a1e8d7d3aa0536153fe078d8fedafb68c21f1dd5301c43760afb0417c653c7`;
image `7ff5c88f4ab24347f9d7e924a6bd5f78d904d9e417f0f723454a01ed63b98d2a`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinwififw=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x575a9e2c5c4caf1c`.

Next: one temporary `wifi-fw-source-v1` boot with authenticated/image/nonce
matched collection and read-only HFS-header observation. Native PAS4 and
fresh SMP2P/GLINK/WLFW, association/data and the iOS interface remain
unfinished. The earlier negative PAS_SUPPORTED4 result is still unresolved.
All firmware, images, device identifiers and logs remain ignored/private.

## REDFIN CB0/1 read-only hardware PASS; user switches priority to Wi-Fi — 2026-10-23

Source parentdee6f34. New explicit `--gpu-smmu-context-probe`/
redfinsmmu2 binds additional exact context-policy before parent power writes.
After fresh GMU/TCM and stable global snapshot, reads only CB0/1's12registers
twice. Every access retains parent/source/reset/IRQ/ADT/argument guards.
CPU mapping is16KiB because XNU's granule; CB2/3 are mapped but never
addressed. No context stores, table dereferences, fault ack, TLB or firmware.
Modes0/1 retain their original mapping/write boundaries.

111focusedtestsPASS plus5return-profile tests; all1125hosttestsPASS in93.009s
(`peripherals-host-tests-v46.txt`). Additional regression for nonzero disabled
hardware-like context state passes49adapter/FDTtests in13.691s. ASan/UBSan
28,974scenariosPASS, including14,619context-mode parent-lease edges.
Local native build `build-20261023-134153.log` and complete real
image/ADT/FDT/return validationPASS.

Fresh authenticated/image/nonce-matched `gpu-context-v1-20261023-134317`
reports GMU0/stage10, SMMU0/stage4/stable1/format1, then context0/stage3,
48reads/completed48/stable1/disabled3/faults0. Both SCTLR.M bits are clear;
other TTBR/TCR/MAIR configuration is nonzero and remains private, never
dereferenced. Disabled is not blank or owned. StaticPID1,verified fastboot
return,HFS clean/unmodified atwrite_count462335. No flash/media operation.

Kernel `4fc20ca23a662c7f67cba169f7004c534de331dfd8d08d388baeb8af5b7bb7fa`;
image `48a6f9fd771b351609f917503bd991208085aae0a2cd9531a6b692417048763b`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinsmmu=2 redfinspmi=1 redfinreturn=1 redfinbootid=0x040221cb6a408414`.

User now requests iOS with Wi-Fi: prioritize native firmware/start/transport.
Retained CX/MSS/XO/AOP power is hardware-proven; PAS4/firmware, SMP2P,
GLINK/WLFW, association/data and iOS network interface are still unfinished.
Do not boot a legacy wifi=1 Sapphire path or claim connection from power.
GPU next is separately owned context/memory, firmware and HFI; no rendering.

## REDFIN GPU-SMMU global hardware snapshot PASS — 2026-10-23

Source dee6f34. Frozen `gpu-smmu-v3` passes real image/ADT/FDT/return
validation and fresh authenticated/image/nonce-matched capture
`gpu-smmu-v3-20261023-123556`. GMU repeats result0/stage10/377reads/20writes,
source200=1/counter=1/restored=1/dirty=0, reset1/INIT0/HFI0.
SMMU reports result0/stage4/guard5,58reads/completed58,stable1/format1.
IDR0/1/2/7=4c017e05/20000005/5511/24:5streamslots,5contexts,4KiBpages,
32KiBglobals,SID15/input36/output36/VA48. CR0=220406,GFSR/syndromes0.
All five SMRs/CBARs/CBA2Rs0; invalid S2CRs are preserved as raw private
evidence, not normalized. Streams4/5 have no active match; unreferenced1f
does not establish ownership. Only global-half reads; no CB/table/route
access or DMA. StaticPID1,verified fastboot return,HFS clean/unmodified
atwrite_count462335. No new native build: uses122808 from dee6f34.

Kernel `8d0a114f9f34434d9f39894af2faa67619180336aa9d4ec165380273f0b34cbf`;
image `727a8692d9a5cac8c44cb0f04ed252cec2ebe704761ccf3eef237364675ec7bb`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinsmmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x452aa2fdebcbdea6`.

Next: explicitly selected read-only context0 inspection using preferred
HackiOS step9 and native register definitions, retaining fresh CX/clocks/
reset/IRQs and bounded return. Do not infer blank or nonsecure context
from globals alone. Firmware/HFI/GPU commands/rendering and Wi-Fi remain
unfinished; all device runs remain temporary md0 boots.

## REDFIN GMU clocked CSR and reset-held TCM hardware PASS — 2026-10-23

Source parent4987f8c. Corrected the native Lito clock-before-CSR order:
configure200MHz and enable the GMU core branch before reading reset,
INIT or HFI. Both GMU access helpers require the running-clock proof;
reset1/readback still precedes counter/TCM, and no reset release is written.
Exact tcm-policy schema2 rejects older ordering contracts. Canonical C,
overlay, Python and prepared native sources match. Fixtures now reject all
GMU accesses with the core clock off, rather than requiring reset before
clock enable.

Observed:105focusedtestsPASS; all1119hosttestsPASS in101.796s, including the
private Wi-Fi bundle (`peripherals-host-tests-v45.txt`); ASan/UBSan
14,278adapter scenariosPASS. Local ARM64 build `build-20261023-122808.log`
links successfully. Complete real image/ADT/FDT/return validationPASS.
Fresh authenticated/image/nonce-matched capture
`gmu-tcm-v8-20261023-123214`, boot ID977293c7cbd9f5bb, reports result0/stage10:
377reads/20writes/8polls, source200=1, counter=1, restored=1, dirty=0.
Reset1→1, INIT/HFI0; crystal delta28627 over1490989ns.
Both DTCM patterns read back and original words restore; staticPID1 lives.
Collector verifies fastboot return; HFSX remains clean/unmodified at
write_count462335. No firmware, CM3 release, GX, DMA, flash or media write.

Kernel `8d0a114f9f34434d9f39894af2faa67619180336aa9d4ec165380273f0b34cbf`;
image `20ea232e50ec6efc354b9db2affa2887f8d94ca579f020b06481763c728b4328`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x977293c7cbd9f5bb`.

Next: a freshly frozen `gpu-smmu-v3` image on this exact kernel repeats
the TCM proof then reads only the GPU-SMMU global half. Earlier v2 predates
this clock order/schema and must not be booted. Context ownership, firmware,
HFI, GPU commands/rendering and Wi-Fi activation remain unfinished.

## REDFIN GMU enters real hardware; source-backed cold clocks — 2026-10-23

Source13197c1 fixes the diagnostic IRQ key. Fresh authenticated v6 capture
1fca65afc80113a7 passes InitIOKit, startup extensions, PID1, held-CX proof and
enters GMU. Preflight reports result35/EAGAIN/stage1/15reads/0childwrites:
GPLL0 MODEd810003d/L31/USER103/ALPHA4000, GPU_MISC0, GMU branch80004220.
This is a successful localization, not GMU execution or TCM proof.

The pinned gcc_lito_probe sets GPU_MISC lowbits3 before preparing feeds;
its fixedGPLL0/even feed does not require the unused third output. Root now
RMWs only GPU_MISC bits1:0, verifies readback and rechecks it during source
proof; accepts main/even USER103 while preserving all PLL configuration.
The enlarged exact ADT clock-policy binds offset/mask/value and USERmask.
105focusedtestsPASS, including cold states/readback failure; all1119hosttests
PASS in101.376s (`peripherals-host-tests-v44.txt`),14,278ASan/UBSan adapter
scenariosPASS. Native ARM64 build122118PASS, real payload/ADT/FDT/returnPASS.

Fresh authenticated v7 capture f056133cffd0b238 completes those GCC/bus votes
and reaches the first GMU SYSRESET read at0x03d7e000, where the log stops.
No CPU panic or PID1; automatic bootloader return/recovery succeeds. Current
leaf tries that CSR before enabling GMU core clock. Native kgsl_gmu.c
(gmu_enable_clks) and preferred HackiOS step5 enable core clock before CSR
inspection. Next is to correct that ordering with fresh CX/source/IRQ gates,
never write a reset-release/firmware/SMMU table, and keep watchdog return.
All HFS header observations remain clean/unmodified atwrite_count462335.
No flash/media/Android boot or per-device artifact was committed.

Rechecked preferred sources: kernel8e611870 unchanged; userland HEAD is now
a79ff0772a3454fd1ef127e181e5b3bce6c9ce18. Reviewed thermald/bootok/thermal_probe
changes are recorded in UPSTREAM.md; no graphics backend/16.7ABI fix is present
or installed. The old pinned worktree is retained for comparisons.

`gmu-tcm-v6` local `build-20261023-121348.log`; kernel `ed2cc8d17a5d7f00c43721ae1c892747aeec4d05c5564c266f2649fd0f1497ac`; image `2db58fd554fd4989c4118630bc71b72cca9cc4871bc948d997c450345cc6cc1b`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x1fca65afc80113a7`.

`gmu-tcm-v7` local `build-20261023-122118.log`; kernel `9c8dbfc3ddfa8116dbc142ca8a1f6f26cdc1d0f3d0ba80f58987b19b2a951293`; image `1b268be61c25372a0f04e5fe76273990bb54a4272cab89089c6f6cda08e3ad87`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xf056133cffd0b238`.

## REDFIN Wi-Fi power hardware PASS; GMU IOKit root cause fixed — 2026-10-23

Source parentdab3c2c. Authenticated/image/nonce-matched SCM615a203339d75f5f
selects64-bit ABI; five PAS-function availability queries return status0/value1
in one call each. PAS_SUPPORTED4/13 returns status0/value0: no positive firmware
support claim and no INIT/MEM_SETUP/AUTH_RESET/SHUTDOWN/assignment issued.
Static PID1, no panic, clean HFS header and verified fastboot return PASS.

Authenticated/image/nonce-matched Wi-Fi4a14fbcc4f02878b power test PASS:
CX7/MSS6/XO3 complete in1/3/4polls; allIRQ1/CMD0x10101. Native AOP opens,
modem-on acknowledged,21stores/4notifications/pending0. Final result0/phase4,
held_mask7,64writes/quarantine0; votes/channel retained until reset. PID1 lives;
fastboot return and unchanged HFSX clean_unmounted=true/inconsistent=false,
write_count462335. No PAS/SMEM/firmware/media operation. Association/data and
firmware activation remain unfinished.

GMUv3 reproduces the early stop on the USB-proven053033kernel/29sbark.
Progress build114947/v4 proves PE image/progress setup completes and execution
enters InitIOKit, then stops before return. Source review finds the diagnostic
leaf's plain `interrupts` is consumed by IODTMapInterruptsSharing during registry
import; IODTMapOneInterrupt does not advance when its root parent has neither
interrupt-controller nor map. This is before GPU startup, not a GMU result.
Root renames only the two private ADT IRQ metadata keys to `gic-intids`, keeps
native Linux interrupt validation/IRQs and all MMIO contracts unchanged.
C/Python/overlay and actual-adapter fixtures match;103focusedGMUtestsPASS.
Both builders include bounded CPU-only preinit/IOKit progress markers for
isolated GPU/Wi-Fi/SCM selectors. Builds121042/121348PASS. Corrected v6 is
running; v5 was prepared only and not booted. Earlier v2..v4images retain the
bad metadata key and must not be reused. Host full regressionv43is running.
All device runs use temporary fastboot boot/md0; no flash or root write.

`scm-query-v2` build `build-20261023-053033.log`; kernel `2ba70c080e479452574f626998d68844e65747bf40a3992de690c2c7443153c7`; image `b278b2b9ab21957a5702d78b72da267a43a86190181c1af608b717e9a91637ca`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=3 redfinscm=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x615a203339d75f5f`.

`wifi-power-v2` build `build-20261023-114947.log`; kernel `8c799db20ebf5f2ec6941bdab5d40b2d6b7dafd845e09bd27a2df5ad0cb70a03`; image `5d694ae5d3fab0359087e81714d34e746dbea16cdcc535fe66892e5bebc65e0f`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinwifipower=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x4a14fbcc4f02878b`.

`gmu-tcm-v3` build `build-20261023-053033.log`; kernel `2ba70c080e479452574f626998d68844e65747bf40a3992de690c2c7443153c7`; image `6269b200eeaffa8b6cf1be9f84d5d129ef338dc6a58e3a0ed22e3be0efbea162`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xe9bc976fb20e5740`.

`gmu-tcm-v4` build `build-20261023-114947.log`; kernel `8c799db20ebf5f2ec6941bdab5d40b2d6b7dafd845e09bd27a2df5ad0cb70a03`; image `a3c23b34e365bbace4ea0d64b1ff8248b845ce22f81b912ab94b685a4df081d9`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x9c783462e7e20fef`.

`gmu-tcm-v6` build `build-20261023-121348.log`; kernel `ed2cc8d17a5d7f00c43721ae1c892747aeec4d05c5564c266f2649fd0f1497ac`; image `2db58fd554fd4989c4118630bc71b72cca9cc4871bc948d997c450345cc6cc1b`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x1fca65afc80113a7`.

## REDFIN access restored; USB TX completed on hardware — 2026-10-23

Source11fcd6e. User returned the device to fastboot. Temporary safe recovery
`gmu-tcm-rescue-20261023-113632` observes journaled16GiBHFSXv5 with clean_unmounted=true,
inconsistent=false, write_count462335; a header observation does not certify
all filesystem contents. Existing4MiBRAM and4096-byte metadata were saved,
but AES-GCM authentication failed: no old plaintext or GMU outcome is accepted.
The ordinary collector refused priming and returned to fastboot. After verifying
both saved hashes, an explicit RAM-only public-key bootstrap uses the existing
verified Cycle helpers in `ramoops-reprime-20261023-113829`; it also preserves
that recovery's raw bank/metadata, verifies root/no mounts/no swap, pushes only
the public key and pinned vendor executable, and verifies the cleared AES block.
No private key was sent; no disk partition/mount/flash/Android boot was requested.
The automatic collector's authentication policy is unchanged.

USB image `usb-net-v8` SHA256 `2895eb16616ce214ae0204e9b7f4ca64ddbaa470c11c2b0c031bca0da2b0c1ab`;
local build053033/kernel `2ba70c080e479452574f626998d68844e65747bf40a3992de690c2c7443153c7`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xa559cbffdc50dfc9`.
Fresh authenticated/image/nonce-matched `usb-net-v8-20261023-113935` observes
staticPID1, submitted78/completed78frames/17485bytes, expected lease timeout60
(ETIMEDOUT), owned halt1 and retained slab, then verified fastboot return.
No panic; HFS header/462335write_count unchanged. Native ECM `en9` has ARP and
14209bytes UDP text, but no solicited nonce echo/boot-ID marker: host status
probe-incomplete. Many empty IOService snapshots are recorded. This proves
actual checked TRB completion and some USB traffic, not the full native-host
freshness/ACK protocol or combined USB/GPU operation.

GMU `gmu-tcm-v2` image `5cd7789a5d40307ecfb098bac337cbe981ac029f3a14eb095d10db4f911d16f5`,
local build051157/kernel `03949cc195ff69f121e318e6c9729501f4cb5acbc5c421f4b9f234a13cd711f3`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x510d59111137311b`.
Fresh authenticated/image/nonce-matched `gmu-tcm-v2-20261023-114224` returns
automatically, but its log ends after iBoot Stage2, before any GPU/GMU marker
or PID1; no panic line. No GMU hardware result can be inferred. HFS header
remains clean/unmodified. A fresh same-profile image on the newer USB-proven
kernel with the hardware maximum29s bark is being tested to distinguish a
stale build/early-boot issue. Watchdog range remains10..29s; shim prearm only
sets the verified bootloader reason, not a separate longer watchdog.

## REDFIN final regression and checked USB TX image prepared — 2026-10-23

Source8c99cfc links the resident Wi-Fi firmware mechanism and fixes the ADT
module collision; Wi-Fi357ca9f and USB protocolc3a9a06 are included. The new
USB completion overlay now requires the same live lease, synchronized exact
normal TX TRB, released HWO, zero residual/success status and no BUSERR/SHORT
before reusing its DMA buffer. Errors retain the in-flight allocation/queue
for the existing owned stop; legacy behavior is preserved. Eight tests execute
actual queue/event handlers, including wire padding, duplicate events, malformed
TRBs and pre/post-sync lease loss. Separate submitted/completed counters are
logged. Exact per-marker receipt tagging/RX ACK/coordinator remains unfinished;
this does not enable live GPU logging or combine standalone USB/GPU profiles.

Observed: all1117hosttestsPASS in61.757s, including the real private firmware
bundle (`logs/redfin/peripherals-host-tests-v42.txt`); no skipped private cases.
Local ARM64 build `build-20261023-053033.log` links successfully; kernel
`2ba70c080e479452574f626998d68844e65747bf40a3992de690c2c7443153c7`.
Prepared `usb-net-v8` image `2895eb16616ce214ae0204e9b7f4ca64ddbaa470c11c2b0c031bca0da2b0c1ab`.
Exact intended args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xa559cbffdc50dfc9`.
The real complete payload/ADT/liveFDT and host return-policy validation PASS;
image/kernel/build/validation snapshots are frozen locally. This image is NOT
booted; neither new TX completion nor firmware ingestion has a hardware result.

Fresh host observation: one unauthorized ADB device, no fastboot. The running
OS and current HFS state remain unknown. The already bounded passive rescue
waiter still waits only for the matching fastboot identity, then collects old
RAM/reads HFS through verified temporary recovery; no new XNU is scheduled.
No device boot, flash or media write occurred in this milestone. Hardware
progress needs a return to fastboot; recover the failedGMUboot's existing RAM
before any new XNU, inspect HFS before another RW GUI, then use the frozen
prearmedGMU test. GPU execution/rendering, Wi-Fi PAS/GLINK/WLFW/association/data,
combined live diagnostics and physical90Hz remain unfinished. Screen/cutout fit
and eight-core touch retain their earlier documented hardware evidence.

## REDFIN firmware source linked; USB delivery protocol prepared — 2026-10-23

Wi-Fi source357ca9f adds immutable resident firmware ingestion, native read-only
mapping and staged copy/readback without UFS/PAS/startup. Root includes its
three source/dependency overlays in both builders. Local full ARM64 build
`build-20261023-052239.log` links successfully; kernel
`58172b861adf0de271fe9ab4360a61530f5023a97406cb56b2c5ba50c7afcf70`.
No new image or boot args were emitted; no device/media operation was issued.
The actual private bundle passes the native CPP/guarded host-copy path:
9420metadata,99,384,626payload and191,553,563BSS bytes;35PHDR/33loads/31assets.
The private12-segment116,933,776-byte payload passes the real C loader, but
ABL download/decompressed placement and native firmware activation remain
unproved.133focusedWi-Fitests passed at source handoff. Full-suitev41 then
found two fixture setup errors from tools/mkadt shadowing the board module;
root fixed script-mode module resolution and added a real shadowing regression.
All28firmware-ingestion/packer/native-adapter tests, including private cases,
pass afterward. Final common regression is pending the USB TX correction.

USB sourcec3a9a06 adds an independent nonce/cookie/sequence-bound delivery
protocol and host codec;17focusedtests plus sanitizers pass. It requires an
actual completed90-byte DWC3 frame and matching host ACK, with10s readiness,
500ms marker deadline,16markers/badACK bounds and no lease extension. The
core is deliberately not a startup hook/coordinator or a combined GPU profile.
Transport still needs exact successful TRB completion/tagging and RX receipts;
root is correcting the existing event handler's unchecked TX completion first.
No claim of autonomous live GPU logs or GPU rendering is made. The passive
device rescue waiter still reports waiting-fastboot; ADB authorization and
the failedGMUboot's existing RAM/HFS remain unresolved. Next: final host/native
checks; collect old RAM/HFS before another temporary XNU boot when accessible.

## REDFIN optional RO SMMU image and GMU breadcrumbs prepared — 2026-10-23

Source cddcb54 binds opt-in redfinsmmu=1 to the exact GMU1 mode. The full
native64KiB SMMU/clock/IRQ/stream ADT is checked before parent ARC writes;
snapshot requires this call's successful reset-held GMU and fresh parent/
source/reset/clock/IRQ proof before each explicit scalar LDR. Only the
0x8000 global half is mapped; no CB pages/TCU/TBU/TLB/fault acknowledgements,
route writes, table install, firmware execution or ownership claim. First
GMU accesses and restoration now have bounded pre-access breadcrumbs.
Observed offline:116focusedGPUtests,42adapter/FDTtests,13,558sanitized
scenarios and private nativeARM64-Werror object/disassembly PASS. Root's
native build `build-20261023-051157.log` links successfully; common parent9,
builder30 and prearm5 focused tests PASS. The unresolved043115 run still has
no fresh log and no hardware GMU/SMMU success is inferred.

Prepared `gmu-tcm-v2` kernel `03949cc195ff69f121e318e6c9729501f4cb5acbc5c421f4b9f234a13cd711f3`; image `5cd7789a5d40307ecfb098bac337cbe981ac029f3a14eb095d10db4f911d16f5`. Exact intended args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x510d59111137311b`. Real complete payload/ADT/liveFDT plus compiled shim/kernel return policy PASS; not booted.

Prepared `gpu-smmu-v1` kernel `03949cc195ff69f121e318e6c9729501f4cb5acbc5c421f4b9f234a13cd711f3`; image `595c4c101d35bf23a7740fa98d36afe93e79b310916998220599be257b30a99b`. Exact intended args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinsmmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x5d19401c742f912f`. Real complete payload/ADT/liveFDT plus compiled shim/kernel return policy PASS; not booted.

USB source231e732 now propagates Redfin log-worker creation failure to the
existing sticky gadget error/owned-quiesce path. Four actual-source injection
tests PASS: preserve active slab/routes if halt is denied, never free in-flight
DMA, no retry. Normal and legacy optional-logger cases are preserved.
Prepared source plus both builders include the additive patch after the USB
network worker. Root native build `build-20261023-051524.log` succeeds; no
new USB device test or host-ready/combined GPU profile is claimed. Independent
nonce-bound host ACK/flush work is ongoing; existing strict separate USB/GPU
gates remain in force. Preferred oosexgang upstream HEADs rechecked and
unchanged. The passive rescue waiter still has no matching fastboot event.
Next: collect pre-existing RAM/HFS when fastboot is available; then use the
new prearmed GMU image for real evidence before RO SMMU or table publication.

## REDFIN GMU attempt unresolved; autonomous device access unavailable — 2026-10-23

Source `3bd5dc8`/GMU`ab1f463`; local ARM64 build
`build-20261023-043115.log` succeeds. Kernel
`1b55eb66f3683cb41cf3acf12f774b5603ecfa38421ee83f75edd9193817d026`, image `gmu-tcm-v1`
`85dc0fb1edfdec36bdc587dfe63adc15a15a79c2fda28dda018cc74da0b1b953`. Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfingmu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xf7be2de3bdd0e7b9`.
Temporary fastboot boot was accepted. Collector waited360s and recorded
no-log/no-fastboot: XNU outcome is unknown. No fresh XNU/GMU capture exists.
USB subsequently reports Google Pixel5/ADB unauthorized; this does not
establish the running OS. Host ADB restart did not authorize it, and the
safe reboot-to-bootloader request was rejected by ADB authentication.
No recovery image was sent after this failure. Current on-device HFS state
is unobserved; no claim is made that GMU clocks/counter/TCM succeeded.
Host backups, frozen kernels/images and prior authenticated logs are retained;
no flash/media operation was issued by this md0 experiment. User is asleep;
no physical screen/USB authorization or reset has been requested.
Next when fastboot becomes available: temporary safe recovery, collect the
existing encrypted RAM before any new XNU boot, then read/verify HFS header
before another RW GUI run. Do not boot Android without restoring its backup.
Offline work continues; future GMU adapter will log critical access breadcrumbs.
A bounded private host waiter now watches only the already-known device's
fastboot identity for2hours (`logs/redfin/rescue-wait/`). If available, it
boots only the verified offline recovery, collects the pre-existing RAM and
reads the HFS header using `--observe-rootfs`, then returns to fastboot.
It sends no XNU image and does nothing to an unauthorized ADB environment.

## REDFIN pre-kernel return and query/power images prepared — 2026-10-23

New isolated UP GPU/GMU/native-Wi-Fi/SCM builds automatically compile the
already-proved CPU0 shim prearm leaf before payload/ADT/kernel checks, while
retaining redfinspmi=1/redfinreturn=1 and the kernel's return verifier. The
host recovery cycle checks exact compiled gates/config hash, diagnostic
selectors, frozen args, md0/no-writer policy and nonce; old modern-probe
images without this prearm are no longer admitted. Five prearm policy tests
and30buildertests PASS; original shim/UP/SMP/GUI guards remain separate.
This is software hardening after the unresolved boot; no new device result
for these combined profiles is claimed.

New query-only SCM engine follows pinned native legacy scm.c ABI detection,
standard call availability and PAS_SUPPORTED4/13. It preserves interrupted
resume cookies, bounds retries/deadline and enforces its query-only allowlist;
no firmware init/auth/reset/shutdown/assignment. Five actual-engine tests
PASS; local full ARM64 build `build-20261023-045451.log` succeeds. Wi-Fi
`80dc3cd` supplies cold SMP2P/lifecycle under trusted ops; `e74fa90` adds
retained CX7/MSS6/XO3 and native AOP modem-on,106focusedWi-Fitests/private
nativeARM64 compile PASS. Neither new power nor SMP2P has run on hardware.
GPU `d2e5ef5` readonly64KiB global SMMU snapshot and `8d53e19` CPU-only4KiB
page tables remain unwired:93focusedGPUtests, nativeprivate-Werror and403
sanitized scenarios PASS. These do not prove SMMU ownership or firmware start.

Prepared `scm-query-v1` kernel `46e3eeb6500d48f526a0c1cda3f6777fee9953ab7c3665e6709334efd0859c8f`; image `5c39900434a27cbdb835879851d5c5e58de67fbcc812a24829a93ae2b56c8db5`. Exact intended args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=3 redfinscm=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x8e18ecd81e118bf4`. Complete real payload/ADT/liveFDT and shim+kernel return policy PASS; not booted.

Prepared `wifi-power-v1` kernel `46e3eeb6500d48f526a0c1cda3f6777fee9953ab7c3665e6709334efd0859c8f`; image `b391c1c7af749d3ece684f788b02759118530ff4eb8bfc22fe56c6ba77c8fa1c`. Exact intended args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinwifipower=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x3428f9031ee4f9f5`. Complete real payload/ADT/liveFDT and shim+kernel return policy PASS; not booted.

Unfinished: recover device access/old RAM, fresh GMU result and optional RO SMMU probe; native SCM capabilities, Wi-Fi power/SMP2P/PAS4/GLINK/WLFW, association/data; GPU firmware execution/commands/rendering and physical90Hz.

## REDFIN native Wi-Fi prerequisite hardware proof; GMU chain integrated — 2026-10-23

Native AOP/platform source `be1f813`, read-only observer `f8647a4`, root
startup mode2 integrated separately from the legacy SMEM observer. Local
ARM64 build `build-20261023-042051.log` succeeds; kernel
`f415d7bfc871f61829945abf6e89c20ac79c6f7d9004b4de0ffa228094eae9f3`, image `wifi-native-v1`
`ada57c8232e0f41fbd63bc03683029429f49b5ee5ec65f521289cd3099ad3a7e`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x87e3064b3486920f`.
Authenticated/image/nonce-matched `logs/redfin/wifi-native-v1/`:
AOP magic0x4d41494c/version1/features0/reserved0; ucore link0xffff,
ack/channel/channel-ack0xffff0000, box0xc0/104bytes; mcore all four link/
channel words0xffff0000, box0x128/728bytes. Stable observation succeeds,
TX/RX lengths0; no channel open, messages or notifications. SMEM has14
partitions, modem partition0xfb000+0x7c000,0uncached items/GLINK0.
Fresh CMD-DB type3/version0x1000/32-byte tables: xo.lvl address0x300a0,
levels[0,32,80,128] followed by12zeros; cx.lvl address0x30000,
[0,16,64,128,192,256,384,416] followed by8zeros; mss.lvl address0x30060,
[0,64,128,192,256,320,384] followed by9zeros. TURBO384 selects6 for CX and MSS. The native AOP
channel matches the coherent-cold handshake expected by the transport.
All maps read-only; no PAS, power, IPCC, SMEM or media writes. Static PID1
has11heartbeats, no panic; authenticated metadata priming and fastboot return
pass. This does not establish modem startup or Wi-Fi scan/association/data.

GMU adapter `ab1f463` now integrated after held CX proof, with its exact
live-FDT/ADT/CPU0/md0/IRQ/return contract checked before any parent power
write. Child receives original frozen args/context and synchronous held-parent
callback; failures or late changes block entry. Four actual-parent glue tests
PASS;61GMUtests include firmware/TCM/adapter/FDT, private actual-XNU ARM64
-Werror compile and ASan/UBSan. Root native build is running; no physical
GMU clock/counter/TCM result or new GMU boot args yet. Full host suitev40
passes962tests (`peripherals-host-tests-v40.txt`), including corrected Wi-Fi
header parity. Next: temporary isolated GMU test and native Wi-Fi retained
CX7/MSS6/XO3/AOP transport stage; no firmware/authentication started yet.

## REDFIN automatic cutout GUI capture passes — 2026-10-23

Source integration `6afc7d8` and geometry `6074350`/checker`7be93bd`.
Local ARM64 build `build-20261023-040928.log`, kernel
`4dc8591629151472438fc8f94ff7b2d089f32f106d5299264f3c3fa6526d2384`;
image `gui8-cutout-v1` SHA256
`ac428885d06d4a49362757288625e0b83ece1666c8a4a690f07b2aa75db660be`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfit=2 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=60 redfinscreen=1 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0x0c92c3566fe971d1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Authenticated/image-matched `logs/redfin/gui8-cutout-v1/`:8/8 CPUs, Apple
userspace, exact FB/HID inverse viewport31,136/1017x2204. Three CRC-checked
captures at presents1,5,14; all3515 camera/side-margin samples black in each.
Final thumbnail visibly contains the iOS lock screen inside the viewport.
Touch worker finishes error0,1463batches/0contacts/0releases/0overflows; user
was asleep, so physical touch/calibration and throughput were not tested.
No panic;180s graceful shutdown, journaled HFSX clean_unmounted=true and
inconsistent=false, authenticated metadata priming, verified fastboot return.
The capture validates RAM placement/exclusion, not physical panel corners or
measured FPS. GPU acceleration and physical90Hz remain unfinished.
Next: source-backed reset-held GMU probe and native read-only AOP/SMEM/CMD-DB
Wi-Fi prerequisites. Source milestones be1f813/f8647a4 pass70focusedWi-Fitests;
full host suitev39 ran925tests with924PASS and one transient header/overlay
comment-parity failure while Wi-Fi files were edited; the70focusedrerun
includes that corrected parity check and passes.

## REDFIN CX power passes hardware; fitted GUI capture running — 2026-10-23

The new separate CPU0/md0 CX experiment passes authenticated image-matched
capture `logs/redfin/gpu-cx-v1/`, bootID d53638ba274b9712. Local ARM64
build `build-20261023-040531.log`, kernel `913a661bb551f2f563713d7fe92969212c356758e67a89eb81b3d26f7c161017`;
image `0926415de93157514db2fb9ad8ac2ca3ac28126ca1cf09a057ff9c5caed3460c`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfingpu=2 redfinrpmh=1 redfingpupower=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xd53638ba274b9712`.
Observation: ARC selector7/corner416 completes in1poll, IRQ1/CMD0x10101;
CX control0x222001 becomes0xf8222000, separate HW status0x80001fe0/on1.
Parent remains held; no GX/GMU/SMMU/firmware/DMA operations in this test.
Static PID1 has11heartbeats, no panic; recovery authentication, fresh nonce,
metadata priming and final fastboot return all pass. This proves CX power,
not a GPU command or graphics acceleration. Five actual-leaf host tests cover
metadata/ownership/handoff/transaction/domain failures; next is a separate
reset-held GMU clock/counter/TCM probe after this fresh held-parent proof.

Display commits `2893537`, `6074350` fit the full1125x2436 iPhone canvas and
inverse touch to sourced Redfin viewports; mode2 puts1017x2204 at31,136 below
Google's front-camera exclusion. Nine geometry host tests PASS. The native
OSObject16KiB-size failure was fixed by separately allocating the workspace,
with allocation-failure cleanup and final free. `7be93bd` adds an automatic
RAM margin/content checker (5host tests), requiring the exact FB/HID fit logs
and CRC-checked samples; physical calibration is not claimed. Root integration
admits the existing optional screen capture only in strict cutout GUI8;
C/Python/real-loader and capture-manifest parity tests PASS (9GUItests).
Local build `build-20261023-040928.log` succeeds; cutout image
`ac428885d06d4a49362757288625e0b83ece1666c8a4a690f07b2aa75db660be`, kernel `4dc8591629151472438fc8f94ff7b2d089f32f106d5299264f3c3fa6526d2384`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfit=2 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=60 redfinscreen=1 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0x0c92c3566fe971d1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Complete payload/ADT/liveFDT plus host return policy PASS; temporary GUI boot
and autonomous capture are running. No physical gesture is requested.

Other completed source milestones, with no device startup yet: GMU firmware/
HFI `de80451`, reset-held clock/TCM `13f403b`, corrected separate CX hardware
status guard `52137f3` (22firmware+18TCMtests); native MPSS/PAS4 planner
`05f371f`, AOP transport/platform binding `be1f813` (60Wi-Fitests). Wi-Fi
association/data and GMU firmware execution remain unfinished. Preferred
HackiOS upstream HEADs are unchanged and recorded in UPSTREAM.md. Next: collect
cutout GUI result, integrate source-backed GMU adapter and native read-only
AOP/SMEM/CMD-DB observer; keep serial temporary boots and all backups intact.

## REDFIN repeat60Hz touch session passes; next GPU and geometry — 2026-10-23

Source `ddff37b`; local ARM64 build024851/kernel
`9e64446032a61cad8fdefc1057cf61a9830b962b3b027101718cdf7839c6c576`.
Image `gui8-60hz-touch-v2` SHA256 `ea43b29ff0ed8f2c2c9f30ccc24be28ca77905fb7eecc1a4c317e0416cfdd7d3`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=60 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0xa886a8a1c2c18f12 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Authenticated/image-matched capture:8/8 CPUs,60Hz copy setting, Apple userspace
and180s HID session.4205batches/114contacts/114releases; stopped error0,
overflows0/recovered0. User confirms touch continues working after the previous
failure point. No panic, clean journaled HFSX/unmounted=true/inconsistent=false,
metadata primed and fastboot return verified. Real clear command was not
exercised in this run; recovery behavior is currently covered by host tests.
User now requests overnight GPU work, full-screen fit and front-camera cutout
handling from HackiOS. Primary most-stable upstream source preference recorded
in AGENTS/README/UPSTREAM: oosexgang/hackios-xnu-kernel and
 oosexgang/hackios-xnu-userland, as explicitly designated by the user.
Next: refresh upstream review, inspect geometry/cutout support and A620 power/
GMU/firmware/SMMU prerequisites; maintain temporary boots and intact backups.

## REDFIN source-backed touch overflow recovery prepared — 2026-10-23

Adds `touch-overflow.patch` after GUI8. Pinned native SEC code at
`0701b191882dc408104ad8af9e2f5eb2bf34c297` uses0x62/CLEAR_EVENT_STACK on
remaining-count>31 (`sec_ts.c:2337..2350`, `sec_ts.h:244`). Queue-full status
ID1 is separately recognized; other IC errors/reset/malformed packets remain
fatal. Runtime overflow releases active contacts, logs the raw event, issues
one exact volatile8-byte clear only in the open/sensed session, then discards
at most4batches until empty before new DOWNs. No transport retry or reopen;
max8clears/boot. Lease/HID/GIC/GPIO checks precede clear and each drain read.
Full817 host tests PASS (`peripherals-host-tests-v37.txt`): exact frame and
64single-bit corruption negatives, pure state/held-contact recovery, lost
ownership/consumer/transport/reset/persistent overflow, bounded session clear
API and actual worker survive-overflow/failed-clear tests. ARM64 build
`build-20261023-024851.log`, kernel SHA256 `9e64446032a61cad8fdefc1057cf61a9830b962b3b027101718cdf7839c6c576`.
Image `gui8-60hz-touch-v2` SHA256 `ea43b29ff0ed8f2c2c9f30ccc24be28ca77905fb7eecc1a4c317e0416cfdd7d3`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=60 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0xa886a8a1c2c18f12 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Complete payload/ADT/liveFDT and host recovery-cycle policy PASS.
Observation: software validation complete, new clear command untested on
hardware; previous60Hz root is clean and phone verified in fastboot.
Next: temporary8-core60Hz GUI touch session and authenticated collection.

## REDFIN GUI8 60Hz boots; touch stops on queue-count overflow — 2026-10-23

Source `69ff90f`; local ARM64 build023513/kernel
`751fa8c92727db9e143162e2b64a9af1ec43bf252aafe553049feb14dd485afa`.
Image `gui8-60hz-v1` SHA256 `3faa038180a81e9212354c428cb6716744348f1eb3ca8da942b0a36aec718b7c`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=60 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0x6ff7bad8f1b964be redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Authenticated/image-matched `logs/redfin/gui8-60hz-v1/`:8/8 CPUs,60Hz copy
configuration, Apple userspace and180s HID session start successfully.
User observes smoother UI, then lost input/possible freeze and artifacts.
Observation: after381 batches/12 contacts/12 releases the event worker
stops with Darwin84=EOVERFLOW. Existing parser returns this for a reported
remaining-event count>31; raw offending bytes were not captured. Rendering
continues to at least CPU present120 after the stop; kernel does not panic,
and180s graceful shutdown, clean HFSX and verified fastboot return succeed.
Thus input stopped independently of the kernel/display; actual queue overflow
versus an invalid count is not yet distinguished. Artifacts have no proven
cause (CPU scanout synchronization and missing GPU features remain candidates).
Next: compare pinned SEC source's overflow handling and implement bounded,
source-backed queue recovery without relaxing SPI/ownership/media fences.

## REDFIN GUI8 60Hz comparison prepared — 2026-10-23

Preserves proven GUI8 10Hz and admits only10/30/60Hz copy profiles; duplicate,
unknown and mismatched manifest cadences fail. The Redfin driver allows30/60
only in strict GUI8, retaining the unchanged60Hz software notification clock.
This does not program the panel's90Hz mode or claim measured60FPS.
Root and framebuffer now parse the strict mode before using their cached
latches, removing dependence on CPU-nub matching order. Touch default is180s
in GUI8 and remains120s in UP. Full810 host tests PASS
(`peripherals-host-tests-v36.txt`), including final real loader/ADT/liveFDT,
shared-header equality, late selection/binding/return negatives, cadence and
old2/8-core profile regressions. Local ARM64 build `build-20261023-023513.log`,
kernel SHA256 `751fa8c92727db9e143162e2b64a9af1ec43bf252aafe553049feb14dd485afa`.
Image `gui8-60hz-v1` SHA256 `3faa038180a81e9212354c428cb6716744348f1eb3ca8da942b0a36aec718b7c`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=60 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0x6ff7bad8f1b964be redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Hardware60Hz comparison pending; previous10Hz GUI8 capture is clean and phone
is in verified fastboot. Next: temporary60Hz boot and authenticated capture.

## REDFIN iOS GUI and SEC touch work on all8 CPUs — 2026-10-23

Source `dc036d4`; local full ARM64 kernel build022643/SHA256
`ae14e146c388373ce7949b5973331183f902a703d1b479e33c75e8ae4455d31f`.
Image `gui8-v1` SHA256 `9e8f2c8d24b5c443fe663cbf32e4832d6068c297ebfe1f6fc23a03e7e35729ab`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=10 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0xba3e7592606a0f91 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Authenticated/image-matched `logs/redfin/gui8-v1/`: actual RO return proof
APID210/PON4/IMEM0x77665500,8/8 CPUs initialized with SGI1, Apple PID1/system
domain/boot tasks, SEC ID and HID worker all succeed.72 physical contacts
and72 releases; no panic.180s graceful shutdown completes; recovery sees
journaled HFSX clean_unmounted=true/inconsistent=false, metadata is primed,
and verified fastboot return succeeds. This is the first confirmed all8
Apple userspace/touch run. User observation: works very quickly compared
with previous single-core UI. No measured FPS or targeted TLB test is claimed.
User asks why10Hz on90Hz panel:10Hz was the CPU-copy limit, not panel capability.
Next test raises only GUI8 copy cadence to60Hz (software notification remains
60Hz; physical90Hz mode/vblank and GPU are still unimplemented). Extend GUI
touch's default session120→180s and make the root/display SMP gate independent
of asynchronous IOKit matching order. Existing10Hz mode remains available.

## REDFIN GUI8 integrated; device test next — 2026-10-23

Extends proven SMP8 (`65c9682`) with a separate exact GUI8 contract:
8 CPUs, 10Hz CPU display, touch, fenced RW HFS root and 180s graceful
shutdown. The complete IRQ/timer/progress proof and CPU publication precede
root/peripheral writes. CPU0 owns touch/RPMh/shutdown; the BSD root thread
restores its previous affinity before Apple userspace. SMP's actual cached
read-only PON/IMEM proof supplies rail observer mappings, without setting the
old UP return latch. USB/Wi-Fi/GPU stay off. Loader/host cycle require their
own compiled GUI/shim/count gates and known display/touch/UFS ADT leaves.
Full810 host tests PASS (`peripherals-host-tests-v35.txt`); actual complete
payload/ADT/liveFDT passes C loader and host return policy. Local full ARM64
build `build-20261023-022643.log`, kernel SHA256 `ae14e146c388373ce7949b5973331183f902a703d1b479e33c75e8ae4455d31f`.
Image `ports/redfin/out/gui8-v1/redfin-xnu.img` SHA256
`9e8f2c8d24b5c443fe663cbf32e4832d6068c297ebfe1f6fc23a03e7e35729ab`. Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfingui=1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=10 redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinbootid=0xba3e7592606a0f91 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Observation: host/build/loader validation only; eight-core Apple userspace,
touch, performance, clean shutdown and TLB shootdowns remain unverified.
Next: temporary GUI8 boot with authenticated recovery capture, then compare UI.

## REDFIN all8XNU cores pass isolated scheduling/IRQ test — 2026-10-23

Eight-core extension preserves the working2-core profile and uses natural
physical/logical CPU0..7 affinity0x000..0x700. Each distinct live-FDT L2
keeps a separate logical cache ID; L3 is shared, sizes unspecified.
Kernel local full ARM64 build `research/redfin-build/build-20261023-020056.log`,
SHA256 `44b38fd5a934d179c2e4d829d13ae4d79a6eef6ed2896740c61f31d6799ba4a2`.
Image `ports/redfin/out/smp8-v1/redfin-xnu.img` SHA256
`62762312bb1e9b4c8c2401ee804dd168b6c14f4308b3c8261e32890a852ad020`.
Exact args: `debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfinbootid=0xdf8acf043e7907ef`.
Full798 host tests PASS (`peripherals-host-tests-v34.txt`), including
real8pthread proof, missing IRQ/timer/return/binding/logger negatives,
2-core regressions, allCPU ADT mutations/handle uniqueness, native ARM64
backend/trampoline and actual GCC relocation tests. Complete generated
payload/ADT/liveFDT passes actual C loader and count-bound host return policy.
Authenticated/image-matched `logs/redfin/smp8-v1/`: RO PON/IMEM proof succeeds;
all8 enter XNU with SGI1. CPU0 progresses224; CPU1..7 each32. Timer counts
4258/99/706/1313/1919/2528/3273/3982. Each core self-SGI2 passes; CPU0 has
bidirectional unique-sequence exchanges with every secondary. All workers
inactive/IRQ observers drained, logger busy/reentrant drops0; XNU publishes
8/8 initialized. md0 PID1 alive/11heartbeats, no panic, metadata primed and
fastboot return verified. This proves concurrent XNU scheduling and stated
IRQ/cache-coherency facts; TLB shootdowns are explicitly untested.
User requests iOS8 immediately after this test to compare performance.
Next GUI integration preserves UFS media bounds/mutex and framebuffer locks,
and adds a strict GUI8 contract plus CPU0 ownership for touch/shutdown;
current md0-only profile cannot yet admit Apple userspace/root writers.

## REDFIN two XNU cores run timers, cross-IPIs and bound tasks — 2026-10-23

Code commit `db420e4`; kernel d1521723/full local ARM64 build013354.
Image `ports/redfin/out/smp2-v1/redfin-xnu.img` SHA256
`33ee6f90b1c50c3d5686a083019b040deb92a49814431552df2f36e5ea4e3212`.
Exact args: `debug=0xc serial=3 cpus=2 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0 redfinbootid=0xb61737af5c379a88`.
Authenticated/image-matched `logs/redfin/smp2-v1/`: live RO return proof
APID210/subtype4/PON4 twice/IMEM0x77665500 succeeds before CPU_ON.
CPU0 and physicalCPU6 come alive with SGI1; bound tasks each progress32,
timer completions66/65, self acknowledgements1/1 and crossSGI2 acknowledgements
131/130. Worker exited/IRQ observers drained, busy/reentrant drops0/0;
kernel publishes2/2 initialized CPUs. md0 PID1 alive/11heartbeats, no
panic, metadata primed and fastboot return verified. TLB shootdowns are
explicitly untested; this is an isolated scheduling/IRQ/coherency result.
Next: extend the same separately gated proof to all8already-capable cores;
preserve the working2-core profile and keep UFS/GUI off until verified.

## REDFIN SMP-capable kernel UP regression passes — 2026-10-23

Kernel d1521723/full local ARM64 build013354, all new SMP overlays
compiled but disabled. Image `ports/redfin/out/up-smp-regression-v1/redfin-xnu.img`
SHA256 `93a6cc35236e5d6664741bd8a3ffe99b8bc75c5257de96335234fdb47d696683`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinearlyreturn=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xc4e45afec808203b`.
Authenticated/image-matched `logs/redfin/up-smp-regression-v1/`: exactly
one boot-ID marker before IOKitCPU startup; shim PON prearm and protected
leaf succeed, PID1 alive/11heartbeats, no panic, metadata primed and
fastboot return verified. This is a UP regression result, not SMP proof.
First isolated `smp2-v1` test now running with UFS/GUI/writers disabled;
actual C validation of its complete payload/ADT/liveFDT and host return
policy passes. Concurrent SMP result pending; all8remains the target.

## REDFIN all eight cores have16K capability; SMP2 kernel prepared — 2026-10-23

User requires all8cores; CPU0+CPU6 is an intermediate XNU proof, not the
final target. Selectable CPU capability overlay keeps the default CPU6
profile and accepts only explicit0x100..0x700 affinities; each separate
boot wakes one secondary, checks its actual part and parks it outside XNU.
20 actual-C/default-regression/target/ARM64 tests PASS. Local ARM64 build
`research/redfin-build/build-20261023-011946.log`, kernel SHA256
`5cf3cd58aa283913816be14993c38662937199aa347d33c23879a97271e3607a`.
Six frozen temporary images use exact common prefix:
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfincpu=1`
then exactly ` redfincputarget=TARGET redfinspmi=1 redfinreturn=1 redfinbootid=0xNONCE`
using each row below (no other args):

| Core | TARGET | NONCE | Image SHA256 |
| --- | --- | --- | --- |
| CPU1 | 0x100 | 4288788d3cf63094 | 8474bd7410c2609369c09fb2677d3cd70ef9b961245dde1d65d48bb6909c7842 |
| CPU2 | 0x200 | 0a295f223d482666 | 94484fdd8a5900444e4bf64ef8c8e6dd82e05131b3043ada228db92891dc0bf4 |
| CPU3 | 0x300 | 7b3f6b989b110f9d | 0194cfde33cecf04b8e3d92d098054a580c0a48afa51de0d8180e0072bf9259d |
| CPU4 | 0x400 | 02aecf21ac379a30 | bf89dfd3ae2afb630366804f6c6ccdb4ccdb6e7e3257f64691bf35b6faacf849 |
| CPU5 | 0x500 | 3f99b9029d15522a | 11da1a3683b99e99ce2b50b1d1a16bfd42d2c6878343f0f9cfacaf8834b3a554 |
| CPU7 | 0x700 | c32374aa711634fc | daa3000d8128ddb7debcfec06167cc5ad2b67271fd4205bdcd8f7f168a39822b |

`logs/redfin/cpuN-cap-v1/` for each row: authenticated/image-matched,
PSCI CPU_ON0, actual EL1, MMFR0x101122/TGran16=1/valid1; CPU1..5
MIDR0x51df805e, CPU7 MIDR0x51ff804e. Each has11PID1 heartbeats, no
panic, verified recovery/fastboot return. Together with existing CPU0
XNU and CPU6CAP this proves required16K support on all8cores. It does
not establish concurrent XNU execution, cross-core coherency or scheduling.

New isolated SMP2 overlays add synchronized RAM logging, an independent
read-only PMIC/IMEM proof before CPU_ON, strict CPU0+CPU6 topology and
EL1 trampoline, and bounded self/crossSGI2, timer and pinned-progress proof.
The unique boot-ID marker now appears at RAM-log initialization, before
IOKitCPU startup. Source/host policy keeps UFS/GUI and legacy PMIC writers
off in this profile; shim alone prearms return before payload validation.
Loader string tables changed to inline arrays after actual GCC caught
absolute-address relocations. Real GCC relocation test and14topology
checks PASS. Logger patch gained external context so git-apply/reverse
verification works without special flags; actual C bodies are unchanged.
Host SMP simulation fixed a missing IRQ delivery after its worker exits;
real PEs retain IRQ delivery, so production proof did not change. Full758
PASS (`peripherals-host-tests-v33.txt`); subsequent loader changes pass
its14targeted tests. Tests previously failed on that host-model race and
on comparing a logger with later overlays still applied; both corrected.
Local full ARM64 build `research/redfin-build/build-20261023-013354.log`
succeeds, kernel `d1521723f01a43deb0972f088440943c05c009885aedc8559206c393f9d33ba9`.
The two-CPU profile has not yet passed hardware proof. TLB shootdowns,
all8concurrent XNU cores, GUI/UFS SMP and GPU remain unverified.

## REDFIN shim return V2: early PON reason and UP boot verified — 2026-10-23

Commit `21c435e`; same kernel9a2d87a5/local ARM64 build004936 as V1 and
protected leaf test. V2 removes redundant pre-relocation watchdog arm;
the existing loader still arms the watchdog immediately before XNU.
Image `ports/redfin/out/shim-return-v2/redfin-xnu.img` SHA256
`84dc2b94273a2cdd76456a6ab6d4f59e716c0ffed2919bdb8fd52c59127283e9`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinearlyreturn=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xde5ac7f14c6e3052`.
Authenticated/image-matched `logs/redfin/shim-return-v2/`: initial PON read
already4/restart reason2 BEFORE existing kernel arm (protected-only V1
initially read0x10). This establishes shim prearm before XNU entry. Existing
arm and shared leaf repeat4->4 with IMEM0x77665500/result0; PID1 alive,
11 heartbeats, no panic, metadata primed, fastboot return verified.
V1's premature ending remains unexplained; removing the early watchdog
correlates with success but does not prove causation. Next: isolated md0
SMP2 startup after synchronized logger/strict topology/RO return proof and
host checks. GUI/UFS SMP, GPU and About wait chain remain unverified.

## REDFIN shim return V1 inconclusive; V2 comparison started — 2026-10-23

Same kernel9a2d87a5/build004936 as the successful protected leaf test.
V1 image `ports/redfin/out/shim-return-v1/redfin-xnu.img` SHA256
`47093dc5857c9920bc2db5fc672aa7e1e014aad64326c0ad66f855b77cdbb75f`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinearlyreturn=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xf43ca06682e803ff`.
Compiled opt-in shim invokes the identical leaf after live FDT validation,
before payload/kernel/ADT validation. V1 also armed watchdog before relocation.
`logs/redfin/shim-return-v1/`: fastboot/recovery return verified, capture
authenticated, but expected boot-ID missing; no PID1 proof. Console ends
after CPU0 init and BSD buffer setup, no panic visible. Without the nonce
this is not an image-matched kernel result, and does not prove early PON4.
Removed the redundant pre-relocation watchdog programming; existing loader
still arms it just before XNU. Early bark/timing is a hypothesis, not a
diagnosis. V2 same-kernel/leaf comparison started, result pending. Do not
enable SMP hardware before shim proof succeeds. Isolated source preparation
for strict SMP2 proceeds separately; no additional CPU has entered XNU.

## REDFIN shared early-return leaf passes protected UP test — 2026-10-23

Kernel local ARM64 build `research/redfin-build/build-20261023-004936.log`,
SHA256 `9a2d87a56915830e4d600c2201e79428c7ca648aa0b1a25b7925b0c56e57ec6b`.
Shared header SHA256 `ddb78cb215e6f6ed070e6ad3d3da96c8d289e931a7276b65a507aa7f2befb7c7`;
early-return overlay `c1288edaafd60907d9b8e2cb445b53490456c85563fe5be3ee3f5f2f96daf4c1`.
15 actual-C/backend/dispatch tests, including fault/timeout/order, all256
prior spare bytes, header identity and native ARM64 compilation PASS.
Full682 PASS (`logs/redfin/peripherals-host-tests-v31.txt`); independent review.
Image `ports/redfin/out/early-return-v1/redfin-xnu.img` SHA256
`c20628664088541b7a6384f883008eafbfd414143f8f5bdf82b75e8982f2ce16`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinearlyreturn=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x5b4e86d27301bfd7`.
Authenticated/image-matched `logs/redfin/early-return-v1/`: existing return
arms first; shared leaf finds APID210/EE0, subtype4, spare4->4/readback4,
IMEM0x77665500, issued1/1, leaf0/stage6/probe0. md0 PID1 heartbeats,
no panic, metadata primed and fastboot return verified. CPU count remains1.
Next: same exact leaf in opt-in shim before loader validation, known UP
kernel and no UFS/GUI. Shim wrapper's7 actual-C/native checks PASS; no
shim hardware result yet. No new GPU power/firmware writes.

## REDFIN CPU6 V2: PSCI entry and 16K capability confirmed — 2026-10-23

Commit `5f34df2` fixes the mailbox alignment. Kernel local ARM64 build
`research/redfin-build/build-20261023-002659.log`, SHA256
`e2770bcc5077056f357d00630c7df6e7c40209b0ce04912138bfb8462418b4f4`.
Image `ports/redfin/out/cpu-cap-v2/redfin-xnu.img`, SHA256
`bf7521057ce2c70b7d3d1645fb630d0ba412622b1435a695edaa6246d4254581`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfincpu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x2c53796a7d06bae3`.
Authenticated, image-matched `logs/redfin/cpu-cap-v2/`: return armed first;
PSCI1.1 reports CPU6 OFF, CPU_ON64 returns0, mailbox publishes
MIDR0x51ff804e, MPIDR0x81000600, MMFR0x101122, CurrentEL4 (EL1),
SCTLR0x30500800, CTR0x9444c004. TGran16=1, valid1, probe result0.
CPU6 remains parked outside XNU with exceptions/MMU/caches off until reset.
This proves firmware entry and architectural16K support, not SMP scheduling.
md0 PID1 alive/11 heartbeats, no panic; recovery authenticated, metadata
primed and fastboot return verified. Phone left in fastboot; no Android boot.
Next: test shared early-return helper behind existing UP return, then the
same helper in shim before kernel/topology validation. Only after that
permit isolated md0 CPU0+CPU6 XNU startup with synchronized logging and
cross-IPI/timer/progress proof. GPU power remains gated on ARC vote ownership.

## REDFIN CPU6 V1 refused misaligned mailbox; V2 kernel ready — 2026-10-23

Commit `eace595` records the guarded capability probe. V1 image SHA256
`a8c57217ab5e9e38d3bb289293573d54ec710e27e47952cd8efdab7fa00913b6`
uses kernel f7c3dc43/build000903.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfincpu=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x17d0a351bbf24a67`.
Authenticated/image-matched `logs/redfin/cpu-cap-v1/`: return armed first,
CPUCAP result22/EINVAL before any PSCI diagnostic/CPU_ON; PID1 alive,
no panic, metadata primed and fastboot return verified. Offline nm identifies
mailbox VAfffffe000806f000, only4KiB aligned despite the C alignment attribute.
The guard correctly prevented waking CPU6; there is no capability result.
Fix uses permanent32KiB static backing and selects a checked16KiB interior
page at runtime. All PA/span/entry/cache/one-shot guards remain. Preflight
failure now reports addresses. 16 backend tests PASS plus independent
49152 alignment cases spanning every residue at low/high/kernel addresses.
Full664 PASS (`peripherals-host-tests-v29.txt`), including separate future
SMP-log tests; that logger patch is NOT applied to the capability kernel.
ARM64 build `research/redfin-build/build-20261023-002659.log` succeeds;
kernel SHA256 `e2770bcc5077056f357d00630c7df6e7c40209b0ce04912138bfb8462418b4f4`,
CPU overlay SHA256 `10fdda6ff3c19c26135e68159ef841ba842b5b60a22bd194c1a81500c33841ba`.
Next: fresh V2 temporary image and automatic capture, no manual input needed.
User is away and authorizes autonomous tests. Interactive touch/UI tests wait.

## REDFIN parked CPU6 capability kernel prepared — 2026-10-23

User requests more cores/GPU after the unchanged V3 lag and About freeze.
New cpu-probe/cpu-probe-start overlays keep every existing UP fence and
wake only OFF CPU6 through PSCI after actual return_ready. The secondary
publishes registers to a permanent checked16KiB page and parks with IRQs,
MMU and caches off. No secondary XNU entry or device MMIO/DMA; CPU0 owns
all logs and bounded500ms polling. Exact token presence dispatch blocks
other observers even for malformed/bare/overflow/zero redfincpu; the backend
uses strict frozen flags, full Aff3 checks and one-shot ownership.
13 actual-C/ARM64 backend tests and2 dispatch tests PASS; full649 PASS
(`peripherals-host-tests-v28.txt`), with independent review. Builder exposes
exclusive --cpu-capability-probe and documents it in CPU.md.
Local build000025 failed on missing delay declaration;000628 correctly
refused a prepared/header-order mismatch. After matching kern/clock.h,
ARM64 build `research/redfin-build/build-20261023-000903.log` succeeds.
Kernel SHA256 `f7c3dc43cf942f169d1d72d3801d8a9bdbf129df190cb3eeb0ca6353d679063f`;
CPU overlay SHA256 `9a95a6f95be5fa090e72e52cb46d764118eb306f08e4c027808940fd177318cf`.
Image generation/hardware proof is next; no CPU6 capability result yet.
Full SMP additionally needs early return ownership, synchronized logging,
MMU/GIC/timer/cross-IPI/progress proof before UFS/GUI. A separate SMP log
overlay is being prepared but is not part of this kernel.
GPU audit found live CX parent cx.lvl ARC dependency: LOW_SVS64 maps to
hardware selector2, and a free TCS is not an independent latched voter.
Current/held HLOS floor is unproved; no GPU power/firmware writes were
added. Source-backed details and future requirements are in GPU.md.

## REDFIN touch GUI V3: cadence/debug change did not resolve lag — 2026-10-22

Commit `414929b` records physical touch/UI confirmation and reported1FPS.
Builder now exposes optional --display-hz1..10 with --display required;
default boot args/manifest shape stay unchanged. 20 CLI checks PASS
(`logs/redfin/display-hz-host-tests-v1.txt`), plus actual generated manifest
assertions for cadence10, screenshots/spam absent, touch/return/shutdown
preserved. No kernel changes; same kernel7da40f41/build214311.
Image `ports/redfin/out/touch-gui-v3/redfin-xnu.img` SHA256
`41546f6110a9aab53a43c75934788c17287f843312c39d8af10a03d0ac431590`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=10 redfinshutdown=120 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinbootid=0x729677d55a2ce393 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Commit `65d0add` records the CLI/guide. Authenticated, image-matched
`logs/redfin/touch-gui-v3/`: Apple userspace alive, no kernel panic,
touch error0/batches1060/contacts9/releases9, clean-unmounted HFSX16GiB,
metadata primed and fastboot return verified. User reports roughly unchanged
lag and slow app opening. About in Settings appeared to freeze the screen,
without an immediate restart; no Preferences crash is visible in console.
There is an earlier driverkitd SIGKILL and later scheduled120s shutdown;
neither establishes the cause of the reported UI freeze. This changes
three debug/cadence settings together and cannot isolate a single
performance cause. Requested10Hz is software cadence, not measured FPS.
User now requests more cores and GPU. Next: separate md0/UP CPU6 PSCI and
16K capability probe AFTER verified return; full SMP additionally needs
topology/loader fences, pre-CPU_ON return ownership and synchronized RAM
logging/watchdog. GPU next stage is separately fenced CX-only power proof.

## REDFIN touch GUI V2: physical contacts and UI response confirmed — 2026-10-22

Commit `5c8d54e` records working bounded USB networking/live logs. The next
temporary image `ports/redfin/out/touch-gui-v2/redfin-xnu.img` SHA256
`24cc3ba67afa63c7a5aa1a6b9d73f668c990f21aad96a07f099f66af05904678`
uses the same kernel7da40f41/build214311; all touch overlays match V1.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinfb=1 sweetfb_noconsole=1 redfinscreen=1 redfinshutdown=120 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinbootid=0x5fcad830b66fc202 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Authenticated/image-matched `logs/redfin/touch-gui-v2/`: actual Apple
launchd/backboardd/SpringBoard, HID service open, SEC ID/sensing/readback0,
consumer synchronized. Touch worker stops normally: error0, batches1458,
contacts41/releases41; 41 DOWN and 41 UP logs contain changing coordinates.
These are accepted physical SEC contacts and native kernel HID dispatch;
releases also include cleanup, so do not label all41 physical finger-UPs.
The user separately confirms visible iOS and taps/swipes changing the UI,
establishing actual panel output and end-to-end single-finger interaction.
No panic; HFSX16GiB journaled, clean-unmounted/not-inconsistent; metadata
primed and fastboot return verified. RAM screenshots are early captures,
not direct proof of later UI response. Touch lease120s includes HID wait.
User reports severe lag, roughly1FPS. This is an observation, not measured
frame timing. Source defaults software display to5Hz; each full present
copies10108800 bytes and rearms its timer afterward. Capture diagnostics
account for ~455KiB of641KiB console; swap logs are already bounded.
Next safe comparison: omit screenshots/kprintf spam, use existing kernel
sweetfb_hz=10 via a validated builder option, keep touch/return/HFS profile.
Do not claim GPU absence or copy cost alone explains1FPS without timings.
USB with UFS/GUI, multitouch, Wi-Fi and GPU acceleration remain unproved.

## REDFIN USB V7: ARP, ICMP and fresh live kernel logs work — 2026-10-22

Native macOS `usb-native.py` uses typed nonpromiscuous libpcap, exact
Darwin ABI, same-port live ECM ancestry/descriptor-MAC proof, and bounded
transient registry reads. It handles the observed masked ifconfig MAC as
reporting only; wire packets/BPF use expected02:00:5e:77:ee:01. Shared
direct-USB Protocol is unchanged. No detach, reset, host IP or permission
change. 27 new tests and independent review PASS; full631 PASS
(`logs/redfin/peripherals-host-tests-v27.txt`). Source SHA256
`be2da58986807ae4b67b127191fb21feb6a65dc86a31ea8b0df346203e497556`.
Same ARM64 kernel7da40f41/build214311 as V5; V7 image SHA256
`5fb561bf61a16c207fa6a346902d8d1b427b6f6c23f55e13575f5bd22fbc27b0`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xcad70162e6f4d65a`.
`logs/redfin/usb-net-v7-host-native/`: link-ready; ARP and solicited
current-nonce ICMP reply true, 14380 validated UDP log bytes, boot-ID
freshness matched, rejected/truncated/overflow0. Interface en9 on original
Google USB port; reported MAC masked, wire/descriptor MAC expected.
Independent `logs/redfin/usb-net-v7/` recovery capture authenticated and
image-matched, md0 PID1 alive/11 heartbeats, no panic, metadata primed,
fastboot return verified. Packet nonce evidence itself is not cryptographic
authentication. This proves bounded md0 USB networking/live logs, not USB
with Apple userspace/UFS. Source/README/USB guide updated; captures private.
User requested touch next: prepare a fresh UFS/GUI/touch-events image with
the same kernel, 120s graceful shutdown and RAM screenshot; require actual
finger input before judging physical contacts. Radio/GPU still unproved.

## REDFIN USB V6: live Skywalk interface MAC differs — 2026-10-22

Commit `b61d354` records V5 native binding. Initial native libpcap probe
passed 20 tests including an actual Darwin SDK ABI check: Apple's
pcap_pkthdr is 280 bytes (256-byte comment extension); caplen/len offsets
16/20. USB subset190 PASS (`usb-native-host-tests-v1.txt`). Independent
review fixed dictionary/list plist roots, bounded transient registry reads,
and revalidation before first packet injection. No kernel changes.
V6 uses the same build214311/kernel7da40f41 as V5; image SHA256
`d7b4dcdbc9e64b44e32eb86a51f4a92ff221b84bf66ae168f13f50f2f13d93df`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xeabb7e61e8cdf3af`.
`logs/redfin/usb-net-v6/`: authenticated/image-matched md0 PID1 alive,
11 heartbeats, no panic, metadata primed and fastboot return verified.
The repaired private observer captures the complete native driver tree:
AppleUserECM -> IOSkywalkLegacyEthernet -> EthernetInterface en9, and
AppleUserECMData with data alternate1. IOMACAddress on the first two
ancestors is expected02:00:5e:77:ee:01. However live ifconfig en9 reports
02:00:00:00:00:00, UP/RUNNING and active; IPv6 link-local then self-assigned
IPv4 appear. This explains why the earlier MAC-only watcher missed en9.
Native probe correctly refuses the mismatch before opening pcap or sending
ARP; UDP listener remains empty. Follow-up host audit finds all 15 Ethernet
MAC reports equal02:00:00:00:00:00. Public XNU dlil_ifaddr_bytes returns
exactly that mask when mac_system_check_info denies net.link.addr; this
supports privacy redaction rather than a changed wire MAC. The exact host
policy decision has not been observed. Next: require the expected MAC on
the same live ECM ancestor and explicitly recognize the masked ifconfig
report. Wire packets/BPF must continue using the descriptor MAC, never the
masked report. Packet exchange will independently test that choice.
No host IP/permissions/driver changes and no flash or Android boot.

## REDFIN USB V5: native macOS ECM binding confirmed — 2026-10-22

Commit `9fdeafc` records the direct probe and restored descriptor build.
Previously prepared V5 has now booted: image SHA256
`d871edc7b7325c0d15405e4ebbbbde83d9b104bc5d3e36ac1915934f28e5d7aa`,
kernel SHA256 `7da40f41a772c11bbcc3b5c1dd4dee7d987dca49aeb5fc0ecf05e844faf76fc9`,
local ARM64 build `research/redfin-build/build-20261022-214311.log`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x2e8c9bed7d6abe6a`.
Authenticated, image-matched `logs/redfin/usb-net-v5/`: md0 PID1 heartbeats,
no panic, metadata primed, fastboot return verified. ue0 up0, gadget0;
host sends SET_CONFIGURATION1, data SET_INTERFACE alt0 then alt1, MAC
descriptor requests and SET_ETHERNET_PACKET_FILTER value0x000e (index0).
The earlier summary calling the packet-filter value zero was incorrect.
Host policy restriction is gone: libusb sees/opens the same-port gadget
and reads configuration1. Claim interface1 returns ACCESS(-3).
Private `usb-net-v5-ecm-driver-audit.txt` proves AppleUserECM holds exclusive
access; native libusb maps Darwin ExclusiveAccess to ACCESS. Native
AppleUserECMData/control drivers start; configd creates the Ethernet
interface. Sanitized persistent preferences identify en9 and expected MAC
02:00:5e:77:ee:01. This is native binding, not a privilege failure.
The old class observer crashed on transient empty ioreg output and the
MAC-only interface watcher missed the interface; their negative results
are inconclusive. ARP/ICMP/live UDP are still unproved.
Next: robust live driver/interface capture and native nonpromiscuous
libpcap traffic through the system driver. Existing host access_bpf permits
opening /dev/bpf read/write without sudo; no host IP edit is necessary for
the bounded Ethernet probe. Keep the same kernel/SMMU profile and fresh
image boot nonce. No Android boot or flash; phone remains in bootloader.

## REDFIN direct USB probe ready; macOS transport restriction confirmed — 2026-10-22

Commit `c54d35d` records bounded ECM/log startup. New `usb-host.py` uses
typed libusb FFI, pins the pre-boot Google bus/port and opens only 1209:0001
there. Standard configuration/interface/alternate selection plus bounded
ARP, nonce-bearing ICMP and checksum-checked UDP logging; no detach, reset,
host IP edits, serial descriptor requests or retry after ACCESS/BUSY.
Private output capped8MiB; USB nonce evidence explicitly not cryptographic
authentication. Native libusb1.0.30 ABI/descriptor18 and Google baseline
check pass. 27 packet/lifecycle/FFI tests and independent reviews PASS.
Source SHA256 `3005772474bc62e40b6d5ff66fed62fcff23fb19a802ef1ce2d18efbe965bed1`;
tests SHA256 `0015a1dc15a63ccc82dda6651fa28a19d5294bab558bdfbb1f9bc087d99efb76`.
Earlier full suite599 PASS (`peripherals-host-tests-v25.txt`); final suite
after bounded discovery telemetry: 604 PASS (`peripherals-host-tests-v26.txt`).
V3 reuses build205957/kernel1387206c (full hash above); image SHA256
`57a9831095bdd50d029b68453dc61d5291e84e3e61ac0d71e02b538927fa3b54`.
Exact V3 args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xf70dc82c59b0045e`.
Authenticated/image-matched V3 again ue0 up0, gadget0, no panic, halted1,
metadata primed and fastboot verified. Host IOUSB sees1209:0001 but libusb
never sees it and the direct probe times out before open, not ACCESS/BUSY.
V4 experiments only with Redfin bDeviceClass2->0 (interfaces unchanged).
ARM64 build `build-20261022-213406.log`, kernel SHA256
`50f088a96d8517b13bf1c96832fe9ecc994e4854f4c4411ee25b916b1a52b032`;
image SHA256 `76307a0ca691284e97c0151894fcfe1d1e1cbdba3988776a1f807141c7cb747b`.
Exact V4 args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xf6f96de49059d593`.
Authenticated/image-matched V4 again ue0 up0/gadget0, no panic, halted1 and
verified fastboot; host IOUSB sees gadget, both IOService class queries and
libusb miss it. The descriptor-class change did not resolve publication.
Host `usb-net-v4-host-kernel-usb.txt` lines137/150/151 prove the cause:
480Mbps enumeration, then `device functionality blocked by transport
restrictions` and `device will not be registered for matching`.
Darwin libusb owns a hotplug CFRunLoop and matches IOUSBDevice; an application
event pump is not a fix. The class experiment was reverted; its source is
preserved privately as `research/redfin-usb/usb-interface-class-v4.patch`.
Build214248 refused the removed overlay's stale prepared fingerprint; after
reverse-apply, only that matching experiment hash was removed, and the full
reverse-overlay verifier/new ARM64 build `build-20261022-214311.log` pass.
Restored kernel SHA256 `7da40f41a772c11bbcc3b5c1dd4dee7d987dca49aeb5fc0ecf05e844faf76fc9`.
Prepared V5 image SHA256 `d871edc7b7325c0d15405e4ebbbbde83d9b104bc5d3e36ac1915934f28e5d7aa`.
Exact V5 args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x2e8c9bed7d6abe6a`.
V5 is prepared, not booted. Next required external action: user unlocks Mac
and approves the named Sweet iOS USB accessory when macOS requests it;
then repeat V5 with the direct receiver. Do not change global OS security
settings or device identity to bypass the host restriction. Phone left in
verified fastboot. ARP/ICMP/live logs, physical touch, Wi-Fi/GPU unproved.

## REDFIN ECM/log startup validated; host configuration still missing — 2026-10-22

Commit `e6de11b` records V5 host enumeration. New typed startup modes
ENUM/ECM/ECM_LOG are sealed once and rechecked by every ownership phase;
strict textual/numeric flags reject overflow/bare/late changes. Network
requires the proved five-store AArch64 route, md0, CPU1 and 30s lease; all
other writers stay fenced. No SMMU changes added. Six actual-C caller tests
and independent review pass; 18 CLI tests pass.
Runtime hardening checks TX/RX proof, constructor allocations and exact
errors, drains the bounded queue/lowers ifnet once before halt, retains DMA,
and uses FIONBIO + MSG_DONTWAIT for log sends. XNU sosendcheck tests SS_NBIO,
so MSG_DONTWAIT alone was insufficient; the first local `usb-net-v1` image
was never booted. Fifteen actual-C real-handler tests and independent source
review pass. Full suite 577 PASS (`peripherals-host-tests-v24.txt`).
Worker overlay SHA256 `5bb409bd8bb69394af57301d24dd44150fff37f5030aaeb3fd8f4195a5e8d163`;
startup SHA256 `81b76303a8462f7ffba259ecfb804e4946ffddbfdad627164f081c89a4a1aa60`.
ARM64 build `research/redfin-build/build-20261022-205957.log` succeeds;
kernel SHA256 `1387206ce4912c8d1546f2d219bc628bb678a3e6a64bf3469bb2e3f3822fa447`.
Image `ports/redfin/out/usb-net-v2/redfin-xnu.img` SHA256
`134a8fe9c2bd3b3a5d9a3cdaa227a597b6563ab598c99717861179c3435c30b6`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinusbnet=1 redfinusblog=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x4d2b27fe54a8cf56`.
Authenticated, image-matched `logs/redfin/usb-net-v2/` reaches PID1, no panic,
metadata primed and return to fastboot verified. Claim/revalidation0, five
stores exact; XNU ue0 192.168.7.2/24 up errno0; ECM+log gadget0. Host-only
watch sees 1209:0001 on same Pixel port. Again only descriptor requests, no
SET_CONFIGURATION. No host ECM interface or UDP packets. DeadlineETIMEDOUT60,
halted1, permanent slab retained. No hardware fault/quarantine observed.
Packet exchange/live USB logs are not yet proved. Local macOS ECM driver
matching is present; IOAccessory log query does not prove a permission block.
Next: standard libusb configuration/CDC packet probe on this exact own port,
with no driver detach/reset or host network edits. Host libusb exists;
sudo has no cached authorization (not needed for the planned raw probe).

## REDFIN USB V5: host enumeration and EP0 DMA validated — 2026-10-22

Commit `d14e784` records the five-store native-format experiment. The new
format-status overlay changes only the expected owned-bank FSR FORMAT after
accepted CBA2R1: `(old & ~0x600) | 0x400`. All non-FORMAT bits, other banks,
fault checks and MMIO remain exact. Eight actual-C tests reproduce V4 and
validate this transition/fault refusal; independent source review passes.
Full host suite 554 PASS (`peripherals-host-tests-v22.txt`). Overlay SHA256
`8abf48445d8d75bfef7c38283e4c662b0a11a9b28112a007b75084308e42434c`.
ARM64 build `research/redfin-build/build-20261022-204018.log` succeeds;
kernel SHA256 `a6f1046bb15ff1e9eac987817fc82e8893cf6ee3cb3baddaf7dafcd0334d75a4`.
Image `ports/redfin/out/usb-enum-v5/redfin-xnu.img` SHA256
`9e8fb370500f4ced299693658aa5d2c80390a432bf3cc143187d96dfaef25c2a`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinspmi=1 redfinreturn=1 redfinbootid=0x0f7677ee4513cb0b`.
Authenticated, image-matched `logs/redfin/usb-enum-v5/` reaches PID1 without
panic, primes metadata and verifies return to fastboot. CB4/slot4 claim and
strict revalidation return zero; all five stores accepted. Slab PA182e50000,
EP0 TRB182e51000. DWC3 runs DSTS00820001 and gadget start returns0. Real host
SET_ADDRESS and device/string/configuration GET_DESCRIPTOR requests complete.
Host-only no-serial capture `usb-enum-v5-host.json` sees 1209:0001 on the
original Pixel port from45.342 to74.628 seconds. The worker's finite30s
deadline reports ETIMEDOUT60 and halted1, slab retained. No SMMU quarantine
or panic appears. This validates USB high-speed enumeration/control DMA,
not networking or USB with UFS/GUI.
Next network/log stage needs a typed md0 mode plus meaningful real-worker
tests: inherited log sock_send is blocking and interface lock allocation is
checked only after publication. Fix those before enabling ECM/live logs.
Physical touch contacts, panel scanout, Wi-Fi and GPU remain unverified.

## REDFIN USB V4: owned CBA2R format write accepted — 2026-10-22

Commit `afe1fce` records exact EP0 TRB/SID evidence. New opt-in
`--usb-aarch64-context` / `redfinusbrw64=1` selects five owned-bank stores:
SCTLR0, CBA2R1, CBAR10000, S2CR, SMR. Native nonstatic NS AArch64 setup
supports CBA2R.RW64 bit0; no other-bank, TLBI or FSR stores are introduced.
Absent/0 keeps exact original four-store I/O. Strict textual 0/1 plus numeric
cross-check rejects uint32 overflow, empty and bare flags; mode is frozen
for the lease. Nine actual-C tests, independent source review and 16 CLI
tests pass; full suite 546 PASS (`peripherals-host-tests-v21.txt`). Overlay
SHA256 `6f5e166eb1ace3ed5bfbb70542be300f6b3bfaaa469e56af8705034b8ce7cfc7`.
ARM64 build `research/redfin-build/build-20261022-203130.log` succeeds;
kernel SHA256 `d551c8a7e85a61bec24cf70a2728f7e8fe3236e9656127401bfb9e60033c4f6d`.
Image `ports/redfin/out/usb-enum-v4/redfin-xnu.img` SHA256
`90b65a48cdc690f4808c9042d38be96fb49d7178c9df5f223837d6f1a4b4b6e0`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbrw64=1 redfinusbgadget=1 redfinusbsecs=30 redfinspmi=1 redfinreturn=1 redfinbootid=0x48dcb371c471bb59`.
Authenticated, image-matched `logs/redfin/usb-enum-v4/` reaches PID1 without
panic, primes metadata and verifies fastboot. CB4/slot4 selected. SCTLR0
and CBA2R1 writes/readbacks succeed. Before CBAR or any gadget/DMA operation,
complete snapshot finds only own-bank FSR changing 0 -> 0x400, with SCTLR0,
CBAR0, CBA2R1 exact. Guard quarantines with EAGAIN35 after two stores.
This is a format-field transition, not FSR_FAULT; enumeration was not reached.
Next: establish exact FSR FORMAT encoding from source/spec and account only
for the documented owned CBA2R write's observed metadata transition; preserve
every fault bit and all other state, with no FSR clear/mask/retry.

## REDFIN USB V3 identifies the exact failing EP0 TRB — 2026-10-22

Commit `3dcfe47` records runtime sensing/HID startup and the V2 translation
fault. New `usb-fault-diagnostic.patch` adds only seven bounded RO reads on
a fresh, complete owned-bank fault: FSR/FAR words/FSYNR0/1/GR1 CBFRSYNRA/FSR.
No fault clear, resume, global TLBI, retry or policy change. All-ones or
changing FSR skips interpretation. Six actual-C tests and independent review
pass. Collector now recognizes normal launchd progression only with exact
authenticated image/nonce binding and no panic; static PID1 evidence stays
separate. Six new collector tests and independent review pass; offline replay
of the existing authenticated GUI V1 capture recognizes launchd successfully.
Full host suite: 535 PASS (`logs/redfin/peripherals-host-tests-v20.txt`).
Local ARM64 build `research/redfin-build/build-20261022-201705.log` succeeds;
kernel SHA256 `b43624055aedf5383a9b047c06677386e353f132e9b258722c058da80ebf909e`.
Image `ports/redfin/out/usb-enum-v3/redfin-xnu.img` SHA256
`abd3d4ac5b4e89d8efc61600b1d0d2d4424c803201db848ad8ad95e7f2f2913d`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbgadget=1 redfinusbsecs=30 redfinspmi=1 redfinreturn=1 redfinbootid=0x9d74a69d71cfe974`.
Authenticated, image-matched `logs/redfin/usb-enum-v3/` reaches PID1 without
panic, primes metadata and verifies return to fastboot. CB4/slot4 warm proof
passes. Permanent slab PA=0x182e54000, EP0 TRB=0x182e55000, setup=0x182e55040.
Fresh fault FSR=2, FAR words=1:82e55000, FSYNR0=1, FSYNR1=0, CBFRSYNRA=e0.
Thus SID e0 faults on the exact EP0 TRB read; SCTLR0/CBAR10000/CBA2R0 remain
unchanged. Guard quarantines, halt reports halted=1, slab retained; host
sees no new 1209:0001 device. Enumeration still unproved.
The cause remains unproved: >4GiB address with the AArch32 context format,
or retained configuration/TLB state, are hypotheses. Native 64-bit S1 setup
uses CBA2R.RW64, while upstream bypass quirk does not explicitly program it.
Native skip-init reset also performs global invalidation; that touches other
contexts and is not a justified next write. Review a narrow owned-bank
format experiment before another temporary boot; retain all fault guards.

## REDFIN USB enumeration V2: real translation fault isolated — 2026-10-22

Cached-only diagnostics preserve route policy/MMIO and have eight actual-C
equivalence tests; the full peripheral suite passes 523 tests. Local ARM64
build `research/redfin-build/build-20261022-200129.log` succeeded, kernel SHA256
`086378b2d7139e6a7f543aa661f4c768b3257f46d9175eab0d4f2ca02194f93c`.
Image `ports/redfin/out/usb-enum-v2/redfin-xnu.img` SHA256
`b596f151974475e093c5d855927d980d69552fdf693d06f996bb6eef3f6aaa92`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbgadget=1 redfinusbsecs=30 redfinspmi=1 redfinreturn=1 redfinbootid=0x73e514a987d0e3a0`.
Authenticated, image-matched `logs/redfin/usb-enum-v2/` reaches static PID1,
has no panic, primes metadata and verifies return to fastboot. CB4/slot4
claim and strict warm revalidation return zero. After device soft reset,
the first cached difference is CB4 FSR `0 -> 0x2`; SCTLR=0, CBAR=0x10000,
CBA2R=0 and all sampled stream/header words remain unchanged. Pinned
`arm-smmu-regs.h` defines bit1 as TF (translation fault), not UUT or FORMAT.
Guard quarantines, gadget returns EPERM, bounded halt reports halted=1 and
the DMA slab is retained. Host watch sees no new 1209:0001 device.
The cause of TF with this bypass context is not established. Next: collect
read-only fault address/syndrome and compare with the bounded DMA slab;
do not mask FSR, change context format or invalidate global TLB on a guess.

## REDFIN runtime sensing and real iOS HID consumer validated — 2026-10-22

Commit663adbb records the successful dedicated USB bypass route. New
usb-enumeration-start binds the same permanent caller to strict WARM,
ACTIVE (live power/clocks and complete SMMU/CB proof) and QUIESCE (sole
owner/live power solely for halt, even after route quarantine). Nine actual-C
policy tests/independent review PASS; legacy absent/0 warm IO trace unchanged.
Enumeration-only mode keeps network/logging off, deadline30s, bounded16KiB DMA.

Build build-20261022-194511.log; kernel SHA256 fd78ccbfa5a971c83511beec165c401f1c3b928f19a995f6237ae7ed1a1bd082.
Image ports/redfin/out/usb-enum-v1/redfin-xnu.img SHA256
0b49e191ad300a11c5e1a60b7d4b5e55e48a6f91180dacebf109a72b08a28eef.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinusbgadget=1 redfinusbsecs=30 redfinspmi=1 redfinreturn=1 redfinbootid=0x3c6600bb077cb79e`.
Authenticated/image-matched capture logs/redfin/usb-enum-v1-cycle/ reached
PID1, no panic, metadata primed and verified fastboot. Route claim/strict0;
local DWC3 reset completed, then ACTIVE SMMU proof failed EAGAIN35, before
host enumeration. Sticky error stopped further MMIO; authorized quiesce
reported halted1 and retained the DMA slab. Subsequent EP0 timeout is not
proof that the physical command hung: guard rejection can produce it.
Host-only no-serial watch logs/redfin/usb-enum-v1/host-usb.json observed no
new1209:0001 device. Cached-only bypass diagnostics preserve all MMIO/writes/
delays and will identify the actual divergence; no FSR mask relaxed.

New touch-sensing implements only source-approved volatile30|61/readback and
SENSE_ON10, with55/AF/30 preflight, APP/non-FLASH gate, post-AF and bounded
raw queue probe. Narrow8/12-byte TX validation exposes no arbitrary command,
firmware/NVM/reset/retry API. Eight actual-C tests/two reviews PASS. Typed
permanent startup lease supports original md0 ID, md0 scan, and exact UFS/GUI
events with source-audited noncompeting UFS code.20 new startup/backend/worker
tests PASS; async worker waits real HID then senses, rechecks lease during
contacts, releases all contacts on proof loss. Full suite514 PASS initially;
GUI CLI + cached USB diagnostics now523 PASS (peripherals-host-tests-v19.txt).

Build build-20261022-194803.log; kernel SHA256 693cfc32b85967bc57f61466246b4eb0dd05a445c6647125272af37a8354b376.
Image ports/redfin/out/touch-scan-v1/redfin-xnu.img SHA256
cdb3e38db49084c8b5504616b0936ef8a84cff031f3799cbb138c50fcb10b39c.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchscan=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x46e6444cda2080c3`.
Authenticated/image-matched logs/redfin/touch-scan-v1/ reached PID1, no panic,
metadata primed/verified fastboot. Typed lease1 power/ID0, BOOT20,
AFpre00:03:01:00, functions61->61/readback61, AFpost00:02:01:02; queue has
boot/vendor status records then empty, result0. This proves runtime sensing
initialization/readback and queue transport, not a physical finger contact.

Build build-20261022-194803.log; kernel SHA256 693cfc32b85967bc57f61466246b4eb0dd05a445c6647125272af37a8354b376.
Image ports/redfin/out/touch-gui-v1/redfin-xnu.img SHA256
4a0f0b12afd7a6a6f61d56591c62a20f70b3bd8f36b512b4fcb06fcbafa05093.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinfb=1 sweetfb_noconsole=1 redfinscreen=1 redfinshutdown=120 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfintouchevents=1 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinbootid=0xd90e6c8b6d64595e redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Authenticated/image-matched logs/redfin/touch-gui-v1/ status logs-collected
(the static-PID1 collector verdict is not applicable to normal launchd).
Typed lease2 power0, ID53:45:37:91:00; worker created before UFS publication.
launchd/backboardd/SpringBoard execute; backboardd opens SweetHIDTouch, real
consumer ready and sensing initialize successfully. Worker stops error0 after
926 batches, contacts0/releases0; no physical contact was observed/reported.
Three CRC-verified RAM screenshots decode in screens/, final frame shows the
lock screen. Fresh physical panel scanout still needs external observation.
Graceful shutdown completed; final HFSX16GiB header journaled/unmounted-clean,
not inconsistent; metadata primed and verified fastboot. Original partitions
and backups remain intact. User has a pending optional physical-display/touch
question; independent USB work continues without treating silence as an answer.
Next: cached USB enum V2 divergence and physical contact through this real HID.

## REDFIN dedicated USB bypass context works on hardware — 2026-10-22

Commit2c4b625 records successful physical SEC identity and RX-status handling.
New usb-bypass-context overlay uses the source-validated ordinary NS bitmap
allocator, excluding all active/latent TRANS refs, configured GR1, M1 and
actual FSR_FAULT banks. It permanently leases first-fit4 and invalid slot4;
only4 ordered stores: owned SCTLR0, CBAR10000, S2CR304, SMR800000e0.
Two initial complete stable imports plus all-bank/all-stream proof at every
boundary preserve nonowned state. Failed writes/proofs quarantine without
rollback/retry/DMA. Builder attests ns-context-allocator only for verified
nonstatic/nonsecure apps and atomic USB FDT contract; captured actual DT PASS.
Review found and fixed inherited DSTSallones accepted as HALT using its cached
read, with regression for all routes.62 USB tests/independent review PASS;
full suite475 PASS (logs/redfin/peripherals-host-tests-v17.txt).
Local ARM64 build research/redfin-build/build-20261022-192241.log passed;
kernel d5284b9b186fd465f091fd65c2fdd1cebb4c63da9a9f994d52c2536b00ad13f0.
Actual kernel rf_usb_bypass_hw_store disassembly is dmb/add/strw2,[x8]/dsb/ret;
zero uses a general register, avoiding the pinned Qualcomm WZR-store trap.
Image ports/redfin/out/usb-bypass-v1/redfin-xnu.img SHA256
7827db6ecb77e510ea58f7e55f05e54966df099550200834831cd41ceb11a79e.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbbypass=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xbe40805b3b96e127`.
Authenticated/image-matched logs/redfin/usb-bypass-v1/ reached PID1, no panic,
metadata primed and verified fastboot. Lease bank4/slot4, all4 stores accepted,
SIDe0 TRANS through SCTLR0/CBAR10000 retained; claim0 and strict revalidate0.
This proves the warm USB SMMU route, not device DMA or enumeration. No gadget
or controller writes ran. Next: hook guarded enumeration-only DWC3 with the
same caller/lease, separate active route proof and safe quiesce policy.

## REDFIN V8: SEC identity read succeeds — 2026-10-22

Commit69dda92 contains the DFS correction; the first TX is now operational.
New touch-rx-irq overlay adds bit7 only to accepted/acknowledged status;
the programmed hardware interrupt mask remains7f003e3f. All other unknown/
fatal status, DONE/FIFO bounds/LAST-valid/checksum/identity checks stay strict.
Six actual-C tests and independent review PASS;63 combined touch tests PASS.
Full suite465 PASS (logs/redfin/peripherals-host-tests-v16.txt), including
draft bypass builder/NS-contract gates; the four-store USB driver is pending.
The RX test then gained the exact V7 partial-FIFO pattern and was repeated:
six tests PASS. Both builders include the RX overlay.
Local ARM64 build research/redfin-build/build-20261022-191420.log passed;
kernel c1874ce0fc0b521b23ce416448ed9db04fc330d73b3f7bdb3bea0482d9a7fcdd.
Image ports/redfin/out/touch-id-v8/redfin-xnu.img SHA256
26e9178e36b6dacb4f1637fbb4ea2d30ee197dc50355480e244592c0b968420e.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x09ae8f1b9f6b61a6`.
Authenticated/image-matched logs/redfin/touch-id-v8/ reached PID1, no panic,
metadata primed and verified fastboot. SEC ID result0, exact53:45:37:91:00 at
960kHz; caller returned0. This proves physical power/cold SPI TX/RX and the
SEC response/checksum/identity path, not contact events or iOS HID. No event
worker/UFS/gadget/DMA ran. Next: source-backed event startup and HID callback
connection, explicitly address the existing md0-only RPMh software lease
before enabling touch alongside UFS-backed iOS.

USB source audit resolves the ordinary non-static NS allocator contract:
pinned arm-smmu.c1158/4988 directly allocates a software bitmap and5007 seeds
handoff; no raw-SCTLR-zero requirement or per-bank secure grant. Actual DT
has skip-init, no static-CB/secure aliases/USB VMID and USB atomic DMA. New
builder-only attestation tests plus actual captured FDT validation PASS.
Controlled dedicated-CB lease draft preserves active/latent refs and configured
banks, first-fit candidate4, exact4stores/noDMA. Peer review found inherited
DSTSallones accepted as HALT; fix/regression required before hardware run.

## REDFIN V7: TX now completes, RX notification falsely rejected — 2026-10-22

Commit070f6ad records V6 DFS mismatch and the private base-firmware inventory.
Minimal DFS correction clears only SE80 bit0 when set, after MCLK-off and
before existing GCC DFS-off/XO setup. It preserves all other fields and
requires exact readback; all-ones/mismatch stops before GCC/GPIO/reset/ID.
Five actual-C tests/independent review PASS;57 combined touch tests PASS;
full suite457 PASS (logs/redfin/peripherals-host-tests-v15.txt).
Local ARM64 build research/redfin-build/build-20261022-190306.log passed;
kernel 4dc7fe054712eac2ae5225a7d35f56c31a6274d75c7d6fb022b353b546a7bd6e.
Image ports/redfin/out/touch-id-v7/redfin-xnu.img SHA256
d8d33104d3563521d001e2095e1922e190e04216f7ebfc2fc440cd6c6debc6b2.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xbd1f9325ac0f615d`.
Authenticated/image-matched logs/redfin/touch-id-v7/ reached PID1, no panic,
metadata primed and verified fastboot. SE DFS300/GCCDFS20 now both disabled.
First TX completed; failing opcode is RX10000000/length10 with STATUS41 and
M_IRQ80 (bit7 M_RX_IRQ), not the former TX timeout. Our blanket unknown-bit
guard returns EIO5. Cancel now completes: STATUS0, IRQ4000080, RXFIFOc0000003.
Pinned qcom-geni-se.h names RX notification bit7; spi-geni-qcom.c ISR handles
FIFO WM/LAST and DONE/CANCEL/ABORT, then acknowledges raw M_IRQ, without
treating bit7 as fatal. Next: narrowly accept/ack that notification while
preserving the programmed interrupt mask, real-fault/unknown-bit refusal,
FIFO bounds/checksum/ID checks; then repeat ID-only RAM boot. ID unproved.

## REDFIN V6 proves GENI/GCC DFS mismatch; firmware assets inventoried — 2026-10-22

Commit20bd079 records V5 clocks/pads, RO USB contexts and bounded liblp parser.
New DFS overlay adds at most20 RO reads/six lines, no writes/delays;7 actual-C
tests/independent review PASS,52 combined touch tests PASS. Full suite452 PASS
(logs/redfin/peripherals-host-tests-v14.txt). Both builders include the overlay.
Local ARM64 build research/redfin-build/build-20261022-185724.log passed;
kernel 971118c2b9e8e40baf1a88ddda02e32a45cdce140dca8ca695ea46f5c9aefddb.
Image ports/redfin/out/touch-id-v6/redfin-xnu.img SHA256
36727ba6310a8d04a89acf42f8926c33394b08295991b7615127c937dd5b06ae.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x8cad7e5c26b9ff88`.
Authenticated/image-matched logs/redfin/touch-id-v6/ reached PID1, no panic,
metadata primed and verified fastboot. Before/failing first TX: SE_DFS_IF80
301 (enabled1), GCCDFS20 (enabled0), protection70/74/780, DMA_GENERALf,
CFG10833f/1090; wrapper HW20070000/AHB_M_CFG1/COMMON_CFG7. ID still timeout60.
Thus mismatch is observed, not merely guessed; whether correcting it fixes
TX remains unproved. Coreboot pinabf9c3b66c06c9f164388c2c72a31006385d3389
qupv3_config.c52..65 pairs SE DFS enable with clock DFS configuration. Next:
clear only SE80 bit0 before the existing GCC DFS-off/manual XO sequence,
preserve other bits, refuse failed readback before GPIO/reset release.

Targeted base-vendor capture completed with only4,509,696 data bytes plus
8,667,136 before/after GPT/super verification bytes, no mounts/device writes
or ramoops access, verified fastboot return.12 files/hashes independently
reverified: a650 SQE31632,GMU41548; a620 zap MDT6860+b00/b01/b02;
WLAN MBN3811096, both Redfin BDF26328, station config, modemuw and build.prop.
The only optional listing error is absent /etc/firmware (manifest partial).
Private report research/redfin-modem-inventory/vendor-assets-v1/host-inventory.json
SHAb79f063cd34f2bf4ede2a30f992553f5280d7546eb10e58640fb22adebfea5f5.
ZAP ELF32LE/Hexagon164/3PHDRs: b00 metadata148+b01 hash6712=MDT6860;
only loadindex2 requires b02 payload1676. WLAN complete7PHDR bounds pass.
WLAN versionWLAN.HL.3.3.1.c9-00516-QCAHLSWMTPLZ-1.38480.2; board variant
selection/RF identity and exact MPSS compatibility are not proved. Base vendor
contains mixed Android14 UP1A/2023patch and Android16 BP4A/SDK36/userdebug
2026 fields; do not call it pristine stock/current snapshot. COW unresolved.
No firmware loaded/authenticated or GPU/WLAN power/start attempted. Covered
ext4 helper10 real-libext2fs tests+independent review PASS; host cache and
firmware/tool outputs stay private. Generic liblp code alone is tracked.

## REDFIN V5 clocks/pads stable; USB context read-only inventory — 2026-10-22

Commit1da638d records USB V2 BYPASS-to-FAULT evidence and cached diagnostics.
New platform SPI overlay adds at most54 RO reads/10 lines, with publication
after complete capture; no new hardware writes/delays, and no new mappings.
Six actual-C tests and peer review PASS,45 combined touch tests PASS.
V5 local ARM64 build research/redfin-build/build-20261022-184139.log passed;
kernel acdc2f12b4313c3fde059e17cc2842406b47334e98bfd9bbb2b080b62732203c.
Image ports/redfin/out/touch-id-v5/redfin-xnu.img SHA256
af99379f2737d2dd63525e6202f34f1c9971d009b147cc5b65bbc6732de60d33.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xa6a012aa288e8a0f`.
Authenticated/image-matched logs/redfin/touch-id-v5/ reached PID1, no panic,
metadata primed and verified fastboot return. SE0/core/core2x4220, vote fc17c0,
RCG_CMD0/CFG1/M0/N0/D0/DFS20 and GPIO reset/AP/SPI remained unchanged across
TX hang. AHBs changed2 to80000002 with HWCG enabled; source permits this
idle gating. SEQ_START remained0. First TX/cancel/abort still timed out.
Next hypothesis, not a fix: GCC DFS was disabled, but SE DFS_IF_CFG80 was
not sampled; check for an interface mismatch plus wrapper initialization.

USB context overlay is explicit one-shot RO registration/observation, never
claim: two stable full81 stream/62 bank snapshots, DT-derived bounded maps,
active+latent references, ownership0 in every result. Ten actual-C tests and
independent review PASS;20 context/builder tests PASS. Both builders include
it and --usb-context-probe rejects touch/claim/UFS/missing return combinations.
Local ARM64 build research/redfin-build/build-20261022-184757.log passed;
kernel e57be69e129d90efa958da215e67a3fc05dabec8caea44c93b24fafff2dec058.
Image ports/redfin/out/usb-context-v1/redfin-xnu.img SHA256
ee63a43e3e0cbdd8317097302078afd1b783656b36f1be7aa036cb7ca93de7c0.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinusbcontexts=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x95cc7885473c0267`.
Authenticated/image-matched logs/redfin/usb-context-v1/ reached PID1, no panic,
metadata primed and verified fastboot. CR0280406/layout4K/62CB/offset80000
stable; unknown refs0. Banks0/1/2 have total TRANS refs3/1/1 (active2/1/1).
Bank3 unreferenced but configured;4..61 unreferenced with CBAR/CBA2R/FSR0
and stable nonzero SCTLR values, all M0. No fully zero unreferenced bank.
These observations do not establish allocation or ownership. No SMMU stores,
fault clear, route/DMA or gadget. Next: source interpretation/NS allocator
proof before any bypass-CB initialization, preserving all inherited banks.

The bounded host liblp parser and11 synthetic tests are now tracked under
ports/redfin/super_inventory.py; no dumps/firmware moved into git. Full suite
445 PASS (logs/redfin/peripherals-host-tests-v13.txt). Private covered ext4
reader has10 real-libext2fs synthetic tests PASS; provider review pending
before targeted read-only vendor-base asset extraction. Full super/vendor
dump, COW merge, mounts and firmware loading remain unnecessary/uninvoked.

## REDFIN USB V2: hardware coerces BYPASS to FAULT — 2026-10-22

Commit640ef10 records SPI V4 and its bounded GENI diagnostic overlay.
New usb-owned-diag overlay adds cached phase/index/header/readback logs
without additional MMIO/barriers/delays or guard changes. Six baseline-vs-
diagnostic actual-C tests and independent review PASS;42 focused tests PASS;
full suite417 PASS (logs/redfin/peripherals-host-tests-v12.txt).
Local ARM64 build research/redfin-build/build-20261022-182913.log passed;
kernel ab06eb9a82a4c815e40f72935e0f13837905f181e21bff67568451ff68a748c4.
Image ports/redfin/out/usb-owned-v2/redfin-xnu.img SHA256
e22d2a4ae84654491a3f99e5fa10086b9fbc1aebced3cc5c3f5e9791a00e6f75.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xec44740a75e6d698`.
Authenticated/image-matched capture logs/redfin/usb-owned-v2/ reached PID1,
no panic, public metadata re-primed and verified fastboot return. Full table
import and pre-store verification passed. Selected slot4 importedSMR0/S2CR0;
the sole store to S2CR offsetc10 requested10300 but read20300 after1000 polls.
Thus TYPE BYPASS1 became FAULT2, not an import/all-ones failure. No SMR store
or gadget/DMA occurred. Owner quarantined; do not accept20300 as bypass or
retry. Next: source-backed Qualcomm bypass-quirk/context-bank ownership audit.

Bounded stock super metadata read completed in safe recovery with no mounts,
disk writes or ramoops access; GPT/by-name sda18/size9755951104 verified and
fastboot returned. Private research/redfin-modem-inventory/super-prefix.raw
contains only first4194304bytes, SHA256
b985645755edb678f26682da8af9b48b73bd4a2b404e7b48c22406350be1a864.
Both geometries/slot1 redundant metadata checksums and contents agree:
max65536,slots3,logicalblock4096,v10.2/header256,tables1056; metadata ends405504.
Fresh current-slot:b proof retained privately. Base vendor_b is798003200bytes
in two linear extents. VirtualAB/COW entries exist, so raw vendor_b is not
yet proved to be the effective current Android snapshot. No firmware loaded;
host-only bounded parser tests and targeted asset inventory remain underway.

## REDFIN V4 identifies the first SPI TX hang — 2026-10-22

New touch-spi-diag overlay adds bounded read-only GENI snapshots:41 safe
registers, at most369 additional reads/45 log lines per boot; no FIFO data
or IRQ-clear reads, transport writes/delays/timeouts unchanged. Independent
review and6 actual-C diagnostic tests PASS; full suite411 PASS
(logs/redfin/peripherals-host-tests-v11.txt). Both builders include it.
Local ARM64 build research/redfin-build/build-20261022-182229.log passed;
kernel b5dfcf12db392c32a735a873d225fd13d63a6082d4f4ebf520f795555b38aa9c.
Image ports/redfin/out/touch-id-v4/redfin-xnu.img SHA256
c0715fc2348994aca16598e093bc7ba2d99e14a066772e9b299c4d63d3601026.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x2fb50bc1fbfe16b7`.
Authenticated/image-matched capture logs/redfin/touch-id-v4/ observed PID1,
no panic, re-primed metadata and verified fastboot return. L17/cold setup
passed again. Before firstTX: INIT8/8,STATUS0,FW101/101,MCLK141,SCLK0,
CLK_CTRL1,CGC7f,IRQ0,TX_LEN8,RX_LEN0,empty FIFOs. At failure:
STATUS31,M_CMD08000000,TX_FIFO20000000,M_IRQ0; clock/config values unchanged.
After cancel/abort: CTRL2,STATUS31,IRQ0,local routes disabled. This proves
the first TX opcode is still active, before RX. FIFO low word-count bits
are0; sequencer/clock failure cause is not yet established. No event worker
or UFS ran. Next: pinned-source interpretation of this actual snapshot,
then a minimal evidence-backed correction; USB cached EIO diagnostics.

## REDFIN touch exchange timeout and first USB ownership result — 2026-10-22

Commit ca0b0de contains the STATUS87 fix and initial USB owner caller.
Touch V3 completed automatically: logs/redfin/touch-id-v3/, authenticated
and matched image c81e1432db027e51, PID1/11 heartbeats, no panic, verified
fastboot return. Build180523/kernel b10cfe0ba85d50d78f9d27c5a67478dd0567edaa3ee50caba71772abae8bd606;
image cd092f49f6cfd64c3104cc866d5ac40c2efcf0a3e40e472e5e23a32175320919.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xc81e1432db027e51`.
Physical L17 proof passed (configured+VALID3304mV,MODE7,ENABLE80,STATUS87).
Cold setup reached reset release: XO19.2MHz/div20,mode3/AP bus. The ID
exchange, starting with TX-only8B, timed out (errno60), as did cancel/abort.
V3 does not identify which opcode hung: the ID is copied out only after a
complete valid reply, so zero bytes do not prove that RX was never issued
or that the touch controller is absent/wrong. Independent pinned-source
audits found no demonstrated original TX omission.
CGC bits8/9 are preserved by native setup too; do not clear them by name.
Next: bounded read-only GENI snapshots before command and around recovery.

USB owned V1 completed automatically: logs/redfin/usb-owned-v1/, authenticated
and image-matched b99e5d6ced0b25e3, PID1 proof, no panic, verified fastboot.
Build175738/kernel 9d9b9373af0c18538ffdffeb0df15ad0a52696f49094810b28f55c32fcbe1e0a;
image 33d6a637bb68946137cba7cd7346ff5538c44881532e3a369daf0ce60cf7d638.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=3 redfinusbowned=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xb99e5d6ced0b25e3`.
Caller registered0, ownership claim quarantined EIO5. Current logs cannot
locate the failed check or establish whether either slot write occurred.
No gadget/controller writes or DMA were invoked. Next: cached failure-stage
diagnostics without relaxing guards or adding writes. Both runs used md0;
UFS stayed disabled and Android must still not boot before userdata restore.

## REDFIN L17 physically enabled; STATUS87 guard corrected — 2026-10-22

V2 cached diagnostics add no MMIO reads/writes or physical callbacks. Build
research/redfin-build/build-20261022-175302.log passed; kernel
1d8f8a4e8d9e0112aab4b09d8a55ba8e8a9dd1b47c9841fd68140b10eccd641b.
Image ports/redfin/out/touch-id-v2/redfin-xnu.img SHA256
ad30236420cce45107067386cfeecea44d511453382057db64d52373124fe761.
Args exactly match touch-id-v1 except `redfinbootid=0xd87bb66d192cdf52`.
Automatic authenticated/image-matched capture logs/redfin/touch-id-v2/:
ACTIVE0 completed after16 polls, IRQ-enable1/IRQ1/IDLE1, all three command
statuses10101. Both first/1000th physical post samples: configured3304mV,
VALID3304mV,MODE7,ENABLE80,STATUS87. Power is present; the previous timeout
was a false rejection of STATUS bit2 by our overly narrow83 allowed mask.
No SPI setup ran, no UFS enabled; public metadata primed/verified fastboot.

Pinned Qualcomm unified readiness uses READY80 (pm_pwr_alg.c571..587) and
OCP20 (943..947), without giving bit2 a name. Both ready/floor guards now
add only observed bit2 to their allowed mask87. Existing configured+VALID,
MODE/ENABLE, model/index/stability/OCP proof is preserved;8f/97/a7/c7 still
fail. 41 related tests and independent review PASS; full suite405 PASS
(logs/redfin/peripherals-host-tests-v10.txt).

Latest actual ARM64 build180523/kernel
b10cfe0ba85d50d78f9d27c5a67478dd0567edaa3ee50caba71772abae8bd606
contains the fix plus the initial USB trusted caller. V3 ID image
cd092f49f6cfd64c3104cc866d5ac40c2efcf0a3e40e472e5e23a32175320919
is running; exact v1 args with image IDc81e1432db027e51. Immutable output
ports/redfin/out/touch-id-v3/ retains kernel/image metadata; capture target
logs/redfin/touch-id-v3/. Actual SPI ID remains pending.

USB initial RAM mode3 now has an explicit builder flag and a source-audited
sticky trusted caller: exact md0/UP/off-path/ADT proof, register/claim/strict
revalidation only, no gadget or DMA. 10 caller tests and peer review passed;
full kernel build175738 also passed. Immutable image usb-owned-v1 is prepared
but has not booted. Touch and USB ownership experiments cannot be combined.

Stock modem_b was read in verified offline Linux recovery, with no disk
mounts/writes or ramoops access; live GPT matched saved metadata, by-name
resolved to sda13 and the exact204472320-byte partition size matched GPT.
Private capture manifest: research/redfin-modem-inventory/capture.json;
host image SHA0f9b2f1bb44ec567bcdb99bf6a5c8a6c1bcd9d7a3b458895050ad0e7b08a8229.
Bounded host FAT/ELF inventory has13 passing tests and31 extracted files
(MDT+30 blobs,99,394,046bytes). All35 PHDRs/required original indices/hashes
are retained privately. Loadable span8c000000..9d800000 matches live reserved
memory exactly. GPU/WLAN board assets are absent from this modem partition;
vendor inventory/native PAS+GLINK remain unimplemented. No firmware loaded.

## REDFIN first controlled L17 vote: completion but no power proof — 2026-10-22

New initial md0-only touch caller owns a sticky software lease, explicitly
disables competing paths and blocks the legacy RPMh helper on Redfin. It
requires the full source/runtime PM8150/L17 producer, then fresh physical
configured+VALID voltage, MODE/ENABLE/STATUS proof before cold SPI setup.
Power backend owns only ACTIVE0, preserves other TCS/GIC/command state,
never unvotes and quarantines uncertainty. Dedicated host tests: rail-ready6,
RPMh22, caller4; full suite384 PASS (peripherals-host-tests-v9.txt).

Actual ARM64 build research/redfin-build/build-20261022-173614.log passed.
Kernel ed652ef1407ddf521347102a5a2da830d59adbb7cefd2ded3b58fbda98fd32a3.
Image ports/redfin/out/touch-id-v1/redfin-xnu.img SHA256
5bc7081aaeb1285ada8a9128b50672f67a8f46745348b865daa6b2286e7d3626.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x3c5be77ed77f9a70`.
Full kernel-build.json retained with the immutable image.

Automatic cycle logs/redfin/touch-id-v1/ authenticated and matched image ID,
observed PID1/11 heartbeats, re-primed the public RAM key and left verified
fastboot. No UFS enabled or panic observed. Physical pre-vote state again
configured3304mV/MODE7/ENABLE0/STATUS3. Owned TCS vote reached its completion
checks, then physical configured+VALID readiness timed out (errno60).
No SPI/GPIO cold setup or event worker ran. This does not prove the rail
remained disabled: post-vote raw fields were not logged. Next diagnostic
must record the exact post-vote tuple before changing vote semantics.

Isolated USB owned-route and warm CDC-ECM core now compile, with no startup
hook and no device DMA. Sole-owner callback, imported stream preservation,
one per-stream bypass publication and sticky quarantine are host tested.
Core has bounded event count, physical DMA bounds/contiguity, route checks,
bounded halt/run and strict MMIO/reset failure handling; first Redfin mode
is enumeration only. Fixed XNU current_thread/thread_terminate declarations
after build173159 failed. Latest guard/reset fixes compile in build174216,
kernel0f477771a5ce93a4748d58408597f81051bf29c10524ee7a15ceb2ce20b0ba9e.
36 focused owner/gadget tests PASS; USB remains uninvoked on hardware.

## REDFIN physical PMIC observations and compiled touch events — 2026-10-22

V6 RAM image2a13c0dc21fcd2451e8f84281794843b66c578ca85d2d706a4c170386226afa9,
kernel d485c0f0b5ec48a023b18acfc29828661d4986f844a6a28528e7beeca6917029,
build research/redfin-build/build-20261022-153354.log. Exact args:
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfintouch=1 redfinrpmh=1 redfinrail=1 redfinspmi=1 redfinreturn=1 redfinbootid=0xec516f717dcc18f5`.
Read-only PMIC observer authenticated the PM8150 model (SID0 REVID511e)
and all18 contiguous SID1 LDO pages4000..5100, APID85..102, owner4/type4,
stable. Candidate5000 has subtype7d, not the initially considered HT35;
unknown-layout gate correctly kept V6 header-only. No PMIC/GPIO writes.

V7 uses the pinned Qualcomm generic LDO driver's explicit unified-layout
branch (type4/subtype>=30) to allow only the observed7d in addition to the
older known types. This permits raw reads, without claiming a voltage policy.
Image19a92afcf8663dc2d3b327997e7f0b6ffc539260bd060d4c124013d7cd8b73ad,
kernel786d41910f244c198001bf1f1c198858519a22b9d0c81a9607b6689c9c220c45,
build research/redfin-build/build-20261022-154344.log. Exact args are V6's
with `redfintouch=1 redfinrpmh=1` removed and image ID6c2e206d85238990.
All18 pages remained stable. Physical5000: configuredVSET3304mV,MODE7,
ENABLE0,STATUS3/VREG_READY0. Physical4900:3000mV,MODE7,ENABLE0,STATUS3.
This proves the candidate rail is disabled; it does not authorize reset
release. V6/V7 automatically authenticated and matched their unique image
IDs, re-primed public metadata, and left verified fastboot. No UFS enabled.
Captures logs/redfin/peripherals-v6-rail/ and peripherals-v7-rail/.

The source ordinal chain plus the observed18 LDOs attributes L17 to5000:
Qualcomm commonbase4000/stride100, ascending peripheral enumeration,
driver index=(base-firstbase)/stride, enumL17=16; Linux PM8150 list1..18.
Exact references/limits are in TOUCH-RAIL.md. PMIC5 PLDO range is1504..3544mV;
3304mV is this board's DT target, not the hardware maximum. A future ready
proof must also read the valid voltage42/43 while enabled, beyond configured
VSET40/41. Controlled RPMh preparation remains unimplemented/unhooked.

Touch event transport/worker and corrected Redfin HID geometry now compile
in the actual ARM64 kernel, build153641/kernel
cb0149c82c927219782d3262f76f6520d11664320d94233fabd8d1d6135b3cd7,
also included in154344. They have no startup hook and have not run on device.
Worker waits for a real HID callback, discards stale initial events, validates
whole batches, suppresses unknown MOVE/palm/grip and releases contacts on
error/expiry. Fixed HID internal UP state being retained if allocation fails;
actual-method fault tests cover all10 contacts. Peer review passed.
313 integrated tests passed before the extra7d regression; the affected rail
suite now has9 passing tests. Next: source-backed PMIC5 power/readiness,
real SEC ID, then event/HID activation; isolated USB manager/gadget drafts.

## REDFIN RPMh/SMEM corrected and image-bound logs V5 — 2026-10-22

Build research/redfin-build/build-20261022-152410.log passed; kernel SHA256
423f87c3f624939ff01abd524dc98fcd50a3c5aa61a8a62f12023849c83fc940.
Image ports/redfin/out/peripherals-v5-ram/redfin-xnu.img SHA256
52edd29694a673aa6883b3ed78f7d1e2b2b212093339afe743d82a2aed2c467d.
Args are V4's exact md0 args plus `redfinbootid=0xc2fdb59fe388b4b6`.
Image/kernel manifests retained beside output. Automatic cycle finished with
authenticated capture, exactly one matching image ID, PID1/11 heartbeats,
public metadata re-primed and verified fastboot. No UFS writes enabled.
Logs logs/redfin/peripherals-v5-ram/. 304 host tests pass, including draft
event tests (logs/redfin/peripherals-host-tests-v6.txt).

New XNU images get a nonzero random 64-bit image ID; startup emits it once.
The collector only accepts PID1 success for these images from authenticated
bytes with exactly one matching marker, and preserves failed/mismatched
captures. Helper/pstore data cannot inherit authentication. The ID binds an
image, not individual executions if the identical image is reused; create
a fresh image or capture a baseline when distinguishing such repeats.

CMD-DB correction follows pinned Linux: directory terminates at its first
zero ID; unrelated nonzero IDs/addresses do not impose target type/alignment
policy; requested type is address bits18:16, preserving higher bits. Bounds
remain strict. V5 CMD-DB status0: ldoa17 VRM address41300, xo300a0,
cx30000, mx30010, gfx30050, ldoa5 40b00, ldoa12 42000, ldoa2 40f00.
DRV2 id20005/config800c8104: major2, 8 TCS,16 commands/TCS. IRQ37 masked,
not pending/active; all TCS idle with enable/wait/control zero; stable1,
ACTIVE-empty-mask3. This is observation, not acquired ownership or a vote.

Wi-Fi now validates the actual SMEM layout:14 partitions, APPS/MODEM
fb000+7c000, zero uncached items, no GLINK descriptor/TX/RX. A native MPSS
firmware/GLINK bring-up remains necessary; no radio readiness demonstrated.
USB route remains unmatched/fault (stable, CR0=290406). No SMMU writes/DMA.
Next: read-only PMIC rail evidence, controlled L17 preparation then real SEC
ID/events; a separately owned USB route; MPSS/QMI and A620 power/GMU backend.

## REDFIN RAM peripheral diagnostics V4 — 2026-10-22

Actual ARM64 build passed: research/redfin-build/build-20261022-151051.log,
kernel SHA256 a31f5a1ab5e90841c1b5a652ae120e7a918f1a101a3c0e42e1843fcd55db6f59.
277 integrated host tests passed (logs/redfin/peripherals-host-tests-v5.txt).
Image ports/redfin/out/peripherals-v4-ram/redfin-xnu.img SHA256
6e60a312f08698559e946c0d8f0fc20374c991c25add322ef40a2f02acc482fa;
exact build manifest and kernel-build.json retained beside it.
Args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinusb=2 redfinwifi=1 redfinrpmh=1 redfinspmi=1 redfinreturn=1`.
No UFS/root writes enabled. Automatic cycle authenticated RAM logs, observed
static PID1 and 11 heartbeats, re-primed public metadata, left verified fastboot.
Logs: logs/redfin/peripherals-v4-ram/. No pre-boot log baseline was captured;
authentication alone does not establish freshness. These diagnostic lines
and the recorded image/kernel fingerprint are consistent with this build.

USB apps-SMMU read succeeded: ID0=4c017e51, ID1=6000003e,
ID2=5111, CR0=2c0406, 81 groups; zero SIDe0 matches, all stable.
CLIENTPD=0/USFCFG=1 means unmatched streams fault. No DMA route was proved;
the inherited a244a000 event-ring address cannot authorize DMA. SMMU supports
4KiB/64KiB tables, not 16KiB; XNU allocations can back separate 4KiB tables.
No context/table, PHY or MMIO writes by these observers.

Wi-Fi status5 now identifies TOC entry0 as ffff/ffff,1ff000+1000: the
table's own reservation, not an APPS heap. Corrected host selection to match
pinned Linux smem.c before bounds/mapping; APPS and global fffe/fffe heaps
retain bounds/overlap checks. 14 parser/observer tests pass, including the
observed sentinel, foreign invalid extents and corrupt APPS equivalents.
The corrected parser has not yet run on the device.
RPMh CMD-DB header is valid but parser status4 (TYPE); source-backed address
slave-ID mask/directory validation correction is being prepared.

Compiled touch cold-setup and ID transport remain uncalled. Physical L17
3,304,000uV/enable/VREG_READY proof is still required before reset release.
No physical touch, Wi-Fi association, USB data or GPU acceleration claimed.

## REDFIN peripheral bring-up and upstream review — 2026-10-22

User requested real touch, Wi-Fi, USB and GPU. Native read-only recovery
snapshot research/redfin-peripherals-v1 confirms SEC S6SY79x SPI SE0
(0x880000, mode3, CS0,10MHz), ICNSS/SNOC radio, and Adreno620v2 with GMU.
No Android filesystems mounted. Exact FDT-gated opt-in observers, codecs
and host tests are now staged; these are not functional peripheral drivers.
Common dispatch runs only after verified PMIC+IMEM bootloader return, with
UP/mode/one-shot checks. Independent review passed. SPI ID-only transport
is a separate host-tested draft; no startup hook or clock/pin/power writes.

Initial peripherals-v1 did not mount root; first recovery transfer failed
transiently, retry captured a wholly FF bank (not valid ciphertext). AES
GCM rejection was retained; no unverified plaintext accepted. The user
identified a hung ADB server. Restarting it restored fastboot. After raw
and metadata preservation, public metadata was re-primed; known-good V6
control authenticated successfully, clean HFS/write_count387472, verified
fastboot. Capture logs/redfin/peripherals-log-baseline/.

Peripherals-v2 authenticated and returned fastboot, HFS unchanged/clean.
It proved the common return guard and GCC observations, then panicked in
kmem_alloc(16777216) during the full-TLMM mapping before GPIO reads. It did
not prove a bus hang or wrong GPIO tile. Replaced this mapping with four
16KiB pages: f508000/f920000/f928000/f92c000. Actual probe host model now
rejects any other TLMM mapping and checks four pages, sharing adjacent pins.

V3 build build-20261022-140202.log; kernel SHA256
a317296a640811d1d01d0b1ccbb029e2995b5e4312334b0d8506ccf414f5dabb.
Image ports/redfin/out/peripherals-v3/redfin-xnu.img SHA256
2d331f74a30dc6aa1e3892f8985eaaed56d4b210bf23b98cd5ca1e56e7f88dbe.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinfb=1 sweetfb_noconsole=1 redfinscreen=1 redfinshutdown=120 redfinstacks=1 redfintouch=1 redfinusb=1 redfingpu=1 redfinwifi=1 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
V3 completed: all four observers logged with authenticated RAM capture,
no panic; lock-screen final frame present12/CRC611f1077. HFS clean,
inconsistent false, write_count392376, verified fastboot and public key
re-primed. Logs logs/redfin/peripherals-v3/, timeout300,
recovery-adb-only.img, leave-bootloader. 248 host tests pass.
Touch GPIO reset8/bus-select35 remain input/low and QUP0 SE0 clock is off;
SE registers correctly skipped. USB GDSC/clocks on, DWC3 0x5533330a,
AWIDTH64, device mode, RUN_STOP clear and event ring a2448000/4KiB/masked.
PHY/SMMU/DMA route still needs proof. SMEM parser returned PARTITION(5),
not proof of radio absence/readiness. GPU CX/GX collapsed, clocks off.
Next concrete work: RPMh resource/TCS snapshot, source-backed SEC cold
setup/ID read, USB DMA-route handoff, and reusing selected upstream layers.

New upstream source checkouts stay ignored, with no automatic patch import:
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab,
userland906425b75e02b4f99eb5d7bb1ef7c9583472d772. Their Redwood/iOS16.5
port has useful GENI, QMI/network and Mesa/DRM layers. A620/SEC/ICNSS need
our hardware backend; private20F66 addresses/ABI must not be copied to
20H392. USB there depends on a resident EFI loader, not an XNU DWC3 driver.
See the new peripheral documents and UPSTREAM.md for details.

## REDFIN workspace cleanup — 2026-10-22

Removed 15 obsolete generated files (~119.4GiB by allocated-file counts)
and 30 old boot-output directories: pre-install root variants/metadata
clones, duplicate DMG views and incomplete IPSW download pieces. Retained
complete Android rollback backup (~109GiB), intact verified IPSW/extracted
mounts, source/build dependencies, current boot images and both post-keybag
snapshots. Rehashed both retained16GiB snapshots against their independent
saved SHA256 values before deletion; both matched. APFS shares clone blocks;
immediate deletion free-space increase was23.45GiB, resulting free space
282.15GiB. Private exact deletion inventory: research/cleanup-20261022.json.
No device writes were performed by cleanup.

## REDFIN iOS lock screen rendered; MobileGestalt wait fixed — 2026-10-22

V5 completed: HFS clean/write_count374738, authenticated logs and verified
fastboot. Deep lsd stack reached MILaunchServicesDatabaseGatherer /
MIInstallationIdentity / __GenerateBuiltInAppInstallSessionID /
MGCopyAnswer(UniqueDeviceID). MobileGestalt WifiAddress queried missing
/chosen/mac-address-wifi0, then waited for absent IONetworkController.
Native disassembly independently confirmed CFData and length >=6 accepted.
Added only a stable synthetic local-unicast six-byte chosen property; no
radio driver or speculative Bluetooth property. Eight ADT tests pass,
including serialized bytes and preserved hardware nodes.

V6 temporary boot produced authenticated 120x260 framebuffer captures:
first/fifth positive copies show Apple logo; final copy13 shows iOS lock
screen, date/time and camera control (CRC32 28af2874). This proves software
lock-screen rendering; physical panel refresh and interactive input were
not independently checked. Home screen remains unverified; touch and live
USB are unported. LaunchServices progressed beyond the V5 identity wait.
Symbolicated stacks independently confirm lsd now serves its main run loop
with zero MobileGestalt frames (V5: two waiting threads); SpringBoard main
is laying out FCUIActivityControl/MTMaterial views, no _LSCopyServerStore
wait. Its main stack hits the 20-frame cap; no claim of main-loop idleness.
No panic. Ordinary timed shutdown left journaled HFSX clean, inconsistent
false, write_count380188. Collector re-primed the public RAM-log key and
left verified fastboot. No reinstall/repair or boot/GPT/modem/persist/EFS
writes. Android must still not boot before restoring its userdata backup.

Kernel unchanged from the successful deeper-probe build (206 host tests and
actual ARM64 build): research/redfin-build/build-20261022-102326.log;
SHA256 76a697ea59ebc61448181c1921566740490cb77c67932dc59bbd9b5c0e0ce2ff.
Image ports/redfin/out/ios-mg-wifi-v6/redfin-xnu.img;
SHA256 00386f34061efbfeb4a536b6138420aa05ce29fdddaa93862761e53cd504fbdb.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinfb=1 sweetfb_noconsole=1 redfinscreen=1 redfinshutdown=120 redfinstacks=1 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Evidence logs/redfin/ios-mg-wifi-v6/{manifest.json,xnu-console.txt,screens/,stacks.json};
collection timeout300, recovery-adb-only.img, leave-bootloader. Collector
status logs-collected/exit1 is its static-PID1 criterion, not Apple failure.
Next: input/USB bring-up and home-screen validation using automatic evidence.

## REDFIN waiting on LaunchServices; deeper probe running — 2026-10-22

V4 resident-only stack capture worked, quiet framebuffer fixed, HFS stayed
clean and phone returned to verified fastboot. SB main waits synchronous XPC;
second thread is in LSContextInitCommon/LaunchServicesDatabase/
FBApplicationDataStoreRepositoryManager. backboardd also has NSXPC syncwait.
First eight frames do not reach caller; no SB crash. Root/jobs audit found
no missing canonical LS seed/job/ownership. Do not preseed invented LSDB.
V5 raises frame cap20 and includes SB,lsd,securityd,backboardd,launchd in that
priority; threads16 and2s total budget unchanged. 206 tests and actual build
pass. Current build /Users/spiceberries/redfin_ios/research/redfin-build/build-20261022-102326.log
Kernel 76a697ea59ebc61448181c1921566740490cb77c67932dc59bbd9b5c0e0ce2ff
Image 410a890e562d78b61c5fa256c6ec920eb4c62086430ae3cfa0ab1be5e99250a3
Exact args unchanged from V4. Collector running logs/redfin/ios-ls-stacks-v5/.
Symbolication script logs/redfin/ios-display-final-v3/symbolicate-rstack.py;
read DSC path under extracted/mounts/systemos and private .a2s cache.

## REDFIN logo persists; bounded wait-stack probe prepared — 2026-10-22

Finalv3 completed with clean HFS/write_count364664 and verified fastboot.
Final snapshot: present4/positive4/powerOff0, still Apple logo plus console
text; no lock/home screen proved. Found direct kprintf→UART fanout→fbcon
bypassing _cnputs. quiet-display.patch gates only framebuffer drawing, keeps
RAM and panic; actual ARM64 compile and 16 UBSan scenarios pass.
userspace-stacks.patch opt-in redfinstacks1 samples named SpringBoard,
backboardd and launchd: <=16 threads/8 frames,2s budget, resident managed WB
RAM only, pmap try-lock, no suspension/faulting reads. Independent final peer review passed before device boot. Full actual kernel build passed: /Users/spiceberries/redfin_ios/research/redfin-build/build-20261022-095803.log
Kernel SHA256 c74e581caed78e520c9cea6ef39dbacee79fad7649ce35320b0fe71e9927e9d4
Image SHA256 f7bb7e12b7e864bd2f20262cf1de21077db78e7038f7e86f059eb4f67d5b035e
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinfb=1 sweetfb_noconsole=1 redfinscreen=1 redfinshutdown=120 redfinstacks=1 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
206 host tests pass. ios-stacks-v4 is now temporarily booted; collector
running at logs/redfin/ios-stacks-v4/, timeout300, leave-bootloader.
Local ipsw3.1.739 release digest verified; dyld symbol cache built privately.
Historical CADisplay trap resolved to FrontBoardServices FBSDisplayMonitor
_initWithBookendObserver:transformer:+1160; current wait unknown until stacks.

## REDFIN late framebuffer capture running — 2026-10-22

Added final-frame.patch after screen-capture: budget remains three captures,
selected at first/fifth positive CPU presentations and immediately before
reboot_kernel after watchdog feed cutoff. One retained opt-in service and a
dedicated copy/fade/capture lock protect lifetime and complete snapshots;
final lock acquisition is finite and never rearms the watchdog. Logs include
actual present count and powerOff. Decoder permits equal final present counts
while keeping capture IDs ordered and CRC strict.
200 host tests, actual full ARM64 kernel build and peer review pass.
Build research/redfin-build/build-20261022-092936.log, kernel SHA256
dbbe819c9a850a836cbae73ce64258890c4dbd1daa2b3ea5dafda9822f91b7e6.
Image ports/redfin/out/ios-display-final-v3/redfin-xnu.img; exact boot args
unchanged from capturev2 below. Automatic test logs/redfin/ios-display-final-v3/
is running, timeout300, leave-bootloader. Previous capturev2 completed with
authenticated Apple-logo pixels and clean HFS; its collector primed public
ramoops metadata before verified fastboot, which is the starting state here.
No device boot/GPT/modem/persist/EFS partitions have been written.

## REDFIN CPU-copy display and graceful shutdown test — 2026-10-22

User requested continuing after the launchd/backboardd milestone. Added a
separate display overlay: AppleCLCD publishes the observed ABL framebuffer
only with redfinfb=1 and exact Redfin ADT contract. Absolute0xa0000000,
reservation0x02300000,1080x2340/stride4320/BGRA; canvas1125x2436. CPU-copy at
5Hz by default, no inherited modem/GPU/MDP/DSI operations. Command-mode scanout
refresh remains to be observed; registration/frame-copy logs alone do not
prove that the panel displayed a frame.

New opt-in redfinshutdown=5..300 starts a sleepable BSD kernel worker after
root/PID1 setup. Only confirmed PMIC+IMEM return readbacks allow it to extend
watchdog feeds. At its deadline console feeds stop and reboot_kernel(0,NULL)
performs ordinary process shutdown/sync/unmount. Hardware bite remains the
bounded fallback. Initial actual compile rejected MACH-private
thread_terminate_self; supported thread_terminate(current_thread()) fixed it.
Old PID1 NAMEI/OPEN/syscall diagnostics are now gated by redfintrace=1.
Default is off; kprintf and persistent RAM logging stay available.

Preserved the exact post-keybag16GiB root snapshot privately and independently
verified stream/host/device SHA256 aedcf2a94c33c437f357fd43dbb12a3084d486b48e32926abf8e909dd833d3d6.
Native fsck_hfs repaired an APFS clone, then fsck -fn passed. Only two4KiB
blocks differed (offsets0 and532480). Uploaded both via verified RAM files,
fsynced and read back. Full repaired device SHA256 now
086dd9fbcfadbc783a214e1d2ae72cfbeef59685cf8d91d17c57947f0adf2570;
exact primary/tail GPT and original Android metadata still match. No manual
clean-bit modification. Snapshot/plan/logs under ignored
research/ipsw-redfin/root-snapshot-redfin-20261022/.

Actual kernel build research/redfin-build/build-20261022-085809.log passed;
kernel SHA2569ffdda233da9599f26a42c154d00c4a8083d19ee4a39d7ade9933bd037d9c298.
184 host tests, compiled C watchdog/scheduler/geometry harnesses and actual
ARM64 C++ compilation passed; independent display/shutdown review done.
Boot image ports/redfin/out/ios-display-v1/redfin-xnu.img SHA256
4c1d4421a2de347d56dd5ae324ea936c3aaa46191d26a5134a03affa09682885.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinfb=1 sweetfb_noconsole=1 redfinshutdown=120 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
Temporary hardware test and authenticated recovery collector are running at
logs/redfin/ios-display-v1/, timeout300 and verified bootloader return.
No boot/GPT/modem/persist/EFS writes; Android must not boot on this iOS root.

Displayv1 hardware result authenticated: AppleCLCD published1080x2340, backboardd
opened it, created BGRA IOSurface id2 1125x2436/stride4608 and submitted a full
1132B swap. SpringBoard executed once; previous SIGTRAP/CADisplay failure is
absent. This proves display publication/user-client activity, not visible UI.
PMRD restart messages and automatic recovery return were captured. A fresh
recovery reads HFS attrs0x80002100, clean=true/inconsistent=false/journaled=true,
write_count354496: graceful shutdown preserved a clean filesystem.

Missing final presentation/shutdown messages exposed a real logging bug:
serial_console.c _cnputs returns on sweet_console_muted before reaching the
Redfin RAM backend. A follow-on muted-log.patch now preserves those bytes
directly in RAM while pixels stay muted; panic output keeps its original path.
Three compiled C tests cover diagnostic/screen record bytes, embeddedNUL and
empty lengths. Collector now automatically observes the HFS primary header
only for matching ufsroot0 images in verified recovery; dirty headers are
reported without calling them healthy or interrupting log recovery.

Opt-in redfinscreen=1 now captures at most three120x260 RGB thumbnails after
positive CPU copies, into RAM only. Each capture is93600 raw bytes,124800 Base64
bytes. Peer review caught the real IOLog256B buffer limit before any capture
test: final payload chunks are144 raw/192 Base64 bytes,650 records, max233B
including newline. All three captures occupy <512KiB including framing.
Strict host decoder checks geometry, ordered records, fixed lengths and CRC32
before writing PNGs under ignored logs/. Captures are disabled by default.
197 host tests, actual ARM64 build and independent peer review pass.
Latest kernel build research/redfin-build/build-20261022-091542.log SHA256
b92e5c509cd25ccd0a9a849a695b7a75e6915828562ac6d7a4a3c9c53cf50261.
Current image ports/redfin/out/ios-display-capture-v2/redfin-xnu.img SHA256
430f25f312ebfb6b79d6a86860807ca56f34400ce658e0d27959fa1196afa58a.
Exact args equal displayv1 above plus `redfinscreen=1` immediately before
redfinshutdown=120. Fresh clean HFS, full primary/tail GPT captures and Android
metadata SHA were checked again before boot. Automatic test/capture running
under logs/redfin/ios-display-capture-v2/, timeout300, leave-bootloader.
Uncertain-ACK installer recovery additionally requires sync after the matching
full readback SHA; failed final flush cannot report success (25 focused tests).

Capturev2 actual result authenticated and decoded: all three120x260 PNGs pass
CRC32, value6750410c; they show a white Apple logo on black. Each presentation
copied10108800 bytes into the physical Redfin framebuffer.381 exec events/176
unique names; SpringBoard and backboardd each exec once, no SpringBoard crash
or kernel panic observed. Contextstored SIGTRAP occurred during SIGTERM shutdown.
Complete reboot_kernel/proc shutdown/HFS unmount messages are now retained.
Collector automatically observes HFSX clean=true/inconsistent=false,
write_count362104, and verified final fastboot. No additional fsck needed.
Screens are local under logs/redfin/ios-display-capture-v2/screens/.
These are the first three presentations, so they do not establish whether the
home screen appears later. A bounded pre-shutdown capture is the next test;
do not claim a working lock/home screen from the early Apple-logo frames.
Source milestone committed as62f1280; binaries, screen PNGs and logs ignored.

## REDFIN corrected keybag root verified; automatic boot — 2026-10-22

The corrected16GiB root transfer lost its ADB acknowledgement and failed the
full readback. Independent1GiB hashes isolated exactly chunk12. Repaired only
that range using sixteen64MiB RAM uploads, upload SHA checks, bounded raw dd
from regular RAM files, fsync and per-range readback. Toybox0.8.12 does not
support iflag=fullblock. No whole-image rewrite was needed.
`logs/redfin/install-keybag-root-20261022/verification.json` now verifies full
device SHA256 fe211754c7970611f6b94341243d5b7c0b930e57ae032626bd43f13031fea774,
byte-identical primary/tail GPT and unchanged Android metadata SHA against
the original verified backup. Original failed installation report is retained.
Fresh root recovery, unmounted persistent storage and stopped return timer
were checked before repair. A public-key-only ramoops prime and verified
recovery-to-fastboot transition preceded temporary boot of
`ports/redfin/out/ios-root-rw-keybag/redfin-xnu.img` (SHA762e9ea499de56d1b9613793aa09ad61b618f6c82dafc283b84d48c00634866b).
Exact boot args equal the first RW args below; ADT now adds
`/defaults/no-effaceable-storage=u32(1)`. Automatic recovery collection
completed under `logs/redfin/apple-root-rw-keybag/`, timeout180, leave-bootloader.
Authenticated actual log: keybag DONE; usermanagerd, dirs_cleaner and later
boot tasks through launchd_cache_loader passed.330 exec events/154 unique names
include logd, cfprefsd, containermanagerd, backboardd and SpringBoard.36 IOKit
events from backboardd establish actual runtime activity. Kernel panic absent.
SpringBoard SIGTRAP at PC/LR0x1d2d44ca8, backtrace and heap diagnostics retained;
heap scan includes `failed to find the main CADisplay`. It is relaunched later.
Redfin AppleCLCD::start remains disabled; GUI is not working. No unverified
display-enabling change was made. driverkitd also received SIGKILL.
Watchdog returned through recovery and authenticated host logs without user
intervention. A subsequent fresh recovery reads primary HFSX attrs0x80002000:
journaled, no inconsistent flag, but not cleanly unmounted (write_count186134).
Do not retry the RW image until offline journal recovery or a verified reset
to the clean test baseline. Never fake the clean-unmount bit. Future healthy
tests need a sleepable worker calling reboot_kernel(0,NULL) before watchdog
fallback; do not call vfs shutdown from the watchdog/console/IRQ path.
19673 NAMEI trace lines also justify gating the old PID1 diagnostics next.
Boot/GPT/modem/persist/EFS remain unmodified; never boot Android on this root.

Installer transport recovery is opt-in. Exact source EOF/SHA followed by a
lost ACK is uncertain, never success. Host restart and unique serial-matched
Google recovery USB reset are followed by fresh identity/storage/timer proof,
byte-identical GPT captures, sync, full16GiB SHA and final GPT validation.
24 focused installer tests and independent review passed; default behavior
does not reset USB. Full redfin host suite:173 tests passed. Final fresh
recovery checks again verify unchanged primary/tail GPT and original Android
metadata SHA; phone is left in verified fastboot. Device images, keys,
backups and logs remain ignored.

## REDFIN Apple launchd executes; bounded RW first boot — 2026-10-22

`logs/redfin/apple-root-ro-first/` authenticated the actual Apple PID1 boot:
Darwin Ignition, `hello from launchd.1`, system domain creation, fsck and
mount-phase-1. Fatal blocker was mount_hfs EROFS while remounting root; mount[3]
exit1 caused kernel panic. Missing Preboot firmware bindfs source and filesystem
info warnings were nonfatal. No kernel/storage-read or userspace ISA failure.

A separate, independently reviewed RW overlay now compiles after the RO port.
It requires both exact ufsrw=1/rootrw=1, validates HFSX headers and bounds all
writes to the first16GiB of userdata. Default stays RO and raw character writes
stay EROFS. Added strict response/controller ownership validation, FUA flush,
cache sync and permanent no-DMA-reuse poison after uncertain completion.
Actual command/strategy C harness tests fault injection; all165 host tests pass.

Local kernel build `research/redfin-build/build-20261022-071331.log` succeeded;
SHA25699a4aa0dfc2fe1f2687003be2728f96fee53edf479bb98c0482c00ed649b56bd.
Prepared first RW boot SHA256 `3461ab6eaa86d0fb7da3fbc8883183d54977e7a2229305f4cb8c123b96c51854`.
Exact args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0`.
This first RW boot is running; hardware writes and later boot tasks remain
unconfirmed until its recovery log.
RW hardware result now confirmed in logs/redfin/apple-root-rw-first/: HFS
created hotfile B-tree, mount-phase-1/2 and FIPS passed. No post-ACTIVE UFS
command failures/timeouts/poison. keybagd then hit FATAL KEYBAG ERROR kb_load
because systembag.kb was absent. Graceful shutdown reached HFS unmount before
platform Halt/Restart timeout; fresh recovery raw VH confirms persisted clean
bit, journaled HFSX,4194304 blocks4096B and write_count161970.
Missing canonical227B root-owned keybag and ADT no-effaceable-storage are now
fixed in builders. New independently audited host image SHA256
fe211754c7970611f6b94341243d5b7c0b930e57ae032626bd43f13031fea774,
boot SHA256762e9ea499de56d1b9613793aa09ad61b618f6c82dafc283b84d48c00634866b.
Updated clean root is being deployed within the same approved16GiB userdata
installation; previous device state contained only our failed first-boot data.
Original clean1c7 host image and verified original Android backups remain intact. Original Android full backup and metadata
remain verified under ignored backup/redfin/pre-ios-full-20261022/.
Boot partitions/GPT/modem/persist/EFS have not been written. Never boot Android
without restoring the saved userdata image. Collector reports Apple runtime
milestones separately from static PID1 health, including panic state.

## REDFIN installation authorized, backup first — 2026-10-22

The user answered “газик” to the explicit question about installing the prepared
16-GiB iOS16.7.16 image into userdata and losing Android data. This authorizes
that exact userdata overwrite. No backup preference was selected, so use a
full offline userdata plus metadata backup with independent SHA verification
before writing. Boot/vendor_boot/DTBO/GPT/modem/persist/EFS remain untouched.
No installation has started yet. Next: coherent offline backup, installer
--erase-userdata, read-only Apple-root temporary boot and recovery-only logs.

Full offline backup running at `backup/redfin/pre-ios-full-20261022/` using
`backup-userdata.py`: metadata16MiB verified first, userdata117155278848B
streams next with exact count_bytes; independent full device/host SHA follows.
Raw snapshots are0600; host writes fsync/F_FULLFSYNC before acceptance.
Binary dd transport was independently verified on tmpfs with16MiB+13 bytes.
Full offline backup finished successfully: userdata117155278848B plus
metadata16777216B, durable host files and both independent device SHA256 values
matched. Exact hashes and private GPT/state evidence stay in ignored backup.json.
Authorized installation has now started with --erase-userdata; final success
requires the written16GiB SHA256 and unchanged GPT captures.
Installation transfer completed with fsync. Host ADB37 stopped responding during
readback; restarting its server restored recovery. No second write was made.
`logs/redfin/install-apple-root-20261022/verification.json` independently verifies
the full16GiB installed SHA2561c7ab7f21b4075d23ed70f9f2a418f7ae2993d7857c844e7854d3cc076de7478
and identical primary/tail GPT captures. First Apple RO root boot is now running.
Android userdata is now replaced; never boot Android without restoring backup.
Installer now accepts aged recovery only when its live return timer is stopped;
all storage/GPT/timer proofs are repeated before the write.
New Apple boot image `0f127227e2c3998985acc3c5b864255377069992a75d009da76f04c5f0508371` at
`ports/redfin/out/ios-root-readonly-apple/redfin-xnu.img` adds the canonical
Sapphire launchd policy args while keeping UFS read-only. Exact args:
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 -enable_kprintf_spam redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=0 rootrw=0 sweetlog=0`. No kernel rebuild was required.


## REDFIN host-decrypted recovery logs and bootloader return — 2026-10-22

Local kernel build `research/redfin-build/build-20261022-000821.log` succeeded;
SHA256 `bcf892c272c82161ae9e103d52c16783ae305498d7425e830092ca992e89cbb0`. PMIC return is explicitly gated by
redfinreturn=1 and same-boot SPMI/ownership/subtype verification. The masked PON
write and IMEM readback are verified; watchdog performs the later reset.
IRQ masking now covers only the bounded SPMI command, not diagnostic printing.

Saved `logs/redfin/return-bootloader-v2/` ciphertext authenticated successfully:
11 PID1 heartbeats, getpid=1, read4096/EROFS, and
`REDFIN RETURN: PMIC+IMEM bootloader reason verified`.
Google's vendor ramoops keeps its RSA private key under CE userdata. Existing
keypair and exact vendor binary were saved privately under ignored backup/.
`decrypt-ramoops.py` unwraps RSA PKCS#1v1.5 and authenticates AES-GCM on host.
Recovery needs only the public key and vendor `-l -c`, with all libraries already
in its ramdisk. Live `logs/redfin/recovery-ramoops-prime/` verifies public CRC,
cleared AES metadata and no partition writes. Private key never leaves host.

Integrated `logs/redfin/log-autonomous-v1-capture/` reports userspace-alive,
11 heartbeats, authenticated decrypt, verified next-boot public-key priming,
and verified final fastboot. Initial 90-second boot wait was too short because
console progress pets the watchdog for up to60 seconds; use180 or default300.
A start from fastboot lacks a pre-boot baseline: log_freshness is explicitly
unproven rather than claiming saved logs establish this boot's freshness.

Probe boot image SHA256 `347925703e925a8eaee7709a4b7aee3c61080f3141806cbb4dce8dc28bfaa284`.
Exact probe args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 -enable_kprintf_spam redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=0 rootrw=0 sweetlog=0`.
Prepared Apple-root boot SHA256 `d41a134ed16592b77a81e23ab965719e53626d94a11b348a97fb8b9b87a84a62`.
Exact Apple-root args: `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinufs=3 redfinspmi=1 redfinreturn=1 redfinroot=1 ufsroot=userdata ufsrw=0 rootrw=0 sweetlog=0`.

`logs/redfin/install-review-final/check.json` passed live check-only validation;
full16-GiB HFSX image SHA256 remains
`1c7ab7f21b4075d23ed70f9f2a418f7ae2993d7857c844e7854d3cc076de7478`.
No userdata/metadata/GPT/boot partition writes, no Apple launchd boot yet.
Repeat complete cycle `logs/redfin/log-autonomous-v2/` succeeded without Android:
XNU -> fastboot -> temporary recovery -> host-authenticated log -> public prime
-> fastboot. PID1 has11 heartbeats; read4096/EROFS and return readback repeat.
All139 host tests pass. Changes committed as the read-only UFS/offline-log
milestone (commit containing this entry).
Next: obtain explicit userdata-overwrite approval under AGENTS.md; only then
install and debug Apple launchd. Android userdata is intact.
Before waiting for approval, returned the phone to normal Android and verified
ro.product.device=redfin, no offline-recovery marker, sys.boot_completed=1.
Explicit installation approval is pending; no destructive action is authorized.

## REDFIN read-only disk access and full root artifact — 2026-10-21 late

`logs/redfin/ufs-root-uio/` proves PID1 read 4096 bytes from `/dev/rufsroot0`,
write-open rejected with EROFS, and eleven heartbeats. Boot image SHA256
62f36aa8c46fbcfa55bd05feef07ff62c9496375390a7a6c2424590587381159.
The initial raw read panicked in memcpy because physio/B_PHYS left a user VA;
the new redfin raw-read path uses uiomove, retaining PAN and fault recovery.
GPT CRC/capacity/partition and overlap checks precede BSD device publication.
Full root init remains explicit redfinroot=1 and read-only; default md0
boots keep the inherited UFS initialization disabled.

Full official iOS 16.7.16 HFSX image now prepared:
`research/ipsw-redfin/root-image-redfin-fast/ios16-root.img`, 17179869184 bytes,
SHA256 1c7ab7f21b4075d23ed70f9f2a418f7ae2993d7857c844e7854d3cc076de7478.
Fast leaf metadata pass restored 283630 distinct CNIDs in 6.03 seconds; fsck clean.
Native verification confirmed owners/modes, 43 cache hardlinks and 45 critical
files' decompressed-source SHA256/size. No root image has been installed.
The original slower remove/reinsert writer also completed successfully in v2.

ADB-only temporary recovery runtime v3 verified root UID 0, marker 1, unmounted
userdata, no active DM/holders/swaps, exact sysfs/GPT geometry and header CRCs.
Evidence: `logs/redfin/recovery-adb-runtime-v3/`. Recovery's pstore directory
was empty; direct raw ramoops collection is being added for this environment.
The normal Android collector must continue avoiding raw access by default.
The safe recovery image returns to bootloader after 120 seconds, rather than
attempting Android after an HFS installation. No partition writes occurred.

This device's CRC-valid secondary GPT header declares entries_lba 2, referencing
the primary entry array. No matching independent array was found in the tail.
The install checker reports this explicitly and preserves exact primary/tail
capture hashes. Do not rewrite this existing GPT layout during porting.

## REDFIN offline recovery and installation tooling — 2026-10-21

`build-recovery.py` prepares a temporary boot-v3 image using the backed-up
Android kernel and matching vendor recovery resources. The generic ramdisk
overlays both possible init roots; stock recovery UI is disabled because its
Lineage startup mounts userdata to copy ADB keys. Root ADB uses the custom
`ro.redfin.offline_recovery=1` marker, and an independent 120-second service
requests a normal reboot. Current local image SHA256 is
c44f431bf3c63ecb50f069aadaac5d3e451545650fce2e39b1ba46064482cdbe;
runtime verification is separate and no device commands were used to build it.

`install-root.py` defaults to check-only and supports offline evidence replay.
It checks clean, exact-16-GiB HFSX against a successful build/hash, dedicated
root recovery, pseudo-filesystems only, no swap/DM/holders, and userdata sda19
geometry against CRC-valid primary and secondary GPT. The explicit erase path
stops and verifies the recovery return timer, repeats checks, bounds the raw
write by byte count with fsync, then verifies the complete image SHA256 and
both GPT copies. Ten host-only tests pass. No installation was performed;
Android userdata destruction still requires explicit user consent under
`AGENTS.md`. Timer-stop failure or a changed recovery/GPT prevents streaming.

## REDFIN storage and Apple image preparation — 2026-10-21

Query diagnostic kernel SHA256
81953777fdb4caf691dafd95c5bee55a96674d8c7c7da46604eb4c1062bef873
booted successfully, with automatic logs in `logs/redfin/ufs-query/` and
`userspace-alive`. TUR, standard INQUIRY and READ CAPACITY all returned OCS0,
response1/status2, fixed sense `f000021000d0070a00000000000000000000`
(NOT READY, ASC/ASCQ zero). Vendor information 0x1000d007 is not decoded.
Read-only Query READ_ATTR IDN2 succeeded with raw value0x33; READ_FLAG IDN1
succeeded with value0. Do not apply the SCSI active/sleep/powerdown enum to
the Query attribute without a source. Capacity and GPT were not read by XNU.
Primary GPT metadata before/after still matches SHA256
6f8b9cd72c1af239162947e290bbd59b8a20d0101f5a3c788426976158e0b49d.

Separate mode3 (`--ufs-wake-probe`) implements Google's REQUEST SENSE on
Device WLUN0xd0, followed by the exact active-power CDB1b0000001000 with no
data-out, then the existing capacity/GPT checks. Mode2 remains read-only
without power changes. Its first kernel SHA256 is
40ab8507fc10cd134c69b4bef5099f252a8bae682080b14143ea79bdae2aecf1.
Boot succeeded: REQUEST SENSE returned data18
700002000000000a00000000040200000000, START STOP ACTIVE completed with OCS0,
the Query value changed0x33->0x11, and TUR/READ CAPACITY then succeeded.
LUN0 has31211520 blocks of4096 bytes. XNU read GPT LBA1 successfully:
signature valid,19 entries of128 bytes. `logs/redfin/ufs-wake/` again reports
userspace-alive with eleven heartbeats. Host GPT CRC/hash comparison after
this cycle is unchanged. Full UFS root initialization is still disabled;
a separately gated read-only block-device path is being prepared.

All three official Apple images are mounted read-only; prepare.json now
reuses exact matching attachments and preserves previous success on failures.
Original APFS ownership is scanned with owners enabled. A separate read-only
copy view allows reading protected directories; four hidden child inode records
were read directly with pinned apfs-fuse, and all21 protected parent records
were cross-checked. The mode000, zero-byte root .file sentinel is explicitly
recreated. Compression xattrs/resource forks are storage for compressed bytes;
native reads produce decompressed content, so those compression attributes are
not copied. No other source xattrs or BSD flags were found.

The root builder copies natively, links cryptex contents, applies upstream
root tweaks with deferred ownership, then restores final uid/gid/mode by HFS
catalog ID. A local filesystem check is required before accepting an image.
The first full image attempt hit a macOS hdiutil option incompatibility before
copying; the corrected run is under `research/ipsw-redfin/root-image-redfin-v2`.
No image has been installed on the phone and no partition writes are authorized.

Optional `--apple-adt` imports D22AP product properties and development boot
policy from the extracted ADT; Redfin CPU/memory/peripheral nodes are retained.
Identity is synthetic and never copies the Pixel's serial or ECID.

## REDFIN resumed — 2026-10-21 evening

The last pre-stop PAN boot actually succeeded: `logs/redfin/pan/xnu-console.txt`
contains successful console open/write, getpid=1 and eleven PID1 heartbeats.
Kernel SHA256 ff99416071826215cddcb5121ad464aa8cee30bc1603478985f98b131a8b49da.
The collector falsely reported logs-collected because syscall trace split the
banner into multiple writes; recognition now combines banner/getpid/heartbeat
evidence. Current probes independently report userspace-alive.

Fresh root Android DTB saved at `research/redfin-resume/device.dtb`. UFS mode1
register reads succeeded: CAP1587031f, VER300, HCS10f, HCE1, IE0, UTRLDBR0,
UTRLRSR1. Mode2 installed a private high-PA DMA list and received device UPIUs
with OCS0; TUR returned response1/status2 three times, so capacity/GPT reads
were not attempted. Sense diagnostics are the next test. Probe command guard
permits only TUR, standard INQUIRY, READ CAPACITY and one GPT header READ10;
WRITE/SYNC/VPD/other LBAs are rejected. Filesystem/UFS root remains disabled.

Exact SDA GPT header and entry-array CRCs and SHA256 match before/after:
6f8b9cd72c1af239162947e290bbd59b8a20d0101f5a3c788426976158e0b49d.
The broader 64KiB hash changed only outside GPT metadata; gpt.py excludes
padding and validates both CRCs. No partitions have been flashed.

Official iPhone X iOS16.7.16 IPSW downloaded, 6171035648 bytes; SHA256 matches
ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb.
All Apple images stay under ignored research/ipsw-redfin. Native macOS image
preparation is in progress. Local HFS catalog editing has been demonstrated
preserving UID0, Unicode, symlinks and hard links without host sudo.

Current RAM boot args:
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinufs=2`.

## REDFIN bring-up — 2026-10-21

Base: ios-sapphire `d7858e985c4fd2fd41c2c4300c5279cbc8eee178`, reference
ios-topaz `89451b811a4e6cc5cdcf734c45887163d92c599e`. XNU is pinned to
`xnu-8796.141.3` / `1b191cb58250d0705d8a51287127505aa4bc0789`, blacktop
builder `663906528d1cd5ea8fde7de6f16de73db9511549`.

Observed: unlocked Pixel 5, root ADB; saved active-slot boot/vendor_boot/DTBO
and verified SHA256 against the device. Dumps and identifiers remain ignored.
Live DTB confirms GIC 0x17a00000/0x17a60000, MPIDRs 0x000..0x700, timer INTID19,
UFS 0x01d84000. Validated RAM window: 0x180000000+0x80000000, one live bank,
no fixed reservations. Source references: `ports/redfin/HARDWARE.md`.

Temporary diagnostic boot works with boot v3, Image text_offset=0x80000,
LZ4 frame plus LE32 uncompressed size. Changing only text_offset from zero to
0x80000 changed ABL rejection to successful boot. User confirmed the visible
REDFIN DIAGNOSTICS screen; splash0xa0000000, 1080x2340, pitch4320 works here.

XNU builds locally with Xcode27.1 and privately extracted KDK (no cloud build
or system installation). Initial kernel SHA256:
3d33adecd4dda69ad1c8a1a6ed72759bd2cce94c672b5f29c25e8239289cef71.
CPU-trace kernel: ed3909aae905e10129a8832f49d35ecb878de65fd4ca14f897a14762ba1d053c.
Latest build/hash/log paths are in `research/redfin-build/result.json`.

Redfin overlay disables fixed early framebuffer writes and inherited
UFS/display initialization, and supports one CPU. Static Mach-O PID1 and
mockfs payload build without IPSW.

Observed XNU: Darwin banner, pmap/VM, GIC INTID19, machine_init/clock_config/
lockdown, platform expert, AKS, IOSurface and HID. CPU nubs are published but
SweetCPU::start was not reached before the initial hang. Found another unsafe
autostart: SweetBattery runs SM6225 cpufreq and I2C. Disable with
sweetcpufreq=0 sweetbattery=0; permanent driver disable overlay is prepared.

Automatic logs work: DBGC console rings mirrored into both reserved ramoops
banks survive reset; boot-cycle.py retrieves Android pstore and a manifest.
First successful capture: `logs/redfin/ramlog-first/after/console-ramoops-0`.
Do not read /dev/access-ramoops by default: it can claim the alt region during
Android's decrypt service and prevent use_alt=1. This race was observed and
removed. Hardware watchdog starts after relocation: bark28s, bite31s. Its
20-bit counter prohibits the initially considered 60s timeout.

Current boot args:
`debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress -enable_kprintf_spam rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0`.
Next: resolve remaining CPU startup, then observe
`REDFIN userspace: init running as PID 1` and heartbeat. Full iOS storage,
touch/USB/graphics/firmware work remains. No partitions were flashed.

Later observed: disabling SweetBattery and cpufreq resolved the IOKit hang.
CPU0 registers and starts, SGI1 verified, BSD mounts md0 and executes PID1.
`logs/redfin/pid1trace/xnu.txt` records `REDFIN EXEC: result=0` and
`REDFIN PID1: syscall 1 enter code=5`. This proves execution in EL0; opening
/dev/console is the next blocker and the heartbeat has not yet appeared.
Panic output now goes directly to the persistent ring. The host no longer
opens the raw alt bank during normal recovery; automatic pstore collection
works without human screen reports. WDT pets are limited to output progress
for the first 60s, then reset follows within 31s.

## SAPPHIRE port (Redmi Note 13 4G, sapphire/sapphiren) - handoff 2026-10-19

Branch `sapphire`, forked from ios-topaz `topaz` at 5b208e0.

**Verified from the sapphire kernel DT/dtbo (Infinity X 17 tree,
`device/xiaomi/sapphire-kernel/dtbs`, sapphiren overlay = dtbo entry 46,
board-id 0x30022; decompiled copies in `../ios-sapphire-research/`, not in git):**
same SoC as topaz (SM6225 khaje, msm-id 0x206/0x24a) and the same addresses:
GIC 0xf200000/0xf300000, UFS 0x4804000, PS_HOLD 0x440b000, IMEM restart
reason 0xc12565c, cpufreq-hw, splash region 0x5c000000+0xf00000.
Touch: FocalTech `focaltech,fts` at 0x38 on `qupv3_se2_i2c` (i2c@4a88000),
IRQ GPIO80, reset GPIO86, AVDD GPIO36 (identical to topaz).
Volume up: PM6125 GPIO5. Panel `n7_38_0c_0a` 1080x2400 video mode, DSC 1.1
(slice 540x20), 120/90/60 Hz, backlight max 0x7ff (the topaz m7 panels too).

**Differences / unknowns (need the phone):**
- DDR layout: `/memory` is filled in by ABL. The user's phone has ~6 GB;
  `mkadt.py --highmem` assumes topaz's 4 GiB at 0x1_40000000. Read
  `/sys/firmware/fdt` (root) and set the ADT RAM from it, or do roadmap
  item 8 (shim reads /memory from the ABL DTB).
- Touch raw range: topaz FT5452 reports 1350x3000 (patch 0083 scales x4/5).
  The sapphire Linux DT says display-coords 17280x38400, which is the
  Xiaomi driver's range, not necessarily the chip's. Check the chip id and
  raw maxima with the patch 0089 diagnostics before changing 0083.
- ABL: assumed to behave like topaz's (boot v4, drops the boot ramdisk).
  First test = the diagnostic shim (`shim/build.sh` with no payload), RAM only.

**Live phone readings (2026-10-19, sapphiren 6 GB, hwversion 2.39.0; dumps in
`../ios-sapphire-research/live/`, not in git):**
- ABL `/memory` reg: 0x0_40000000+0x3cc00000, 0x0_80000000+1G,
  0x0_c0000000+4G (ends 0x1_c0000000). topaz's 4 GiB at 0x1_40000000 would run
  2 GiB past the end: 37a6936 makes the shim clamp it to 2 GiB.
- Fixed reserved-memory ends at 0x65b00000 (removed_region@60000000); every
  other region is a dynamic pool (alloc-ranges below 4G). Giving xnu
  0xc0000000+4G is a later option.
- Touch: Linux `fts_ts`, FocalTech driver V3.4 20211214, IC ID 0x5452 (same
  family as topaz, so 0083's chip id check passes), tp_info FT3519T, vendor
  0x48 (Samsung panel), FW 0x2f, range 0..17279 x 0..38399 = 16x the panel.
  Likely the FocalTech hi-res report (12-bit panel pixels + 4-bit fraction in
  the pressure byte) instead of topaz's 1350x3000 + 2-bit fraction: confirm
  with the 0089 raw diagnostics before changing 0083's scaling.
- Bootloader unlocked: bootconfig androidboot.verifiedbootstate=orange (the
  ro.boot.* props are spoofed to locked/green by the ROM). Active slot _b.
  userdata = sda18, 115232026624 bytes.

**Done:** 8cc24ec `tools/mkadt.py` sapphire identity. `shim/build.sh` builds
on the server (aarch64-linux-gnu-gcc, `MKBOOTIMG="python3
<aosp>/system/tools/mkbootimg/mkbootimg.py"`).

**Blocked on the user:** a GitHub repo for the kernel CI (macOS runners) and
`gh` auth to download artifacts; the iOS root image needs root + apfs-fuse +
hfsprogs (not on the server: build it on the user's PC/WSL); device access
over the adb tunnel; explicit OK before `fastboot flash userdata`.

## Agent handoff / active work (2026-10-15, latest)

### >>> UPDATE 2026-10-18 (read first, then the 10-17 handoff below) <<<

**sapphire: Adreno 610 bring-up written, not yet run (2026-10-21, patch 0145 `xnu/patches/0145-sapphire-gpu-bringup.patch`, `iokit/Kernel/arm/SapphireGpu.cpp`).** Ported from topaz-woa's `drivers/TopazGpu` + `docs/P8_gpu.md` (their G1 is done under Windows on the same SoC: power-up, zap, identity SMMU, SQE, ring, CP_ME_INIT, CP_MEM_WRITE). Checked against sapphire's own device tree: GPU `qcom,kgsl-3d0@5900000` (0x90000) chipid 0x6010001 "Adreno610v2", GPU CC `clock-controller@5990000` (khaje-gpucc), `kgsl-smmu@0x59a0000`, `gfx3d_user iommus = <&kgsl_smmu 0 1>` (SID 0 mask 1, what the driver programs), and **zap region `gpu_region@55A15000` + 0x2000** — topaz's is at 0x55B15000, this is the one real difference found so far. Buffers the GPU reads live at 0xE1000000 (1 MB), right after the modem pool, below 0xF0000000 and below 4 GB for ADRENO_QUIRK_4GB_VA.

Verified offline (no phone in this session), every register the driver reads or writes:
- **GPU registers**: all 46 dword offsets match freedreno's `a6xx.xml` / `adreno_common.xml` by name, and the three opcodes match `adreno_pm4.xml` (CP_ME_INIT 0x48, CP_SET_SECURE_MODE 0x66, CP_MEM_WRITE 0x3d). The type-7 header encoding matches `pm4_calc_odd_parity_bit` for every opcode/count pair tried (CP_ME_INIT(8) = 0x70c80008).
- **A610 values** against Linux `a6xx_gpu.c` / `a6xx_catalog.c`: khaje is named there as an A610 SoC; SQE `a630_sqe.fw`, zap `a610_zap.mdt`, gmem 128K+4K, quirk 4GB_VA, `a6xx_gmuwrapper_funcs` (no GMU); GBIF_QSB_SIDE 0x00071620, QOS_CNTL 3, ROQ thresholds 0x00800060 / 0x40201b16, MEM_POOL_SIZE 48, AHB_CNTL 1, HANG_INT_CNTL (1<<30)|0x3ffff, UCHE trap base 0x1fffffffff000 (+0xfc0 for WRITE_RANGE_MAX), GMEM range 1 MB .. 1 MB + gmem - 1, FILTER_CNTL 0x804, CACHE_WAYS 4, CLIENT_PF 0x81, the twelve ADDR_MODE_CNTL registers; CP_RB_CNTL fields BUFSZ[5:0] / BLKSZ[13:8] / NO_UPDATE bit 27 give 0x0800020c for a 32 KB ring.
- **Clock registers** against Linux `gpucc-sm6115.c` / `gcc-sm6115.c`: every GPU CC branch and RCG offset, CX GDSC 0x106c with `gds_hw_ctrl` 0x1540, GX GDSC 0x100c with `clamp_io_ctrl` 0x1508 and CLAMP_IO | SW_RESET (hence the BCR pulse at 0x1008), GPLL0 vote 0x79004 bit 15, bimc_gpu_axi 0x71154, memnoc_gfx 0x3600c, snoc_dvm_gfx 0x36018; `P_GPLL0_OUT_MAIN = 5` in both parent maps, so the parent index the driver writes is right for the GMU and the core clock.
- The whole patch series applies cleanly with 0145, and the file compiles with clang `--target=arm64-apple-darwin -Wall -Wextra` against stub headers. `tools/fwtable-file.py` gives the same offset as `filefrag` and the same CRC32 as zlib.

Firmware now travels in the device tree: `tools/mkadt.py --gpu-sqe / --gpu-zap-mdt / --gpu-zap-seg` and `tools/sapphire-boot.sh --gpu-fw DIR` put the blobs in /chosen, and the driver reads them with SecureDTGetProperty before falling back to the partition table (checked: the three properties come out at their exact sizes, and the microcode is byte-identical inside a built boot image). **a630_sqe.fw is already on this server at `/serverhive/angelpro09devv/gpu-fw/` (34188 B, from linux-firmware, md5 9f2540d789d9fd4699a566d97fcabded)** — enough for `gpu=4`, which leaves secure mode by writing RBBM_SECVID_TRUST_CNTL (0xF400) the way Linux does on a device with no zap firmware, instead of CP_SET_SECURE_MODE. `kSuccess` is **1** in xnu-8796, not 0; the driver compares against the symbol.

Next, with the phone: build the kernel (Codemagic), then `tools/sapphire-boot.sh --gpu-fw /serverhive/angelpro09devv/gpu-fw KERNEL out.img "gpu=1"` and read the clock tree, then `gpu=2` (expect `CP_ALWAYS_ON_COUNTER` +~192000 in 10 ms), then `gpu=4` (the command processor with only the open microcode). For `gpu=3` the signed zap shader has to be found first: `a630_sqe.fw` and `a610_zap.mdt/.bNN` are **not** in modem_a (its FAT holds only fpctzapp among the TZ apps), so they are in the vendor filesystem inside `super`; mount it (recovery can, or extract vendor from the ROM zip's payload.bin) and run `tools/fwtable-file.py super --base <vendor offset> ...` into `gpu_fw[]`. If the files are compressed in that filesystem, copy them into the iOS root instead and point the table at `userdata`.

**sapphire: Wi-Fi JOINED a WPA2-PSK network (2026-10-20, Codemagic kernel of 209fca0 = upstream 0129/0130 WLAN station + sapphire 0144 boot-arg join; boot args `sweetusb=2 modem=1 wifi=1 wifi_ssid=... wifi_pass=...`).** Upstream's crypto self-test passes (key unwrap, PBKDF2), the AP is found on channel 6 (2437 MHz), open auth status 0, assoc status 0 (aid 7), the 4-way handshake completes and the pairwise + group keys are installed ~9 s after the modem is up (`*** joined ... ***`); no deauth afterwards. Not yet: a network interface for iOS (topaz_wlan_rx_hook / topaz_wlan_transmit / link hook are there) and DHCP. Note: launchd logs the boot args, so a test image with wifi_pass leaves the passphrase in the phone's logs; keep such images out of git.

**sapphire: modem and Wi-Fi scan work (2026-10-20, kernel CI Codemagic b907929, boot args `sweetusb=2 modem=1 wifi=1`, log `logs/sapphire-wifi2.txt`).** Patch 0130 adds sapphire's modem_a tables (generated by `tools/fwtable-modem.py` from a read-only dump of the phone's modem_a; same SoC, carveouts and file set as topaz, other offsets) and picks them by the modem.mdt CRC. PAS auth_and_reset ret 0, MODEM READY, 45 QMI services, WLFW: chip_id 150 (WCN3988), board data image/bdwlan.bin, FW_READY, mission mode, HTC/WMI/HTT ready, passive scan: 12 networks (2.4 and 5 GHz). Note: SCM assign of the WLAN MSA regions returns -2 (res 0x56) yet the firmware runs. Also on sapphire: USB CDC-ECM (patch 0129, usbipd into WSL, live log UDP 5140), touch range by boot args (0127), Codemagic builds with Xcode 16 (0128). Next for Wi-Fi: association (WPA2 4-way), HTT data path, an IONetworking interface for iOS.

**LIVE LOG over USB (0077, boot 0077s): no more recovery round-trips.** Boot an image with `sweetusb=2`, run `tools/sweet-usbnet.sh logs/live-NAME.txt` on the PC: it waits for the phone's CDC-ECM interface, sets 192.168.7.1/24 (sudo) and prints/saves the kernel console the phone streams every 100 ms as UDP to 192.168.7.1:5140 (starts with the last 64 KiB). `ping 192.168.7.2` checks the link. Current image: `shim/out/shim-boot-0077s.img` (kernel 0077, ADT sweet-0069hi, cpus=6, sweetfb_noconsole=1, sweetfb_hz=30, sweetusb=2). The recovery pull (`tools/sweet-log-pull.sh`) is still the way after a panic/hang before USB comes up.

**🎉 USB networking works (boot 0076s, 18:24 local): `ping 192.168.7.2` from the PC answers in ~1 ms, 0 % loss (200-packet burst, 1500-byte frames, 512/1024-byte frames).** 0075: CDC-ECM function (bulk 0x81/0x01, interrupt 0x82 NETWORK_CONNECTION; host MAC 02:00:5e:77:ee:01) + kernel ethernet ifnet `ue0` (legacy output, header strip like if_fake) with 192.168.7.2/24 set from the kernel (proto_plumb + SIOCAIFADDR on an in-kernel socket). 0076: received frames into one cluster mbuf (mbuf_allocpacket gave a first mbuf of length 0 -> panic "Failed mbuf validity check: len -14"). Host side (Linux cdc_ether, interface `enp0s20f0u3u1`): `nmcli dev set IF managed no; sudo ip addr add 192.168.7.1/24 dev IF; sudo ip link set IF up`. Boot image `shim/out/shim-boot-0076s.img` (`sweetusb=2`). iOS itself does not see ue0 yet (configd needs an IONetworkInterface in IOKit).

**USB device mode works (boot 0074s, 17:45 local): the host enumerates the phone at high speed as `1209:0001 ios-sweet "Sweet iOS (USB bring-up)"`.** 0072 read-only probe: ABL leaves the USB30_PRIM GDSC and all 7 USB clocks on, DWC3 v3.20a (GSNPSID 0x5533320a) in device mode (GCTL 0x00112000), halted (DCTL RUN_STOP 0, DSTS 0x00d3de04), event buffer still at ABL's 0xfdfc8000, QUSB2 PHY alive. 0073 (`sweetusb=2`): DCTL soft reset, own event buffer (polled, interrupt masked), ep0 DEPSTARTCFG/SETEPCONFIG/SETTRANSFRESOURCE, setup TRB, RUN_STOP; control-transfer state machine as Linux ep0.c; descriptors: vendor class, no data endpoints. It ran but no event came: **0074** forces the VBUS session in the Qualcomm wrapper (QSCRATCH 0xa6f8800: HS_PHY_CTRL |= UTMI_OTG_VBUS_VALID(20)|SW_SESSVLD_SEL(28), SS_PHY_CTRL |= LANE0_PWR_PRESENT(24), as Linux dwc3_qcom_vbus_override_enable) -> connect + enumeration. Image `shim/out/shim-boot-0074s.img`. Black Phone app: main thread waits in -[VMVoicemailManager fetchAccounts] (sync XPC; voicemail needs the modem).

**Navigation works (boot 0071s on v14, log `logs/boot-0071s.txt`):** swipe up from the bottom edge returns to the home screen; app switcher works. Two fixes: **0070** pid_hibernate (syscall 435 was nosys on the macOS config -> SIGSYS killed SpringBoard in -[SBToAppsWorkspaceTransaction _didComplete] when an app left the foreground; the only CONFIG_EMBEDDED-only entry in syscalls.master); **0071** touches starting within 48 px of an edge carry kIOHIDDigitizerEventFromEdgeTip (UIKit `_UIEventHIDTouchEdgeTypeForHIDEvent` reads the digitizer EventMask 0xb0007 bits 0x800/0x1000/0x2000/0x40000). Diagnosed, not fixed: Settings (Preferences) SIGTRAP in PodcastsUI func_1cdc47c58: force-unwrap of `URL.volumeTotalCapacity` (nil on our HFS+ root). Phone/Photos/Messages show black (MobilePhone launches, no crash) - next: stack samples via boot-arg `sweetsample=MobilePhone,MobileSlideShow,MobileSMS,SpringBoard` (image `shim/out/shim-boot-0071s.img`).

**🎉🎉 MILESTONE 2026-10-18 ~15:30 local: iOS 16.7 SPRINGBOARD HOME SCREEN ON THE PHONE** (boot `shim/out/shim-boot-0069s.img` = kernel 0069 + ADT `shim/out/sweet-0069hi.adt`, image **v14**; log `logs/boot-0069s-v14-HOMESCREEN.txt`). Home screen with a few apps, Settings opens, Control Center / lock screen / notification center work, touch + buttons work, 6 A55 cores (`cpus=6`), `sweetfb_noconsole=1 sweetfb_hz=30`. Known issue: cannot leave Settings (home gesture / AssistiveTouch home do nothing) - to investigate.
What it took today (in order): 0058 HID services (Apple IOHIDFamily-1915 user client), 0059 iPhone X identity (hw.product etc.), 0060 SPMI keys + GENI touch, 0061 1125x2436 presented display, 0062 RPMh L11C touch power + IOPMPowerSource battery, 0063 GENI FIFO packing (Goodix GT9896), 0064 PRIV_WORK_INTERVAL grant (SpringBoard "Failed to create work interval"), 0065 SMP via PSCI (6 A55), 0066 crash map regions, 0067 console mute without cons_ops write, 0068 IOSurface lookup of an already-mapped surface returns base -1 (backboardd snapshot crash), 0069 UFS log flush 10 s. Image v13: CommCenter removed from launchd.plist, BKNoWatchdogs. **Image v14** = v13 + Setup skipped (`/var/mobile/Library/Preferences/com.apple.purplebuddy.plist` SetupDone/SetupFinishedAllSteps true, SetupVersion 11, daemonizeNeedsToRun false; purplebuddy.notbackedup mini-buddy flags false; managedconfiguration.notbackedup LockdownActivationIndicatesCloudConfigurationAvailable false; springboard MCForceShowCloudConfigurationUI false) + mobileactivationd data ark seeded (`/private/var/containers/Data/System/D90C94C4-F94E-4FCF-8A28-A93BE3846D8E/Library/internal/data_ark.plist`, -ActivationState Activated etc.) + MediaToolbox D22/D221/Default SubServerConfiguration StartRecorderServer=false (mediaserverd crash loop: portrait-filter prewarm called NULL GL). **Activation:** ADT /chosen certificate-production-status 0, effective-production-status-ap 0, certificate-security-mode 1, effective-security-mode-sep 1 -> mobileactivationd's native Hactivation branch (Codex `codex/activation/report.md`; alternative 4-byte daemon patch documented there). Fallback image v13; v12 deleted.

**🎉 TOUCH WORKS (boot 0063u on image v13, 2026-10-18 ~13:15 local):** tapping (i) on Setup's Hello opens the device-info sheet; swipe-up is recognised (spinner, then back to Hello - under investigation). Chain: RPMh L11C vote (0062, `bsd/dev/sweet_rpmh.c`) -> GT9896 @0x5d on GENI SE7 (0063 fixed FIFO packing: register address went out byte-swapped) -> sweet_hid_touch -> SweetHIDTouch -> backboardd. Battery icon OK (0062 SweetBattery IOPMPowerSource, static 100 %). **Image v13** (= v12 + CommCenter jobs removed from launchd.plist + `BKNoWatchdogs`=true and `FBLaunchWatchdogExceptions{com.apple.purplebuddy:100}` in /var/mobile/Library/Preferences/com.apple.springboard.plist): Setup no longer killed by the scene-create watchdog (it blocked in CoreTelephony getSubscriptionInfo -> CommCenter, Codex `codex/setup/report.md`; that report also lists how to skip Setup: SetupDone/SetupFinishedAllSteps/SetupVersion=11 in com.apple.purplebuddy.plist + activation check). v9 deleted, fallback = v12. Input latency ~1 min with 1 CPU -> Codex task 11 = SMP via PSCI (`codex/smp/`).

**INPUT WORKS (boot 0060u on a freshly flashed v12, log `logs/boot-0060u.txt`):** power, volume up, volume down reach iOS (PMIC -> sweet_keys.c -> SweetHIDButtons -> backboardd). Power locks/unlocks (screen "off" shows the kernel console because the panel never really turns off). **Device identity fixed: iPhone X** (home indicator, Face-ID-style Setup). Earlier test (0059u, `sweethidtest=15` fake Home presses) advanced Setup from Hello to the language list.
- **0058** HID: `iokit/Kernel/arm/hid/`: IOHIDEventServiceUserClient + IOHIDEventServiceQueue + IOHIDEvent compiled UNCHANGED from Apple IOHIDFamily-1915.140.3 (= exact version of the iOS 16.7 IOHIDLib, clone in `research/iohid-1915`) over our minimal IOHIDEventService (SweetHID.cpp: SweetHIDButtons consumer page 0x0C power 0x30 / vol 0xE9/0xEA / menu 0x40; SweetHIDTouch digitizer collections). C hooks `sweet_hid_key(key, down)` (0 power, 1 vol+, 2 vol-, 3 home) and `sweet_hid_touch(finger, down, x, y)`. HID logs go to IOLog. Boot-arg `sweethidtest=N` = fake Home press every N s.
- **0059** identity: hw.machine/hw.model/hw.target/hw.product from the ADT (macOS-config kernel used to answer "iPad8,6"/"Redmi Note 10 Pro"). mkadt: root compatible `D22AP|iPhone10,3|xiaomi,sweet|...`, model iPhone10,3, target-type D22, `/product` copied from the real D22AP device tree (`research/ipsw-x/d22ap.adt`, extracted from the IPSW, NOT in git), `/buttons home-button-type 2`. Codex report `codex/mg/report.md`: MG ProductType = sysctl **hw.product** (unrecognized -> iPod), HWModelStr = hw.target, HomeButtonType = `/buttons/home-button-type`; disk cache `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist` (keyed by build + UUID only -> stale iPod answers survived; reflashed clean v12 to clear it).
- **0060** drivers by Codex (`codex/input/hw-report.md`): `bsd/dev/sweet_keys.c` (SPMI arbiter v5 observer reads, PON 0x810 bits KPDPWR/RESIN SID0, PM6150L GPIO2 SID4 0xc110; works), `bsd/dev/sweet_touch.c` (GENI SE7 I2C @0xa84000, starts 45 s after boot). Touch result: SE7 fw ok (proto 3) but **0x5d and 0x38 both time out -> touch IC unpowered** (L11C LDO needs an RPMh vote). Codex task 8 = RPMh client (`codex/rpmh/`), task 7 = battery (`codex/battery/`).
- **0061** (CI 39117078444): red status bar "rdar:45025538" = UIKit "No status bar visual provider for screen" (360x800 pt is no real iPhone). AppleCLCD now presents **1125x2436** (iPhone X) and shows the centered 1080x2400; touch mapped the same; ADT canvas 1125x2436. `sweetfb_native=1` reverts.
- Images: `shim/out/shim-boot-0060b.img` (0060 + /buttons ADT `sweet-0060hi.adt`). Next: 0061 image with ADT from current mkadt.

### >>> HANDOFF 2026-10-17 late (read this first) <<<

**STATE: iOS 16.7 Setup.app "Hello" screen is ON THE PHONE** (boot `shim/out/shim-boot-0057u.img` on image v12). Photo `/run/media/dipa/android/ios-sweet-work/MILESTONE-setup-hello-2026-10-17.jpg`. SpringBoard + backboardd + Setup run; nothing crashes in the GUI path. Remaining crash/relaunch loops: installcoordinationd (should be fixed by 0057, unverified), mediaserverd (VirtualAudio removed in v12, unverified), mobileactivationd (~100/boot, not analysed), bluetoothd + fairplayd.H2 relaunch constantly (no hardware).

**What is on the phone now:** userdata = image **v12** (`/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v12.img` + `.simg` + `.sha256`; v9 kept as fallback, v8/v10/v11 deleted or superseded). Kernel **0057** (`xnu/out-0057`, CI `39067532732`). ADT **`shim/out/sweet-0057hi.adt`** (QEMU twin `research/q0057-hi.adt`). Boot image **`shim/out/shim-boot-0057u.img`**. Boot args: `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1`.

**Build a phone image** (kernel K, ADT A): `python3 tools/mkpayload.py $K $A shim/out/payload-X.bin --cmdline "$B" && (cd shim && ./build.sh ../shim/out/payload-X.bin && cp out/shim-boot.img out/shim-boot-X.img)` then check `python3 tools/unpack_bootv2.py shim/out/shim-boot-X.img shim/out/check-X && cmp shim/out/check-X/ramdisk shim/out/payload-X.bin`. QEMU smoke test: `python3 tools/mkpayload.py $K research/q0057-hi.adt $S/csq/payloadX.bin --ramdisk $S/csq/root-fork.img --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=md0"` + `PATH=~/swift/usr/bin:$PATH python3 tools/qemu-sweet.py ... --secs 40 --kernel $K --fail-on-panic` (S = scratchpad; root-fork.img lives in the session scratchpad csq/ dir and may be gone in a new session).

**Kernel workflow:** edit `research/bt28/xnu/...` (keep the pre-edit copy in `research/preNNNN/`), syntax check `python3 tools/xnu-cc.py research/run28.log research/bt28 <file>`, make `xnu/patches/NNNN-*.patch` with `diff -u pre bt28 | sed` path rewrite, add new/changed files to `research/check-patch-order.py` list, run it (must say applied + MATCH), commit + push -> GitHub Actions `xnu` builds (~8 min) -> `gh run download <id> -R dipa-studio/ios-sweet -n xnu-kernel -D xnu/out-NNNN`. **Repo is PUBLIC since 2026-10-17** (private macOS runner minutes ran out: "recent account payments have failed"); public = free runners. Commit trailer: only `Co-Authored-By: dipa-studio <183933817+dipa-studio@users.noreply.github.com>`.

**Phone workflow (user does buttons, Claude runs commands):**
- Boot test kernel: phone in fastboot -> `fastboot boot shim/out/shim-boot-X.img`. NEVER `fastboot getvar`.
- **Read logs WITHOUT filming:** after a test the user holds Power+VolDown -> fastboot -> `fastboot boot recovery/recovery.img` (OrangeFox, temp) -> wait for `adb shell true` -> `tools/sweet-log-pull.sh /run/media/dipa/android/ios-sweet-work/logs/<name>.txt` (reads the 4 MiB console ring the kernel keeps in the last 1025 blocks of userdata; patch 0047). Then `adb reboot bootloader` brings the phone back to fastboot without the user.
- **Flash a root image:** `fastboot flash -S 512M userdata <img>.simg` (7 min, 25 chunks). After a big flash the Xiaomi ABL fastboot hangs: next `fastboot boot` stalls at "Sending" -> the USER must re-enter fastboot by hand (Power+VolDown). Do not retry commands against the hung ABL. A flash right after `adb reboot bootloader` once failed on chunk 1 (USB protocol error): just retry. User must NOT unplug during flash (once interrupted at 25/25 -> reflash).
- **Edit the phone root without reflashing (same-length only):** find the file's raw offset in the local image (it is one extent; search the image for its first 4 KiB), compare with `adb exec-out dd if=/dev/block/sda34 ...`, then `adb push` changed 4 KiB blocks and `dd of=/dev/block/sda34 seek=... conv=notrunc,fsync`, read back. Recovery kernel has no hfsplus.
- **Pull the whole phone root** (12 min): `adb exec-out "dd if=/dev/block/sda34 bs=1048576 count=16384" > img`; mount ro with udisksctl or `sudo mount -t hfsplus -o loop,ro`. To write into a pulled image: `sudo fsck.hfsplus -fy` first (volume is never cleanly unmounted -> Linux mounts ro even with -o force), then `sudo mount -t hfsplus -o loop,force`.
- Making images: copy latest img with `cp --sparse=always`, mount rw with force, change, `sync; umount`, `sha256sum`, `img2simg`. Keep only the latest image + one fallback on the SSD (/home is ~98% full; big work files live in `/run/media/dipa/android/ios-sweet-work/`, old kernels/images archived in `.../ios-sweet-work/archive/`).

**Diagnostics built into the kernel (all SWEET-only):** persistent console log (0047, boot-arg sweetlog=0 off; flush every ~1 s); `|name| text` copies of /dev/null writes for processes in `sweetnull` (default backboardd,SpringBoard; 0048); `IOK name:` IOKit lookup/open trace for `sweetiolog` (default backboardd,SpringBoard; 0049/0054, 400 lines max); `SWEET Sandbox: proc op N` (0050); `STR ...` heap text dump on SIGABRT/SIGTRAP for `sweetscan` (default backboardd,SpringBoard; 0051/0053) - this is how NSException/BSAssert reasons were found; `SMP name tN pc .. bt ..` user stack sampler for `sweetsample` (default SpringBoard,backboardd; first at 90 s then every 120 s, 40 samples, 16 frames; 0054/0055); `SWEET FB: N swaps` every 1000 swaps; `CRASH name ...` crash reports (0043/0044). Symbolicate cache addresses with `ipsw dyld a2s research/dsc/dyld_shared_cache_arm64 <addr - slide>`; main-binary addresses: addr - mh + 0x100000000.

**Patches added today (0046-0057, all CI-built):** 0046 IOSurface (IOCoreSurfaceRoot) + IOMobileFramebuffer (AppleCLCD on /arm-io/disp0) + arm-io nubs; 0047 persistent log; 0048 /dev/null tee; 0049 IOKit trace; 0050 permissive "Sandbox" MAC policy; 0051/0053 heap text on crash; 0052 RENAME_SWAP via exchangedata on HFS; 0054/0055 sampler, swap counter, AKS selectors 35 (extended device state = 17) and 101; 0056 panel copy from the vsync timer at 10 Hz (sweetfb_hz) instead of every swap; 0057 no config_ext_resolver (ACL group entries resolve without memberd). ADT (tools/mkadt.py): /arm-io/disp0, /chosen/display-scale 3, /chosen/unique-chip-id (synthetic 0x5357454554000001) + chip-id 0x8015 -> IOPlatformUUID A9683613-3704-53F2-95D0-98A8FB574E78. Image v9-v12: /private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}; launchd.plist StandardOut/ErrorPath renamed to ...PatX (pointing jobs at /dev/console stops them launching: EACCES); v12: LastSystemVersion=20H392 in plain /var/mobile/Library/Preferences/com.apple.migration.plist (stops the 1-hour data migration that ran every boot), VirtualAudio.plugin moved to /Library/Audio/Plug-Ins/HAL.disabled/.

**Codex helper** (`codex exec --skip-git-repo-check -m gpt-6.1-sol -c model_reasoning_effort=high -s workspace-write -C /run/media/dipa/android/ios-sweet-work/codex -o OUT "$(cat task.md)" < /dev/null`, run detached with setsid nohup; config already defaults to gpt-6.1-sol high). Reports in `/run/media/dipa/android/ios-sweet-work/codex/`: mediaserverd-report.md, installcoordinationd-report.md (-> 0057), ufs-performance.md (ranked UFS speed plan), **ufs/0058-sweet-ufs-faster.patch** (READY, not yet applied: ufslogsecs default 10 s log flush batching, optional ufscache=1 directional cache ops, optional ufswait=1 spin-then-sleep; syntax-checked, host-stub verified; see ufs/README.md). Apply it as patch 0058 after review.

**Claude safety-classifier note:** several messages about QuartzCore renderer selection / writing an HFS reader tool were cut off by an automatic classifier (false positives, user agrees). Keep those topics short or let them be; they are not blockers now (rendering already works).

**NEXT STEPS (in order):**
1. **Input** (Setup stuck on Hello): touch + power + volume as IOHIDEventService/IOHIDDevice services backboardd matches (log shows backboardd matching IOHIDDevice with DeviceUsagePairs and IOService with HIDServiceSupport=true). Phone hardware: Goodix/Focaltech touch over I2C/SPI (check live DT `dtb/`), buttons via PMIC (pon) and GPIO keys. Start with a fake HID service (e.g. power button via a timer or boot-arg) to learn the ABI, then real drivers.
2. **Device identity**: MobileGestalt reports iPod + Home button. Add /product node / product-type (iPhone10,3, D22AP), device class iPhone, home-button-less (Face ID) properties in mkadt; find exact MG keys (MGIOMFBSupport.c, `IODeviceTree:/product` lookups seen in backboardd trace).
3. **Battery**: AppleSmartBattery/IOPMPowerSource style service (status bar shows empty red battery).
4. Apply Codex 0058 (UFS speed), consider cpus>1, check whether installcoordinationd/mediaserverd loops are gone, analyse mobileactivationd.
5. Hide kernel console over the GUI when not debugging: boot-arg sweetfb_noconsole=1 (but then panics are not on screen).

- **🎉 MILESTONE: iOS GUI ON THE PHONE - Setup.app "Hello" screen (2026-10-17 ~21:30 UTC, boot 0057u on image v12).** Photo: `/run/media/dipa/android/ios-sweet-work/MILESTONE-setup-hello-2026-10-17.jpg` (animated "dobar d(an)" hello lettering, status bar "iPod" + battery icon, bottom "Pritisnite Home za otvaranje" = "Press Home to open" (locale hr), (i) button). Rendered by iOS 16.7 SpringBoard/Setup through CoreAnimation -> backboardd -> kernel IOSurface (IOCoreSurfaceRoot) -> kernel AppleCLCD swaps -> ABL panel memory. What made it: data migration finally skipped (v12: `LastSystemVersion` 20H392 in the plain `/var/mobile/Library/Preferences/com.apple.migration.plist`; ADT `/chosen/unique-chip-id` + `chip-id` for IOPlatformUUID), 0057 (no ext resolver -> ACL containers work), plus everything before (0046 display/IOSurface, 0050 Sandbox policy, display-scale 3, containers dirs, RENAME_SWAP, AKS 35/101, 10 Hz present).
  **Missing (next work, in rough order):**
  - **Input: no touch, no power button, no volume buttons** (no HID drivers; backboardd looks for IOHIDDevice / HIDServiceSupport services). Setup is stuck on "Hello".
  - **Device identity: it thinks it is an iPod with a Home button** (status bar "iPod", "Press Home to open"): MobileGestalt has no product/model identity (no /product node, product-type, etc.) - give it iPhone10,3 / home-button-less (Face ID class) identity.
  - **No battery detection** (no battery/charger/PMIC service; status bar battery shows empty/red).
  - Locale came up Croatian (hr) - harmless.
  - Performance: cpus=1, polled UFS (Codex UFS patch in progress: `codex/ufs/`), backboardd presents at 60 Hz.
- **README refreshed (2026-10-17):** read the full notes and updated the public overview through patch 0045, v7 hardware observations and prepared v8 diagnostics. Documents real Apple userspace, the missing display/IOSurface GUI work, limited security services, highmem, persistent userdata root, current tooling and build examples. Documentation only; no kernel build, tests, flashing or phone boot performed.

- **v11 still migrated (boot 0056u, 20:32 UTC, `logs/boot-0056u-v11.txt`).** On iOS kCFPreferencesCurrentHost lands in the plain plist: all DMEnvironment setters (setLastBuildVersionPref, setUserDataDispositionPref, ...) use CurrentHost and the phone's `/var/mobile/Library/Preferences/com.apple.migration.plist` holds DMUserDataDisposition; datamigrator's XPC service runs with `_RoleAccount: mobile`. **Image v12** = v11 + `LastSystemVersion` = 20H392 added to that plain `com.apple.migration.plist` (keeps DMUserDataDisposition, 501:501 0600) + `/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin` moved to `/Library/Audio/Plug-Ins/HAL.disabled/` (Codex: stops the mediaserverd SIGSEGV loop; untested). **installcoordinationd loop explained (Codex `codex/installcoordinationd-report.md`):** os_crash "Failed to create data directory" EACCES for `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.installcoordinationd/Library/InstallCoordination`: `Library`/`Library/Caches` in the container are ACL-only (uid/gid 0xfffffffe, mode 0000, ACE for group GUID ...012B = gid 299 systemusers); with `config_ext_resolver` the kernel asks an identity resolver (memberd/opendirectoryd) that iOS does not run -> EWOULDBLOCK -> ACE skipped -> EACCES. **Patch 0057**: drop config_ext_resolver from FILESYS_BASE (compatibility UID/GID<->GUID mapping is used instead), likely fixes other ACL-protected containers too. Codex task 3: UFS driver performance design (`codex/ufs-performance.md`).
- **mediaserverd SIGSEGV loop explained (Codex report `/run/media/dipa/android/ios-sweet-work/codex/mediaserverd-report.md`):** the fault (FAR 0x390) is in the HAL plug-in `/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin/VirtualAudio` (ApplyBeamFormerPreference <- VirtualAudio_PlugIn::SetPropertyData <- HALS_AHPPlugIn::ObjectSetPropertyData <- AudioObjectSetPropertyData <- MediaExperience vaemVADSerializationListener): the default virtual audio device ('vdef', VirtualAudioDevice_Default) does not exist (no audio hardware/driver, no /product/audio). Proposed workaround for GUI bring-up: move VirtualAudio.plugin out of /Library/Audio/Plug-Ins/HAL/ in the next root image (untested). v11 reflashed OK after an interrupted flash (USB unplugged at chunk 25/25). Codex task 2: installcoordinationd crash loop.
- **ROOT CAUSE of the endless migration: no IOPlatformUUID (2026-10-17).** datamigrator's `-[DMMigrator isMigrationNeededWithBuildVersion:lastBuildVersion:clientPID:]` gets lastBuildVersion from `-[DMEnvironment lastBuildVersionPref]` = `CFPreferencesCopyValue("LastSystemVersion", "com.apple.migration", kCFPreferencesCurrentUser, kCFPreferencesCurrentHost)` -> a ByHost file. The phone had `/var/mobile/Library/Preferences/com.apple.migration.plist` (only DMUserDataDisposition) and NO `Preferences/ByHost` directory at all. On arm XNU publishes IOPlatformUUID (gethostuuid) only from `/chosen/unique-chip-id` (8 bytes) + `/chosen/chip-id` (4 bytes) (IOPlatformExpertDevice::generatePlatformUUID, called from IOPlatformExpert::start); the SWEET ADT had neither, so every CurrentHost preference write failed. Fix: mkadt adds `unique-chip-id` = 0x5357454554000001 (synthetic) and `chip-id` = 0x8015 -> UUID `A9683613-3704-53F2-95D0-98A8FB574E78` (same SHA1 namespace computation as the kernel). ADT `shim/out/sweet-0057hi.adt`, boot image `shim/out/shim-boot-0056u.img` (0056 kernel + 0057hi ADT, QEMU OK). **Image v11** = v10 + `Preferences/ByHost/com.apple.migration.<UUID upper and lower>.plist` {LastSystemVersion: 20H392} (501:501, dir 0755 files 0600). Flashing v11 2026-10-17 ~20:10 UTC. Codex (gpt-6.1-sol high) analysing the mediaserverd SIGSEGV loop in `/run/media/dipa/android/ios-sweet-work/codex/` (report `mediaserverd-report.md`).
- **v10 did NOT stop the migration (boot 0056n on v10, 19:18 UTC, `logs/boot-0056n-v10.txt`):** datamigrator + migrationpluginwrapper ran again, backboardd drew the progress UI (13000+ swaps in ~5 min). So `com.apple.DataMigration.plist`/LastSystemVersion is not the deciding input. What is known about the decision (datamigrator XPC service `DataMigration.framework/XPCServices/com.apple.datamigrator.xpc/com.apple.datamigrator`, strings): `Migration sentinel present. Migration necessary.` (sentinel `/private/var/datamigrator/migrate`, created and removed by datamigrator itself; absent in v10), `System build version changed from %@ to %@. Migration necessary.` / `...unchanged... not necessary`, `Disposition dictionary with build version %@ is out of date relative to current build version %@`, `SyntheticDidUpgrade`, DMUserDataDispositionManager; previous build source not found yet (not in the binary's plain strings; likely in DataMigration.framework's DMUserDataDispositionManager / preferences domain `com.apple.migration`). backboardd calls `DMPerformMigrationIfNeeded` and holds SpringBoard in `checkInAndWaitForDataMigration` until it returns. NEXT: find where the previous build version / disposition dictionary is stored (disassemble DataMigration.framework DMUserDataDispositionManager + datamigrator's isMigrationNeeded path), write it into the image; or get datamigrator's os_log out (OS_ACTIVITY_DT_MODE needs a launchd env change).
- **Data migration never records completion -> skip it (image v10, 2026-10-17).** Boot 0056n (18:16 UTC, `logs/boot-0056n.txt`, 30 min): 10 Hz panel copies, backboardd still presents at ~60 Hz (107k swaps), SpringBoard still in `BKSSystemShellService _checkIn` at sample 14. Every migration run takes 1+ hour on cpus=1 and repeats each boot. DataMigration decides from `/var/mobile/Library/Preferences/com.apple.DataMigration.plist` key `LastSystemVersion` (vs ProductBuildVersion 20H392); the pulled phone root (21:01 local) had NO such file. **v10** = that pulled phone state + fsck.hfsplus -fy (volume was marked not cleanly unmounted -> Linux mounts it read-only even with -o force; fsck found only hard-link counts + minor volume header, repaired) + `com.apple.DataMigration.plist` {LastSystemVersion: 20H392} (501:501 0600). `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v10.img` (+ .sha256, .simg); v8 files deleted, v9 kept as fallback.
- **Repo made PUBLIC (2026-10-17, user request) so GitHub-hosted macOS runners are free:** the 0056 CI run was refused ("recent account payments have failed or your spending limit needs to be increased"). Checked before: no device dumps, serials, IMEI or Apple binaries in the history (.gitignore keeps backup/, dtb/, recovery/, research/ out); commit author emails are public now. 0056 rerun `39056660104` passed -> `xnu/out-0056`, QEMU OK, image `shim/out/shim-boot-0056n.img` booted 18:16 UTC.
- **Boot 0055n (17:16 UTC, ~65 min, `logs/boot-0055n.txt`): migration bar reached 99% in ~30 min (was ~60), then crawled.** Root cause of the slowness: backboardd presents the progress UI at ~58 Hz (**167,000 swaps in ~48 min**) and AppleCLCD copied the full 10 MB frame into the panel on every swap -> ~600 MB/s memcpy on the single CPU (cpus=1), starving everything (polled UFS I/O too). Sampler (16 frames): **SpringBoard waits in `-[BKSSystemShellService _checkIn]`** (synchronous BSXPC call to backboardd, from FBSystemShellInitialize <- SBSystemAppMain) - backboardd holds the system shell check-in until the data migration ends, so the migration is the gate to SpringBoard UI. **Patch 0056**: swap only records the latest swap record; the vsync timer copies it to the panel every 60/sweetfb_hz ticks (default 10 Hz); `SWEET FB: N swaps` every 1000.
- **Boot 0054n (16:53 UTC, ~12 min, `logs/boot-0054n.txt`, patch 0054 sampler):** the data migration runs AGAIN on every boot (it completed once in the 0053s run) - completion is not being recorded. backboardd keeps swapping the progress UI (3700+ swaps in ~10 min, `SWEET FB: N swaps`). Sample during migration: SpringBoard main thread blocked in a synchronous XPC call (`mach_msg2_trap <- dispatch_mach_send_and_wait_for_reply <- xpc_connection_send_message_with_reply_sync <- -[BSXPCServiceConnectionMessage _sendSynchronously:] <- BSXPCServiceConnectionProxy ...`). Unsupported AKS selectors seen: 101 `aks_assert_consume`, 93 `aks_get_internal_info`, 34 `_aks_stash_load` (datamigrator), **35 `aks_get_extended_device_state`** (SpringBoard, chronod, remindd, searchd, symptomsd...). **Patch 0055**: AKS 35 answered like 17 (same DER device state), 101 succeeds; sampler backtraces 16 frames, 40 samples (~80 min).
- **MILESTONE: FIRST iOS PIXELS ON THE PANEL (boot 0053s long run, 15:33 UTC, ~60 min; photos IMG_20261017_183029/183222/183419; log `/run/media/dipa/android/ios-sweet-work/logs/boot-0053s-long.txt`, 407 KB, 1428 flushes).** The iOS data-migration boot screen (Apple logo + progress bar) was shown and the bar advanced to full in ~60 minutes. It is drawn by **backboardd through our kernel display path**: `SWEET SURF: backboardd create id 2/3 1080x2400 fmt 0x42475241 (BGRA) bpe 4 bpr 4352 size 10452992 keys 11`, IOSurface sels 9, 27, 5, 34 and traps 2/3 (lock/unlock), IOMFB SwapBegin (4) / SwapEnd (5, 1132-byte struct) / GetLayerDefaultSurface (3) / 68 / 55, then `SWEET FB: swap N layer 0 surface 2|3 1080x2400 ... a 0,0 1080x2400 b 0,0 1080x2400` alternating (double buffering; only the first 16 swaps are logged). Triggered by `com.apple.datamigrator` (AKS sels 101/93/34 return unsupported) and `com.apple.migrationpluginwrapper`. Probably ProgressUI-style CoreGraphics drawing into IOSurfaces (no GPU used). After the migration: SpringBoard and backboardd stay up (exec once each, no crash), nothing new drawn; crash loops only for mediaserverd, installcoordinationd, mobileactivationd (~108 each in the hour); bluetoothd and fairplayd.H2 relaunch constantly (no hardware). Kernel console text overlays the image (sweetfb_noconsole=1 would hide it).
- **MILESTONE: SpringBoard and backboardd both stay up (boot 0053s on v9, 15:29 UTC, `logs/boot-0053s.txt`).** With /chosen/display-scale = 3: `exec SpringBoard` once, `exec backboardd` once, no CRASH for either; MobileGestaltHelper reads IOMFB size/dot pitch; backboardd opens AppleCLCD (sels 57,15,22,29,33,79,74 as before). No IOSurface creates and no swaps: backboardd keeps polling `IOProviderClass IOAcceleratorES` (-> 0 found) and AGXAccelerator/IOAcceleratorESLegacy - no GPU, so no CoreAnimation renderer yet. Log goes quiet after ~47 s (only 47 flushes): the system idles. NEXT WALL: CoreAnimation rendering without a GPU (CPU path) so the window server produces frames.
- **SpringBoard's invalid mode = scale 0 (boot 0053n, 15:19 UTC, `logs/boot-0053n.txt`, heap scan):** `FBSDisplayMode cannot be configured as requested : <FBSDisplayMode: ...; infxinf@0x (1080x2400/0) 60Hz sRGB SDR>` - pixel size and 60 Hz are fine, scale is 0. libMobileGestalt (MGIOMFBSupport.c, sub_19c560a54) reads `display-scale` (u32, default 0) and `display-rotation` from **IODeviceTree:/chosen**, pixel size via IOMobileFramebufferGetDisplaySize (MobileGestaltHelper sel 8/28 in the log). mkadt now adds `/chosen/display-scale` = 3 (1080x2400 @3x = 360x800 pt). ADT `shim/out/sweet-0054hi.adt` (QEMU `research/q0054-hi.adt`), image `shim/out/shim-boot-0053s.img` = 0053 kernel + 0054hi ADT. Possible catch: MobileGestalt may have cached scale 0 in `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/...`.
- **MILESTONE: backboardd survives and opens the display (boot 0052n on v9, 15:07 UTC, `logs/boot-0052n.txt`).** No `CRASH backboardd`. It walks `IODeviceTree:/arm-io` children, matches IOMobileFramebuffer, `open AppleCLCD type 0 -> 0x0`, calls IOMFB selectors 57, 15, 22, 29, 33, 79 (GetBlock, out 1580/40), 74 (SupportedFrameInfo), 12, 6, 27, 17, 84, 50; opens IOCoreSurfaceRoot (sel 13); looks for AGXAccelerator / IOAcceleratorES / IOAcceleratorESLegacy (none, repeatedly), `IODeviceTree:/product` (none, repeatedly), `/buttons`, aop-smart-cover, IOPMrootDomain. No swaps yet. **SpringBoard now gets past display discovery** and dies (sig 5) in `-[FBSDisplayMode _initWithWidth:height:preferredScale:scaleOverride:refreshRate:gamut:hdr:rotation:virtual:validityCheck:]+580` <- `_initWithCADisplayMode:scale:rotation:` <- `FBSDisplayConfiguration _initWithImmutableDisplay:` <- `FBSDisplaySource initWithDisplay:` <- `FBSDisplayMonitor` (slide 0x14504000): "FBSDisplayMode cannot be configured as requested". Checks: width/height >= 2, preferredScale > 0, scaleOverride >= 0, refreshRate non-zero, valid gamut/HDR/rotation. Suspects: refresh rate 0 (IOMFB timing blocks answered with zeros) and/or scale 0 (MobileGestalt main-screen-scale; no /product node in the ADT). **Patch 0053**: heap text scan also on SIGTRAP and for SpringBoard (default sweetscan list backboardd,SpringBoard) to read the exact mode description.
- **Image v9 (2026-10-17) = v8 + `/private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}` (root:wheel 0755; on iOS these live on the data volume, absent from the rootfs) + launchd.plist with StandardOutPath/StandardErrorPath renamed to ...PatX (the in-place phone fix; daemons' stdout reaches the log via the 0048 /dev/null tee).** `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v9.img` SHA256 aa9f9139...6e67, `.simg` 12,145,303,864 bytes; written through `sudo mount -t hfsplus -o loop,force`. **Patch 0052** (`xnu/patches/0052-sweet-hfs-rename-swap.patch`, CI `39042761826` -> `xnu/out-0052`, QEMU OK, image `shim/out/shim-boot-0052n.img`): vn_rename falls back to VNOP_EXCHANGE when VNOP_RENAMEX(RENAME_SWAP) returns ENOTSUP for two regular files on one volume (HFS exchange swaps data and cnode descriptors = swap semantics). Flashing v9 started 2026-10-17 ~15:00 UTC.
- **backboardd EXCEPTION FOUND (boot 0051n, 14:41 UTC, `logs/boot-0051n.txt`, patch 0051 heap scan):** `*** Terminating app due to uncaught exception 'NSInvalidArgumentException', reason: '*** -[NSURL initFileURLWithPath:]: nil string parameter'`. First-throw stack (slide 0x337f0000): `+[NSURL fileURLWithPath:]` <- `-[BSSystemContainerForCurrentProcessPathProvider libraryPath]` <- `cachesPath` <- backboardd main+0x1d858 (StartWindowServer, shader cache path). BaseBoard: libraryPath = `BSSystemSharedResourcesDirectoryForIdentifier` = `BSSystemSharedDirectoryForIdentifier(id)` + "/Library"; that calls `container_system_path_for_identifier` (libsystem_containermanager -> `_container_legacy_lookup` -> containermanagerd XPC), which returned NULL (BaseBoard logs "Error getting shared system container ..."). With 0050 the sandbox denials are gone. containermanagerd.log.0 in the pulled (pre-0050) image: "Did not receive any persona attributes", "Expected to find at least one persona", notify_register_dispatch failed 9; `/private/var/containers` does NOT exist in the root image (on iOS it lives on the data volume). usermanagerd does create kernel personas 99/199/1000, but fails to save `/private/var/keybags/usersession.kb` and `persona.kb`: "Failed to atomically swap writing file: Operation not supported (45)" (HFS has no RENAME_SWAP). NEXT: create `/private/var/containers` (and check what containermanagerd needs for system group containers), fix or emulate RENAME_SWAP on HFS, then re-check backboardd.
- **Disk housekeeping (2026-10-17):** /home was at 4 GiB free. Moved (not deleted) `xnu/out-0010..0044` and old `shim/out/*.img`/`payload-*.bin` (everything before 0046) to `/run/media/dipa/android/ios-sweet-work/archive/{xnu,shim-out}` (6.3 GiB); /home now 8.7 GiB free. Large work files (phone-root.img 16 GiB, logs, tracev3 dumps) live in `/run/media/dipa/android/ios-sweet-work/`. **Patch 0051** (`xnu/patches/0051-sweet-crash-heap-strings.patch`, CI `39041440935`): on SIGABRT of a process in boot-arg `sweetscan` (default backboardd) the crash log prints heap text runs as `STR ...` (to find the NSException reason). Boot 0051n 14:41 UTC.
- **Boot 0049n (14:11 UTC, `logs/boot-0049n.txt`, patch 0049 trace): backboardd's IOKit lookups before it dies** (each run): `IODeviceTree:/arm-io/pearl-sep` -> none, matching ApplePearlSEPDriver -> none, `IOService:/IOResources/AppleKeyStore` open OK, matching IOHIDDevice (DeviceUsagePairs) / `HIDServiceSupport` notifications, `usb-drd,t8027` notification; **never any IOMobileFramebuffer / display lookup** - the exception happens before display detection. launchd (tracev3) shows backboardd's mach lookups denied with `error = 159: Sandbox restriction`: com.apple.mobilegestalt.xpc, com.apple.iohideventsystem, com.apple.system.notification_center, com.apple.logd, containermanagerd, ACCHWComponentAuthService, oscard. libsystem_sandbox uses `__mac_syscall("Sandbox", op, arg)` (ops: 1 init, 2 check, 3 note, 4 container path, 5/6/7/8 extensions, 0x15 check_bulk, ...); with no policy named "Sandbox" every call gets ENOPOLICY. **Patch 0050** (`xnu/patches/0050-sweet-sandbox-policy.patch`): built-in permissive MAC policy "Sandbox" in sweet_amfi.c (mpo_policy_syscall returns 0, container/extension ops ENOENT; logs first use of each op as `SWEET Sandbox: proc op N`).
- **Phone root pulled (16 GiB, 12 min, `adb exec-out dd if=/dev/block/sda34`) to `/run/media/dipa/android/ios-sweet-work/phone-root.img` (loop-mounted ro at /run/media/dipa/iOSRoot).** No .ips crash reports. logd tracev3 (Persist, LZ4 `bv41` blocks, decompressed strings in `ios-sweet-work/tracev3/all.txt`): /private/var/db/uuidtext is EMPTY so only launchd's own messages are readable. Findings: v8 launch failure = `Service could not initialize: posix_spawn(/usr/libexec/backboardd), error 0xd - Permission denied` (xpcproxy exit 78) - /dev/console not openable for the mobile user; backboardd[98] spawned `com.apple.MTLCompilerService` before SIGABRT; **launchd denies many mach lookups with `error = 159: Sandbox restriction`** (mediaserverd -> com.apple.backboard.display.services, remoted, mobiletimerd -> sleepd, identityservicesd -> apsd) and **tccd exits OS_REASON_SANDBOX "profile not found"** - no Sandbox kext/profiles on SWEET; likely cause of many daemon crash loops (next wall after the display). CF's uncaught-exception text never reaches stderr for daemons (no CF handler; libc++abi prints only the type). **Patch 0049** (`xnu/patches/0049-sweet-iokit-trace.patch`): `IOK name: ...` console lines for registry path lookups, child iterators, matching (with result count/class), matching notifications and IOServiceOpen of the processes in boot-arg `sweetiolog` (default backboardd), max 400 lines.
- **CONFIRMED: launchd StandardOut/ErrorPath=/dev/console stops backboardd from launching.** After the in-place rename (boot 0047n-b, log `logs/boot-0047n-b.txt`) backboardd launches again and dies as on v7: sig 6, `___pthread_kill <- abort <- demangling_terminate_handler <- _objc_terminate <- std::terminate <- _dispatch_client_callout <- _dispatch_once_callout <- main+0x9334` (window-server dispatch_once). It never opened AppleCLCD or IOCoreSurfaceRoot (no `SWEET FB/SURF: backboardd` lines) -> throws before/at display detection. **Patch 0048** (`xnu/patches/0048-sweet-devnull-tee.patch`, CI `39037749668` -> `xnu/out-0048`, image `shim/out/shim-boot-0048n.img`): writes to /dev/null by processes named in boot-arg `sweetnull` (default `backboardd,SpringBoard`) are printed as `|name| text`. Boot 0048n (13:48 UTC, log `logs/boot-0048n.txt`): only `|backboardd| libc++abi: terminating due to uncaught exception of type NSException` (CF's reason line goes to os_log, not stderr, despite CFLOG_FORCE_STDERR/OS_ACTIVITY_DT_MODE). Next: pull the whole 16 GiB root from recovery (`adb exec-out dd if=/dev/block/sda34`) to `/run/media/dipa/android/ios-sweet-work/phone-root.img` and read ReportCrash .ips files / logd tracev3 for the exception reason.
- **Persistent log WORKS (boot 0047n on v8, 13:31 UTC; pulled from OrangeFox: 70 KB, 111 flushes, `/run/media/dipa/android/ios-sweet-work/logs/boot-0047n.txt`).** In 3 min **backboardd was never exec'd** (v7 ran it), ~70 bare `exec xpcproxy`, SpringBoard loops on FBSDisplayMonitor (no display), mediaserverd sig 11 loop, locationd, lockdownd sig 5. Suspect the v8 plist (StandardOut/ErrorPath=/dev/console on backboardd). **In-place plist edit from recovery (no reflash):** launchd.plist is one extent at image/partition byte offset 0x1e025f000 (195 blocks; verified bytes identical on phone vs local v8 mount); renamed StandardOutPath->StandardOutPatX and StandardErrorPath->StandardErrorPatX (same length, both jobs) in blocks 68 and 105 via `adb push` + `dd of=/dev/block/sda34 seek=... conv=notrunc,fsync`, read back VERIFIED. Phone now differs from local v8 image in those 2 blocks (files in `/run/media/dipa/android/ios-sweet-work/`). Test boot 0047n 13:38:42 UTC. Recovery kernel has no hfsplus (raw block edits only).
- **Patch 0047: persistent console log (CI `39036478663` -> `xnu/out-0047`, QEMU no panic; phone image `shim/out/shim-boot-0047n.img` = 0047 + sweet-0046hi.adt + 0045n cmdline).** `_cnputs` (all console output: kernel printf + daemons' /dev/console) also appends to a 4 MiB ring in sweet_ufs.c; after the UFS partition is ready and writable (ufsrw=1) a thread writes new ring blocks + header to the LAST 1025 blocks (4 KiB) of userdata every ~1 s and SYNCHRONIZE CACHE (prints `SWEET LOG: console log to the last 4100 KiB ...`). Read: phone to fastboot -> `fastboot boot recovery/recovery.img` (OrangeFox) -> `tools/sweet-log-pull.sh OUT.txt` (adb dd of that area + `tools/sweet-log.py`). Not yet verified on the phone. Panics after the last flush are not in it (screen still shows them). 2x font attempt reverted: XNU's v_scale only scales the progress icon.
- **Boot 0046n on v8 (13:05 UTC, VID_20261017_150522_HSR_120):** phone prints `SWEET SURF: IOCoreSurfaceRoot registered` and `SWEET FB: AppleCLCD 1080x2400 stride 4320 at 0x9c000000, default surface 1` (nubs + match work on hardware). Visible userspace: early boot tasks, launchd_cache_loader, `exec SpringBoard`; no `exec backboardd` / `SWEET FB: backboardd` line seen in the readable frames (video blurry). Frame 00:47: lower half of the screen shows OLDER console text (16:01:12) below newer lines -> unconfirmed hint that a swap copied an old snapshot of the panel (CA reads the default/displayed surface = panel memory). SpringBoard still dies in `-[FBSDisplayMonitor _initWithBookendObserver:transformer:]+1160` (sig 5, slide 0x30960000). **Shim: 2x console font** (`shim/loader.c` Video.v_depth scale field = 1) so phone videos are readable; image `shim/out/shim-boot-0046b.img` = 0046n + 2x font.
- **Patch 0046: built-in IOSurface + IOMobileFramebuffer (2026-10-17, offline, NOT phone-tested).** `xnu/patches/0046-sweet-iosurface-iomfb.patch`: new `iokit/Kernel/arm/SweetSurface.{h,cpp}` (IOCoreSurfaceRoot + IOSurfaceRootUserClient: sel 13/0/4/34/35, traps 0-5, wired buffers mapped into the caller, per-client refs) and `SweetFramebuffer.cpp` (AppleCLCD : IOMobileFramebuffer on /arm-io/disp0: sizes, swap = CPU copy of enabled layers into the ABL panel memory, 60 Hz vsync via sendAsyncResult64WithOptions(CanDrop), panel memory published as the default IOSurface, kernel text console paused on the first swap only with `sweetfb_noconsole=1` (default keeps the console: pausing switches it to serial and would hide panics)); SweetPlatformExpert creates nubs for /arm-io children (not gic) attached to the platform expert (IOPlatformDevice::compareName casts its provider to IOPlatformExpert, so nubs under the arm-io nub never matched - first CI build showed that in QEMU). mkadt: /arm-io/disp0 {device_type display-subsystem, compatible sweet,display, canvas-width 1080, canvas-height 2400}. CI `39021572169` -> `xnu/out-0046`. **QEMU** (`research/q0046-hi.adt`, RAM disk init, msgbuf): `SWEET SURF: IOCoreSurfaceRoot registered`, `SWEET FB: AppleCLCD 1080x2400 stride 4320 at 0x9c000000, default surface 1`, init alive, no panic. Phone image **`shim/out/shim-boot-0046n.img`** (SHA256 9c4d2fe9..., CI `39024108588` with the review fixes: swap bounds check, zeroed 64-bit async ref, port release, 1.5 GiB wired budget, ref leak/race fixes; QEMU re-checked) = 0046 kernel + `shim/out/sweet-0046hi.adt` + the 0045n cmdline; boot it on image v8 (backboardd/SpringBoard log to console) and film. Expected new console lines: `SWEET SURF: <proc> create id ...`, `SWEET FB: backboardd sel N ...`, `SWEET FB: swap ...`. Open question for the next wall: QuartzCore's IOMFB server builds its renderer from Metal first (`CAMetalContextCreate`), GLES only when enabled; how the CPU renderer gets selected on a device without a GPU is not yet established.
- **IOSurface values ABI (offline RE, `/run/media/dipa/android/ios-sweet-work/iosurface-values.md`) - TODO in SweetSurface (0046 only accepts and drops values, so IOSurfaceCopyValue always returns NULL):** sel 9 SetValue in = {u32 id, u32 pad, IOCFSerialize([value, key]) or ([dict] = merge)}, sel 0xb RemoveValue in = {u32 id, u32 pad, key\0} (empty key = remove all); both out 4 bytes = new generation, client accepts only (gen+2)|1. Kernel after each change: gen = (gen+2)|1 (odd, never 0) -> state+0x20, serialized size (>=1) -> state+0x28. sel 0xa in {u32 id, u32 0, u8 0}, out {u32 ?, u32 gen, serialized non-bulk dict}; too small -> 0xe00002db + needed size (client retries x16). sel 0x1b in 0x88: bulk struct 0x70 @0, u64 valid size @0x70, u64 changed mask @0x78, u32 id @0x80 -> copy masked fields into state+0x30 (bit0 32B @0, bit1 16B @0x20, bit2 8B @0x30, bits3-10 1B @0x38..0x3f, bits11-14 24B @0x40/4B @0x58/8B @0x5c/1B @0x64).
- **IOMFB display matching confirmed (offline RE, `/run/media/dipa/android/ios-sweet-work/iomfb-match.md`):** the framework never matches on "AppleCLCD"; any registered IOMobileFramebuffer subclass works. `iomfb_match_callback` reads only `dfr`/`AppleTV`/`external` (CFBoolean, service itself, no parents); internal main display = all absent/false (type 0, name "primary"). Display count = /arm-io children whose device_type starts with "display-subsystem" (count 0 -> CreateDisplayList returns NULL; more nodes than services -> 30 s wait). IOMobileFramebufferOpen fails only on IOServiceOpen failure; canvas-width/height read as 4-byte CFData from the IOService-plane parent (optional). CopyProperty = IORegistryEntrySearchCFProperty on the service only. Patch 0046 (disp0 node, `external`=false, AppleCLCD : IOMobileFramebuffer) fits all of this.
- **IOMobileFramebuffer swap + notification ABI (2026-10-17, offline).** Swap record = fb+0x18, **0x46c bytes**, zeroed by SwapBegin and sent whole by `kern_SwapEnd` = IOConnectCallStructMethod(sel 5, rec, 0x46c, no output). **SwapBegin** = sel 4, no input, 1 scalar out = swap id (stored at rec+0x50). `kern_SwapSetLayer(fb, layer<4, IOSurfaceRef, CGRect a, CGRect b, flags)`: rec+0x54+4*layer = **IOSurface id**; rec+0x104 bit layer = layer enabled (rec+0x108 bit cleared); rect a (int x,y,w,h, scaled) at rec+0x64+16*layer, rect b at rec+0xc4+16*layer; rec+0x114+4*layer = transform from flags&0xf; flag bits 5/31/6/7/8/9 set bytes rec+0x2ca/0x2cc/0x2e3/0x2e5/0x2e6/0x467+layer. A NULL surface only sets the enable bit with zero id. SwapWait = sel 6 scalars [swap id, timeout, 0].
  - **Notifications**: `IOMobileFramebufferScheduleWithDispatchQueue`/`GetRunLoopSource` create an IONotificationPort and `IOConnectSetNotificationPort(conn, type, port, 0)` (kernel `registerNotificationPort`). `kern_EnableNotifications(fb, type, cb, ctx)` = **sel 72 scalars [NotifyCallbackFuncs[type], fb, type, 0]** -> the kernel keeps an async reference {port, func, refcon=fb} per type and fires it with `sendAsyncResult64`. Types: 0 HotPlug, 1 Power, 3 FrameInfo (args[0] = mask of 31-bit keys, args[1] u32, then values), 4 CRC, **5 Vsync**: 6 args, each a 32-bit half in a u64 slot: (ts lo, ts hi), (t2 lo, hi) passed through the time-ingest helper, (t3 lo, hi); the framework then calls the client's vsync callback(fb, ts, t2', t3, ctx). Vsync callbacks are dropped while the notification port has queued messages.

- **IOSurface.framework user-client ABI reversed (2026-10-17, offline, step 2 of the GUI plan).** `ipsw dyld disass research/dsc/dyld_shared_cache_arm64 --image IOSurface` (selector scan script: scratchpad `selscan.py`).
  - Connect (`_iosConnectInitalize`, pthread_once): `IOServiceGetMatchingService(IOServiceNameMatching("IOCoreSurfaceRoot"))`, retried with sleep(1) up to 241 times (a missing service stalls every client ~4 min, no crash); `IOServiceOpen(type 0)`; then **sel 13** (no inputs, struct out 0x18 bytes = `_ioSurfaceLimits`) and requires u16 at out+0x16 == 1 (ABI version); out+0 = offset/plane-base alignment mask, out+4 = bytes-per-row alignment mask (used as (x+m)&~m), +0..+0x14 also copied into IOSurface remote-method init, otherwise logs and closes the connection.
  - **Create = sel 0**: scalar in [parent id or 0], struct in = `IOCFSerialize(props, kIOCFSerializeToBinary)` (OSUnserializeBinary format; keys IOSurfaceWidth/Height/BytesPerRow/BytesPerElement/PixelFormat/AllocSize/PlaneInfo/CacheMode/IsGlobal/...), struct out **0xa68 bytes** ("lock result"). **Lookup = sel 4**: scalar in [id], same struct out. LookupFromMachPort = sel 0x22 (scalar in [port name]); CreateMachPort = sel 0x23 (scalar in [id, options], scalar out [port name]).
  - Lock result (copied to client+0x68, size 0x68 + planes*0x80, min 0xe8): 0x00 u64 base address **mapped in the caller's task**; 0x08 u64 task VA of a per-surface shared state page (+0 u64 registry id, +8/+0xa u16 bound accel ids, +0xc u32 seed, +0x14 u8 tiled, +0x20 u32 value generation, +0x24 YCbCr matrix, +0x28 u32 non-bulk values size, +0x2d u8 displayable, +0x2e u8 sysmem-only, +0x30 0x70 bytes bulk attachments); 0x10 u64 task VA of timestamp page (4 u64 indexed timestamps, +0x20 detach code); 0x18 u32 surface id; 0x1c u32 alloc size; 0x20 width; 0x24 height; 0x28 bytes per row; 0x2c buffer offset; 0x30 pixel format; 0x34 u32 (dcache flush length); 0x38 plane count; 0x40 u16 bytes/element; 0x42 u8 element width; 0x43 u8 element height; 0x44 cache mode; 0x4c u8 subsampling; 0x4d u8 prohibit-use count; 0x50 parent id; 0x54 slice count; 0x58 u64 trace id; 0x60 u64 protection options; planes[n] at 0x68+n*0x80 (+0 width, +4 height, +8 bytes/row, +0xc offset, +0x14 size, +0x18 u16 bpe, +0x1a/+0x1b u8 element w/h, +0x1c u8 component count, +0x1d address format, +0x54 u8 compression type (non-zero -> no CPU base address)).
  - **Traps** (IOConnectTrapN -> `IOUserClient::getTargetAndTrapForIndex`): 0 IncrementUseCount(id, category), 1 DecrementUseCount(id, category), 2 **Lock**(id, options, &seed_out), 3 **Unlock**(id, options, &seed_out), 4 Release(id), 5 Release after a failed create/lookup setup (id).
  - Other selectors: 5 SetYCbCrMatrix, 6 WrapClientImage, 7 WrapClientMemory, 9 SetValue (serialized), 0xa UpdateNonBulkValueCache (struct in 9), 0xb RemoveValue, 0xc BindAccel, 0x11 SetSurfaceNotify (async), 0x12 RemoveSurfaceNotify, 0x13 Log, 0x14 SetPurgeable, 0x15 SetOwnership, 0x16 SetTiled, 0x18 SetTimestamp, 0x19 GetTileFormat, 0x1a CopyDataValueBytes, 0x1b SetBulkAttachments (struct 0x88), 0x1e/0x2e-0x31 (via outlined helpers), 0x1f SetCompressedTileDataRegionMemoryUsed, 0x20 GetGraphicsCommPageAddress, 0x21 SetIndexedTimestamp, 0x24-0x26/0x2d IOSurfaceAccelerator, 0x27-0x29 shared events, 0x2a SignalEvent, 0x2b Set/InitDetachModeCode, 0x2c SetOwnershipIdentity, 0x32-0x34 data properties.
  - => SWEET kernel service: class/name **IOCoreSurfaceRoot** + IOSurfaceRootUserClient; minimum = sel 13, 0, 4, 9/0xa/0xb (values), traps 0-5, 0x22/0x23 later for cross-process surfaces (CA sends surfaces to backboardd by mach port). Memory: IOBufferMemoryDescriptor per surface, mapped into each task with createMappingInTask; ids from a global table.

- **Image v8: daemon logs on the console.** `tools/patch-launchd-plist.py IN OUT LABEL...` rewrites launchd.plist (binary, plistlib): renames every `_PanicOnCrash` to `_PanicOnCrasX` and gives the listed jobs `StandardOutPath`/`StandardErrorPath` `/dev/console` (devfs console is 0622, writable by mobile) plus `OS_ACTIVITY_DT_MODE=YES` (os_log mirrored to stderr) and `CFLOG_FORCE_STDERR=1`. v8 = v7 + that plist for com.apple.backboardd and com.apple.SpringBoard, written through the mount (796310 bytes, root:80 0644), SHA256 in `ios16-root-20H392-v8.img.sha256`, `.simg` ready; boot with `shim/out/shim-boot-0045n.img`. Goal: see backboardd's uncaught exception text and the window server's display probing. ODDITY (unresolved): the v5 raw-image rename at offset 0x1e025f000 is present in the v5-v7 image bytes, but the plist read through a Linux mount of v7 still had the original `_PanicOnCrash` keys; filefrag shows the file as one extent. Never patch file contents through raw offsets again; write through the mount.
- **IOMobileFramebuffer.framework reversed (step 1 of the GUI plan).** `ipsw dyld disass research/dsc/dyld_shared_cache_arm64 --image IOMobileFramebuffer`.
  - Display discovery (`IOMobileFramebufferCreateDisplayList` -> `getDisplayListNumber`): iterates children of `IODeviceTree:/arm-io`, counts nodes whose `device_type` is "display-subsystem" or "ext-display-subsystem" (or `compatible` "paravirtualizedgraphics,gpu"); then `iomfb_populate_display_infos` adds an IOServiceAddMatchingNotification(IOServiceFirstMatch, **IOServiceMatching("IOMobileFramebuffer")**) and runs the run loop up to 30 s until that many services matched. `iomfb_match_callback` reads service properties `dfr`, `AppleTV`, `external` (CFBoolean) and names displays (external ones "%s-%d").
  - `IOMobileFramebufferOpen(service, task, type, &fb)`: `__ioMobileFramebufferAlloc` (CFPreferences com.apple.iokit.IOMobileGraphicsFamily: canvas_width/height, override_display_width/height, override_panel_width/height, benchmark, enable_ktrace), `IOServiceOpen(service, task, type)` (GetMainDisplay passes type 0), `getEDTProperty` reads `canvas-width`/`canvas-height` from the service's IODeviceTree parent, then fills a table of `kern_*` function pointers.
  - User client selectors (`kern_*` -> IOConnectCall*): 3 _kern_GetLayerDefaultSurface[ScalarMethod_stub]; 4 _kern_SwapBegin[ScalarMethod_stub]; 5 _kern_SwapEnd[StructMethod_stub]; 6 _kern_SwapWaitWithTimeout[ScalarMethod_stub] _kern_SwapWait[ScalarMethod_stub]; 7 _kern_GetID[ScalarMethod_stub]; 8 _kern_GetDisplaySize[ScalarMethod_stub]; 10 _kern_SetTVOutMode[ScalarMethod_stub]; 11 _kern_SetWSSInfo[ScalarMethod_stub]; 12 _kern_RequestPowerChange[ScalarMethod_stub]; 13 _kern_EnableStatistics[ScalarMethod_stub]; 14 _kern_SetFlags[ScalarMethod_stub]; 15 _kern_SetDebugFlags[ScalarMethod_stub]; 16 _kern_SetTVOutSignalType[ScalarMethod_stub]; 17 _kern_SetGammaTable[StructMethod_stub]; 18 _IOMobileFramebufferIsMainDisplay[ScalarMethod_stub]; 19 _kern_SetWhiteOnBlackMode[ScalarMethod_stub]; 20 _kern_SwapSignal[ScalarMethod_stub]; 22 _kern_SetDisplayDevice[ScalarMethod_stub]; 23 _kern_SetDigitalOutMode[ScalarMethod_stub]; 24 _kern_GetHDCPDownstreamState[StructMethod_stub]; 25 _kern_GetDigitalOutState[ScalarMethod_stub]; 26 _kern_printDisplayRegs[ScalarMethod_stub]; 27 _kern_GetGammaTable[StructMethod_stub]; 28 _kern_GetDotPitch[ScalarMethod_stub]; 29 _kern_GetDisplayArea[StructMethod_stub]; 30 _kern_EnableDisableDithering[ScalarMethod_stub]; 31 _kern_SetUnderrunColor[ScalarMethod_stub]; 33 _kern_EnableDisableVideoPowerSavings[ScalarMethod_stub]; 34 _kern_SetVideoDACGain[ScalarMethod_stub]; 35 _kern_SetLine21Data[ScalarMethod_stub]; 41 _IOMobileFramebufferEnableMirroring[ScalarMethod_stub]; 42 _IOMobileFrameBufferGetMirroringCapability[StructMethod_stub]; 43 _IOMobileFramebufferSetRenderingAngle[StructMethod_stub]; 44 _IOMobileFramebufferSetMirrorContentRegion[StructMethod_stub]; 47 _kern_HDCPSendRequest[ScalarMethod_stub]; 48 _kern_HDCPGetReply[ScalarMethod_stub]; 49 _kern_SurfaceIsReplaceable[ScalarMethod_stub]; 50 _kern_SetBrightnessCorrection[ScalarMethod_stub]; 51 _kern_SetColorRemapMode[ScalarMethod_stub]; 52 _kern_SwapCancel[ScalarMethod_stub]; 53 _IOMobileFramebufferSetCanvasSize[ScalarMethod_stub]; 54 _IOMobileFramebufferGetMatrix[Method_stub]; 55 _IOMobileFramebufferSetMatrix[Method_stub]; 56 _IOMobileFramebufferKernelTests[StructMethod_stub]; 57 _kern_GetColorRemapMode[ScalarMethod_stub]; 66 _kern_SPLCSetBrightness[ScalarMethod_stub]; 67 _kern_SPLCGetBrightness[ScalarMethod_stub]; 68 _kern_SetParameter[Method_stub]; 69 _kern_SwapSetColorMatrix[StructMethod_stub]; 72 _kern_DisableNotifications[ScalarMethod_stub] _kern_EnableNotifications[ScalarMethod_stub]; 73 _kern_ChangeFrameInfo[ScalarMethod_stub]; 74 _kern_SupportedFrameInfo[Method_stub]; 75 _kern_FactoryPortal[StructMethod_stub]; 77 _kern_GetCurrentAbsoluteTime[ScalarMethod_stub]; 78 _kern_SetBlock[Method_stub]; 79 _kern_GetBlock[Method_stub]; 80 _kern_GetLinkQuality[ScalarMethod_stub]; 81 _kern_SwapCancelAll[ScalarMethod_stub]; 82 _kern_GetProtectionOptions[ScalarMethod_stub]; 83 _kern_CopyLayerDisplayedSurface[ScalarMethod_stub]; 84 _kern_SetContrast[StructMethod_stub]; 85 _kern_GetBufBlock[Method_stub]; 86 _IOMFBGainEncoderFinishEncoding[Method_stub]; UNKNOWN {}
  - => Kernel needs: an `/arm-io` child node with device_type "display-subsystem" (+ canvas-width/height) and an IOService of class **IOMobileFramebuffer** (subclass name match) attached under it, opened with type 0, implementing at least GetDisplaySize(8), IsMainDisplay(18), GetID(7), GetLayerDefaultSurface(3), SwapBegin(4)/SwapEnd(5 struct)/SwapWait(6), Enable/DisableNotifications(72), frame info(73/74), CopyLayerDisplayedSurface(83), plus IOSurface for the swapped buffers. NEXT: CoreAnimation's AppleDisplay/IOMFBDisplay usage of these (constructor, first swap, vsync), then IOSurface.framework's IOSurfaceRoot selectors.
- **GUI PLAN (decided 2026-10-16): CPU rendering + kernel IOMobileFramebuffer.** User: CPU rendering is fine for now (goal = prove the GUI runs), may later research an Apple-style GPU driver for the Adreno 618 -> keep display output and renderer separable. QuartzCore findings (symbols from the cache's .symbols subcache: `ipsw dyld symaddr research/dsc/dyld_shared_cache_arm64 --image QuartzCore`; strings: `ipsw dyld macho ... QuartzCore --strings`):
  - Renderers: `sw_new_context` (CA::OGL::SWContext, full CPU renderer incl. blur, images, IOSurface-backed surfaces, make_buffer_current(WindowServer::Surface)), `gles_new_context`, `metal_new_context`, `new_null_context`. Env knobs include CA_ENABLE_OGL, CA_DISPLAY_TYPE, CA_FORCE_LOCAL_SERVER, CA_FORCE_TIMER, CA_CANVAS_WIDTH/HEIGHT, CA_MAIN_DISPLAY_SCALE/ORIENTATION, CA_DISABLE_RENDER, CA_ALWAYS_RENDER (selection logic not traced yet).
  - `-[CAWindowServer _detectDisplays]` (0x1884e3150) iterates static tables `open_funcs`/`count_funcs` = AppleCLCDDisplay, AppleRGBOutDisplay, AppleWirelessDisplay only; each `count()` = `display_count_of_type(IOMFBDisplayType)` over **`IOMobileFramebufferCreateDisplayList()`**, `open(i)` = `create_display_of_type` -> `CA::WindowServer::AppleDisplay(CFString name, ..., IOMFBDisplayType)` (an IOMFBDisplay driven by IOMFBServer: vsync_callback, frame_info_callback, swaps). `CA::WindowServer::VirtualDisplay` exists but is never auto-detected (explicit API only). => the main display MUST come from an IOMobileFramebuffer kernel service.
  - NEXT: reverse IOMobileFramebuffer.framework: IOMobileFramebufferCreateDisplayList / IOMobileFramebufferOpen (service matching, display type property), the user-client selectors used by IOMFBServer (display size/modes, swap begin/set-layer/end with IOSurface ids, vsync notifications), then the IOSurface kernel side (IOSurfaceRoot user client: create/lookup/lock, memory mapping) that both IOMFB swaps and CA surfaces need. Kernel: SWEET IOMobileFramebuffer service that copies the swapped IOSurface to the 1080x2400 framebuffer at 0x9c000000.
- **logd fixed; backboardd = DISPLAY WALL (boot 0045n on v7, 21:08:57 UTC, frames VID_20261016_230850 00:55-01:28, slide 0x4c3ec000, `research/crash-0045n-v7.txt`).** No `CRASH logd` any more; new daemons run (runningboardd, WirelessRadioManagerd, networkserviceproxy, dasd, cloudpaird, magicswitchd, atc, askpermissiond, ManagedSettingsAgent, containermanagerd uses AKS 0/17). New: locationd sig 11 at CFRunLoopAddSource+132 (NULL source) from its main+0x2af138 in a dispatch_once. **backboardd** sig 6: abort <- std::terminate <- _objc_terminate <- dispatch_once <- main+0x9334 = the "start %{public}@..." wrapper (0x100009264) for **"window server"** (block 0x10000a770 -> dispatch_once body 0x10001d7f0 = StartWindowServer): MTLSetShaderCachePath, `[CAWindowServer serverWithOptions:@{kCAWindowServerDisableUpdatesOnMainDisplay: @YES}]`, `setRendererFlags:`, **`mainDisplay`** -> `displayId` -> `[CADisplay displayWithDisplayId:]`, setWindowServerDisplay:, bounds, pointScale, currentMode, preferredScale, nativeOrientation, touchScales... With no display, mainDisplay is nil and it throws. (HID system and GS start fine before it.) SpringBoard dies on the same missing display (FBSDisplayMonitor). QuartzCore display backends (from the cache's .symbols subcache, `ipsw dyld str`): `CA::WindowServer::AppleCLCDDisplay` (IOMobileFramebuffer hardware) and **`CA::WindowServer::VirtualDisplay`** (open(), new_server, clone_update). `CA_DISPLAY_TYPE` and `CA_FORCE_LOCAL_SERVER` strings exist in QuartzCore but have no direct xref (likely read via a table of CA_* env names). NEXT: find how CA::WindowServer::Server enumerates displays (IOMobileFramebuffer services vs VirtualDisplay / CA_DISPLAY_TYPE) and choose: (a) kernel IOMobileFramebuffer service + IOSurface, or (b) a VirtualDisplay rendered by CA's CPU path (CA::OGL::SW) and copied to the framebuffer.
- **watchdogd + CommCenter + identityservicesd fixed (boot 0045n on v6, 20:41:30 UTC, frames VID_20261016_224133 00:39-01:13, slide 0x20fec000).** `SWEET WDT: watchdogd sel 0 in 0/0 out 1/0 -> ok`, no watchdogd/CommCenter/identityservicesd crashes (CommCenter/identityservicesd now call AKS 0/17/7). usermanagerd boot task runs (UMD_INIT creates primary session uid 501 "mobile", personas 99 System and 199 Default registered with the kernel); `Failed to atomically swap writing file /private/var//keybags/usersession.kb: Operation not supported (45)` (HFS lacks the atomic swap rename; non-fatal so far). Remaining: SpringBoard (FBSDisplayMonitor, no display), backboardd (uncaught exception), mediaserverd, lockdownd (crash inside obfuscated code, main+0x4c1b4?), logd. **logd**: main+0x18160 = `BUG IN LIBTRACE: Failed to migrate directory` from 0x10001801c(dir 0): 0x100016538 requires the dir to exist with uid/gid/mode from the table at 0x10002df14 (0: /private/var/db/diagnostics 272:272 0751, 1: /private/var/db/uuidtext 272:272 0755, 2: /private/var/db/diagnostics/timesync 272:272 0755) plus a `.migrated` file, else XPC "operation 6" to a helper and crash. **Image v7** = v6 + those dirs/markers (also in mkiosroot.sh), SHA256 in `ios16-root-20H392-v7.img.sha256`, `.simg` ready. Boot with `shim/out/shim-boot-0045n.img`.
- **Exit-reason text works (boot 0044n, frames VID_20261016_221726 00:32-00:53, slide 0x22d5c000).** CommCenter/identityservicesd: `couldn't dlopen libobjc-trampolines.dylib: dlopen(/usr/lib/libobjc-trampolines.dylib, 0x0106): tried: '/usr/lib/libobjc-trampolines.dylib' (no such file, not in dyld cache)`: the file only exists in the OS cryptex and dyld does not search cryptexes at ignition_level=1. 19 cryptex files have no root counterpart (OS: DriverKit dyld cache + .symbols, VisualTestKit, libffi-trampolines, libobjc-trampolines, libstdc++ 6.0.9 + 2 symlinks; App: SafariSupport.bundle, AuthenticationServicesAgent, com.apple.Safari.History, passwordbreachd, safarifetcherd, webbookmarksd, webinspectord, webpushd) -> hard-linked (symlinks copied: Linux hfsplus cannot hard-link symlinks); `tools/mkiosroot.sh` does it generically. watchdogd still crashed: the `-wdt_no_pmu` / `/arm-io/wdt no-pmu` check (0x10000a01c) only runs when os_variant_has_internal_diagnostics; otherwise 0x100009b18 looks up IOServiceMatching("IOService") + IOPropertyMatch {IOPMUPrimary: 1} (NSConstantDictionary) and crashes if absent, then IORegistryEntrySetCFProperty(boot stage 0xff) (failure only logged). Patch **0045**: IOWatchdog sets IOPMUPrimary = 1 and accepts setProperties; CI `38961814194` -> `xnu/out-0045`. **Image v6** = v5 + the 19 cryptex links, SHA256 7c610c6a...297a, `ios16-root-20H392-v6.simg` (full flash needed). Boot image `shim/out/shim-boot-0045n.img` (0045 + sweet-0044hi.adt). Still open: SpringBoard (no display), backboardd (uncaught exception, reason none), mediaserverd (Fig NULL dict), logd (main+0x18160), lockdownd (main+0x4c1b4).
- **System survives daemon crashes (boot 0043p, video frames VID_20261016_215006 00:25/00:42/00:54).** With the v5 plist patch no panic: launchd keeps launching (runningboardd, powerd, tccd, healthd, peopled, cryptexd, routined, aksd, mediaremoted, familynotificationd, nanoprefsyncd, navd, cloudpaird, passd, amsaccountsd, accessoryupdaterd, wcd ...). Shared cache slide that boot 0x406b4000 (`research/crash-0043p.txt`). watchdogd still crashed at main+0xb82c from the PMU step: `-wdt_no_pmu` is only honored when os_variant_has_internal_diagnostics; customer builds read `no-pmu` from IODeviceTree:/arm-io/wdt (IORegistryEntrySearchCFProperty) -> mkadt adds /arm-io/wdt {no-pmu}. **cryptexd** sig 6: abort_with_payload <- os_crash_fmt <- `__darwin_arm_secure_boot_chip.cold.7` ("panic: failed to get crypto algorithm") <- `_img4_chip_select_personalized_ap`: reads /chosen use-ddi-secure-boot, allow-ecid-mismatch, crypto-hash-method ("sha1" | "sha2-384"), /chosen/asmb lp-smb0/1 -> mkadt adds crypto-hash-method "sha2-384". **identityservicesd** sig 6 = same `_objc_fatal` in imp_implementationWithBlock as CommCenter (block trampolines; message needed). lockdownd sig 5 at main+0x4c1b4. Patch **0044**: crash report adds `CRASH name reason ns N code X: text` (exit reason description = abort_with_payload text). CI `38959096811` -> `xnu/out-0044`, QEMU OK. Image `shim/out/shim-boot-0044n.img` = 0044 + `shim/out/sweet-0044hi.adt` (wdt no-pmu, crypto-hash-method) + cmdline (wdt=-1, no -wdt_no_pmu).
- **First symbolicated daemon crashes (boot 0043u on journaled v4, 19:38:53 UTC; video frame chat image 36; transcribed in `research/crash-0043u.txt`; shared cache slide 0x40d60000 for every process).** (Gemini's video transcription invented values, use frames only.) `tools/sweet-crash.py research/dsc/dyld_shared_cache_arm64 x research/crash-0043u.txt`:
  - **watchdogd** pc main+0xb82c (`_os_crash` trap helper) from 0x100009bb0 = set PMU boot stage via IORegistry (no PMU) -> fix: boot-args `wdt=-1 -wdt_no_pmu` (Apple's own test mode writes "%s wdt=-1 -wdt_no_pmu"; watchdogd logs "skipping setting PMU boot stage because -wdt_no_pmu found in boot-args or no-pmu found in EDT"). Kernel effect of wdt=-1: sched hygiene debug off, zone_exhausted_timeout -1 (harmless).
  - **SpringBoard** sig 5 in `-[FBSDisplayMonitor _initWithBookendObserver:transformer:]+1160` <- `+[FBDisplayManager sharedInstance]` <- `FBSystemShellInitialize` <- `SBSystemAppMain`: no main display. GUI WALL: display service (IOMobileFramebuffer / CoreAnimation display).
  - **backboardd** sig 6: abort <- std::terminate <- _objc_terminate (uncaught exception; message not shown).
  - **CommCenter** sig 6: `_objc_fatal` in `imp_implementationWithBlock` (from `+[_PFRoutines initialize]`, CoreData): objc block trampolines cannot be allocated -> likely kernel gap (trampoline page remap); will hit many processes.
  - **mediaserverd** sig 11: CFDictionaryGetValue(NULL) in FigNotificationListenerStartNotifications (routing session manager).
  - **logd** sig 5 at its main+0x18160 (bt main+0x9dfc); lockdownd sig 5 (not yet symbolicated).
  - Image v5 = v4 + launchd.plist (`/System/Library/xpc/launchd.plist`, contiguous at image offset 0x1e025f000, 1456980 bytes) with the 7 `_PanicOnCrash` keys renamed `_PanicOnCrasX` in place (raw image patch, no metadata change) -> `diff-v4-v5.simg` = 7 blocks; v5 SHA256 78f96974...185a. Boot image `shim/out/shim-boot-0043p.img` = 0043 + `wdt=-1 -wdt_no_pmu`.
- **0043 console crash reports (QEMU verified); image `shim/out/shim-boot-0043u.img`; NEXT: flash v4 + boot 0043u.** Boot 0042u (video photo IMG_20261016_211646): short exec lines work; watchdogd crashes with NO `SWEET WDT:` line (fails before its first IOWatchdog call: lookup or IOServiceOpen, or elsewhere); lockdownd, SpringBoard, mediaserverd, CommCenter, identityservicesd, backboardd, watchdogd all crash repeatedly ("Too many corpses being created" = corpse limit, no crash reports). AKS callers: lockdownd (0, 7), imagent/sleepd (0, 17, 7), backboardd (0, 17), UserEventAgent (0, 7, 102, 103 -> unsupported). Patch **0043**: `sweet_crash_log` (osfmk/kern/exception.c, called from proc_prepareexit for crash exits on the current proc) prints `CRASH name[pid] sig S code (exc<<32|code) sub X slide SR mh MH`, `CRASH name pc lr sp fp far`, `CRASH name bt` (10 fp frames); AKS sel 103 notify_state_is_set -> 0. CI `38954520419` -> `xnu/out-0043`. QEMU test: init forks, child `brk #1`: `CRASH launchd[2] sig 5 code 0x600000001 sub 0x1000004f0 slide 0x0`, pc correct, parent keeps running (pid 1 crashes panic before proc_prepareexit, so test with a child). `tools/sweet-crash.py CACHE ROOT [report]` symbolicates typed-in CRASH lines (`ipsw dyld a2s` with addr - slide; main binary offsets = addr - mh + 0x100000000).
- **v3 reflashed 18:50-18:55 UTC (`research/flash-userdata-v3b.log`, 24/24 OKAY); 0042u booted 19:01:17 UTC on the clean disk (`research/boot0042u-2.log`), SLOW MO VID pending (watchdogd failure reason).** ABL hangs on the first `fastboot boot` after every big flash; user re-enters fastboot. User gave standing approval to reflash/boot without asking (memory standing-flash-approval). Commits now end with `Co-Authored-By: dipa-studio <183933817+dipa-studio@users.noreply.github.com>` (user request; never a Claude trailer).
  - watchdogd flow: connect_to_kext (0x100005408): IOServiceGetMatchingService("IOWatchdog") fails -> "failed to discover" + _os_crash; IOServiceOpen(type 1) fails -> "IOServiceOpen failed with error : 0x%x" + _os_crash. Then sel 0 (out 1 scalar): 0 -> "userspace monitoring disabled", 0x100009bb0, sleep 2, exit(0); nonzero -> "userspace monitoring enabled", normal operation.
  - **Image v4 (JOURNALED):** `tools/mkiosroot.sh` now does `mkfs.hfsplus -J`, mounts with `-o loop,force`, adds the /System/Library/Caches/com.apple.dyld hard links (44) and /private/var/keybags/systembag.kb (0700/0600 root). Built from the IPSW dmgs (OS 087-86698-044, SystemOS 087-86593-047, AppOS 087-86715-047) -> `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v4.img` SHA256 fba4aeae...ec0f9 + `.simg`. Header: attr 0x80002100 (unmounted, journaled), journal info block 129, journal 8 MiB at 532480 flagged need-init. Linux `fsck.hfsplus -n` reports "Volume header needs minor repair" on any fresh journaled volume even after -y (quirk). QEMU: 64 MB journaled test root (`rd=md0 rootrw=1`, 0042 kernel): `hfs: Initializing the journal (joffset 0x3000 sz 0x80000)` -> mounted -> init runs, no panic. NEXT: flash v4 (full), boot 0042u.
- **SPRINGBOARD STARTS (boot 0041u 18:39:53 UTC, photo IMG_20261016_204142).** backboardd, bluetoothd, fairplayd.H2, SpringBoard (pid 111, crashed: "Too many corpses"), xpcproxy run; `SWEET AKS: backboardd sel 0 -> 0`, `sel 17 in 1/0 out 0/4096 -> 0`. Panic: watchdogd[113] exited, namespace 2 subcode 5 (SIGTRAP = its _os_crash): watchdogd crashes on purpose when IOServiceGetMatchingService("IOWatchdog") fails ("connect_to_kext() unexpectedly failed") or IOServiceOpen(type 1) fails ("IOServiceOpen failed with error"); IOWatchdog DOES register (QEMU msgbuf: `SWEET WDT: IOWatchdog registered`), cause not on screen yet -> need video. Note `wdt_test=no_user_checkin` makes watchdogd log "detected testing boot-args to not run, exiting" (path not reached here?). **HFS CORRUPTION:** `hfs_swap_BTNode: offset #0 invalid (0xBC1D) (blockSize 0x2000 numRecords 81)`, `node=19677 fileID=4` (catalog), `hfs_mark_inconsistent` repeated. Likely cause: non-journaled HFS + unclean panics while writing (0038e wrote a 2.7 GB core then panicked; every boot since ends in panic). Plan: reflash v3 (clean), longer term HFS journaling. Patch **0042**: one short `exec NAME` console line instead of the 3-line "Allowing spawn of iOS binary" notice; CI `38949451276` -> `xnu/out-0042`; image `shim/out/shim-boot-0042u.img` (same cmdline as 0041u).
- **LAUNCHD DAEMONS RUN (boot 0039u, 18:29:13 UTC, photo IMG_20261016_203052).** With `launchd_unsecure_cache=1` all boot tasks pass and launchd starts LaunchDaemons (pids > 100: identityservicesd 114 and lockdownd 106 crash, "Too many corpses being created"). Fatal: `watchdogd: ERROR: failed to discover watchdog KEXT service` -> exit (namespace 2 = signal, subcode 5) -> `_PanicOnCrash` panic. watchdogd: IOServiceMatching("IOWatchdog"), IOServiceOpen type 1, IOConnectCallScalarMethod sel 0/1 (check in)/3/4 (disable/enable userspace monitoring)/5, IOConnectCallStructMethod sel 2 (1 KiB in) and 9 (small out); VM path ("detected virtual machine environment and no watchdog KEXT found, exiting...") only when it detects a VM. Console also flooded with `hfs: set hardlink bit on vol=iOSRoot cnid=321318` (Linux-made hard links lack kHFSHasLinkChainBit; repaired only in memory on each lookup). Patches **0040** (`iokit/Kernel/arm/SweetWatchdog.cpp`: IOWatchdog + IOWatchdogUserClient, all selectors succeed with zeroed outputs, each logged once as `SWEET WDT: ...`) and **0041** (sweet_hfs hfs_catalog.c: the three link-repair printfs limited to 8 per boot); CI `38948245372` PASSED -> `xnu/out-0041` (QEMU regression OK). Image `shim/out/shim-boot-0041u.img` (0041 + sweet-0038hi.adt + ufsrw rootrw + launchd_unsecure_cache=1) booted 18:39:53 UTC (`research/boot0041u.log`), photo pending.
- **v3 FLASHED + keybag passes; next wall AMFI (launchd_cache_loader).** User said "flash, nothing to lose": `fastboot -S 512M flash userdata ios16-root-20H392-v3.simg` 17:51:52-17:57:01 UTC, 24/24 chunks OKAY (`research/flash-userdata-v3.log`). userdata = v3 (SHA256 fa84274c...22df) until the next rw boot. ABL fastboot then hung ("Sending" forever, `reboot bootloader` timed out) until the user re-entered fastboot by hand (common Xiaomi ABL crash). Boot 0038e 18:06:15 UTC (`research/boot0038e-3.log`), photos IMG_20261016_200812/200838: keybag OK, then boot tasks tzinit (`Bad zoneinfo link`, resets to system partition, OK), finish-restore, finish-demo-restore, sysstatuscheck, prng_seedctl (`failed to load kernel prng seed`, `failed to load virtual random (-147)`, AllowCrash), auearlyboot, then **launchd_cache_loader: `abort: Unable to find AMFI`** -> 2.7 GB core written to /cores in 91 s -> launchd panic `launchd_cache_loader[22] exited -- exit reason namespace 7 subcode 0x1`. launchd_cache_loader: SecStaticCodeCheckValidity of /System/Library/xpc/launchd.plist with detached .sig, then IOServiceMatching("AppleMobileFileIntegrity") + IOServiceOpen type 0 + IOConnectCallMethod sel 6 (1 scalar = 1, struct in = cdhash) = trust the cdhash, then sends the cache to launchd. Boot-arg `launchd_unsecure_cache=1` skips signature + AMFI ("Using unsecure cache"); the value is parsed with strtoul base 10 (helper 0x100002da8), so a path = 0 = off: boot 0039w (18:17:13 UTC, `=/System/Library/xpc/launchd.plist`, photo IMG_20261016_202008) still aborted `Unable to find AMFI` (core dump now skipped: `Failed to generate core file ... error 14`, so 0039 works). Image `shim/out/shim-boot-0039u.img` uses `launchd_unsecure_cache=1`. Patch **0039**: do_coredump = 0 on SWEET (kern.coredump sysctl still works); CI `38945267341` -> `xnu/out-0039` (_do_coredump now in __common). Image `shim/out/shim-boot-0039w.img` = 0039 + sweet-0038hi.adt + ufsrw rootrw + `launchd_unsecure_cache=/System/Library/xpc/launchd.plist`. TODO later: real AppleMobileFileIntegrity IOService (sel 6 trust cdhash etc.).
- **Image v3 ready, awaiting user "flash".** Boot 0038w 17:38:10 UTC, photo (chat image 30): `SWEET AKS: keybagd sel 0 -> 0x0`, `sel 14 out 1/0 -> 0x0` (x2), `MKB_INIT: mount is with NO CPROTECT ... does not support Data Protection`, `System Keybag loaded`; then keybagd still opens /private/var/keybags/systembag.kb (0x100012d3c, for BackupKeyBagKeys) -> ENOENT, `no-effaceable-storage` not set -> `Can't load the keybag. tears in rain... Time to die` -> `FATAL KEYBAG ERROR: kb_load` -> reboot -> Halt/Restart Timed Out panic. Fix: ADT `/defaults/no-effaceable-storage` (mkadt.py; `shim/out/sweet-0038hi.adt`, `research/q0038-hi.adt`, QEMU OK) + file `/private/var/keybags/systembag.kb` (0600 root, dir 0700; XML plist {KeyBagKeys: data}). **v3 image** `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392-v3.img` = v2 + that file, fsck OK, SHA256 fa84274c...22df; `ios16-root-20H392-v3.simg` (img2simg: zero blocks become FILL chunks, so a full flash overwrites every block the rw boots changed). Flash: `fastboot -S 512M flash userdata ios16-root-20H392-v3.simg`, then boot `shim/out/shim-boot-0038e.img` (0038 + sweet-0038hi.adt + ufsrw=1 rootrw=1).
- **0038 AppleKeyStore (CI 38938744130 PASSED -> `xnu/out-0038`; QEMU msgbuf: `SWEET AKS: AppleKeyStore registered (no passcode, unlocked)`; phone image `shim/out/shim-boot-0038w.img` booted 17:38:10 UTC, `research/boot0038w.log`, photo pending).** QEMU full kernel log trick (fb.txt is only the last screen): `llvm-nm KERNEL | grep _msgbufp` -> `--hmp "x /1gx ADDR"` gives struct msgbuf address (static, 0xfffffe0007b56678 on 0038) -> `--hmp "x /3gx STRUCT"` gives bufc (3rd quad) -> `--hmp "memsave BUFC 0x20000 \"FILE\""` (quote the file name), `tr -d "\0" < FILE`. Same inputs give the same addresses. Boot 0037w 17:08:35 UTC, photo IMG_20261016_191052: bindfs fixed mount; mount-phase-1/2 pass; `cc_fips_test` boot task: all corecrypto FIPS POST tests PASSED in userspace; then keybag boot task `keybagd --init`: `MKB_INIT: FATAL KEYBAG ERROR: failed to load system bag`, `Could not get options entry from the device tree` (x2, IODeviceTree:/options = NVRAM, non-fatal), `REBOOTING INTO RECOVERY MODE` -> reboot -> panic `Halt/Restart Timed Out @IOPlatformExpert.cpp:884` (no restart path on SWEET).
  - keybagd (static libaks): load_devicebag (0x100012c30) calls aks_get_system (sel 14, 0-1 scalar in, 1 out) and loads /private/var/keybags/systembag.kb only if the result is 0xe00002f0 (NotFound); any other error -> fatal; SUCCESS -> skip the file (userspace-reboot path). systembag.kb is a plist {KeyBagKeys}; decrypted with effaceable storage unless IODeviceTree:/defaults has `no-effaceable-storage`. Image has no /private/var/keybags. has_data_protection: statfs of /private/var; no cprotect on our HFS -> device-bag volume mapping skipped.
  - libaks connection: IORegistryEntryFromPath / IOServiceMatching("AppleKeyStore"), IOServiceOpen type 0, then selector 0 (no args) must succeed.
  - **AppleKeyStore selector map (iOS 16.7 AppleKeyStore.framework, via `ipsw dyld disass`):** 0 open, 2 create_bag, 3 save_bag, 4 unload_bag, 5 set_system_with_passcode, 6 load_bag, 7 get_lock_state (1 in, 1 out; bit 2 = unlocked since boot), 9 unlock_device, 10 wrap_key, 11 unwrap_key, 12 unlock_bag/test_stashed_kek, 13 lock_bag, 14 get_system, 15 change_secret_se, 16 internal_state, 17 get_device_state (1 in, struct out <=4K: DER SET of SEQUENCE{UTF8 key, INTEGER}: ss state, sls lock_state (MKBGetDeviceLockState returns it), sb backoff, sbo, sfa failed attempts, sfao, sgs generation, sas assertions, sgpe grace, srcd countdown, sr reserved), 18 recover_with_escrow_bag, 19 obliterate_class_d, 20 drain_backup_keys, 21/22 set/clear_backup_bag, 23 get_bag_uuid, 24 rewrap_key_for_backup, 26/27 assert_hold/drop, 30/31 set/get_configuration, 33-37 stash, 38 auth_token_create, 40 generation, 41 fdr_hmac_data, 42 verify_password, 43 _aks_operation, 44 remote_session, 49/50 signing keys, 51/53/54 stash enable/persist/escrow, 55 unload_session_bags, 57/58 remote peer, 59-62 smartcard, 63 migrate_s_key, 65 set_keybag_for_volume_with_cookie_persona, 66/67 sync bags, 68 copy_volume_cookie_persona, 69-73 se_*, 74-79/84/85/99 fv_* (FileVault/VEK), 80/81 absinthe, 82 make_public_backup_bag, 83 drop_auxiliary_auth, 86 kext get/set options, 87 invalidate_bag, 88-91/94/95/106/107 se_*, 92 lower_iteration_count, 93 get_internal_info, 96-98/117 keybag_persona create/list/delete, 100/101 assert promote/consume, 102/103 notify_state set/is_set, 104 fairplay, 105 change_secret_epilogue, 108 delete_xart_leak, 110-113 backup volume, 114 sealed_hashes_set, 115 prewarm_sps, 118-128 AKSIdentity*/AKSGetLastUser.
  - Patch **0038**: `iokit/Kernel/arm/SweetKeyStore.cpp` (class AppleKeyStore on IOResources, IOUserClientClass AppleKeyStoreUserClient; personality in KernelConfigTables.cpp): 0/4/5/9/12/13/26/27/55/102 success, 14 -> handle 0, 7 -> 0x4, 17 -> DER state (ss 4, sls 0), others kIOReturnUnsupported; logs `SWEET AKS: <proc> sel N arg0 in a/b out c/d -> ret` for every call.
  - Tools: shared cache copied to `research/dsc/` (git-ignored; ipsw needs a writable dir for its .a2s symbol cache); `ipsw dyld disass research/dsc/dyld_shared_cache_arm64 --image AppleKeyStore|MobileKeyBag`; scratchpad `annot2.py BIN DIS FIXUPS` annotates llvm-objdump output with strings and import names (`ipsw macho info --fixups`).
- **0037 bindfs (phone boot 0037w pending photo).** Boot 0036mw 16:57:47 UTC, photo IMG_20261016_190102: WRITABLE ROOT WORKS: `/dev/ufsroot0 on / (hfs, local, noatime)` after mount_hfs update (GetMasterBlock EBUSY harmless), coredump of mount written to /cores (rw). Then `mount: failed to mount /private/preboot/5CBE3601.../usr/standalone/firmware -> ...: Operation not supported by device (19)` -> exit 74 -> launchd panic `mount[2] exited`. Cause: the macOS-derived config had nullfs but no bindfs (ENODEV = unknown fs type). Caller passes env 0 -> bind not required, ENOENT (missing source dir) tolerated. Patch **0037** adds `bindfs` to FILESYS_BASE in MASTER.arm64.sweet; CI `38936550483` -> `xnu/out-0037` (bindfs_vfsops present; QEMU probe regression OK). Image `shim/out/shim-boot-0037w.img` (0037 + sweet-0036hi.adt + ufsrw=1 rootrw=1) booted 17:08:35 UTC (`research/boot0037w.log`). NOTE: userdata has now been modified by rw boots; it no longer equals the v2 image, so sparsediff with v2 as OLD is not safe any more (full reflash or a new baseline needed).
- **0036 phone: launchd boot tasks run; mount -P 1 needs /chosen/boot-manifest-hash.** Boot 0036hr 16:15:32 UTC, photo IMG_20261016_185236: platform check passes; fsck boot task runs (`fsck: not booting main or diagnostic OS. Skipping fsck on OS container`); mount-phase-1: `failed to get filesystem info` x2 (no IODeviceTree:/filesystems/fstab, non-fatal), `mount: data volume missing, but not required in env: 0`, mount_hfs update of /: `GetMasterBlock: Error 16 opening /dev/ufsroot0` (EBUSY, mounted block dev, non-fatal) then mount() EROFS (read-only boot) -> `mount: / failed with 1`; then `failed to get boot-manifest-hash` -> errx exit 66 -> launchd panic `mount[3] exited`. /sbin/mount: fn 0x100005f90 reads IODeviceTree:/chosen boot-manifest-hash (hex), bindfs-mounts /private/preboot/<HEX>/usr/standalone/firmware (ENOENT tolerated unless required). `tools/mkadt.py` now adds `boot-manifest-hash` = SHA-384("sweet boot manifest") (5CBE3601...5205). ADTs `shim/out/sweet-0036hi.adt`, `research/q0036-hi.adt` (QEMU probe OK, csops 0x26000001). Image `shim/out/shim-boot-0036mw.img` (0036 + new ADT + ufsrw=1 rootrw=1), booted 16:57:47 UTC (`research/boot0036mw.log`): FIRST WRITABLE BOOT of userdata (restore source: v2 image on SSD).
- **0036 CS_SIGNED (phone boot 0036hr pending photo).** Phone boot 0035hr 2026-10-16 15:57:02 UTC (`research/boot0035hr.log`, photo IMG_20261016_180249): highmem works on hardware; shared cache maps (trust-cache warnings only), Apple launchd runs (`Darwin Bootstrapper Version 7.0.0`, `entering ondemand mode`), starts boot task fsck, then userspace panic `boot task is not a platform binary (fsck, /sbin/fsck)`. launchd+0x3fea0: `csops(pid, CS_OPS_STATUS)` must have bit 0x04000000. Cause: nothing set CS_SIGNED (AMFI does it in vnode_check_signature), so csproc_get_blob() returns NULL for every process and csops never reports CS_PLATFORM_BINARY (also breaks per-process cdhash/entitlement queries). QEMU probe init (`csops` status printer, scratchpad csq/) on 0035: `0x02000001`; patch **0036** (`*cs_flags |= CS_SIGNED` in the SWEET AMFI hook), CI `38929635791` -> `xnu/out-0036`: `0x26000001`. Images `shim/out/shim-boot-0036hr.img` / `-0036hw.img` (same cmdlines as 0035). 0036hr booted 16:15:32 UTC (`research/boot0036hr.log`). Next launchd boot tasks (embedded __config plist): fsck -qL and mount -P 1/2 (RequireSuccess); no /etc/fstab on the image.
- **0035 ENTITLEMENTS + PLATFORM BINARIES (QEMU verified).** `xnu/patches/0035-sweet-amfi-entitlements-platform-binaries.patch`: new `iokit/Kernel/arm/SweetEntitlements.cpp` (OSObject subclass: OSDictionary from OSUnserializeXML of the signature's XML entitlements + original XML for CS_OPS_ENTITLEMENTS_BLOB); `bsd/kern/sweet_amfi.c` answers queryEntitlementBoolean/String(+WithProc, string also matches array members), copyEntitlementAsOSObject(+WithProc, retained), asdict (retained), get_xml (kalloc_data copy); built-in MAC policy "SWEET AMFI" (registered from bsd_init before vfs/exec) with mpo_vnode_check_signature: every signed binary on the MNT_ROOTFS mount gets CS_PLATFORM_BINARY (stand-in for AMFI's static trust cache: iOS system binaries are ad-hoc, cd_flags 0x2, platform byte 0), and attaches entitlements ONLY for the writable copy (cs_blob != csb_ro_addr; revalidation passes the RO blob). LESSON: first version attached in adjustContextWithoutMonitor -> QEMU `unable to adjust OSEntitlements context without monitor: 53` because ubc_cs_convert_to_multilevel_hash (4K-page signatures on 16K kernel) sets csb_entitlements_blob = NULL; ALL iOS 16 binaries (launchd, backboardd, SpringBoard) use 4K code pages, so this would have broken launchd on the phone. Boot-arg `sweet_amfi_debug=1` logs `SWEET AMFI: <ident>: N entitlements (test: ...)`. `tools/mkinit.py OBJ OUT [ENTS.plist]` adds an XML entitlements blob (special slot -5; default output byte-identical). QEMU `research/q0035-ent` (RAM disk `research/root-hfs-ent.img`, init with 3 test entitlements, highmem): `org.sweet.init: 3 entitlements (test: bool 1 string 1 array 1)` then init PID 1. MAC policies loaded: 0034 = 1, 0035 = 2 (QMP `mac_policy_list`). CI `38909807230` -> `xnu/out-0035`. Phone images: `shim/out/shim-boot-0035hr.img` (highmem, ro), `-0035hw.img` (highmem, +ufsrw=1 rootrw=1), `-0035r.img` (low mem fallback).
- **PHONE TEST ORDER (updated):** 0035hr -> if instant reset, 0035r -> then 0035hw.

- **HIGHMEM: XNU in the upper DDR bank, ~3.95 GiB (was 1.2 GiB).** Live FDT memory = <0x80000000 2G> + <0x1_00000000 0xfcc00000>; all fixed reserved-memory carve-outs are in the low bank (highest: ramdump_fb 0xaf000000, rmtfs ~0xfde01000), dynamic pools have alloc-ranges <= 0xffffffff, UFS node has no `iommus` (Linux DMAs anywhere). `tools/mkadt.py --highmem` sets /chosen dram-base 0x100000000 dram-size 0xfcc00000; `tools/mkpayload.py` now takes phys_base/mem_size from the ADT (default payloads byte-identical, verified); `tools/qemu-sweet.py` sizes -m from the payload (8G for highmem). Patch **0034** (`0034-sweet-ufs-dma-above-4g.patch`): UFS refuses DMA memory above 4G without UFSHCI CAP.64AS (bit 24), logs `DMA at 0x...`. CI `38905889883` success -> `xnu/out-0034`. **QEMU verified** (`research/q0034-hi`, ADT `research/q0034-hi.adt` --qemu --highmem, HFS RAM disk): phys_base 0x100000000, init PID 1 heartbeat, no panic; `max_mem` = `mem_size` = 0xfcc00000 read via QMP (`research/q0034-hi-mem`). Phone images: `shim/out/shim-boot-0034hr.img` (read-only) / `-0034hw.img` (+ufsrw=1 rootrw=1), ADT `shim/out/sweet-0034hi.adt` (asmb SIP + sweet-ufs + highmem). PHONE RISK: unknown runtime TZ/XPU protection in the upper bank would show as an instant reset; fall back to 0033r/w. Watchdog ruled out for the overnight reset: msm-watchdog bark is 20 s (qcom,bark-time 0x4e20) yet panic screens stay up for many minutes.

- **Offline research 2026-10-16 (user away, phone unavailable). Images rebuilt** `shim/out/shim-boot-0033r.img` / `-0033w.img` now also carry `wdt_test=no_user_checkin`. NEXT ON PHONE: boot 0033r (expect past in6_nigroup), then 0033w (first writes: rw root fixes HFS link-chain bits itself and gives /var for launchd sockets /var/run/syslog, /var/run/lockdown.sock).
- **launchd.plist** (`/System/Library/xpc/launchd.plist`, compiled; 532 daemons, 66 RunAtLoad/KeepAlive, list in scratchpad `early-daemons.txt`). `_PanicOnCrash` daemons: containermanagerd/usermanagerd (InternalOnly), lockdownd/remoted/trustd/remotepairingdeviced (AutomationOnly), **watchdogd unconditional** (KeepAlive SuccessfulExit=false). watchdogd needs IOKit `IOWatchdog` kext service; if absent it exits only when `kern.hv_vmm_present` (ADT `/defaults/vmm-present`, hvg_sysctl.c) or with boot-arg `wdt_test=no_user_checkin` ("detected testing boot-args to not run, exiting"; reads kern.bootargs). Using the boot-arg (vmm-present would change many daemons; keep as an option).
- **GUI path research (QuartzCore in the shared cache, `ipsw dyld str CACHE STR`, ~10 s/search):** CA::WindowServer has IOMFBServer/IOMFBDisplay (Apple DCP/IOMobileFramebuffer), AppleCLCDDisplay, AppleRGBOutDisplay, **VirtualServer/VirtualDisplay** and **MemorySurface**, EAGLServer. Renderers: CA::OGL::MetalContext, GLContext and a **CPU software rasterizer CA::OGL::SW** (samplers/blend modes; "image is too large for software renderer"). Env knobs: `CA_ENABLE_OGL`, `CA_DISPLAY_TYPE`, `CA_FORCE_LOCAL_SERVER` (249 CA_* vars). Hypothesis (unverified): backboardd's render server could run a VirtualServer/MemorySurface with the SW renderer and we copy the surface to the ABL framebuffer -> needs disassembly of CA::WindowServer server creation. Expected other GUI walls: IOSurface (closed-source kext; needs a reimplementation), IOMobileFramebuffer user client, IOHID touch events, AppleKeyStore/keybag (SEP) for lock state, MobileGestalt answers (AppleCLCD etc.).

- **0032r RESULT (boot 05:07:50 UTC, `research/boot0032r.log`, photo IMG_20261016_071200): SHARED CACHE MAPPED, LAUNCHD RUNS.** With SIP relaxed (ADT asmb) the `not in trust cache` lines are only warnings for every subcache (.31 ... .42.dyldlinkedit); no SIP rejection; libSystem loads; launchd configures networking (`skip attaching fsw to lo0 using legacy TX model`) -> kernel data abort far 0x28 in `SHA1Init` (symbolized as sha1_init) from `in6_nigroup` (IPv6 on lo0): g_crypto_funcs NULL. Kernel addresses are unslid: `~/swift/usr/bin/llvm-symbolizer --obj=KERNEL ADDR` works directly.
- **0032** BearSSL SHA-1 (`0032-sweet-bearssl-sha1.patch`), **0033** BearSSL SHA-384/512 (`0033-sweet-bearssl-sha384-sha512.patch`, BearSSL ctx stored in SHA512_CTX, static-asserted to fit; ubc_subr.c uses SHA-384 for code directories). `0020-stage-bearssl.sh` now also stages hash/sha1.c, hash/sha2big.c, codec/{dec,enc}{32,64}be.c. CI `38854909053` success (0032-only run `38854802073` superseded). Kernel `xnu/out-0033` (SHA1Init -> _br_sha1_init verified by disassembly; nm symbols have a leading underscore). Images (ADT sweet-0032): `shim/out/shim-boot-0033r.img` (read-only), `shim-boot-0033w.img` (+ufsrw=1 rootrw=1). Still NULL g_crypto_funcs users: des, chacha20poly1305, rsa, aesxts, rand, flow_divert.
- `research/check-patch-order.py` now skips patches touching CI-staged sweet_hfs sources (0031) instead of stopping.

- **0031r RESULT (boot 05:03:52 UTC 2026-10-16, `research/boot0031r.log`, photo IMG_20261016_070508): SHARED CACHE FOUND.** dyld now opens `dyld_shared_cache_arm64` (v2 image hard links), kernel refuses to map it: `shared_region: ... map(...'dyld_shared_cache_arm64'): not in trust cache` -> `vnode is not SIP-protected` (vm_unix.c: macOS arm64 path needs trust cache, else root-owned + SF_RESTRICTED unless CSR_ALLOW_UNRESTRICTED_FS) -> `dyld cache '(null)' not loaded: syscall to map cache into shared region failed` -> libSystem not loaded -> coredump to /cores fails error 30 (EROFS) -> panic initproc failed -> "MACH Reboot" (spins; screen kept). Lots of `hfs: set hardlink bit on vol=iOSRoot cnid=... linkid=...` spam (Linux-made hard links lack the link-chain bit; read-only mount cannot persist the fix). FIX: ADT `/chosen/asmb` with `lp-sip0`=0x6f (u64; incl. CSR_ALLOW_UNRESTRICTED_FS) and `lp-sip1`=1 (unauthenticated root), `tools/mkadt.py` -> `shim/out/sweet-0032.adt`. Images with kernel 0031: `shim/out/shim-boot-0032r.img` (read-only) and `shim-boot-0032w.img` (+ufsrw=1 rootrw=1).

- **2026-10-16 morning:** userdata now = **v2** image (`diff-v1-v2.simg` flashed 21:06:50 UTC 2026-10-15, OKAY, `research/flash-userdata-diff-v2.log`); future diffs use `ios16-root-20H392-v2.img` as OLD. Booted `shim-boot-0029k.img` (ignition_level=1) right after (`research/boot0029k-v2.log`); **no photo** (user asleep). Next morning the phone was in PixelOS recovery = some hardware reset (ABL then booted Android, which cannot use userdata). OBSERVATION: our kernel cannot reset the SoC itself (`PE_halt_restart` is never set; reboot/halt print "MACH Reboot"/"CPU halted" and spin), so the reset came from outside XNU: Qualcomm watchdog or a TZ/XPU violation. Unknown which; re-boot 0029k and watch/video until the reset. Do NOT tap factory reset/format data in recovery (would wipe the iOS image).
- **0030** (`xnu/patches/0030-sweet-ufs-writes.patch`, CI `38852655542`): UFS WRITE(10) + read-modify-write for partial 4 KiB blocks + SYNCHRONIZE CACHE (DKIOCSYNCHRONIZE), only with boot-arg `ufsrw=1`; `ufs_write_blocks` re-checks partition bounds before every write (only place data goes out).
- **0031** (`xnu/patches/0031-sweet-read-write-root.patch`, CI `38852837176`): boot-arg `rootrw=1` clears MNT_RDONLY before the root mount (no data volume on sweet: /private/var is on the root; image has no /etc/fstab); Apple HFS accepts a dirty non-journaled ROOT read-write on SWEET (logs "mounting dirty non-journaled root read-write"). Later: journaled HFS for crash safety. Kernel `xnu/out-0031` (CI `38852837176` success, 5m31s; 0030 run cancelled by the newer push). Boot images (phone ADT `sweet-0028.adt`, ramdisk byte-matched): `shim/out/shim-boot-0031r.img` = 0029k args (read-only, ignition_level=1) and `shim/out/shim-boot-0031w.img` = same + `ufsrw=1 rootrw=1`. PLAN: boot 0031r first and film until the reset (diagnose overnight reset), then 0031w (first ever writes to userdata; v2 image on the SSD is the restore source). `research/check-patch-order.py` cannot check 0031 (staged sweet_hfs files are not in its index); CI stage scripts run first, so CI is the check.

- **ignition_level=1 result** (boot 21:01:39 UTC, `research/boot0029k.log`, photo IMG_20261015_230308): preboot/cryptex stages skipped (need >= 2/3), `dylib_cache: finding shared cache on system volume: ignition level = 1, search root fd = 4, subpath = System/Library/Caches/com.apple.dyld/` -> not found -> `ignition boot failed: 19` -> no shared cache -> libSystem not loaded. FIX IN PROGRESS: image v2 = copy of the flashed image + `/System/Library/Caches/com.apple.dyld/` with HARD LINKS to the 44 cryptex cache files (no extra space; avoids symlink-following doubts), then `tools/sparsediff.py ios16-root-20H392.img ios16-root-20H392-v2.img diff.simg` and flash only the diff. Boot with `ignition_level=1` (shim-boot-0029k.img).
- **ignition_level=0 result** (boot 20:58:07 UTC, `research/boot0029j.log`, photo IMG_20261015_230037): all stages skipped as "ignition level insufficient" (hello/preboot/cryptex1 sniff >= 2, select os cryptex path/graft >= 3, **dyld_cache >= 1**), `ignition boot failed: 89`, "ignition partially disabled", then same `Library not loaded: /usr/lib/libSystem.B.dylib (no such file, no dyld cache)`. => dyld gets the shared cache directory from ignition's dyld_cache stage. Next: `ignition_level=1` (`shim/out/shim-boot-0029k.img`) to skip preboot/cryptex stages but run dyld_cache; its log "finding shared cache on %s ... subpath = %s" will show where it searches. If it searches rootfs /System/Library/Caches/com.apple.dyld, add a symlink there (image rebuild; consider a diff-only sparse flash tool to avoid rewriting 12 GB).
- **APPLE dyld/launchd RUNNING (libignition) with `unentitled_ios_sim_launch=1`** (boot 20:53:24 UTC, `research/boot0029i.log`, photo IMG_20261015_225617): kernel prints "Allowing spawn of iOS binary ... boot-arg set to true"; `shared_region: ... check_np ... vm_shared_region_start_address() failed` (no region yet, normal); dyld's built-in **libignition** (Darwin Ignition Sequence 1.0.0, libignition-51~1974; prints rd=ufsroot0, hardware target sweet, ignition level 0x5, platform 0x2, boot spec local, 7 stages): `hello from launchd.1` -> `preboot: mounting preboot` -> `failed to lookup preboot: 25` (ENOTTY: looks for a separate Preboot volume by role) -> ignition fails -> dyld `Library not loaded: /usr/lib/libSystem.B.dylib ... (no such file, no dyld cache)` -> launchd exit -> panic initproc failed. dyld boot-args found via strings: `ignition_level`, `ignition_force_dylib_root` (forced rootfs/livefs/cryptex fallback), `ignition_halt_after`, `ignition_live_app_graft`; dyld cache search paths include /System/Cryptexes/OS, /System/Volumes/Preboot/Cryptexes/OS/, /private/preboot/Cryptexes/OS/ (present in our image). Next try `ignition_level=0` (`shim/out/shim-boot-0029j.img`).
- **APPLE launchd EXECUTED FROM UFS (2026-10-15).** Flashed iOS image: `img2simg` -> `ios16-root-20H392.simg` (12.1 GB) then `fastboot -S 512M flash userdata ...simg` (24 chunks, 307 s, `research/flash-userdata-ios16.log`; a raw-image flash was killed by earlyoom at 2.6 GB RSS - always flash the sparse image). ABL fastboot hung on getvar after the flash; power+vol-down fixed it. Boot 0029u 20:49:04 UTC (`research/boot0029u-ios16.log`), photo IMG_20261015_225134: `hfs: mounted iOSRoot` -> load_init_program /sbin/launchd -> panic `unexpected SIGKILL of launchd (CS_KILLED) with reason -- namespace 9 code 0xe` = OS_REASON_EXEC / EXEC_EXIT_REASON_WRONG_PLATFORM: our kernel is XNU_TARGET_OS_OSX, iOS-platform binaries are "alien" and refused unless spawn attr platform set or DEVELOPMENT TUNABLE `unentitled_ios_sim_launch`. Next try: same kernel, cmdline + `unentitled_ios_sim_launch=1` (`shim/out/shim-boot-0029i.img`). LONGER TERM: macOS-config kernel marks iOS maps alien (vm_map_mark_alien) and differs from iOS in many policies; an iPhoneOS-config kernel build may eventually be needed.
- **iOS 16 ROOT IMAGE BUILT:** `/run/media/dipa/android/ios-sweet-ipsw/ios16-root-20H392.img` (16 GiB case-sensitive HFS+, label iOSRoot, 12 GB used, fsck OK after `fsck.hfsplus -y` rewrote 32 non-ASCII localized WorkflowKit Shortcut names Linux decomposes differently). Built by `tools/mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]` (needs sudo; apfs-fuse as root; OS dmg is UDIF -> link must end .dmg). Contents: iPhone X 20H392 OS root + SystemOS cryptex at /private/preboot/Cryptexes/OS (so /System/Cryptexes/OS -> cache, 44 files, dyld_v1 arm64) + AppOS at .../App. /sbin/launchd and /usr/lib/dyld root:wheel 0755. NEXT: (confirm) `fastboot flash userdata ios16-root-20H392.img` (auto-sparse), boot 0029u (rd=ufsroot0) -> Apple launchd attempt.
- **MILESTONE ON HARDWARE: BOOT FROM INTERNAL FLASH.** 0029 CI `38797924912` PASSED, `xnu/out-0029` SHA256 `a68bc847...2a37`. Image `shim/out/shim-boot-0029u.img` (payload-0029u = 0029 kernel + `shim/out/sweet-0028.adt` + `rd=ufsroot0`, NO RAM disk). Boots 20:01:34 and 20:12:37 UTC (`research/boot0029u*.log`), photo IMG_20261015_221403: `SWEET UFS: "userdata" on LUN 0: first block 0x2b8c00, 109643 MiB, read-only` -> `BSD root: ufsroot0, major 1, minor 0` -> `hfs: mounted SweetRoot on device b(1, 0)` -> `SWEET: root volume is not authenticated (error 25); continuing unsealed` -> `load_init_program ... /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> heartbeat (ran for minutes unattended). userdata currently holds the 8 MB `research/root-hfs.img`. NEXT: build a multi-GB HFS+ image with the iOS 16 (iPhone X 20H392) userland (OS rootfs + SystemOS cryptex contents incl. dyld shared cache at /System/Library/Caches/com.apple.dyld; preserve modes/owners/symlinks; decompress LZBITMAP via apfs-fuse), flash it to userdata (sparse, needs user OK), then try Apple's dyld/launchd. Driver is read-only (root mounts RDONLY), fine for first launchd attempts.
- **userdata FLASHED with the 8 MB HFS test volume** (user said "flash it", 2026-10-15 19:53:17 UTC, `research/flash-userdata-hfs-test.log`: `fastboot flash userdata research/root-hfs.img` OKAY; pre-checks: one sweet device, partition-size:userdata 0x1AC4BFB000, partition-type f2fs, image fsck OK, SHA256 3626ea69...). Android userdata is now destroyed (expected/approved). Boot 0028u at 19:53:20 (`research/boot0028u-hfs.log`), photo IMG_20261015_215541: `BSD root: ufsroot0` -> **`hfs: mounted SweetRoot on device b(1, 0)` from internal UFS** -> panic `rootvp not authenticated after mounting @bsd_init.c:931` (arm64 macOS-config requires FSIOC_KERNEL_ROOTAUTH sealed root for non-ramdisk roots). Patch **0029** (`dd1c284`): SWEET logs `SWEET: root volume is not authenticated (error N); continuing unsealed` instead of panicking (Apple configs keep the panic; pivot_root still requires auth). CI **`38797924912`** running. Next: download out-0029, phone image with sweet-0028.adt + rd=ufsroot0 (no RAM disk), boot -> expect init from UFS.
- **UFS ROOT DRIVER VERIFIED ON HARDWARE (read-only).** 0028 CI `38796139570` PASSED, `xnu/out-0028` SHA256 `8b981640...9da6`; QEMU HFS RAM-disk regression `research/q0028-hfs` still runs init. Phone boot 2026-10-15 19:50:24 UTC (`research/boot0028u.log`, image `shim/out/shim-boot-0028u.img`, phone ADT `shim/out/sweet-0028.adt` with /sweet-ufs, NO RAM disk, `rd=ufsroot0`), photos IMG_20261015_215151/215220: `SWEET UFS: "userdata" on LUN 0: first block 0x2b8c00, 109643 MiB, read-only` -> `BSD root: ufsroot0, major 1, minor 0` -> `hfs_ValidateHFSPlusVolumeHeader: unknown Volume Signature : f188` (Android-encrypted data, as expected) -> `cannot mount root, errno = 19`, kernel retries mountroot (no panic). Nothing written to flash. NEXT (destructive, needs user confirmation right before): `fastboot flash userdata research/root-hfs.img` (8 MB HFS with test init) then boot rd=ufsroot0 -> expect init from internal flash.
- **PATCH 0028 (`33aceac`): XNU read-only UFS root device**, CI **`38796139570`** running (next artifacts xnu/out-0028, research/bt29, run29.log). `bsd/dev/sweet_ufs.c`: reuses ABL's UFSHCI state (like the shim probe), takes over UTRL at a kmem_alloc_contig region (DMA layout: UTRL 0x0, UCD 0x1000, 1 MiB bounce 0x4000), verifies UTRLBA readback before any doorbell, IE=0 polled, one SCSI cmd at a time on LUN0 (TUR x3, READ(10) via bounce, PRDT 256 KiB chunks), flush_dcache64 by PA around each command (host not dma-coherent per DT), finds GPT partition by name (`ufsroot=` boot-arg, default `userdata`), exposes `/dev/ufsroot0`/`rufsroot0` (512-byte logical sectors, physical 4 KiB, DKIOC* ioctls), refuses writes (EROFS). IOKitBSDInit: `rd=ufsroot0` -> sweet_ufs_rootdev() (lazy init) else panic. ADT: `tools/mkadt.py` adds `/sweet-ufs` reg <0x1d84000 0x3000> for the PHONE only (not --qemu). Local compile OK, imports resolve. Sandbox research/bt28 (pre0028 originals). FIRST PHONE TEST PLAN (non-destructive): boot 0028 with phone ADT + `rd=ufsroot0` and NO RAM disk: expect `SWEET UFS: "userdata" on LUN 0: first block 0x2b8c00, 109643 MiB` + `BSD root: ufsroot0`, then root mount failure (userdata is still Android-encrypted) -> panic. That validates the driver before flashing an HFS image into userdata (needs explicit user confirmation at that time).
- **SUPERSEDES the 64 GiB iosroot GPT plan: user said "u can delete android" (2026-10-15).** Use the existing `userdata` partition (LUN0 sda34, 4K LBA 0x2B8C00, 0x1AC4B MiB ~107 GiB) directly as the iOS root: NO GPT changes. Keep bootloaders, recovery (OrangeFox), modem/persist/fsg/modemst untouched. Write the HFS image later with `fastboot flash userdata` (sparse, auto-split under the 768 MiB limit). Android will no longer boot normally (expected; reinstallable). Order: XNU UFS driver first, read-only against the current GPT; flash only once it can locate userdata. Nothing erased yet.
- **DECIDED (user, 2026-10-15): 64 GiB `iosroot` on LUN0 (sda), taken from userdata (wipes Android user data; Android/super kept).** Planned GPT (4K LBAs): userdata 0x2B8C00..0xD7D6FF (~43 GiB, keep type/unique GUIDs and attributes); iosroot 0xD7D700..0x1D7D6FF (0x1000000 blocks = 64 GiB, 1 MiB aligned); backup GPT area unchanged. Procedure: user backs up phone data -> boot OrangeFox recovery (adb) -> back up GPT (sgdisk --backup + raw dd of LBA 0-5 and last 6 blocks) to research/ -> sgdisk edit -> Format Data -> verify Android boots to setup. NOT EXECUTED YET.
- **INTERNAL UFS WORKS FROM THE SHIM (read-only), user authorized internal-UFS approach incl. flashing (2026-10-15, "i allow everything").** Shim probe `shim/ufs.c` (commit `12ed3ed` + filter): ufshc@1d84000 is UFSHCI 2.1 (ver 0x210, cap 0x1587031F, 32 slots), ABL leaves HCE=1, HCS=0x10F (device present, lists ready, UIC ready); probe takes over UTRL at its own buffer (verifies UTRLBA readback before any doorbell), TEST UNIT READY/READ CAPACITY/READ(10) all succeed. LUN0 = 0x1D7D800 x 4 KiB (~126.6 GB), valid GPT (64 entries at LBA 2). Photos IMG_20261015_212916/213325/213429. Big LUN0 partitions (start in 4K LBAs / MiB): super 0xCA00/0x2200 (8.5 GiB), logdump 0x22CA00/64, minidump 0x230A00/128, rawdump 0x238A00/128, recovery 0x240C00/128, cache 0x248C00/384 ext4, exaid 0x260C00/384, cust 0x278C00/1024 ext4, **userdata 0x2B8C00/0x1AC4B MiB (~107 GiB), fs unreadable = encrypted (metadata encryption)**. cache..cust contiguous = only 1.75 GiB (too small for iOS ~10+ GiB). Plan needing user consent: shrink userdata in GPT (wipes Android data) and add an `iosroot` partition at the end of LUN0. LUNs 1-5 not listed yet (sdb..sdf backed up in backup/lun).
- **fastboot limit measured (2026-10-15, read-only getvar):** `max-download-size: 805306368` (768 MiB); `max-fetch-size` unsupported; `is-userspace: no` (ABL fastboot). A `fastboot boot` image (shim+kernel+RAM disk) must be < 768 MiB, so the 2.5 GiB iOS shared cache cannot ride in the boot RAM disk even if XNU gets all RAM. Real userland needs storage access (UFS driver, or USB host) or a much smaller cache. Unlocking full RAM is still needed later (GUI).
- **iOS 16 USERLAND SOURCE (Claude, 2026-10-15).** Chose **iPhone X (iPhone10,3/10,6, D22/D221AP)** iOS **16.7.16 (20H392)** over iPhone 8: same A11 (no PAC -> plain arm64, runs on Kryo 470/ARMv8.2), last iOS for A11; X userland is home-button-less and tall-screen (1125x2436 vs sweet 1080x2400), better fit for later GUI. Note the X has its OWN SystemOS cryptex (different digest from iPhone 8's). IPSW URL in `research/ipsw-x/URL.txt` (+ BuildManifest). Images on the user's external SSD (NOT in git, do not format that disk: it holds the user's photos): `/run/media/dipa/android/ios-sweet-ipsw/iPhone10,3_16.7.16_20H392/` — `087-86593-047.dmg` = Cryptex1,SystemOS (2,743,074,816 B), `087-86698-044.dmg` = OS rootfs (4,730,814,044 B), both zip CRC-32 verified, plus Firmware/*.root_hash/.trustcache/.mtree. AppOS cryptex is 087-86715-047.dmg (10 MB, same as iPhone 8).
  - Images are raw APFS; files use LZBITMAP (decmpfs type 14). 7z cannot decode. Tools: `ipsw` 3.1.738 (AUR ipsw-bin, user-approved) needs apfs-fuse on Linux; **apfs-fuse** built in user space (system cmake broken: cmake 4.4.4 wants libjsoncpp.so.27, jsoncpp 1.9.6 installed = partial upgrade, NOT fixed) with pip cmake + `-DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_CXX_FLAGS="-include cstdint"`, installed to `~/.local/bin/apfs-fuse` (+apfs-dump-quick). Mount via a comma-free symlink (apfs-fuse splits options on ',' in `iPhone10,3`; exFAT has no symlinks -> put link elsewhere): `apfs-fuse LINK/087-86698-044.dmg MNT` -> `MNT/root/...`; unmount `fusermount3 -u MNT`.
  - Verified from headers: `dyld_shared_cache_arm64` magic `dyld_v1   arm64`; `/sbin/launchd`, `/usr/lib/dyld` = cputype 0x100000c subtype 0 (plain arm64). libSystem exists only inside the cache.
  - **BLOCKER for real userland via RAM disk:** shared cache = 3.10 GiB in 44 files (~2.5 GiB without the 592 MB `.symbols`), but the kernel manages only 1.20 GiB (0xb0000000..0xfd000000). Options: (A) give XNU the phone's full ~6 GB (banks 0x80000000+2G and 0x100000000+0xfcc00000, carve-out holes need pmap support) AND check fastboot max-download-size for a multi-GB boot image; (B) storage driver (Qualcomm UFS) to read a root from flash (no flashing allowed: would need a file/partition strategy); (C) run against individual dylibs extracted from the cache (uncertain).
- **MILESTONE ON HARDWARE: HFS+ ROOT FILESYSTEM -> PID 1.** Boot 2026-10-15 18:22:12 UTC (`research/boot0027b.log`, image `shim/out/shim-boot-0027b.img`), photo `IMG_20261015_202334.jpg`: `BSD root: md0` -> `hfs: mounted SweetRoot on device b(1, 0)` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> repeated `SWEET init: still alive`, no panic. Kernel 0027 (built-in Apple OSS HFS + BearSSL MD5), init with SP alignment fix. NEXT: real iOS 16 userland on the HFS image (dyld, libSystem/dyld shared cache, launchd). Known gaps: entitlements (none granted), SHA-1/SHA-384/512 providers, no storage driver (RAM disk only), root mounted read-only.
- **PHONE HFS ROOT (0027) + SIGBUS ROOT-CAUSED.** Phone boot 2026-10-15 17:49:06 UTC (`research/boot0027.log`, photo `IMG_20261015_200031.jpg`): `hfs: mounted SweetRoot on device b(1, 0)` (HFS works on hardware), init printed its first line, then `pid 1 exited -- exit reason namespace 2 subcode 0xa` = SIGNAL/SIGBUS -> `initproc failed to start` panic. Diagnostic boot 18:08:13 UTC (`research/boot0027d.log`, image `shim/out/shim-boot-0027d.img`, diag init `research/diag-init` from scratch diag-init.S with [a][b][c] markers, `cs_debug=1`; photo `IMG_20261015_201547.jpg`): output `PID [a][b]` then SIGBUS -> fault at first `strb w21,[sp]`; no code-signing messages. Cause: kernel enters a static binary with sp at argc, not necessarily 16-aligned (depends on arg/apple string lengths, differs mockfs vs HFS); EL0 SP alignment check -> EXC_ARM_SP_ALIGN -> SIGBUS (sleh handle_sp_align). QEMU does not enforce SP alignment. NOT a kernel bug: real binaries start in dyld which aligns. Fix `1a8fc15`: sweet-init aligns sp at entry. Rebuilt `research/root-hfs.img`, QEMU `research/q0027-hfs2` OK. Phone image `shim/out/shim-boot-0027b.img` SHA256 `098ba46c...c5c` (payload-0027b, ramdisk match check-0027b) ready, awaiting FASTBOOT. Lesson: Assembly `;` is a comment in Apple arm64 asm (use .macro, not ;-joined #define).
- **HFS ROOT WORKS (QEMU).** 0027 CI `38779441895` PASSED, `xnu/out-0027` SHA256 `a8643886...5f6a`. QEMU `research/q0027-hfs` (RAM disk = `research/root-hfs.img`, rd=md0): `BSD root: md0` -> `hfs: mounted SweetRoot on device b(1, 0)` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` + heartbeat, no panic. Phone image `shim/out/shim-boot-0027.img` (payload-0027 = 0027 kernel + sweet-0021.adt + root-hfs.img + rd=md0, ramdisk byte-match check-0027) ready; awaiting FASTBOOT for phone test.
- **HFS ROOT WORK (Claude), patches 0026-0027.**
  - 0026 (`f0e990c` + link fix `64c96f4`): Apple OSS **hfs-627.100.6** (commit `31d5ec238dfab485e78a9a30b8b92d13e8914f03`, paired with xnu-8796.141.3 in macos-135 release.json) staged by `xnu/patches/0026-stage-hfs.sh` into `bsd/sweet_hfs` (core + hfs_encodings; AppleKeyStore include/key prototypes guarded by CONFIG_PROTECT; SDK TargetConditionals copied). New config option `sweet_hfs` (MASTER + MASTER.arm64.sweet); 40 `optional sweet_hfs` files; Makefile.template foreach adds `_CFLAGS_ADD = -include sweet_hfs_compat.h -I...` (MUST come after kernel -D flags; compat undefs BSD/XNU_KERNEL_PRIVATE and the CONFIG_* HFS tests so kext-config.h decides: macOS profile, no content protection). `sweet_hfs_iokit.c` replaces hfs_iokit.cpp/hfs_encodings_kext.cpp: `sweet_hfs_register()` called in bsd_init after vfsinit (encodings init, vfs_fsadd VFS_TBLCANMOUNTROOT, zones, sysctls); is_ejectable 0, iterate_media none, serial KERN_NOT_SUPPORTED, OSKextGetCurrentLoadTag -> kOSKextInvalidLoadTag (renamed via compat macro). hfs_encodings' own `hfs_allocated` renamed per object (separate kexts on Apple; first CI `38777325964` failed on that duplicate at link). mockfs now validates Mach-O magic (its TODO) so non-Mach-O roots fall through to HFS (new fs entries come AFTER mockfs in vfsconf). CI `38778133720` PASSED, `xnu/out-0026` SHA256 `0b49170c...701a`, prints `SWEET HFS: hfs-627.100.6 registered`.
  - HFS+ image: `research/root-hfs.img` (8 MB, mkfs.hfsplus from AUR hfsprogs installed with user approval; loop-mounted with sudo; /sbin/launchd = research/sweet-init, /dev; fsck.hfsplus OK). QEMU `research/q0026-hfs`: `BSD root: md0` then data abort in MD5Init from hfs_getvoluuid (mount computes volume UUID).
  - 0027 (`14bf2b7`): 0020 stager also copies BearSSL hash/md5.c + codec/dec32le.c/enc32le.c; `corecrypto_md5.c` SWEET branch converts MD5_CTX <-> br_md5_context around br_md5_* calls; wrappers sweet_md5.c/sweet_dec32le.c/sweet_enc32le.c. Host test 40/40 match md5sum. CI **`38779441895`** running.
  - Local tooling: `tools/xnu-cc.py` has `XNU_CC_POST` (flags after logged ones). Sandbox `research/bt28/xnu` = 0025 CI tree + 0026/0027 edits; originals `research/pre0026`, `research/pre0027`. HFS local objects `research/hfs-objs`. Checker entries updated to bt28.
  - SHA-1 / SHA-384/512 still have no provider.
- **MILESTONE ON HARDWARE: USERSPACE PID 1 RUNS ON THE PHONE.** Boot 2026-10-15 17:16:00 UTC (`research/boot0025.log`: send OKAY0.410s, boot OKAY0.135s), image `shim/out/shim-boot-0025.img` SHA256 `9dbfa0b1...89db0`. Photo `IMG_20261015_191733.jpg`: `BSD root: md0` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> repeated `SWEET init: still alive` (5 s heartbeat), no panic. Kernel 0025 + mockfs RAM disk + built-in no-entitlements AMFI. No flashing performed.
- **NEXT (toward real iOS userland):** real root filesystem with real binaries. Options: (a) build Apple OSS `hfs` (macOS 13.5 tag `hfs-627.100.6`) into SWEET like libpthread, then an HFS RAM disk image; (b) iOS 16 dyld + libSystem/dyld shared cache from the IPSW (needs APFS or repacking onto HFS). Expected hurdles: entitlements (sweet_amfi grants none), SHA-1/MD5/SHA-384/512 providers (BearSSL), missing kexts/daemons. Current init is a static test program, not launchd.
- **MILESTONE: USERSPACE RUNS (QEMU).** 0025 CI `38774788048` PASSED, `xnu/out-0025` SHA256 `5496069b...4877`. QEMU `research/q0025-rd` (150 s, no panic): `BSD root: md0` -> `load_init_program: attempting to load /sbin/launchd` -> `*** SWEET userspace: init running as PID 1 ***` -> `SWEET init: still alive` every 5 s. Exec, ad-hoc SHA-256 code signature, syscalls, devfs /dev/console, select timeouts all work. Phone image prepared: `shim/out/shim-boot-0025.img` 16,515,072 bytes SHA256 `9dbfa0b15140c0bd733a16c4f727f6a7df44a8741f98d8e266d5f2fa4f689db0` (payload-0025 = 0025 kernel + sweet-0021.adt + research/sweet-init + rd=md0; ramdisk byte-match check-0025). Waiting for user to put phone in FASTBOOT.
- **0024 CI `38773277811` PASSED**, `xnu/out-0024` SHA256 `a0ba964b...4348`. QEMU `research/q0024-rd` and **PHONE (boot 2026-10-15 17:05:55 UTC, `research/boot0024.log`, image `shim/out/shim-boot-0024.img` SHA256 `cf3dac86...6964`, 16,510,976 bytes, payload `shim/out/payload-0024.bin` = 0024 kernel + `shim/out/sweet-0021.adt` + RAM disk `research/sweet-init` + rd=md0; ramdisk byte-match `check-0024`)** agree: `Added memory device md0`, `BSD root: md0`, `load_init_program: attempting to load /sbin/launchd`, then data abort in accelerate_entitlement_queries (PC 0x...77d2458, FAR 0x1a0) = NULL AMFI interface. Photo `IMG_20261015_190715.jpg`. RAM disk root is physically verified.
- **0025 (`2518c79`)**: new `bsd/kern/sweet_amfi.c` registers a built-in AMFI interface at EARLY_BOOT/MIDDLE: no entitlements (adjustContextWithoutMonitor succeeds without creating a context, queries KERN_DENIED, copies NULL/KERN_NOT_FOUND, get_xml/transmuted false); WithMonitor KERN_NOT_SUPPORTED; OSEntitlements_query and query_context_to_object panic explicitly (CoreEntitlements closed; no kernel caller); TrustCache version 0 (0015 keys on trust_cache_rt==NULL, img4 absent -> still unavailable); CoreEntitlements table zero (PMAP_CS only). Compiles locally; checker updated (bt27 entries). CI **`38774788048`** running. Next artifacts `xnu/out-0025`, `research/bt29`, `research/run29.log`. Real iOS binaries will need real entitlements later (no OSS CoreEntitlements exists).
- **0021-0024 RAM-disk-root iteration (Claude), QEMU only so far, no new phone boot since 0020.** Each kernel tested with `tools/mkpayload.py KERNEL research/q0021.adt OUT --ramdisk research/sweet-init --cmdline "debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=md0"` then `tools/qemu-sweet.py OUT DIR --secs 150 --kernel KERNEL --fail-on-panic` (PATH needs ~/swift/usr/bin for llvm-nm). Fresh ADTs: `research/q0021.adt` (QEMU), `shim/out/sweet-0021.adt` (phone).
  - 0021 CI `38769532000` PASSED, `xnu/out-0021` SHA256 `2b7500a1...962e`, `research/bt25`/`run25.log`. QEMU `research/q0021-rd`: md0 root, then assert `iomediaClass` in IOService::publishHiddenMedia.
  - 0022 (`20ece9c`, publishHiddenMedia without IOMedia class) CI `38770666158` PASSED, `xnu/out-0022` SHA256 `a4d0e787...30c5`, `research/bt26`/`run26.log`. QEMU `research/q0022-rd`: data abort in SHA256_Init (NULL g_crypto_funcs) from vm_kernel_addrhash_internal.
  - 0023 (`c8089d1`, libkern SHA256_Init/Update/Final use built-in ccsha256_ltc_di + ccdigest_init/update on SWEET; also serves code-signing SHA-256; SHA-1/MD5/SHA-384/512 still have NO provider - BearSSL from 0020 could supply them later) CI `38771876423` PASSED, `xnu/out-0023` SHA256 `d763fed7...1003`, `research/bt27`/`run27.log`. QEMU `research/q0023-rd`: **mockfs mounted md0, `load_init_program: attempting to load /sbin/launchd`**, then panic `mockfs_fsnode_vnode failed to create fictitious pages ... rvalue = 5` (mockfs.c:351).
  - 0024 (`3293c80`): mockfs used memdev mi_base (4K page number of a VIRTUAL kernel address for IOKit RAMDisk, truncated to 32 bits) << PAGE_SHIFT as a physical address. Now zero-copy pager mapping only when mi_phys (with 4K units); virtual md uses pagein/blockmap/strategy -> memdev bcopy. memdev's own mdPhys path assumes 4K ppnums (unsafe on 16K arm64), so do NOT switch the RAMDisk to physical. CI **`38773277811`** running. Next artifacts `xnu/out-0024`, `research/bt28`, `research/run28.log`.
  - Sandboxes: bt25/bt26/bt27 contain the next patch's edited files; pristine copies in `research/pre0022`..`pre0024`.
- **PATCH 0021 (Claude): RAM disk root via mockfs -> first userspace program.** Commits `9c37771` (initial; CI `38768500280` FAILED: mockfs_fsnode.c kfree_type(mockfs_fsnode_t) typed-alloc static assert; local xnu-cc stubs `__builtin_xnu_types_compatible` so it can't catch this) and `193772f` (fix), CI **`38769532000`** running: https://github.com/dipa-studio/ios-sweet/actions/runs/38769532000. Next artifacts: `xnu/out-0021`, `research/bt25`, `research/run25.log`.
  - Kernel: `config/MASTER.arm64.sweet` FILESYS_BASE += `mockfs` (XNU's built-in FS: root device is itself a Mach-O, served as /sbin/launchd, plus /dev for devfs). Upstream mockfs bit-rot fixed: kalloc_type/kfree_type used the POINTER typedef mockfs_fsnode_t (nodes were 8 bytes) -> `struct mockfs_fsnode`. `IOService::setRootMedia` asserted IOBlockStorageDriver class exists (IOStorageFamily absent): SWEET-only, a missing class means root=NULL (same as IOSetImageBoot); Apple path keeps assert. All 21 patches apply (`research/check-patch-order.py`); 5 TUs compile locally with -DMOCKFS (`research/mockfs-objs`), imports resolve vs 0020 kernel. Sandbox `research/bt24/xnu` now holds 0021 versions of those 3 files; pristine 0020 copies in `research/pre0021`.
  - Tools: `tools/mkpayload.py --ramdisk IMAGE` appends IMAGE as an extra payload segment right after the kernel, moves kernel_end past it (shim unchanged: ADT+boot_args follow it, image stays below topOfKernelData), and adds ADT `/chosen/memory-map` `RAMDisk`=<phys,size>. Boot with `rd=md0`. Without --ramdisk output is byte-identical to existing 0020 QEMU and phone payloads (verified). `tools/sweet-init.S` + `tools/mkinit.py`: PIC static init (open /dev/console, print PID, heartbeat every 5 s via select, never exits) wrapped into a static arm64 Mach-O (__PAGEZERO, __TEXT@0x100000000, LC_UNIXTHREAD, ad-hoc SHA-256 CodeDirectory v0x20400, 4K pages). Build: `~/swift/usr/bin/clang -target arm64-apple-ios16.0 -c tools/sweet-init.S -o X.o && tools/mkinit.py X.o research/sweet-init` (ld64.lld cannot link static iOS). Signature not verified by a real codesign; the kernel will tell.
  - QEMU with 0020 kernel + RAM disk (`research/q0020-rd.bin`, rd=md0, 150 s `research/q0020-rd150`): `Added memory device md0`, **`BSD root: md0, major 1, minor 0`** (plumbing works), then the setRootMedia assert (now fixed in 0021). NOTE: QEMU needs >60 s to reach IOFindBSDRoot (60 s run showed nothing after stf0; likely RTC/inittodr wait), so use --secs 150.
  - NEXT: download 0021, QEMU 150 s with ramdisk; expect mockfs mount then init exec -> `*** SWEET userspace: init running as PID 1 ***`. Then phone boot with same payload (phone ADT shim/out/sweet-0020.adt pattern + --ramdisk + rd=md0).
- **0020 PHONE RESULT (user transcription of screen, 2026-10-15): KERNEL INIT COMPLETE, WAITING FOR ROOT.** After Skywalk self-tests PASSED, kminit, ifnet_attach lo0/gif0/stf0, screen prints `BSD`, then `Waiting on <dict><key>IOProviderClass</key><string>IOMedia</string><key>Content</key><string>Apple_HFS</string></dict>` and `Failed to write boot-picker-bringup-reason to NVRAM.` No panic. This is IOFindBSDRoot waiting for a root device (none exists); NVRAM warning is expected (no NVRAM driver). QEMU `cpu_idle` snapshot is presumably the same wait (not GDB-confirmed; milestone GDB run was cancelled by user since phone answered it). Draft `research/check-milestones20.gdb` (hbreaks inittodr/vfs_mountroot/IOFindBSDRoot/bsd_utaskbootstrap) left uncommitted/ignored.
- **NEXT MILESTONE: root filesystem -> launchd.** Plan: (1) RAM disk: shim places an image in RAM, ADT /chosen/memory-map `RAMDisk` entry, boot-arg `rd=md0` (XNU md driver). (2) HFS is a separate kext on Apple; build Apple OSS `hfs` (tag paired with macOS 13.5 in distribution-macOS macos-135 release.json) into SWEET like libpthread 0019. APFS is closed. (3) Minimal HFS image with iOS 16 launchd (later: dyld/shared cache; AMFI/code-signing absent will be a later hurdle). User's end goal is full iOS GUI.
- **0020 (AES) VERIFIED + PHONE BOOTED (Claude took over after Codex usage limit).** Actions `38765422261` (`ab9e23f`) PASSED; kernel `xnu/out-0020/kernel.development.sweet` checksum OK; buildtree `research/bt24`, log `research/run24.log`. Actual-kernel AES checks PASS (`research/check-aes20.gdb` / `.log`, 12 extra CBC cases match OpenSSL). 45s QEMU `research/q0020`: no panic, zero unknown glyphs, past old TCP/AES panic -> Skywalk self-tests PASSED -> bsd_autoconf kminit -> ifnet_attach lo0/gif0/stf0; final snapshot PC in `cpu_idle` (idle or waiting; NOT yet diagnosed, could be root-device wait). Image `shim/out/shim-boot-0020.img` 16,461,824 bytes SHA256 `775200cb02d95fc750981516b79d91dcdc96184bbe67a38f9d57c59b4a391828`, ramdisk byte-matches `payload-0020.bin` (`check-0020`). **Phone temporarily booted 2026-10-15 16:10:00 UTC**: one FASTBOOT product sweet, send OKAY0.407s, boot OKAY0.134s, total0.549s, exit0 (`research/boot0020.log`). Awaiting user photo; do not reboot the phone before it. NEXT: read photo; diagnose what QEMU waits on after stf0 (GDB backtrace of threads / longer run). Codex's STOP request below is complete.
- User requests STOP after completing the current0020 AES iteration (Actions/QEMU/phone), then leave a precise committed handoff for another AI. User says FASTBOOT ready again after0019 photo. Do not start a new blocker fix after this iteration.
- Goal: iOS16-generation XNU on Redmi Note10Pro sweet/SM7150. Always commit, use gh/Actions for kernel builds, keep this handoff current. Temporary fastboot boot only; preserve Android/backups. No userland/root filesystem boot yet.
- **Patch0020 update:** initial `e71098d` / Actions `38765012466` superseded by scalar-only compile flags. Added -mgeneral-regs-only to all six provider/BearSSL TUs and corecrypto_aes.c; object disassembly now confirms no SIMD. Updated implementation `ab9e23f`, Actions `38765422261` queued/running: https://github.com/dipa-studio/ios-sweet/actions/runs/38765422261. Do not launch another run. portable BearSSL AES CBC and legacy one-block ECB wired directly into SWEET corecrypto_aes.c. Genuine bitslice implementation, no CPU AES/SIMD requirement, heap or fake global crypto table. Source fetched by `0020-stage-bearssl.sh` from official BearSSL git at immutable `7bea48e5e850ab4cafbe68d3765cdaba13a86d6f`; MIT license retained, downloaded source stays out of git. Kernel limits include adapter only. All128/192/256-bit keys, CBC encrypt/decrypt, copied contexts, in-place/out-of-place; zero block count and size overflow handled, invalid keys clear context. Seven TUs compile to arm64 objects (`research/aes-objs`), imports resolve, all20 patches apply and sources match (`research/patch0020-check.log`). Sandbox `research/bt23/xnu`, originals `research/pre0020`. NEXT: Actions then actual-kernel NIST/random CBC/ECB checks and >=45s QEMU before another phone boot. Next artifacts out-0020 / bt24 / run24.log. 0020 updated CI pending. Local sources/checks match the scalar-only patch.
- **Latest built kernel0019**, implementation `256d3f0`, patches0001-0019. Actions `38763072907` PASSED (4m5s): https://github.com/dipa-studio/ios-sweet/actions/runs/38763072907. Kernel `xnu/out-0019/kernel.development.sweet`, SHA256 `a27df7568f03fb541cf0e8024c0a594fa178a85054fcf9eba29158cbd4c5ecc0`; checksum verified. Log/source `research/run23.log` / `research/bt23` (no nested .git). Seven pthread source/build/header files and staged adaptations byte-match local compile inputs.
- **0019 hardware photo received** `IMG_20261015_175306.jpg`: pthread registration visible, passes mbinit and DLIL checksum/scheduling, same AES fault as QEMU: PC`0xfffffe00079174e0` (`aes_encrypt_key128`), LR`0xfffffe000767c3a4` (`tcp_init`), FAR0x78, x8=0. Disassembly proves NULL g_crypto_funcs->ccaes_cbc_encrypt. Photo processed; no more0019 observation pending. General crypto table remains absent, other hash/mode operations may still fault after0020. DO NOT bypass TCP or install fake crypto. XNU already contains SHA256/HMAC implementations; AES source there is a dispatch wrapper. Full future provider interface libkern/libkern/crypto/register_crypto.h. Apple/corecrypto default README describes evaluation-only licensing, so no external corecrypto was fetched or staged; BearSSL selected for this portable AES integration.
- **0019 pthread FIXED in QEMU and observed beyond its init on phone**: 45s QEMU `research/q0019`, zero unknown glyphs, then AES panic. Actual-kernel API checks PASS `research/check-pthread19.gdb` / `.log`, guest `research/q0019-api`: function/callback table identity, actual provider pthread_init returns, locks/global hash/threadcall/typed zones initialized, thread_selfid via syscall shim + buffer bounds, process hash init/delete via shims restores NULL. Monitor quit prints expected remote-disconnect after PASS. All fixture guests stopped.
- **0019 provider**: genuine Apple libpthread-514.100.2 commit `a6c70ca0e544347a0377babf748f831577ec24f9`, exact paired release with xnu8796.141.3 in distribution-macOS/macos-135/release.json (`research/macos-135-release.json`). 0019 shell stage runs before patches (workflow copies *.sh); three SWEET wrapper TUs use kext BSD header view, vm_fault_external, renamed provider-side pthread_kern/current_uthread; register real function table at EARLY_BOOT SECOND, real pthread_init later. Stager applies bounded address casts, zero user addresses, proper panic format. SWEET opaque ksyn storage enlarged48->56 for trailing kwe_uth, checked with provider static assertion. Local pre-CI TargetConditionals fixture was syntax-only; artifact bt23 carries actual SDK header and CI is authoritative.
- **Phone0019 temporarily booted** 2026-10-15 15:51:36 UTC: exactly one FASTBOOT/product sweet verified; send OKAY0.406s, boot OKAY0.134s, total0.546s, exit0 (`research/boot0019.log`). Image `shim/out/shim-boot-0019.img`, 16,457,728 bytes, SHA256 `19429a57e486b856880df9e27327ed488e0139345311fdb0350974e72103a9a1`. Phone ADT/payload `shim/out/sweet-0019.adt` / `payload-0019.bin` timer19, unpacked ramdisk byte-match (`check-0019`). EntryPA0xb146b488, kernelendPA0xb2000000, boot_argsPA0xb2004000/top0xb2008000. Last user FASTBOOT+USB reply preceded this boot; do not assume phone is still in FASTBOOT.
- **CPU0018 physically verified** by `IMG_20261015_173951 (2).jpg`: boot CPU0 registered, real SGI1 verified, initialization complete -> BSD/MAC/mbinit -> old pthread-table panic. SweetCPU uses legacy IOCPU, ml_processor_register/processor_start/initCPU, real SGI1 clears SIGPdisabled before max CPUs completion; no forced flags/skipped waits. CPU APIs and two-CPU rejection passed (`research/check-cpu18.gdb`, `q0018-api`, `q0018-smp`). Single core; SMP/suspend unsupported. CURRENT SWEET has NO USE_APPLEARMSMP.
- QEMU next run: generate fresh `tools/mkadt.py research/q0020.adt --qemu` (timer27), mkpayload with `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`, then `tools/qemu-sweet.py PAYLOAD OUT --secs 45 --kernel KERNEL --fail-on-panic`. 12s can miss later panics because IORTC waits30s. Runner snapshot only: panic exit2, blank/incomplete exit3; absence of panic does not mean complete boot. Qualcomm XPU/ABL/panel and phone SMC PSCI require hardware checks.
- Local checker `tools/xnu-cc.py research/run23.log research/bt23 FILTER --per-file`, XNU_CC_OBJDIR for objects. For new BearSSL TUs add XNU_CC_EXTRA with -I bt23/xnu/libkern/crypto/sweet_bearssl/{inc,src}. Patch checker `research/check-patch-order.py` uses temporary upstream index; source fixtures/artifacts ignored under research. GDB mask registers to unsigned64, use function-entry manual-call return traps, discard manipulated guests. No QEMU guest intentionally left running.

## Session log and earlier handoffs (superseded by the active summary above)

### Prior 0019 transition notes (superseded)

- Goal: iOS 16 generation XNU on sweet. Always commit completed work, use gh/Actions for kernel builds, keep this handoff current. Temporary fastboot boot only; preserve Android/backups.
- **0019 build PASSED** Actions `38763072907` (4m5s), implementation `256d3f0`. Kernel `xnu/out-0019/kernel.development.sweet`, SHA256 `a27df7568f03fb541cf0e8024c0a594fa178a85054fcf9eba29158cbd4c5ecc0`; checksum verified. Log/source `research/run23.log` / `research/bt23`; all seven patched files and staged provider adaptations match local compile inputs. Prefer bt23 as the next baseline.
- **0019 pthread FIXED in QEMU**: 45s run `research/q0019` registers provider, passes mbinit, DLIL SUM16 checks and DLIL thread scheduling. Actual-kernel GDB checks `research/check-pthread19.gdb` / `.log` PASS: function/callback table identity, real _pthread_init returns, locks/global hash/cleanup threadcall/typed zones non-NULL, thread_selfid via actual syscall shim with output bounds, process hash init/delete through actual shims restores NULL. Guest stopped after tests; no fixture left running. GDB monitor quit prints expected remote disconnect after PASS.
- **Current next blocker:** QEMU0019 panic data abort FAR0x78 at `aes_encrypt_key128` PC`0xfffffe00079174e0`, called by `tcp_init` LR`0xfffffe000767c3a4`. Disassembly confirms `g_crypto_funcs == NULL`, loading ccaes_cbc_encrypt at+0x78. General crypto registration is still absent; DO NOT bypass TCP or supply fake crypto. Next integrate a genuine compatible crypto implementation/provider (AES first needed here, other digest/mode APIs also used). XNU contains SHA256/HMAC but no AES implementation; its corecrypto_aes.c is a dispatch wrapper. Full crypto table is in libkern/libkern/crypto/register_crypto.h.
- **0019 phone image prepared and verified**, user reports FASTBOOT+USB again; exactly one device/product sweet verified. `shim/out/shim-boot-0019.img`, 16,457,728 bytes, SHA256 `19429a57e486b856880df9e27327ed488e0139345311fdb0350974e72103a9a1`; unpacked ramdisk matches phone payload (`shim/out/check-0019`, `payload-0019.bin`, `sweet-0019.adt`, timer19). EntryPA0xb146b488; kernelendPA0xb2000000; boot_argsPA0xb2004000/top0xb2008000. Usual debug cmdline cpus=1/-noprogress. **Temporarily booted 2026-10-15 15:51:36 UTC**: send OKAY0.406s, boot OKAY0.134s, total0.546s, exit0 (`research/boot0019.log`). User asked for photo after45s. Await the photo; DO NOT reboot again before observation. Bootloader acceptance only; no0019 physical progress observed yet.
- **Hardware photo confirms 0018 progress** (`IMG_20261015_173951 (2).jpg`): real phone prints `SWEET CPU: boot CPU 0 registered, SGI1 verified, initialization complete`, enters BSD/MAC, reaches `mbinit: done`, then the same missing-pthread-function-table panic as QEMU at pthread_shims.c:318. CPU completion/interrupt delivery is now physically observed. The photo was received; no further phone boot performed yet.
- **Patch0019 committed/pushed `256d3f0`; Actions `38763072907` queued/running:** https://github.com/dipa-studio/ios-sweet/actions/runs/38763072907. Do not launch a duplicate. genuine Apple OSS libpthread-514.100.2 provider (immutable commit `a6c70ca0e544347a0377babf748f831577ec24f9`), paired with xnu-8796.141.3 by Apple's `distribution-macOS/macos-135/release.json` (`research/macos-135-release.json`). `0019-stage-libpthread.sh` fetches/stages it before patches; workflow now copies shell scripts too. SWEET-only wrappers compile all three real kernel sources, rename provider-side symbols, use kext header view and vm_fault_external, register the real function table at EARLY_BOOT SECOND. Existing pthread_init then runs the actual provider initialization. No pthread wait/syscall is bypassed. Source staging includes bounded explicit address casts/zero user addresses and panic-format fixes. SWEET kernel opaque ksyn storage enlarged from48 to56 bytes to contain this provider's trailing kwe_uth, with a provider size assertion. Local compile of three provider TUs plus pthread_shims/kern_fork passed; imports resolve and provider exports do not collide with existing kernel symbols. All19 patches apply and changed sources match (`research/patch0019-check.log`). Source sandbox `research/bt22/xnu`, originals `research/pre0019`, objects `research/pthread-objs`. Local TargetConditionals fixture only has target macros for syntax; CI stages the real macOS SDK header and is authoritative. Next Actions artifacts: out-0019 / bt23 / run23.log; run QEMU >=45 seconds. 0019 CI is pending; no 0019 QEMU run yet.
- **Latest kernel implementation `e7d9550`, patches0001-0018; CI `38760004398` PASSED (3m56s)**: https://github.com/dipa-studio/ios-sweet/actions/runs/38760004398. No build is pending. Kernel `xnu/out-0018/kernel.development.sweet`, SHA256 `b3c8d59acc88f93a2c836eb2527a05ed4fbaac7c580a2ea8c3b795137f4aadf1`; checksum verified. Source/log `research/bt22` / `research/run22.log` (baseline for patch0019; no nested .git). New driver/config sources match CI exactly.
- **CPU wait FIXED in QEMU**: SweetCPU uses legacy IOCPU, validates single boot CPU, ml_processor_register -> processor_start -> initCPU real SGI1 -> scheduler/IOKit completion -> ml_set_max_cpus. It does NOT force a flag or skip a wait. CPU APIs passed: Running CPU0, processor_array[0] association, SGI signalling enabled, name, unsupported secondary-start error (`research/check-cpu18.gdb` / `.log`, `research/q0018-api`). Single-core only; SMP and suspend unsupported. Two-CPU topology fails explicitly (`research/q0018-smp`).
- **Next blocker reproduced in 45s QEMU** (`research/q0018-long`, zero unknown glyphs): BSD initialization reaches MAC framework, network mcache and `mbinit: done`, then **`pthread kernel extension not loaded (function table is NULL). @pthread_shims.c:318`**. Do not bypass pthread_init: find/integrate the matching open-source libpthread kernel implementation and register its real function table. A 12s run `research/q0018` looked panic-free before the 30s IORTC wait elapsed; use >=45s or GDB checkpoints for the next iteration. No userland/root filesystem boot yet.
- **Phone 0018 TEMPORARILY BOOTED** 2026-10-15 **15:31:15 UTC**: exactly one FASTBOOT device verified product sweet; send OKAY0.400s, boot OKAY0.134s, total0.539s, exit0. Local log `research/boot0018.log`. This confirms bootloader acceptance only. User was asked for a photo; await it, DO NOT reboot the phone again before their observation. No flashing performed.
- Current hardware image `shim/out/shim-boot-0018.img`, **16,437,248 bytes**, SHA256 **`b7a23595d143a76c72c9fe2cfcc5d77a8f16987b5af1a2703bbffdfa6922908c`**. Phone ADT/payload `shim/out/sweet-0018.adt` / `shim/out/payload-0018.bin` (timer19), unpacked ramdisk exactly matches payload (`shim/out/check-0018`). EntryPA0xb146b488; kernelendPA0xb1ffc000; boot_argsPA0xb2000000/top0xb2004000. Command line `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`.
- QEMU payload/ADT `research/q0018.bin` / `research/q0018.adt` (timer27). Run `python3 tools/qemu-sweet.py research/q0018.bin research/NEW-OUT --secs 45 --kernel xnu/out-0018/kernel.development.sweet --fail-on-panic`; fresh ADT seed for a new payload. Output fb.png/fb.txt/regs.txt/qemu.log/result.json. Visible panic exit2; blank/incomplete decode exit3; no_panic_observed is snapshot-only, not successful boot. -noprogress prevents the graphical indicator corrupting console text. Qualcomm XPU/bootloader/panel and SMC PSCI still need physical validation.
- Patches0014-0017 fixed PRNG registration/direct SHA256, explicit unavailable trust-cache service with rejected loads/no matches, built-in SweetPlatformExpert, and timer PPI from ADT (phone19/default19, QEMU27). All their checks/artifacts are preserved in the history below. CURRENT SWEET has NO USE_APPLEARMSMP; do not assume gCPUIC/gAIC/gPMGR AppleARMSMP globals exist.
- Local single-file checker: tools/xnu-cc.py research/run22.log research/bt22 FILTER --per-file, output via XNU_CC_OBJDIR. Patch checker `research/check-patch-order.py` applies all18 via temporary index, matches sandbox sources. Sandbox for0018 `research/bt21/xnu`, originals `research/pre0018`, objects `research/cpu-objs`. First compiler issues were missing machine/atomic.h and nonexistent getNameSymbol; fixed and both TUs compiled successfully before CI. Fixtures/artifacts under research are local-only/ignored.
- GDB: mask int(register)&((1<<64)-1) for unsigned kernel pointers; use function-entry manual-call return traps, discard manipulated guests. No QEMU fixture is intentionally left running.

### Earlier active handoff snapshot (superseded)


- **0018 milestone:** Actions `38760004398` PASSED (3m56s), checksums passed, new CPU/build files byte-match CI tree. Kernel `xnu/out-0018/kernel.development.sweet`, SHA256 `b3c8d59acc88f93a2c836eb2527a05ed4fbaac7c580a2ea8c3b795137f4aadf1`; log/tree `research/run22.log` / `research/bt22`. QEMU `research/q0018` 12s: boot CPU registered, SGI1 verified, CPU initialization complete, **BSD initialization entered** (copyright, MAC framework, buffer headers), no panic/zero unknown glyphs. Direct CPU API checks PASS (`research/check-cpu18.gdb`, `.log`, `research/q0018-api`): CPU0 Running, processor matches processor_array[0], real SGI enabled, CPU name correct, secondary-start returns KERN_NOT_SUPPORTED. Two-CPU ADT correctly panics before registration (`research/q0018-smp`). Longer 45s run `research/q0018-long` still running; next BSD wait/fault not yet identified.
- **Prepared 0018 phone image:** `shim/out/shim-boot-0018.img`, 16,437,248 bytes, SHA256 `b7a23595d143a76c72c9fe2cfcc5d77a8f16987b5af1a2703bbffdfa6922908c`. Phone ADT/payload `shim/out/sweet-0018.adt` / `shim/out/payload-0018.bin`, usual debug args with cpus=1 and -noprogress. Unpacked ramdisk byte-compared (`shim/out/check-0018`). Entry PA remains 0xb146b488; kernel end PA 0xb1ffc000, boot_args 0xb2000000/top0xb2004000. User reports FASTBOOT+USB ready; read-only check found exactly one product sweet. NEXT: temporary fastboot boot of this verified image, record send/boot results, then await hardware photo without rebooting again.
- Patch 0018 committed/pushed **`e7d9550`**; Actions **`38760004398`** queued/running: https://github.com/dipa-studio/ios-sweet/actions/runs/38760004398. Do not launch a duplicate run.
- Active continuation: patch **0018** implemented in `iokit/Kernel/arm/SweetCPU.cpp` + arm64 source list + exact qcom,kryo470 personality. Keeps legacy IOCPU, accepts ONLY the single boot CPU, fills ml_processor_info from parsed topology with CPU object as cpu_id, calls ml_processor_register and processor_start. initCPU sends SGI1 via ICC_SGI1R_EL1 and waits (1-second deadline) for real cpu_signal_handler to clear SIGPdisabled. Only after successful startup calls ml_cpu_init_completed/cpusRunning and publishes completion/max CPUs. Secondary startup/suspend are explicitly unsupported. Local C++ compile passed for both TUs (`research/cpu-objs`), all imports resolve, object contains dsb ishst / ICC_SGI1R / isb; all18 patches apply in order and match sources. Sandbox `research/bt21/xnu`, originals `research/pre0018`; next CI artifacts should use `xnu/out-0018`, `research/bt22`, `research/run22.log`. User has the phone available; first run QEMU, then prepare/temporarily boot useful hardware progress.
- Goal: iOS 16 generation XNU on Redmi Note 10 Pro / sweet. User wants persistent progress, commits, kernel builds via `gh` Actions, and this handoff kept current across agent switches. Temporary `fastboot boot` only; preserve Android and backups.
- Latest kernel implementation: **`aa3f991`**, patches **0001-0017**. All four new Actions builds PASSED: 0014 `38748543058` (4m0s), 0015 `38749549779` (4m3s), 0016 `38750733996` (4m3s), 0017 **`38751507437` (4m7s)**. Latest: https://github.com/dipa-studio/ios-sweet/actions/runs/38751507437. No build is pending.
- **Current blocker: CPU initialization has no SWEET CPU driver.** QEMU registers SweetPlatformExpert, then kernel_bootstrap_thread waits in **kperf_init_early -> ml_wait_max_cpus**. Confirmed via actual-kernel GDB call stack (`research/locate-cpu-wait2.log` / `.symbols`) and normal-run `max_cpus_initialized == 2` (MAX_CPUS_WAIT). Do not force the flag or remove the wait. Next implement real CPU registration and completion using XNU's CPU/processor interfaces. CURRENT SWEET uses legacy IOCPU (`USE_APPLEARMSMP` is absent); enabling AppleARMSMP is a separate architectural change requiring GIC/PMGR services. No userland/root filesystem boot yet.
- Fixed this session: PC=0 unregistered PRNG callback (0014, built-in HMAC-SHA256 provider + direct entropy/write_random hashing); absent Image4/AMFI trust-cache service (0015, unavailable runtime, loads rejected and queries no-match); missing platform driver (0016, SweetPlatformExpert exact personality); incorrect QEMU timer IRQ (0017, validated ADT PPI property, phone default19/QEMU27).
- **Latest kernel** `xnu/out-0017/kernel.development.sweet`, SHA256 `055a80190ab998b4df9203f1102072dcc78faad1779a537a514e522b682b582f`. Buildtree/log **`research/bt21` / `research/run21.log`**; all nine changed C/C++/header/config files byte-match local checked sources. Checksums passed. Entry PA `0xb146b488`, kernel end PA `0xb1ff4000`. Preferred baseline for patch 0018: `research/bt21/xnu` (no nested .git).
- **QEMU verified**: `research/q0017-noprogress` ran **30 seconds**, no visible panic, **zero unknown glyphs**, IRQ exceptions returned normally (4 IRQs, tickless idle). It still waits for CPU completion, so this is NOT a completed boot. Earlier 15s run `research/q0017` captured 122 IRQs, timer value27, GICR_ISENABLER0 `0x08000002`, and CPU WAIT; graphical progress overlay corrupted 13 glyphs. Add **`-noprogress`** to keep the console readable. New runner classifies incomplete/blank decoding explicitly (exit3 with --fail-on-panic), visible panic exits2. Snapshot-only; use regs/GDB to diagnose stalls.
- Current QEMU payload/ADT: **`research/q0017-noprogress.bin` / `research/q0017.adt`**. Run: `python3 tools/qemu-sweet.py research/q0017-noprogress.bin research/NEW-OUT --secs 30 --kernel xnu/out-0017/kernel.development.sweet --fail-on-panic`. Generate fresh seed with mkadt for a new payload. QEMU virt models generic ARM execution, not Qualcomm XPU/bootloader/panel or the phone's SMC PSCI conduit.
- **Prepared phone image**: **`shim/out/shim-boot-0017.img`**, 16,416,768 bytes, SHA256 `51ff7fe30b4a6668c3452ffe1da922c5ac30cb8de60625c2a652587ecbd0ec92`. Phone ADT/payload `shim/out/sweet-0017.adt` / `shim/out/payload-0017.bin` (timer19). Unpacked ramdisk exactly matches payload (`shim/out/check-0017`). Command line **`debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`**. NOT sent to phone this session: known CPU-driver wait should be addressed in QEMU first. Last actual phone boot remains 0013; user's latest photo `IMG_20261015_160033.jpg` confirmed the old PRNG PC=0 panic.
- Direct QEMU/GDB API checks: PRNG 600-byte chunking, buffer bounds, changing output, zero-length reads/writes, user reseed, contended refresh, generator1 init/output PASS again on latest0017 (`research/check-prng17.gdb` / `.log`, guest `research/q0017-api`). Trust-cache unavailable-service/argument/output cases PASS on0015 (`research/check-trustcache.gdb` / `.log`). Platform registration + target/product normal/truncated/zero/null/bounds PASS on0016 (`research/check-platform.gdb`, `research/check-platform3.log`). Different platform ID correctly retains IOPanicPlatform fallback (`research/q0016-negative`). Timer PPI32 and size2 correctly panic (`research/q0017-badppi`, `research/q0017-badsize`); omitted property selects19 (`research/q0017-default`). These are API/bring-up checks, not crypto certification or SMP scheduling validation.
- Local checker **`research/check-patch-order.py`** verifies all17 patches and changed source equality using a temporary upstream git index. Fixtures/logs/artifacts under research are local-only and ignored. For GDB unsigned kernel pointers, mask `int(register_value) & ((1<<64)-1)`; x30/x29 may be rendered signed. Stop at a function entry for manual-call return traps, and discard each manipulated guest after API tests. All fixture QEMU guests have been stopped.


- User wants persistent progress toward iOS 16, commits for completed changes, builds through `gh` / GitHub Actions.
- Keep this file current at every milestone so another agent can resume immediately, including when usage limits interrupt a session.
- Patch 0017 committed/pushed `aa3f991`, Actions `38751507437` running: https://github.com/dipa-studio/ios-sweet/actions/runs/38751507437. Next artifacts: xnu/out-0017, research/bt21, research/run21.log. Do not duplicate.
- Patch 0016 kernel downloaded/checksum verified: SHA256 `d06336c54baa06e0df6561a8bd7df98a9b9f7502c9381c62d1a44c045cd1ce46`, `xnu/out-0016/kernel.development.sweet`; buildtree/log `research/bt20` / `research/run20.log`. QEMU `research/q0016` (10s) prints platform expert registered, zero unknown glyphs, no panic observed BUT stalls (timer mapping still wrong until 0017). Direct actual-kernel GDB tests passed for registered instance and target/product names, including maxLength=1/0 and NULL, sentinels intact (`research/check-platform.gdb`, `research/check-platform3.log`, `research/q0016-api3`). First two fixture attempts used premature/wrong return breakpoints; discarded, corrected fixture uses start-return observation then a function-entry return trap. No phone boot yet.
- Patch 0016 CI `38750733996` PASSED (4m3s); artifacts not yet downloaded/booted. Patch 0017 prepared to fix QEMU timer fidelity BEFORE interpreting future no-panic/stall runs: actual `qemu-system-aarch64 -M virt,gic-version=3,dumpdtb=research/qemu-virt.dtb ...` timer property has virtual PPI 11 => INTID 27, while phone uses INTID 19. Kernel formerly hardcoded 19. New optional /arm-io/gic virtual-timer-intid property selects the PPI (validate exact u32 and 16..31); missing property retains phone default 19. One RO-late global drives GIC enable and sleh_irq dispatch. tools/mkadt.py emits phone19/QEMU27. Both C TUs compile (`research/timer-objs`), ADT serialize/parse checks confirm values/addresses, all 17 patches apply and match. Sandbox `research/bt19/xnu`, originals `research/pre0017`; initial local sleh compile failed due read-only exported header not updated, fixed export and BOTH recompiled successfully. CI exports normally.
- Architecture correction for next agent: CURRENT SWEET board_config does NOT define USE_APPLEARMSMP; it compiles the legacy IOCPU path, not cpu_boot_thread/IOPMGR AppleARMSMP. Existing roadmap mentions AppleARMSMP as a future approach. Do not look for gCPUIC/gAIC/gPMGR globals in the current kernel: they are absent. Determine the actual CPU-init wait after platform registration before choosing the next driver architecture.
- Patch 0016 committed/pushed as `0dcdf5c`; Actions `38750733996` running: https://github.com/dipa-studio/ios-sweet/actions/runs/38750733996. Next artifacts: `xnu/out-0016`, `research/bt20`, `research/run20.log`.
- Patch 0016 implemented: new `iokit/Kernel/arm/SweetPlatformExpert.cpp`, arm64 source list, built-in personality in KernelConfigTables.cpp guarded by ARM64_BOARD_CONFIG_SWEET. Matches only xiaomi,sweet at score 10000, keeps IOPanicPlatform fallback for other hardware. Uses IODTPlatformExpert base initialization/power domain and createNubs CPU logical-ID annotation; overrides top-level publishing because base requires nonexistent Apple NVRAM /options. Publishes real CPU/top-level nodes, provides bounded target/product names, and registers the platform service. GIC/PMGR and arm-io child-bus drivers remain separate work. Both C++ TUs compile (`research/platform-objs`), all imports resolve against 0015/own objects, all 16 patches apply and sources match. Sandbox `research/bt19/xnu`; originals `research/pre0016`. NEXT: full Actions/QEMU; inspect CPU boot waits after the platform registers, do not equate absence of panic with successful boot.
- Patch 0015 CI `38749549779` PASSED (4m3s), checksum verified. Kernel `xnu/out-0015/kernel.development.sweet`, SHA256 `ca1b424a596c7058550ad1659080a333e7643270f019656401d80bf2b876645f`; buildtree/log `research/bt19` / `research/run19.log`. QEMU `research/q0015` (10s, zero unknown glyphs) passes trust-cache handling and machine lockdown, then panics `Unable to find driver for this platform: "xiaomi,sweet" @IOPlatformExpert.cpp:2319` (IOPanicPlatform fallback). Next concrete work: add a built-in SWEET IODTPlatformExpert personality/class; keep the fallback for mismatched platforms. No phone boot yet.
- Direct trust-cache API checks PASSED in the actual 0015 kernel under QEMU/GDB (`research/check-trustcache.gdb`, `research/check-trustcache.log`, `research/q0015-api`): runtime pointers NULL, hash/UUID queries return NOT_FOUND, typed/untyped/legacy loads return NOT_SUPPORTED, capabilities outputs zero and bounds preserved, invalid-argument cases still reject. Second PRNG check also verifies contended refresh returns immediately (`research/check-prng2.log`, `research/q0014-api2`).
- Patch 0015 committed/pushed `8f851d4`, Actions run `38749549779` running: https://github.com/dipa-studio/ios-sweet/actions/runs/38749549779. Do not duplicate.
- Direct PRNG API checks passed in the REAL 0014 kernel under QEMU/GDB, stopped before trust-cache init (`research/check-prng.gdb`, log `research/check-prng.log`, guest `research/q0014-api`). Invoked read_random for 600 bytes (chunking and buffer sentinel intact), repeated output differed, zero-length read/write succeeded, write_random(64-byte input) succeeded, secondary generator 1 initialized and generated distinct output. QEMU log has no exceptions during these checks; guest was discarded after the tests. This tests API behavior, not a cryptographic certification or SMP scheduling.
- Patch 0015 implemented in `bsd/kern/kern_trustcache.c`: SWEET with missing Image4/AMFI marks both runtime pointers NULL and logs service unavailability. Existing static loader handles NULL. Public load APIs return KERN_NOT_SUPPORTED; hash/UUID queries return KERN_NOT_FOUND; capabilities outputs are zero with KERN_NOT_SUPPORTED. Invalid-input checks remain, and Apple paths/available-provider initialization retain existing behavior. No trust is granted. Local arm64 compile passed (`research/trustcache-objs`), all 15 patches apply and sources match. Sandbox `research/bt18/xnu`, baseline `research/pre0015`. Next: Actions/QEMU and direct unavailable-service API checks using GDB.
- Patch 0014 CI `38748543058` PASSED (4m0s), artifact checksum passed. Kernel `xnu/out-0014/kernel.development.sweet`, SHA256 `741de20c851755d333759d7e668346f3edb4f325efac4cc7c142d80d1f5ff75c`; buildtree/log `research/bt18` / `research/run18.log`. QEMU run `research/q0014` (10s, zero unknown glyphs) prints `SWEET PRNG: HMAC-SHA256 registered`, passes commpage initialization, loads vnguard policy, THEN panics `image4 interface not available @kern_trustcache.c:253`. PC=0 fault FIXED IN QEMU. No new phone boot performed.
- Next work: SWEET currently has neither AppleImage4 nor AMFI. `trust_cache_runtime_init` unconditionally requires both; unlike BCM2837, SWEET enters this startup path. Investigate an explicitly unavailable trust-cache runtime with rejected loads/no query matches while providers are absent; preserve all Apple-platform checks. Merely skipping the startup call would leave later AMFI/IMG4 dereferences unsafe. Existing load_static_trust_cache already handles trust_cache_rt == NULL.
- QEMU runner now supports `--kernel MATCHING_KERNEL --fail-on-panic`: runtime font extraction from the payload produces exact `fb.txt`, plus `result.json`; a visible panic returns 2. Baseline 0013 re-run `research/q0013-text` detects the same NULL callback panic with zero unknown glyphs. Synthetic glyph roundtrip (including literal `?`) and invalid-VA rejection passed. Screen rows remain circular, not a full log; `no_panic_observed` does not prove successful boot. README has the invocation.
- Patch 0014 committed/pushed as `be61f99`; Actions run `38748543058` is running: https://github.com/dipa-studio/ios-sweet/actions/runs/38748543058. Do not start a duplicate build.
- 2026-10-15 active: hardware photo `IMG_20261015_160033.jpg` confirms the same PC=0 instruction-fetch abort as QEMU (LR `0xfffffe0007443fe4` = read_random). Independently reproduced with kernel 0013 in `research/q0013` (8-second run); prior allocator fix works. Latest tooling commit reviewed: `8d66d2d`.
- Patch 0014 implemented: registers a built-in HMAC-SHA256 DRBG provider at EARLY_BOOT/FIRST, before commpage creation. A shared mutex serializes output/reseed across CPUs (correctness first; no per-CPU scaling yet), initgen validates CPU identities, refresh uses try-lock and the existing entropy filter/health tests. SWEET entropy accumulation and write_random now use the built-in SHA256 directly; no incomplete g_crypto_funcs table is registered. The existing bootloader-seed requirement remains enforced.
- Local validation: both PRNG translation units compile to arm64 objects in `research/prng-objs`; no SHA256 wrapper imports remain. All 14 patches apply in CI order and resulting PRNG sources match local inputs. Sandbox `research/bt17/xnu`, originals `research/pre0014`, checker `research/check-patch-order.py`. NEXT: Actions kernel build, download to `xnu/out-0014`, run the QEMU payload before requesting another phone boot. Baseline QEMU ADT/payload are `research/q0013.adt` / `research/q0013.bin`.
- 2026-10-15 08:15 QEMU EMULATION WORKS (`tools/qemu-sweet.py`, see "QEMU emulation" below). Patch 0013 VERIFIED in QEMU: boot passes kmem_crypto_init and ulock_initialize. NEXT BLOCKER (reproduced in QEMU, expected on hardware too): `pmap_create_commpages -> random() -> RandomULong -> read_random -> prng_funcs.refresh == NULL` (instruction fetch abort at pc 0, lr read_random+0x34). Nobody calls `register_and_init_prng` (closed corecrypto kext does it on Apple). Fix = patch 0014: SWEET-registered cckprng_funcs provider (osfmk/prng/prng_random.c); note random_cpu_init also panics while !prng_ready. The 07:26 hardware boot of 0013 will most likely show this same panic.
- Previous hardware boot: patch 0013 (`a3a46e2`) CI `38686345689` PASSED (3m44s), image `shim/out/shim-boot-0013.img` was temporarily booted on 2026-10-15 at 05:26 UTC: send OKAY (0.407s), boot OKAY (0.134s), total 0.546s. Superseded by the hardware/QEMU PC=0 observation and patch 0014 work above.
- Latest kernel implementation commit: `8f851d4`. Latest successful kernel CI: `38749549779` (patch 0015), https://github.com/dipa-studio/ios-sweet/actions/runs/38749549779.
- CURRENT image: `shim/out/shim-boot-0013.img`, 16,412,672 bytes, SHA256 `110d1c46aee4b60253db24b6535e9781c4cf0fd25ca2a70e9016cf81378cea25`. Kernel `xnu/out-0013/kernel.development.sweet`, SHA256 `f0b1d375995316c550ce7014ff234d8271e9b9ac2857795ceff41b76ba2cd740`, plain arm64. CI log confirms 0013 applied; checksums passed. Entry PA `0xb146b488`, kernel end PA `0xb1ff4000`.
- Current log/buildtree: `research/run17.log`, `research/bt17` (extracted, no nested .git; preferred baseline for patch 0014). Payload/ADT: `shim/out/payload-0013.bin`, `shim/out/sweet-0013.adt` (includes /defaults). Unpacked ramdisk byte-compared with payload in `shim/out/check-0013`.
- Patch-0012 original image: `shim/out/shim-boot-0012.img`, 16,412,672 bytes, SHA256 `cf4b8ec4a65a51888d71c17d09cd0831d6b761b90e2531fdb8e575c32f4fd24a`. Kernel `xnu/out-0012/kernel.development.sweet`, SHA256 `69b78f49f6459cc63a0af44e7cf73c1779ef72130ef72b12ae86c88183ffc742`; checksums passed and sweet_early_relocate symbol present. Entry PA remains `0xb146b488`, kernel end PA `0xb1ff4000`.
- Patch-0012 log/tree: `research/run16.log`, `research/bt16` (extracted, no nested .git; preferred baseline for next patch). CI log confirms 0012 applied. Payload `shim/out/payload-0012.bin`, ADT `shim/out/sweet-0012.adt`; packed ramdisk byte-compared with payload in `shim/out/check-0012`.
- Active payload command line: `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam`.
- Latest observed photo: `/home/dipa/Downloads/IMG_20261015_071346.jpg` (local only). Stages 9 (kernel framebuffer VA), 10 (TTBR0 off/TLB flush), 11 (physmap table pointers) and 12 (calling pmap_bootstrap) all visible. Persistent diagnostics are VERIFIED ON HARDWARE.
- pmap.c:1987 is the assert after SecureDTLookupEntry(NULL, "/defaults", &entry). The pmap-max-asids property itself is optional; an empty /defaults uses XNU's MAX_ASIDS. Do not bypass the assertion or guess an ASID limit.
- Previous payload-only fix image: `shim/out/shim-boot-0012-defaults.img`, SHA256 `3ff61a268853c6ea7cbf284833f1346a1d791980ca366b6e1a215a86e040512b` (16,412,672 bytes). Same kernel/CI as 0012; ADT 2516 bytes (`shim/out/sweet-0012-defaults.adt`), root /defaults present with no ASID override. Payload `shim/out/payload-0012-defaults.bin`; unpacked ramdisk exactly matches payload (`shim/out/check-0012-defaults`). This boot reached the allocator crypto NULL-pointer fault below.
- Latest hardware photo: `/home/dipa/Downloads/IMG_20261015_071608.jpg` (local only). Normal serial framebuffer console works. VM bootstrap/zone initialization, logging, scheduler, IPC, KDP and ulock_initialize print before the kmem_crypto_init data abort. gPanicBase warnings are expected because PLATFORM_PANIC_LOG_DISABLED is configured, and are not the faulting call.
- Faulting instruction: `ldr x0, [x8, #0x150]` in crypto_random_kmem_ctx_size; x8 = NULL g_crypto_funcs. Source: libkern/crypto/corecrypto_rand.c and osfmk/vm/vm_kern.c:2448. rand.h explicitly permits NON-cryptographic kmem RNGs, but requires no locking in generation and context size <=256. Do not substitute read_random here: the global PRNG provider is also unregistered and kmem generation must remain lock-free. early_random may seed contexts during single-CPU bootstrap; it uses the built-in HMAC-SHA256 DRBG with the host-generated ADT seed.
- Patch 0013 keeps the replacement entirely private to vm_kern.c: SplitMix64 state is 8 bytes per CPU/sizeclass, initialized using early_random. Uniform selection uses rejection sampling to avoid modulo bias. Other platforms retain the original corecrypto calls; SWEET's generic crypto APIs/registration remain untouched. Reference: https://prng.di.unimi.it/splitmix64.c (Sebastiano Vigna, public domain).
- Validation: vm_kern.c compiles to arm64 (`research/kmem-rng-objs`, using `research/run16.log` + `research/bt16`). Undefined symbols include early_random and NO crypto_random_* references. All 13 patches apply in CI order and match the checked source. Original saved as `research/vm_kern.pre0013.c`.
- RNG host checks: extracted actual new helper in `research/kmem-rng-check.c`; 16,384 outputs match the author's downloaded reference (`research/splitmix64-reference.c`), 147,456 bounded outputs satisfy their limits (including 1 and UINT64_MAX), and a forced rejection advances correctly. Full kernel crypto services and the registered kernel PRNG provider remain future work; this patch only supplies the allocator RNG contract.
- Patch-0011 artifacts: kernel `xnu/out-0011/kernel.development.sweet`, log `research/run15.log`, extracted buildtree `research/bt15` (no nested .git). CI log confirms patch 0011 applied; artifact checksums passed. Kernel is plain arm64, entry VA `0xfffffe000746b488` -> PA `0xb146b488`, kernel end PA still `0xb1ff4000`.
- Patch-0011 image: 16,412,672 bytes, SHA256 `29ad5cbfc752473de4af2c471a24a8b34f92da4bff5afec65c614b90cd3ad53a`. Kernel SHA256 `8ac3a956894b09f7bd0d890de8c5de38c65513287feb1e1bcd12db8ca772ee5c`. Payload/ADT in `shim/out/payload-0011.bin`, `shim/out/sweet-0011.adt`. Header unpacked/checked in `shim/out/check-0011`.
- First patch-0011 attempt timed out waiting for FASTBOOT; superseded by the successful send/boot recorded above. Do not repeat the boot before the user reports the current screen.
- Patch-0011 photo: `/home/dipa/Downloads/IMG_20261015_070218.jpg` (local only). Visible stages 1-8 and old red shim text; entry PA B146B488, boot args PA B1FF8000 / top B1FFC000. No evidence yet locating execution after stage 8.
- Patch-0012 sandbox: `research/bt15/xnu` (NO nested .git). Proposed permanent debug VA: VM_MIN_KERNEL_ADDRESS + ARM_TT_L2_SIZE, in the reserved gap below gVirtBase and above low globals; map the same PA framebuffer as Normal-NC in the final TTBR1 before arm_vm_physmap_init changes phystokv(). Keep the early panic sink until normal kprintf startup.
- Patch 0012 validation: all 4 changed C translation units compiled to arm64 objects in `research/post-ttbr0-objs`; internal header export added to osfmk/arm64/Makefile and recreated locally in EXPORT_HDRS for pe_serial.c. All 12 patches apply in CI order and match all 6 edited files. Baselines are saved under `research/pre0012/`.
- Actual mapping-helper host model (`research/early-map-check.c`, barrier stubbed only for host compilation) confirms: VA `0xfffffe0002000000`, L1 index 2016, L2 index 1; descriptor `0x006000009c000605` = framebuffer PA, Normal-NC, outer-shareable, EL1 RW, PXN+UXN. All other L2 entries preserved. The gap is excluded by ARM_LARGE_MEMORY's pmap_virtual_region(0).
- Next boot command line MUST add `-enable_kprintf_spam`: DEVELOPMENT disables kprintf_output by default even when DB_KPRT is set (`pexpert/arm/pe_kprintf.c`). Planned command line: `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam`.

### Patch 0012 screen legend (after original stages 1-8)
- 9: kernel framebuffer VA live; 10: TTBR0 off / TLB flushed; 11: physmap pointers rebound.
- 12: calling pmap_bootstrap; 13: pmap_bootstrap returned; 14: early I/O page tables ready; 15: arm_vm_init returned.
- 16: calling serial_init; 17: fbcon config read / mapping; 18: fbcon mapping returned; 19: serial_init returned; 20: kprintf startup complete.
- Normal serial initialization clears the screen, so earlier stages may disappear before 19. If serial exists, early console disables after 20; otherwise early panic output stays enabled.
- Local source sandbox: `research/bt13/xnu` (git baseline `623b060`, patches 0001-0008 already in baseline; uncommitted export edits correspond to patch 0009). Preserve those edits when producing patch 0010.
- Previous compile log/tree: `research/run13.log`, `research/bt13`; previous kernel: `xnu/out/kernel.development.sweet`. New successful log/tree: `research/run14.log`, `research/bt14`; new kernel: `xnu/out-0010/kernel.development.sweet`.
- Current device access: patch-0012 image was temporarily started from FASTBOOT; no adb connection is expected. Never flash partitions for bring-up; use `fastboot boot` with the shim image.
- Patch `0010` lives in `xnu/patches/0010-sweet-early-framebuffer-debug.patch`. Its exact compiled sources are under `research/bt13/xnu`; generated objects are in `research/early-objs`.
- Local checks passed: all 5 changed/new translation units compiled to arm64 Mach-O objects; new console only imports `_doprnt` and `iso_font` (both exist in the previous kernel). All 10 patches applied to a temporary upstream git index in CI order, and all 7 resulting changed source files matched the local compile inputs.
- Reproduce changed-file compilation: `XNU_CC_OBJDIR="$PWD/research/early-objs" python3 tools/xnu-cc.py research/run13.log research/bt13 arm_init.c arm_vm_init.c kern/debug.c arm64/start.s osfmk/arm64/sweet_early.c --per-file` (create the output directory first). The helper now accepts explicit new source paths absent from the old artifact's Makefiles and rejects empty selections.
- Device command result: `adb reboot bootloader`, then `timeout 30s fastboot boot shim/out/shim-boot-0010.img`: send OKAY (16028 KB), boot OKAY, total 0.541s. This confirms bootloader acceptance only, not XNU progress.
- The successful boot above was on 2026-10-14. On 2026-10-15, `timeout 45s fastboot boot ...` timed out waiting for a device; no image was sent. Boot image SHA256 rechecked and unchanged. No new build is needed to repeat the trial.
- Earlier retry: `timeout 90s fastboot boot shim/out/shim-boot-0010.img` timed out (exit 124). This is superseded by the successful 2026-10-15 repeat boot recorded above; do not repeat it until the user reports the screen.
- User observation confirms MMU-on C entry, platform expert, CPU topology/bootstrap, startup bootstrap and cpu_init all complete. Failure is within arm_vm_physmap_init (non-XNU_MONITOR branch), before stage 8 / TTBR0 teardown. Old red shim text remains behind the early console; this is expected because only written rows are cleared.
- New edit/compile sandbox is `research/bt14/xnu` (extracted artifact, NO nested .git; `git diff` there would act on the parent project). Use a saved baseline file / generated unified diff, or explicitly initialize a local baseline before editing. `research/bt13/xnu` does have its own baseline git repo.
- Exact user-reported panic: `arm_vm_init.c:1606 Assertion failed: (temp_ptov_table[ptov_index - 1].va + temp_ptov_table[ptov_index - 1].len) <= physmap_end`.
- Root cause: MacOSX build sets `ARM_LARGE_MEMORY=1`; `XNU_MONITOR` is off. Block alignment in arm_vm_physmap_slide can add gaps, but the non-PPL large-memory physmap_end omitted the padding already present in the small-memory branch. Patch 0011 reserves PTOV_TABLE_SIZE*ARM_TT_TWIG_SIZE (8*32MB) in both the aperture bound and its L1 allocation; monitor/PPL builds retain zero padding. The assertion is preserved.
- Validation: `arm_vm_init.c` compiled to an arm64 object using `research/run14.log` + `research/bt14` (object in `research/physmap-objs`). All 11 patches apply in CI order and produce exactly that source. Host harness `research/physmap-check.c` extracts the real XNU slide function with page-table-write stubs: all 65,536 page-aligned slides within 1GB checked against the current kernel memory layout; old bound fails 65,504 cases, padded bound fails zero; worst overrun 0x1ffc000 bytes. Baseline source saved as `research/arm_vm_init.pre0011.c`.
- CI: https://github.com/dipa-studio/ios-sweet/actions/runs/38638702083 (success; artifacts and full log downloaded).
- New image: `shim/out/shim-boot-0010.img` (16,412,672 bytes, SHA256 `ed2c270e0081bad5ff517be415f9bfe8805463aea7866732203fa97ac737e64e`). Previous image preserved as `shim/out/shim-boot-pre0010.img`.
- New kernel SHA256: `3ee05270cc291c49589a101678f904b1b69cb2f2575e05398bce8a4e052f409a`. Artifact checksums passed; arm64 (not arm64e), early-console symbols present. Payload entry VA `0xfffffe000746a488` -> PA `0xb146a488`; kernel end PA `0xb1ff4000`. Command line remains `debug=0xc serial=3 cpus=1 keepsyms=1`.

### Patch 0010 screen legend
- Bottom-left white 64x32 tile: assembly entered `start_first_cpu`, before page tables/MMU.
- Text `SWEET EARLY 1`: entered `arm_init` with MMU on; 2: platform expert done; 3: CPU topology done; 4: CPU bootstrap done; 5: startup bootstrap done; 6: CPU init done; 7: entering `arm_vm_init`; 8: leaving bootstrap TTBR0.
- `SWEET EARLY PANIC:` prints a copy of panic arguments before normal panic handling needs per-CPU/thread state.
- In patches 0010/0011 the console disabled before TTBR0 invalidation; patch 0012 replaces that with a persistent kernel VA alias and diagnostics through normal serial/kprintf startup (see its legend above).
- Screen contents require a physical observation from the user: adb cannot capture a framebuffer after Android has been replaced by a bare-metal kernel.

## QEMU emulation (2026-10-15)
- `tools/mkadt.py OUT.adt --qemu` = same ADT with QEMU virt GICD 0x08000000 / GICR 0x080a0000 / CNTFRQ 62.5 MHz.
- `tools/qemu-sweet.py PAYLOAD OUTDIR [--secs N] [--hmp "x /8gx ADDR"] [--gdb]`: host-side copy of shim/loader.c
  (segments + ADT + boot_args at their PAs, 6-instruction stub sets x0 and jumps), `-M virt,gic-version=3 -cpu cortex-a76`
  (same ID_AA64MMFR0 as Kryo 470), 4G RAM so 0x9c000000 fb and 0xb0000000 kernel are plain RAM.
  Outputs `fb.png` (the screen), `regs.txt`, `qemu.log` (exceptions with ESR/FAR/ELR). `--gdb` halts with a stub on :1234
  (system `gdb` + `set architecture aarch64`, `hbreak *VA` works with the MMU on).
- Not emulated: Qualcomm XPUs, ABL, real panel, PSCI conduit (QEMU virt uses hvc). Hardware still decides those.
- Example: `python3 tools/mkadt.py /tmp/q.adt --qemu && python3 tools/mkpayload.py xnu/out-0013/kernel.development.sweet /tmp/q.adt /tmp/pq.bin --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam' && python3 tools/qemu-sweet.py /tmp/pq.bin /tmp/q`

## Layout
- `backup/`  partition dumps + full sdb..sdf LUNs, `SHA256SUMS` (all verified on-device == local)
- `dtb/`     live FDT (from OrangeFox), PixelOS boot.img dtb, dtbo, dts versions
- `shim/`    bare-metal boot shim (`./build.sh` -> `out/shim-boot.img`)
- `research/` mainline sm7150 dts, XNU pe_fiq.c etc, PocketDarwin patches
- `tools/unpack_bootv2.py`

## Device access
- No root in PixelOS 17 (user build, adb root disabled). Root = `fastboot boot recovery/recovery.img` (OrangeFox R12.0_2, temp boot, not flashed).
- `fastboot boot` works for stock boot.img, OrangeFox, and our shim.
- Shim resets itself via PSCI SYSTEM_RESET; IMEM restart_reason 0x77665500 is seen
  (bootreason=bootloader) but ABL still boots Android, so it does not stop in fastboot.

## Hardware facts (live DT + shim measurements)
- Framebuffer (ABL cont splash): 0x9c000000, 1080x2400, stride 4320, a8r8g8b8, panel is DSC *video* mode (no kick needed).
- RAM: 0x80000000+2G, 0x100000000+0xfcc00000. Live reserved-memory = PixelOS base dtb + sweet dtbo fixups.
- GICv3: GICD 0x17a00000, GICR 0x17a60000 (stride 0x20000, 8 PEs). GICD_TYPER 0x007B041D: SecurityExtn=1 (DS=0).
  ABL leaves GICD_CTLR = 0x10 (ARE_NS on, groups off). Writing 0x13 reads back 0x12: EnableGrp1A (bit1) is the one that matters.
- GIC Group 1 VERIFIED (shim 2c): vtimer INTID 19 = 30 IRQs/300ms, ptimer INTID 18 = 30, SGI 1 to self = 10/10.
  ICC_SRE=1 already, ICC_CTLR 0x8440, priority/enable writes stick. GICR_IGROUPR0 and GICD_IGROUPRn read 0 from NS
  even though Group 1 delivery works (RAZ in NS view) - do not use them as a health check.
  INTID 28 shows pending constantly (unknown PPI 12).
- Timer 19.2 MHz. Qualcomm PPI numbering: secure-phys/phys/virt/hyp = PPI 1/2/3/0 -> vtimer INTID 19, ptimer 18 (NOT 27/30).
- PSCI 1.1 via SMC, SMCCC 1.1. CPU_ON ok; SYSTEM_SUSPEND and SYSTEM_RESET2 unsupported.
- SMP: CPU_ON works for all 7 secondaries (MPIDR 0x81000n00).
- Entry EL1, MMU off, x0 = DTB (magic ok). ID_AA64MMFR0 = ...101122: 16K granule YES, 4K YES.
- No serial console: debug UART SE is in SPI mode on sweet. Screen is the only debug channel.

## XNU implications
- XNU GICv3 path (pexpert/arm/pe_fiq.c, VMAPPLE) puts the timer (PPI 27) in Group 0 = FIQ. With SecurityExtn=1,
  Group 0 is secure -> impossible from NS EL1. Need: Group 1 IRQ, ICC_IGRPEN1, INTID 19, and the timer handled in the IRQ path.
- XNU VMAPPLE PSCI uses `hvc`; sweet needs `smc`.
- PocketDarwin NonAppleGenericCpu.patch only swaps -mcpu=apple-h7 for -march=armv8-a.

## Milestone 3 (2026-10-14): 16K MMU verified
- ABL loads the Image at 0x80080000 (base 0x80000000 + 0x80000) regardless of text_offset=0.
- 16K granule, T0SZ=28 (L2 start, 32MB blocks), MAIR 0x44ff00, TCR 0x1409CB51C, PARange=2 (40-bit PA).
- Only own image pages WB (Qualcomm XPUs: never map carve-outs cacheable); fb Normal-NC; rest Device.
- AT S1E1R checks all as expected; unmapped -> translation fault L2.
- Fill fb: 110 ms (MMU off) -> 3.5 ms (NC). Memory loop 70 ms -> 0.7 ms. vtimer + SGI IRQs still fine with MMU on.

## XNU loader design notes (xnu-8796)
- Entry: `_start` -> `start_first_cpu`, x0 = boot_args (PA), MMU off, EL1. boot_args: Revision/Version 2,
  virtBase/physBase/memSize/topOfKernelData, Boot_Video (fb 0x9c000000, rowBytes 4320, 1080x2400, depth 32),
  deviceTreeP/Length (ADT), CommandLine[608], bootFlags, memSizeActual.
- start.s maps [kernel mach header .. physBase+memSize) with cacheable BLOCKS. On Qualcomm every XPU carve-out
  must therefore lie below the kernel: use physBase = 0xb0000000 (above ramdump_fb 0xaf000000+16M,
  cdsp_sec, qseecom), end before rmtfs 0xfde01000 -> memSize ~0x4d000000 for bring-up.
- Base ADT: iPhone 8 d20ap DeviceTree from iOS 16.7.16 IPSW (tools/remotezip.py + tools/adt.py; LZFSE payload).
  Template values are empty: the loader must fill chosen/*, memory-map, cpu*/reg etc. like iBoot.
- XNU build: GitHub Actions (dipa-studio/ios-sweet, xnu.yml) via blacktop/darwin-xnu-build, MACOS_VERSION=13.5.
  New-clang fixes in xnu/patches; Xcode 16 iig is incompatible (IORPC.kernelContent) -> macos-14 runner, oldest Xcode.

## Kernel architecture plan (SWEET machine config)
- First stock build (VMAPPLE) is arm64e (PAC). Kryo 470 = ARMv8.2, no PAC -> SWEET must build plain arm64
  (HAS_APPLE_PAC is only defined for __arm64e__, so arm64 drops PAC automatically).
- Template: VMAPPLE (16K pages, GICv3 code in pe_fiq.c) minus APPLEVIRTUALPLATFORM hypercalls/paravirt PAC,
  plus BCM2837 (generic ARM: no APPLE_ARM64_ARCH_FAMILY Apple sysregs). Do not link the KDK lib<cfg>.os.*.a.
- Timer: XNU expects it on FIQ (sleh_fiq -> rtclock_intr). SWEET: GIC Group 1, so sleh_irq must ack ICC_IAR1,
  route INTID 19 to the same timer path, SGIs to cpu_signal_handler, EOI via ICC_EOIR1.
- SMP/interrupts: open-source AppleARMSMP (USE_APPLEARMSMP) needs an IOInterruptController (AIC role) and an
  IOPMGR (CPU power -> PSCI CPU_ON via SMC). Plan: built-in IOKit classes (SweetGIC, SweetPMGR, platform
  expert) compiled into the kernel and matched via iokit/KernelConfigTables.cpp -> no closed kexts needed.
- Debug: xnu patch 0003 sweet-fbcon = kprintf drawn on the framebuffer (ADT node "sweet-fbcon").
- ADT /arm-io ranges must not map to parent 0 (pe_arm_get_soc_base_phys()==0 disables serial): use parent 0x1000000.

## Status 2026-10-14 late: first XNU boot attempt
- SWEET kernel builds (CI run 38635343732, patches 0001-0009). Verified offline: arm64, no PAC, no >v8.2 code,
  70300 classic relocs all in range (slide 0 = no loader work), entry = __start.
- Boot: shim loader worked (initrd 0x846F0000-0x855FE3E0, BOOTARG 0xB1FF8000, JUMP 0xB146A488) but screen stayed
  red -> xnu died/hung before serial_init (fbcon). kprintf is a no-op before STARTUP_SUB_KPRINTF.
- Historical next-step plan (patch 0010, now implemented and built; see active handoff above): early fb debug channel
  1. start.s start_first_cpu (after mov x20,x0 / mov x21,#0): PA marker band (MMU off, direct store to 0x9c000000).
  2. start.s after both create_bootstrap_mapping calls: add ONE block entry to the existing V=P L2 table
     (x25 + 2*PGBYTES; do NOT call create_bootstrap_mapping again: fb and RAM share L1 entry 0, it would replace
     the L2 table). Entry = TYPE_BLOCK|VALID|SH(OUTER)|ATTRINDX(CACHE_ATTRINDX_WRITECOMB=1)|AF|PNX|NX|0x9c000000,
     index = (va & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT.
  3. new osfmk/arm64/sweet_early.c (+files.arm64 entry): sweet_early_mark(n) colored bands at screen bottom and
     sweet_early_putc using iso_font via VA=PA while the bootstrap TTBR0 is live; disable before
     arm_vm_init's set_mmu_ttb(invalid_ttep) (arm_vm_init.c:2148).
  4. markers in arm_init after PE_init_platform, ml_parse_cpu_topology, cpu_bootstrap, kernel_startup_bootstrap,
     cpu_init, before arm_vm_init.
  5. panic hook at top of panic_trap_to_debugger: va_copy + _doprnt(fmt, &copy, sweet_early_putc, 16).
  Verify with tools/xnu-cc.py (compile+symbols) and patch-order simulation before the single CI run.


## REDFIN stopped at user request — 2026-10-21

User requested stopping and will disconnect the phone. No further device
operations are scheduled. Last completed kernel build: Cortex-A55 with PAN
restored, SHA256 ff99416071826215cddcb5121ad464aa8cee30bc1603478985f98b131a8b49da.
Disassembly verifies PAN disable/restore around copyinstr. Image is
ports/redfin/out/pan/redfin-xnu.img; an automatic test boot was accepted, but
its result was not yet assessed when stopped. Previously proven: XNU CPU/IRQ,
BSD/md0, successful exec of static PID1 and first EL0 syscall open (code5).
Latest diagnosed blocker: vn_open_auth/namei user-pointer access with the
inherited A53 configuration lacking PAN support. Heartbeat remains unconfirmed.
Next session: inspect logs/redfin/pan/ if the last collector captured anything;
otherwise connect rooted Android and run the existing boot cycle when requested.
All backups/dumps/binaries/logs stay local and ignored; no partitions flashed.
