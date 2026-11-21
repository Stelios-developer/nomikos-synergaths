"""Exercise the real n8n workflow with a synthetic local backend, never a provider."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from verify_offline import ROOT, IMAGE, clean_revision, extract_archive, run

N8N_IMAGE = 'n8nio/n8n:2.42.7'
PREFIX = 'http://host.docker.internal:8000/'


def synthetic_workflow(workflow):
    if not isinstance(workflow, dict) or workflow.get('id') != 'nexusAgentOrchestrator':
        raise ValueError('Unexpected workflow')
    count = 0
    for node in workflow.get('nodes', []):
        if node.get('type') == 'n8n-nodes-base.httpRequest':
            parameters = node.get('parameters', {})
            url = parameters.get('url')
            if not isinstance(url, str) or not url.startswith(PREFIX):
                raise ValueError('Unexpected workflow HTTP destination')
            parameters['url'] = 'http://mock-backend:8000/' + url[len(PREFIX):]
            if node.get('name') == 'Finalize human-review pack':
                parameters['url'] += '?fixture_branch=review'
            elif node.get('name') == 'Finalize verified action pack':
                parameters['url'] += '?fixture_branch=verified'
            count += 1
    if not count:
        raise ValueError('Workflow has no integration HTTP nodes')
    workflow['active'] = False
    workflow['pinData'] = {}
    return workflow


def main():
    revision = clean_revision()
    image_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE])
    n8n_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', N8N_IMAGE])
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', x) for x in (image_id, n8n_id)):
        raise ValueError('Expected exact local image IDs')
    run_id = 'nomikos-n8n-' + secrets.token_hex(8)
    network, volume = run_id, run_id + '-state'
    folder = ROOT / 'output' / 'verification' / run_id; folder.mkdir(parents=True, exist_ok=False)
    source = folder / 'source'; source.mkdir()
    archive = folder / 'source.zip'; workflow_file = folder / 'synthetic-workflow.json'
    target = folder / 'report.json'
    report = {'commit': revision, 'run_id': run_id, 'backend_image': image_id, 'n8n_image': n8n_id,
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': [],
              'result': 'running', 'cleanup': 'not_started',
              'limits': ['synthetic local mock endpoints, no PDF, AI provider or production data',
                         'workflow HTTP destinations rewritten to an isolated synthetic backend; finalize branches carry test-only markers',
                         'reused local images, no signed provenance or deployed-system certification']}
    def save(): target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    def step(name, args, timeout=180):
        args = args[:2] + ['--name', f'{run_id}-{name}', '--label', f'nomikos.local/verify={run_id}'] + args[2:]
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except subprocess.TimeoutExpired:
            report['steps'].append({'name': name, 'status': 'timeout'}); save(); raise
        report['steps'].append({'name': name, 'status': 'passed' if result.returncode == 0 else 'failed', 'exit_code': result.returncode})
        # n8n logs can contain request metadata; keep outputs out of reports.
        save()
        if result.returncode:
            if name == 'workflow':
                for line in result.stdout.splitlines():
                    if re.fullmatch(r'diagnostic: [a-z_]+ [A-Za-z0-9_]+', line):
                        print(line, file=sys.stderr)
            raise RuntimeError(f'{name} failed; subprocess output withheld')
        print(f'{name}: passed', flush=True)
    save()
    try:
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', f'--output={archive}', revision], check=True, timeout=120)
        extract_archive(archive, source)
        original = (source / 'n8n' / 'agent-orchestrator.workflow.json').read_bytes()
        workflow = json.loads(original.decode('utf-8-sig'))
        workflow_file.write_text(json.dumps(synthetic_workflow(workflow), ensure_ascii=False), encoding='utf-8')
        report['original_workflow_sha256'] = hashlib.sha256(original).hexdigest()
        report['test_workflow_sha256'] = hashlib.sha256(workflow_file.read_bytes()).hexdigest()
        report['fixture_sha256'] = {name: hashlib.sha256((source / 'scripts' / 'quality' / 'fixtures' / name).read_bytes()).hexdigest()
                                    for name in ('synthetic_n8n_backend.py', 'synthetic_n8n_client.py')}
        save()
        run(['docker', 'network', 'create', '--internal', '--label', f'nomikos.local/verify={run_id}', network])
        run(['docker', 'volume', 'create', '--label', f'nomikos.local/verify={run_id}', volume])
        common = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--memory', '1g', '--pids-limit', '128',
                  '--mount', f'type=volume,source={volume},target=/home/node/.n8n',
                  '--mount', f'type=bind,source={workflow_file},target=/work/workflow.json,readonly',
                  '-e', 'N8N_ENCRYPTION_KEY=synthetic-only-test-key-32-characters',
                  '-e', 'N8N_DIAGNOSTICS_ENABLED=false', '-e', 'N8N_PERSONALIZATION_ENABLED=false',
                  '--entrypoint', 'n8n', n8n_id]
        step('import', common + ['import:workflow', '--input=/work/workflow.json'])
        step('publish', common + ['publish:workflow', '--id=nexusAgentOrchestrator'])
        run(['docker', 'run', '-d', '--rm', '--pull=never', '--network', network, '--network-alias', 'mock-backend',
             '--name', run_id + '-mock', '--label', f'nomikos.local/verify={run_id}', '--cap-drop=ALL',
             '--security-opt=no-new-privileges', '--memory', '256m', '--pids-limit', '64',
             '--mount', f'type=bind,source={source},target=/project,readonly',
             '--entrypoint', 'python', image_id, '/project/scripts/quality/fixtures/synthetic_n8n_backend.py'])
        run(['docker', 'run', '-d', '--rm', '--pull=never', '--network', network, '--network-alias', 'n8n',
             '--name', run_id + '-server', '--label', f'nomikos.local/verify={run_id}',
             '--memory', '1g', '--pids-limit', '128', '--cap-drop=ALL', '--security-opt=no-new-privileges',
             '--mount', f'type=volume,source={volume},target=/home/node/.n8n',
             '-e', 'N8N_ENCRYPTION_KEY=synthetic-only-test-key-32-characters', '-e', 'N8N_HOST=n8n',
             '-e', 'N8N_SECURE_COOKIE=false', '-e', 'N8N_DIAGNOSTICS_ENABLED=false',
             '-e', 'N8N_PERSONALIZATION_ENABLED=false', '-e', 'N8N_COMMUNITY_PACKAGES_ENABLED=false',
             '-e', 'N8N_TEMPLATES_ENABLED=false', '-e', 'N8N_BLOCK_ENV_ACCESS_IN_NODE=true',
             '-e', 'EXECUTIONS_DATA_SAVE_ON_SUCCESS=none', '-e', 'EXECUTIONS_DATA_SAVE_ON_ERROR=none', n8n_id])
        for _ in range(120):
            probe = subprocess.run(['docker', 'exec', run_id + '-server', 'node', '-e',
                                    "fetch('http://127.0.0.1:5678/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"], capture_output=True)
            if probe.returncode == 0: break
            time.sleep(1)
        else: raise RuntimeError('Isolated n8n did not become ready')
        client = ['docker', 'run', '--rm', '--pull=never', '--network', network, '--cap-drop=ALL',
                  '--security-opt=no-new-privileges', '--mount', f'type=bind,source={source},target=/project,readonly',
                  '-e', 'PYTHONPATH=/project/backend', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                  '-e', 'N8N_ORCHESTRATOR_URL=http://n8n:5678/webhook/nexus-agent-orchestrator/case',
                  '-e', 'N8N_WEBHOOK_API_KEY=synthetic-only-key', '--entrypoint', 'python', image_id,
                  '/project/scripts/quality/fixtures/synthetic_n8n_client.py']
        step('workflow', client, timeout=180)
        report['result'] = 'passed'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        report['result'] = 'failed'; report['failure_type'] = type(exc).__name__
        print(f'Isolated n8n check failed: {type(exc).__name__}', file=sys.stderr)
    finally:
        try:
            run(['docker', 'info', '--format', '{{.ServerVersion}}'])
            for part in ('workflow', 'server', 'mock', 'publish', 'import'):
                name = run_id + '-' + part
                if run(['docker', 'ps', '-aq', '--filter', f'name=^/{name}$']):
                    if run(['docker', 'inspect', '--format', '{{index .Config.Labels "nomikos.local/verify"}}', name]) != run_id:
                        raise RuntimeError('Container ownership mismatch')
                    run(['docker', 'stop', name], timeout=60)
            if run(['docker', 'network', 'ls', '-q', '--filter', f'name=^{network}$']):
                if run(['docker', 'network', 'inspect', '--format', '{{index .Labels "nomikos.local/verify"}}', network]) != run_id:
                    raise RuntimeError('Network ownership mismatch')
                run(['docker', 'network', 'rm', network])
            if run(['docker', 'volume', 'ls', '-q', '--filter', f'name=^{volume}$']):
                if run(['docker', 'volume', 'inspect', '--format', '{{index .Labels "nomikos.local/verify"}}', volume]) != run_id:
                    raise RuntimeError('Volume ownership mismatch')
                run(['docker', 'volume', 'rm', volume])
            report['cleanup'] = 'confirmed_or_never_created'
        except (RuntimeError, OSError, subprocess.SubprocessError):
            report['cleanup'] = 'unconfirmed'
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat(); save()
    print(f"n8n integration: {report['result']}; cleanup: {report['cleanup']}; report: {target}")
    return 0 if report['result'] == 'passed' and report['cleanup'] == 'confirmed_or_never_created' else 1


if __name__ == '__main__':
    raise SystemExit(main())
