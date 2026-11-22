import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'quality'))
from verify_release_bundle import unique_object, verify


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'report.json').write_bytes(b'synthetic')
        self.manifest = {'commit': 'a' * 40, 'artifacts': [{'path': 'report.json',
                         'sha256': hashlib.sha256(b'synthetic').hexdigest()}],
                         'checks': [{'id': 'test', 'status': 'passed', 'artifact': 'report.json'}]}

    def test_matching_bundle_and_incomplete_checks(self):
        self.assertEqual(verify(self.root, self.manifest)['result'], 'passed')
        self.manifest['checks'][0]['status'] = 'skipped'
        self.assertEqual(verify(self.root, self.manifest)['result'], 'incomplete')

    def test_tampering_unsafe_paths_and_unreferenced_reports_fail(self):
        variants = []
        for change in ('digest', 'traversal', 'alias', 'missing_check_artifact', 'duplicate_check'):
            data = copy.deepcopy(self.manifest)
            if change == 'digest': data['artifacts'][0]['sha256'] = '0' * 64
            elif change == 'traversal': data['artifacts'][0]['path'] = '../outside'
            elif change == 'alias': data['artifacts'].append({'path': 'REPORT.JSON', 'sha256': '0' * 64})
            elif change == 'missing_check_artifact': data['checks'][0]['artifact'] = 'other.json'
            else: data['checks'].append(copy.deepcopy(data['checks'][0]))
            variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValueError): verify(self.root, data)

    def test_duplicate_json_keys_fail(self):
        with self.assertRaises(ValueError):
            json.loads('{"commit":"one","commit":"two"}', object_pairs_hook=unique_object)

    def test_symlink_artifact_is_rejected(self):
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                verify(self.root, self.manifest)


if __name__ == '__main__':
    unittest.main()
