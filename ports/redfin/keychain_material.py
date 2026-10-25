"""Provision persistent private material for Redfin's software key wrapping.

The secret is supplied only to a temporary boot image and consumed/removed
from IORegistry before userspace. It is separate from public device identity.
This does not provide a Secure Enclave or Apple activation certificates.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import uuid

KEYS = {'format_version', 'product', 'wrapping_key_hex', 'bag_uuid_hex'}
PROPERTY = 'redfin-keychain-material'


def validate(value):
    if (not isinstance(value, dict) or set(value) != KEYS
            or type(value.get('format_version')) is not int or value['format_version'] != 1
            or value.get('product') != 'redfin'):
        raise ValueError('expected private Redfin software keychain material version1')
    for name, count in (('wrapping_key_hex',64),('bag_uuid_hex',32)):
        text = value.get(name)
        if not isinstance(text,str) or len(text) != count or any(c not in '0123456789abcdef' for c in text):
            raise ValueError('invalid private keychain material encoding')
        if not any(bytes.fromhex(text)):
            raise ValueError('empty private keychain material')
    return dict(value)


def load(path):
    path = Path(path)
    if not path.is_file() or not 1 <= path.stat().st_size <= 4096 or path.stat().st_mode & 0o077:
        raise ValueError('expected bounded mode0600 private keychain material')
    return validate(json.loads(path.read_text()))


def create(path):
    path = Path(path)
    value = validate(dict(format_version=1, product='redfin',
        wrapping_key_hex=secrets.token_hex(32), bag_uuid_hex=uuid.uuid4().hex))
    descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as stream:
        json.dump(value,stream,indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    return value


def report(path,value):
    validate(value)
    return dict(source=str(Path(path).resolve()),sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                software_keywrap='AES256-RFC3394',hardware_secure_enclave=False,material_logged=False)


def apply(root,value):
    value = validate(value)
    chosen = [node for node in root.children if node.name == 'chosen']
    if len(chosen) != 1 or any(key == PROPERTY for key,_,_ in chosen[0].props):
        raise ValueError('expected one chosen node without existing keychain material')
    material = (1).to_bytes(4,'little')+(1).to_bytes(4,'little')
    material += bytes.fromhex(value['wrapping_key_hex'])+bytes.fromhex(value['bag_uuid_hex'])
    assert len(material) == 56
    chosen[0].props.append((PROPERTY,0,material))
