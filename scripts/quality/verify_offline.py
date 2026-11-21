"""Verify a committed synthetic snapshot offline; this is not a release gate."""
import argparse
import datetime
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'dmc-release-review-backend:langgraph-1214'


def run(args, *, cwd=None, timeout=120):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, check=True).stdout.strip()


def clean_revision():
    if run(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=normal']):
        raise ValueError('Commit or otherwise resolve working-tree changes first')
    revision = run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'])
    if not re.fullmatch(r'[0-9a-f]{40,64}', revision):
        raise ValueError('Invalid Git revision')
    return revision


def extract_archive(archive, destination):
    with zipfile.ZipFile(archive) as contents:
        for item in contents.infolist():
            name = item.filename
            target = (destination / name).resolve()
            mode = (item.external_attr >> 16) & 0o170000
            if (name.startswith(('/', '\\')) or '\\' in name or mode == 0o120000
                    or not target.is_relative_to(destination.resolve())):
                raise ValueError('Unsafe archive entry')
        contents.extractall(destination)


def pytest_mounts():
    """Mount only pure pytest packages, not the host's entire site-packages."""
    mounts = []
    for module in ('pytest', '_pytest', 'pluggy', 'iniconfig', 'packaging', 'py'):
        spec = importlib.util.find_spec(module)
        if spec is None or not spec.origin:
            raise ValueError(f'Missing local pytest dependency: {module}')
        path = Path(spec.origin).resolve()
        source = path.parent if path.name == '__init__.py' else path
        target = f'/testdeps/{module}' + ('.py' if source.is_file() else '')
        mounts += ['--mount', f'type=bind,source={source},target={target},readonly']
    return mounts


def verify(image=IMAGE):
    revision = clean_revision()
    image_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image])
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
        raise ValueError('Expected an exact local Docker image ID')
    mounts = pytest_mounts()
    try:
        pytest_version = importlib.metadata.version('pytest')
    except importlib.metadata.PackageNotFoundError:
        pytest_version = 'unavailable'
    run_id = 'offline-verify-' + secrets.token_hex(8)
    folder = ROOT / 'output' / 'verification' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    source = folder / 'source'; source.mkdir()
    archive = folder / 'source.zip'
    report_path = folder / 'report.json'
    report = {'schema': 1, 'commit': revision, 'image_id': image_id, 'run_id': run_id,
              'host_python': sys.version.split()[0], 'host_pytest': pytest_version,
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': [],
              'limits': ['local synthetic tests only', 'container image and host pytest are reused, not a clean lockfile build',
                         'no Kubernetes, real provider, real documents, browser or production certification']}
    def save():
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    def step(name, command, cwd, timeout=900):
        print(f'Running {name}...', flush=True)
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=timeout)
            output = result.stdout + result.stderr
            status, code = ('passed' if result.returncode == 0 else 'failed'), result.returncode
        except subprocess.TimeoutExpired as exc:
            output = 'Timed out; inspect the uniquely labelled test container before cleanup.\n'
            status, code = 'timeout', None
        (folder / f'{name}.log').write_text(output, encoding='utf-8')
        skips = [line.strip() for line in output.splitlines() if line.strip().startswith('SKIPPED')]
        report['steps'].append({'name': name, 'status': status, 'exit_code': code, 'skips': skips,
                                'log': f'{name}.log'})
        save(); print(f'{name}: {status}', flush=True)
    save()
    try:
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', f'--output={archive}', revision], check=True, timeout=120)
        extract_archive(archive, source)
        report['lockfile_sha256'] = {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                     for name in ('backend/requirements-linux-py312.lock', 'backend/requirements-test.lock')}
        for name, pattern, directory in [('evaluation_unit', 'test*.py', 'backend/evaluation'),
                                         ('k8s_guard_unit', 'test_k8s_local_guard.py', 'scripts/tests'),
                                         ('verification_unit', 'test_verify_*.py', 'scripts/tests')]:
            step(name, [sys.executable, '-m', 'unittest', 'discover', '-s', directory, '-p', pattern, '-v'], source)
        container_name = 'nomikos-' + run_id
        command = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--name', container_name,
                   '--label', f'nomikos.local/verify={run_id}', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   '--mount', f'type=bind,source={source},target=/project,readonly', *mounts,
                   '-w', '/project/backend', '-e', 'PYTHONPATH=/testdeps:/project/backend',
                   '-e', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'HOME=/tmp',
                   '--entrypoint', 'python', image_id, '-m', 'pytest', '-p', 'no:cacheprovider', 'tests', '-q', '-rs']
        step('backend_unit', command, source)
        if report['steps'][-1]['status'] == 'timeout':
            # A timeout can leave a container running. Stop only the exact
            # generated name after checking its ownership label.
            try:
                label = run(['docker', 'inspect', '--format', '{{index .Config.Labels "nomikos.local/verify"}}', container_name])
                if label == run_id:
                    run(['docker', 'stop', container_name], timeout=60)
            except (OSError, subprocess.SubprocessError):
                report['limits'].append('Timed-out test container cleanup was not confirmed; inspect it manually.')
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report['result'] = 'failed' if any(item['status'] != 'passed' for item in report['steps']) else 'passed_with_skips' if any(item['skips'] for item in report['steps']) else 'passed'
        save(); print(f"Verification {report['result']}; report: {report_path}", flush=True)
        return 1 if report['result'] == 'failed' else 0
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile):
        report['result'] = 'setup_failed'; save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default=IMAGE, help='existing local backend image; no pull is performed')
    args = parser.parse_args()
    try:
        return verify(args.image)
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f'Offline verification could not complete: {type(exc).__name__}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
