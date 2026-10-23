# Redfin Wi-Fi: evidence and the next two stages

2026-10-22. No XNU Wi-Fi association or data transfer has been demonstrated on
Pixel 5. A MAC address or an ICNSS probe is not that evidence.

The saved live FDT (`research/redfin-root/device.dtb`) and recovery capture
(`research/redfin-peripherals-v1/buses.txt:12`, `dmesg.txt:1185`) agree:

| Property | Verified value |
| --- | --- |
| Host interface | integrated SNOC, `qcom,icnss`; Linux driver `msm_icnss` |
| WLAN registers | `0x18800000 + 0x800000`; twelve copy engines |
| WLAN SMMU stream | `0xc0`, mask `1`; IPA's separate WLAN stream is `0x521` |
| MSA firmware reservation | `0x8ba00000 + 0x200000` |
| Modem/WLAN firmware reservation | `0x8c000000 + 0x11800000` (Google board override) |
| SMEM | `0x80900000 + 0x200000`, reserved and aligned to 16 KiB |
| GLINK notification | IPCC `0x00408000 + 0x1000`, SPI 229; MPSS client 2, signal 0 |
| SMEM allocator lock | TCSR syscon `0x01f40000 + 0x20000`, lock 3, stride `0x1000` |
| WLAN CE SPI indices | `132,81,415,416,417,86,94,96,82,119,120,87`; add 32 for GIC INTIDs |

