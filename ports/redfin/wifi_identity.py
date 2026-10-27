"""Private persistent Redfin station identity; no identifiers are printed."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct

PROPERTY='redfin-wifi-identity'
SOURCES={'factory':1,'persistent-local':2}


def validate(value):
    if (not isinstance(value,dict) or set(value)!={'format_version','product','source','address_hex'} or
            type(value.get('format_version')) is not int or value['format_version']!=1 or
            value.get('product')!='redfin' or value.get('source') not in SOURCES or
            not isinstance(value.get('address_hex'),str) or
            not re.fullmatch('[0-9a-f]{12}',value['address_hex'])):
        raise ValueError('invalid private persistent Wi-Fi identity')
    address=bytes.fromhex(value['address_hex'])
    if address[0]&1 or not any(address) or (value['source']=='persistent-local' and not address[0]&2):
        raise ValueError('invalid private unicast Wi-Fi identity')
    return dict(value)


def load(path):
    path=Path(path);s=path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600 or
            not 1<=s.st_size<=4096):
        raise ValueError('bounded owner-only private Wi-Fi identity required')
    return validate(json.loads(path.read_text()))


def create_local(path):
    """Never overwrite or rotate an existing identity, including an invalid one."""
    path=Path(path)
    if path.exists() or path.is_symlink():return load(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    address=bytearray(secrets.token_bytes(6));address[0]=(address[0]&0xfc)|2
    value=validate(dict(format_version=1,product='redfin',source='persistent-local',address_hex=address.hex()))
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:return load(path)
    with os.fdopen(fd,'w') as output:
        output.write(json.dumps(value,indent=2)+'\n');output.flush();os.fsync(output.fileno())
    return value


def payload(value):
    value=validate(value)
    return struct.pack('<II6s2x',1,SOURCES[value['source']],bytes.fromhex(value['address_hex']))


def apply(root,value):
    chosen=[n for n in root.children if n.name=='chosen']
    if len(chosen)!=1 or any(k==PROPERTY for k,_,_ in chosen[0].props):
        raise ValueError('one chosen node without existing Wi-Fi identity required')
    chosen[0].props.append((PROPERTY,0,payload(value)))


def report(path,value):
    value=validate(value)
    return dict(source=str(Path(path).resolve()),sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        persistent_station_address=True,factory_address=value['source']=='factory',
        locally_administered=value['source']=='persistent-local',identifier_logged=False)
