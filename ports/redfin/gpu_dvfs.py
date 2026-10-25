"""Bind native Redfin OPPs, all speed bins and the readonly GPU fuse cell."""
import struct

from ports.redfin import mkadt

POLICY=(1,0x780000,0x7000,0x1ea,2,5,8,1000,200)
OPPS=((275000000,64),(400000000,128),(500000000,192),(540000000,256),
      (625000000,256),(670000000,320),(700000000,320),(750000000,384))
LOW=(275000,64,5,5,7)
FOUR=(400000,128,7,5,8)
FIVE=(500000,192,8,7,10)
SIX=(625000,256,10,9,12)
FAST=((0,)*5,LOW,FOUR,FIVE,SIX,(670000,320,10,9,12),(750000,384,10,9,12))
MID=((0,)*5,LOW,FOUR,FIVE,SIX)
PROFILES=((0,FAST),(132,MID),(115,((0,)*5,LOW,FOUR,(540000,256,8,7,12))),
          (158,FAST),(165,MID))


def profile_words():
    result=[]
    for speed,rows in PROFILES:
        result.extend((speed,len(rows)))
        result.extend(v for row in rows for v in row)
        result.extend((0,)*((7-len(rows))*5))
    return tuple(result)


def add_contract(tree,nodes):
    cells=lambda *v:struct.pack('>'+str(len(v))+'I',*v)
    def need(path,key,value):
        if nodes.get(path,{}).get(key)!=value:
            raise ValueError('native GPU DVFS FDT mismatch: '+path+' '+key)
    def resolve(raw):
        found=[p for p,v in nodes.items() if raw and v.get('phandle')==raw]
        if len(found)!=1:raise ValueError('GPU DVFS unresolved native phandle')
        return found[0]
    gpu='/soc/qcom,kgsl-3d0@3d00000';fuses='/soc/qfprom@780000'
    need(fuses,'compatible',b'qcom,qfprom\0');need(fuses,'reg',cells(0x780000,0x7000))
    need(fuses,'read-only',b'')
    names=nodes.get(gpu,{}).get('nvmem-cell-names',b'').split(b'\0')
    raw=nodes.get(gpu,{}).get('nvmem-cells',b'')
    if names!=[b'speed_bin',b'gaming_bin',b'isense_slope',b''] or len(raw)!=12:
        raise ValueError('GPU DVFS native nvmem cell order changed')
    speed=resolve(raw[:4])
    if speed!=fuses+'/gpu_speed_bin@1ea':raise ValueError('GPU DVFS speed cell changed')
    need(speed,'reg',cells(0x1ea,2));need(speed,'bits',cells(5,8))
    opp=resolve(nodes.get(gpu,{}).get('operating-points-v2'))
    for hz,voltage in OPPS:
        path=opp+'/opp-'+str(hz)
        need(path,'opp-hz',struct.pack('>Q',hz));need(path,'opp-microvolt',cells(voltage))
    parents=[p for p,v in nodes.items() if p.startswith(gpu+'/qcom,gpu-pwrlevel-bins/') and 'qcom,speed-bin' in v]
    if len(parents)!=len(PROFILES):raise ValueError('GPU DVFS native speed-bin count changed')
    for speed,rows in PROFILES:
        matches=[p for p in parents if nodes[p]['qcom,speed-bin']==cells(speed)]
        if len(matches)!=1:raise ValueError('GPU DVFS missing or duplicate native speed bin')
        parent=matches[0];children=[p for p in nodes if p.rsplit('/',1)[0]==parent]
        if len(children)!=len(rows):raise ValueError('GPU DVFS native power-level count changed')
        need(parent,'qcom,initial-pwrlevel',cells(len(rows)-2))
        for index,row in enumerate(reversed(rows)):
            path=parent+'/qcom,gpu-pwrlevel@'+str(index)
            khz,voltage,bw,minimum,maximum=row
            need(path,'reg',cells(index));need(path,'qcom,gpu-freq',cells(khz*1000))
            for key,value in [('qcom,bus-freq',bw),('qcom,bus-min',minimum),('qcom,bus-max',maximum)]:
                need(path,key,cells(value))
    selected=[n for n in tree.children if n.name=='redfin-gpu-command']
    if len(selected)!=1 or not selected[0].prop('runtime-policy') or selected[0].prop('dvfs-policy'):
        raise ValueError('GPU DVFS needs one native GPU runtime without a duplicate contract')
    for name,words in [('dvfs-policy',POLICY),('dvfs-opps',tuple(v for row in OPPS for v in row)),('dvfs-bins',profile_words())]:
        selected[0].props.append((name,0,mkadt.u32(*words)))
    return dict(source='native Redfin FDT and readonly QFPROM speed_bin',bins=len(PROFILES),
                selection='physical fuse at runtime',thermal_inputs='actual TSENS and battery',
                stale_input='minimum OPP',idle_ms=200,maximum_hz=max(hz for hz,_ in OPPS))
