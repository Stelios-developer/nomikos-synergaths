import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL('../' + path, import.meta.url), 'utf8')
const brand = 'NOMIKOS SYNERGATHS'

test('public page metadata uses NOMIKOS SYNERGATHS', () => {
  const html = read('index.html')
  assert.ok(html.includes('<title>' + brand + ' — Document Intelligence</title>'))
  assert.ok(html.includes('name="application-name" content="' + brand + '"'))
  assert.ok(html.includes('content="' + brand + ' — understand your PDFs'))
})

test('shared product identity is used across workspace, authentication and assistant', () => {
  assert.ok(read('src/brand.ts').includes("export const BRAND_NAME = '" + brand + "'"))
  for (const path of [
    'src/App.tsx',
    'src/components/auth/AuthGate.tsx',
    'src/components/intelligence/ChatInterface.tsx',
    'src/components/intelligence/DocumentIntelligencePanel.tsx',
  ]) {
    const source = read(path)
    assert.ok(source.includes('BRAND_NAME'), path + ' uses the shared brand')
    assert.doesNotMatch(source, /nexus/i, path + ' has no old branding or layout names')
  }
})

test('brand layout and logo use coordinated names', () => {
  assert.match(read('src/components/ui/Icon.tsx'), /export function DocumentMark/)
  assert.doesNotMatch(read('src/styles/workspace.css'), /nexus/i)
  assert.match(read('src/styles/workspace.css'), /\.dmc-topbar\s*\{/)
})

test('rebranding preserves the existing CSRF integration contract', () => {
  assert.match(read('src/api/http.ts'), /headers\.set\('X-CSRF-Protection', 'nexus-v1'\)/)
})
