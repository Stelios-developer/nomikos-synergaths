import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('guard', Path(__file__).parents[1] / 'k8s_local_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class LocalTargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cluster = 'nomikos-ak-abcdef123456'
        self.folder = self.root / 'output' / 'k8s'
        self.folder.mkdir(parents=True)
        self.config = self.folder / f'{self.cluster}.kubeconfig'
        self.config.write_text('test-only', encoding='utf-8')
        self.view = {'clusters': [{'cluster': {'server': 'https://127.0.0.1:12345'}}]}
        self.bindings = [{'HostIp': '127.0.0.1', 'HostPort': '12345'}]
        self.namespace = {'metadata': {'name': self.cluster, 'labels': {guard.OWNER_LABEL: self.cluster}}}

    def run_guard(self, responses, cluster=None, config=None):
        with patch.object(guard, 'ROOT', self.root), patch.object(guard, 'execute', side_effect=responses):
            return guard.validate_target(cluster or self.cluster, config or self.config)

    def test_accepts_owned_loopback_target(self):
        result = self.run_guard([self.cluster, json.dumps(self.view), json.dumps(self.bindings), json.dumps(self.namespace)])
        self.assertEqual(result, self.config.resolve())

    def test_rejects_unowned_or_remote_targets(self):
        with self.assertRaises(ValueError):
            self.run_guard(['another-cluster'])
        self.view['clusters'][0]['cluster']['server'] = 'https://example.test:6443'
        with self.assertRaises(ValueError):
            self.run_guard([self.cluster, json.dumps(self.view)])
        self.view['clusters'][0]['cluster']['server'] = 'https://127.0.0.1:12345'
        self.namespace['metadata']['labels'] = {}
        with self.assertRaises(ValueError):
            self.run_guard([self.cluster, json.dumps(self.view), json.dumps(self.bindings), json.dumps(self.namespace)])

    def test_rejects_loopback_api_pointing_to_another_container(self):
        bindings = [{'HostIp': '127.0.0.1', 'HostPort': '23456'}]
        with self.assertRaisesRegex(ValueError, 'control-plane port'):
            self.run_guard([self.cluster, json.dumps(self.view), json.dumps(bindings)])

    def test_rejects_other_project_or_arbitrary_config_before_docker(self):
        outside = self.root / 'outside.kubeconfig'
        outside.write_text('test-only', encoding='utf-8')
        with patch.object(guard, 'ROOT', self.root), patch.object(guard, 'execute') as execute:
            with self.assertRaises(ValueError):
                guard.validate_target('padel-local', self.config)
            with self.assertRaises(ValueError):
                guard.validate_target(self.cluster, outside)
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
