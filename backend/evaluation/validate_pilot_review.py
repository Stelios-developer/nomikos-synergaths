"""Validate a human review's structure against the synthetic pilot; never grade it."""
import argparse
import hashlib
import json
from pathlib import Path

from pilot_manifest import validate_manifest

FIELDS = ('owner', 'approver', 'deadline')


def strict_json(raw):
    """Reject ambiguous duplicate keys and non-JSON numeric constants."""
    def object_without_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError('Invalid JSON numeric constant')

    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=object_without_duplicates,
                      parse_constant=invalid_constant)


def validate_review(review, manifest, manifest_digest):
    if (not isinstance(review, dict) or set(review) != {'reviewer', 'manifest_sha256', 'documents'}
            or not isinstance(review.get('reviewer'), str)
            or not review['reviewer'].strip() or len(review['reviewer']) > 100):
        raise ValueError('A reviewer identifier is required')
    if review.get('manifest_sha256') != manifest_digest:
        raise ValueError('Review does not match the exact manifest')
    cases = review.get('documents')
    if not isinstance(cases, list):
        raise ValueError('Review documents must be a list')
    expected = {entry['id'] for entry in manifest['documents']}
    seen = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {'id', 'fields'}
                or case.get('id') not in expected or case['id'] in seen):
            raise ValueError('Unknown or duplicate document')
        seen.add(case['id'])
        fields = case.get('fields')
        if not isinstance(fields, dict) or set(fields) != set(FIELDS):
            raise ValueError('Every document requires exactly the defined fields')
        for field in FIELDS:
            item = fields[field]
            if not isinstance(item, dict) or item.get('status') not in ('present', 'absent', 'uncertain'):
                raise ValueError('Invalid annotation status')
            if item['status'] == 'present':
                if (set(item) != {'status', 'value', 'quote', 'page'}
                        or not isinstance(item.get('value'), str) or not item['value'].strip() or len(item['value']) > 300
                        or not isinstance(item.get('quote'), str) or not item['quote'].strip() or len(item['quote']) > 500
                        or type(item.get('page')) is not int or item['page'] not in (1, 2)):
                    raise ValueError('Present annotations require value, quote and valid page')
            elif item['status'] == 'absent':
                pages = item.get('reviewed_pages')
                if (set(item) != {'status', 'reviewed_pages'} or pages != [1, 2]
                        or any(type(page) is not int for page in pages)):
                    raise ValueError('Absence requires review of both pages')
            elif (set(item) != {'status', 'reason'} or not isinstance(item.get('reason'), str)
                  or not item['reason'].strip() or len(item['reason']) > 500):
                raise ValueError('Uncertainty requires a bounded reason')
    if seen != expected:
        raise ValueError('Review must cover each synthetic document exactly once')
    return len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    try:
        directory = args.corpus.resolve(strict=True)
        raw_manifest = (directory / 'manifest.json').read_bytes()
        manifest = strict_json(raw_manifest)
        if not validate_manifest(directory, manifest):
            raise ValueError('Legacy corpus without verified PDF hashes cannot be used for a frozen review')
        raw_review = args.review.read_bytes()
        review = strict_json(raw_review)
        digest = hashlib.sha256(raw_manifest).hexdigest()
        count = validate_review(review, manifest, digest)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Review validation failed: {type(exc).__name__}\n')
    print(json.dumps({'documents': count, 'manifest_sha256': digest,
                      'review_sha256': hashlib.sha256(raw_review).hexdigest(),
                      'limits': ['reviewer independence is not verified', 'annotations and quotes are not checked for correctness',
                                 'synthetic development corpus only; no holdout, OCR, retrieval or model evaluation']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
