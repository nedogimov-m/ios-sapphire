#!/usr/bin/env python3
"""Extract the observed RF-config module from the main bundle's modem snapshot.

The source is a bounded regular host file opened read-only. No device access,
mount, signature modification, firmware execution or partition write occurs.
The output is private firmware and must stay in an ignored directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from modem_fat import FAT
from wifi_firmware import read_regular, require

MODULE = 'image/modem_pr/so/549_38_0.mbn'
MAX_MODULE = 8 * 1024 * 1024


def source_plan(path, expected_bundle=None):
    data = read_regular(path, 1024 * 1024)
    plan = json.loads(data)
    require(type(plan) is dict and plan.get('schema') == 1 and
            plan.get('hardware_started') is False and plan.get('signature_authenticated') is False and
            all(type(plan.get(key)) is str and re.fullmatch('[0-9a-f]{64}', plan[key]) for key in
                ('source_image_sha256', 'bundle_sha256')) and
            (expected_bundle is None or plan['bundle_sha256'] == expected_bundle),
            'module requires the selected native firmware source plan')
    return plan, hashlib.sha256(data).hexdigest()


def extract(image, plan_path, destination):
    plan, plan_sha = source_plan(plan_path)
    destination = Path(destination)
    require(not destination.exists(), 'refusing to overwrite an existing private module output')
    fat = FAT(image)
    try:
        require(fat.image_hash() == plan['source_image_sha256'], 'modem source differs from the main firmware plan')
        first, selected = None, None
        for index, part in enumerate(MODULE.split('/')):
            matches = [entry for entry in fat.directory(first) if entry.name.casefold() == part.casefold()]
            require(len(matches) == 1, 'observed modem module path missing or ambiguous')
            selected = matches[0]
            require(selected.directory == (index < 3), 'observed modem module path has the wrong type')
            first = selected.cluster
        require(selected is not None and 52 <= selected.size <= MAX_MODULE, 'observed modem module exceeds its source bound')
        data = b''.join(fat.chunks(selected))
        require(len(data) == selected.size and data[:7] == b'\x7fELF\1\1\1' and
                int.from_bytes(data[18:20], 'little') == 164 and fat.unchanged(),
                'observed module is not an unchanged native Hexagon ELF')
        destination.mkdir(parents=True, mode=0o700)
        name = MODULE.rsplit('/', 1)[-1]
        record = {'schema': 1, 'path': MODULE, 'private_file': name, 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), 'source_image_sha256': plan['source_image_sha256'],
            'source_plan_sha256': plan_sha, 'bundle_sha256': plan['bundle_sha256'], 'source_unchanged': True}
        for path, value in ((destination / name, data), (destination / 'inventory.json',
                            (json.dumps(record, indent=2) + '\n').encode())):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(value); output.flush(); os.fsync(output.fileno())
        return record
    finally:
        fat.close()


def load(manifest, plan_path, expected_bundle):
    manifest = Path(manifest).resolve()
    plan, plan_sha = source_plan(plan_path, expected_bundle)
    item = json.loads(read_regular(manifest, 1024 * 1024))
    require(type(item) is dict and item.get('schema') == 1 and item.get('path') == MODULE and
            item.get('source_plan_sha256') == plan_sha and item.get('source_image_sha256') == plan['source_image_sha256'] and
            item.get('bundle_sha256') == expected_bundle and item.get('source_unchanged') is True and
            item.get('private_file') == MODULE.rsplit('/', 1)[-1], 'module provenance differs from the selected main firmware')
    data = read_regular(manifest.parent / item['private_file'], MAX_MODULE)
    digest = hashlib.sha256(data).hexdigest()
    require(52 <= len(data) <= MAX_MODULE and len(data) == item.get('bytes') and digest == item.get('sha256') and data[:7] == b'\x7fELF\1\1\1' and
            int.from_bytes(data[18:20], 'little') == 164, 'module bytes differ from their read-only source')
    return (MODULE, data, bytes.fromhex(digest)), {'path': MODULE, 'bytes': len(data), 'sha256': digest,
        'source_image_sha256': plan['source_image_sha256'], 'source_plan_sha256': plan_sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        record = extract(args.image, args.plan, args.out)
        print('Observed modem module extracted read-only: %u bytes, source and plan hashes verified.' % record['bytes'])
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
