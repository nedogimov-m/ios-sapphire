"""Validate complete sampled native host scopes; these are not GPU timestamps."""
from pathlib import Path
import argparse
import json
import re
import statistics

OWNER_PARTS = ('admission-queue-us', 'hardware-lock-us', 'owner-execute-us',
               'hardware-release-us', 'client-retire-us', 'queue-retire-us')
OUTPUT_PARTS = ('prepare-us', 'source-sync-us', 'command-build-us',
                'command-sync-us', 'native-submit-wait-us', 'readback-us')


def metric(values):
    return dict(samples=len(values), minimum=min(values),
                median=statistics.median(values), maximum=max(values)) if values else None


def partition(raw, names):
    values = [int(v) for v in raw.split(',')]
    if len(values) != len(names)+1 or any(v < 0 or v >= 2**64 for v in values):
        raise ValueError('missing or out-of-range scope')
    # Each adjacent nanosecond scope is independently truncated to us. The
    # complete total may therefore exceed their sum by at most n-1us.
    if not 0 <= values[-1]-sum(values[:-1]) < len(names):
        raise ValueError('scope sum differs from the complete total')
    return dict(zip((*names, 'total-us'), values))


def analyze(text):
    owners, identities, outputs, invalid = {}, {}, {}, []
    formats = (
        ('REDFIN GPU OWNER: ', re.compile(
            r's=(\d+) k=([RP]) r=([0-9a-f]+) us=([0-9,]+) host=1')),
        ('REDFIN GPU OWNER ID: ', re.compile(
            r's=(\d+) name=(\S{1,19}) pid=(\d+) cf=(\d+) pf=(\d+)')),
        ('REDFIN GPU OUTPUT: ', re.compile(
            r'f=(\d+) n=(\d+) clear=(\d+) us=([0-9,]+) scope=1')),
    )
    for line in text.splitlines():
        for index, (prefix, pattern) in enumerate(formats):
            if prefix not in line:
                continue
            record = line[line.index(prefix)+len(prefix):].strip()
            try:
                match = pattern.fullmatch(record)
                if not match:
                    raise ValueError('incomplete or malformed record')
                fields = match.groups()
                key = int(fields[0])
                table = (owners, identities, outputs)[index]
                if not 0 < key < 2**64 or key in table:
                    raise ValueError('invalid or duplicate record key')
                if index == 0:
                    result = int(fields[2], 16)
                    if result >= 2**32:
                        raise ValueError('invalid result')
                    table[key] = dict(sequence=key, kind={'R': 'render', 'P': 'present'}[fields[1]],
                                      result=result, **partition(fields[3], OWNER_PARTS))
                elif index == 1:
                    pid, client, physical = map(int, fields[2:])
                    if pid >= 2**31 or max(client, physical) >= 2**32:
                        raise ValueError('invalid native identity')
                    table[key] = dict(process=fields[1], pid=pid,
                                      client_fence=client, physical_fence=physical)
                else:
                    count, cleared = map(int, fields[1:3])
                    if not 1 <= count <= 4 or not 0 <= cleared <= 1080*2340:
                        raise ValueError('invalid output geometry')
                    table[key] = dict(frame=key, layers=count, cleared_pixels=cleared,
                                      **partition(fields[3], OUTPUT_PARTS))
            except ValueError as error:
                invalid.append(dict(reason=str(error), line=line))
            break
    for key in sorted(owners.keys() | identities.keys()):
        if key not in owners or key not in identities:
            invalid.append(dict(reason='unpaired owner timing/identity', sequence=key))
            continue
        owners[key].update(identities[key])
        row = owners[key]
        if row['kind'] == 'present' and (row['process'] != 'kernel' or row['pid'] or row['client_fence']):
            invalid.append(dict(reason='inconsistent internal owner identity', sequence=key))
    owner_rows, output_rows = list(owners.values()), list(outputs.values())
    summary = {}
    for kind in ('render', 'present'):
        selected = [r for r in owner_rows if r['kind'] == kind and not r['result']]
        summary[kind] = {name: metric([r[name] for r in selected])
                         for name in (*OWNER_PARTS, 'total-us')}
    summary['output'] = {name: metric([r[name] for r in output_rows])
                         for name in (*OUTPUT_PARTS, 'total-us')}
    return dict(valid=bool(owners and outputs) and not invalid, sampled_only=True,
                gpu_execution_time_isolated=False,
                scope='adjacent host intervals, including native CPU programming and real GPU waits',
                owner_samples=len(owners), output_samples=len(outputs),
                invalid=invalid, summary=summary, owner_rows=owner_rows, output_rows=output_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('console', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.console.read_text(errors='replace'))
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if not k.endswith('_rows')}, indent=2))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
