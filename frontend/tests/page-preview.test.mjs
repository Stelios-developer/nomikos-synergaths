import assert from 'node:assert/strict'
import test from 'node:test'
import { pagePreviewRequest } from '../src/api/pagePreview.ts'

test('preview sends sensitive excerpt in the body instead of the URL', () => {
  const excerpt = 'PRIVATE synthetic excerpt & details'
  const { url, init } = pagePreviewRequest('/api', 'case one.pdf', 2, excerpt)
  assert.equal(url, '/api/documents/case%20one.pdf/page')
  assert.equal(init.method, 'POST')
  assert.deepEqual(JSON.parse(init.body), { page: 2, snippet: excerpt })
  assert.ok(!url.includes('PRIVATE'))
})
