import assert from 'node:assert/strict'
import test from 'node:test'
import { waitForSignedOutSession } from '../src/auth/session-transition.ts'

function fixture(initial) {
  let snapshot = initial
  const listeners = new Set()
  return {
    get: () => snapshot,
    listen: (fn) => { listeners.add(fn); return () => listeners.delete(fn) },
    emit: (value) => { snapshot = value; for (const fn of listeners) fn(value) },
    listeners,
  }
}

test('sign-out waits for session refresh and unsubscribes', async () => {
  const store = fixture({ data: { user: 'synthetic' }, isPending: false, isRefetching: false })
  let finished = false
  const waiting = waitForSignedOutSession(store, 1000).then(() => { finished = true })
  store.emit({ data: { user: 'synthetic' }, isPending: false, isRefetching: true })
  await Promise.resolve()
  assert.equal(finished, false)
  store.emit({ data: null, isPending: false, isRefetching: false })
  await waiting
  assert.equal(store.listeners.size, 0)
})

test('sign-out continues if session refresh never completes', async () => {
  const store = fixture({ data: { user: 'synthetic' }, isPending: false, isRefetching: false })
  await waitForSignedOutSession(store, 10)
  assert.equal(store.listeners.size, 0)
})

test('an already cleared session does not wait', async () => {
  const store = fixture({ data: null, isPending: false, isRefetching: false })
  await waitForSignedOutSession(store, 1000)
  assert.equal(store.listeners.size, 0)
})

test('a failed session observer cannot block logout', async () => {
  await waitForSignedOutSession({ get: () => { throw new Error('unavailable') }, listen: () => { throw new Error('unavailable') } }, 1000)
})
