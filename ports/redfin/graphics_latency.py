"""Correlate sampled, nonce-bound Metal phases; never infer rendering FPS."""
import argparse
import json
from pathlib import Path
import re
import statistics

ROW=re.compile(r'\[(?P<process>[^\s\]]+) (?P<pid>\d+)\]: REDFIN METAL '
               r'(?P<kind>FENCE|RETIREMENT|FRONTEND|IO|ROUTES): (?P<fields>.*)')
PARTS=('completion-queue-us','native-wait-us','predecessor-us','retire-gate-us',
       'bookkeeping-us','resources-us','slot-us')


def analyze(lines,boot,process='backboardd'):
    if not re.fullmatch('[0-9a-f]{16}',boot):raise ValueError('an exact 16-digit boot nonce is required')
    commands={}
    for line in lines:
        if 'boot='+boot not in line:continue
        match=ROW.search(line)
        if not match or match['process']!=process:continue
        values=dict(re.findall(r'([\w-]+)=([^\s]+)',match['fields']))
        if values.get('boot')!=boot or values.get('actual-finish')!='1':continue
        try:sequence=int(values['sequence'])
        except (KeyError,ValueError):continue
        key=(int(match['pid']),sequence)
        row=commands.setdefault(key,{'pid':key[0],'sequence':sequence,'observations':{}})
        kind=match['kind'].lower()
        numeric={k:int(v) for k,v in values.items() if k!='boot' and re.fullmatch('[0-9]+',v)}
        previous=row['observations'].get(kind)
        if previous is not None and previous!=numeric:row['conflicting_duplicate']=True
        row['observations'][kind]=numeric
    complete=[];incomplete=0;invalid=[]
    for row in commands.values():
        observations=row['observations']
        if not {'fence','retirement','frontend'}<=observations.keys():incomplete+=1;continue
        fence,retirement,frontend=(observations[k] for k in ('fence','retirement','frontend'))
        missing=set(PARTS+('submit-to-ready-us','native-ticket'))-retirement.keys()
        if missing or row.get('conflicting_duplicate'):
            invalid.append({'pid':row['pid'],'sequence':row['sequence'],'reason':'missing/conflicting phases'});continue
        # The seven adjacent intervals partition the host's post-submit time.
        # Independent truncation to microseconds loses at most six microseconds.
        residual=retirement['submit-to-ready-us']-sum(retirement[k] for k in PARTS)
        if not 0<=residual<len(PARTS) or retirement['native-ticket']!=1:
            invalid.append({'pid':row['pid'],'sequence':row['sequence'],'reason':'invalid retirement partition/native ticket'});continue
        before_resources=sum(retirement[k] for k in PARTS[:5])
        legacy=fence.get('final-fence-us')
        if legacy is None or not 0<=legacy-before_resources<len(PARTS[:5]):
            invalid.append({'pid':row['pid'],'sequence':row['sequence'],'reason':'legacy interval does not match retirement'});continue
        if frontend.get('nested-scopes')!=1:
            invalid.append({'pid':row['pid'],'sequence':row['sequence'],'reason':'frontend scope contract missing'});continue
        if 'routes' in observations:
            routes=observations['routes']
            if routes.get('command-delta')!=1 or not {'gmem-batches','sysmem-batches'}<=routes.keys():
                invalid.append({'pid':row['pid'],'sequence':row['sequence'],'reason':'native raster-route scope missing'});continue
        row['partition-rounding-us']=residual;complete.append(row)
    complete.sort(key=lambda r:(r['pid'],r['sequence']))
    def metric(kind,key):
        values=[r['observations'][kind][key] for r in complete if key in r['observations'].get(kind,{})]
        return {'samples':len(values),'minimum':min(values),'median':statistics.median(values),'maximum':max(values)} if values else None
    return {'boot':boot,'process':process,'pids':sorted({r['pid'] for r in complete}),
            'complete_samples':len(complete),'incomplete_samples':incomplete,'invalid_samples':invalid,
            'sampled_only':True,'frontend_scopes_overlap':True,'gpu_execution_time_measured':False,
            'retirement_us':{k:metric('retirement',k) for k in PARTS},
            # These are native route selections, possibly including helper
            # batches. They are not whole frames or GPU execution durations.
            'raster_routes':{k:metric('routes',k) for k in ('gmem-batches','sysmem-batches')},
            'frontend':{k:metric('frontend',k) for k in (
                'stage-us','draw-us','framebuffer-us','draw-emit-us','snapshots','snapshot-bytes',
                'unknown-snapshots','unknown-snapshot-bytes','constant-prepare-us','constant-copy-us',
                'proven-snapshots','avoided-snapshot-bytes','full-snapshots',
                'GPU-snapshots','GPU-snapshot-bytes','GPU-snapshot-chunks',
                'submit-us','submit-clear-us','submit-resolve-us')},
            'commands':complete}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path);parser.add_argument('--boot',required=True)
    parser.add_argument('--process',default='backboardd');parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    with args.log.open(errors='replace') as lines:result=analyze(lines,args.boot,args.process)
    data=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(data)
    else:print(data,end='')
    return 1 if result['invalid_samples'] or not result['complete_samples'] else 0


if __name__=='__main__':raise SystemExit(main())
