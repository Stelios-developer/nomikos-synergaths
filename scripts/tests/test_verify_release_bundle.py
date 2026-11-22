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
        raw = json.dumps({'commit': 'a' * 40, 'result': 'passed'}).encode()
        (self.root / 'report.json').write_bytes(raw)
        self.manifest = {'commit': 'a' * 40, 'artifacts': [{'path': 'report.json',
                         'sha256': hashlib.sha256(raw).hexdigest()}],
                         'checks': [{'id': 'test', 'status': 'passed', 'artifact': 'report.json'}]}

    def test_matching_bundle_and_incomplete_checks(self):
        self.assertEqual(verify(self.root, self.manifest, ['test'])['result'], 'passed')
        self.manifest['checks'][0]['status'] = 'skipped'
        self.assertEqual(verify(self.root, self.manifest, ['test'])['result'], 'incomplete')

    def test_required_check_cannot_be_silently_omitted(self):
        report = verify(self.root, self.manifest, ['test', 'browser'])
        self.assertEqual(report['result'], 'incomplete')
        self.assertEqual(report['missing_required_checks'], ['browser'])
        for required in ([], ['test', 'test'], ['invalid id']):
            with self.subTest(required=required), self.assertRaises(ValueError):
                verify(self.root, self.manifest, required)

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
            with self.subTest(data=data), self.assertRaises(ValueError): verify(self.root, data, ['test'])

    def test_duplicate_json_keys_fail(self):
        with self.assertRaises(ValueError):
            json.loads('{"commit":"one","commit":"two"}', object_pairs_hook=unique_object)

    def test_symlink_artifact_is_rejected(self):
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                verify(self.root, self.manifest, ['test'])

    def test_cannot_declare_a_failed_or_other_commit_report_as_passed(self):
        for commit, result in (('a' * 40, 'failed'), ('b' * 40, 'passed'), ('a' * 40, 'passed_with_skips')):
            raw = json.dumps({'commit': commit, 'result': result}).encode()
            (self.root / 'report.json').write_bytes(raw)
            manifest = copy.deepcopy(self.manifest)
            manifest['artifacts'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
            with self.subTest(commit=commit, result=result), self.assertRaises(ValueError):
                verify(self.root, manifest, ['test'])


if __name__ == '__main__':
    unittest.main()
