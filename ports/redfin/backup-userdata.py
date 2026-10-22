#!/usr/bin/env python3
"""Read-only, verified full Redfin userdata + encryption-metadata backup.

Requires the offline recovery return timer to be stopped already. Never writes
device storage, changes properties, or reboots. Incomplete images retain .partial.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

SPEC = importlib.util.spec_from_file_location('redfin_install', Path(__file__).with_name('install-root.py'))
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)
require = INSTALL.require
METADATA = '/dev/block/sda15'
CHUNK = 4 * 1024**2
TIMEOUT = 7200

STATE_SCRIPT = INSTALL.STATE_SCRIPT + r'''
field return_target getprop ro.redfin.return_target
field metadata_resolved readlink -f /dev/block/by-name/metadata
field metadata_block_node sh -c 'test -b /dev/block/sda15 && echo 1'
field metadata_start_sectors cat /sys/class/block/sda15/start
field metadata_size_sectors cat /sys/class/block/sda15/size
field metadata_holders ls /sys/class/block/sda15/holders
field metadata_readonly cat /sys/class/block/sda15/ro
'''


def durable(stream):
    stream.flush()
    os.fsync(stream.fileno())
    if sys.platform == 'darwin':
        fcntl.fcntl(stream.fileno(), getattr(fcntl, 'F_FULLFSYNC', 51))


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        durable(stream)


def save_report(out, report):
    temporary = out / 'backup.json.new'
    temporary.unlink(missing_ok=True)
    private_write(temporary, (json.dumps(report, indent=2) + '\n').encode())
    temporary.replace(out / 'backup.json')
    fd = os.open(out, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def metadata_partition(primary):
    INSTALL.fingerprint(primary, INSTALL.BLOCK)
    lba, count, size = struct.unpack_from('<QII', primary, INSTALL.BLOCK + 72)
    matches = []
    for index in range(count):
        item = primary[lba*INSTALL.BLOCK + index*size:lba*INSTALL.BLOCK + (index+1)*size]
        if any(item[:16]) and item[56:128].decode('utf-16le').split('\0')[0] == 'metadata':
            begin, end = struct.unpack_from('<QQ', item, 32)
            matches.append({'index': index + 1, 'start_bytes': begin*INSTALL.BLOCK,
                            'bytes': (end-begin+1)*INSTALL.BLOCK, 'node': METADATA})
    require(len(matches) == 1 and matches[0]['index'] == 15, 'expected exactly metadata GPT entry 15')
    return matches[0]


def validate_state(state, target, metadata, primary):
    # Backups accept read-only block nodes; the installation validator requires
    # a writable node only because it is also used before installation.
    require(state.get('readonly') in ('0', '1'), 'invalid userdata read-only state')
    INSTALL.validate_state({**state, 'readonly': '0'}, target, primary)
    require(state.get('return_target') == 'bootloader', 'recovery must return to bootloader')
    require(state.get('timer') == 'stopped', 'stop the verified recovery-return timer before backup')
    require(state.get('metadata_resolved') == METADATA and state.get('metadata_block_node') == '1',
            'metadata does not resolve to block sda15')
    require(state.get('metadata_readonly') in ('0', '1') and not state.get('metadata_holders', 'missing').strip(),
            'metadata holders or invalid block state')
    require(int(state['metadata_start_sectors'])*512 == metadata['start_bytes'] and
            int(state['metadata_size_sectors'])*512 == metadata['bytes'],
            'sysfs metadata geometry differs from GPT')


def bounded_read_script(node, size, hashed=False):
    require(node in (INSTALL.RAW, METADATA) and type(size) is int and size > 0,
            'invalid bounded backup source')
    prefix = 'set -e\nexport PATH=/system/bin:/bin\n'
    read = f'dd if={node} bs={CHUNK} count={size} iflag=count_bytes status=none'
    return prefix + ('set -o pipefail\n' + read + ' | sha256sum\n' if hashed else read + '\n')


def file_hash(path, expected):
    digest, total, started = hashlib.sha256(), 0, time.monotonic()
    last_progress = started
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            now = time.monotonic()
            require(now-started < TIMEOUT, 'host backup hashing timed out')
            digest.update(chunk)
            total += len(chunk)
            if now-last_progress >= 60:
                print(f'{path.name}: host SHA256 {total*100/expected:.1f}% {now-started:.0f}s', flush=True)
                last_progress = now
    require(total == expected, 'saved backup file has an incorrect length')
    return digest.hexdigest()


class ADB(INSTALL.ADB):
    def state(self):
        fields = self.command(STATE_SCRIPT).decode().split('\0')
        require(fields.pop() == '' and len(fields) % 2 == 0, 'truncated recovery evidence')
        return {fields[i]: fields[i+1].strip() for i in range(0, len(fields), 2)}

    def device_hash(self, node, size):
        done, started = threading.Event(), time.monotonic()
        def progress():
            while not done.wait(60):
                print(f'{Path(node).name}: independent device SHA256 {time.monotonic()-started:.0f}s', flush=True)
        worker = threading.Thread(target=progress, daemon=True)
        worker.start()
        try:
            output = self.command(bounded_read_script(node, size, hashed=True), timeout=TIMEOUT)
        finally:
            done.set()
            worker.join()
        require(re.fullmatch(rb'[0-9a-f]{64}\s+(?:-|/dev/stdin)\s*', output) is not None,
                'invalid independent device SHA256 output')
        return output.split()[0].decode()

    def stream(self, node, size, destination, label):
        script = bounded_read_script(node, size).encode()
        started, last_progress, last_percent = time.monotonic(), 0, -5
        digest, total = hashlib.sha256(), 0
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(['adb', '-s', self.serial, 'shell', '-T', 'sh', '-s'],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
            try:
                process.stdin.write(script)
                process.stdin.close()
                process.stdin = None
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        now = time.monotonic()
                        require(now-started < TIMEOUT, 'backup streaming timed out')
                        events = selector.select(timeout=1)
                        if events:
                            chunk = os.read(process.stdout.fileno(), CHUNK)
                            if not chunk:
                                break
                            require(total + len(chunk) <= size, 'backup stream exceeds validated partition size')
                            output.write(chunk)
                            digest.update(chunk)
                            total += len(chunk)
                        percent = total*100/size
                        if percent-last_percent >= 5 or now-last_progress >= 60:
                            elapsed = max(now-started, 0.001)
                            print(f'{label}: {percent:.1f}% {total/1024**3:.2f} GiB '
                                  f'{total/1024**2/elapsed:.1f} MiB/s {elapsed:.0f}s', flush=True)
                            last_progress, last_percent = now, percent
                process.wait(timeout=max(1, TIMEOUT-(time.monotonic()-started)))
                errors.seek(0)
                error = errors.read(1000).decode(errors='replace').replace(self.serial, '<device>')
                require(process.returncode == 0, 'device backup read failed: ' + error)
                require(total == size, 'backup stream was shorter than validated partition size')
                durable(output)
            except BaseException:
                process.kill()
                process.wait()
                raise
            finally:
                process.stdout.close()
        return {'bytes': total, 'stream_sha256': digest.hexdigest(),
                'seconds': round(time.monotonic()-started, 2)}


def snapshot(adb, expected, target, metadata):
    state = adb.state()
    validate_state(state, target, metadata, expected)
    primary, tail = adb.gpt(state['disk_sectors'])
    require(INSTALL.fingerprint(primary) == INSTALL.fingerprint(expected), 'GPT differs from expected capture')
    return state, primary, tail, INSTALL.backup_proof(primary, tail)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial')
    parser.add_argument('--expected-gpt', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    report = {'success': False, 'mode': 'read-only-full-backup', 'device_writes': False, 'images': {}}
    adb, created = None, False
    try:
        args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
        created = True
        os.chmod(args.out, 0o700)
        expected = args.expected_gpt.read_bytes()
        gpt, target = INSTALL.partition(expected)
        metadata = metadata_partition(expected)
        report.update(gpt=gpt, userdata=target, metadata=metadata)
        required = target['bytes'] + metadata['bytes'] + 128*1024**2
        require(shutil.disk_usage(args.out).free >= required, 'insufficient host disk space for full backup')
        adb = ADB(args.serial)
        before, primary, tail, proof = snapshot(adb, expected, target, metadata)
        report['before'] = before
        report['secondary_gpt_before'] = proof
        private_write(args.out / 'primary-before.bin', primary)
        private_write(args.out / 'tail-before.bin', tail)
        save_report(args.out, report)
        for name, source in (('metadata', metadata), ('userdata', target)):
            state, current, current_tail, current_proof = snapshot(adb, expected, target, metadata)
            require(current_tail == tail, 'secondary GPT changed before backup')
            partial = args.out / (name + '.img.partial')
            print(f'{name}: reading {source["bytes"]} bytes', flush=True)
            result = adb.stream(source['node'], source['bytes'], partial, name)
            report['images'][name] = {**result, 'status': 'verifying', 'file': partial.name}
            save_report(args.out, report)
            print(f'{name}: verifying saved file and independent device SHA256', flush=True)
            checksum = file_hash(partial, source['bytes'])
            require(checksum == result['stream_sha256'], 'host file SHA256 differs from received bytes')
            independent = adb.device_hash(source['node'], source['bytes'])
            require(checksum == independent, 'host/device backup SHA256 mismatch')
            state, current, current_tail, current_proof = snapshot(adb, expected, target, metadata)
            require(current_tail == tail, 'secondary GPT changed during backup')
            final = args.out / (name + '.img')
            partial.replace(final)
            report['images'][name].update(status='verified', file=final.name,
                                         sha256=checksum, device_sha256=independent)
            save_report(args.out, report)
        after, final_primary, final_tail, final_proof = snapshot(adb, expected, target, metadata)
        require(final_tail == tail, 'secondary GPT changed after backup')
        private_write(args.out / 'primary-after.bin', final_primary)
        private_write(args.out / 'tail-after.bin', final_tail)
        report.update(success=True, after=after, secondary_gpt_after=final_proof)
        save_report(args.out, report)
        print('backup verified: ' + str(args.out / 'backup.json'), flush=True)
        return 0
    except (OSError, ValueError, KeyError, UnicodeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        message = str(error) or type(error).__name__
        if adb is not None:
            message = message.replace(adb.serial, '<device>')
        report['error'] = message
        report['success'] = False
        if created:
            try:
                save_report(args.out, report)
            except OSError:
                pass
        print('backup failed: ' + message, file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
