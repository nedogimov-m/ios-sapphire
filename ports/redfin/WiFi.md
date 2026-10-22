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
an exact copy and adds a one-shot kernel observer before UFS probing; device
execution remains unverified. `wifi-smem.c` is the host-only CLI for an exact
regular 2 MiB snapshot:

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
