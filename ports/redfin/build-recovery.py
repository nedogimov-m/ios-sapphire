#!/usr/bin/env python3
"""Build a temporary, RAM-only root-ADB image from backed-up Redfin boot v3.

No device commands. Keep the matching vendor_boot/DTBO installed. Recovery UI
is disabled: its Lineage startup mounts /data to copy ADB keys. This image
starts only ueventd and ADB, without filesystem mounting or formatting.

Boot v3 loads vendor ramdisk before generic ramdisk (Qcom BootLinux.c).
Lineage init tests /system/bin/recovery, and force_normal_boot=1 switches to
/first_stage_ramdisk even if the generic cmdline also contains '=0'. Copying
the recovery tree there makes both bootloader paths select recovery init.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import struct
import subprocess

PAGE = 4096
PROPERTIES = {
    'ro.secure': '0', 'ro.debuggable': '1', 'ro.force.debuggable': '1',
    'ro.adb.secure': '0', 'ro.adb.secure.recovery': '0',
    'ro.redfin.offline_recovery': '1',
    'ro.redfin.return_target': 'android',
}


def align(size, page=PAGE):
    return (size + page - 1) & -page


def records(data):
    """Parse newc without extracting paths or following symlinks."""
    result, offset = {}, 0
    while offset < len(data):
        if data[offset:offset + 4] == bytes(4):
            offset += 4
            continue
        if data[offset:offset + 6] not in (b'070701', b'070702') or offset + 110 > len(data):
            raise ValueError('invalid/truncated newc archive')
        fields = [int(data[offset + 6 + i*8:offset + 14 + i*8], 16) for i in range(13)]
        size, name_size = fields[6], fields[11]
        if not name_size or offset + 110 + name_size > len(data):
            raise ValueError('invalid newc name')
        name = data[offset + 110:offset + 110 + name_size - 1].decode()
        if data[offset + 110 + name_size - 1] != 0 or name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('unsafe newc path')
        start = align(offset + 110 + name_size, 4)
        if start + size > len(data):
            raise ValueError('truncated newc payload')
        if name != 'TRAILER!!!':
            if stat.S_ISREG(fields[1]) and fields[4] > 1:
                raise ValueError('regular hardlinks require explicit resolution')
            result[name] = (fields, data[start:start + size])
        offset = align(start + size, 4)
    return result


def archive(entries):
    output = bytearray()
    all_entries = list(entries.items()) + [('TRAILER!!!', ([0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], b''))]
    for inode, (name, (original, contents)) in enumerate(all_entries, 1):
        encoded = name.encode() + b'\0'
        fields = original.copy()
        fields[0], fields[4], fields[5] = inode, 1, 0
        fields[6], fields[11], fields[12] = len(contents), len(encoded), 0
        output += b'070701' + b''.join(f'{field:08x}'.encode() for field in fields) + encoded
        output += bytes(-len(output) % 4)
        output += contents
        output += bytes(-len(output) % 4)
    return bytes(output) + bytes(-len(output) % 512)


def file_entry(contents, mode=0o100644):
    return ([0, mode, 0, 0, 1, 0, len(contents), 0, 0, 0, 0, 0, 0], contents)


def decompress(data):
    return subprocess.run(['lz4', '-dc'], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def recovery_properties(return_target='android'):
    if return_target not in ('android', 'bootloader'):
        raise ValueError('unsupported recovery return target')
    return {**PROPERTIES, 'ro.redfin.return_target': return_target}


def recovery_tree(vendor, return_target='android'):
    properties = recovery_properties(return_target)
    required = ('system/bin/recovery', 'system/bin/init', 'system/bin/adbd',
                'system/bin/sh', 'system/bin/toybox', 'system/bin/toolbox',
                'system/bin/sleep', 'system/bin/setprop',
                'lib/modules/modules.load',
                'prop.default', 'system/etc/init/hw/init.rc', 'sepolicy', 'init.recovery.redfin.rc')
    if any(name not in vendor for name in required):
        raise ValueError('vendor ramdisk lacks matching recovery resources')
    tree = {name: value for name, value in vendor.items()
            if name != 'first_stage_ramdisk' and not name.startswith('first_stage_ramdisk/')}
    props = tree['prop.default'][1].decode()
    props = '\n'.join(line for line in props.splitlines()
                      if line.partition('=')[0] not in properties)
    props += '\n' + '\n'.join(f'{key}={value}' for key, value in properties.items()) + '\n'
    tree['prop.default'] = file_entry(props.encode())
    rc = tree['system/etc/init/hw/init.rc'][1].decode()
    marker = 'service recovery /system/bin/recovery\n'
    pseudo_only = rc
    for filesystem in ('tmpfs', 'binder', 'pstore', 'configfs', 'functionfs'):
        pseudo_only = pseudo_only.replace('mount ' + filesystem, filesystem)
    if rc.count(marker) != 1 or 'mount_all ' in rc or '\n    mount ' in pseudo_only:
        raise ValueError('unexpected recovery init layout: review before use')
    # Avoid UI/BCB processing, data-key copying, charger and HAL startup.
    rc = rc.replace(marker, marker + '    disabled\n')
    rc = rc.replace('    class_start default\n', '').replace('    class_start hal\n', '')
    reboot = 'reboot' if return_target == 'android' else 'reboot,bootloader'
    rc += '''
service recovery-return /system/bin/sh -c "/system/bin/sleep 120; /system/bin/setprop sys.powerctl RETURN_COMMAND"
    disabled
    oneshot
    user root
    group root
    seclabel u:r:su:s0

on boot
    start recovery-return
    setprop service.adb.root 1
    setprop sys.usb.config adb
'''.replace('RETURN_COMMAND', reboot)
    tree['system/etc/init/hw/init.rc'] = file_entry(rc.encode())
    return tree


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot', type=Path, required=True)
    parser.add_argument('--vendor-boot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--return-target', choices=('android', 'bootloader'), default='android',
                        help='120-second fallback destination; use bootloader after replacing userdata')
    args = parser.parse_args(argv)
    if not shutil.which('lz4'):
        parser.error('lz4 required')
    boot, vendor_boot = args.boot.read_bytes(), args.vendor_boot.read_bytes()
    if (len(boot) < PAGE or len(vendor_boot) < PAGE or
            boot[:8] != b'ANDROID!' or struct.unpack_from('<I', boot, 40)[0] != 3 or
            struct.unpack_from('<I', boot, 20)[0] != 1580 or vendor_boot[:8] != b'VNDRBOOT' or
            struct.unpack_from('<II', vendor_boot, 8) != (3, PAGE)):
        parser.error('requires matching Redfin boot/vendor_boot header v3')
    kernel_size, ramdisk_size = struct.unpack_from('<II', boot, 8)
    vendor_size = struct.unpack_from('<I', vendor_boot, 24)[0]
    offset = PAGE + align(kernel_size)
    if not kernel_size or offset + ramdisk_size > len(boot) or PAGE + vendor_size > len(vendor_boot):
        parser.error('truncated boot components')
    generic = records(decompress(boot[offset:offset + ramdisk_size]))
    vendor = records(decompress(vendor_boot[PAGE:PAGE + vendor_size]))
    tree = recovery_tree(vendor, args.return_target)
    # All existing generic entries precede our overlay. Both possible roots
    # get the same init policy; symlinks and module bytes retain vendor data.
    combined = dict(generic)
    for name in ('prop.default', 'system/etc/init/hw/init.rc'):
        combined[name] = tree[name]
    combined.update({'first_stage_ramdisk/' + name: value for name, value in tree.items()})
    cpio = archive(combined)
    parsed = records(cpio)
    assert parsed == records(archive(parsed))
    for prefix in ('', 'first_stage_ramdisk/'):
        assert parsed[prefix + 'prop.default'][1] == tree['prop.default'][1]
        assert b'service recovery /system/bin/recovery\n    disabled\n' in parsed[prefix + 'system/etc/init/hw/init.rc'][1]
    compressed = subprocess.run(['lz4', '-l', '-c'], input=cpio, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True).stdout
    assert decompress(compressed) == cpio
    header = bytearray(boot[:PAGE])
    struct.pack_into('<I', header, 12, len(compressed))
    cmdline = header[44:1580].split(b'\0')[0]
    cmdline += b' androidboot.mode=recovery androidboot.force_normal_boot=0'
    if len(cmdline) >= 1536:
        parser.error('stock cmdline leaves no room for recovery request')
    header[44:1580] = cmdline.ljust(1536, b'\0')
    kernel = boot[PAGE:PAGE + kernel_size]
    image = bytes(header) + kernel + bytes(-kernel_size % PAGE) + compressed + bytes(-len(compressed) % PAGE)
    if len(image) > len(boot):
        parser.error('temporary image exceeds backed-up boot partition')
    assert image[PAGE:PAGE + kernel_size] == kernel
    assert image[:12] == boot[:12] and image[16:44] == boot[16:44]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'recovery-adb-only.img').write_bytes(image)
    manifest = {
        'boot_header_version': 3, 'kernel_unchanged': True,
        'boot_sha256': hashlib.sha256(boot).hexdigest(),
        'vendor_boot_sha256': hashlib.sha256(vendor_boot).hexdigest(),
        'image_sha256': hashlib.sha256(image).hexdigest(),
        'image_bytes': len(image), 'generic_ramdisk_bytes': len(compressed),
        'recovery_ui_disabled': True, 'data_mount_actions': False,
        'userdata_writes': False, 'device_commands_executed': False,
        'runtime_verified': False, 'properties': recovery_properties(args.return_target),
        'return_target': args.return_target, 'return_after_seconds': 120,
        **({'return_to_android_seconds': 120} if args.return_target == 'android' else {}),
        'requires': 'Matching installed vendor_boot/DTBO; unlocked bootloader; temporary RAM boot only',
        'source_proof': [
            'https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions',
            'https://github.com/LineageOS/android_system_core/blob/lineage-23.2/init/first_stage_init.cpp',
            'https://github.com/LineageOS/android_system_core/blob/lineage-23.2/init/util.cpp',
            'https://github.com/LineageOS/android_packages_modules_adb/blob/lineage-23.2/daemon/main.cpp',
            'https://github.com/LineageOS/android_bootable_recovery/blob/lineage-23.2/recovery_main.cpp',
        ],
    }
    (args.out/'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'image': str(args.out/'recovery-adb-only.img'),
                      'sha256': manifest['image_sha256'], 'bytes': len(image),
                      'runtime_verified': False}, indent=2))


if __name__ == '__main__':
    main()
