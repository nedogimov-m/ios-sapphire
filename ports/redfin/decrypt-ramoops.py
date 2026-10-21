#!/usr/bin/env python3
"""Authenticate/decrypt a saved Pixel encrypted ramoops capture on the host.

Protocol matches the public Redfin vendor ramoops binary: RSA PKCS#1 v1.5
unwrap, then AES-GCM over the complete 4 MiB bank, without associated data.
Private keys and unwrapped AES material never appear in argv, logs or JSON.
No device access. Plaintext is created mode 0600 only after authentication.
"""
import argparse
import contextlib
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import zlib

BANK_BYTES = 4*1024*1024
CONTROL_MAGIC = 0x4b6c6243
AES_MAGIC = 0x596b4145
PLAINTEXT_MAGIC = 0x4165357a
AES_OFFSET = 0x408
MAX_METADATA = 0x808


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextlib.contextmanager
def private_file(path, maximum):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        item = os.fstat(fd)
        require(stat.S_ISREG(item.st_mode) and item.st_uid == os.geteuid(),
                'private input must be a regular file owned by the current user')
        require(not item.st_mode & 0o077, 'private input requires permissions 0600 or stricter')
        require(0 < item.st_size <= maximum, 'private input size is invalid')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            yield stream
    finally:
        os.close(fd)


def metadata(data):
    require(len(data) in (MAX_METADATA, 4096), 'metadata must be 2056 or 4096 bytes')
    require(struct.unpack_from('<I', data)[0] == CONTROL_MAGIC, 'metadata control magic mismatch')
    magic, flags, length = struct.unpack_from('<3I', data, AES_OFFSET)
    require(magic == AES_MAGIC, 'metadata has no encrypted AES block')
    key_bytes = {2: 32, 4: 16}.get(flags & 6)
    require(key_bytes is not None, 'unsupported AES key-length flags')
    end = AES_OFFSET + 12 + length
    require(length in (128, 256, 384, 512) and end+4 <= MAX_METADATA,
            'invalid or out-of-bounds wrapped AES key length')
    expected_crc = struct.unpack_from('<I', data, end)[0]
    require(zlib.crc32(data[AES_OFFSET:end]) == expected_crc, 'encrypted AES block CRC mismatch')
    return data[AES_OFFSET+12:end], key_bytes


def aes_payload(plaintext, key_bytes):
    # Native generator wraps a 64-byte struct even for AES-128. Accept the
    # shorter meaningful AES-128 prefix, but never read beyond decrypted data.
    require(32+key_bytes <= len(plaintext) <= 64, 'unwrapped AES payload length is invalid')
    require(struct.unpack_from('<I', plaintext)[0] == PLAINTEXT_MAGIC, 'unwrapped AES payload magic mismatch')
    return plaintext[32:32+key_bytes], plaintext[4:16], plaintext[16:32]


def unwrap(wrapped, private_key, openssl):
    with private_file(private_key, 65536) as key:
        result = subprocess.run([openssl, 'pkeyutl', '-decrypt', '-inkey', f'/dev/fd/{key.fileno()}',
                                 '-pkeyopt', 'rsa_padding_mode:pkcs1'], input=wrapped,
                                pass_fds=(key.fileno(),), capture_output=True, timeout=15)
    require(result.returncode == 0, 'RSA unwrap failed: wrong private key or damaged metadata')
    return result.stdout


def crypto_library(explicit=None):
    candidates = [explicit] if explicit else [
        '/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib',
        '/usr/local/opt/openssl@3/lib/libcrypto.3.dylib', ctypes.util.find_library('crypto')]
    for candidate in filter(None, candidates):
        try:
            library = ctypes.CDLL(candidate)
            library.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
            library.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
            for name in ('EVP_aes_128_gcm', 'EVP_aes_256_gcm'):
                getattr(library, name).restype = ctypes.c_void_p
            library.EVP_DecryptInit_ex.argtypes = [ctypes.c_void_p]*5
            library.EVP_DecryptInit_ex.restype = ctypes.c_int
            library.EVP_CIPHER_CTX_ctrl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
            library.EVP_CIPHER_CTX_ctrl.restype = ctypes.c_int
            library.EVP_DecryptUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_int), ctypes.c_void_p, ctypes.c_int]
            library.EVP_DecryptUpdate.restype = ctypes.c_int
            library.EVP_DecryptFinal_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
            library.EVP_DecryptFinal_ex.restype = ctypes.c_int
            return library
        except (OSError, AttributeError):
            continue
    raise ValueError('OpenSSL libcrypto with AES-GCM is required')


