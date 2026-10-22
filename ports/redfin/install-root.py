#!/usr/bin/env python3
"""Check a 16 GiB HFSX installation plan; writing requires --erase-userdata.

Use only the ADB-only recovery built by build-recovery.py. Check-only never
changes device properties or storage. --state-json replays saved evidence
offline and cannot enable writing. Obtain user consent before using the erase
flag: installation destroys Android user data. Boot/recovery/GPT stay intact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
import time
import zlib

from gpt import fingerprint

IMAGE_BYTES = 16 * 1024**3
MIB = 1024**2
BLOCK = 4096
PREFIX_BLOCKS = 33
RAW = '/dev/block/sda19'
PSEUDO = {'rootfs', 'tmpfs', 'ramfs', 'proc', 'sysfs', 'devtmpfs', 'devpts',
          'cgroup', 'cgroup2', 'selinuxfs', 'tracefs', 'debugfs', 'binder',
          'binderfs', 'pstore', 'configfs', 'functionfs', 'securityfs', 'bpf',
          'fusectl', 'mqueue', 'nsfs'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def atomic(path, data):
    temporary = path.with_name(path.name + '.partial')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def hfs_header(primary, alternate, size):
    require(size == IMAGE_BYTES, 'root image must be exactly 16 GiB')
    geometry = []
    for index, header in enumerate((primary, alternate)):
        require(len(header) == 512 and header[:4] == b'HX\x00\x05', 'expected raw HFSX v5')
        attributes = struct.unpack_from('>I', header, 4)[0]
        # Native images verified by fsck retain a stale alternate unmounted
        # bit. The current primary header supplies the clean-unmount state.
        require(not attributes & (1 << 11) and (index != 0 or attributes & (1 << 8)),
                'HFSX is dirty/inconsistent')
        require(attributes & (1 << 13), 'expected journaled HFSX')
        block, count = struct.unpack_from('>II', header, 40)
        require(4096 <= block <= MIB and not block & (block - 1) and block * count == size,
                'HFSX volume geometry differs from exact image length')
        geometry.append((block, count))
    require(geometry[0] == geometry[1], 'HFSX alternate volume header differs')
    return {'signature': 'HFSX', 'clean': True, 'journaled': True,
            'allocation_block_bytes': geometry[0][0]}


def filesystem_proof(record, manifest_path=None):
    proof = record.get('fsck')
    if proof is None:
        require(any(Path(command[0]).name == 'fsck_hfs' and '-fn' in command
                    for command in record.get('commands', []) if command),
                'manifest lacks successful filesystem check')
        return
    require(isinstance(proof, dict) and proof.get('success') is True and manifest_path is not None,
            'invalid explicit filesystem-check proof')
    name, checksum = proof.get('log'), proof.get('sha256')
    require(isinstance(name, str) and name and not Path(name).is_absolute() and
            '..' not in Path(name).parts and isinstance(checksum, str) and
            re.fullmatch('[0-9a-f]{64}', checksum), 'unsafe filesystem-check log path/hash')
    base = manifest_path.resolve().parent
    log = base / name
    require(log.resolve().is_relative_to(base) and log.is_file() and
            not any((base / Path(*Path(name).parts[:index])).is_symlink()
                    for index in range(1, len(Path(name).parts)+1)),
            'filesystem-check log escapes manifest directory or uses a symlink')
    require(log.stat().st_size <= 16*MIB, 'filesystem-check log exceeds 16 MiB')
    data = log.read_bytes()
    require(hashlib.sha256(data).hexdigest() == checksum, 'filesystem-check log SHA256 mismatch')
    text = data.decode()
    require('Executing fsck_hfs' in text, 'filesystem-check log lacks fsck_hfs execution')
    final_run = text.rsplit('Executing fsck_hfs', 1)[1]
    require('Checking Journaled HFS Plus volume.' in final_run and
            'Detected a case-sensitive volume.' in final_run and
            re.search(r'^\*\* The volume .+ appears to be OK\.$', final_run, re.MULTILINE),
            'filesystem-check log lacks final clean HFSX result')
    require(not re.search(r'FILE SYSTEM WAS MODIFIED|could not be verified|could not be repaired|is corrupt',
                          final_run, re.IGNORECASE), 'filesystem-check log reports an unsuccessful check')


def build_record(record, image, manifest_path=None):
    require(record.get('success') is True and record.get('stage') == 'root-prepared',
            'build manifest does not certify a prepared root')
    require(not record.get('blocked') and not record.get('detach_errors'), 'root build has unresolved errors')
    built = record.get('image', {})
    require(Path(built.get('path', '')).resolve() == image.resolve(), 'manifest names another image')
    require(built.get('bytes') == IMAGE_BYTES and re.fullmatch('[0-9a-f]{64}', built.get('sha256', '')),
            'manifest image size/SHA256 is invalid')
    checks = record.get('critical_content_checks', [])
    require(checks and all(item.get('matches_decompressed_source') is True for item in checks),
            'manifest has failed critical content checks')
    names = {item.get('path') for item in checks if item.get('matches_decompressed_source') is True}
    require({'sbin/launchd', 'usr/lib/dyld'} <= names and
            any(name and name.startswith('System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64') for name in names),
            'manifest lacks successful launchd/dyld/shared-cache content checks')
    filesystem_proof(record, manifest_path)
    return built['sha256']


def local_image(image, manifest):
    require(image.is_file() and not image.is_symlink(), 'image must be a regular local file')
    expected = build_record(json.loads(manifest.read_text()), image, manifest)
    if sys.platform == 'darwin':
        info = plistlib.loads(subprocess.run(['hdiutil', 'info', '-plist'], check=True, capture_output=True).stdout)
        require(not any(Path(item.get('image-path', '')).resolve() == image.resolve()
                        for item in info.get('images', [])), 'detach the root image before installation')
    else:
        for backing in Path('/sys/class/block').glob('loop*/loop/backing_file'):
            require(Path('/' + backing.read_text().strip().lstrip('/')).resolve() != image.resolve(),
                    'detach the root image loop device before installation')
    with image.open('rb') as stream:
        before = os.fstat(stream.fileno())
        stream.seek(1024); primary = stream.read(512)
        stream.seek(before.st_size - 1024); alternate = stream.read(512)
        header = hfs_header(primary, alternate, before.st_size)
        stream.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(4 * MIB), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    require((before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns), 'image changed during validation')
    require(digest.hexdigest() == expected, 'image SHA256 differs from successful build')
    return {'path': str(image.resolve()), 'bytes': IMAGE_BYTES, 'sha256': expected,
            'hfs': header, 'stat': [after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns]}


def partition(blob):
    proof = fingerprint(blob, BLOCK)
    entries, count, size = struct.unpack_from('<QII', blob, BLOCK + 72)
    matches = []
    for index in range(count):
        item = blob[entries*BLOCK + index*size:entries*BLOCK + (index+1)*size]
        if any(item[:16]) and item[56:128].decode('utf-16le').split('\0')[0] == 'userdata':
            begin, end = struct.unpack_from('<QQ', item, 32)
            matches.append({'index': index + 1, 'start_bytes': begin*BLOCK,
                            'bytes': (end-begin+1)*BLOCK, 'node': RAW})
    require(len(matches) == 1 and matches[0]['index'] == 19, 'expected exactly userdata GPT entry 19')
    require(matches[0]['bytes'] >= IMAGE_BYTES, 'root image does not fit userdata')
    require(count == 19, 'unexpected Redfin GPT entry count')
    return proof, matches[0]


def backup_proof(primary, tail):
    """Validate secondary metadata, including Redfin's primary-array reference.

    The saved vendor secondary header has entries_lba=2. Preserve that header;
    do not invent an independent array when no reserved-tail copy is present.
    The complete tail hash protects every captured byte before/after writing.
    """
    fingerprint(primary, BLOCK)
    require(len(tail) == PREFIX_BLOCKS*BLOCK, 'truncated secondary GPT capture')
    header = tail[-BLOCK:]
    require(header[:8] == b'EFI PART', 'missing secondary GPT')
    revision, length, checksum, reserved = struct.unpack_from('<4I', header, 8)
    require(revision == 0x10000 and 92 <= length <= BLOCK and not reserved, 'invalid secondary GPT header')
    raw = header[:length]
    require(zlib.crc32(raw[:16] + bytes(4) + raw[20:]) == checksum, 'secondary GPT header CRC mismatch')
    current, alternate, first, last = struct.unpack_from('<4Q', raw, 24)
    pcurrent, palternate, pfirst, plast = struct.unpack_from('<4Q', primary, BLOCK + 24)
    require((current, alternate, first, last) == (palternate, pcurrent, pfirst, plast) and
            raw[56:72] == primary[BLOCK + 56:BLOCK + 72], 'secondary GPT geometry/GUID differs')
    lba, count, size, crc = struct.unpack_from('<Q3I', raw, 72)
    plba, pcount, psize, pcrc = struct.unpack_from('<Q3I', primary, BLOCK + 72)
    require((count, size, crc) == (pcount, psize, pcrc), 'secondary GPT entry fields differ from primary')
    array = primary[plba*BLOCK:plba*BLOCK + count*size]
    require(len(array) == count*size and zlib.crc32(array) == crc, 'referenced primary GPT array CRC mismatch')
    capture_start = current + 1 - PREFIX_BLOCKS
    array_blocks = (count*size + BLOCK-1)//BLOCK
    candidates = []
    for candidate in range(max(last+1, capture_start), current-array_blocks+1):
        begin = (candidate-capture_start)*BLOCK
        contents = tail[begin:begin + count*size]
        if contents == array and zlib.crc32(contents) == crc:
            candidates.append(candidate)
    if lba == plba:
        reference = 'primary-array'
    else:
        require(lba > last and lba + array_blocks <= current,
                'secondary GPT array overlaps usable space/header')
        require(lba in candidates, 'secondary GPT array is outside capture or CRC/content differs')
        reference = 'secondary-array'
    return {'capture_sha256': hashlib.sha256(tail).hexdigest(),
            'header_sha256': hashlib.sha256(raw).hexdigest(),
            'header_crc32': f'{checksum:08x}', 'entry_array_crc32': f'{crc:08x}',
            'entries_reference': reference, 'declared_entries_lba': lba,
            'independent_array_verified': len(candidates) == 1,
            'physical_array_lba': candidates[0] if len(candidates) == 1 else None,
            'matching_reserved_array_count': len(candidates)}


def backup_fingerprint(primary, tail):
    return backup_proof(primary, tail)['capture_sha256']


def validate_state(state, target, primary):
    require(state.get('uid') == '0' and state.get('marker') == '1' and state.get('product') == 'redfin',
            'requires root ADB-only Redfin recovery marker; normal Android is refused')
    for line in state['mountinfo'].splitlines():
        parts = line.split()
        require('-' in parts and len(parts) >= 10, 'malformed mountinfo')
        separator = parts.index('-')
        require(separator + 3 < len(parts), 'malformed mountinfo filesystem')
        mount = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), parts[4])
        require(parts[separator+1] in PSEUDO and
                not any(mount == path or mount.startswith(path + '/') for path in ('/data', '/metadata')),
                'persistent filesystem or data/metadata mount is active')
    require(state['mountinfo'].strip(), 'empty mountinfo')
    require(len(state['swaps'].splitlines()) == 1 and state['swaps'].startswith('Filename'), 'swap is active')
    require(not state['holders'].strip() and not state['dm'].strip(), 'userdata holders/device-mapper are active')
    require(state['resolved'] == RAW and state['block_node'] == '1', 'userdata does not resolve to block sda19')
    require(int(state['logical_block_size']) == BLOCK, 'unexpected UFS logical block size')
    require(int(state['start_sectors']) * 512 == target['start_bytes'] and
            int(state['size_sectors']) * 512 == target['bytes'], 'sysfs userdata geometry differs from GPT')
    alternate = struct.unpack_from('<Q', primary, BLOCK + 32)[0]
    require(int(state['disk_sectors']) * 512 == (alternate+1)*BLOCK, 'disk size differs from GPT')
    require(state['readonly'] == '0', 'userdata block device is read-only; installer does not change that flag')


STATE_SCRIPT = r'''set -e
export PATH=/system/bin:/bin
field() { printf '%s\0' "$1"; shift; "$@"; printf '\0'; }
field uid id -u
field marker getprop ro.redfin.offline_recovery
field product getprop ro.product.device
if test "$(id -u)" != 0 || test "$(getprop ro.redfin.offline_recovery)" != 1 || test "$(getprop ro.product.device)" != redfin; then
    exit 0
fi
field resolved readlink -f /dev/block/by-name/userdata
field block_node sh -c 'test -b /dev/block/sda19 && echo 1'
field start_sectors cat /sys/class/block/sda19/start
field size_sectors cat /sys/class/block/sda19/size
field disk_sectors cat /sys/class/block/sda/size
field logical_block_size cat /sys/class/block/sda/queue/logical_block_size
field readonly cat /sys/class/block/sda19/ro
field holders ls /sys/class/block/sda19/holders
field dm sh -c 'for p in /sys/class/block/dm-*; do test -e "$p" || continue; basename "$p"; done'
field mountinfo cat /proc/self/mountinfo
field swaps cat /proc/swaps
field timer getprop init.svc.recovery-return
field uptime cat /proc/uptime
'''


class ADB:
    def __init__(self, serial=None):
        if serial is None:
            serial = subprocess.run(['adb', 'get-serialno'], check=True, capture_output=True, timeout=15).stdout.decode().strip()
        require(serial and serial != 'unknown' and not any(char.isspace() for char in serial), 'select one ADB device')
        self.serial = serial

    def command(self, script, timeout=30):
        command = ['adb', '-s', self.serial, 'shell', '-T', 'sh', '-s']
        try:
            result = subprocess.run(command, input=script.encode(), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError('ADB command timed out') from None
        require(result.returncode == 0, 'ADB read/control failed: ' + result.stderr.decode(errors='replace').replace(self.serial, '<device>')[:500])
        return result.stdout

    def state(self):
        fields = self.command(STATE_SCRIPT).decode().split('\0')
        require(fields.pop() == '' and len(fields) % 2 == 0, 'truncated recovery evidence')
        return {fields[i]: fields[i+1].strip() for i in range(0, len(fields), 2)}

    def gpt(self, disk_sectors):
        count = int(disk_sectors)*512//BLOCK
        primary = self.command(f'dd if=/dev/block/sda bs={BLOCK} count={PREFIX_BLOCKS} status=none')
        tail = self.command(f'dd if=/dev/block/sda bs={BLOCK} skip={count-PREFIX_BLOCKS} count={PREFIX_BLOCKS} status=none')
        require(len(primary) == PREFIX_BLOCKS*BLOCK, 'truncated primary GPT capture')
        return primary, tail

    def stop_timer(self):
        self.command('setprop ctl.stop recovery-return')
        for unused in range(20):
            if self.command('getprop init.svc.recovery-return').strip() == b'stopped':
                return
            time.sleep(0.1)
        raise ValueError('recovery-return did not stop; no disk write was started')

    def stream(self, image, expected):
        with image.open('rb') as source:
            item = os.fstat(source.fileno())
            require([item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns] == expected['stat'],
                    'image changed since validation; no disk write started')
            process = subprocess.Popen(['adb', '-s', self.serial, 'shell', '-T', 'dd',
                                        f'of={RAW}', f'bs={MIB}', f'count={IMAGE_BYTES}',
                                        'iflag=count_bytes', 'conv=fsync'],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            checksum, total = hashlib.sha256(), 0
            try:
                for chunk in iter(lambda: source.read(4*MIB), b''):
                    require(total + len(chunk) <= IMAGE_BYTES, 'image grew during streaming')
                    process.stdin.write(chunk)
                    checksum.update(chunk); total += len(chunk)
                process.stdin.close(); process.stdin = None
                output, error = process.communicate(timeout=3600)
            except BaseException as error:
                process.kill(); process.communicate()
                if isinstance(error, subprocess.TimeoutExpired):
                    raise ValueError('userdata streaming timed out; written data may be incomplete') from None
                raise
            require(process.returncode == 0 and total == IMAGE_BYTES,
                    'raw userdata write failed or was short; Android data may be partially overwritten')
            require(checksum.hexdigest() == expected['sha256'], 'image changed during streaming; written data needs repair')

    def readback(self):
        output = self.command(f'set -o pipefail; dd if={RAW} bs={MIB} count={IMAGE_BYTES} iflag=count_bytes status=none | sha256sum', timeout=3600)
        checksum = output.decode().split()[0]
        require(re.fullmatch('[0-9a-f]{64}', checksum), 'invalid full readback SHA256')
        return checksum


def evidence(adb, expected_primary, expected_target):
    state = adb.state()
    validate_state(state, expected_target, expected_primary)
    primary, tail = adb.gpt(state['disk_sectors'])
    require(fingerprint(primary) == fingerprint(expected_primary), 'device GPT differs from approved host capture')
    return state, primary, tail, backup_proof(primary, tail)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--build-manifest', type=Path, required=True)
    parser.add_argument('--expected-gpt', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--serial', help='ADB target; never stored in artifacts')
    parser.add_argument('--state-json', type=Path, help='offline evidence replay; cannot write')
    parser.add_argument('--erase-userdata', action='store_true', help='DESTROY Android user data; requires prior user consent')
    args = parser.parse_args(argv)
    if args.erase_userdata and args.state_json:
        parser.error('--state-json cannot be combined with --erase-userdata')
    report = {'success': False, 'mode': 'erase-userdata' if args.erase_userdata else 'check-only',
              'disk_write_started': False, 'timer_stopped': False}
    created = False
    try:
        require(not args.out.exists(), 'choose a fresh --out directory')
        args.out.mkdir(parents=True)
        created = True
        image = local_image(args.image, args.build_manifest)
        expected = args.expected_gpt.read_bytes()
        expected_proof, target = partition(expected)
        if args.state_json:
            saved = json.loads(args.state_json.read_text())
            state = saved['state']
            validate_state(state, target, expected)
            primary, tail = Path(saved['primary_path']).read_bytes(), Path(saved['backup_path']).read_bytes()
            require(fingerprint(primary) == expected_proof, 'saved GPT differs from approved host capture')
            backup = backup_proof(primary, tail)
            adb = None
        else:
            adb = ADB(args.serial)
            state, primary, tail, backup = evidence(adb, expected, target)
        report.update(image=image, target=target, gpt_before=expected_proof, backup_gpt_before=backup,
                      primary_capture_before_sha256=hashlib.sha256(primary).hexdigest(),
                      action={'node': RAW, 'offset': 0, 'bytes': IMAGE_BYTES,
                              'would_destroy_android_user_data': True,
                              'stop_timer_and_recheck_before_write': True,
                              'dd_arguments': [f'of={RAW}', f'bs={MIB}', f'count={IMAGE_BYTES}',
                                               'iflag=count_bytes', 'conv=fsync'],
                              'verify': 'full 16 GiB SHA256, primary GPT, and exact secondary header/tail preservation',
                              'other_partitions_written': False})
        (args.out/'gpt-before-primary.bin').write_bytes(primary)
        (args.out/'gpt-before-backup.bin').write_bytes(tail)
        atomic(args.out/'evidence.json', {'state': state, 'primary_path': str((args.out/'gpt-before-primary.bin').resolve()),
                                        'backup_path': str((args.out/'gpt-before-backup.bin').resolve())})
        if args.erase_userdata:
            # A full userdata backup can take much longer than the return
            # timer. Only its already-stopped live state permits that age.
            if state.get('timer') != 'stopped':
                require(0 <= float(state['uptime'].split()[0]) < 105,
                        'start installation in a fresh recovery (<105 s uptime), or stop its timer first')
                adb.stop_timer()
            report['timer_stopped'] = True
            state, primary, tail, current_backup = evidence(adb, expected, target)
            require(state['timer'] == 'stopped' and current_backup == backup, 'pre-write recovery/GPT changed')
            # No block-device mutation is possible above this point.
            report['disk_write_started'] = True
            atomic(args.out/'check.json', report)
            adb.stream(args.image, image)
            report['readback_sha256'] = adb.readback()
            require(report['readback_sha256'] == image['sha256'], 'full userdata readback SHA256 mismatch')
        report['success'] = True
    except (OSError, ValueError, KeyError, IndexError, UnicodeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    finally:
        if report['disk_write_started']:
            try:
                after, tail_after = adb.gpt(state['disk_sectors'])
                report['gpt_after'], unused = partition(after)
                report['backup_gpt_after'] = backup_proof(after, tail_after)
                report['primary_capture_after_sha256'] = hashlib.sha256(after).hexdigest()
                require(report['gpt_after'] == expected_proof and report['backup_gpt_after'] == backup,
                        'GPT changed during installation')
                require(report['primary_capture_after_sha256'] == report['primary_capture_before_sha256'],
                        'primary GPT capture bytes changed during installation')
                (args.out/'gpt-after-primary.bin').write_bytes(after)
                (args.out/'gpt-after-backup.bin').write_bytes(tail_after)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                report['success'] = False
                report['gpt_after_error'] = str(error)
        if created:
            atomic(args.out/'check.json', report)
    # Never print device identifiers or the full private build manifest.
    print(json.dumps({'success': report['success'], 'mode': report['mode'],
                      'disk_write_started': report['disk_write_started'],
                      'report': str(args.out/'check.json'), 'error': report.get('error')}, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
