import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'database'))
from archive_validation import validate_inventory


def archive_bytes(files, manifest=None):
    target = io.BytesIO()
    if manifest is None:
        manifest = json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in files})
    with tarfile.open(fileobj=target, mode='w') as archive:
        for name, data in [*files, ('manifest.json', manifest.encode())]:
            entry = tarfile.TarInfo(name); entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return target.getvalue()


class BackupInventoryTests(unittest.TestCase):
    def test_valid_inventory(self):
        data = archive_bytes([('legacy-vectors.json', b'[]'), ('pdfs/a.pdf', b'synthetic')])
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
            self.assertEqual(len(validate_inventory(archive)), 2)

    def test_duplicate_and_unsafe_members_fail_closed(self):
        for extra in ('legacy-vectors.json', '../escape', 'pdfs/../../escape', 'C:/escape', 'pdfs\\escape', '/escape'):
            data = archive_bytes([('legacy-vectors.json', b'[]'), (extra, b'fake')])
            with self.subTest(extra=extra), tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
                with self.assertRaises(ValueError):
                    validate_inventory(archive)

    def test_duplicate_manifest_keys_and_changed_data_are_rejected(self):
        digest = hashlib.sha256(b'[]').hexdigest()
        duplicate = '{"legacy-vectors.json":"' + digest + '","legacy-vectors.json":"' + digest + '"}'
        for manifest in (duplicate, json.dumps({'legacy-vectors.json': '0' * 64})):
            data = archive_bytes([('legacy-vectors.json', b'[]')], manifest)
            with self.subTest(manifest=manifest), tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
                with self.assertRaises(ValueError):
                    validate_inventory(archive)

    def test_symbolic_link_is_rejected(self):
        target = io.BytesIO()
        with tarfile.open(fileobj=target, mode='w') as archive:
            entry = tarfile.TarInfo('pdfs/link'); entry.type = tarfile.SYMTYPE; entry.linkname = '../outside'
            archive.addfile(entry)
        with tarfile.open(fileobj=io.BytesIO(target.getvalue()), mode='r:') as archive:
            with self.assertRaises(ValueError):
                validate_inventory(archive)


if __name__ == '__main__':
    unittest.main()
