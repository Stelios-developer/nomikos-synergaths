import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { filename, documentCase, session } from '../tests/fixtures/workspace.mjs'
import recorded from './recorded-ai-answers.json' with { type: 'json' }

// A separate, loopback-only demo server. Unknown APIs fail closed; no proxies,
// uploads, persistent data, real sessions or provider requests are permitted.
function syntheticDemo() {
  return {
    name: 'synthetic-demo',
    transformIndexHtml(html) {
      return html.replace('</body>', `<div role="status" style="position:fixed;right:12px;bottom:12px;z-index:9999;padding:10px 14px;border:1px solid #79d6b5;border-radius:12px;background:#102921;color:#fff;font:600 12px system-ui;box-shadow:0 4px 20px #0008">DEMO · Synthetic data · Recorded AI answers</div></body>`)
    },
    configureServer(server) {
      server.middlewares.use('/api', (req, res) => {
        const path = new URL(req.url, 'http://localhost').pathname
        const json = (data, status = 200) => {
          res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
          res.end(JSON.stringify(data))
        }
        if (req.method === 'GET' && path === '/auth/get-session') return json(session)
        if (req.method === 'GET' && path === '/documents') return json([{ filename, chunk_count: 24, method: 'pymupdf', upload_date: '2026-10-01' }])
        if (req.method === 'GET' && path === '/analysis/jobs') return json([])
        if (req.method === 'GET' && path.endsWith('/intelligence')) return json(documentCase)
        if (req.method === 'GET' && path.endsWith('/page')) {
          res.writeHead(200, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'no-store' })
          return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="40" y="70" font-size="22" fill="black">Synthetic source preview</text><text x="40" y="120" font-size="16" fill="black">First release: 15 October 2026</text></svg>')
        }
        if (req.method === 'POST' && path === '/query') {
          let body = ''
          req.setEncoding('utf8')
          req.on('data', chunk => { body += chunk; if (body.length > 16384) req.destroy() })
          req.on('end', () => {
            let question
            try { question = JSON.parse(body).question } catch { return json({ detail: 'Invalid request' }, 400) }
            const answer = recorded.answers.find(item => item.question === question)
            if (!answer) return json({ detail: 'Demo has two recorded questions. Select Deadlines or Risks & approvals.' }, 400)
            const citations = documentCase.citations.map(c => ({ filename, page: c.page, text: c.excerpt }))
            res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' })
            const events = [
              { type: 'token', content: 'Recorded AI answer from synthetic excerpts (not a live response):\n\n' + answer.answer },
              { type: 'done', citations, eval: null },
            ]
            res.end(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''))
          })
          return
        }
        if (req.method === 'POST' && path === '/audit/run') return json({ detail: 'No live verification in this demo.' }, 503)
        return json({ detail: 'Unavailable in the synthetic demo. No real data or AI is processed.' }, 403)
      })
    },
  }
}

export default defineConfig({
  plugins: [syntheticDemo(), react(), tailwindcss()],
  define: { 'import.meta.env.VITE_DEMO_MODE': JSON.stringify('true') },
  server: { host: '127.0.0.1', port: 5198, strictPort: true },
})
