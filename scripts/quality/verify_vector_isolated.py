"""Run synthetic pgvector and durable-job integration tests in disposable containers.

Uses only already available images and an internal Docker network. It never reads
the project's live database credentials or mounts its persistent storage.
"""
import datetime
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys

from verify_offline import ROOT, IMAGE, clean_revision, extract_archive, pytest_mounts, run

PG_IMAGE = 'pgvector/pgvector:0.8.7-pg17'
PASSWORD = 'synthetic-disposable-only'
SETUP = r'''
import psycopg
from db.migrate import migrate
from scripts.database.setup_vector_database import grant_runtime
with psycopg.connect('postgresql://dmc_owner:synthetic-disposable-only@db:5432/dmc', autocommit=True) as conn:
    conn.execute("CREATE ROLE dmc_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD 'synthetic-disposable-only'")
    conn.execute("CREATE ROLE dmc_dispatcher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD 'synthetic-disposable-only'")
    migrate(conn, dimensions=3, model='synthetic-integration')
    grant_runtime(conn)
print('Synthetic schema and restricted roles initialized.')
'''


def verify():
    revision = clean_revision()
    image_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE])
    pg_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', PG_IMAGE])
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', image) for image in (image_id, pg_id)):
        raise ValueError('Expected exact local image IDs')
    mounts = pytest_mounts()
    run_id = 'nomikos-vector-' + secrets.token_hex(8)
    network, container = run_id, run_id + '-db'
    folder = ROOT / 'output' / 'verification' / run_id
    folder.mkdir(parents=True, exist_ok=False)
    source = folder / 'source'; source.mkdir()
    archive = folder / 'source.zip'
    report_path = folder / 'report.json'
    report = {'commit': revision, 'run_id': run_id, 'backend_image': image_id,
              'postgres_image': pg_id, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'result': 'running', 'steps': [], 'cleanup': 'not_started',
              'limits': ['synthetic data only', 'reused local images and host pytest, not a clean signed build',
                         'no auth, PDF worker, n8n, browser, real provider or production certification']}

    def save():
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    def step(name, args, timeout=900):
        args = args[:2] + ['--name', f'{run_id}-{name}', '--label', f'nomikos.local/verify={run_id}'] + args[2:]
        try:
            result = subprocess.run(args, cwd=source, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except subprocess.TimeoutExpired:
            report['steps'].append({'name': name, 'exit_code': None, 'status': 'timeout', 'skips': []})
            save()
            raise
        output = result.stdout + result.stderr
        (folder / (name + '.log')).write_text(output, encoding='utf-8')
        report['steps'].append({'name': name, 'exit_code': result.returncode,
                                'skips': [line.strip() for line in output.splitlines() if line.strip().startswith('SKIPPED')]})
        save()
        if result.returncode:
            raise RuntimeError(f'{name} failed; see local test log')
        print(f'{name}: passed', flush=True)

    save()
    try:
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', f'--output={archive}', revision], check=True, timeout=120)
        extract_archive(archive, source)
        run(['docker', 'network', 'create', '--internal', '--label', f'nomikos.local/verify={run_id}', network])
        run(['docker', 'run', '-d', '--rm', '--pull=never', '--network', network, '--network-alias', 'db',
             '--name', container, '--label', f'nomikos.local/verify={run_id}',
             '-e', 'POSTGRES_USER=dmc_owner', '-e', f'POSTGRES_PASSWORD={PASSWORD}', '-e', 'POSTGRES_DB=dmc', pg_id])
        import time
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'dmc_owner', '-d', 'dmc'], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable PostgreSQL did not become ready')
        base = ['docker', 'run', '--rm', '--pull=never', '--network', network, '--cap-drop=ALL',
                '--security-opt=no-new-privileges', '--mount', f'type=bind,source={source},target=/project,readonly',
                *mounts, '-w', '/project', '-e', 'PYTHONPATH=/testdeps:/project:/project/backend',
                '-e', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'HOME=/tmp',
                '-e', f'DMC_TEST_VECTOR_URL=postgresql://dmc_runtime:{PASSWORD}@db:5432/dmc',
                '-e', f'DMC_TEST_VECTOR_ADMIN_URL=postgresql://dmc_owner:{PASSWORD}@db:5432/dmc',
                '-e', f'DMC_TEST_DISPATCH_URL=postgresql://dmc_dispatcher:{PASSWORD}@db:5432/dmc',
                '--entrypoint', 'python', image_id]
        step('setup', base + ['-c', SETUP])
        step('postgres_integration', base + ['-m', 'pytest', '-p', 'no:cacheprovider', 'backend/integration_tests', '-q', '-rs'])
        report['result'] = 'passed_with_skips' if any(s['skips'] for s in report['steps']) else 'passed'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        report['result'] = 'failed'; report['failure_type'] = type(exc).__name__
        print(f'Isolated integration failed: {type(exc).__name__}', file=sys.stderr)
    finally:
        # Stop only exact generated container names bearing our unique label.
        # A failed daemon connection is not proof of successful cleanup.
        try:
            run(['docker', 'info', '--format', '{{.ServerVersion}}'])
            for name in (container, run_id + '-setup', run_id + '-postgres_integration'):
                found = run(['docker', 'ps', '-aq', '--filter', f'name=^/{name}$'])
                if found:
                    label = run(['docker', 'inspect', '--format', '{{index .Config.Labels "nomikos.local/verify"}}', name])
                    if label != run_id:
                        raise RuntimeError('Container ownership mismatch')
                    run(['docker', 'stop', name], timeout=60)
            found = run(['docker', 'network', 'ls', '-q', '--filter', f'name=^{network}$'])
            if found:
                label = run(['docker', 'network', 'inspect', '--format', '{{index .Labels "nomikos.local/verify"}}', network])
                if label != run_id:
                    raise RuntimeError('Network ownership mismatch')
                run(['docker', 'network', 'rm', network])
        except (RuntimeError, OSError, subprocess.SubprocessError):
            report['cleanup'] = 'unconfirmed'
        if report['cleanup'] == 'not_started':
            report['cleanup'] = 'confirmed_or_never_created'
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    print(f"Result: {report['result']}; cleanup: {report['cleanup']}; report: {report_path}")
    return 0 if report['result'] in ('passed', 'passed_with_skips') and report['cleanup'] == 'confirmed_or_never_created' else 1


if __name__ == '__main__':
    raise SystemExit(verify())
