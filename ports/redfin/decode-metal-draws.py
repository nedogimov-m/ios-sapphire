#!/usr/bin/env python3
"""Verify private native Metal draw readbacks and write PNGs below logs/."""
import argparse
import base64
import json
from pathlib import Path
import re
import struct
import zlib

ROOT=Path(__file__).resolve().parents[2]
RECORD=re.compile(rb'REDFIN METAL DRAW IMAGE: boot=([0-9a-f]{16}) frame=([0-9]+) draw=([0-9]+) '
    rb'role=(FINAL|OUTPUT|INPUTV|INPUTF) slot=([0-9]+) surface=([0-9]+) format=([0-9]+) '
    rb'source=([0-9]+)x([0-9]+) width=([0-9]+) height=([0-9]+) raw=([0-9]+) '
    rb'crc32=([0-9a-f]{8}) data=([A-Za-z0-9+/]+)')


def png(rgb,width,height):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    scanlines=b''.join(b'\0'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+\
        chunk(b'IDAT',zlib.compress(scanlines))+chunk(b'IEND',b'')


def decode(data,boot):
    if len(data)>32*1024**2 or not re.fullmatch('[0-9a-f]{16}',boot):raise ValueError('bounded log and exact boot ID required')
    records=[]
    for line in data.splitlines():
        if not line.startswith(b'REDFIN METAL DRAW IMAGE: boot='+boot.encode()+b' '):continue
        match=RECORD.fullmatch(line)
        if not match:raise ValueError('malformed native Metal draw record')
        _,frame,draw,role,slot,surface,fmt,sw,sh,width,height,raw,crc,encoded=match.groups()
        frame,draw,slot,surface,fmt,sw,sh,width,height,raw=map(int,(frame,draw,slot,surface,fmt,sw,sh,width,height,raw))
        if not(frame==len(records)+1<=48 and 1<=draw<=8192 and slot<32 and surface<2**32 and fmt<2**32 and
            1<=sw<=16384 and 1<=sh<=16384 and 1<=width<=80 and 1<=height<=174 and raw==width*height*3):
            raise ValueError('native Metal draw bounds/sequence mismatch')
        rgb=base64.b64decode(encoded,validate=True)
        if len(rgb)!=raw or base64.b64encode(rgb)!=encoded or zlib.crc32(rgb)&0xffffffff!=int(crc,16):
            raise ValueError('native Metal draw pixel/CRC mismatch')
        record=dict(frame=frame,draw=draw,role=role.decode(),slot=slot,surface=surface,format=fmt,
            source_width=sw,source_height=sh,width=width,height=height,crc32=crc.decode())
        records.append((record,rgb))
    if not records:raise ValueError('no complete native draw readbacks for this boot')
    return records


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path)
    p.add_argument('--boot-id',required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    out=args.out.resolve()
    if (ROOT/'logs').resolve() not in out.parents:raise ValueError('private draw captures must remain under logs/')
    records=decode(args.log.read_bytes(),args.boot_id);out.mkdir(parents=True,exist_ok=False)
    report=[]
    for record,rgb in records:
        name=f"frame-{record['frame']:02}-draw-{record['draw']:02}-{record['role'].lower()}{record['slot']}.png"
        path=out/name;path.write_bytes(png(rgb,record['width'],record['height']));path.chmod(0o600)
        report.append(dict(record,path=str(path)))
    path=out/'manifest.json';path.write_text(json.dumps(dict(boot_id=args.boot_id,frames=report),indent=2)+'\n');path.chmod(0o600)
    print(json.dumps(dict(boot_id=args.boot_id,frames=len(report),manifest=str(path)),indent=2))


if __name__=='__main__':main()
