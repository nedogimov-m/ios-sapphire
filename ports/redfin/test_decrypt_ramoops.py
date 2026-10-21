"""Public known vectors and generated fixture keys; never read device keys."""
import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

SPEC = importlib.util.spec_from_file_location('ramoops_decrypt', Path(__file__).with_name('decrypt-ramoops.py'))
DECRYPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DECRYPT)


def fixture_metadata(key_bytes=16):
    result = bytearray(4096)
    struct.pack_into('<I', result, 0, DECRYPT.CONTROL_MAGIC)
    struct.pack_into('<3I', result, 0x408, DECRYPT.AES_MAGIC, 5 if key_bytes == 16 else 3, 256)
    end = 0x414+256
    struct.pack_into('<I', result, end, zlib.crc32(result[0x408:end]))
    return bytes(result)


def fixture_payload():
    return struct.pack('<I', DECRYPT.PLAINTEXT_MAGIC)+bytes(60)


class RamoopsCryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.library = DECRYPT.crypto_library()
        except ValueError as error:
            raise unittest.SkipTest(str(error))

    def test_nist_aes_gcm_vector_and_bad_tag(self):
        ciphertext = bytes.fromhex('0388dace60b6a392f328c2b971b2fe78')
        tag = bytes.fromhex('ab6e47d42cec13bdf53a67b21257bddf')
        self.assertEqual(DECRYPT.decrypt_gcm(ciphertext, bytes(16), bytes(12), tag, self.library), bytes(16))
        with self.assertRaisesRegex(ValueError, 'authentication failed'):
            DECRYPT.decrypt_gcm(ciphertext, bytes(16), bytes(12), bytes(16), self.library)

    def test_metadata_crc_length_magic_and_key_size_fences(self):
        for length in (16, 32):
            wrapped, key_bytes = DECRYPT.metadata(fixture_metadata(length))
            self.assertEqual((len(wrapped), key_bytes), (256, length))
        for offset in (0, 0x408, 0x414, 0x414+256):
            bad = bytearray(fixture_metadata()); bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                DECRYPT.metadata(bytes(bad))
        for offset, value in ((0x40c, 0), (0x410, 0), (0x410, 0xffffffff)):
            bad = bytearray(fixture_metadata()); struct.pack_into('<I', bad, offset, value)
            with self.assertRaises(ValueError):
                DECRYPT.metadata(bytes(bad))
        for size in (0, 1024, 0x807, 4095, 4097):
            with self.assertRaises(ValueError):
                DECRYPT.metadata(bytes(size))

    def test_native_payload_accepts_canonical_64_and_bounds_key_material(self):
        for size in (16, 32):
            key, iv, tag = DECRYPT.aes_payload(fixture_payload(), size)
            self.assertEqual((len(key), len(iv), len(tag)), (size, 12, 16))
        self.assertEqual(len(DECRYPT.aes_payload(fixture_payload()[:48], 16)[0]), 16)
        for payload, size in ((fixture_payload()[:47], 16), (fixture_payload()[:63], 32),
                              (fixture_payload()+b'\0', 16), (bytes(64), 16)):
            with self.assertRaises(ValueError):
                DECRYPT.aes_payload(payload, size)

    @unittest.skipUnless(shutil.which('openssl'), 'openssl executable required')
    def test_pkcs1_v15_unwrap_and_private_permissions(self):
        openssl = shutil.which('openssl')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); private, public = root/'private.pem', root/'public.pem'
            subprocess.run([openssl, 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                            '-out', str(private)], check=True, capture_output=True)
            private.chmod(0o600)
            subprocess.run([openssl, 'pkey', '-in', str(private), '-pubout', '-out', str(public)],
                           check=True, capture_output=True)
            wrapped = subprocess.run([openssl, 'pkeyutl', '-encrypt', '-pubin', '-inkey', str(public),
                                       '-pkeyopt', 'rsa_padding_mode:pkcs1'], input=fixture_payload(),
                                      check=True, capture_output=True).stdout
            self.assertEqual(DECRYPT.unwrap(wrapped, private, openssl), fixture_payload())
            private.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'permissions'):
                DECRYPT.unwrap(wrapped, private, openssl)
            private.chmod(0o600)
            link = root/'link.pem'; link.symlink_to(private)
            with self.assertRaises((OSError, ValueError)):
                DECRYPT.unwrap(wrapped, link, openssl)

    @unittest.skipUnless(shutil.which('openssl'), 'openssl executable required')
    def test_wrapper_authentication_failure_returns_no_plaintext_and_cli_creates_nothing(self):
        with patch.object(DECRYPT, 'unwrap', return_value=fixture_payload()), \
             self.assertRaisesRegex(ValueError, 'authentication failed'):
            DECRYPT.decrypt_capture(bytes(DECRYPT.BANK_BYTES), fixture_metadata(), Path('unused.pem'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); meta, raw, output = root/'metadata', root/'raw', root/'plaintext'
            meta.write_bytes(fixture_metadata()); meta.chmod(0o600)
            raw.write_bytes(bytes(DECRYPT.BANK_BYTES))
            with patch.object(DECRYPT, 'unwrap', return_value=fixture_payload()), \
                 contextlib.redirect_stderr(io.StringIO()):
                code = DECRYPT.main(['--metadata', str(meta), '--raw', str(raw),
                                     '--private-key', 'unused.pem', '--out', str(output)])
            self.assertEqual(code, 1)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
