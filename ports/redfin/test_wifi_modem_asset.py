"""Read-only FAT provenance, module bytes and the actual native asset parser."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

import modem_fat as F
import wifi_assets
import wifi_modem_asset as M
from test_wifi_firmware import SHA, sha256

HERE = Path(__file__).resolve().parent


def record(short, cluster, size=0, directory=False):
    data = bytearray(32); data[:11] = short; data[11] = 16 if directory else 32
    struct.pack_into('<H', data, 20, cluster >> 16); struct.pack_into('<H', data, 26, cluster & 0xffff)
    struct.pack_into('<I', data, 28, size)
    return data


def fixture(path, bits=16):
    bps, clusters, reserved, fats = 512, 4096 if bits == 16 else 65525, 1 if bits == 16 else 32, 2
    roots = 512 if bits == 16 else 0
    fat_sectors = ((clusters + 2) * (bits // 8) + bps - 1) // bps
    first_data = reserved + fats * fat_sectors + (roots * 32 + bps - 1) // bps
    total = first_data + clusters
    boot = bytearray(512); boot[:3] = b'\xeb\x3c\x90'; boot[13] = 1; boot[16] = 2; boot[510:512] = b'\x55\xaa'
    struct.pack_into('<H', boot, 11, bps); struct.pack_into('<H', boot, 14, reserved)
    struct.pack_into('<H', boot, 17, roots); struct.pack_into('<I', boot, 32, total)
    if bits == 16: struct.pack_into('<H', boot, 22, fat_sectors)
    else:
        struct.pack_into('<I', boot, 36, fat_sectors); struct.pack_into('<I', boot, 44, 2)
    root, image, modem, so, file = (0, 2, 3, 4, 5) if bits == 16 else (2, 3, 4, 5, 6)
    table = bytearray(fat_sectors * 512); fmt = '<H' if bits == 16 else '<I'
    end = 0xffff if bits == 16 else 0x0fffffff
    for cluster in range(file + 2): struct.pack_into(fmt, table, cluster * (bits // 8), end)
    struct.pack_into(fmt, table, file * (bits // 8), file + 1)
    data = bytearray((i * 7 + 3) % 256 for i in range(700)); data[:7] = b'\x7fELF\1\1\1'
    struct.pack_into('<H', data, 18, 164)
    short = b'549_38~1MBN'
    units = [ord(c) for c in '549_38_0.mbn'] + [0]; units += [0xffff] * (13 - len(units))
    raw = struct.pack('<13H', *units); lfn = bytearray(32)
    lfn[0] = 0x41; lfn[11] = 15; lfn[13] = F.FAT.lfn_checksum(short)
    lfn[1:11], lfn[14:26], lfn[28:32] = raw[:10], raw[10:22], raw[22:26]
    def offset(cluster): return (first_data + cluster - 2) * 512
    root_offset = (reserved + fats * fat_sectors) * 512 if bits == 16 else offset(root)
    writes = [(0, boot), (reserved * 512, table), ((reserved + fat_sectors) * 512, table),
              (root_offset, record(b'IMAGE      ', image, directory=True)),
              (offset(image), record(b'MODEM_PR   ', modem, directory=True)),
              (offset(modem), record(b'SO         ', so, directory=True)),
              (offset(so), lfn + record(short, file, len(data))), (offset(file), data)]
    with path.open('wb') as output:
        output.truncate(total * 512)
        for at, value in writes: output.seek(at); output.write(value)
    return bytes(data), {'fat': reserved * 512, 'fat_bytes': len(table), 'fat_copy': (reserved + fat_sectors) * 512,
                         'file_cluster': file, 'so_offset': offset(so), 'image_offset': offset(image), 'bits': bits}


def plan(path, image):
    digest = hashlib.sha256(b'main native bundle').hexdigest()
    report = {'schema': 1, 'source_image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
              'bundle_sha256': digest, 'hardware_started': False, 'signature_authenticated': False}
    path.write_text(json.dumps(report))
    return digest


class ModemAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def prepared(self, bits=16):
        image = self.directory / ('modem-' + str(bits)); data, geometry = fixture(image, bits)
        source = self.directory / ('plan-' + str(bits)); digest = plan(source, image)
        return image, source, digest, data, geometry

    def test_fat16_and_fat32_preserve_source_and_bind_exact_module_to_main_bundle(self):
        for bits in (16, 32):
            image, source, digest, data, _ = self.prepared(bits)
            original = image.read_bytes(); output = self.directory / ('output-' + str(bits))
            item = M.extract(image, source, output)
            entry, report = M.load(output / 'inventory.json', source, digest)
            self.assertEqual(entry[0], M.MODULE); self.assertEqual(entry[1], data)
            self.assertEqual(report['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(image.read_bytes(), original)
            self.assertEqual(stat.S_IMODE((output / item['private_file']).stat().st_mode), 0o600)
            with self.assertRaises(ValueError): M.extract(image, source, output)

    def test_changed_image_plan_bundle_module_or_path_is_rejected(self):
        image, source, digest, data, _ = self.prepared()
        output = self.directory / 'output'; M.extract(image, source, output)
        manifest = output / 'inventory.json'; original = manifest.read_text()
        for key, value in [('path', 'image/other.mbn'), ('private_file', '../modem-16'),
                           ('source_image_sha256', '0' * 64), ('source_plan_sha256', '0' * 64)]:
            item = json.loads(original); item[key] = value; manifest.write_text(json.dumps(item))
            with self.assertRaises(ValueError): M.load(manifest, source, digest)
        manifest.write_text(original)
        with self.assertRaises(ValueError): M.load(manifest, source, '0' * 64)
        (output / M.MODULE.rsplit('/', 1)[-1]).write_bytes(data[:-1] + b'x')
        with self.assertRaises(ValueError): M.load(manifest, source, digest)
        image_data = bytearray(image.read_bytes()); image_data[-1] ^= 1; image.write_bytes(image_data)
        with self.assertRaises(ValueError): M.extract(image, source, self.directory / 'changed')

    def test_bad_geometry_fat_mirror_lfn_cycle_and_directory_alias_are_refused(self):
        for case in ('geometry', 'mirror', 'lfn', 'cycle', 'directory-alias'):
            with self.subTest(case=case):
                image = self.directory / case; _, g = fixture(image)
                data = bytearray(image.read_bytes())
                if case == 'geometry': data[13] = 3
                if case == 'mirror': data[g['fat_copy'] + 10] ^= 1
                if case == 'lfn': data[g['so_offset'] + 13] ^= 1
                if case == 'cycle':
                    for start in (g['fat'], g['fat_copy']): struct.pack_into('<H', data, start + 2 * g['file_cluster'], g['file_cluster'])
                if case == 'directory-alias': struct.pack_into('<H', data, g['image_offset'] + 26, 2)
                image.write_bytes(data); source = self.directory / (case + '.json'); plan(source, image)
                with self.assertRaises(ValueError): M.extract(image, source, self.directory / (case + '-out'))

    def test_source_symlink_and_mutation_during_read_are_refused_without_published_output(self):
        image, source, _, _, _ = self.prepared()
        alias = self.directory / 'alias'; alias.symlink_to(image)
        with self.assertRaises((OSError, ValueError)): M.extract(alias, source, self.directory / 'alias-out')
        original = M.FAT
        class Changed(original):
            def chunks(self, entry, claim=True):
                yield from super().chunks(entry, claim)
                with image.open('r+b') as stream: stream.seek(-1, 2); stream.write(b'!')
        with mock.patch.object(M, 'FAT', Changed), self.assertRaises(ValueError):
            M.extract(image, source, self.directory / 'mutated-out')
        self.assertFalse((self.directory / 'mutated-out').exists())

    def test_extra_module_bundle_is_accepted_by_actual_native_readonly_asset_parser(self):
        compiler = shutil.which('cc')
        if not compiler: self.skipTest('host C compiler unavailable')
        image, source, digest, data, _ = self.prepared()
        output = self.directory / 'module'; M.extract(image, source, output)
        files = []
        for index, name in enumerate(wifi_assets.FILES):
            value = bytes([index + 1]) * 64; file = self.directory / ('asset-' + str(index)); file.write_bytes(value)
            files.append({'path': name, 'private_file': file.name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()})
        inventory = self.directory / 'assets.json'; inventory.write_text(json.dumps({'files': files}))
        blob, report = wifi_assets.pack(inventory, modem_inventory=output / 'inventory.json', firmware_plan=source,
                                       firmware_sha256=digest)
        self.assertEqual(report['assets'], 6)
        (self.directory / 'parse.c').write_text('''#include "wifi_firmware.h"\n#include "wifi_assets.h"\nstatic struct rf_wlan_assets assets;\nint parse(const uint8_t *p,size_t n,const uint8_t *digest,redfin_mpss_sha256_fn sha){return rf_wlan_assets_open(&assets,p,n,digest,sha,0);}\nint find(const uint8_t **p,uint32_t *n){return rf_wlan_asset_find(&assets,"image/modem_pr/so/549_38_0.mbn",p,n);}\n''')
        library = self.directory / 'parse.so'
        subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', '-I', str(HERE),
            str(self.directory / 'parse.c'), '-o', str(library)], check=True, capture_output=True)
        native = C.CDLL(str(library)); native.parse.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, SHA]
        native.find.argtypes = [C.POINTER(C.c_void_p), C.POINTER(C.c_uint32)]
        memory = C.create_string_buffer(blob)
        self.assertEqual(native.parse(memory, len(blob), hashlib.sha256(blob).digest(), sha256), 0)
        pointer, length = C.c_void_p(), C.c_uint32()
        self.assertEqual(native.find(C.byref(pointer), C.byref(length)), 0)
        self.assertEqual(C.string_at(pointer, length.value), data)


if __name__ == '__main__':
    unittest.main()
