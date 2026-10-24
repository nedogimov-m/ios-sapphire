"""Read a private Redfin identity; never generate an Apple handset identity.

The serial belongs to the actual Pixel. It fills the local OS identity only;
Apple activation certificates and account authentication are separate.
"""
import hashlib
import json
from pathlib import Path


def validate(value):
    if (not isinstance(value, dict) or type(value.get('format_version')) is not int or value.get('format_version') != 1 or
            value.get('product') != 'redfin' or
            set(value) - {'format_version', 'product', 'serial_number', 'source'}):
        raise ValueError('expected a private Redfin identity version1')
    serial = value.get('serial_number')
    if (not isinstance(serial, str) or not 6 <= len(serial) <= 64 or
            any(not (c.isascii() and (c.isalnum() or c in '-_')) for c in serial)):
        raise ValueError('invalid physical Redfin serial')
    return dict(value)


def load(path):
    path = Path(path)
    if not path.is_file() or not 1 <= path.stat().st_size <= 4096:
        raise ValueError('expected a bounded private identity file')
    return validate(json.loads(path.read_text()))


def report(path, value):
    validate(value)
    return {'source': str(Path(path).resolve()),
            'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'physical_redfin_serial': True, 'apple_activation_identity': False}


def apply(root, value):
    value = validate(value)
    serial = value['serial_number'].encode('ascii') + b'\0'
    chosen = [node for node in root.children if node.name == 'chosen']
    if len(chosen) != 1:
        raise ValueError('expected exactly one chosen node for private identity')
    for node in (root, chosen[0]):
        if any(key == 'serial-number' for key, _, _ in node.props):
            raise ValueError('refusing an existing serial identity')
    if any(key == 'redfin-identity-version' for key, _, _ in chosen[0].props):
        raise ValueError('refusing an existing private identity version')
    for node in (root, chosen[0]):
        node.props.append(('serial-number', 0, serial))
    chosen[0].props.append(('redfin-identity-version', 0, (1).to_bytes(4, 'little')))

