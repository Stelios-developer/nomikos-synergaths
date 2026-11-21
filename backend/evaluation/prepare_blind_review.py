"""Create an unlabelled review packet for an existing synthetic pilot corpus.

The reviewer must inspect the supplied PDFs independently. This does not create
labels, prove reviewer independence, or turn development documents into holdout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from pilot_manifest import validate_manifest

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ('owner', 'approver', 'deadline')


def prepare(corpus: Path, destination: Path, output_root: Path):
    source = corpus.resolve(strict=True)
    root = output_root.resolve(strict=True)
    if destination.is_symlink() or not destination.resolve().is_relative_to(root) or destination.resolve() == root:
        raise ValueError('Review packet must be a new directory inside the designated output root')
    raw = (source / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if not validate_manifest(source, manifest):
        raise ValueError('Review requires a fully hash-verified pilot corpus')
    digest = hashlib.sha256(raw).hexdigest()
    documents = [{'id': item['id'], 'filename': item['filename'], 'sha256': item['sha256'],
                  'format': item['format'], 'language': item['language']} for item in manifest['documents']]
    template = {'reviewer': '', 'manifest_sha256': digest,
                'documents': [{'id': item['id'], 'fields': {field: None for field in FIELDS}} for item in documents]}
    destination.mkdir(parents=False, exist_ok=False)
    pdfs = destination / 'pdfs'; pdfs.mkdir()
    for item in documents:
        target = pdfs / item['filename']
        shutil.copyfile(source / item['filename'], target)
        with target.open('rb') as copied:
            if hashlib.file_digest(copied, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Copied PDF differs from the verified manifest; discard the incomplete packet')
    (destination / 'documents.json').write_text(json.dumps({'documents': documents}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'review-template.json').write_text(json.dumps(template, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return len(documents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True, help='new directory inside output/')
    args = parser.parse_args()
    try:
        count = prepare(args.corpus, args.destination, ROOT / 'output')
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Cannot prepare review: {type(exc).__name__}\n')
    print(f'Prepared {count} unlabelled document entries. Human review and independence remain unverified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
