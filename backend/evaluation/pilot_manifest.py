"""Validate pilot corpus inventory and optional PDF integrity before evaluation."""
import hashlib
import re
from pathlib import Path


def validate_manifest(directory: Path, manifest: object) -> bool:
    """Return whether all PDFs have verified hashes; legacy manifests lack them."""
    if not isinstance(manifest, dict) or manifest.get('version') != 'pilot-1':
        raise ValueError('Unsupported pilot manifest')
    documents = manifest.get('documents')
    if not isinstance(documents, list) or len(documents) != 30:
        raise ValueError('Pilot must contain exactly 30 documents')
    ids, names, hash_count, scanned = set(), set(), 0, 0
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError('Invalid document entry')
        identifier, filename = item.get('id'), item.get('filename')
        if not isinstance(identifier, str) or not re.fullmatch(r'pilot-(?:0[1-9]|[12][0-9]|30)', identifier):
            raise ValueError('Invalid document ID')
        if filename != identifier + '.pdf' or identifier in ids or filename in names:
            raise ValueError('Duplicate or invalid document filename')
        ids.add(identifier); names.add(filename)
        if item.get('format') not in ('digital', 'scanned') or item.get('language') not in ('el', 'en') or item.get('split') != 'development_only':
            raise ValueError('Invalid document metadata')
        scanned += item['format'] == 'scanned'
        expected = item.get('expected')
        if not isinstance(expected, dict) or any(not isinstance(expected.get(k), str) or not expected[k].strip() for k in ('owner', 'approver', 'deadline')):
            raise ValueError('Missing expected facts')
        if (type(expected.get('page')) is not int or expected['page'] != 1
                or type(expected.get('untrusted_instruction_page')) is not int or expected['untrusted_instruction_page'] != 2
                or 'budget' not in expected or expected['budget'] is not None):
            raise ValueError('Invalid page or absence labels')
        path = directory / filename
        if path.is_symlink() or not path.is_file() or path.resolve().parent != directory.resolve():
            raise ValueError('Missing or unsafe document path')
        claimed = item.get('sha256')
        if claimed is not None:
            if not isinstance(claimed, str) or not re.fullmatch(r'[0-9a-f]{64}', claimed):
                raise ValueError('Invalid PDF digest')
            with path.open('rb') as source:
                actual = hashlib.file_digest(source, 'sha256').hexdigest()
            if actual != claimed:
                raise ValueError('PDF digest mismatch')
            hash_count += 1
    if scanned != 6 or hash_count not in (0, 30):
        raise ValueError('Unexpected scan count or incomplete digest inventory')
    return hash_count == 30
