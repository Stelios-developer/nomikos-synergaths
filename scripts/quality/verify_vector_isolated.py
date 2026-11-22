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
AUTH_IMAGE = 'dmc-release-review-auth:latest'
PDF_IMAGE = 'dmc-release-review-pdf:latest'
SCANNER_IMAGE = 'clamav/clamav:1.5.4'
PASSWORD = 'synthetic-disposable-only'
SCANNER_CONFIG = b'TCPSocket 3310\nTCPAddr 0.0.0.0\nDatabaseDirectory /var/lib/clamav\nTemporaryDirectory /tmp\n'
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
    auth_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', AUTH_IMAGE])
    pdf_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', PDF_IMAGE])
    scanner_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', SCANNER_IMAGE])
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', image) for image in (image_id, pg_id, auth_id, pdf_id, scanner_id)):
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
              'postgres_image': pg_id, 'auth_image': auth_id, 'pdf_image': pdf_id, 'scanner_image': scanner_id,
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'result': 'running', 'steps': [], 'cleanup': 'not_started',
              'limits': ['synthetic data only', 'reused local images and host pytest, not a clean signed build',
                         'synthetic auth with verification email disabled; not a live HTTP browser flow',
                         'PDF ingress client, worker and scanner use a synthetic HTTP path; not a full authenticated upload',
                         'OCR timeout mocked',
                         'scanner uses bundled local signatures, not a current signature-update check',
                         'no integrated upload, n8n, browser, real provider or production certification']}

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

    def exchange(name, args, payload, *, json_output=False):
        # Cookies and test credentials stay in memory and must never enter logs.
        args = args[:2] + ['--name', f'{run_id}-{name}', '--label', f'nomikos.local/verify={run_id}', '-i'] + args[2:]
        try:
            result = subprocess.run(args, cwd=source, input=json.dumps(payload), capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=120)
        except subprocess.TimeoutExpired:
            report['steps'].append({'name': name, 'exit_code': None, 'status': 'timeout', 'skips': []})
            save()
            raise
        report['steps'].append({'name': name, 'exit_code': result.returncode, 'skips': []})
        save()
        if result.returncode:
            raise RuntimeError(f'{name} failed; sensitive subprocess output withheld')
        try:
            value = json.loads(result.stdout.splitlines()[-1]) if json_output else None
        except (ValueError, IndexError) as exc:
            raise RuntimeError(f'{name} returned invalid output') from exc
        print(f'{name}: passed', flush=True)
        return value

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
        secret = secrets.token_urlsafe(48)
        uri = f'postgresql://dmc_owner:{PASSWORD}@db:5432/dmc'
        auth = ['docker', 'run', '--rm', '--pull=never', '--network', network, '--cap-drop=ALL',
                '--security-opt=no-new-privileges', '--mount', f'type=bind,source={source / "auth-service" / "src"},target=/app/src,readonly',
                '--mount', f'type=bind,source={source / "scripts" / "quality" / "fixtures" / "synthetic_auth.mjs"},target=/app/synthetic_auth.mjs,readonly',
                '-w', '/app', '-e', f'DATABASE_URL={uri}', '-e', f'BETTER_AUTH_SECRET={secret}',
                '-e', 'APP_ENV=development', '-e', 'NODE_ENV=development', '-e', 'APP_ORIGIN=http://127.0.0.1:5174',
                '-e', 'BETTER_AUTH_URL=http://127.0.0.1:3002', '-e', 'REQUIRE_EMAIL_VERIFICATION=false',
                '-e', 'HOME=/tmp', '--entrypoint', 'node', auth_id, '--import', 'tsx', '/app/synthetic_auth.mjs']
        auth_backend = base[:base.index('--entrypoint')] + [
            '-e', f'DATABASE_URL={uri}', '-e', f'BETTER_AUTH_SECRET={secret}',
            '-e', 'AUTH_REQUIRED=true', '-e', 'REQUIRE_VERIFIED_EMAIL=false',
        ] + base[base.index('--entrypoint'):] + ['/project/scripts/quality/fixtures/synthetic_auth_backend.py']
        users = exchange('auth_create', auth, {'phase': 'create', 'password': secrets.token_urlsafe(24)}, json_output=True)['users']
        if not isinstance(users, list) or len(users) != 2:
            raise RuntimeError('Synthetic auth did not produce exactly two users')
        exchange('auth_active', auth_backend, {'phase': 'active', 'users': users})
        exchange('auth_expire', auth_backend, {'phase': 'expired_first', 'users': users})
        exchange('auth_signout', auth, {'phase': 'signout', 'users': [users[1]]}, json_output=True)
        exchange('auth_revoked', auth_backend, {'phase': 'revoked', 'users': users})
        pdf = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only', '--cap-drop=ALL',
               '--security-opt=no-new-privileges', '--pids-limit', '64', '--memory', '1g', '--cpus', '2',
               '--tmpfs', '/tmp:rw,nosuid,noexec,size=96m',
               '--mount', f'type=bind,source={source / "security" / "pdf_worker" / "app.py"},target=/app/app.py,readonly',
               '--mount', f'type=bind,source={source / "security" / "pdf_worker" / "pdf_task.py"},target=/app/pdf_task.py,readonly',
               '--mount', f'type=bind,source={source / "scripts" / "quality" / "fixtures" / "synthetic_pdf_worker.py"},target=/app/synthetic_pdf_worker.py,readonly',
               '-w', '/app', '-e', 'CLAMAV_HOST=127.0.0.1', '-e', 'CLAMAV_PORT=1',
               '-e', 'PDF_SECURITY_TOKEN=synthetic-only-token-at-least-32-characters', '--entrypoint', 'python', pdf_id,
               '/app/synthetic_pdf_worker.py']
        step('pdf_worker', pdf, timeout=300)
        scanner_config = folder / 'clamd.conf'
        scanner_config.write_bytes(SCANNER_CONFIG)
        scanner_name = run_id + '-scanner'
        run(['docker', 'run', '-d', '--rm', '--pull=never', '--network', network, '--network-alias', 'clamav',
             '--name', scanner_name, '--label', f'nomikos.local/verify={run_id}', '--read-only',
             '--user', '100:101', '--cap-drop=ALL', '--security-opt=no-new-privileges',
             '--pids-limit', '128', '--memory', '2g', '--tmpfs', '/tmp:rw,nosuid,noexec,size=128m',
             '--mount', f'type=bind,source={scanner_config},target=/tmp/isolated-clamd.conf,readonly',
             '--entrypoint', 'clamd', scanner_id, '--foreground', '--config-file=/tmp/isolated-clamd.conf'])
        for _ in range(150):
            alive = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', scanner_name], capture_output=True, text=True)
            if alive.returncode != 0 or alive.stdout.strip() != 'true':
                raise RuntimeError('Disposable scanner exited during startup')
            ready = subprocess.run(['docker', 'exec', scanner_name, 'sh', '-c', 'echo PING | nc -w 2 127.0.0.1 3310'], capture_output=True)
            if ready.returncode == 0 and ready.stdout.strip() == b'PONG':
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable scanner did not become ready')
        scanner_worker = ['docker', 'run', '--rm', '--pull=never', '--network', network, '--read-only', '--cap-drop=ALL',
                          '--security-opt=no-new-privileges', '--pids-limit', '64', '--memory', '1g', '--cpus', '2',
                          '--tmpfs', '/tmp:rw,nosuid,noexec,size=96m',
                          '--mount', f'type=bind,source={source / "security" / "pdf_worker" / "app.py"},target=/app/app.py,readonly',
                          '--mount', f'type=bind,source={source / "security" / "pdf_worker" / "pdf_task.py"},target=/app/pdf_task.py,readonly',
                          '--mount', f'type=bind,source={source / "scripts" / "quality" / "fixtures" / "synthetic_scanner_worker.py"},target=/app/synthetic_scanner_worker.py,readonly',
                          '-w', '/app', '-e', 'CLAMAV_HOST=clamav', '-e', 'CLAMAV_PORT=3310',
                          '-e', 'PDF_SECURITY_TOKEN=synthetic-only-token-at-least-32-characters', '--entrypoint', 'python', pdf_id,
                          '/app/synthetic_scanner_worker.py']
        step('scanner_worker', scanner_worker, timeout=300)
        worker_name = run_id + '-http-worker'
        run(['docker', 'run', '-d', '--rm', '--pull=never', '--network', network, '--network-alias', 'pdf-worker',
             '--name', worker_name, '--label', f'nomikos.local/verify={run_id}', '--read-only', '--cap-drop=ALL',
             '--security-opt=no-new-privileges', '--pids-limit', '64', '--memory', '1g', '--cpus', '2',
             '--tmpfs', '/tmp:rw,nosuid,noexec,size=96m',
             '--mount', f'type=bind,source={source / "security" / "pdf_worker" / "app.py"},target=/app/app.py,readonly',
             '--mount', f'type=bind,source={source / "security" / "pdf_worker" / "pdf_task.py"},target=/app/pdf_task.py,readonly',
             '-w', '/app', '-e', 'CLAMAV_HOST=clamav', '-e', 'CLAMAV_PORT=3310',
             '-e', 'PDF_SECURITY_TOKEN=synthetic-only-token-at-least-32-characters', '--entrypoint', 'python', pdf_id,
             '-m', 'uvicorn', 'app:app', '--host', '0.0.0.0', '--port', '8080', '--workers', '1'])
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', worker_name, 'python', '-c',
                                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable PDF HTTP worker did not become ready')
        client = base[:base.index('--entrypoint')] + [
            '-e', 'APP_ENV=production', '-e', 'PDF_SECURITY_URL=http://pdf-worker:8080',
            '-e', 'PDF_SECURITY_TOKEN=synthetic-only-token-at-least-32-characters',
        ] + base[base.index('--entrypoint'):] + ['/project/scripts/quality/fixtures/synthetic_pdf_http.py']
        step('pdf_http_ready', client + ['ready'], timeout=300)
        # Scanner is test-owned and deliberately stopped to check fail-closed ingress.
        run(['docker', 'stop', scanner_name], timeout=60)
        step('pdf_http_scanner_down', client + ['scanner_down'], timeout=180)
        step('postgres_integration', base + ['-m', 'pytest', '-p', 'no:cacheprovider', 'backend/integration_tests', '-q', '-rs'])
        report['result'] = 'passed_with_skips' if any(s['skips'] for s in report['steps']) else 'passed'
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, IndexError, subprocess.SubprocessError) as exc:
        report['result'] = 'failed'; report['failure_type'] = type(exc).__name__
        print(f'Isolated integration failed: {type(exc).__name__}', file=sys.stderr)
    finally:
        # Stop only exact generated container names bearing our unique label.
        # A failed daemon connection is not proof of successful cleanup.
        try:
            run(['docker', 'info', '--format', '{{.ServerVersion}}'])
            for name in (container, *(run_id + '-' + part for part in ('setup', 'auth_create', 'auth_active', 'auth_expire', 'auth_signout', 'auth_revoked', 'pdf_worker', 'scanner_worker', 'http-worker', 'pdf_http_ready', 'pdf_http_scanner_down', 'scanner', 'postgres_integration'))):
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
