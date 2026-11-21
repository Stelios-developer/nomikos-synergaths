"""Use the backend's actual transport against a synthetic, internal n8n."""
import json
import time
import urllib.error
import urllib.request

from services.n8n_orchestrator import trigger_case_workflow

stage = 'missing_header'
try:
    url = 'http://n8n:5678/webhook/nexus-agent-orchestrator/case'
    request = urllib.request.Request(url, data=b'{"filename":"synthetic.pdf","workspace_id":"synthetic-workspace"}',
                                     headers={'Content-Type': 'application/json'}, method='POST')
    for attempt in range(30):
        try:
            urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                break
            if exc.code == 404 and attempt < 29:
                time.sleep(1); continue
            print(f'diagnostic: missing_header HTTP{exc.code}', flush=True)
            raise SystemExit(1)
        else:
            raise AssertionError('Missing integration header was accepted')
    stage = 'invalid_header'
    invalid = urllib.request.Request(url, data=b'{"filename":"synthetic.pdf","workspace_id":"synthetic-workspace"}',
                                     headers={'Content-Type': 'application/json', 'X-N8N-API-Key': 'invalid-synthetic-key'}, method='POST')
    try:
        urllib.request.urlopen(invalid, timeout=20)
    except urllib.error.HTTPError as exc:
        assert exc.code in (403, 500)
    else:
        raise AssertionError('Invalid integration header was accepted')
    with urllib.request.urlopen('http://mock-backend:8000/seen', timeout=5) as response:
        assert json.load(response)['seen'] == []
    stage = 'transport'
    trigger_case_workflow('synthetic.pdf', 'synthetic-workspace', timeout_seconds=60)
    stage = 'stages'
    with urllib.request.urlopen('http://mock-backend:8000/seen', timeout=5) as response:
        seen = json.load(response)['seen']
    assert seen == ['start', 'document-dna', 'facts', 'risks', 'draft-action-pack', 'audit', 'finalize']
except Exception as exc:
    print(f'diagnostic: {stage} {type(exc).__name__}', flush=True)
    raise SystemExit(1)
print('Real backend transport and local n8n workflow reached the synthetic human-review path.')
