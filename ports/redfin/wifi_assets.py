"""Pack the captured, hash-verified WLAN base-vendor assets for RAM-only TFTP."""
import hashlib
import json
from pathlib import Path
import struct

from wifi_firmware import read_regular, require

FILES = {
    'firmware/wlanmdsp.mbn': 'image/wlanmdsp.mbn',
    'firmware/modemuw.jsn': 'image/modemuw.jsn',
    'firmware/bdwlan-redfin.bin': 'image/bdwlan-redfin.bin',
    'firmware/bdwlan-u-redfin.bin': 'image/bdwlan-u-redfin.bin',
    'firmware/wlan/qca_cld/WCNSS_qcom_cfg.ini': 'image/WCNSS_qcom_cfg.ini',
}


def pack(manifest, *, modem_inventory=None, firmware_plan=None, firmware_sha256=None):
    manifest = Path(manifest).resolve()
    report = json.loads(read_regular(manifest, 1024 * 1024))
    require(type(report) is dict and type(report.get('files')) is list, 'invalid private WLAN asset inventory')
    selected = {}
    for item in report['files']:
        name = item.get('path', '').removeprefix('/vendor/').removeprefix('vendor/').lstrip('/')
        if name not in FILES:
            continue
        require(name not in selected, 'duplicate private WLAN asset')
        candidate = Path(item['private_file'])
        if not candidate.is_absolute():
            require('..' not in candidate.parts, 'private WLAN asset path escapes its inventory')
            base = manifest.parent.parent if candidate.parts and candidate.parts[0] == manifest.parent.name else manifest.parent
            candidate = base / candidate
        data = read_regular(candidate, 8 * 1024 * 1024)
        digest = hashlib.sha256(data).hexdigest()
        require(len(data) == item['bytes'] and digest == item['sha256'], 'WLAN asset differs from the captured inventory')
        selected[name] = (FILES[name], data, bytes.fromhex(digest))
    require(set(selected) == set(FILES), 'private WLAN inventory lacks required captured firmware/board/config files')
    entries = [selected[name] for name in sorted(selected)]
    module_report = None
    if any(value is not None for value in (modem_inventory, firmware_plan, firmware_sha256)):
        require(all(value is not None for value in (modem_inventory, firmware_plan, firmware_sha256)),
                'observed modem module requires its inventory, main plan and selected bundle hash')
        import wifi_modem_asset
        module, module_report = wifi_modem_asset.load(modem_inventory, firmware_plan, firmware_sha256)
        entries.append(module)
    out = bytearray(64 + 128 * len(entries))
    for i, (name, data, digest) in enumerate(entries):
        encoded = name.encode('ascii')
        require(len(encoded) < 64 and data, 'invalid native WLAN asset name/length')
        offset = len(out)
        out.extend(data)
        out.extend(bytes(-len(out) % 16))
        record = 64 + 128 * i
        out[record:record + 64] = encoded.ljust(64, b'\0')
        struct.pack_into('<QQ', out, record + 64, offset, len(data))
        out[record + 80:record + 112] = digest
    struct.pack_into('<8sIIQQ', out, 0, b'RFWAS01\0', 1, len(entries), len(out), 128)
    require(len(out) <= 16 * 1024 * 1024, 'private WLAN assets exceed native RAM cap')
    return bytes(out), {'schema': 1, 'bytes': len(out), 'assets': len(entries), 'modem_module': module_report,
                       'sha256': hashlib.sha256(out).hexdigest(),
                       'view': report.get('view'), 'current_effective_image_proven': report.get('current_effective_image_proven'),
                       'pristine_stock_vendor_proven': report.get('pristine_stock_vendor_proven')}
