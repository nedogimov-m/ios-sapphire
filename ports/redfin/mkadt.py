#!/usr/bin/env python3
"""Generate a Pixel 5 ADT for an eventual RAM-only, single-CPU PID 1 boot.

The RAM window must come from the live bootloader DT, excluding every reserved
region. This generator cannot verify that a supplied range is safe. It supplies
no framebuffer or peripheral drivers and does not add redfin kernel support:
upstream's CPU checks and fixed early framebuffer writes still need patches.
"""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import adt

PAGE_SIZE = 0x4000
PHYSICAL_LIMIT = 1 << 36
MPIDRS = tuple(range(0, 0x800, 0x100))
SOC_BASE = 0x01000000  # pe_arm_get_soc_base_phys requires a nonzero base.
# Google redbull kernel, arch/arm64/boot/dts/qcom/lito.dtsi.
GICD, GICD_SIZE = 0x17A00000, 0x10000
GICR, GICR_SIZE = 0x17A60000, 0x100000
TIMEBASE = 19200000
VTIMER_INTID = 19
DISPLAY_BASE, DISPLAY_BYTES = 0xA0000000, 0x02300000
DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_STRIDE = 1080, 2340, 4320
DISPLAY_CANVAS_WIDTH, DISPLAY_CANVAS_HEIGHT = 1125, 2436


def u32(*values):
    return struct.pack('<%dI' % len(values), *values)


def u64(*values):
    return struct.pack('<%dQ' % len(values), *values)


def cstr(value):
    return value.encode('ascii') + b'\0'


def node(name, props=(), children=()):
    result = adt.Node()
    result.props = [('name', 0, cstr(name))]
    result.props.extend((key, 0, value) for key, value in props)
    result.children = list(children)
    return result


def apple_userspace_identity(root, blob):
    """Add D22AP product data and the upstream development boot policy.

    All physical memory, CPU and peripheral descriptions remain Redfin's.
    Identity values below are synthetic; no handset identifiers are imported.
    """
    if not isinstance(blob, bytes) or not 32 <= len(blob) <= 2 * 1024 * 1024:
        raise ValueError('Apple ADT must be between 32 bytes and 2 MiB')
    source, end = adt.parse(blob)
    if end != len(blob) or source.prop('model') != cstr('iPhone10,3') or source.prop('target-sub-type') != cstr('D22AP'):
        raise ValueError('expected the iPhone X D22AP device tree')
    products = [child for child in source.children if child.name == 'product']
    if len(products) != 1 or any(child.name == 'product' for child in root.children):
        raise ValueError('expected exactly one new Apple product node')
    props = [(key, cstr('sRGB') if key == 'artwork-display-gamut' else value)
             for key, flag, value in products[0].props
             if not flag and key not in ('name', 'AAPL,phandle')]
    if not props:
        raise ValueError('Apple product node has no usable properties')
    root.children.append(node('product', [('AAPL,phandle', u32(0x100)), *props]))
    compatible = root.prop('compatible')
    root.props = [(key, flag, value) for key, flag, value in root.props
                  if key not in ('compatible', 'model', 'target-type', 'target-sub-type', 'manufacturer')]
    root.props.extend((key, 0, value) for key, value in [
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + compatible),
        ('model', cstr('iPhone10,3')), ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')), ('manufacturer', cstr('Apple Inc.'))])
    chosen = next(child for child in root.children if child.name == 'chosen')
    chosen.props.extend((key, 0, value) for key, value in [
        ('system-firmware-version', cstr('redfin-shim-development')),
        ('boot-manifest-hash', hashlib.sha384(b'redfin development boot manifest').digest()),
        ('crypto-hash-method', cstr('sha2-384')), ('display-scale', u32(3)),
        ('unique-chip-id', u64(0x52454446494e0001)), ('chip-id', u32(0x8015)),
        # MG reads this before waiting for an absent IONetworkController.
        # Stable synthetic local-unicast identity; no Wi-Fi hardware is bound.
        ('mac-address-wifi0', bytes.fromhex('025245444649')),
        ('certificate-production-status', u32(0)), ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)), ('effective-security-mode-sep', u32(1))])
    chosen.children.append(node('asmb', [
        ('AAPL,phandle', u32(0x101)), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))]))
    return root


