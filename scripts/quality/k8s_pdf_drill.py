"""Run the partial synthetic PDF/scanner slice only in an owned local cluster."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from k8s_local_guard import ROOT, OWNER_LABEL, validate_target
from verify_offline import clean_revision


def execute(args, *, data=None, timeout=180):
    try:
        result = subprocess.run(args, input=data, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Kubernetes command timed out') from exc
    if result.returncode:
        raise RuntimeError('Kubernetes command failed; output withheld')
    return result.stdout


def prepare(documents, namespace):
    expected = {('Namespace', 'nomikos-pdf-demo'), ('ConfigMap', 'scanner-config'),
                ('Secret', 'pdf-worker-test-token'), ('Service', 'clamav'), ('Service', 'pdf-worker'),
                ('Deployment', 'pdf-scanner'), ('Deployment', 'pdf-worker'), ('NetworkPolicy', 'deny-default'),
                ('NetworkPolicy', 'scanner-flow'), ('NetworkPolicy', 'worker-flow')}
    if len(documents) != len(expected) or {(d['kind'], d['metadata']['name']) for d in documents} != expected:
        raise ValueError('Unexpected PDF demo resources')
    for doc in documents:
        meta = doc['metadata']
        if doc['kind'] == 'Namespace':
            meta['name'] = namespace; meta.setdefault('labels', {})[OWNER_LABEL] = namespace
        elif meta.get('namespace') == 'nomikos-pdf-demo':
            meta['namespace'] = namespace
        else:
            raise ValueError('Unexpected resource namespace')
    return documents


def wait_worker_endpoint(k, expected_uid, timeout=90):
    """Wait until the service routes to exactly the expected pod, or none."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        slices = json.loads(execute(k + ['get', 'endpointslices', '-l',
                                        'kubernetes.io/service-name=pdf-worker', '-o', 'json']))
        ready = []
        for item in slices['items']:
            for endpoint in item.get('endpoints', []):
                if endpoint.get('conditions', {}).get('ready') is True:
                    target = endpoint.get('targetRef', {})
                    if target.get('kind') != 'Pod' or not target.get('uid'):
                        raise RuntimeError('Unexpected ready service endpoint')
                    ready.append(target['uid'])
        if sorted(ready) == ([] if expected_uid is None else [expected_uid]):
            return
        time.sleep(1)
    raise RuntimeError('Worker service endpoint did not converge')


