"""Verify hashes and declared check status in a local release evidence bundle.

This does not verify signatures, provenance, image contents, test semantics or
whether a report truthfully belongs to the stated commit.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate manifest key')
        result[key] = value
    return result


def verify(bundle, manifest, required_checks):
    root = bundle.resolve(strict=True)
    if not root.is_dir() or not isinstance(manifest, dict):
        raise ValueError('Invalid bundle or manifest')
    if set(manifest) != {'commit', 'artifacts', 'checks'} or not isinstance(manifest['commit'], str) or not re.fullmatch(r'[0-9a-f]{40,64}', manifest['commit']):
        raise ValueError('Invalid commit or manifest fields')
    if not isinstance(manifest['artifacts'], list) or not manifest['artifacts']:
        raise ValueError('At least one artifact is required')
    paths, exact_paths, verified = set(), set(), {}
    for item in manifest['artifacts']:
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise ValueError('Invalid artifact')
        name, digest = item['path'], item['sha256']
        if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                or str(PurePosixPath(name)) != name or PurePosixPath(name).is_absolute()
                or any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('Unsafe artifact path')
        if name.casefold() in paths:
            raise ValueError('Duplicate artifact path')
        paths.add(name.casefold())
        exact_paths.add(name)
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid artifact digest')
        candidate = root
        for part in name.split('/'):
            candidate = candidate / part
            if candidate.is_symlink():
                raise ValueError('Symlink artifacts are not allowed')
        if not candidate.is_file() or not candidate.resolve(strict=True).is_relative_to(root):
            raise ValueError('Artifact missing or outside bundle')
        with candidate.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                raise ValueError('Artifact digest mismatch')
        verified[name] = (candidate, digest)
    checks = manifest['checks']
    if not isinstance(checks, list) or not checks:
        raise ValueError('At least one check is required')
    if (not isinstance(required_checks, (list, tuple)) or not required_checks
            or any(not isinstance(name, str) or not re.fullmatch(r'[a-z0-9_-]{1,80}', name) for name in required_checks)
            or len(set(required_checks)) != len(required_checks)):
        raise ValueError('A unique nonempty required check list is required')
    names = set()
    for check in checks:
        if (not isinstance(check, dict) or set(check) != {'id', 'status', 'artifact'}
                or not isinstance(check['id'], str) or not re.fullmatch(r'[a-z0-9_-]{1,80}', check['id'])
                or check['id'] in names or check['status'] not in ('passed', 'failed', 'skipped')
                or not isinstance(check['artifact'], str) or check['artifact'] not in exact_paths):
            raise ValueError('Invalid check')
        names.add(check['id'])
        # The caller's declaration cannot turn a failed or different-commit
        # JSON report into a passing check. This still cannot prove authenticity.
        report_path, digest = verified[check['artifact']]
        with report_path.open('rb') as source:
            raw = source.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Check report changed or exceeds size limit')
        report = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
        if (not isinstance(report, dict) or report.get('commit') != manifest['commit']
                or report.get('result') not in ('passed', 'passed_with_skips', 'failed', 'skipped', 'incomplete', 'setup_failed')):
            raise ValueError('Invalid check report commit or result')
        if check['status'] == 'passed' and report['result'] != 'passed':
            raise ValueError('Passing declaration contradicts report')
    missing = sorted(set(required_checks) - names)
    return {'commit': manifest['commit'], 'artifacts_verified': len(paths), 'checks': len(checks),
            'missing_required_checks': missing,
            'result': 'passed' if not missing and all(item['status'] == 'passed' for item in checks) else 'incomplete',
            'limits': ['checks report commit and result fields only', 'no signature or provenance verification',
                       'does not prove report authenticity, image identity, or test semantics']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--require-check', action='append', required=True,
                        help='required check identifier; repeat for each check')
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)
        result = verify(args.bundle, manifest, args.require_check)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f'Bundle verification failed: {type(exc).__name__}\n')
    print(json.dumps(result, indent=2))
    return 0 if result['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
