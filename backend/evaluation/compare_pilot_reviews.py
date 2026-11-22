"""Compare two completed synthetic pilot reviews without adjudicating them."""
import argparse
import hashlib
import json
from pathlib import Path

from pilot_manifest import validate_manifest
from validate_pilot_review import FIELDS, strict_json, validate_review


def compare(first, second):
    if first['reviewer'].strip().casefold() == second['reviewer'].strip().casefold():
        raise ValueError('Two distinct reviewer identifiers are required')
    other = {row['id']: row for row in second['documents']}
    differences = []
    for document in first['documents']:
        peer = other[document['id']]
        for field in FIELDS:
            if document['fields'][field] != peer['fields'][field]:
                differences.append({'id': document['id'], 'field': field,
                                    'status_differs': document['fields'][field]['status'] != peer['fields'][field]['status']})
    return {'documents': len(first['documents']), 'fields_compared': len(first['documents']) * len(FIELDS),
            'disagreements': differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    args = parser.parse_args()
    try:
        directory = args.corpus.resolve(strict=True)
        manifest_bytes = (directory / 'manifest.json').read_bytes()
        manifest = strict_json(manifest_bytes)
        if not validate_manifest(directory, manifest):
            raise ValueError('Pilot PDF hashes must be complete')
        digest = hashlib.sha256(manifest_bytes).hexdigest()
        raw_reviews = [args.first.read_bytes(), args.second.read_bytes()]
        reviews = [strict_json(raw) for raw in raw_reviews]
        for review in reviews:
            validate_review(review, manifest, digest)
        result = compare(*reviews)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Cannot compare pilot reviews: {type(exc).__name__}\n')
    result.update({'manifest_sha256': digest,
                   'review_sha256': [hashlib.sha256(raw).hexdigest() for raw in raw_reviews],
                   'limits': ['identifiers do not prove independence', 'agreement does not prove accuracy',
                              'disagreements require human adjudication', 'synthetic development corpus, not a holdout']})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
