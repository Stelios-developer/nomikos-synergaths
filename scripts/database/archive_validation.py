"""Fail closed on ambiguous or modified members in a synthetic/legacy backup."""
import hashlib
import json
from pathlib import PurePosixPath
import re


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate manifest key')
        result[key] = value
    return result


def validate_inventory(archive):
    entries = archive.getmembers()
    by_name = {}
    for entry in entries:
        name = entry.name
        path = PurePosixPath(name)
        if (not entry.isfile() or not name or name in by_name or path.is_absolute()
                or str(path) != name
                or '\\' in name or ':' in name or any(part in ('.', '..') for part in name.split('/'))
                or any(ord(character) < 32 for character in name)):
            raise ValueError('Unexpected or duplicate backup member')
        by_name[name] = entry
    if 'manifest.json' not in by_name or 'legacy-vectors.json' not in by_name:
        raise ValueError('Required backup member is missing')
    manifest_stream = archive.extractfile(by_name['manifest.json'])
    if manifest_stream is None:
        raise ValueError('Backup manifest is unreadable')
    manifest = json.load(manifest_stream, object_pairs_hook=_unique_object)
    if (not isinstance(manifest, dict) or 'manifest.json' in manifest
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in manifest.values())):
        raise ValueError('Invalid backup manifest')
    if set(manifest) != set(by_name) - {'manifest.json'}:
        raise ValueError('Backup inventory does not match archive members')
    for name, expected in manifest.items():
        stream = archive.extractfile(by_name[name])
        if stream is None:
            raise ValueError('Backup member is unreadable')
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('Backup checksum mismatch')
    return manifest