def decrypt_gcm(ciphertext, key, iv, tag, library=None):
    require(len(key) in (16, 32) and len(iv) == 12 and len(tag) == 16, 'invalid AES-GCM parameters')
    require(0 < len(ciphertext) <= BANK_BYTES, 'ciphertext size exceeds one ramoops bank')
    library = library or crypto_library()
    context = library.EVP_CIPHER_CTX_new()
    require(context, 'could not allocate AES-GCM context')
    try:
        cipher = library.EVP_aes_128_gcm() if len(key) == 16 else library.EVP_aes_256_gcm()
        require(library.EVP_DecryptInit_ex(context, cipher, None, None, None) == 1, 'AES-GCM initialization failed')
        require(library.EVP_CIPHER_CTX_ctrl(context, 0x9, len(iv), None) == 1, 'AES-GCM IV initialization failed')
        key_buffer, iv_buffer = ctypes.create_string_buffer(key), ctypes.create_string_buffer(iv)
        require(library.EVP_DecryptInit_ex(context, None, None, key_buffer, iv_buffer) == 1,
                'AES-GCM key initialization failed')
        source, tag_buffer = ctypes.create_string_buffer(ciphertext), ctypes.create_string_buffer(tag)
        output = ctypes.create_string_buffer(len(ciphertext)+16)
        size, final_size = ctypes.c_int(), ctypes.c_int()
        require(library.EVP_DecryptUpdate(context, output, ctypes.byref(size), source, len(ciphertext)) == 1,
                'AES-GCM update failed')
        require(library.EVP_CIPHER_CTX_ctrl(context, 0x11, len(tag), tag_buffer) == 1, 'AES-GCM tag setup failed')
        require(library.EVP_DecryptFinal_ex(context, ctypes.byref(output, size.value), ctypes.byref(final_size)) == 1,
                'AES-GCM authentication failed; no plaintext was written')
        require(size.value+final_size.value == len(ciphertext), 'AES-GCM plaintext length mismatch')
        return output.raw[:len(ciphertext)]
    finally:
        library.EVP_CIPHER_CTX_free(context)


def decrypt_capture(ciphertext: bytes, metadata_bytes: bytes, private_key: Path, *, libcrypto=None) -> bytes:
    """Return authenticated bank bytes; raise without returning unauthenticated data.

    Callers own metadata-file permissions; private-key ownership/mode and RSA
    unwrap are checked here. This helper never writes files or contacts devices.
    """
    require(isinstance(ciphertext, bytes) and len(ciphertext) == BANK_BYTES,
            'raw capture must be exactly 4 MiB')
    wrapped, key_bytes = metadata(metadata_bytes)
    openssl = shutil.which('openssl')
    require(openssl, 'openssl executable required for RSA unwrap')
    key, iv, tag = aes_payload(unwrap(wrapped, private_key, openssl), key_bytes)
    return decrypt_gcm(ciphertext, key, iv, tag, crypto_library(libcrypto))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--libcrypto', help='OpenSSL libcrypto shared library')
    args = parser.parse_args(argv)
    created = False
    try:
        require(not args.out.exists() and not args.out.is_symlink(), 'choose a new output file')
        with private_file(args.metadata, 4096) as stream:
            metadata_bytes = stream.read()
        unused, key_bytes = metadata(metadata_bytes)
        ciphertext = args.raw.read_bytes()
        plaintext = decrypt_capture(ciphertext, metadata_bytes, args.private_key, libcrypto=args.libcrypto)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            stream.write(plaintext)
        print(json.dumps({'authenticated': True, 'bytes': len(plaintext), 'aes_bits': key_bytes*8,
                          'out': str(args.out), 'sha256': hashlib.sha256(plaintext).hexdigest(),
                          'markers': {name: token in plaintext for name, token in (
                              ('darwin', b'Darwin Kernel Version'), ('redfin', b'REDFIN'),
                              ('pid1_heartbeat', b'REDFIN init: still alive'))}}, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if created:
            args.out.unlink(missing_ok=True)
        print('decrypt-ramoops: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
