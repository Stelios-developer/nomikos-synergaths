from fastapi.testclient import TestClient

import main


def test_private_page_preview_body_and_legacy_route(sample_pdf_factory, fake_embeddings):
    client = TestClient(main.app)
    path = sample_pdf_factory(num_pages=1)
    with open(path, 'rb') as source:
        uploaded = client.post('/upload', files={'file': ('private.pdf', source, 'application/pdf')},
                               headers={'X-Session-ID': 'owner'})
    assert uploaded.status_code == 200
    body = {'page': 1, 'snippet': 'sample text about tax technology'}
    owner = client.post('/documents/private.pdf/page', json=body, headers={'X-Session-ID': 'owner'})
    assert owner.status_code == 200 and owner.content.startswith(b'\x89PNG\r\n\x1a\n')
    assert owner.headers['cache-control'] == 'no-store'
    other = client.post('/documents/private.pdf/page', json=body, headers={'X-Session-ID': 'other'})
    assert other.status_code == 404
    legacy = client.get('/documents/private.pdf/page', params=body, headers={'X-Session-ID': 'owner'})
    assert legacy.status_code == 200 and legacy.headers['cache-control'] == 'no-store'


def test_preview_rejects_oversized_or_extra_fields_without_echoing_content():
    client = TestClient(main.app)
    private_text = 'PRIVATE-SYNTHETIC-' * 300
    response = client.post('/documents/private.pdf/page', json={'page': 1, 'snippet': private_text})
    assert response.status_code == 422 and private_text not in response.text
    assert client.post('/documents/private.pdf/page', json={'page': 1, 'unexpected': True}).status_code == 422
