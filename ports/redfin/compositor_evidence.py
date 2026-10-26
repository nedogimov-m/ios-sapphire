"""Read nonce-bound actual renderer activity, independently of a requested policy."""
import re


def native_direct_check(lines,boot,mode=None):
    rows=[];modes=[]
    for line in lines:
        if 'REDFIN GLES DIRECT CHECK:' not in line or 'boot='+boot not in line:continue
        fields=dict(re.findall(r'([A-Za-z][A-Za-z-]*)=([^\s]+)',line))
        if mode is not None and fields.get('mode')!=mode:continue
        modes.append(fields.get('mode'))
        try:rows.append({k:int(fields[k]) for k in ('width','height','pitch','rounds','pixels',
            'tail-guard-bytes','fetch','seed-progress','CPU-lock-first','result')})
        except (KeyError,ValueError):return False
    wanted=dict(width=1125,height=2435,pitch=4608,rounds=4,
        pixels=1125*2435*4,**{'tail-guard-bytes':57344,'fetch':1,'seed-progress':1,'CPU-lock-first':1,'result':0})
    return bool((len(rows)==1 or mode is None and len(rows)==2 and set(modes)=={'gmem','sysmem'}) and
        all(row==wanted for row in rows))


def native_budget_check(lines,boot,mode=None):
    rows=[];modes=[]
    for line in lines:
        if 'REDFIN GLES BUDGET CHECK:' not in line or 'boot='+boot not in line:continue
        fields=dict(re.findall(r'([A-Za-z][A-Za-z-]*)=([^\s]+)',line))
        if mode is not None and fields.get('mode')!=mode:continue
        modes.append(fields.get('mode'))
        try:rows.append({k:int(fields[k]) for k in ('bound','rounds','maximum','waits','pixels',
            'tail-guard-bytes','real-GL-fences','CPU-pixels','result')})
        except (KeyError,ValueError):return False
    wanted=dict(bound=2,rounds=12,maximum=2,waits=11,
        pixels=80*61*12,**{'tail-guard-bytes':147456,'real-GL-fences':1,'CPU-pixels':1,'result':0})
    return bool((len(rows)==1 or mode is None and len(rows)==2 and set(modes)=={'gmem','sysmem'}) and
        all(row==wanted for row in rows))


def native_mode_checks(lines,boot):
    results=[]
    for line in lines:
        if 'REDFIN GLES MODE RESULT:' not in line or 'boot='+boot not in line:continue
        fields=dict(re.findall(r'([A-Za-z][A-Za-z-]*)=([^\s]+)',line))
        try:results.append((fields['mode'],int(fields['result']),int(fields['hardware'])))
        except (KeyError,ValueError):return False
    return bool(sorted(results)==[('gmem',0,1),('sysmem',0,1)] and
        all(native_direct_check(lines,boot,mode) and native_budget_check(lines,boot,mode)
            for mode in ('gmem','sysmem')))


