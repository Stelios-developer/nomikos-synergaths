"""Exercise real synthetic Better Auth cookies against backend auth and scoped vectors."""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.requests import Request
from db.vector_store import PgVectorStore, VectorSettings
from services.authentication import _cookie_token, start_auth_pool, close_auth_pool, require_authenticated_user

data = json.load(sys.stdin)


async def check():
    app = SimpleNamespace(state=SimpleNamespace())
    await start_auth_pool(app)
    try:
        if data['phase'] == 'expired_first':
            request = Request({'type': 'http', 'method': 'GET', 'path': '/',
                               'headers': [(b'cookie', data['users'][0]['cookie'].encode())], 'app': app})
            token = _cookie_token(request)
            assert token
            async with app.state.auth_db_pool.acquire() as conn:
                result = await conn.execute('UPDATE "session" SET "expiresAt" = NOW() - INTERVAL \'1 minute\' WHERE token = $1', token)
                assert result == 'UPDATE 1'
        for index, user in enumerate(data['users']):
            async def resolve(cookie):
                request = Request({'type': 'http', 'method': 'GET', 'path': '/',
                                   'headers': [(b'cookie', cookie.encode()),
                                               (b'x-workspace-id', b'untrusted-forged-workspace')], 'app': app})
                return await require_authenticated_user(request)
            try:
                actual = await resolve(user['cookie'])
            except HTTPException as exc:
                assert (data['phase'] == 'revoked' or (data['phase'] == 'expired_first' and index == 0)) and exc.status_code == 401
            else:
                assert (data['phase'] == 'active' or (data['phase'] == 'expired_first' and index == 1)) and actual.id == user['id']
            if data['phase'] == 'active':
                altered = '; '.join(part + 'x' if '.session_token=' in part else part
                                    for part in user['cookie'].split('; '))
                assert altered != user['cookie']
                try:
                    await resolve(altered)
                except HTTPException as exc:
                    assert exc.status_code == 401
                else:
                    raise AssertionError('Tampered cookie was accepted')
        if data['phase'] == 'active':
            store = PgVectorStore(VectorSettings(os.environ['DMC_TEST_VECTOR_URL'], 3, 'synthetic-integration'))
            try:
                store.verify()
                a, b = (user['id'] for user in data['users'])
                for owner, text in ((a, 'Synthetic Alice document'), (b, 'Synthetic Bob document')):
                    store.add(workspace_id=owner, ids=['fixture'], documents=[text],
                              metadatas=[{'session_id': owner, 'filename': 'synthetic.pdf'}], embeddings=[[1, 0, 0]])
                assert store.get(workspace_id=a)['documents'] == ['Synthetic Alice document']
                assert store.get(workspace_id=b)['documents'] == ['Synthetic Bob document']
            finally:
                store.close()
    finally:
        await close_auth_pool(app)


asyncio.run(check())
print('Synthetic auth and scope assertions passed.')
