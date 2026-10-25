#!/usr/bin/env python3
"""Record Redfin's retained RTC counter against host UTC, without setting it.

The native RTC has a device-specific epoch; erased Android userdata held its
old epoch mapping. This private replacement follows the continuously running
physical counter across RAM boots. No RTC/alarm/partition write is performed.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'ports/redfin'))
from ports.redfin.platform_power import load_anchor


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'backup/redfin/ios-rtc-anchor.json')
    a=p.parse_args();out=a.out.resolve()
    if out.exists():
        load_anchor(out);print('Existing valid RTC anchor retained.');return
    if ROOT/'backup' not in out.parents:raise ValueError('RTC epoch mapping must stay in private backup')
    devices=subprocess.check_output(['adb','devices'],timeout=10).splitlines()[1:]
    devices=[x.split() for x in devices if x.strip()]
    if len(devices)!=1 or devices[0][1] not in (b'device',b'recovery'):
        raise ValueError('one offline recovery device required')
    spec=importlib.util.spec_from_file_location('rtc_recovery_cycle',ROOT/'ports/redfin/boot-cycle.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cycle=module.Cycle(argparse.Namespace(serial=devices[0][0].decode(),out=ROOT/'research/redfin-power'))
    cycle.verify_recovery()
    started=time.time_ns()
    code,data,_=cycle.adb('exec-out','cat','/sys/class/rtc/rtc0/since_epoch')
    finished=time.time_ns()
    if code or not data.strip().isdigit() or finished-started>1500000000:
        raise ValueError('bounded actual RTC read failed')
    rtc=int(data.strip());epoch=(started+finished)//2000000000
    record=dict(version=1,product='redfin',source='verified-offline-recovery/host-UTC',
                rtc_seconds=rtc,unix_offset_seconds=epoch-rtc,
                uncertainty_ms=1000+(finished-started)//1000000)
    out.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(out,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(record,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    load_anchor(out);cycle.verify_recovery_storage()
    print('Private RTC-to-UTC anchor saved; physical RTC and alarms unchanged.')


if __name__=='__main__':main()
