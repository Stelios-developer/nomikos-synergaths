import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from pilot_manifest import validate_manifest


class PilotManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.manifest = {'version': 'pilot-1', 'documents': []}
        for index in range(1, 31):
            identifier = f'pilot-{index:02}'
            data = f'synthetic {index}'.encode()
            (self.directory / f'{identifier}.pdf').write_bytes(data)
            self.manifest['documents'].append({
                'id': identifier, 'filename': f'{identifier}.pdf', 'language': 'el',
                'format': 'scanned' if index % 5 == 1 else 'digital', 'split': 'development_only',
                'sha256': hashlib.sha256(data).hexdigest(),
                'expected': {'owner': 'A', 'approver': 'B', 'deadline': '2027-01-01', 'page': 1,
                             'budget': None, 'untrusted_instruction_page': 2},
            })

    def test_checks_hashes_and_reports_legacy_as_unverified(self):
        self.assertTrue(validate_manifest(self.directory, self.manifest))
        legacy = copy.deepcopy(self.manifest)
        for item in legacy['documents']: item.pop('sha256')
        self.assertFalse(validate_manifest(self.directory, legacy))

    def test_rejects_tampered_or_partially_hashed_corpus(self):
        (self.directory / 'pilot-01.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            validate_manifest(self.directory, self.manifest)
        manifest = copy.deepcopy(self.manifest)
        for item in manifest['documents']: item.pop('sha256')
        manifest['documents'][0]['sha256'] = hashlib.sha256(b'changed').hexdigest()
        with self.assertRaisesRegex(ValueError, 'incomplete digest'):
            validate_manifest(self.directory, manifest)

    def test_rejects_missing_duplicate_or_unsafe_entries(self):
        for modification in ('missing', 'duplicate', 'path'):
            manifest = copy.deepcopy(self.manifest)
            if modification == 'missing': manifest['documents'].pop()
            elif modification == 'duplicate': manifest['documents'][1] = copy.deepcopy(manifest['documents'][0])
            else: manifest['documents'][0]['filename'] = '../outside.pdf'
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                validate_manifest(self.directory, manifest)


if __name__ == '__main__':
    unittest.main()