def analyze(lines,boot):
    if not re.fullmatch('[0-9a-f]{16}',boot):
        raise ValueError('exact actual boot identity required')
    frames=[];hardware=[];requested=[];declined=[];metal=[];publications=[];driver_waits=[];direct=[];budgets=[];sysmem=[]
    for line in lines:
        if 'boot='+boot not in line:continue
        if 'REDFIN EAGL MEMORY:' in line and 'mode=sysmem hardware-GPU=1' in line:sysmem.append(line)
        if 'REDFIN COMPOSITOR:' in line and 'process=backboardd' in line:
            if 'requested=gles' in line:requested.append(line)
            if 'Metal-device-declined=1' in line:declined.append(line)
        if 'REDFIN EAGL ABI:' in line and 'renderer=' in line:hardware.append(line)
        if 'REDFIN EAGL FRAME:' in line:
            fields=dict(re.findall(r'([a-z][a-z-]*)=([^\s]+)',line))
            try:row={k:int(fields[k]) for k in ('pid','frame','draws','triangles','shared','copied','errors')}
            except (KeyError,ValueError):continue
            frames.append(row)
        if 'REDFIN EAGL PRESENT:' in line and 'driver-waits=1' in line:driver_waits.append(line)
        if 'REDFIN EAGL PUBLISH:' in line:
            fields=dict(re.findall(r'([a-zA-Z][a-zA-Z-]*)=([^\s]+)',line))
            try:publications.append({k:int(fields[k]) for k in ('pid','published','fallbacks','result','GPU-wait')})
            except (KeyError,ValueError):pass
        if 'REDFIN EAGL DIRECT FRAME:' in line:
            fields=dict(re.findall(r'([a-zA-Z][a-zA-Z-]*)=([^\s]+)',line))
            try:direct.append({k:int(fields[k]) for k in ('pid','frame','direct','mirrored','producer-notified')})
            except (KeyError,ValueError):pass
        if 'REDFIN EAGL BUDGET:' in line:
            fields=dict(re.findall(r'([a-zA-Z][a-zA-Z-]*)=([^\s]+)',line))
            try:budgets.append({k:int(fields[k]) for k in ('pid','frame','bound','pending','maximum',
                'waits','already','completed','fallbacks','real-GL-fences')})
            except (KeyError,ValueError):budgets.append({'invalid':True})
        if re.search(r'redwoodmetal\[backboardd \d+\]: REDFIN METAL FENCE:',line):metal.append(line)
    native=bool(hardware and all('620' in line and not any(x in line.lower() for x in
        ('softpipe','llvmpipe','software')) for line in hardware))
    return dict(boot=boot,requested_GLES=bool(requested),Metal_decline_observed=bool(declined),
        native_GLES_hardware=native,GLES_frame_records=len(frames),
        scoped_sysmem_GPU_policy_observed=bool(sysmem and native),
        maximum_GLES_frame=max((r['frame'] for r in frames),default=0),
        shared_surface_frames=sum(r['shared']>0 for r in frames),
        CPU_copy_frame_records=sum(r['copied']>0 for r in frames),
        GLES_errors=max((r['errors'] for r in frames),default=None),
        actual_backboardd_Metal_records=len(metal),
        driver_waits_for_GPU=bool(driver_waits),publication_records=len(publications),
        kernel_published_GLES_frames=max((r['published'] for r in publications),default=0),
        publication_fallbacks=max((r['fallbacks'] for r in publications),default=0),
        bounded_frame_records=len(budgets),
        real_GLES_frame_budget=bool(budgets and not any(r.get('invalid') for r in budgets) and
            all(r['bound']==2 and 0<=r['pending']<=r['maximum']<=2 and not r['fallbacks'] and
                r['real-GL-fences']==1 and r['waits']==r['already']+r['completed'] for r in budgets) and
            any(r.get('frame',0)>=60 and r.get('maximum')==2 and r.get('waits',0)>0 for r in budgets)),
        direct_surface_frame_records=sum(r['direct']>0 for r in direct),
        direct_surface_latest_frame=max((r['frame'] for r in direct if r['direct']),default=0),
        direct_surface_GPU_composition=bool(native and requested and frames and direct and
            max((r['frame'] for r in direct if r['direct']),default=0)>=60 and
            not any(r['direct'] and (r['mirrored'] or not r['producer-notified']) for r in direct) and
            not any(r['errors'] for r in frames)),
        asynchronous_GLES_handoff=bool(driver_waits and publications and
            max(r['published'] for r in publications)>=60 and
            not any(r['fallbacks'] or r['result'] or r['GPU-wait'] for r in publications)),
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
    kernel=(root/'xnu-console.txt').read_text(errors='replace')
    direct_native=native_direct_check((root/'userspace-gpu-render.log').read_text(errors='replace').splitlines(),boot)
    budget_native=native_budget_check((root/'userspace-gpu-render.log').read_text(errors='replace').splitlines(),boot)
    dual_modes=native_mode_checks((root/'userspace-gpu-render.log').read_text(errors='replace').splitlines(),boot)
    producer_lines=re.findall(r'^REDFIN GPU SURFACE PRODUCER: n=(\d+) surface=(\d+) cf=(\d+) issued=(\d+) seed=(\d+) seed-only=1 completion=0\s*$',kernel,re.M)
    producers=[tuple(map(int,row)) for row in producer_lines]
    producer_valid=bool(producers and all(n>0 and sid>0 and 0<cf<=issued and 0<=seed<2**32 for n,sid,cf,issued,seed in producers))
    crashes=sorted({(int(pid),int(signal)) for pid,signal in
        re.findall(r'CRASH backboardd\[(\d+)\] sig (\d+)',kernel)})
    report.update(cycle=str(root),authenticated_clean_runtime=authenticated,
        app_Metal_full_native_contract_pass=app_metal,offscreen_GPU_contract_pass=gpu,
        native_direct_GL_pixels_and_guards_pass=direct_native,kernel_surface_producer_records=len(producers),
        native_frame_budget_pixels_and_guards_pass=budget_native,
        native_GMEM_and_sysmem_full_GPU_contract_pass=bool(authenticated and gpu and dual_modes),
        complete_scoped_sysmem_GUI_and_app_Metal_proof=bool(authenticated and
            report['scoped_sysmem_GPU_policy_observed'] and report['actual_GLES_composition'] and report['direct_surface_GPU_composition'] and
            report['asynchronous_GLES_handoff'] and report['real_GLES_frame_budget'] and
            direct_native and budget_native and dual_modes and app_metal and gpu and not crashes),
        complete_bounded_direct_GLES_and_app_Metal_proof=bool(authenticated and
            report['actual_GLES_composition'] and report['direct_surface_GPU_composition'] and
            report['asynchronous_GLES_handoff'] and report['real_GLES_frame_budget'] and
            direct_native and budget_native and producer_valid and app_metal and gpu and not crashes),
        complete_direct_GLES_and_app_Metal_proof=bool(authenticated and
            report['actual_GLES_composition'] and report['direct_surface_GPU_composition'] and
            report['asynchronous_GLES_handoff'] and direct_native and producer_valid and app_metal and gpu and not crashes),
        backboardd_crashes=[dict(pid=pid,signal=signal) for pid,signal in crashes],
        complete_GLES_GUI_and_app_Metal_proof=bool(authenticated and
            report['actual_GLES_composition'] and app_metal and gpu and not crashes))
    (root/'compositor-evidence.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='frames'},indent=2))


if __name__=='__main__':main()
