"""Read actual current-boot native pixel proof and selected GPU output route."""
import json
from pathlib import Path
import re


def analyze(lines):
    checks=[];presents=[];invalid=[]
    for line in lines:
        if 'REDFIN GPU DIRECT CHECK:' in line:
            keys=('ABI','cases','pixels','mismatches','guard-errors','stage-writes','completed','tolerance')
            fields=dict(re.findall(r'([A-Za-z][A-Za-z-]*)=([^\s]+)',line))
            try:checks.append({k:int(fields[k]) for k in keys})
            except (KeyError,ValueError):invalid.append('malformed-native-direct-check')
        if 'REDFIN GPU DIRECT PRESENT:' in line:
            keys=('n','direct','staged','ABI','full-image-only','CPU-pixel-copy')
            fields=dict(re.findall(r'([A-Za-z][A-Za-z-]*)=([^\s]+)',line))
            try:presents.append({k:int(fields[k]) for k in keys})
            except (KeyError,ValueError):invalid.append('malformed-direct-present')
    native=bool(len(checks)==1 and checks[0]==dict(ABI=1,cases=4,pixels=4*1080*2340,
        mismatches=0,**{'guard-errors':0,'stage-writes':0,'completed':1,'tolerance':1}))
    previous=0
    for row in presents:
        if row['n']<=previous or row['n']!=row['direct']+row['staged'] or row['ABI']!=1 or \
                row['CPU-pixel-copy'] or row['full-image-only']!=1 or min(row.values())<0:
            invalid.append('invalid-direct-present-counter')
        previous=row['n']
    direct=max((r['direct'] for r in presents),default=0)
    return dict(native_full_image_direct_pixels_and_guards_pass=native,
        actual_direct_output_present_records=len(presents),actual_direct_output_frames=direct,
        staged_output_frames=max((r['staged'] for r in presents),default=0),
        actual_direct_GPU_output=bool(native and direct>=60 and not invalid),
        invalid_records=invalid,full_native_direct_check=checks)


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('cycle',type=Path)
    a=p.parse_args();root=a.cycle;m=json.loads((root/'manifest.json').read_text())
    fresh=m.get('log_freshness',{});presentation=json.loads((root/'presentation-summary.json').read_text())
    authenticated=bool(presentation.get('authenticated_clean_runtime') and
        fresh.get('status')=='boot-id-matched' and fresh.get('capture_authenticated'))
    report=analyze((root/'xnu-console.txt').read_text(errors='replace').splitlines())
    report.update(cycle=str(root),boot=fresh.get('expected_boot_id'),authenticated_clean_runtime=authenticated,
        complete_native_and_actual_direct_output_proof=bool(authenticated and report['actual_direct_GPU_output']))
    (root/'direct-output-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