def add_linear_display(root, reservation_base, reservation_bytes, framebuffer_base,
                       width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, stride=DISPLAY_STRIDE):
    """Add the observed Redfin ABL buffer; display.patch also requires redfinfb=1.

    Addresses are absolute properties, avoiding arm-io's SOC_BASE translation.
    Only the geometry demonstrated by REDFIN DIAGNOSTICS is accepted; this does
    not establish command-mode refresh or hardware-vsync support.
    """
    values = reservation_base, reservation_bytes, framebuffer_base, width, height, stride
    expected = DISPLAY_BASE, DISPLAY_BYTES, DISPLAY_BASE, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_STRIDE
    if any(type(value) is not int for value in values) or values != expected:
        raise ValueError('unverified Redfin splash framebuffer contract')
    arm_io = next(child for child in root.children if child.name == 'arm-io')
    if any(child.name == 'disp0' for child in arm_io.children):
        raise ValueError('display already present')
    arm_io.children.append(node('disp0', [
        ('AAPL,phandle', u32(0x102)),
        ('device_type', cstr('display-subsystem')), ('compatible', cstr('sweet,display')),
        ('redfin,abl-copy-only', u32(1)),
        ('redfin,framebuffer', u64(framebuffer_base, reservation_bytes)),
        ('width', u32(width)), ('height', u32(height)), ('stride', u32(stride)),
        ('pixel-format', cstr('BGRA')),
        ('canvas-width', u32(DISPLAY_CANVAS_WIDTH)), ('canvas-height', u32(DISPLAY_CANVAS_HEIGHT)),
    ]))
    return root


def build(memory_base, memory_size, boot_mpidr=0, seed=None):
    """Return an ADT node; address validation does not prove a RAM window safe."""
    for name, value in (('memory-base', memory_base), ('memory-size', memory_size)):
        if type(value) is not int or value <= 0 or value % PAGE_SIZE:
            raise ValueError(f'{name} must be a positive, 16 KiB aligned integer')
    if memory_base + memory_size > PHYSICAL_LIMIT:
        raise ValueError('RAM window exceeds the 36-bit physical address limit')
    if type(boot_mpidr) is not int or boot_mpidr not in MPIDRS:
        raise ValueError('boot-mpidr must be 0x0..0x700 in steps of 0x100')
    seed = os.urandom(64) if seed is None else seed
    if not isinstance(seed, bytes) or len(seed) != 64:
        raise ValueError('random seed must contain exactly 64 bytes')

    handles = iter(range(1, 32))

    def ph():
        return ('AAPL,phandle', u32(next(handles)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(memory_base)),
        ('dram-size', u64(memory_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('redfin-shim-development')),
    ], [node('memory-map', [ph()])])
    # keybagd reads the plain systembag.kb seeded by sweet-root-tweaks.py.
    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])
    cpu = node('cpu0', [
        ph(),
        ('device_type', cstr('cpu')),
        # kryo470 keeps the existing SweetCPU IONameMatch; it is not a SoC claim.
        ('compatible', cstr('qcom,kryo475') + cstr('qcom,kryo470') + cstr('ARM,v8')),
        ('reg', u32(boot_mpidr)),
        ('cpu-id', u32(0)),
        ('cluster-id', u32(0)),
        ('cluster-type', u32(0)),
        ('die-cluster-id', u32(0)),
        ('cluster-core-id', u32(0)),
        ('l2-cache-id', u32(0)),
        ('l3-cache-id', u32(0)),
        ('state', cstr('running')),
        ('timebase-frequency', u32(TIMEBASE)),
        ('fixed-frequency', u32(TIMEBASE)),
    ])
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)), ('#size-cells', u32(0))], [cpu])
    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(VTIMER_INTID)),
        ('reg', u64(GICD - SOC_BASE, GICD_SIZE, GICR - SOC_BASE, GICR_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('sweet-io')),
        ('compatible', cstr('sweet-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, (1 << 32) - SOC_BASE)),
    ], [gic])
    return node('device-tree', [
        ph(),
        # xiaomi,sweet keeps SweetPlatformExpert's existing IONameMatch.
        ('compatible', cstr('google,redfin') + cstr('xiaomi,sweet') + cstr('qcom,sm7250')),
        ('model', cstr('Google Pixel 5')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--memory-base', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--memory-size', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--boot-mpidr', type=lambda value: int(value, 0), default=0)
    parser.add_argument('--dump', action='store_true')
    args = parser.parse_args(argv)
    try:
        root = build(args.memory_base, args.memory_size, args.boot_mpidr)
    except ValueError as error:
        parser.error(str(error))
    blob = adt.serialize(root)
    args.output.write_bytes(blob)
    if args.dump:
        adt.dump(root)
    print(f'{args.output}: {len(blob)} bytes; ADT only, kernel support unverified', file=sys.stderr)


if __name__ == '__main__':
    main()
