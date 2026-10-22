#!/usr/bin/env python3
"""Build a Pixel 5 boot-v3 diagnostic image or XNU plus a static Darwin PID1.

No device commands are executed. XNU requires the redfin kernel overlay.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PAGE = 4096


def padded(data, alignment=PAGE):
    return data + bytes((-len(data)) % alignment)


def boot_v3(image, os_version):
    # AOSP bootimg.h boot_img_hdr_v3: 1580 bytes, 4096-byte pages.
    cpio = b'070701' + b''.join(f'{v:08x}'.encode() for v in
        (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 11, 0)) + b'TRAILER!!!\0'
    ramdisk = gzip.compress(padded(padded(cpio, 4), 512), mtime=0)
    cmdline = b'console=null'
    header = b'ANDROID!' + struct.pack('<9I', len(image), len(ramdisk),
        os_version, 1580, 0, 0, 0, 0, 3) + cmdline.ljust(1536, b'\0')
    assert len(header) == 1580
    return padded(header) + padded(image) + padded(ramdisk)


def run(args):
    subprocess.run([str(a) for a in args], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=HERE / 'out')
    p.add_argument('--stock-boot', type=Path, required=True,
        help='saved active-slot boot.img; retain its OS version/security patch metadata')
    p.add_argument('--cross-prefix', default=os.environ.get('CROSS_COMPILE', 'aarch64-elf-'))
    p.add_argument('--splash', action='store_true', help=
        'EXPERIMENTAL: draw at the live FDT splash reservation start; scanout is unverified')
    p.add_argument('--stride', type=int, default=4320, help='bytes per row; used only with --splash')
    p.add_argument('--seconds', type=int, default=30, help='time before PSCI system reset')
    p.add_argument('--kernel', type=Path, help='kernel built with ports/redfin/redfin.patch')
    p.add_argument('--dtb', type=Path, help='validated live Redfin DTB, required with --kernel')
    p.add_argument('--apple-adt', type=Path, help='D22AP product identity and development policy for Apple userspace')
    p.add_argument('--memory-base', type=lambda x: int(x, 0))
    p.add_argument('--memory-size', type=lambda x: int(x, 0))
    p.add_argument('--boot-mpidr', type=lambda x: int(x, 0), default=0)
    p.add_argument('--trace', action='store_true', help='enable verbose kernel kprintf tracing')
    p.add_argument('--trace-syscalls', action='store_true', help='enable PID1 syscall and pathname diagnostics')
    p.add_argument('--cpu-capability-probe', action='store_true', help='wake and park CPU6 to record architectural capabilities; RAM root and verified return only')
    p.add_argument('--cpu-capability-target', type=lambda x: int(x, 0), help='select one secondary MPIDR 0x100..0x700 for --cpu-capability-probe; default CPU6')
    p.add_argument('--early-return-probe', action='store_true', help='rehearse the shared bootloader-return leaf after existing verified return; separate RAM-only CPU0 test')
    p.add_argument('--shim-early-return', action='store_true', help='prearm the same return leaf before payload validation; requires the isolated --early-return-probe rehearsal profile')
    p.add_argument('--smp-probe', action='store_true', help='isolated md0 CPU0+CPU6 XNU proof; requires compiled shim prearm and bootloader return')
    p.add_argument('--smp-cpus', type=int, choices=(2, 8), help='CPU count for the isolated --smp-probe; default 2')
    p.add_argument('--display', action='store_true', help='publish the CPU-copy AppleCLCD display; requires --kernel, --apple-adt and --splash')
    p.add_argument('--display-hz', type=int, help='software display copy cadence, 1..10 Hz; requires --display; omitted keeps kernel default')
    p.add_argument('--capture-screen', action='store_true', help='capture up to three tiny display frames in the RAM log; requires --display')
    p.add_argument('--userspace-stacks', action='store_true', help='capture bounded user thread stacks before timed shutdown')
    p.add_argument('--touch-probe', action='store_true', help='observe SEC SPI controller handoff without transactions')
    p.add_argument('--touch-rail-probe', action='store_true', help='read fixed PMIC identity and candidate LDO states without PMIC writes')
    p.add_argument('--touch-id-probe', action='store_true', help='prepare L17 and cold SEC SPI, then read ID only; RAM root and bootloader return required')
    p.add_argument('--touch-scan-probe', action='store_true', help='read SEC state and enable runtime sensing with a bounded queue probe; initial RAM root only')
    p.add_argument('--touch-events', action='store_true', help='start SEC sensing and HID events with the validated UFS/CPU-display profile')
    p.add_argument('--usb-probe', action='store_true', help='observe DWC3 handoff without PHY or DMA changes')
    p.add_argument('--usb-route-probe', action='store_true', help='observe halted DWC3 and standard SMMU routing without writes')
    p.add_argument('--usb-owned-probe', action='store_true', help='claim only the USB SMMU stream in the initial RAM experiment; no gadget or DMA')
    p.add_argument('--usb-context-probe', action='store_true', help='read inherited SMMU context banks only; RAM root and bootloader return required')
    p.add_argument('--usb-bypass-probe', action='store_true', help='claim a dedicated NS bypass context and USB route only; no gadget or DMA')
    p.add_argument('--usb-enumeration-probe', action='store_true', help='start the guarded enumeration-only USB gadget for 30 seconds; initial RAM root only')
    p.add_argument('--usb-aarch64-context', action='store_true', help='opt into native AArch64 format for the owned USB bypass context; requires a USB bypass or enumeration probe')
    p.add_argument('--usb-network-probe', action='store_true', help='start bounded USB ECM networking with the validated AArch64 context; initial RAM root only')
    p.add_argument('--usb-live-log', action='store_true', help='stream kernel log over bounded USB ECM; requires --usb-network-probe')
    p.add_argument('--rpmh-probe', action='store_true', help='inspect CMD-DB and RPMh TCS handoff without commands')
    p.add_argument('--gpu-probe', action='store_true', help='observe Adreno 620 clock handoff; requires --display')
    p.add_argument('--wifi-probe', action='store_true', help='inspect reserved SMEM transport without firmware or FIFO writes')
    p.add_argument('--shutdown-seconds', type=int, default=0,
        help='gracefully stop iOS after 5..300 seconds; requires --ufs-root and --return-bootloader')
    p.add_argument('--spmi-probe', action='store_true', help='read PM8150 subtype and reboot-reason spare through the SPMI observer')
    p.add_argument('--return-bootloader', action='store_true', help='arm verified PMIC/IMEM bootloader return before the watchdog reset')
    ufs = p.add_mutually_exclusive_group()
    ufs.add_argument('--ufs-probe', action='store_true', help='read UFS host registers; keep storage initialization disabled')
    ufs.add_argument('--ufs-read-probe', action='store_true', help='test UFS capacity and GPT reads; leave filesystem drivers disabled')
    ufs.add_argument('--ufs-wake-probe', action='store_true', help='activate UFS Device WLUN before read probes; no media writes')
    ufs.add_argument('--ufs-root-probe', action='store_true', help='expose userdata read-only and test a raw device read from PID1')
    ufs.add_argument('--ufs-root', action='store_true', help='boot the prepared HFS userdata root; defaults to read-only and requires --apple-adt')
    p.add_argument('--ufs-rw', action='store_true', help='enable writes to the prepared userdata root; requires --ufs-root and the gated writable kernel overlay')
    p.add_argument('--watchdog-seconds', type=int, default=28,
        help='hardware reset after this many seconds (+3 s bite margin) for XNU runs')
    a = p.parse_args()
    if a.smp_cpus is not None and not a.smp_probe:
        p.error('--smp-cpus requires --smp-probe')
    if a.cpu_capability_target is not None:
        if not a.cpu_capability_probe:
            p.error('--cpu-capability-target requires --cpu-capability-probe')
        if a.cpu_capability_target not in range(0x100, 0x800, 0x100):
            p.error('--cpu-capability-target must be 0x100..0x700 in steps of 0x100')
    if a.shim_early_return and not (a.early_return_probe or a.smp_probe):
        p.error('--shim-early-return requires --early-return-probe or --smp-probe')
    if a.smp_probe:
        if not (a.kernel and a.dtb and a.return_bootloader and a.shim_early_return):
            p.error('--smp-probe requires --kernel, --dtb, --return-bootloader and --shim-early-return')
        if a.boot_mpidr != 0:
            p.error('--smp-probe requires boot CPU0')
        competing = ('display', 'splash', 'touch_events', 'usb_aarch64_context',
                     'usb_live_log', 'ufs_root', 'ufs_rw', 'shutdown_seconds',
                     'userspace_stacks', 'capture_screen', 'trace_syscalls', 'spmi_probe')
        if (any(getattr(a, name) for name in competing) or
                any(value for name, value in vars(a).items()
                    if name.endswith('_probe') and name != 'smp_probe')):
            p.error('--smp-probe requires a separate RAM-only profile')
    if a.early_return_probe:
        if not (a.kernel and a.dtb and a.return_bootloader):
            p.error('--early-return-probe requires --kernel, --dtb and --return-bootloader')
        if a.boot_mpidr != 0:
            p.error('--early-return-probe requires boot CPU0')
        competing = ('display', 'splash', 'touch_events', 'usb_aarch64_context',
                     'usb_live_log', 'ufs_root', 'ufs_rw', 'shutdown_seconds',
                     'userspace_stacks', 'capture_screen', 'trace_syscalls')
        if (any(getattr(a, name) for name in competing) or
                any(value for name, value in vars(a).items()
                    if name.endswith('_probe') and name not in
                    ('early_return_probe', 'spmi_probe'))):
            p.error('--early-return-probe requires a separate RAM-only profile')
    if a.cpu_capability_probe:
        if not (a.kernel and a.dtb and a.return_bootloader):
            p.error('--cpu-capability-probe requires --kernel, --dtb and --return-bootloader')
        if a.boot_mpidr != 0:
            p.error('--cpu-capability-probe requires boot CPU0')
        competing = ('display', 'splash', 'touch_events', 'usb_aarch64_context',
                     'usb_live_log', 'ufs_root', 'ufs_rw', 'shutdown_seconds',
                     'userspace_stacks', 'capture_screen', 'trace_syscalls')
        if (any(getattr(a, name) for name in competing) or
                any(value for name, value in vars(a).items()
                    if name.endswith('_probe') and name not in
                    ('cpu_capability_probe', 'spmi_probe'))):
            p.error('--cpu-capability-probe requires a separate RAM-only profile')
    if a.display_hz is not None:
        if not 1 <= a.display_hz <= 10:
            p.error('--display-hz must be in [1, 10]')
        if not a.display:
            p.error('--display-hz requires --display')
    if a.usb_live_log and not a.usb_network_probe:
        p.error('--usb-live-log requires --usb-network-probe')
    if a.usb_network_probe:
        a.usb_enumeration_probe = True
        a.usb_aarch64_context = True
    if a.usb_enumeration_probe:
        a.usb_bypass_probe = True
    if a.usb_aarch64_context and not a.usb_bypass_probe:
        p.error('--usb-aarch64-context requires --usb-bypass-probe or --usb-enumeration-probe')
    if a.touch_scan_probe:
        a.touch_id_probe = True
    if a.touch_id_probe:
        a.touch_rail_probe = True
    if a.touch_events:
        a.touch_rail_probe = True
    if (a.touch_probe or a.touch_rail_probe or a.usb_probe or a.usb_route_probe or a.usb_owned_probe or a.usb_context_probe or a.usb_bypass_probe or a.rpmh_probe or a.gpu_probe or a.wifi_probe) and not a.kernel:
        p.error('peripheral observers require --kernel')
    if a.gpu_probe and not a.display:
        p.error('--gpu-probe requires --display')
    if a.touch_events and a.touch_id_probe:
        p.error('GUI touch events must run separately from RAM touch ID or scan probes')
    if a.touch_events and not (a.ufs_root and a.display and a.return_bootloader):
        p.error('--touch-events requires --ufs-root, --display and --return-bootloader')
    if a.touch_events and (a.usb_probe or a.usb_route_probe or a.usb_owned_probe or
                           a.usb_context_probe or a.usb_bypass_probe or a.gpu_probe or
                           a.wifi_probe or a.rpmh_probe):
        p.error('GUI touch events require USB, GPU, Wi-Fi and RPMh probes disabled')
    if a.touch_id_probe and not a.return_bootloader:
        p.error('--touch-id-probe requires --return-bootloader')
    if a.usb_owned_probe and not a.return_bootloader:
        p.error('--usb-owned-probe requires --return-bootloader')
    if a.usb_owned_probe and a.touch_id_probe:
        p.error('initial touch ID and owned USB experiments must run separately')
    if a.usb_context_probe and not a.return_bootloader:
        p.error('--usb-context-probe requires --return-bootloader')
    if a.usb_context_probe and (a.usb_owned_probe or a.touch_id_probe):
        p.error('USB context observation must run separately from touch ID and owned USB experiments')
    if a.usb_bypass_probe and not a.return_bootloader:
        p.error('--usb-bypass-probe requires --return-bootloader')
    if a.usb_bypass_probe and (a.usb_owned_probe or a.usb_context_probe or a.touch_id_probe):
        p.error('USB bypass experiment must run separately from touch ID, direct claim and context observation')
    if a.ufs_rw and not a.ufs_root:
        p.error('--ufs-rw requires --ufs-root')
    if a.display and not (a.kernel and a.apple_adt and a.splash):
        p.error('--display requires --kernel, --apple-adt and --splash')
    if a.display and a.stride != 4320:
        p.error('--display requires the observed 4320-byte framebuffer stride')
    if a.capture_screen and not a.display:
        p.error('--capture-screen requires --display')
    if a.trace_syscalls and not a.kernel:
        p.error('--trace-syscalls requires --kernel')
    if a.shutdown_seconds and not 5 <= a.shutdown_seconds <= 300:
        p.error('--shutdown-seconds must be zero or in [5, 300]')
    if a.shutdown_seconds and not (a.kernel and a.ufs_root and a.return_bootloader):
        p.error('--shutdown-seconds requires --kernel, --ufs-root and --return-bootloader')
    if a.userspace_stacks and not a.shutdown_seconds:
        p.error('--userspace-stacks requires --shutdown-seconds')
    if (a.return_bootloader and not a.smp_probe) or a.touch_rail_probe:
        a.spmi_probe = True
    ufs_mode = 3 if a.ufs_wake_probe or a.ufs_root_probe or a.ufs_root else 2 if a.ufs_read_probe else int(a.ufs_probe)
    if a.touch_id_probe and ufs_mode:
        p.error('--touch-id-probe requires the initial RAM root without UFS')
    if a.usb_owned_probe and ufs_mode:
        p.error('--usb-owned-probe requires the initial RAM root without UFS')
    if a.usb_context_probe and ufs_mode:
        p.error('--usb-context-probe requires the initial RAM root without UFS')
    if a.usb_bypass_probe and ufs_mode:
        p.error('--usb-bypass-probe requires the initial RAM root without UFS')
    if (a.apple_adt or ufs_mode or a.spmi_probe) and not a.kernel:
        p.error('Apple identity and UFS probes require --kernel')
    if a.ufs_root and not a.apple_adt:
        p.error('--ufs-root requires --apple-adt')
    if not 4320 <= a.stride <= 16384 or a.stride % 4:
        p.error('--stride must be a multiple of 4 in [4320, 16384]')
    if not 5 <= a.seconds <= 300:
        p.error('--seconds must be in [5, 300]')
    if not 10 <= a.watchdog_seconds <= 29:
        p.error('--watchdog-seconds must be in [10, 29] (20-bit hardware counter)')
    with a.stock_boot.open('rb') as stock:
        stock_header = stock.read(44)
    if len(stock_header) != 44 or stock_header[:8] != b'ANDROID!' or struct.unpack_from('<I', stock_header, 40)[0] != 3:
        p.error('--stock-boot must be an Android boot image v3')
    os_version = struct.unpack_from('<I', stock_header, 16)[0]
    if not os_version:
        p.error('stock boot image has no OS version/security patch metadata')
    tools = {name: shutil.which(a.cross_prefix + name) for name in ('gcc', 'objcopy', 'nm', 'readelf')}
    if not all(tools.values()):
        p.error('missing AArch64 toolchain: brew install aarch64-elf-gcc (or --cross-prefix)')
    clang = shutil.which('clang')
    if not clang:
        p.error('clang is required to assemble the Darwin PID1')
    lz4 = shutil.which('lz4')
    if not lz4:
        p.error('lz4 is required for the verified Pixel boot format: brew install lz4')
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    init_source = (ROOT / 'tools/sweet-init.S').read_text().replace('SWEET', 'REDFIN')
    if a.ufs_root_probe:
        if init_source.count('\ntick:\n') != 1:
            p.error('unexpected static PID1 heartbeat entry')
        init_source = init_source.replace('\ntick:\n', '\n' + (HERE / 'ufs-init.inc.S').read_text() + '\ntick:\n')
    (out / 'init.S').write_text(init_source)
    run([clang, '-target', 'arm64-apple-ios16.0', '-c', out / 'init.S', '-o', out / 'init.o'])
    run([sys.executable, ROOT / 'tools/mkinit.py', out / 'init.o', out / 'init'])
    payload = b''
    if a.kernel:
        if a.dtb is None or a.memory_base is None or a.memory_size is None:
            p.error('--kernel requires --dtb, --memory-base and --memory-size')
        sys.path.insert(0, str(HERE))
        from memory import validate_window
        import mkadt
        from tools import adt
        validate_window(a.dtb.read_bytes(), a.memory_base, a.memory_size)
        tree = (mkadt.build(a.memory_base, a.memory_size, a.boot_mpidr, smp=True, smp_cpus=a.smp_cpus or 2)
                if a.smp_probe else mkadt.build(a.memory_base, a.memory_size, a.boot_mpidr))
        if a.apple_adt:
            mkadt.apple_userspace_identity(tree, a.apple_adt.read_bytes())
        from memory import _tree
        nodes, _ = _tree(a.dtb.read_bytes())
        from peripherals import add_observers
        try:
            add_observers(tree, nodes, touch=a.touch_probe or a.touch_id_probe or a.touch_events, usb=a.usb_probe,
                          gpu=a.gpu_probe, wifi=a.wifi_probe,
                          usb_route=a.usb_route_probe or a.usb_owned_probe or a.usb_context_probe or a.usb_bypass_probe,
                          usb_bypass=a.usb_bypass_probe, rpmh=a.rpmh_probe)
        except ValueError as error:
            p.error(str(error))
        if a.spmi_probe or a.smp_probe:
            spmi = nodes.get('/soc/qcom,spmi@c440000', {})
            names = spmi.get('reg-names', b'').rstrip(b'\0').split(b'\0')
            ranges = []
            try:
                for name in (b'core', b'obsrvr', b'cnfg'):
                    ranges.extend(struct.unpack_from('>II', spmi.get('reg', b''), names.index(name) * 8))
            except (ValueError, struct.error):
                p.error('live FDT has no valid SPMI observer ranges')
            if ranges != [0xc440000, 0x1100, 0xe600000, 0x100000, 0xc40a000, 0x26000] or spmi.get('qcom,ee') != struct.pack('>I', 0):
                p.error('live SPMI controller does not match Redfin EE0')
            tree.children.append(mkadt.node('redfin-spmi', [('reg', mkadt.u64(*ranges)), ('ee', mkadt.u32(0))]))
            if a.return_bootloader:
                try:
                    channel = struct.unpack_from('>II', spmi.get('reg', b''), names.index(b'chnls') * 8)
                    imem = nodes['/soc/qcom,msm-imem@146ab000']
                    reason = nodes['/soc/qcom,msm-imem@146ab000/restart_reason@65c']
                except (ValueError, KeyError, struct.error):
                    p.error('live FDT has no verified bootloader return registers')
                if channel != (0xc600000, 0x2000000) or imem.get('reg') != struct.pack('>II', 0x146ab000, 0x1000) or reason.get('reg') != struct.pack('>II', 0x65c, 4):
                    p.error('live bootloader return registers do not match Redfin')
                tree.children.append(mkadt.node('redfin-return', [('reg', mkadt.u64(*channel, 0x146ab65c, 4))]))
        if ufs_mode:
            ufs = nodes.get('/soc/ufshc@1d84000', {})
            names = ufs.get('reg-names', b'').rstrip(b'\0').split(b'\0')
            try:
                index = names.index(b'ufs_mem')
                base, size = struct.unpack_from('>II', ufs.get('reg', b''), index * 8)
            except (ValueError, struct.error):
                p.error('live FDT has no valid UFS host register range')
            if (base, size) != (0x1d84000, 0x3000):
                p.error('live UFS host does not match Redfin')
            tree.children.append(mkadt.node('redfin-ufs', [('reg', mkadt.u64(base, size))]))
        # Pixel's two ramoops areas are swapped/decrypted by Android. Mirror the
        # console ABI in both; never write its encryption metadata or partitions.
        consoles = []
        for name in ('ramoops_region@B7E41000', 'alt_ramoops_region@B8241000'):
            reg = nodes.get('/reserved-memory/' + name, {}).get('reg', b'')
            if len(reg) != 16:
                p.error('live FDT must contain both Pixel ramoops reservations')
            base, size = struct.unpack('>QQ', reg)
            if size != 0x400000:
                p.error('unexpected Pixel ramoops reservation size')
            consoles.extend((base + 0x280000, 0x100000))
        tree.children.append(mkadt.node('redfin-log', [('reg', mkadt.u64(*consoles))]))
        watchdogs = [props for props in nodes.values()
            if b'qcom,msm-watchdog\0' in props.get('compatible', b'')]
        if len(watchdogs) != 1 or watchdogs[0].get('reg') != struct.pack('>II', 0x17c10000, 0x1000):
            p.error('live FDT watchdog must match the verified Redfin controller')
        tree.children.append(mkadt.node('redfin-watchdog', [
            ('reg', mkadt.u64(0x17c10000, 0x1000))]))
        # XNU's panic machinery requires pram even on a DEVELOPMENT kernel.
        # Use one unused dump area below the primary console, inside ramoops.
        tree.children.append(mkadt.node('pram', [
            ('reg', mkadt.u64(consoles[0] - 0x80000, 0x80000))]))
        chosen = next(child for child in tree.children if child.name == 'chosen')
        chosen.props.append(('embedded-panic-log-size', 0, mkadt.u32(0x80000)))
        if a.splash:
            regs = nodes.get('/reserved-memory/cont_splash_region', {}).get('reg', b'')
            if len(regs) != 16:
                p.error('live FDT must contain a splash reservation')
            fb_base, fb_size = struct.unpack('>QQ', regs)
            if fb_size < a.stride * 2340:
                p.error('splash reservation cannot hold the requested console')
            tree.children.append(mkadt.node('sweet-fbcon', [
                ('reg', mkadt.u64(fb_base, fb_size)), ('width', mkadt.u32(1080)),
                ('height', mkadt.u32(2340)), ('stride', mkadt.u32(a.stride))]))
            if a.display:
                mkadt.add_linear_display(tree, fb_base, fb_size, fb_base, 1080, 2340, a.stride)
        (out / 'redfin.adt').write_bytes(adt.serialize(tree))
        command_line = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 '
            'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0')
        if a.ufs_root:
            command_line = command_line.replace('rd=md0', 'rd=ufsroot0')
            # Match upstream tools/sapphire-boot.sh for real Apple launchd.
            # In particular, root tweaks invalidate launchd.plist's Apple sig.
            command_line += (' unentitled_ios_sim_launch=1 ignition_level=1 '
                'wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1')
        if a.trace:
            command_line += ' -enable_kprintf_spam'
        if a.trace_syscalls:
            command_line += ' redfintrace=1'
        if a.cpu_capability_probe:
            command_line += ' redfincpu=1'
        if a.cpu_capability_target is not None:
            command_line += f' redfincputarget=0x{a.cpu_capability_target:03x}'
        if a.early_return_probe:
            command_line += ' redfinearlyreturn=1'
        if a.smp_probe:
            command_line = command_line.replace('cpus=1', f'cpus={a.smp_cpus or 2}')
            command_line += ' redfinsmp=1 redfinshim=1 redfinspmi=0 redfinreturn=0'
        if a.display:
            command_line += ' redfinfb=1 sweetfb_noconsole=1'
        if a.display_hz is not None:
            command_line += f' sweetfb_hz={a.display_hz}'
        if a.capture_screen:
            command_line += ' redfinscreen=1'
        if a.shutdown_seconds:
            command_line += f' redfinshutdown={a.shutdown_seconds}'
        if a.userspace_stacks:
            command_line += ' redfinstacks=1'
        usb_mode = 3 if a.usb_owned_probe or a.usb_context_probe or a.usb_bypass_probe else 2 if a.usb_route_probe else int(a.usb_probe)
        touch_mode = 2 if a.touch_id_probe or a.touch_events else int(a.touch_probe)
        for mode, name in ((touch_mode, 'redfintouch'), (usb_mode, 'redfinusb'),
                           (int(a.gpu_probe), 'redfingpu'), (int(a.wifi_probe), 'redfinwifi'),
                           (int(a.rpmh_probe), 'redfinrpmh'), (int(a.touch_rail_probe), 'redfinrail')):
            if mode:
                command_line += f' {name}={mode}'
        if a.touch_id_probe or a.touch_events:
            command_line += ' redfintouchsetup=1 redfinrpmhtouch=1'
        if a.touch_scan_probe:
            command_line += ' redfintouchscan=1'
        if a.touch_events:
            command_line += ' redfintouchevents=1'
        if a.usb_owned_probe or a.usb_context_probe or a.usb_bypass_probe:
            command_line += ' redfinusbowned=1'
        if a.usb_context_probe:
            command_line += ' redfinusbcontexts=1'
        if a.usb_bypass_probe:
            command_line += ' redfinusbbypass=1'
        if a.usb_aarch64_context:
            command_line += ' redfinusbrw64=1'
        if a.usb_enumeration_probe:
            command_line += ' redfinusbgadget=1 redfinusbsecs=30'
        if a.usb_network_probe:
            command_line += ' redfinusbnet=1'
        if a.usb_live_log:
            command_line += ' redfinusblog=1'
        if ufs_mode:
            command_line += f' redfinufs={ufs_mode}'
        if a.spmi_probe:
            command_line += ' redfinspmi=1'
        if a.return_bootloader and not a.smp_probe:
            command_line += ' redfinreturn=1'
        # A per-image nonce binds authenticated RAM logs to this build.
        boot_id = int.from_bytes(os.urandom(8), 'big') or 1
        command_line += f' redfinbootid=0x{boot_id:016x}'
        if a.ufs_root_probe or a.ufs_root:
            writable = int(a.ufs_rw)
            command_line += f' redfinroot=1 ufsroot=userdata ufsrw={writable} rootrw={writable} sweetlog=0'
        run([sys.executable, ROOT / 'tools/mkpayload.py', a.kernel, out / 'redfin.adt',
            out / 'payload.bin', '--ramdisk', out / 'init', '--cmdline',
            command_line])
        payload = (out / 'payload.bin').read_bytes()
    (out / 'config.h').write_text(f'#define DIAG_SPLASH {int(a.splash)}\n'
        f'#define DIAG_STRIDE {a.stride}\n#define DIAG_SECONDS {a.seconds}\n'
        f'#define WATCHDOG_SECONDS {a.watchdog_seconds}\n'
        f'#define SHIM_EARLY_RETURN {int(a.shim_early_return)}\n'
        f'#define REDFIN_SMP_PROBE {int(a.smp_probe)}\n'
        f'#define REDFIN_SMP_CPUS {a.smp_cpus or 2}\n'
        f'#define XNU_PAYLOAD_SIZE {len(payload)}ULL\n')
    flags = ['-O2', '-ffreestanding', '-fno-builtin', '-nostdlib', '-fno-pic',
        '-mgeneral-regs-only', '-mstrict-align', '-fno-stack-protector',
        '-fno-tree-loop-distribute-patterns', '-Wall', '-Wextra', '-Werror', '-I', out]
    objects = []
    for src in (ROOT / 'shim/start.S', HERE / 'diag.c', HERE / 'fdt.c', HERE / 'loader.c', HERE / 'watchdog.c'):
        obj = out / (src.stem + '.o')
        run([tools['gcc'], *flags, '-c', src, '-o', obj])
        objects.append(obj)
    relocs = subprocess.check_output([tools['readelf'], '-r', *map(str, objects[1:])], text=True)
    if 'R_AARCH64_ABS' in relocs:
        raise SystemExit('C objects contain absolute addresses: image cannot relocate')
    run([tools['gcc'], *flags, '-static', '-T', ROOT / 'shim/shim.ld',
        '-Wl,--build-id=none', '-Wl,--no-warn-rwx-segments', '-Wl,-N',
        *objects, '-o', out / 'redfin-diag.elf'])
    run([tools['objcopy'], '-O', 'binary', out / 'redfin-diag.elf', out / 'Image'])
    symbols = subprocess.check_output([tools['nm'], str(out / 'redfin-diag.elf')], text=True)
    image_end = next(int(line.split()[0], 16) for line in symbols.splitlines()
                     if line.split()[-1] == '_end')
    image = (out / 'Image').read_bytes()
    if len(image) > image_end or struct.unpack_from('<Q', image, 16)[0] != image_end:
        raise SystemExit('invalid Linux Image image_size')
    image = image.ljust(image_end, b'\0')
    if payload:
        image = padded(image, 16384) + payload
        image = image[:16] + struct.pack('<Q', len(image)) + image[24:]
    # Pixel ABL rejects text_offset=0; the code itself remains PC-relative.
    image = image[:8] + struct.pack('<Q', 0x80000) + image[16:]
    (out / 'Image').write_bytes(image)
    run([lz4, '-f', '-q', '-B7', '-BI', '--no-content-size', out / 'Image', out / 'Image.lz4'])
    # Match the stock Pixel LZ4 frame plus trailing uncompressed-size word.
    compressed = (out / 'Image.lz4').read_bytes() + struct.pack('<I', len(image))
    image_name = 'redfin-xnu.img' if payload else 'redfin-diag.img'
    (out / image_name).write_bytes(boot_v3(compressed, os_version))
    artifacts = ('Image', 'redfin-diag.elf', image_name, 'init')
    manifest = dict(stage='XNU/PID1 execution unverified' if payload else 'diagnostics only',
        root_writable=bool(a.ufs_rw),
        cpu_copy_display=bool(a.display), shutdown_seconds=a.shutdown_seconds,
        capture_screen=bool(a.capture_screen),
        userspace_stacks=bool(a.userspace_stacks),
        syscall_tracing=bool(a.trace_syscalls),
        splash_reservation_assumption=a.splash, stride=a.stride, seconds=a.seconds,
        linux_text_offset='0x80000', kernel_encoding='LZ4 frame + LE32 size',
        upstream=subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip(),
        sha256={name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in artifacts})
    if a.kernel:
        manifest.update(boot_args=command_line, root_device='ufsroot0' if a.ufs_root else 'md0',
                        kernel={'path': str(a.kernel.resolve()),
                                'sha256': hashlib.sha256(a.kernel.read_bytes()).hexdigest()})
    if a.display_hz is not None:
        manifest['display_hz'] = a.display_hz
    if a.cpu_capability_probe:
        manifest['cpu_capability_probe'] = True
    if a.cpu_capability_target is not None:
        manifest['cpu_capability_target'] = a.cpu_capability_target
    if a.early_return_probe:
        manifest['early_return_probe'] = True
    if a.shim_early_return:
        manifest['shim_early_return'] = True
    if a.smp_probe:
        manifest['smp_probe'] = True
        manifest['smp_cpus'] = a.smp_cpus or 2
        manifest['sha256']['config.h'] = hashlib.sha256((out / 'config.h').read_bytes()).hexdigest()
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{out}/{image_name}: Android boot v3, execution unverified')
    print(f'{out}/init: static arm64 Darwin PID1')


if __name__ == '__main__':
    main()
