"""Read nonce-bound actual renderer activity, independently of a requested policy."""
import re


def analyze(lines,boot):
    if not re.fullmatch('[0-9a-f]{16}',boot):
        raise ValueError('exact actual boot identity required')
    frames=[];hardware=[];requested=[];declined=[];metal=[]
    for line in lines:
        if 'boot='+boot not in line:continue
        if 'REDFIN COMPOSITOR:' in line and 'process=backboardd' in line:
            if 'requested=gles' in line:requested.append(line)
            if 'Metal-device-declined=1' in line:declined.append(line)
        if 'REDFIN EAGL ABI:' in line and 'renderer=' in line:hardware.append(line)
        if 'REDFIN EAGL FRAME:' in line:
            fields=dict(re.findall(r'([a-z][a-z-]*)=([^\s]+)',line))
            try:row={k:int(fields[k]) for k in ('pid','frame','draws','triangles','shared','copied','errors')}
            except (KeyError,ValueError):continue
            frames.append(row)
        if re.search(r'redwoodmetal\[backboardd \d+\]: REDFIN METAL FENCE:',line):metal.append(line)
    native=bool(hardware and all('620' in line and not any(x in line.lower() for x in
        ('softpipe','llvmpipe','software')) for line in hardware))
    return dict(boot=boot,requested_GLES=bool(requested),Metal_decline_observed=bool(declined),
        native_GLES_hardware=native,GLES_frame_records=len(frames),
        maximum_GLES_frame=max((r['frame'] for r in frames),default=0),
        shared_surface_frames=sum(r['shared']>0 for r in frames),
        CPU_copy_frame_records=sum(r['copied']>0 for r in frames),
        GLES_errors=max((r['errors'] for r in frames),default=None),
        actual_backboardd_Metal_records=len(metal),
        actual_GLES_composition=bool(requested and native and frames and
            max(r['frame'] for r in frames)>=60 and any(r['shared'] for r in frames) and
            not any(r['errors'] for r in frames) and not metal),
        app_Metal_proved_by_this_log=False,frames=frames)


def main():
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cycle',type=Path)
    args=parser.parse_args();root=args.cycle
    manifest=json.loads((root/'manifest.json').read_text())
    presentation=json.loads((root/'presentation-summary.json').read_text())
    fresh=manifest.get('log_freshness',{});boot=fresh.get('expected_boot_id','')
    report=analyze((root/'userspace-eagl.log').read_text(errors='replace').splitlines(),boot)
    native=presentation.get('native_correctness',{})
    authenticated=bool(presentation.get('authenticated_clean_runtime') and
        fresh.get('status')=='boot-id-matched' and fresh.get('capture_authenticated'))
    app_metal=bool(authenticated and native.get('metal_exit_result')==0)
    gpu=bool(authenticated and (native.get('gpu') or {}).get('result')=='0')
    report.update(cycle=str(root),authenticated_clean_runtime=authenticated,
        app_Metal_full_native_contract_pass=app_metal,offscreen_GPU_contract_pass=gpu,
        complete_GLES_GUI_and_app_Metal_proof=bool(authenticated and
            report['actual_GLES_composition'] and app_metal and gpu))
    (root/'compositor-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='frames'},indent=2))


if __name__=='__main__':main()
