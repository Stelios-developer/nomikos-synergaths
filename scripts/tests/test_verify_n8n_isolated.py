import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

QUALITY = Path(__file__).parents[1] / 'quality'
sys.path.insert(0, str(QUALITY))
spec = importlib.util.spec_from_file_location('verify_n8n_isolated', QUALITY / 'verify_n8n_isolated.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class WorkflowIsolationTests(unittest.TestCase):
    def test_cleanup_refuses_foreign_volume_and_reports_unconfirmed(self):
        run_id = 'nomikos-n8n-' + 'a' * 16
        calls = []
        def fake_run(args, **_kwargs):
            calls.append(args)
            if args[:3] == ['docker', 'image', 'inspect']:
                return 'sha256:' + '1' * 64
            if args[:4] == ['docker', 'volume', 'ls', '-q']:
                return 'volume-present'
            if args[:3] == ['docker', 'volume', 'inspect']:
                return 'foreign-owner'
            return ''
        with tempfile.TemporaryDirectory() as temporary, patch.object(verify, 'ROOT', Path(temporary)), \
             patch.object(verify, 'clean_revision', return_value='a' * 40), \
             patch.object(verify.secrets, 'token_hex', return_value='a' * 16), \
             patch.object(verify, 'run', side_effect=fake_run), \
             patch.object(verify.subprocess, 'run', side_effect=OSError('synthetic setup failure')):
            self.assertEqual(verify.main(), 1)
            report = json.loads((Path(temporary) / 'output' / 'verification' / run_id / 'report.json').read_text())
        self.assertEqual(report['cleanup'], 'unconfirmed')
        self.assertFalse(any(args[:3] == ['docker', 'volume', 'rm'] for args in calls))

    def workflow(self):
        return {'id': 'nexusAgentOrchestrator', 'active': True, 'pinData': {'sensitive': 'fixture'}, 'nodes': [
            {'name': 'Start', 'type': 'n8n-nodes-base.httpRequest',
             'parameters': {'url': 'http://host.docker.internal:8000/integrations/n8n/cases/start'}},
            {'name': 'Finalize human-review pack', 'type': 'n8n-nodes-base.httpRequest',
             'parameters': {'url': 'http://host.docker.internal:8000/integrations/n8n/cases/finalize'}},
            {'name': 'Finalize verified action pack', 'type': 'n8n-nodes-base.httpRequest',
             'parameters': {'url': 'http://host.docker.internal:8000/integrations/n8n/cases/finalize'}}]}

    def test_rewrites_to_mock_and_distinguishes_review_branch(self):
        value = verify.synthetic_workflow(self.workflow())
        self.assertFalse(value['active']); self.assertEqual(value['pinData'], {})
        urls = [node['parameters']['url'] for node in value['nodes']]
        self.assertTrue(all(url.startswith('http://mock-backend:8000/') for url in urls))
        self.assertTrue(urls[1].endswith('?fixture_branch=review'))
        self.assertTrue(urls[2].endswith('?fixture_branch=verified'))

    def test_rejects_unexpected_http_destination_and_workflow(self):
        for url in ('https://example.test/', 'http://host.docker.internal:8001/anything', None):
            value = copy.deepcopy(self.workflow()); value['nodes'][0]['parameters']['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                verify.synthetic_workflow(value)
        with self.assertRaises(ValueError):
            verify.synthetic_workflow({'id': 'other', 'nodes': []})
        with self.assertRaises(ValueError):
            verify.synthetic_workflow({'id': 'nexusAgentOrchestrator', 'nodes': []})

    def test_rejects_unexpected_nodes_and_credentials(self):
        for extra in ({'type': 'n8n-nodes-base.executeCommand'},
                      {'type': 'n8n-nodes-base.httpRequest', 'credentials': {'api': {'id': 'foreign'}}},
                      None):
            value = copy.deepcopy(self.workflow())
            value['nodes'].append(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                verify.synthetic_workflow(value)


if __name__ == '__main__':
    unittest.main()
