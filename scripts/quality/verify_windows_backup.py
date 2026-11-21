"""Run synthetic backup crypto checks under the current Windows user.

This covers the DPAPI check skipped by the Linux container verifier. It does
not use customer data, access existing backups or prove off-machine recovery.
"""
import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

from verify_offline import ROOT, clean_revision


def main():
    if os.name != 'nt':
        print('Windows current-user DPAPI is required.', file=sys.stderr)
        return 2
    revision = clean_revision()
    run_id = 'windows-backup-' + secrets.token_hex(8)
    folder = ROOT / 'output' / 'verification' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'backend' / 'services' / 'backup_crypto.py'
    tests = ROOT / 'backend' / 'tests' / 'test_backup_crypto.py'
    report = {'commit': revision, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'test_sha256': hashlib.sha256(tests.read_bytes()).hexdigest(), 'python': sys.version.split()[0],
              'cryptography': importlib.metadata.version('cryptography'), 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'result': 'running', 'checks': [], 'limits': ['synthetic data only', 'host dependencies reused; no clean lockfile build',
              'DPAPI key is tied to current Windows user; no off-machine recovery', 'no coordinated restore of real stores']}
    target = folder / 'report.json'
    def save():
        target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    save()
    sys.path.insert(0, str(ROOT / 'backend'))
    try:
        spec = importlib.util.spec_from_file_location('synthetic_backup_tests', tests)
        if spec is None or spec.loader is None:
            raise RuntimeError('Cannot load backup tests')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.test_actual_windows_key_roundtrip_is_not_plaintext()
        report['checks'].append('current_user_dpapi')
        with tempfile.TemporaryDirectory(prefix='nomikos-synthetic-backup-') as directory:
            module.test_backup_roundtrip_crosses_frame_boundaries_without_plaintext_file(Path(directory))
        report['checks'].append('encrypted_roundtrip_and_exclusive_creation')
        for fault in ('truncated', 'missing-end', 'modified', 'wrong-key', 'trailing', 'reordered'):
            module.test_tampered_or_incomplete_backups_fail_closed(fault)
            report['checks'].append('reject_' + fault)
        report['result'] = 'passed'
    except Exception as exc:
        report['result'] = 'failed'; report['failure_type'] = type(exc).__name__
    report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(f"Windows backup verification: {report['result']}; report: {target}")
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
