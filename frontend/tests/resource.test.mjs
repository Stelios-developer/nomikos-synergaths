import assert from 'node:assert/strict'
import test from 'node:test'
import { Resource } from '../src/api/resource.ts'

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

test('an empty successful list is distinguishable from a failed initial load', async () => {
  const empty = new Resource(async () => [])
  await empty.load()
  assert.equal(empty.getSnapshot().status, 'success')
  assert.deepEqual(empty.getSnapshot().data, [])
  const failed = new Resource(async () => { throw new Error('offline') })
  await failed.load()
  assert.equal(failed.getSnapshot().status, 'error')
  assert.equal(failed.getSnapshot().data, null)
})
test('failed refresh preserves the last good snapshot with an explicit error', async () => {
  let fail = false
  const resource = new Resource(async () => { if (fail) throw new Error('offline'); return ['source.pdf'] })
  await resource.load()
  const updated = resource.getSnapshot().updatedAt
  fail = true
  await resource.load()
  assert.equal(resource.getSnapshot().status, 'error')
  assert.deepEqual(resource.getSnapshot().data, ['source.pdf'])
  assert.equal(resource.getSnapshot().updatedAt, updated)
})
for (const status of [401, 403, 404]) test(`${status} discards protected cached data`, async () => {
  let fail = false
  const resource = new Resource(async () => { if (fail) throw Object.assign(new Error('denied'), { status }); return ['private.pdf'] })
  await resource.load(); fail = true; await resource.load()
  assert.equal(resource.getSnapshot().data, null)
  assert.equal(resource.getSnapshot().updatedAt, null)
})
test('late responses from a cleared session are ignored even if fetch ignores abort', async () => {
  const request = deferred()
  const resource = new Resource(() => request.promise)
  const loading = resource.load()
  resource.clear()
  request.resolve(['old-account.pdf'])
  await loading
  assert.equal(resource.getSnapshot().status, 'idle')
  assert.equal(resource.getSnapshot().data, null)
})
test('a stale response cannot overwrite a newer refresh', async () => {
  const first = deferred(), second = deferred()
  let calls = 0
  const resource = new Resource(() => (++calls === 1 ? first.promise : second.promise))
  const old = resource.load(), fresh = resource.load()
  second.resolve(['new.pdf']); await fresh
  first.resolve(['old.pdf']); await old
  assert.deepEqual(resource.getSnapshot().data, ['new.pdf'])
})
test('successful retry removes the error state', async () => {
  let fail = true
  const resource = new Resource(async () => { if (fail) throw new Error('offline'); return ['ok.pdf'] })
  await resource.load(); fail = false; await resource.load()
  assert.equal(resource.getSnapshot().status, 'success')
  assert.equal(resource.getSnapshot().error, null)
})
