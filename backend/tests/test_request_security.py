import asyncio

import pytest

from services.request_security import RequestSecurityMiddleware


def _request(headers=(), parts=(b"ok",), path="/upload", auth=True, limit=10):
    called = []
    sent = []
    received = []

    async def app(scope, receive, send):
        called.append(True)
        data = bytearray()
        while True:
            event = await receive()
            data.extend(event["body"])
            if not event.get("more_body"):
                break
        received.append(bytes(data))
        await send({"type": "http.response.start", "status": 200, "headers": []})

    messages = iter([{"type": "http.request", "body": part, "more_body": index < len(parts) - 1}
                     for index, part in enumerate(parts)])

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    middleware = RequestSecurityMiddleware(app, ["http://localhost:5173"], auth, upload_limit=limit)
    asyncio.run(middleware({"type": "http", "method": "POST", "path": path, "headers": list(headers)}, receive, send))
    return sent[0]["status"], called, received


@pytest.mark.parametrize("origin", [b"http://localhost:7777", b"https://evil.test", b"null"])
def test_untrusted_origin_rejected_before_processing(origin):
    status, called, _ = _request([(b"origin", origin), (b"x-csrf-protection", b"nexus-v1")])
    assert status == 403
    assert not called


def test_trusted_origin_requires_custom_csrf_header():
    assert _request([(b"origin", b"http://localhost:5173")])[0] == 403
    assert _request([(b"origin", b"http://localhost:5173"), (b"x-csrf-protection", b"nexus-v1")])[0] == 200


def test_cookie_without_origin_cannot_bypass_protection():
    assert _request([(b"cookie", b"nexus.session_token=opaque")], auth=False)[0] == 403
    assert _request(auth=True)[0] == 403
    assert _request(auth=False)[0] == 200  # Explicit anonymous development CLI only.


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"2")], [(b"transfer-encoding", b"chunked")]])
def test_actual_stream_limit_before_downstream_parser(headers):
    status, called, _ = _request(headers + [(b"x-csrf-protection", b"nexus-v1")], parts=(b"123456", b"78901"))
    assert status == 413
    assert not called


def test_declared_limit_rejects_without_reading_body():
    status, called, _ = _request([(b"content-length", b"11"), (b"x-csrf-protection", b"nexus-v1")], parts=())
    assert status == 413
    assert not called


def test_valid_body_replayed_exactly():
    assert _request([(b"x-csrf-protection", b"nexus-v1")], parts=(b"12345", b"67890")) == (200, [True], [b"1234567890"])


def test_n8n_key_authenticated_ingress_is_not_cookie_csrf_route():
    assert _request(path="/integrations/n8n/documents")[0] == 200
    assert _request(path="/integrations/n8n/documents", headers=[(b"origin", b"https://evil.test")])[0] == 403


def test_sixteen_observers_do_not_starve_n8n_callback_intake():
    async def scenario():
        release,started,half_started=asyncio.Event(),asyncio.Event(),asyncio.Event()
        observed=[]
        async def app(scope,receive,send):
            await receive()
            if scope['path'].startswith('/documents/'):
                observed.append(scope['path'])
                if len(observed)==8:half_started.set()
                if len(observed)==16:started.set()
                await release.wait()
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b''})
        guard=RequestSecurityMiddleware(app,[],False)
        async def request(path):
            sent=[]
            async def receive():return {'type':'http.request','body':b'','more_body':False}
            async def send(message):sent.append(message)
            await guard({'type':'http','method':'POST','path':path,'headers':[]},receive,send)
            return sent[0]['status']
        tasks=[asyncio.create_task(request('/documents/synthetic.pdf/intelligence/stream')) for _ in range(8)]
        try:
            await asyncio.wait_for(half_started.wait(),2)
            tasks.extend(asyncio.create_task(request('/documents/synthetic.pdf/intelligence/stream')) for _ in range(8))
            await asyncio.wait_for(started.wait(),2)
            assert await request('/documents/another.pdf/intelligence/run')==429
            assert await request('/integrations/n8n/cases/document-dna')==200
        finally:
            release.set()
            await asyncio.gather(*tasks)
        assert guard.intakes._value==8 and guard.observers._value==16
    asyncio.run(scenario())


def test_trusted_browser_can_read_a_guard_error_through_cors():
    import main
    from fastapi.testclient import TestClient
    origin = main.allowed_origins[0]
    response = TestClient(main.app).post("/upload", headers={"Origin": origin}, content=b"not parsed")
    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["cache-control"] == "no-store"
