import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

QUALITY = Path(__file__).parents[1] / 'quality'
sys.path.insert(0, str(QUALITY))
spec = importlib.util.spec_from_file_location('verify_vector_isolated', QUALITY / 'verify_vector_isolated.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class IsolatedCleanupTests(unittest.TestCase):
    def test_scanner_config_uses_linux_line_endings(self):
        self.assertIn(b'TCPSocket 3310\n', verify.SCANNER_CONFIG)
        self.assertNotIn(b'\r', verify.SCANNER_CONFIG)

    def test_daemon_failure_does_not_claim_cleanup_succeeded(self):
        run_id = 'nomikos-vector-' + 'b' * 16
        def fake_run(args, **_kwargs):
            if args[:3] == ['docker', 'image', 'inspect']:
                return 'sha256:' + '1' * 64
            if args[:2] == ['docker', 'info']:
                raise subprocess.CalledProcessError(1, args)
            return ''
        with tempfile.TemporaryDirectory() as temporary, patch.object(verify, 'ROOT', Path(temporary)), \
             patch.object(verify, 'clean_revision', return_value='a' * 40), patch.object(verify, 'pytest_mounts', return_value=[]), \
             patch.object(verify.secrets, 'token_hex', return_value='b' * 16), patch.object(verify, 'run', side_effect=fake_run), \
             patch.object(verify.subprocess, 'run', side_effect=OSError('test failure')):
            self.assertEqual(verify.verify(), 1)
            report = __import__('json').loads((Path(temporary) / 'output' / 'verification' / run_id / 'report.json').read_text())
        self.assertEqual(report['cleanup'], 'unconfirmed')

    def test_timeout_stops_only_owned_test_resources(self):
        run_id = 'nomikos-vector-' + 'a' * 16
        stopped = []
        def fake_run(args, **_kwargs):
            if args[:3] == ['docker', 'image', 'inspect']:
                return 'sha256:' + '1' * 64
            if args[:3] == ['docker', 'ps', '-aq']:
                return 'owned-id' if args[-1] in (f'name=^/{run_id}-db$', f'name=^/{run_id}-setup$') else ''
            if args[:2] == ['docker', 'inspect']:
                return run_id
            if args[:2] == ['docker', 'stop']:
                stopped.append(args[-1]); return ''
            if args[:4] == ['docker', 'network', 'ls', '-q']:
                return 'network-id'
            if args[:3] == ['docker', 'network', 'inspect']:
                return run_id
            return ''
        def fake_subprocess(args, **_kwargs):
            if args[0] == 'git' or args[:2] == ['docker', 'exec']:
                return SimpleNamespace(returncode=0)
            raise subprocess.TimeoutExpired(args, 1)
        with tempfile.TemporaryDirectory() as temporary, patch.object(verify, 'ROOT', Path(temporary)), \
             patch.object(verify, 'clean_revision', return_value='a' * 40), patch.object(verify, 'pytest_mounts', return_value=[]), \
             patch.object(verify, 'extract_archive'), patch.object(verify.secrets, 'token_hex', return_value='a' * 16), \
             patch.object(verify, 'run', side_effect=fake_run), patch.object(verify.subprocess, 'run', side_effect=fake_subprocess):
            self.assertEqual(verify.verify(), 1)
            report = __import__('json').loads((Path(temporary) / 'output' / 'verification' / run_id / 'report.json').read_text())
        self.assertEqual(stopped, [run_id + '-db', run_id + '-setup'])
        self.assertEqual(report['cleanup'], 'confirmed_or_never_created')
        self.assertEqual(report['steps'][0]['status'], 'timeout')


if __name__ == '__main__':
    unittest.main()
