"""Exercise authenticated ASGI upload with isolated database and real PDF worker.

No browser, n8n or real embedding/model provider is involved. Test cookies are
read from stdin and must never be printed.
"""
import json
import sys

import fitz
from fastapi.testclient import TestClient

import main
import services.ingestion as ingestion

users = json.load(sys.stdin)['users']
assert len(users) == 2
ingestion.embed_texts = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]

with fitz.open() as document:
    page = document.new_page()
    for index in range(8):
        page.insert_text((55, 75 + index * 25), 'SYNTHETIC LEGAL DOCUMENT. A REVIEW IS REQUIRED.', fontsize=13)
    content = document.tobytes()

headers = lambda user: {'cookie': user['cookie'], 'origin': 'http://localhost:5173',
                        'x-csrf-protection': 'nexus-v1'}
mode = sys.argv[1] if len(sys.argv) > 1 else 'ready'
assert mode in ('ready', 'scanner_down')
name = 'isolated-upload.pdf' if mode == 'ready' else 'unavailable-upload.pdf'
with TestClient(main.app) as client:
    result = client.post('/upload', headers=headers(users[0]), files={'file': (name, content, 'application/pdf')})
    if mode == 'scanner_down':
        assert result.status_code == 503, f'outage status {result.status_code}'
        listing = client.get('/documents', headers=headers(users[0]))
        assert listing.status_code == 200
        assert name not in [row['filename'] for row in listing.json()]
        print('Authenticated upload refused scanner outage without publishing a document.')
        raise SystemExit(0)
    assert result.status_code == 200, f'upload status {result.status_code}'
    first = client.get('/documents', headers=headers(users[0]))
    second = client.get('/documents', headers=headers(users[1]))
    assert first.status_code == second.status_code == 200
    assert name in [row['filename'] for row in first.json()]
    assert name not in [row['filename'] for row in second.json()]
    assert client.get(f'/documents/{name}/page?page=1', headers=headers(users[0])).status_code == 200
    assert client.get(f'/documents/{name}/page?page=1', headers=headers(users[1])).status_code == 404
    assert client.delete(f'/documents/{name}', headers=headers(users[1])).status_code == 404
    assert client.get(f'/documents/{name}/page?page=1', headers=headers(users[0])).status_code == 200

print('Authenticated ASGI upload, OCR, scoped listing and page access passed with synthetic embeddings.')
