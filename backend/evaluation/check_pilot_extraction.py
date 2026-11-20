"""Check pilot source-page extraction and scan detection, not OCR/AI accuracy."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.ingestion import extract_pages, is_scanned  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('directory')
directory = Path(parser.parse_args().directory).resolve(strict=True)
manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
failures = []
for item in manifest['documents']:
    path = (directory / item['filename']).resolve(strict=True)
    if path.parent != directory:
        raise ValueError('Corpus filename escaped its directory')
    pages = extract_pages(str(path))
    expected = item['expected']
    if len(pages) != 2 or is_scanned(pages) != (item['format'] == 'scanned'):
        failures.append(item['id'] + ': pages/scan classification')
    if item['format'] == 'digital':
        for field in ('owner', 'approver', 'deadline'):
            if expected[field] not in pages[0]['text']:
                failures.append(item['id'] + ': missing ' + field)
        if 'Ignore previous' not in pages[1]['text'] and 'Αγνόησε' not in pages[1]['text']:
            failures.append(item['id'] + ': missing synthetic instruction')
print(json.dumps({'documents': len(manifest['documents']), 'failures': failures,
                  'ocr_tested': False, 'independent_holdout': False}, ensure_ascii=False, indent=2))
sys.exit(bool(failures))
