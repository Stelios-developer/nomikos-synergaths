"""Private fake integration endpoints for a disposable n8n workflow test."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlsplit, parse_qs

EXPECTED = ['start', 'document-dna', 'facts', 'risks', 'draft-action-pack', 'audit', 'finalize']
seen = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code); self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        self.respond(200, {'seen': seen})

    def do_POST(self):
        if self.headers.get('X-N8N-API-Key') != 'synthetic-only-key' or self.headers.get('X-Workspace-ID') != 'synthetic-workspace':
            self.respond(403, {'error': 'denied'}); return
        prefix = '/integrations/n8n/cases/'
        parsed = urlsplit(self.path)
        operation = parsed.path.removeprefix(prefix) if parsed.path.startswith(prefix) else ''
        if len(seen) >= len(EXPECTED) or operation != EXPECTED[len(seen)]:
            self.respond(409, {'error': 'unexpected stage'}); return
        if operation == 'finalize' and parse_qs(parsed.query) != {'fixture_branch': ['review']}:
            self.respond(409, {'error': 'unexpected audit branch'}); return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('invalid size')
            body = json.loads(self.rfile.read(size))
            if operation == 'start':
                assert body.get('filename') == 'synthetic.pdf'
            else:
                assert body.get('case_id') == 'synthetic-case'
        except (ValueError, AssertionError, TypeError):
            self.respond(400, {'error': 'invalid fixture'}); return
        seen.append(operation)
        self.respond(200, {'case_id': 'synthetic-case', 'workspace_id': 'synthetic-workspace',
                           'audit': {'passed': False}, 'status': 'needs_human_review'})


ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
