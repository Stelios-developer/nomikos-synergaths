import io
import os

import pytest
from cryptography.exceptions import InvalidTag

from services.backup_crypto import EncryptWriter, decrypt_frames, protect_key, seal, unprotect_key


def encrypt(value):
    key, output = os.urandom(32), io.BytesIO()
    writer = EncryptWriter(output, key)
    writer.write(value)
    writer.finish()
    return output.getvalue(), key


@pytest.mark.skipif(os.name != 'nt', reason='Windows current-user DPAPI boundary')
def test_actual_windows_key_roundtrip_is_not_plaintext():
    key = os.urandom(32)
    protected = protect_key(key)
    assert key not in protected
    assert unprotect_key(protected) == key


def test_backup_roundtrip_crosses_frame_boundaries_without_plaintext_file(tmp_path):
    value = b'private-source' * 100_000
    path = tmp_path / 'snapshot.aesgcm'
    report = seal(path, lambda out: out.write(value), wrap=lambda key: key, unwrap=lambda key: key)
    assert b'private-source' not in path.read_bytes()
    key = (tmp_path / 'snapshot.aesgcm.key.dpapi').read_bytes()
    assert b''.join(decrypt_frames(io.BytesIO(path.read_bytes()), key)) == value
    assert len(report['plaintext_sha256']) == 64
    with pytest.raises(FileExistsError):
        seal(path, lambda out: out.write(value), wrap=lambda key: key)


@pytest.mark.parametrize('fault', ['truncated', 'missing-end', 'modified', 'wrong-key', 'trailing', 'reordered'])
def test_tampered_or_incomplete_backups_fail_closed(fault):
    data, key = encrypt(b'a' * 1_100_000)
    if fault == 'truncated':
        data = data[:-3]
    elif fault == 'missing-end':
        data = data[:-32]
    elif fault == 'modified':
        data = data[:50] + bytes([data[50] ^ 1]) + data[51:]
    elif fault == 'wrong-key':
        key = os.urandom(32)
    elif fault == 'trailing':
        data += b'x'
    elif fault == 'reordered':
        first = 24 + 4 + 12 + 1_048_576 + 16
        data = data[:24] + data[first:-32] + data[24:first] + data[-32:]
    with pytest.raises((ValueError, InvalidTag)):
        list(decrypt_frames(io.BytesIO(data), key))
