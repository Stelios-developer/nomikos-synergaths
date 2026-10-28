"""Streaming AES-256-GCM backup with authenticated frame order and end marker.

Recovery keys are wrapped using Windows current-user DPAPI. Portable backups
require an externally managed key, not a plaintext key written beside data.
"""

import ctypes
import hashlib
import os
from pathlib import Path
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"DMCBK002"
FRAME = 1024 * 1024


def _dpapi(data, protect):
    if os.name != "nt":
        raise RuntimeError("DPAPI is available only on Windows")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    source = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptProtectData if protect else library.CryptUnprotectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    if not function(
        ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def protect_key(key):
    if os.name == "nt":
        return b"DPAPI\n" + _dpapi(key, True)
    raise RuntimeError("Provision an external backup key on this platform")


def unprotect_key(value):
    if not value.startswith(b"DPAPI\n"):
        raise ValueError("Unknown backup key protection")
    return _dpapi(value[6:], False)


class EncryptWriter:
    def __init__(self, stream, key):
        self.stream, self.aes = stream, AESGCM(key)
        self.identity, self.sequence, self.buffer = os.urandom(16), 0, bytearray()
        self.digest = hashlib.sha256()
        stream.write(MAGIC + self.identity)

    def _frame(self, data):
        nonce = os.urandom(12)
        aad = MAGIC + self.identity + struct.pack(">Q", self.sequence)
        cipher = self.aes.encrypt(nonce, data, aad)
        self.stream.write(struct.pack(">I", len(cipher)) + nonce + cipher)
        self.sequence += 1

    def write(self, data):
        self.digest.update(data)
        self.buffer.extend(data)
        while len(self.buffer) >= FRAME:
            self._frame(bytes(self.buffer[:FRAME]))
            del self.buffer[:FRAME]
        return len(data)

    def finish(self):
        if self.buffer:
            self._frame(bytes(self.buffer))
            self.buffer.clear()
        self._frame(b"")


def decrypt_frames(stream, key):
    header = stream.read(24)
    if len(header) != 24 or header[:8] != MAGIC:
        raise ValueError("Unknown or truncated backup header")
    aes, sequence = AESGCM(key), 0
    while True:
        size = stream.read(4)
        if len(size) != 4:
            raise ValueError("Missing authenticated backup end")
        length = struct.unpack(">I", size)[0]
        if not 16 <= length <= FRAME + 16:
            raise ValueError("Invalid backup frame size")
        nonce, cipher = stream.read(12), stream.read(length)
        if len(nonce) != 12 or len(cipher) != length:
            raise ValueError("Truncated backup frame")
        data = aes.decrypt(nonce, cipher, header + struct.pack(">Q", sequence))
        sequence += 1
        if not data:
            if stream.read(1):
                raise ValueError("Trailing backup data")
            return
        yield data


def seal(path, producer, wrap=protect_key, unwrap=unprotect_key):
    path = Path(path)
    key_path = Path(str(path) + ".key.dpapi")
    key = os.urandom(32)
    # Exclusive creation: do not overwrite a previous recovery copy.
    with key_path.open("xb") as output:
        output.write(wrap(key))
        output.flush()
        os.fsync(output.fileno())
    with path.open("xb") as output:
        writer = EncryptWriter(output, key)
        producer(writer)
        writer.finish()
        output.flush()
        os.fsync(output.fileno())
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for data in decrypt_frames(source, unwrap(key_path.read_bytes())):
            digest.update(data)
    if digest.digest() != writer.digest.digest():
        raise ValueError("Backup failed written-file restore verification")
    return {
        "format": "DMCBK002",
        "plaintext_sha256": digest.hexdigest(),
        "ciphertext_sha256": file_sha256(path),
    }


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(FRAME), b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore_bytes(path, *, maximum=512 * 1024 * 1024):
    """Bounded in-memory restore drill. Never extracts an archive automatically."""
    value = bytearray()
    with open(path, "rb") as source:
        key = unprotect_key(Path(str(path) + ".key.dpapi").read_bytes())
        for data in decrypt_frames(source, key):
            if len(value) + len(data) > maximum:
                raise ValueError("Backup exceeds the restore memory budget")
            value.extend(data)
    return bytes(value)
