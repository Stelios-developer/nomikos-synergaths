"""Focused render checks only; these are not cluster or CNI tests."""
from pathlib import Path
import copy
import importlib.util
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/quality'))
spec = importlib.util.spec_from_file_location('k8s_pdf_drill', ROOT / 'scripts/quality/k8s_pdf_drill.py')
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


class PdfDemoManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = subprocess.run(['kubectl', 'kustomize', str(ROOT / 'infra/k8s/pdf-demo')],
                             capture_output=True, text=True, check=True).stdout
        cls.docs = list(yaml.safe_load_all(raw))

    def test_only_expected_synthetic_resources(self):
        actual = {(doc['kind'], doc['metadata']['name']) for doc in self.docs}
        self.assertEqual(actual, {('Namespace', 'nomikos-pdf-demo'), ('ConfigMap', 'scanner-config'),
                                  ('Secret', 'pdf-worker-test-token'), ('Service', 'clamav'),
                                  ('Service', 'pdf-worker'), ('Deployment', 'pdf-scanner'),
                                  ('Deployment', 'pdf-worker'), ('NetworkPolicy', 'deny-default'),
                                  ('NetworkPolicy', 'scanner-flow'), ('NetworkPolicy', 'worker-flow')})
        secret = next(doc for doc in self.docs if doc['kind'] == 'Secret')
        self.assertTrue(secret['stringData']['token'].startswith('synthetic-only-'))

    def test_single_replica_non_root_and_bounded_storage(self):
        for doc in (doc for doc in self.docs if doc['kind'] == 'Deployment'):
            spec = doc['spec']; pod = spec['template']['spec']; context = pod['securityContext']
            self.assertEqual(spec['replicas'], 1)
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertTrue(context['runAsNonRoot'])
            self.assertEqual(context['seccompProfile']['type'], 'RuntimeDefault')
            self.assertTrue(all('hostPath' not in volume for volume in pod['volumes']))
            scratch = next(volume for volume in pod['volumes'] if volume['name'] == 'scratch')
            self.assertIn('sizeLimit', scratch['emptyDir'])
            for container in pod['containers']:
                self.assertEqual(container['imagePullPolicy'], 'Never')
                self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
                self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
                self.assertEqual(container['securityContext']['capabilities']['drop'], ['ALL'])
                self.assertIn('startupProbe', container)
                self.assertIn('readinessProbe', container)
                self.assertIn('livenessProbe', container)
                self.assertIn('ephemeral-storage', container['resources']['limits'])

    def test_drill_remaps_only_expected_resources_and_refuses_extra(self):
        namespace = 'nomikos-ak-123456abcdef'
        docs = drill.prepare(copy.deepcopy(self.docs), namespace)
        self.assertTrue(all(doc['metadata']['name'] == namespace if doc['kind'] == 'Namespace'
                            else doc['metadata']['namespace'] == namespace for doc in docs))
        bad = copy.deepcopy(self.docs)
        bad.append({'kind': 'Secret', 'metadata': {'name': 'unexpected', 'namespace': 'nomikos-pdf-demo'}})
        with self.assertRaisesRegex(ValueError, 'Unexpected PDF demo resources'):
            drill.prepare(bad, namespace)
        bad = copy.deepcopy(self.docs)
        next(doc for doc in bad if doc['kind'] == 'Service')['metadata']['namespace'] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'Unexpected resource namespace'):
            drill.prepare(bad, namespace)


if __name__ == '__main__':
    unittest.main()
