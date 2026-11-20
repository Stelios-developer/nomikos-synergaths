"""Read-only preflight for a future isolated legal-workspace Kubernetes drill.

This does not create a cluster, namespace, deployment, secret, or test data.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OWNER_LABEL = 'nomikos.local/cluster'


def execute(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        # Never echo credentials, kubeconfig contents or command stderr.
        raise RuntimeError('Local Kubernetes preflight command failed') from exc
    return result.stdout


def validate_target(cluster, kubeconfig):
    if not re.fullmatch(r'nomikos-ak-[a-f0-9]{12}', cluster):
        raise ValueError('Expected a unique nomikos-ak-* local test cluster')
    parent = (ROOT / 'output' / 'k8s').resolve()
    if not parent.is_relative_to(ROOT.resolve()):
        raise ValueError('Test kubeconfig directory must remain in this repository')
    candidate = Path(kubeconfig)
    if candidate.is_symlink():
        raise ValueError('Kubeconfig must not be a symlink')
    path = candidate.resolve(strict=True)
    if path.parent != parent or path.name != f'{cluster}.kubeconfig' or not path.is_file():
        raise ValueError('Expected the dedicated ignored test kubeconfig')
    label = execute(['docker', 'inspect', '--format', '{{index .Config.Labels "io.x-k8s.kind.cluster"}}', f'{cluster}-control-plane']).strip()
    if label != cluster:
        raise ValueError('Control-plane ownership does not match')
    context = f'kind-{cluster}'
    view = json.loads(execute(['kubectl', '--kubeconfig', str(path), 'config', 'view', '--minify', '--context', context, '-o', 'json']))
    server = view['clusters'][0]['cluster']['server']
    match = re.fullmatch(r'https://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})', server)
    if not match or not 1 <= int(match.group(1)) <= 65535:
        raise ValueError('Kubernetes API must bind to local loopback')
    bindings = json.loads(execute(['docker', 'inspect', '--format', '{{json (index .NetworkSettings.Ports "6443/tcp")}}', f'{cluster}-control-plane']))
    endpoint = urlsplit(server)
    if not isinstance(bindings, list) or not any(
        isinstance(binding, dict) and binding.get('HostIp') == endpoint.hostname
        and binding.get('HostPort') == str(endpoint.port) for binding in bindings
    ):
        raise ValueError('Kubeconfig API does not match the owned control-plane port')
    namespace = json.loads(execute(['kubectl', '--kubeconfig', str(path), '--context', context,
                                    'get', 'namespace', cluster, '-o', 'json']))
    if namespace['metadata'].get('name') != cluster or namespace['metadata'].get('labels', {}).get(OWNER_LABEL) != cluster:
        raise ValueError('Namespace ownership does not match')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cluster', required=True)
    parser.add_argument('--kubeconfig', required=True)
    args = parser.parse_args()
    try:
        validate_target(args.cluster, args.kubeconfig)
    except (ValueError, RuntimeError, OSError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Preflight refused the target: {type(exc).__name__}\n')
    print('Owned local cluster and namespace verified. No deployment or fault test was performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
