#!/usr/bin/env python3
"""Generate a Pixel 5 ADT for an eventual RAM-only, single-CPU PID 1 boot.

The RAM window must come from the live bootloader DT, excluding every reserved
region. This generator cannot verify that a supplied range is safe. It supplies
no framebuffer or peripheral drivers and does not add redfin kernel support:
upstream's CPU checks and fixed early framebuffer writes still need patches.
"""
import argparse
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
    # pmap_compute_max_asids requires /defaults even with no overrides.
    defaults = node('defaults', [ph()])
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
