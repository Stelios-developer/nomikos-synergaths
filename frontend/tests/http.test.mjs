import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, requestJson, streamEvents } from '../src/api/http.ts'

const response = (text, init) => new Response(text, init)
const options = (res) => ({ fetchImpl: async () => res, timeoutMs: 1000 })

test('cookies and CSRF are preserved; no mutation is retried', async () => {
  let calls = 0
  await requestJson('/test', { method: 'POST', body: '{}' }, { fetchImpl: async (_url, init) => {
    calls++
    assert.equal(init.credentials, 'include')
    assert.equal(init.headers.get('X-CSRF-Protection'), 'nexus-v1')
    return response('{}')
  } })
  assert.equal(calls, 1)
})
test('structured problem errors preserve code, request ID and retry hint', async () => {
  await assert.rejects(requestJson('/test', {}, options(response(JSON.stringify({ detail: 'Unavailable', code: 'DEPENDENCY_UNAVAILABLE' }), {
    status: 503, headers: { 'X-Request-ID': 'request-123', 'Retry-After': '3' },
  }))), (error) => error instanceof ApiError && error.status === 503 && error.code === 'DEPENDENCY_UNAVAILABLE' && error.requestId === 'request-123' && error.retryAfter === '3')
})
test('a pre-aborted request sends nothing', async () => {
  const controller = new AbortController()
  controller.abort()
  let calls = 0
  await assert.rejects(requestJson('/test', {}, { signal: controller.signal, fetchImpl: async () => { calls++; return response('{}') } }), { name: 'AbortError' })
  assert.equal(calls, 0)
})
test('total deadline covers a stalled response body', async () => {
  const body = new ReadableStream({ start() {} })
  await assert.rejects(requestJson('/test', {}, { ...options(response(body)), timeoutMs: 15 }), (e) => e.code === 'TIMEOUT' && !e.uncertain)
})
test('mutation timeout warns of an uncertain outcome and never retries', async () => {
  let calls = 0
  await assert.rejects(requestJson('/test', { method: 'POST' }, {
    timeoutMs: 15, fetchImpl: () => { calls++; return new Promise(() => {}) },
  }), (e) => e.code === 'TIMEOUT' && e.uncertain && e.message.includes('refresh'))
  assert.equal(calls, 1)
})
test('network loss during a mutation does not pretend the write failed safely', async () => {
  await assert.rejects(requestJson('/test', { method: 'DELETE' }, {
    fetchImpl: async () => { throw new TypeError('network') },
  }), (e) => e.code === 'NETWORK' && e.uncertain)
})
test('204 is a successful empty response, not a JSON error', async () => {
  assert.equal(await requestJson('/test', {}, options(response(null, { status: 204 }))), undefined)
})

test('null or malformed error bodies preserve the actual HTTP error', async () => {
  for (const body of ['null', '<html>unavailable</html>']) {
    await assert.rejects(requestJson('/test', {}, options(response(body, { status: 503 }))),
      (error) => error instanceof ApiError && error.status === 503 && error.code === 'HTTP_503')
  }
})

test('invalid successful JSON is a protocol failure with an uncertain write outcome', async () => {
  await assert.rejects(requestJson('/test', { method: 'POST' }, options(response('not-json'))),
    (error) => error.code === 'INVALID_RESPONSE' && error.uncertain)
})
test('SSE accepts comments, CRLF, multiline JSON and split Greek UTF-8', async () => {
  const bytes = new TextEncoder().encode(': heartbeat\r\n\r\ndata: {"type":"token",\r\ndata: "content":"Καλημέρα"}\r\n\r\ndata: {"type":"done"}\r\n\r\n')
  const events = []
  const body = new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i++) controller.enqueue(bytes.slice(i, i + 1))
    controller.close()
  } })
  await streamEvents('/test', {}, (event) => events.push(event), options(response(body)))
  assert.deepEqual(events, [{ type: 'token', content: 'Καλημέρα' }, { type: 'done' }])
})
test('SSE completion does not wait for a server that leaves the connection open', async () => {
  let cancelled = false
  const body = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n')) }, cancel() { cancelled = true } })
  await streamEvents('/test', {}, () => {}, options(response(body)))
  assert.equal(cancelled, true)
})
test('a truncated stream cannot masquerade as a successful analysis', async () => {
  await assert.rejects(streamEvents('/test', {}, () => {}, options(response('data: {"type":"token","content":"partial"}\n\n'))), (e) => e.code === 'INCOMPLETE_STREAM')
})
test('malformed stream data fails closed', async () => {
  await assert.rejects(streamEvents('/test', {}, () => {}, options(response('data: not-json\n\n'))), (e) => e.code === 'INVALID_STREAM')
})
test('oversized unfinished frames are bounded', async () => {
  await assert.rejects(streamEvents('/test', {}, () => {}, options(response('data: ' + 'a'.repeat(1_048_577)))), (e) => e.code === 'INVALID_STREAM')
})
test('an analysis error event never becomes a done result', async () => {
  await assert.rejects(streamEvents('/test', {}, () => {}, options(response('data: {"type":"error","message":"Audit failed"}\n\n'))), (e) => e.code === 'ANALYSIS_FAILED')
})

test('uncertain workflow delivery preserves its status instead of encouraging a replay', async () => {
  await assert.rejects(streamEvents('/test', {}, () => {}, options(response('data: {"type":"error","message":"Check saved progress","code":"ANALYSIS_UNCERTAIN","uncertain":true}\n\n'))),
    (error) => error.code === 'ANALYSIS_UNCERTAIN' && error.uncertain)
})
test('stream timeout cancels its reader', async () => {
  let cancelled = false
  const body = new ReadableStream({ cancel() { cancelled = true } })
  await assert.rejects(streamEvents('/test', {}, () => {}, { ...options(response(body)), timeoutMs: 15 }), (e) => e.code === 'TIMEOUT')
  assert.equal(cancelled, true)
})