def drill(cluster, kubeconfig):
    revision = clean_revision()
    path = validate_target(cluster, kubeconfig)
    k = ['kubectl', '--kubeconfig', str(path), '--context', f'kind-{cluster}', '-n', cluster]
    namespace = json.loads(execute(k + ['get', 'namespace', cluster, '-o', 'json']))
    if namespace['metadata'].get('labels', {}).get(OWNER_LABEL) != cluster:
        raise ValueError('Test namespace is not owned')
    rendered = execute(['kubectl', 'kustomize', str(ROOT / 'infra/k8s/pdf-demo')])
    docs = prepare(list(yaml.safe_load_all(rendered)), cluster)
    data = yaml.safe_dump_all(docs)
    report_dir = ROOT / 'output' / 'verification' / cluster
    report_dir.mkdir(parents=True, exist_ok=False)
    target = report_dir / 'report.json'
    report = {'commit': revision, 'cluster': cluster, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'resources': [f"{d['kind']}/{d['metadata']['name']}" for d in docs], 'steps': [], 'result': 'running',
              'limits': ['partial PDF/scanner slice only, not full application deployment',
                         'local reused image tags; no independently verified source provenance',
                         'bundled scanner signatures were not updated', 'no CNI enforcement, ingress, auth, n8n or production certification',
                         'caller owns cluster cleanup; this drill deletes no namespaces or volumes']}
    def save(): target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    def step(name, args, *, payload=None, timeout=180):
        try:
            output = execute(args, data=payload, timeout=timeout)
        except RuntimeError:
            report['steps'].append({'name': name, 'status': 'failed'}); save(); raise
        report['steps'].append({'name': name, 'status': 'passed'}); save()
        print(f'{name}: passed', flush=True)
        return output
    save()
    try:
        step('schema', k + ['apply', '--dry-run=server', '--validate=strict', '-f', '-'], payload=data)
        step('apply', k + ['apply', '-f', '-'], payload=data)
        for name in ('pdf-scanner', 'pdf-worker'):
            step('ready_' + name, k + ['rollout', 'status', 'deployment/' + name, '--timeout=180s'], timeout=190)
        pods = json.loads(execute(k + ['get', 'pods', '-o', 'json']))['items']
        report['runtime_images'] = [{'pod': pod['metadata']['name'], 'container': c['name'], 'image_id': c.get('imageID', '')}
                                    for pod in pods for c in pod.get('status', {}).get('containerStatuses', [])]
        worker_pods = [pod for pod in pods if pod['metadata'].get('labels', {}).get('app') == 'pdf-worker'
                       and not pod['metadata'].get('deletionTimestamp')]
        if len(worker_pods) != 1:
            raise RuntimeError('Expected exactly one PDF worker pod')
        worker = worker_pods[0]['metadata']['name']
        worker_uid = worker_pods[0]['metadata']['uid']
        wait_worker_endpoint(k, worker_uid)
        report['steps'].append({'name': 'worker_endpoint_ready', 'status': 'passed'}); save()
        client = (ROOT / 'scripts/quality/fixtures/k8s_pdf_client.py').read_text(encoding='utf-8')
        report['client_sha256'] = hashlib.sha256(client.encode('utf-8')).hexdigest()
        step('scanner_and_cdr', k + ['exec', worker, '--', 'python', '-c', client, 'ready'], timeout=300)
        try:
            step('stop_scanner', k + ['scale', 'deployment/pdf-scanner', '--replicas=0'])
            for _ in range(60):
                scanner = json.loads(execute(k + ['get', 'pods', '-l', 'app=pdf-scanner', '-o', 'json']))['items']
                if not scanner: break
                time.sleep(1)
            else: raise RuntimeError('Scanner did not stop')
            step('scanner_unavailable', k + ['exec', worker, '--', 'python', '-c', client, 'scanner_down'], timeout=120)
            wait_worker_endpoint(k, None)
            report['steps'].append({'name': 'worker_endpoint_withdrawn', 'status': 'passed'}); save()
        finally:
            execute(k + ['scale', 'deployment/pdf-scanner', '--replicas=1'])
            execute(k + ['rollout', 'status', 'deployment/pdf-scanner', '--timeout=180s'], timeout=190)
            execute(k + ['rollout', 'status', 'deployment/pdf-worker', '--timeout=180s'], timeout=190)
        step('scanner_recovered', k + ['exec', worker, '--', 'python', '-c', client, 'ready'], timeout=300)
        wait_worker_endpoint(k, worker_uid)
        report['steps'].append({'name': 'worker_endpoint_restored', 'status': 'passed'}); save()
        step('replace_worker', k + ['delete', 'pod', worker, '--wait=true'], timeout=120)
        step('replacement_ready', k + ['rollout', 'status', 'deployment/pdf-worker', '--timeout=180s'], timeout=190)
        pods = json.loads(execute(k + ['get', 'pods', '-l', 'app=pdf-worker', '-o', 'json']))['items']
        replacements = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
        if len(replacements) != 1 or replacements[0]['metadata']['uid'] == worker_uid:
            raise RuntimeError('Expected a single new worker pod')
        replacement = replacements[0]['metadata']
        wait_worker_endpoint(k, replacement['uid'])
        step('replacement_scanner_and_cdr', k + ['exec', replacement['name'], '--', 'python', '-c', client, 'ready'], timeout=300)
        report['result'] = 'passed'
    except (RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report['result'] = 'failed'; report['failure_type'] = type(exc).__name__
    report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat(); save()
    print(f"PDF Kubernetes slice: {report['result']}; report: {target}", flush=True)
    return 0 if report['result'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cluster', required=True); parser.add_argument('--kubeconfig', required=True)
    args = parser.parse_args()
    try:
        return drill(args.cluster, args.kubeconfig)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f'PDF Kubernetes drill refused or failed: {type(exc).__name__}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