Pinned sources are Google's [Lito DTS](https://android.googlesource.com/kernel/msm-extra/devicetree/+/afc98e2bb0716a57bf4f8d2b6191378dd7123ce4/qcom/lito.dtsi#3662),
[board memory override](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/arch/arm64/boot/dts/google/lito-redbull-memory.dtsi#52),
and [redbull config](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/arch/arm64/configs/redbull_defconfig#617).
`CONFIG_ICNSS=m` plus `ICNSS_QMI=y` selects the legacy `icnss.c`, not ICNSS2/WCN6750.
[BoardConfig](https://android.googlesource.com/device/google/redbull/+/3595d0b214eeeddf87e2c37477e3e74f831eca82/BoardConfig-common.mk#418)
selects `qcwcn`/`qca_cld3`. The Bluetooth `wcn3990` compatible does not establish
the exact WLAN RF chip/revision. That needs a WLFW capability response containing
chip/family/board/SoC IDs and firmware version. The recovery capture has ICNSS
probe success, but no firmware-ready/capability response.

The Linux power path enables five RPMh supplies (`vdd-cx-mx`, `vdd-1.8-xo`,
`vdd-1.3-rfa`, `vdd-3.3-ch1`, `vdd-3.3-ch0`) before its optional
`cxo_ref_clk_pin` clock. The DT supplies resolve to LDOA1/A14/C2/C11/C10.
Modem PIL separately requires RPMh XO/CX/MSS votes, AOP notification and trusted
`modem` firmware with PAS ID 4. See
[icnss.c power](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/soc/qcom/icnss.c#574)
and [QMI setup](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/soc/qcom/icnss.c#1085).
WLFW is QMI service `0x45`, version 1, instance 0. Setup registers indications,
exchanges MSA regions, assigns permissions, signals MSA ready, reads capabilities,
and waits for firmware ready. Stock firmware, board/calibration assets and their
exact Redfin IDs are not yet inventoried; the vendor WLAN config is
`/vendor/firmware/wlan/qca_cld/WCNSS_qcom_cfg.ini`.

## Stage 1: inspect the transport without touching hardware registers

`wifi_smem.h` is a bounded, allocation-free C parser. `wifi-probe.patch` embeds
an exact copy and adds a one-shot kernel observer before UFS probing. V3
execution returned `status=5 version=0xc0000`. Its `partitions=0` was not
evidence of an empty table: the old parser copied only the version to its
report before the failing return. V4 preserved failure metadata and identified
the TOC's own `ffff/ffff` reservation. The parser now selects APPS/private
and global heaps before validating their extents, following Linux host
selection; it never maps foreign-host entries. V5 validated the real layout:
14 entries, APPS/MODEM at `0xfb000+0x7c000`, no uncached items or GLINK
descriptor/FIFOs. This does not prove a live remote processor; firmware
startup and transport creation are still required. `wifi-smem.c`
is the host-only CLI for an exact regular 2 MiB snapshot:

```sh
cc -std=c11 -Wall -Wextra -Werror ports/redfin/wifi-smem.c -o /tmp/redfin-wifi-smem
/tmp/redfin-wifi-smem /path/to/private/smem.raw
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ports/redfin -p test_wifi_smem.py
```

The kernel observer requires exact `redfinwifi=1`, `cpus=1` and a new
`/redfin-wifi` node whose absolute `reg` is the verified SMEM range. Revalidate
that the incoming live FDT reserves it, excludes it from the XNU RAM window,
and has the expected APPS/MPSS topology before emitting
`reserved-memory-verified = u32(1)` in that ADT node. The observer independently
checks exact reg/marker lengths and the chosen RAM range's nonoverlap. It maps only
that 2 MiB RAM range with `kIOMapReadOnly | kIOMapWriteCombineCache`; never map
IPCC/TCSR/WLAN registers in this probe. No allocator lock, SMEM allocation,
FIFO reset/advance, notification, SCM, firmware load or power vote is allowed.

The parser checks the SBL initialization/version, `$TOC` table and nonoverlapping
partitions, APPS(0)/MODEM(1) `$PRT`, uncached item bounds/padding/canaries and
GLINK IDs 478/479/480 (descriptor/TX/RX). Descriptor indices and wrapped pending
byte counts are reported. Cached items are explicitly uninspected. Invalid or
changing headers fail closed; missing objects are observations, not proof of a
dead modem. Even a populated or nonempty FIFO can be stale. This probe cannot
prove remote-firmware liveness or absence of QMI. Two time-separated snapshots
can establish observed changes, not an authenticated firmware identity.

Observer status codes: 0 valid layout, 1 bad length, 2 SBL-uninitialized,
3 unsupported SMEM version, 4 bad table, 5 bad partition, 6 bad item,
7 invalid GLINK geometry/indices, 8 allocator headers changed during reading.
These classify the observed RAM layout, not the remote processor's power state.

### Partition diagnostics for the next observation

Google's pinned `smem.c:158` defines 48-byte TOC entries after a 32-byte TOC
header. Each entry has offset/size at 0/4, host0/host1 at 12/14 and cacheline
at 16; the partition header is also 32 bytes. The existing parser uses this
stride correctly. Linux APPS enumeration (`smem.c:945`) skips non-APPS hosts
and entries whose offset **or** size is zero. It validates the chosen host
membership without requiring the same order in the TOC and header. Linux
also handles a separate global partition with hosts `0xfffe/0xfffe`.

Our observer deliberately remains stricter: it checks every active range,
rejects partial zero entries and overlaps, and requires the selected
APPS/MODEM header host order to match its TOC entry. These differences are
possible rejection causes, not a diagnosis of V3. No condition was relaxed
to accept unseen firmware data.

For rejected observations the kernel emits two extra bounded metadata lines:
`reject detail=... entry=... offset=... bytes=... hosts=... cacheline=... peer=...`
and `peer_offset=... peer_bytes=... header=... magic=... hosts=... size=... free_u=... free_c=...`.
Entry and peer indices are zero-based; `0xffffffff` means no entry/peer.
`header=1` means the complete header was in a validated range before reading
its metadata. `header=0` leaves its fields zero and performs no header read.
The header belongs to the diagnostic entry, which can differ from an earlier
selected MODEM partition if a later table entry fails. No item identifiers,
FIFO payloads, firmware identities or network credentials are added to logs.

| `detail` | Rejection |
| --- | --- |
| 0 | No partition-specific detail; use the main status |
| 1 | Exactly one of entry offset/size is zero |
| 2 | Entry range does not fit below the TOC or cannot contain its header |
| 3 | Entry overlaps `peer`; both bounds are retained |
| 4 | Duplicate APPS/MODEM entry; `peer` is the first |
| 5 | Selected partition header magic differs from `$PRT` |
| 6 | Selected header host order differs from its TOC entry |
| 7 | Selected header size differs from its TOC entry |
| 8 | Uncached/cached free pointers fail existing bounds |

Thirteen host tests compile the actual C parser and C++ observer. They cover
48-byte strides, global/unused slots, every partition rejection detail,
preserved metadata, unchanged input bytes, bounded log formatting, mapping
cleanup/gates and exact equality of the embedded header. Passing these tests
does not establish that the observed allocator is live or usable by QMI.

## Stage 2: firmware identity, then association and actual packets

Port Lito's verified SMEM/IPCC/GLINK/QRTR and trusted remote-firmware boot/power
sequence, then obtain a fresh WLFW capability response. Only after firmware
readiness and exact board data are established, port CE/HTC/WMI/HTT with a
bounded DMA/SMMU design. Keep WLAN SID `0xc0` separate from IPA `0x521` and all
other SMMU owners. The 16 KiB XNU page size does not change firmware's 4 KiB
layouts; do not share XNU page tables with the SMMU. High XNU RAM starts above
4 GiB, so DMA address width and a separately validated pool must be established.
Do not reuse Sapphire's hardcoded `0xe0000000` pool or identity-map all RAM.

Sapphire's code already implements scan, open authentication, association,
WPA2-PSK four-way exchange and Ethernet TX/RX hooks. Its successful association
is recorded in `NOTES.md` (2026-10-20), but it has no iOS network-interface/DHCP
consumer. Redfin must first validate its own firmware ABI and DMA completion.
The useful finish criteria are association plus key installation, then an
Ethernet/IP interface with DHCP, ARP and bidirectional packets (for example,
ping to a test AP), rather than a MAC identity or a scan-only result.

Sapphire transport addresses differ: SMEM `0x46000000`, TCSR `0x00340000`, APCS
`0x0f111000`, MSA `0x51900000`, WLAN SID `0x1a0`, CE base `0x0ca40000`.
Do not enable `modem=1 wifi=1` on Redfin as a substitute for this port.


## Native MPSS firmware boundary — 2026-10-22

The saved Redfin FDT identifies `/soc/qcom,mss@4080000` as
`qcom,pil-tz-generic`, firmware `modem`, PAS ID 4. Google's pinned
[peripheral loader](https://android.googlesource.com/kernel/msm/+/500b3a2059c1eec0fec08ec56add06320ea901a8/drivers/soc/qcom/peripheral-loader.c#1008)
requests `modem.mdt`, then `modem.b%02d` for non-hash PT_LOAD entries with
nonzero file size. The suffix is the original program-header index, not an
index after filtering. The exact required suffixes must come from the stock
Redfin MDT. A separate hash blob is needed only when the metadata is not
already contained in the MDT; reproduce the observed layout before PAS init.
Google's `ueventd` firmware directory is `/vendor/firmware_mnt/image/`.

The public Redfin vendor inventory also includes
`vendor/firmware/wlanmdsp.mbn`, `modemuw.jsn`, `bdwlan-redfin.bin` and
`bdwlan-u-redfin.bin`. The service metadata describes `msm/modem/wlan_pd`,
QMI instance 180, with `kernel/elf_loader`, `tms/servreg` and `wlan/fw`
services. These describe a later modem user-domain/board-data stage; they do
not replace the PAS modem image. Legacy `icnss.c` has no direct
`request_firmware` call. ICNSS2/WCN6750 board-file naming is not evidence for
this device. Preserve the exact stock board-data alternatives until live
capabilities and the stock selection path establish which one is required.

The compiled Topaz/Sapphire modem implementation cannot be enabled unchanged.
Its modem carveout `0x4ab00000+0x6900000`, SMEM `0x46000000`, firmware pool
`0xe0000000`, APCS `0x0f111000` and hardware mutex `0x00340000` differ from
Redfin. Its firmware tables contain other boards' offsets/CRCs; patch 0143
falls back to the Topaz table when no MDT CRC matches. Its ELF loader and
SMEM allocator also lack the bounds required by the native Redfin port.
`tools/fwtable-modem.py` assumes FAT16 and follows unbounded cluster chains;
it must not be used directly against an unvalidated stock capture.

The first native implementation should consume a bounded, identity-checked
manifest rather than a board-table fallback. Validate FAT geometry, every
cluster/extent and duplicate path; then ELF class/endianness, header and
program-header sizes/counts, all arithmetic, `filesz <= memsz`, exact blob
lengths, relocation and nonoverlapping destination bounds inside the proven
modem reservation. Establish a separate source-backed SCM metadata buffer;
do not reuse the Sapphire pool. Build any SMEM allocator on the existing
bounded Redfin parser, with the proven TCSR lock. PAS 4, fresh remote-ready,
GLINK and WLFW capability exchange follow these prerequisites. No native
loader, PAS call or MPSS readiness is claimed by this audit.

### Read-only stock extraction

The validated saved LUN0 GPT identifies `modem_a` as `sda12` and `modem_b` as
`sda13`. Reconfirm the live by-name symlink, sysfs geometry, partition length
and GPT name/LBA bounds in temporary safe recovery before reading either.
Keep Android filesystems unmounted. Stream only the selected modem partition
with host-side binary capture, verify its exact length and SHA-256 against a
read-only device digest, then inventory the host file without mounting it.
Retain the dump, extracted firmware and per-device manifest only in ignored
private paths. Do not print GPT GUIDs or serials into public reports.

This inventory requires no modem flash, mount, slot switch, GPT write,
remote-processor start, or access to `modemst1/2`, `fsg` or `fsc`. Vendor
assets can be inventoried later from a separate read-only stock vendor source;
booting Android on the replaced userdata is not part of extraction. Any future
UFS firmware reader must authorize only the verified modem partition/ranges
and retain the existing userdata/write fences.

### Bounded base vendor inventory

`super_inventory.py` consumes at most4MiB of a regular host super prefix
and an externally captured current-slot:b witness. It checks both geometry
copies, both selected-slot header/table hashes and complete-slot equality,
table references and source bounds before emitting vendor_b extents. Eleven
synthetic tests cover corrupt/truncated metadata, ambiguous slot evidence,
overlaps, oversized images and unsupported targets. It issues no device I/O;
the caller must separately verify GPT, by-name, partition length and freshness.

The observed metadata contains Virtual A/B COW entries. Raw vendor_b therefore
means the base filesystem, not a proved current snapshot. Firmware inventory
must preserve that distinction; reconcile base version, COW state and modem
compatibility before loading any extracted assets. The firmware and per-device
plans stay private. Targeted read-only filesystem requests can use the verified
extent map without dumping the whole9.7GB super partition.

The first targeted base-vendor pass extracted WLAN firmware, both Redfin board
variants and the station configuration with a hash-verified sparse host cache.
Only4,509,696 bytes of vendor data were requested, plus8,667,136 bytes for
before/after GPT and super metadata verification. Safe recovery performed no
mounts or disk writes and returned to verified fastboot. All artifacts remain
under private `research/redfin-modem-inventory/vendor-assets-v1/`.
The base identifies Redfin but contains mixed version properties: an Android14
UP1A fingerprint/security patch alongside Android16/BP4A/SDK36/userdebug
fields. It must not be described as a pristine stock or effective snapshot.
COW/modem compatibility and native PAS/GLINK/WLFW startup remain unproved.
No firmware was loaded.

## Native MPSS loader and private firmware bundle — 2026-10-23

`wifi_firmware.h` now implements the native firmware-loading boundary rather
than using Topaz's modem tables. It parses the observed compact ELF32/Hexagon
MDT, preserves the original program-header number in each `modem.bNN` choice,
and checks all load/zero-fill extents, overlap, entry point and firmware bounds.
The supported destination remains the exact live Redfin MPSS reservation
`0x8c000000+0x11800000`. Its hash program header is metadata; its address is
never treated as another load destination. Mixed fixed/relocatable images and
other metadata layouts are refused until separately established.

The host planner compiles that same C implementation:

```sh
cc -std=c11 -Wall -Wextra -Werror ports/redfin/wifi-firmware-plan.c \
  -o /tmp/redfin-wifi-firmware-plan
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s ports/redfin -p 'test_wifi_*.py'
```

`wifi_firmware.py` binds the MPSS node's PAS4/modem/AOP contract and phandle
to the exact live reservation, verifies SMEM/display reservations and kernel
RAM, and passes all other fixed/recovery reservations to the native planner.
It consumes the existing private, verified FAT inventory and extracted files;
it neither reads a partition nor invents a firmware-table fallback. Every
required asset must match its inventoried length/SHA256 and native PHDR index.
The optional output is a mode0600, atomically published, no-overwrite bundle.
Firmware, hashes tied to a device capture and reports remain in ignored paths.

For example, using already captured host files (replace the private paths):

```sh
python3 ports/redfin/wifi_firmware.py \
  --inventory research/private/inventory.json \
  --assets research/private/minimal-mpss --dtb research/private/device.dtb \
  --planner /tmp/redfin-wifi-firmware-plan \
  --xnu-base 0x180000000 --xnu-bytes 0x80000000 \
  --bundle research/private/mpss.bundle
```

The runtime validates the bundle's bounded layout, every SHA256 and exact asset
set before invoking any platform callback. Its one-attempt lifecycle performs
AOP load-state, proxy votes, metadata copy/sync, PAS INIT_IMAGE and MEM_SETUP,
bounded 64 KiB firmware copies/BSS clearing, final sync and PAS AUTH_AND_RESET.
SCM transport status and PAS result must both succeed. Success additionally
requires a fresh, post-authentication SMP2P err-ready observation. Shutdown
requires an acknowledged SMP2P stop before PAS shutdown, power release and AOP
load-state off. Ownership loss or failed teardown quarantines the lease and
retains uncertain resources; no automatic retry or forced reset is provided.
The platform must implement these operations with native hardware guards.

The caller owns a 6352-byte workspace in its persistent worker context; large
arrays never occupy the kernel entry stack. Freestanding optimized ARM64
compilation reports 176 bytes for the boot wrapper, 80 for the planner, 96 for
SCM and 80 for cleanup. `wifi-firmware.patch` exports an exact header copy and
`RedfinWiFiFirmware.cpp`, which uses XNU's existing SHA256 implementation.
The adapter compiles with the actual ARM64 IOKit flags. The patch has no startup
hook or source-list changes and is deliberately not in the builders yet.

Observation: 37 Wi-Fi host tests pass (23 new firmware tests plus 14 existing
SMEM tests), including real native copy/BSS contents, corruption before I/O,
original PHDR numbering, all platform failure positions, lease loss, separate
PAS failures, acknowledged-stop ordering, file safety and strict C++/ARM64
compilation. The existing real Redfin inventory produced a 99,395,632-byte
private bundle. Its native parser/hash preflight passes with 35 PHDRs, 33 loads,
31 assets, 30 live exclusions and the exact 0x11800000 span. File payloads total
99,384,626 bytes and BSS 191,553,563 bytes. No MPSS power/start/SCM operation ran;
PAS authentication, GLINK creation, WLFW capability, association and packets
remain unobserved.

Integration still requires a source-complete native XO/CX/MSS and bandwidth
lease, AOP QMP mailbox with acknowledged delivery, SCM convention/resume
handling, APPS/MPSS allocator/SMP2P ownership and fresh ready/stop proof. A
review of these hardware prerequisites follows before any startup hook.

## Native AOP transport and exact platform binding — 2026-10-23

`wifi_aop.c` now implements Redfin's QMP mailbox handshake, warm idle-channel
adoption and the exact 64-byte modem `load_state` on/off messages. It uses the
live Lito 4 KiB msgram range at `0x0c300000`; HackiOS's hardcoded 1 KiB map is
not copied. The read-only observer requires two equal descriptor snapshots
before publishing geometry. Every write/notification/poll rechecks the lease,
immutable geometry and APPS-owned control words. Payload words are read back
before the length is published. Message completion requires AOP consumption;
it does not establish MPSS readiness. Failed or ambiguous operations poison the
session, preserve an outstanding length and prohibit retries or link reset.

`wifi_platform.py` validates the actual live MPSS XO/CX/MSS supplier chain,
TURBO consumer level 384, RPMh DRV2 layout, AOP/QMP/IPCC phandles, APPS/MPSS
SMP2P IDs and CMD-DB reservation. It emits a separate `redfin-wifi-native` ADT
contract for the next read-only probe, after validating the physical inputs.
Its host CLI accepts only the saved FDT and explicit kernel window:

```sh
python3 ports/redfin/wifi_platform.py --dtb research/private/device.dtb \
  --xnu-base 0x180000000 --xnu-bytes 0x80000000
```

Source details are pinned to Google's kernel commit
`500b3a2059c1eec0fec08ec56add06320ea901a8` (`msm_qmp.c`, `qcom_ipcc.c`,
`clk-rpmh.c`, `rpmh-regulator.c`, `smp2p.c`, `subsys-pil-tz.c`) and Lito DT
commit `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`. The primary HackiOS snapshot
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab` was reviewed for its mailbox
interface and serialization; its WPSS/PAS6 power/radio path remains excluded.

MPSS uses inbound SMEM item 435, outbound 428, local PID 0 and remote PID 1.
Notifications are IPCC client 2, signal 2; AOP is client 0, signal 0. The
`master-kernel` force-stop bit is 0. Incoming `slave-kernel` bits are fatal 0,
ready 1, proxy-unvote 2, stop-ack 3 and shutdown-ack 7. The CX and MSS values
384 are consumer levels, requiring CMD-DB ARC selector lookup. They must not
be written directly as selector data. XO uses `xo.lvl` with clock-driver ARC
data 3. Power votes must preserve inherited floors and coordinate with the
existing DRV2 manager; no new RPMh writer is enabled here.

Observation: the real saved live FDT passes the complete host binding with
30 protected exclusions. All 60 Wi-Fi tests pass: 17 native AOP transport tests,
6 platform-binding tests, 23 firmware tests and 14 SMEM tests. These cover all
open-read failures, each control/payload write failure, ownership loss, word
readback, exact packet bytes, descriptor/role mutations and bounded ACK waits.
`wifi-aop.patch` exports the tested native source/header, with no startup or
source-list change. No AOP doorbell, message-memory write or modem startup has
run on hardware. Next: a bounded native read-only AOP/SMEM/CMD-DB probe to
establish cold-ABL mailbox state and the missing MSS resource mapping, followed
by native guarded SMP2P and power/SCM integration.

## Native read-only prerequisite probe prepared — 2026-10-23

`wifi-native-probe.patch` supplies `RedfinWiFiProbe.cpp` and its public header;
the entry is `extern "C" void redfin_wifi_native_observe(void)`. It requires
the separate `redfinwifi=2 redfinwifinative=1` mode, one CPU, `rd=md0`, a nonzero
boot ID and the actual cached PMIC/IMEM return proof. Inherited radio/GPU/USB
drivers stay disabled. The previous `redfinwifi=1` SMEM observer remains a
separate mode. No startup hook, builder change or device operation is installed
by these overlays; the coordinator owns that integration.

The exact `redfin-wifi-native` ADT is generated by
`wifi_platform.add_probe_contract(tree, nodes)` only after the live platform
binding succeeds. Its `reg` consists of native u64 pairs for AOP
`0x0c300000+0x1000`, SMEM `0x80900000+0x200000` and CMD-DB
`0x80860000+0x20000`. `live-fdt-verified` is u32(1), and `source-contract` is
u32(1,4,384,384,3,435,428,1,0,0x20002,1,3). The kernel checks exact property
lengths/values and nonoverlap with the selected kernel RAM before mapping.

All three mappings use `kIOMapReadOnly`; AOP write/notify/pause callbacks are
NULL. The probe logs raw AOP descriptor state even if malformed, the bounded
stable-observer result/pending lengths, SMEM/GLINK layout, and the actual
`xo.lvl`, `cx.lvl`, `mss.lvl` resource addresses and complete bounded raw AUX
arrays. It computes the TURBO selector from a valid increasing consumer-level
table only as a diagnostic. This is neither a power reading nor a vote. It
never maps IPCC/TCSR/RSC, loads firmware, calls PAS, advances a FIFO, writes
shared memory or accesses media. Every map is released on success or failure.

Observation: all 70 focused Wi-Fi tests pass, including 10 actual-probe tests
for every profile/ADT gate, mapping failure/cleanup, malformed AOP, preservation
of pending messages, return-proof loss, exact overlay contents and unchanged
input bytes. Both the AOP C source and kernel probe compile with the real XNU
ARM64 flags/headers using a private source tree. Native stack frames are 960
bytes for the observer, 816 for the SMEM parser, 192 for AOP observation and
64 for its snapshot helper. No full kernel or hardware test is claimed for
this milestone. Next: isolated temporary md0 observer boot, then use its fresh
mailbox/MSS-resource facts to finish native power/SMP2P/SCM startup.

## Native SMEM allocation and SMP2P lifecycle prepared — 2026-10-23

`wifi_smp2p.c` implements a bounded cold APPS/MODEM private-SMEM allocator and
the native MPSS ready/stop protocol. Its platform lease must prove this
session's PAS reset/authentication state, serialize APPS allocation and own
Redfin TCSR lock 3 (`0x01f43000`, APPS owner 1). Neither an absent SMEM object
nor a boot argument establishes reset. The allocator refuses existing items
428/435, GLINK or cached allocations, initializes only a new 340-byte outbound
item, publishes allocation metadata before its valid version and releases only
the verified APPS-owned mutex. `master-kernel` and `ipa` come from Lito's DT.

Subsequent writes recheck the TOC fingerprint, partition geometry, item header
and every APPS-owned payload word. After authenticated PAS4, a newly allocated
inbound item 435 must have stable snapshots, the exact SMP2P ABI/PIDs and valid
entry names. Feature/restart acknowledgement changes only the APPS words;
later restart, fatal or identity changes quarantine the session. The bounded
stop path requires a fresh low-to-high stop acknowledgement and clears the
APPS force-stop bit only afterward. A missing acknowledgement retains the
request and prevents PAS/power/AOP release. No retry resets the channel.

Observation: all 91 focused Wi-Fi tests pass, including 21 new SMP2P tests.
Every one of the allocator's 92 stores has a failure-injection case. Three
combined models execute the actual firmware lifecycle, AOP transport and
SMP2P implementation together, covering successful acknowledged shutdown,
stop failure retaining resources and corrupt firmware failing before any I/O.
The deployed overlay compiles with actual XNU ARM64 flags in a private source
tree; maximum frame is 1152 bytes (`peer`), allocator 160 and heap parser 816.
`wifi-smp2p.patch` contains the exact source/header without startup or source-list
changes. No SMEM, TCSR or SMP2P IPCC write has run on the device. PAS/SCM proof,
native power binding, GLINK/WLFW and Wi-Fi association/data remain unfinished.

## Guarded retained-power/AOP phase prepared — 2026-10-23

The coordinator's authenticated `wifi-native-v1` device cycle established the
closed AOP negotiation state and exact `xo.lvl`, `cx.lvl`, `mss.lvl` resources
used below. That read-only run completed PID1 heartbeats and verified fastboot
return. It did not prove a Wi-Fi power vote, modem start or radio operation.

The existing `RedfinWiFiProbe.cpp` now has a separate `redfinwifipower=1` path.
Its exact command-line contract is the native-v1 CPU0/md0 profile plus that
single flag and a fresh nonzero 16-digit boot ID:

```text
debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinwifipower=1 redfinspmi=1 redfinreturn=1 redfinbootid=0x<FRESH_16_HEX_DIGITS>
```

Only optional `-enable_kprintf_spam` is additionally admitted. Duplicate/unknown
arguments and competing RPMh, GPU, AOP, GUI or root modes fail before mapping.
The native lease binds the sole attempt to the current thread, physical CPU0,
EL1, unchanged command line, exact mappings and actual cached PMIC/IMEM return
proof. Ownership failure is sticky. The old path remains read-only when the
new flag is absent.

`wifi_platform.add_power_contract(tree, nodes)` emits an additional
`redfin-wifi-power` ADT leaf after validating the live GIC/GCC/DRV2 topology and
inherited interrupt parents. `reg` is native u64 pairs for AOP
`0x0c300000+0x1000`, IPCC `0x00408000+0x1000`, DRV2 `0x18220000+0x10000`, GCC
`0x00100000+0x1f0000`, GICD `0x17a00000+0x4000`, CMD-DB
`0x80860000+0x20000`. `live-fdt-verified` is u32(1); `source-contract` is
u32(1,2,0,1,37,261,0x71004,0x30000,7,416,0x30060,6,384,0x300a0,3,0).
The existing native observer leaf is also mandatory. Kernel RAM must be the
proven `0x180000000+0x80000000` window. Only AOP/IPCC/DRV2 map writable;
GCC/GIC/CMD-DB stay read-only.

Before writing, the probe checks exact complete ARC tables, both empty ACTIVE
TCSs, all inherited SLEEP/WAKE templates, idle DRV2, the enabled inherited CBCR,
masked/inactive RSC/IPCC interrupts and a usable empty AOP handoff. It then
performs source-backed ACTIVE transactions for CX selector7/corner416, MSS
selector6/level384 and XO data3. These highest legal votes preserve every
validated inherited resource floor; unsupported/illegal inherited votes fail.
Every typed write rechecks resource metadata, its own staged command and the
untouched inherited slots. Completion requires IRQ, idle and issued/completed
command status. No GIC or inherited template write is made.

Only after all three acknowledgements does the existing native QMP transport
open/adopt the channel and send the exact modem-on load-state packet through
IPCC client0/signal0. The probe retains all votes and AOP state until platform
reset. Failures quarantine the session without unvote, channel rollback, off
message or retry; uncertain message length remains intact. This phase never
calls SCM/PAS, allocates SMEM, writes TCSR, loads firmware or accesses media.

Observation: all 106 focused Wi-Fi tests pass. The actual native CPP adapter
runs against bounded fake IOKit/MMIO, exercising successful retained votes and
QMP, every one of 39 RSC and 25 AOP/IPCC stores/notifications failing, malformed
tables/ADT, mapping cleanup, illegal inherited floors, ownership loss and
bounded completion/ACK timeouts. The real saved live FDT passes the power
validator. Actual XNU ARM64 compilation in a private tree reports no source
diagnostics; maximum entry frame896 bytes and power snapshot336 bytes. The
existing overlay exports this code with no new source-list entry. No Wi-Fi
power/AOP write has run on hardware. Device testing is currently unavailable;
SCM capability proof, PAS4 start, bandwidth/remaining proxy integration,
SMP2P hardware operation, GLINK/WLFW, association and data remain unfinished.

## Immutable boot-blob firmware source prepared — 2026-10-23

The reviewed primary HackiOS kernel snapshot
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab` keeps plain firmware files in its
resident image (`redwood_image.c`, `redwood_wifi.c`). Redfin now has a dedicated
flat boot-blob source with the same benefit: the kernel reads firmware in
place, without a second 99 MB allocation or a filesystem dependency. The current
UFS implementation is fenced to approved userdata; no new partition/extent
access, media placement or UFS interface is introduced here.

`wifi_fw_blob.py` appends one segment to an existing SWEETXNU v1 payload,
preserving kernel/PID1 segments and command line. The segment lives after the
old final segment, immediately before the relocated ADT and original boot
arguments, below `topOfKernelData`. The producer invokes
`wifi-fw-source-check.c` and the actual native source/bundle planner; it never
implements another ELF or asset parser. The selected whole-bundle SHA256 is
mandatory and must come from the recorded verified inventory. Files are
published mode 0600 without replacing an existing file or symlink.

The new ADT leaf `/redfin-wifi-fw` has `reg` = native u64(physical,reserved),
`bundle-bytes` = u64(logical bytes), `bundle-sha256` = 32 raw bytes, and
`source-contract` = u32(1,4,16384,0x10000000). The matching
`/chosen/memory-map/RedfinWiFiFirmware` is u64(physical,reserved). Reserved
length is logical length rounded to 16 KiB, and every padding byte must be zero.
The native source checks the actual BootArgs RAM/top, kernel end, ADT,
original argument extent and optional RAMDisk. XNU copies BootArgs into kernel
data; its current pointer is not the original argument physical address.

`wifi_fw_boot.cpp` requires an explicit live platform worker policy, physical
CPU0/EL1, unchanged current thread and copied BootArgs, native md0/return
profile, actual cached PMIC/IMEM proof, exact ADT source and immutable mapping.
It maps the full reserved source read-only with `IOMemoryDescriptor`, avoiding
the small `ml_io_map` aperture. It calls the existing native
`redfin_mpss_bundle_open` with all live exclusions, original PHDR indices and
per-asset hashes. Ownership failure is sticky; close releases only its own
source map. This source lease grants no MPSS destination authority.

`wifi_fw_source.c` exposes separate metadata and segment copy mechanisms for
the future platform manager. Destination callbacks must independently prove
the appropriate native PAS reset/INIT/MEM_SETUP phase. The module itself has
no SCM, power, device or media operation. Each write/zero is at most 64 KiB and
is read back before progress is published. The planner workspace remains
fingerprinted, source hashes are rechecked between phases, and aliased
control/readback buffers fail. Any uncertain operation quarantines the copy;
the caller retains responsibility for its destination lease and safe teardown.

Future kernel link dependencies are explicit: apply existing
`wifi-firmware.patch`, then `wifi-fw-source.patch`; add
`bsd/dev/redfin_wifi_fw_source.c` to BSD sources, and
`iokit/Kernel/arm/RedfinWiFiFWSource.cpp` plus existing
`iokit/Kernel/arm/RedfinWiFiFirmware.cpp` to IOKit C++ sources. The latter
provides the kernel SHA256 adapter. No startup hook/source-list integration is
installed by this milestone. The caller owns persistent `rf_wifi_fw_boot`,
the existing 6352-byte workspace and a separate 64 KiB readback buffer; keep
them outside the kernel entry stack and do not embed that buffer in OSObject.

Observation: the private bundle's recorded inventory hash passes through the
actual producer ADT, native CPP read-only source adapter, existing planner and
guard-page host-owned destination. It copies 9420 metadata bytes,
99,384,626 payload bytes, and zeros 191,553,563 BSS bytes, reading back every
chunk; 35 PHDRs / 33 loads / 31 assets and exact 0x11800000 span pass. The generated
private payload is 116,933,776 bytes with 12 segments (previously 11). Source is
`0x1825e4000+99,401,728`; ADT `0x1884b0000`, original arguments
`0x1884b0f00`, top `0x1884b4000`. Its full C loader preflight passes. Both
source files compile with actual XNU ARM64 flags/headers under `-Werror`
(only the existing system-header C++ designator warnings are suppressed);
maximum source/native frames are 192/272 bytes. All 133 focused Wi-Fi tests pass,
including the three explicitly enabled private-bundle cases.

Limits: source bundle <= 256 MiB; SWEETXNU <= 64 segments (one free slot required);
producer implementation bound 512 MiB with an explicit caller cap. The private
payload uses a 128 MiB host cap. These are software bounds, not measured Redfin
ABL download/decompressed-Image placement limits. No larger Image was built or
booted; source pinning, MPSS copy/readback and power remain untested on device.
SCM/PAS start, complete proxy/bandwidth, native SMP2P/GLINK/WLFW, association
and data remain unfinished. Firmware/payload/check reports remain private.
