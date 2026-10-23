#!/usr/bin/env python3
"""Capture four Redfin EFS partitions read-only through offline recovery.

Every source must match its GPT label, by-name link, size and the saved LUN
GPT hashes. Two independent reads must agree. Outputs contain device secrets
and belong only in an ignored, private directory. No mount or disk write is
performed; recovery returns to the verified hardware bootloader.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
from types import SimpleNamespace

import gpt

HERE = Path(__file__).resolve().parent
PARTITIONS = {'modemst1': '/boot/modem_fs1', 'modemst2': '/boot/modem_fs2',
              'fsg': '/boot/modem_fsg', 'fsc': '/boot/modem_fsc'}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def gpt_partition(prefix, label, number):
    proof = gpt.fingerprint(prefix)
    lba, count, width = struct.unpack_from('<QII', prefix, 4096 + 72)
    matches = []
    for index in range(count):
        entry = prefix[lba * 4096 + index * width:lba * 4096 + (index + 1) * width]
        if any(entry[:16]) and entry[56:128].decode('utf-16le').split('\0', 1)[0] == label:
            first, last = struct.unpack_from('<QQ', entry, 32)
            matches.append((index + 1, (last - first + 1) * 4096))
    require(len(matches) == 1 and matches[0][0] == number, 'EFS GPT/by-name identity mismatch')
    length = matches[0][1]
    require(4096 <= length <= 4 * 1024 * 1024 and not length % 4096, 'EFS partition exceeds capture bounds')
    return length, proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-image', required=True, type=Path)
    parser.add_argument('--gpt-sha256-file', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('rmtfs_cycle', HERE / 'boot-cycle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.recovery_proof(args.recovery_image)
    expected = {}
    for disk, sectors, block, head, tail in re.findall(
            r'(sd[a-f]) sectors512=(\d+) logical_block=(\d+)\nhead64K ([0-9a-f]{64})  -\ntail64K ([0-9a-f]{64})  -',
            args.gpt_sha256_file.read_text()):
        require(disk not in expected and block == '4096', 'invalid saved LUN proof')
        expected[disk] = (int(sectors) * 512, head, tail)
    require(set(expected) == {'sda', 'sdb', 'sdc', 'sdd', 'sde', 'sdf'}, 'missing saved LUN GPT proofs')
    require(not args.out.exists(), 'refusing to overwrite an existing snapshot')
    args.out.mkdir(parents=True, mode=0o700)
    cycle = module.Cycle(SimpleNamespace(out=args.out, serial=None, recovery_image=args.recovery_image,
        from_bootloader=True, leave_bootloader=True, timeout=120))
    report = {'schema': 1, 'status': 'incomplete', 'device': 'redfin', 'disk_writes': False,
              'source': 'verified-offline-recovery', 'files': []}

    def read(command, length):
        code, data, _ = cycle.call('adb', ['exec-out', *command], timeout=30)
        require(code == 0 and len(data) == length, 'bounded EFS/GPT read failed or truncated')
        return data

    def disk_proof(disk):
        size, head, tail = expected[disk]
        require(read(['blockdev', '--getsize64', '/dev/block/' + disk], len(str(size)) + 1).strip() ==
                str(size).encode(), 'LUN size differs from saved GPT proof')
        prefix = read(['dd', 'if=/dev/block/' + disk, 'bs=4096', 'count=34', 'status=none'], 34 * 4096)
        end = read(['dd', 'if=/dev/block/' + disk, 'bs=4096', 'skip=' + str(size // 4096 - 16),
                    'count=16', 'status=none'], 65536)
        require(hashlib.sha256(prefix[:65536]).hexdigest() == head and hashlib.sha256(end).hexdigest() == tail,
                'LUN GPT hashes differ from the saved pre-install proof')
        return prefix

    try:
        require(cycle.wait_fastboot(), 'verified redfin fastboot unavailable')
        cycle.enter_recovery()
        cycle.verify_recovery()
        sources, proofs = {}, {}
        for label in PARTITIONS:
            code, path, _ = cycle.adb('exec-out', 'readlink', '-f', '/dev/block/by-name/' + label)
            match = re.fullmatch(rb'/dev/block/(sd[a-f])(\d+)\n', path)
            require(code == 0 and match, 'EFS by-name link is not a bounded UFS partition')
            disk, number = match[1].decode(), int(match[2])
            if disk not in proofs:
                proofs[disk] = disk_proof(disk)
            length, proof = gpt_partition(proofs[disk], label, number)
            device = path.strip().decode()
            code, size, _ = cycle.adb('exec-out', 'blockdev', '--getsize64', device)
            require(code == 0 and size.strip() == str(length).encode(), 'EFS block size differs from GPT')
            sources[label] = (device, length, proof)
        require(sum(row[1] for row in sources.values()) <= 12 * 1024 * 1024, 'total EFS snapshot exceeds RAM bound')
        for label, (device, length, proof) in sources.items():
            command = ['dd', 'if=' + device, 'bs=4096', 'count=' + str(length // 4096), 'status=none']
            first, second = read(command, length), read(command, length)
            require(first == second, 'independent EFS reads disagree')
            cycle.save(label + '.img', first, private=True)
            report['files'].append({'path': PARTITIONS[label], 'partition': label, 'private_file': label + '.img',
                'bytes': length, 'sha256': hashlib.sha256(first).hexdigest(), 'gpt': proof,
                'independent_reads_match': True})
        cycle.verify_recovery_storage()
        for disk, before in proofs.items():
            require(disk_proof(disk) == before, 'GPT changed during read-only capture')
        report['status'] = 'verified-read-only-rmtfs-snapshot'
    finally:
        try:
            if cycle.recovery_verified:
                cycle.leave_bootloader()
                report['left_in_bootloader'] = True
        finally:
            module.atomic(args.out / 'inventory.json', (json.dumps(report, indent=2) + '\n').encode(), mode=0o600)
            module.atomic(args.out / 'capture.json', (json.dumps(cycle.manifest, indent=2) + '\n').encode(), mode=0o600)
    print('Four EFS snapshots verified; no disk writes; verified bootloader return.')


if __name__ == '__main__':
    main()
